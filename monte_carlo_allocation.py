"""
Monte Carlo surplus optimisation for the UChicago Fixed Income Competition (Fall 2026).

Fund: $100M city pension, pays no tax, draws $6M/yr (paid monthly), horizon Oct-2026 -> Oct-2031.
Liabilities: 30 years of level $6M/yr benefit payments, valued off the simulated Treasury curve.

Pipeline
  1. Market data   - Bloomberg 1y history of UST 1/2/3/5/7/10/20/30 yields and ICE BofA
                     C0A0 (US Corp), C8R0 (15+yr telecom), U0A0 (US Muni) total-return indices.
  2. Credit model  - Moody's "Corporate Default and Recovery Rates, 1920-2008":
                     * Exhibit 36 annual default rates by rating -> 2-state Markov-switching
                       model of the spec-grade default rate (benign / stress credit regimes)
                     * Exhibit 26 sr. unsecured recoveries vs. spec-grade default rate
                       -> recovery regression (Moody's Exhibit 9 reports y = 0.588 - 3.03x)
                     * current regime probability from the Treasury curve slope
                       (Estrella-Mishkin / NY Fed recession probit)
  3. Simulation    - monthly Treasury curve shocks (empirical covariance), regime-dependent
                     drift, regime-linked spread moves, default losses by rating.
  4. Grid search   - every gov/muni/corp weight combination (and gov tenor / corp index
                     choice); rank by surplus Sharpe; check the competition rules.
"""
import os
import re
import sys
import warnings

import numpy as np
import pandas as pd
from scipy.stats import norm

warnings.filterwarnings("ignore")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA_XLSX = os.path.join(ROOT, "fixed income data.xlsx")
MOODYS_PDF = os.path.join(ROOT, "default_and_recovery_rates_02_09.pdf")
OUT_DIR = os.path.join(HERE, "output")

# --------------------------------------------------------------------------------------
# Assumptions.  Index yields / spreads are NOT in the Bloomberg pull (px_last only), so they
# are inputs here.  Replace with Bloomberg INDEX yield-to-worst / OAS / mod. duration fields
# for C0A0, C8R0, U0A0 on the pricing date.
# --------------------------------------------------------------------------------------
SEED = 2026
N_PATHS = 5000
YEARS = 5
MONTHS = 12 * YEARS
ASSETS0 = 100.0            # $M
PAYMENT = 6.0              # $M per year
LIAB_YEARS = 30
LIAB_SPREAD = 0.0          # liability discount = Treasury curve + this spread

TENORS = np.array([1, 2, 3, 5, 7, 10, 20, 30], dtype=float)
GOVT_CHOICES = [1, 2, 5, 10, 30]    # 1y = T-bills / cash

SLEEVES = {
    # mod_dur: modified duration at the pricing date (used for the 4-6y rule)
    # match:   Treasury tenors the sleeve's base yield is taken from
    # spread:  OAS (for muni: spread added on top of ratio * UST)
    # spread_beta: spread change per unit change in the spec-grade default rate
    #              (Moody's Exh. 12: HY spread ~ 1:1 with spec-grade default rate; IG ~0.2x HY)
    # mix:     rating mix used for default losses
    "CORP":  dict(name="IG Corporate (C0A0)", mod_dur=6.6, match=[7, 10], spread=0.0090,
                  spread_beta=0.20, mix={"Aaa": .02, "Aa": .08, "A": .42, "Baa": .48}),
    "TEL15": dict(name="15+yr Telecom (C8R0)", mod_dur=13.0, match=[20, 30], spread=0.0150,
                  spread_beta=0.25, mix={"A": .15, "Baa": .85}),
    "MUNI":  dict(name="Municipal (U0A0)", mod_dur=6.2, match=[7, 10], spread=0.0,
                  spread_beta=0.06, mix=None),
}
MUNI_RATIO = 0.76          # tax-exempt muni yield / Treasury yield (fund pays no tax!)
MUNI_PD = {"benign": 0.0001, "stress": 0.0005}   # Moody's muni study ballpark (not in the PDF)
MUNI_RECOVERY = 0.60

# Treasury drift in a stress (default-cycle) year, per year, by tenor: bull steepener as the
# Fed cuts.  Benign years: zero drift (yields are a martingale).
STRESS_DRIFT = np.interp(TENORS, [1, 10, 30], [-0.0125, -0.0070, -0.0050])
FIT_START = 1970          # HMM sample: modern spec-grade market (1942-69 had ~zero defaults,
                          # which a 2-state model on 1920-2008 picks up as a structural break)
SPREAD_AR = 0.90           # monthly AR(1) persistence of idiosyncratic spread noise
GOV_CAP = 0.15
DUR_RANGE = (4.0, 6.0)


# --------------------------------------------------------------------------------------
# 1. Market data
# --------------------------------------------------------------------------------------
def load_market():
    x = pd.read_excel(DATA_XLSX, header=None)
    cols = ["date"] + [f"UST{int(t)}" for t in TENORS] + ["CORP", "TEL15", "MUNI"]
    d = x.iloc[2:].copy()
    d.columns = cols
    d["date"] = pd.to_datetime(d["date"].astype(float), unit="D", origin="1899-12-30")
    d = d.set_index("date").astype(float)
    return d[d.diff().abs().sum(axis=1) > 0]       # drop holiday / weekend fill rows


def market_diagnostics(d):
    """Empirical rate betas of each index (weekly + monthly), used to set rate sensitivities."""
    rows = []
    for freq in ["W-FRI", "ME"]:
        w = d.resample(freq).last()
        ret = np.log(w[["CORP", "TEL15", "MUNI"]]).diff().dropna()
        dy = w.filter(like="UST").diff().dropna() / 100
        for s, cfg in SLEEVES.items():
            x = dy[[f"UST{t}" for t in cfg["match"]]].mean(axis=1)
            X = np.c_[np.ones(len(x)), x]
            b, *_ = np.linalg.lstsq(X, ret[s], rcond=None)
            resid = ret[s] - X @ b
            per_yr = 52 if freq == "W-FRI" else 12
            rows.append(dict(sleeve=s, freq=freq, emp_dur=-b[1],
                             resid_vol_ann=resid.std() * np.sqrt(per_yr)))
    diag = pd.DataFrame(rows)
    agg = diag.groupby("sleeve").agg(emp_dur=("emp_dur", "mean"),
                                     resid_vol_ann=("resid_vol_ann", "mean"))
    return diag, agg


# --------------------------------------------------------------------------------------
# 2. Moody's data and credit regime model
# --------------------------------------------------------------------------------------
RATINGS = ["Aaa", "Aa", "A", "Baa", "Ba", "B", "CaaC", "IG", "SG", "All"]


def pdf_text(path):
    from pypdf import PdfReader
    return "\n".join((p.extract_text() or "") for p in PdfReader(path).pages)


def parse_exhibit36(text):
    """Annual issuer-weighted default rates by letter rating, 1920-2008 (two years per line)."""
    seg = text[text.index("Exhibit 36"):text.index("Exhibit 37")]
    recs = {}
    for line in seg.splitlines():
        tok = line.split()
        if not tok or not re.fullmatch(r"19[2-6]\d", tok[0]):
            continue
        # split the line at the second year token
        idx = [i for i, t in enumerate(tok) if re.fullmatch(r"(19[6-9]\d|200\d)", t) and i > 0]
        halves = [tok[:idx[0]], tok[idx[0]:]] if idx else [tok]
        for h in halves:
            yr, vals = int(h[0]), [float(v) for v in h[1:]]
            if len(vals) == 9:      # 1920 has no Caa-C entry
                vals = vals[:6] + [np.nan] + vals[6:]
            recs[yr] = vals
    df = pd.DataFrame.from_dict(recs, orient="index", columns=RATINGS).sort_index() / 100
    assert df.index.min() == 1920 and df.index.max() == 2008 and len(df) == 89, df.index
    return df


def parse_exhibit26(text):
    """Sr. unsecured bond recovery rates (30-day post-default prices), 1982-2008."""
    seg = text[text.index("Exhibit 26"):text.index("Exhibit 27")]
    out = {}
    for line in seg.splitlines():
        tok = line.split()
        if tok and re.fullmatch(r"(198[2-9]|199\d|200\d)", tok[0]):
            # columns: loan sr sec, bond sr sec, sr unsec, sr sub, sub, jr sub, all bonds
            # "n.a." occupies a column, so positional indexing is safe
            vals = tok[1:]
            out[int(tok[0])] = float(vals[2].rstrip("%")) / 100
    s = pd.Series(out).sort_index()
    assert len(s) == 27
    return s


def fit_credit_regimes(dr):
    """2-state Gaussian hidden Markov model (Baum-Welch EM) on log spec-grade default rate.
    State 0 = benign, state 1 = stress (higher mean)."""
    y = np.log(dr["SG"].values + 0.001)
    T = len(y)
    mu = np.percentile(y, [30, 85])
    sd = np.array([y.std(), y.std()]) * 0.6
    P = np.array([[0.85, 0.15], [0.35, 0.65]])
    pi = np.array([0.7, 0.3])
    for _ in range(500):
        B = norm.pdf(y[:, None], mu, sd)                          # (T, 2)
        a = np.zeros((T, 2)); c = np.zeros(T)
        a[0] = pi * B[0]; c[0] = a[0].sum(); a[0] /= c[0]
        for t in range(1, T):
            a[t] = (a[t - 1] @ P) * B[t]; c[t] = a[t].sum(); a[t] /= c[t]
        b = np.ones((T, 2))
        for t in range(T - 2, -1, -1):
            b[t] = (P @ (B[t + 1] * b[t + 1])) / c[t + 1]
        g = a * b
        xi = (a[:-1, :, None] * P[None] * (B[1:] * b[1:])[:, None, :]) / c[1:, None, None]
        P_new = xi.sum(0) / xi.sum((0, 2))[:, None]
        mu_new = (g * y[:, None]).sum(0) / g.sum(0)
        sd_new = np.sqrt((g * (y[:, None] - mu_new) ** 2).sum(0) / g.sum(0))
        done = np.abs(P_new - P).max() < 1e-9 and np.abs(mu_new - mu).max() < 1e-9
        P, mu, sd, pi = P_new, mu_new, np.maximum(sd_new, 0.05), g[0]
        if done:
            break
    if mu[0] > mu[1]:                                             # enforce state order
        P, mu, sd, g = P[::-1, ::-1], mu[::-1], sd[::-1], g[:, ::-1]
    w = pd.DataFrame({"benign": g[:, 0], "stress": g[:, 1]}, index=dr.index)
    cond = pd.DataFrame({r: [(w[r] * dr[c]).sum() / w[r][dr[c].notna()].sum() for c in RATINGS]
                         for r in ["benign", "stress"]}, index=RATINGS)
    return dict(P=P, weights=w, cond=cond, mu=mu, sd=sd, loglik=np.log(c).sum())


def fit_recovery(dr, rec):
    x = dr.loc[rec.index, "SG"].values
    X = np.c_[np.ones_like(x), x]
    b, *_ = np.linalg.lstsq(X, rec.values, rcond=None)
    resid = rec.values - X @ b
    r2 = 1 - resid.var() / rec.values.var()
    return dict(a=b[0], b=b[1], sigma=resid.std(ddof=2), r2=r2)


def current_regime_prob(curve):
    """NY Fed / Estrella-Mishkin probit: Pr(recession in 12m) = N(-0.5333 - 0.6330 * (10y - 3m)).
    The pull has no 3m bill, so the 1y bill is used as the short rate."""
    term = curve["UST10"] - curve["UST1"]
    return float(norm.cdf(-0.5333 - 0.6330 * term)), term


# --------------------------------------------------------------------------------------
# 3. Simulation
# --------------------------------------------------------------------------------------
def par_duration_convexity(y, n):
    """Modified duration and convexity of a semi-annual par bond with n years to maturity."""
    y = np.maximum(y, 1e-6)
    h = y / 2
    m = 2 * n
    D = (1 - (1 + h) ** (-m)) / y
    # numerical convexity
    def price(yy):
        hh = yy / 2
        return h * (1 - (1 + hh) ** (-m)) / hh + (1 + hh) ** (-m)
    e = 1e-4
    C = (price(y + e) + price(y - e) - 2 * price(y)) / e ** 2
    return D, C


def zero_curve(par):
    """Approximate continuously-compounded zero rates from par yields (par ~ zero for this use)."""
    return 2 * np.log1p(par / 2)


def simulate(d, credit, recov, p_stress0, agg, rng):
    N, M = N_PATHS, MONTHS
    y0 = d.filter(like="UST").iloc[-1].values / 100
    w = d.resample("W-FRI").last().filter(like="UST").diff().dropna() / 100
    cov_m = np.cov(w.values.T) * 52 / 12
    Lc = np.linalg.cholesky(cov_m + 1e-12 * np.eye(len(TENORS)))

    # --- regime paths (one draw per year) ---
    P = credit["P"]
    reg = np.zeros((N, YEARS), dtype=int)
    reg[:, 0] = rng.random(N) < p_stress0
    for t in range(1, YEARS):
        p_s = np.where(reg[:, t - 1] == 1, P[1, 1], P[0, 1])
        reg[:, t] = rng.random(N) < p_s

    # --- default/recovery draws: bootstrap a Moody's year from the matching regime ---
    dr = credit["dr"].fillna(credit["dr"]["CaaC"].mean())
    wts = credit["weights"]
    pools = {k: (wts[name] / wts[name].sum()).values for k, name in [(0, "benign"), (1, "stress")]}
    years_idx = np.zeros((N, YEARS), dtype=int)
    for k in (0, 1):
        mask = reg == k
        years_idx[mask] = rng.choice(len(dr), size=mask.sum(), p=pools[k])
    DR = {r: dr[r].values[years_idx] for r in RATINGS}           # (N, YEARS)
    RR = np.clip(recov["a"] + recov["b"] * DR["SG"] + recov["sigma"] * rng.standard_normal((N, YEARS)),
                 0.05, 0.95)
    sg_ref = credit["cond"].loc["SG", "benign"]

    # --- Treasury curve paths ---
    Y = np.zeros((N, M + 1, len(TENORS)))
    Y[:, 0] = y0
    reg_m = np.repeat(reg, 12, axis=1)                            # (N, M)
    for t in range(M):
        shock = rng.standard_normal((N, len(TENORS))) @ Lc.T
        drift = np.where(reg_m[:, t:t + 1] == 1, STRESS_DRIFT / 12, 0.0)
        drift = drift - drift.mean(axis=0)        # no net rate view: stress years rally, benign drift up
        Y[:, t + 1] = np.maximum(Y[:, t] + drift + shock, 0.0005)
    dY = np.diff(Y, axis=1)

    R = {}
    # --- government sleeves: constant-maturity par bonds rolled monthly ---
    for g in GOVT_CHOICES:
        j = list(TENORS).index(g)
        yt, dyt = Y[:, :-1, j], dY[:, :, j]
        D, C = par_duration_convexity(yt, g)
        R[f"UST{g}"] = yt / 12 - D * dyt + 0.5 * C * dyt ** 2

    # --- credit sleeves ---
    loss_ann = {}
    for s, cfg in SLEEVES.items():
        j = [list(TENORS).index(t) for t in cfg["match"]]
        base = Y[:, :, j].mean(axis=2)                            # (N, M+1)
        beta = agg.loc[s, "emp_dur"] / cfg["mod_dur"]             # empirical rate beta
        if s == "MUNI":
            beta = min(beta, 1.0)
        spr_vol_m = agg.loc[s, "resid_vol_ann"] / cfg["mod_dur"] / np.sqrt(12)
        # spread = base + regime-linked level + AR(1) noise
        noise = np.zeros((N, M + 1))
        for t in range(M):
            noise[:, t + 1] = SPREAD_AR * noise[:, t] + spr_vol_m * rng.standard_normal(N)
        sg_m = np.repeat(DR["SG"], 12, axis=1)
        level = cfg["spread_beta"] * (sg_m - sg_ref)
        spread = np.empty((N, M + 1))
        spread[:, 0] = cfg["spread"]
        spread[:, 1:] = np.maximum(cfg["spread"] + level + noise[:, 1:], -0.02 if s == "MUNI" else 0.0005)

        if s == "MUNI":
            yld = MUNI_RATIO * base + spread
            pd_ann = np.where(reg == 1, MUNI_PD["stress"], MUNI_PD["benign"])
            loss = pd_ann * (1 - MUNI_RECOVERY)
        else:
            yld = base + spread
            loss = sum(wgt * DR[r] for r, wgt in cfg["mix"].items()) * (1 - RR)
        loss_ann[s] = loss
        d_rate = beta * np.diff(base, axis=1)     # beta embeds muni ratio / IG spread-rate correlation
        d_spr = np.diff(spread, axis=1)
        dtot = d_rate + d_spr
        D = cfg["mod_dur"]
        C = D ** 2 * 1.1                                          # convexity approximation
        R[s] = yld[:, :-1] / 12 - D * dtot + 0.5 * C * dtot ** 2 - np.repeat(loss, 12, axis=1) / 12

    # --- liabilities: remaining level monthly payments, discounted on the Treasury curve ---
    pay_m = PAYMENT / 12
    L = np.zeros((N, M + 1))
    for t in range(M + 1):
        n_left = LIAB_YEARS * 12 - t
        tau = np.arange(1, n_left + 1) / 12.0                     # years to each payment
        # vectorised linear interpolation across paths
        zc = zero_curve(Y[:, t]) + LIAB_SPREAD                    # (N, 8)
        k = np.clip(np.searchsorted(TENORS, tau) - 1, 0, len(TENORS) - 2)
        t0, t1 = TENORS[k], TENORS[k + 1]
        wgt = np.clip((tau - t0) / (t1 - t0), 0, 1)
        zi = zc[:, k] * (1 - wgt) + zc[:, k + 1] * wgt
        zi = np.where(tau < TENORS[0], zc[:, :1], zi)
        L[:, t] = pay_m * np.exp(-zi * tau).sum(axis=1)
    RL = (L[:, 1:] + pay_m) / L[:, :-1] - 1

    return dict(R=R, L=L, RL=RL, Y=Y, reg=reg, DR=DR, RR=RR, loss=loss_ann, y0=y0)


# --------------------------------------------------------------------------------------
# 4. Allocation grid
# --------------------------------------------------------------------------------------
def sleeve_yield0(key, y0):
    if key.startswith("UST"):
        return y0[list(TENORS).index(int(key[3:]))]
    cfg = SLEEVES[key]
    base = np.mean([y0[list(TENORS).index(t)] for t in cfg["match"]])
    return MUNI_RATIO * base + cfg["spread"] if key == "MUNI" else base + cfg["spread"]


def sleeve_dur0(key, y0):
    if key.startswith("UST"):
        g = int(key[3:])
        return float(par_duration_convexity(y0[list(TENORS).index(g)], g)[0])
    return SLEEVES[key]["mod_dur"]


def evaluate(sim, gkey, ckey, step):
    R, L, RL = sim["R"], sim["L"], sim["RL"]
    pay_m = PAYMENT / 12
    grid = [(g, m, 100 - g - m) for g in range(0, 101, step) for m in range(0, 101 - g, step)]
    W = np.array(grid, dtype=float) / 100                         # (K, 3) gov, muni, corp
    Rg, Rm, Rc = R[gkey], R["MUNI"], R[ckey]
    y0 = sim["y0"]
    yld = np.array([sleeve_yield0(k, y0) for k in (gkey, "MUNI", ckey)])
    dur = np.array([sleeve_dur0(k, y0) for k in (gkey, "MUNI", ckey)])
    exp_loss = np.array([0.0, sim["loss"]["MUNI"].mean(), sim["loss"][ckey].mean()])
    rows = []
    for (wg, wm, wc) in W:
        rA = wg * Rg + wm * Rm + wc * Rc                          # (N, M)
        A = np.empty((rA.shape[0], MONTHS + 1))
        A[:, 0] = ASSETS0
        for t in range(MONTHS):
            A[:, t + 1] = np.maximum(A[:, t] * (1 + rA[:, t]) - pay_m, 0.0)
        FS = A / L
        rS = rA - (L[:, :-1] / np.maximum(A[:, :-1], 1e-9)) * RL   # surplus return per $ of assets
        dFS = np.diff(FS, axis=1)
        ann_ret = (np.prod(1 + rA, axis=1) ** (1 / YEARS) - 1)
        rows.append(dict(
            govt=wg, muni=wm, corp=wc, govt_sleeve=gkey, corp_sleeve=ckey,
            yield0=float(yld @ [wg, wm, wc]),
            exp_default_loss=float(exp_loss @ [wg, wm, wc]),
            mod_duration=float(dur @ [wg, wm, wc]),
            exp_return_ann=float(ann_ret.mean()),
            surplus_ret_ann=float(rS.mean() * 12),
            surplus_vol_ann=float(rS.std() * np.sqrt(12)),
            surplus_sharpe=float(rS.mean() * 12 / (rS.std() * np.sqrt(12))),
            fs_start=float(FS[:, 0].mean()),
            fs_end_mean=float(FS[:, -1].mean()),
            fs_end_median=float(np.median(FS[:, -1])),
            fs_end_p5=float(np.percentile(FS[:, -1], 5)),
            fs_end_p95=float(np.percentile(FS[:, -1], 95)),
            fs_vol_ann=float(dFS.std() * np.sqrt(12)),
            fs_end_std=float(FS[:, -1].std()),
            prob_underfunded_end=float((FS[:, -1] < 1).mean()),
        ))
    df = pd.DataFrame(rows)
    df["gov_ok"] = df["govt"] <= GOV_CAP + 1e-9
    df["dur_ok"] = df["mod_duration"].between(*DUR_RANGE)
    df["feasible"] = df["gov_ok"] & df["dur_ok"]
    return df


def credit_projection(sim, credit, recov):
    """Expected default and recovery rates by year in the current regime."""
    reg, DR, RR = sim["reg"], sim["DR"], sim["RR"]
    out = []
    for y in range(YEARS):
        row = {"year": 2027 + y, "P(stress)": reg[:, y].mean()}
        for r in ["Aaa", "Aa", "A", "Baa", "Ba", "B", "CaaC", "IG", "SG"]:
            row[r] = DR[r][:, y].mean()
        row["recovery"] = RR[:, y].mean()
        for s in SLEEVES:
            row[f"loss_{s}"] = sim["loss"][s][:, y].mean()
        out.append(row)
    return pd.DataFrame(out)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    rng = np.random.default_rng(SEED)
    pd.set_option("display.width", 200)
    pd.set_option("display.max_columns", 40)

    d = load_market()
    curve = d.iloc[-1]
    print(f"Pricing date: {d.index[-1].date()}  (Bloomberg, last obs)")
    print("Treasury curve (%):", curve.filter(like="UST").round(3).to_dict())
    diag, agg = market_diagnostics(d)
    print("\nEmpirical rate sensitivity of ICE indices vs matched Treasuries:\n", agg.round(3))

    text = pdf_text(MOODYS_PDF)
    dr = parse_exhibit36(text)
    rec = parse_exhibit26(text)
    credit = fit_credit_regimes(dr.loc[FIT_START:])
    credit["dr"] = dr.loc[FIT_START:]
    recov = fit_recovery(dr, rec)
    print(f"\nRecovery regression (1982-2008): RR = {recov['a']:.4f} {recov['b']:+.4f} x SG_DR "
          f"(R2={recov['r2']:.3f}, resid sd={recov['sigma']:.3f}); Moody's Exh. 9: 0.5877 - 3.0265x")
    P = credit["P"]
    stat = P[0, 1] / (P[0, 1] + P[1, 0])
    print("\nCredit regime transition matrix [benign, stress]:\n", np.round(P, 3),
          f"\nstationary P(stress)={stat:.3f}; expected stress spell={1/(1-P[1,1]):.1f}y")
    print(f"Regime-conditional annual default rates (Moody's {FIT_START}-2008, %):\n",
          (credit["cond"] * 100).round(3))
    stress_years = credit["weights"].index[credit["weights"]["stress"] > 0.5].tolist()
    print("Years classified as stress:", stress_years)

    p0, term = current_regime_prob(curve)
    print(f"\n10y-1y term spread = {term:.2f}%  ->  Pr(stress regime next 12m) = {p0:.3f}")

    sim = simulate(d, credit, recov, p0, agg, rng)
    L0 = sim["L"][:, 0].mean()
    print(f"\nLiability PV (30y x $6M, Treasury curve) = ${L0:.2f}M; "
          f"starting funded status = {ASSETS0 / L0:.3f}")

    proj = credit_projection(sim, credit, recov)
    print("\nPredicted default / recovery rates, current regime (annual, %):")
    print((proj.set_index("year") * pd.Series(
        {c: (1 if c == "P(stress)" else 100) for c in proj.columns if c != "year"})).round(3))
    proj.to_csv(os.path.join(OUT_DIR, "credit_projection.csv"), index=False)

    # coarse search over sleeve choices, then fine grid for the best two
    coarse = pd.concat([evaluate(sim, f"UST{g}", c, 5) for g in GOVT_CHOICES for c in ["CORP", "TEL15"]])
    coarse.to_csv(os.path.join(OUT_DIR, "grid_coarse_5pct.csv"), index=False)
    top = (coarse[coarse.feasible].sort_values("surplus_sharpe", ascending=False)
           .drop_duplicates(["govt_sleeve", "corp_sleeve"]).head(2))
    fine = pd.concat([evaluate(sim, r.govt_sleeve, r.corp_sleeve, 1) for r in top.itertuples()])
    fine.to_csv(os.path.join(OUT_DIR, "grid_fine_1pct.csv"), index=False)

    show = ["govt_sleeve", "corp_sleeve", "govt", "muni", "corp", "yield0", "exp_default_loss",
            "mod_duration", "exp_return_ann", "surplus_ret_ann", "surplus_vol_ann", "surplus_sharpe",
            "fs_start", "fs_end_mean", "fs_end_p5", "fs_vol_ann", "prob_underfunded_end"]
    print("\nBest feasible per sleeve choice (5% grid):")
    print(coarse[coarse.feasible].sort_values("surplus_sharpe", ascending=False)
          .drop_duplicates(["govt_sleeve", "corp_sleeve"])[show].round(4).to_string(index=False))
    print("\nBest unconstrained (5% grid):")
    print(coarse.sort_values("surplus_sharpe", ascending=False)[show].head(5).round(4).to_string(index=False))
    best = fine[fine.feasible].sort_values("surplus_sharpe", ascending=False)
    print("\nTop feasible allocations (1% grid):")
    print(best[show].head(10).round(4).to_string(index=False))
    best.head(1).T.to_csv(os.path.join(OUT_DIR, "best_allocation.csv"))
    return dict(d=d, credit=credit, recov=recov, sim=sim, proj=proj, coarse=coarse, fine=fine, p0=p0)


if __name__ == "__main__":
    main()
