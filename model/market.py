"""What the market is pricing on the pricing date: policy path, forward Treasury yields, breakeven
inflation and CDX-implied default rates, plus a macro dashboard that cross-checks the regime probability."""
import numpy as np
import pandas as pd

from . import config as C

FF = [1, 2, 3, 4, 6, 12]      # fed funds futures: FFn settles on the average effective rate of month n
SFR = [1, 2, 3, 4, 8]         # 3m SOFR futures: SFRn is the n-th quarterly contract


def policy_path(d):
    """Implied rates (100 - price) by approximate months ahead.  FF1 is the current month; SFRn's
    3-month reference quarter is centred about 3(n-1) months ahead (SFR1 is already in its quarter)."""
    last = d.iloc[-1]
    rows = [("Fed funds target (upper bound)", 0, last["FED_UPPER"])]
    rows += [(f"FF{n} (fed funds, month {n})", n - 1, last[f"FF{n}_RATE"]) for n in FF]
    rows += [(f"SFR{n} (3m SOFR, quarter {n})", 3 * (n - 1), last[f"SFR{n}_RATE"]) for n in SFR]
    return pd.DataFrame(rows, columns=["instrument", "months_ahead", "rate_pct"])


def discount_curve(y0):
    """Bootstrap semi-annual discount factors from the par curve (linear in maturity between tenors;
    bills are treated as par yields).  Returns maturities 0.5..40 and their discount factors."""
    mats = np.arange(1, 81) / 2
    par = np.interp(mats, C.TENORS, y0)
    P = np.empty_like(mats)
    for i, c in enumerate(par):
        P[i] = (1 - c / 2 * P[:i].sum()) / (1 + c / 2)
    return mats, P


def forward_par(y0, start, length):
    """Par yield of a `length`-year bond starting `start` years from now, implied by today's curve."""
    mats, P = discount_curve(y0)
    i0, i1 = int(round(start * 2)) - 1, int(round((start + length) * 2)) - 1
    return 2 * (P[i0] - P[i1]) / P[i0 + 1:i1 + 1].sum()


def breakevens(d):
    """Nominal minus TIPS real yield, and the 5y5y forward breakeven (simple-rate approximation)."""
    last = d.iloc[-1]
    be = {t: last[f"UST{t}"] - last[f"TIPS{t}"] for t in ("5", "10", "30")}
    be["5y5y"] = 2 * be["10"] - be["5"]
    return be


def _rpv01(hazard, r, years=5.0):
    """Risky annuity of a CDS with quarterly premiums, flat hazard rate and flat discount rate."""
    t = np.arange(1, int(years * 4) + 1) / 4
    return (0.25 * np.exp(-np.multiply.outer(np.asarray(r) + np.asarray(hazard), t))).sum(axis=-1)


def cdx_spreads(d):
    """CDX IG is quoted as a spread (bp); CDX HY as a price with a 500bp coupon.  The HY par spread s
    solves price = 100 + (coupon - s) * RPV01(hazard = s / (1 - R)), by fixed-point iteration."""
    x = d[["CDX_IG", "CDX_HY_PX", "UST5"]].dropna()
    r, px, R = x["UST5"].values / 100, x["CDX_HY_PX"].values, C.CDX_RECOVERY["HY"]
    s = np.full(len(x), 0.05)
    for _ in range(50):
        s = 0.05 - (px - 100) / 100 / _rpv01(s / (1 - R), r)
    return pd.DataFrame({"IG": x["CDX_IG"].values / 1e4, "HY": s}, index=x.index)


def implied_defaults(spreads, model_dr):
    """Credit triangle: risk-neutral default intensity = spread / (1 - recovery).  model_dr gives the
    model's (real-world) 5-year average default rates for IG and spec-grade."""
    last = spreads.iloc[-1]
    rows = []
    for k, lab in (("IG", "IG"), ("HY", "SG")):
        lam = last[k] / (1 - C.CDX_RECOVERY[k])
        rows.append(dict(index=f"CDX {k} 5y", spread_bp=last[k] * 1e4, recovery=C.CDX_RECOVERY[k],
                         implied_default=lam, model_default=model_dr[lab], ratio=lam / model_dr[lab]))
    return pd.DataFrame(rows)


def ig_hy_beta(spreads):
    """Weekly change in CDX IG spread per unit change in CDX HY spread (2011-2026), and the IG spread
    sensitivity to the spec-grade default rate it implies through Moody's Exh. 12 text (HY spreads of
    ~1,000bp at spec-grade default peaks of ~10-12%, i.e. ~0.9bp of spread per bp of default rate)."""
    w = spreads.resample("W-FRI").last().diff().dropna()
    beta = np.polyfit(w["HY"], w["IG"], 1)[0]
    return beta, beta * 0.10 / 0.11


def forecast_2031(d, y0, sim):
    """Market-implied (forwards and breakevens) vs the model's simulated distribution for Oct 2031."""
    be = breakevens(d)
    Y = sim["Y"][:, -1, :]
    i2, i10, i3m = (list(C.TENOR_LABELS).index(l) for l in ("2", "10", "3m"))
    rows = [("Policy-rate proxy (3m bill)", y0[i3m], forward_par(y0, 5, 0.5), Y[:, i3m]),
            ("2y Treasury", y0[i2], forward_par(y0, 5, 2), Y[:, i2]),
            ("10y Treasury", y0[i10], forward_par(y0, 5, 10), Y[:, i10])]
    out = [dict(item=n, today=t, market_implied=f, model_mean=s.mean(), model_p5=np.percentile(s, 5),
                model_p95=np.percentile(s, 95)) for n, t, f, s in rows]
    out.append(dict(item="CPI inflation (5y5y breakeven)", today=d["CPI_YOY"].iloc[-1] / 100,
                    market_implied=be["5y5y"] / 100, model_mean=np.nan, model_p5=np.nan, model_p95=np.nan))
    return pd.DataFrame(out)


def macro_dashboard(d, spreads):
    """Latest value of each macro and market series and its percentile in its own 2006-2026 monthly
    history.  The Sahm indicator is the 3-month average unemployment rate minus its low over the prior
    12 months (a reading of 0.5pp or more has marked the start of every US recession since 1970)."""
    m = d.resample("ME").last()
    u3 = m["UNEMP"].rolling(3).mean()
    series = {
        "Unemployment rate (%)": m["UNEMP"], "Sahm indicator (pp)": u3 - u3.shift(1).rolling(12).min(),
        "Initial jobless claims (k)": m["CLAIMS"], "ISM manufacturing PMI": m["PMI"],
        "Real GDP growth, q/q ann. (%)": m["GDP_QOQ"], "CPI inflation, y/y (%)": m["CPI_YOY"],
        "Bloomberg US financial conditions": m["BFCI"], "VIX": m["VIX"],
        "10y - 3m Treasury (pp)": m["UST10"] - m["UST3m"],
        "CDX IG 5y spread (bp)": spreads["IG"].resample("ME").last() * 1e4,
        "CDX HY 5y spread (bp)": spreads["HY"].resample("ME").last() * 1e4,
    }
    stress_high = {"Unemployment rate (%)", "Sahm indicator (pp)", "Initial jobless claims (k)", "VIX",
                   "CDX IG 5y spread (bp)", "CDX HY 5y spread (bp)"}
    rows = []
    for name, s in series.items():
        s = s.dropna()
        rows.append(dict(series=name, latest=s.iloc[-1], median=s.median(), percentile=(s < s.iloc[-1]).mean(),
                         since=f"{s.index[0]:%Y-%m}", stress_when="high" if name in stress_high else "low"))
    return pd.DataFrame(rows)


def index_history(d):
    """ICE BofA index risk and return, 2006-2026: annualised total return and volatility (weekly), maximum
    drawdown, and drawdowns in the 2008 crisis, the 2020 Covid shock and the 2022 rate shock."""
    cols = ["CORP_AAA", "CORP_AA", "CORP_A", "CORP_BBB", "CORP_1_3", "CORP_3_5", "CORP_5_7", "CORP_7_10",
            "CORP_10P", "CORP", "HY", "MUNI", "TEL15"]
    w = d[cols].resample("W-FRI").last()
    r = np.log(w).diff().dropna()
    yrs = (w.index[-1] - w.index[0]).days / 365.25

    def dd(s):
        return (s / s.cummax() - 1).min()

    out = pd.DataFrame({
        "ann_return": (w.iloc[-1] / w.iloc[0]) ** (1 / yrs) - 1, "ann_vol": r.std() * np.sqrt(52),
        "max_drawdown": d[cols].apply(dd),
        "gfc_2008": d.loc["2008-09-01":"2009-03-31", cols].apply(dd),
        "covid_2020": d.loc["2020-02-14":"2020-04-30", cols].apply(dd),
        "rates_2022": d.loc["2021-12-31":"2022-10-31", cols].apply(dd),
        "corr_10y": r.corrwith(d["UST10"].resample("W-FRI").last().diff().dropna())})
    out.index.name = "index"
    return out
