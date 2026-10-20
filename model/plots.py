"""Figures.  Colours follow the reference data-viz palette (validated for colour-vision deficiency)."""
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import LinearSegmentedColormap, TwoSlopeNorm
from matplotlib.ticker import FuncFormatter, NullFormatter

from . import config as C
from .data import UST
from .portfolio import asset_paths, portfolio_returns, sleeve_yield

BLUE, ORANGE, AQUA, YELLOW = "#2a78d6", "#eb6834", "#1baf7a", "#eda100"
INK, INK2, MUTED, GRID, SURFACE, RED, NEUTRAL = "#0b0b0b", "#52514e", "#8a8984", "#e6e5e0", "#fcfcfb", "#e34948", "#f0efec"
RAMP = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]
START = 2026 + 9.5 / 12                                           # mid-October 2026

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "axes.edgecolor": GRID, "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
    "text.color": INK, "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6, "axes.axisbelow": True,
    "axes.spines.top": False, "axes.spines.right": False, "axes.titleweight": "bold", "axes.titlesize": 12,
    "axes.titlelocation": "left", "font.size": 10, "lines.linewidth": 2, "legend.frameon": False,
    "figure.dpi": 130, "text.parse_math": False,                 # "$" in labels is literal text
})


def _label(ax, x, y, text, dx=4, dy=0, **kw):
    ax.annotate(text, (x, y), textcoords="offset points", xytext=(dx, dy), fontsize=kw.pop("fontsize", 8),
                color=kw.pop("color", INK2), va=kw.pop("va", "center"), **kw)


def _save(fig, name):
    fig.tight_layout()
    fig.savefig(C.FIG_DIR / name, bbox_inches="tight")
    plt.close(fig)


def _mix(row, keys):
    return " / ".join(f"{row[k]:.0%} {C.SLEEVES[k]['name'].split(' (')[0]}" for k in keys if row[k] > 1e-9)


def market(d, mkt):
    fig, ax = plt.subplots(2, 2, figsize=(15, 9))
    a = ax[0, 0]
    date = d.index[-1]
    for lag, c in ((5, MUTED), (1, BLUE), (0, ORANGE)):
        row = d[UST].loc[:date - pd.DateOffset(years=lag)].iloc[-1]
        lab = f"{row.name:%b %Y}" + (" (pricing date)" if lag == 0 else "")
        a.plot(C.TENORS, row, color=c, marker="o", ms=4, label=lab)
    for t, dx, dy in (("3m", 6, -10), ("2", 0, 8), ("10", 0, 8), ("30", 0, 8)):
        v = d[f"UST{t}"].iloc[-1]
        _label(a, C.TENORS[C.TENOR_LABELS.index(t)], v, f"{v:.2f}%", dx=dx, dy=dy, ha="center" if dx == 0 else "left")
    a.set(title="Treasury curve, 1m to 30y", xlabel="Maturity (years)", ylabel="Yield (%)")
    a.legend(loc="lower right")

    a = ax[0, 1]
    for col, lab, c in (("UST3m", "3m", MUTED), ("UST2", "2y", BLUE), ("UST10", "10y", ORANGE), ("UST30", "30y", AQUA)):
        a.plot(d.index, d[col], color=c, lw=1.2, label=lab)
    for pk in C.NBER_PEAKS:
        p = pd.Period(pk, "M")
        a.axvspan(p.to_timestamp(), (p + 12).to_timestamp(), color=RED, alpha=0.10, lw=0)
    a.set(title="Treasury yields 2006-2026 (shaded: the 12 months after each NBER peak)", ylabel="Yield (%)")
    a.legend(loc="upper center", ncol=4, fontsize=8)

    a = ax[1, 0]
    for col, c, lab in (("CORP", BLUE, "IG Corp (C0A0)"), ("HY", RED, "High Yield (H0A0)"),
                        ("TEL15", ORANGE, "15+yr Telecom (C8R0)"), ("MUNI", AQUA, "Muni (U0A0)")):
        s = d[col] / d[col].iloc[0] * 100
        a.plot(d.index, s, color=c, lw=1.3, label=lab)
        _label(a, d.index[-1], s.iloc[-1], f"{s.iloc[-1]:.0f}", dx=4)
    a.axhline(100, color=MUTED, lw=0.8)
    a.set(title="ICE BofA total-return indices (Oct 2006 = 100)", ylabel="Index level")
    a.legend(loc="upper left", fontsize=8)

    a = ax[1, 1]
    x = np.arange(len(C.TENORS))
    for i, (pk, c) in enumerate(zip(C.NBER_PEAKS, (MUTED, RAMP[2]))):
        a.bar(x + (i - 1) * 0.27, mkt["stress_moves"][i] * 1e4, width=0.27, color=c, label=f"{pk} peak + 12 months")
    a.bar(x + 0.27, mkt["stress_drift"] * 1e4, width=0.27, color=BLUE, label="model stress drift (average)")
    for xi, v in zip(x, mkt["stress_drift"] * 1e4):
        _label(a, xi + 0.27, v, f"{v:.0f}", dx=0, dy=-8, ha="center")
    a.axhline(0, color=INK2, lw=0.8)
    a.set_xticks(x, C.TENOR_LABELS)
    a.set(title="Stress-year Treasury drift, calibrated on the two recessions", xlabel="Tenor", ylabel="bp over 12 months")
    a.legend(loc="lower right", fontsize=8)
    _save(fig, "01_market_data.png")


def credit(cr, dr, rec):
    fig, ax = plt.subplots(1, 2, figsize=(14, 4.4), gridspec_kw={"width_ratios": [1.6, 1]})
    sg, w = cr["dr"]["SG"] * 100, cr["weights"]
    ax[0].fill_between(w.index, 0, w["stress"] * sg.max() * 1.1, step="mid", color=RED, alpha=0.12, lw=0,
                       label="Pr(stress regime), scaled")
    ax[0].plot(sg.index, sg, color=BLUE, marker="o", ms=4, label="Spec-grade default rate")
    ax[0].plot(sg.index, cr["dr"]["Baa"] * 1000, color=ORANGE, lw=1.4, label="Baa default rate x10")
    for s in ("benign", "stress"):
        v = cr["cond"].loc["SG", s] * 100
        ax[0].axhline(v, color=INK2, lw=0.8)
        _label(ax[0], w.index[0], v, f"{s} mean {v:.1f}%", dx=2, dy=6)
    ax[0].set(title=f"Moody's default history and the fitted credit regimes ({C.FIT_START}-2008)",
              ylabel="Annual default rate (%)")
    ax[0].legend(loc="upper right", fontsize=8)
    x = dr["SG"].loc[rec.index] * 100
    ax[1].scatter(x, rec * 100, s=40, color=BLUE, edgecolor=SURFACE, linewidth=1.5, zorder=3)
    xx = np.linspace(0, x.max() * 1.05, 50)
    ax[1].plot(xx, (cr["rec_a"] + cr["rec_b"] * xx / 100) * 100, color=ORANGE,
               label=f"RR = {cr['rec_a']:.3f} {cr['rec_b']:+.2f} x DR  (R² {cr['rec_r2']:.2f})")
    for yr in (1990, 2001, 2007, 2008):
        _label(ax[1], x[yr], rec[yr] * 100, str(yr), dx=5, dy=2)
    ax[1].set(title="Recovery falls when defaults rise (Exh. 9 / 26)", xlabel="Spec-grade default rate (%)",
              ylabel="Sr. unsecured recovery (%)")
    ax[1].legend(loc="upper center", bbox_to_anchor=(0.5, -0.14), fontsize=8)
    _save(fig, "02_credit_regimes.png")


def projection(proj, cr):
    fig, ax = plt.subplots(1, 3, figsize=(15, 4.2))
    yrs = proj["year"]
    ax[0].bar(yrs, proj["p_stress"] * 100, color=BLUE, width=0.6)
    for x, v in zip(yrs, proj["p_stress"] * 100):
        _label(ax[0], x, v, f"{v:.0f}%", dx=0, dy=6, ha="center")
    P = cr["P"]
    lr = P[0, 1] / (P[0, 1] + P[1, 0]) * 100
    ax[0].axhline(lr, color=INK2, lw=0.8)
    _label(ax[0], yrs.iloc[0] - 0.4, lr, f"long-run {lr:.0f}%", dx=0, dy=6)
    ax[0].set(title="Probability of a credit-stress year", ylabel="%")
    for r, c in (("A", BLUE), ("Baa", ORANGE), ("Ba", AQUA)):
        ax[1].plot(yrs, proj[r] * 100, color=c, marker="o", ms=5, label=r)
        _label(ax[1], yrs.iloc[-1], proj[r].iloc[-1] * 100, f"{proj[r].iloc[-1] * 100:.2f}%", dx=6)
    ax[1].set_yscale("log")
    ax[1].yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:g}%"))
    ax[1].yaxis.set_minor_formatter(NullFormatter())
    ax[1].set_xlim(yrs.iloc[0] - 0.3, yrs.iloc[-1] + 0.7)
    ax[1].set(title="Predicted annual default rate by rating", ylabel="% per year (log)")
    ax[1].legend(loc="lower left", bbox_to_anchor=(0.02, 0.22), ncol=3)
    ax[2].plot(yrs, proj["recovery"] * 100, color=BLUE, marker="o", ms=5)
    for x, v in zip(yrs, proj["recovery"] * 100):
        _label(ax[2], x, v, f"{v:.1f}%", dx=0, dy=8, ha="center")
    ax[2].set_ylim(proj["recovery"].min() * 100 - 2, proj["recovery"].max() * 100 + 2)
    ax[2].set(title="Predicted sr. unsecured recovery rate", ylabel="%")
    for a in ax:
        a.set_xticks(yrs)
    _save(fig, "03_credit_projection.png")


def heatmap(grid, best):
    g, m, c = C.MAIN
    piv = grid.pivot_table(index=g, columns=c, values="surplus_sharpe")
    feas = grid.pivot_table(index=g, columns=c, values="feasible").astype(float)
    fig, ax = plt.subplots(figsize=(8.5, 6.2))
    v = np.nanmax(np.abs(piv.values))
    mesh = ax.pcolormesh(piv.columns * 100, piv.index * 100, piv.values, shading="nearest",
                         cmap=LinearSegmentedColormap.from_list("div", [RED, NEUTRAL, BLUE]), norm=TwoSlopeNorm(0, -v, v))
    cb = fig.colorbar(mesh, ax=ax, pad=0.02)
    cb.set_label("Surplus Sharpe ratio", color=INK2)
    cb.outline.set_visible(False)
    ax.contour(feas.columns * 100, feas.index * 100, feas.values, levels=[0.5], colors=INK, linewidths=1.4)
    ax.axhline(C.GOV_CAP * 100, color=INK2, lw=0.8)
    _label(ax, 2, C.GOV_CAP * 100, "15% government cap", dx=0, dy=8)
    ax.scatter(best[c] * 100, best[g] * 100, s=120, marker="*", color=ORANGE, edgecolor=SURFACE, lw=1.5, zorder=4)
    ax.annotate(f"best feasible\n{_mix(best, C.MAIN)}\nSharpe {best.surplus_sharpe:.3f}", (best[c] * 100, best[g] * 100),
                textcoords="offset points", xytext=(-190, 40), fontsize=8, arrowprops=dict(arrowstyle="-", color=INK2, lw=0.8))
    _label(ax, 0.99, 0.98, "outlined: gov ≤ 15% and duration 4-6y", dx=0, xycoords="axes fraction", ha="right", va="top")
    ax.grid(False)
    ax.set(title="Surplus Sharpe across every allocation (1% grid)", xlabel="Corporate weight (%)",
           ylabel="Government (2y Treasury) weight (%)   muni = remainder")
    _save(fig, "04_sharpe_heatmap.png")


def frontier(grid, sector, bench, best, best_s, unc):
    fig, ax = plt.subplots(figsize=(9.5, 6))
    pts = ((bench, MUTED, 0.35, "30y Treasury sleeve (rules ignored)"),
           (grid[~grid.feasible], RAMP[1], 0.5, "C0A0 corporate sleeve, breaks a rule"),
           (sector[sector.feasible], YELLOW, 0.6, "tower corporate sleeve, meets rules"),
           (grid[grid.feasible], BLUE, 0.9, "C0A0 corporate sleeve, meets rules"))
    for df, c, a, lab in pts:
        ax.scatter(df.surplus_vol_ann * 100, df.surplus_ret_ann * 100, s=9, color=c, alpha=a, lw=0, label=lab)
    for row, keys, lab, c, dy in ((best, C.MAIN, "best feasible", ORANGE, -24), (best_s, C.SECTOR, "best, tower sleeve", RED, -50),
                                  (unc, C.BENCH, "best ignoring rules", AQUA, 10)):
        ax.scatter(row.surplus_vol_ann * 100, row.surplus_ret_ann * 100, s=150, marker="*", color=c, edgecolor=INK,
                   lw=0.6, zorder=4, label=lab)
        _label(ax, row.surplus_vol_ann * 100, row.surplus_ret_ann * 100, f"{lab}: {_mix(row, keys)}\nSharpe "
               f"{row.surplus_sharpe:.2f}, duration {row.mod_duration:.1f}y", dx=10, dy=dy, color=INK)
    ax.axhline(0, color=INK2, lw=0.8)
    ax.set(title="Surplus risk vs. surplus return, every allocation", ylabel="Expected surplus return (%/yr)",
           xlabel="Surplus volatility (% of assets, annualised)")
    ax.legend(loc="lower right", fontsize=8)
    _save(fig, "05_surplus_frontier.png")


def funded_status(sim, rows):
    """rows: [(label, row, keys, colour)], first entry gets the fan chart."""
    years = START + np.arange(C.MONTHS + 1) / 12
    fs = [(lab, asset_paths(portfolio_returns(sim, k, [r[x] for x in k])) / sim["L"], c, r, k) for lab, r, k, c in rows]
    fig, ax = plt.subplots(1, 2, figsize=(15, 4.8), gridspec_kw={"width_ratios": [1.5, 1]})
    p = np.percentile(fs[0][1] * 100, [5, 25, 50, 75, 95], axis=0)
    ax[0].fill_between(years, p[0], p[4], color=RAMP[1], lw=0, label="5th-95th percentile")
    ax[0].fill_between(years, p[1], p[3], color=RAMP[3], lw=0, alpha=0.7, label="25th-75th percentile")
    ax[0].plot(years, p[2], color=RAMP[6], label="median")
    ax[0].axhline(100, color=RED, lw=1)
    _label(ax[0], years[0], 100, "fully funded", dx=2, dy=-9)
    for q, lab in ((0, "5th"), (2, "median"), (4, "95th")):
        _label(ax[0], years[-1], p[q, -1], f"{lab} {p[q, -1]:.0f}%")
    ax[0].set(title=f"Funded status path, best feasible ({_mix(fs[0][3], fs[0][4])})", ylabel="Assets / PV(liabilities) (%)")
    ax[0].legend(loc="upper left", fontsize=8)
    for lab, F, c, *_ in fs:
        end = F[:, -1]
        ax[1].hist(end * 100, bins=np.linspace(60, 170, 56), histtype="step", lw=2, color=c,
                   label=f"{lab}: median {np.median(end) * 100:.0f}%, P(<100%) {(end < 1).mean():.0%}")
    ax[1].axvline(100, color=RED, lw=1)
    ax[1].legend(loc="upper center", bbox_to_anchor=(0.5, -0.14), fontsize=8)
    ax[1].set(title="Funded status in October 2031", xlabel="Funded status (%)", ylabel="Paths")
    _save(fig, "06_funded_status.png")


def expected_return(yearly, best, sim):
    keys = [k for k in C.MAIN if best[k] > 1e-9]
    contrib = [(f"{C.SLEEVES[k]['name'].split(' (')[0]}\n{best[k]:.0%} × {sleeve_yield(k, sim['y0']) * 100:.2f}%",
                best[k] * sleeve_yield(k, sim["y0"])) for k in keys]
    gross, avg_loss = yearly.portfolio_yield.iloc[0], yearly.expected_default_loss.mean()
    labels = [c[0] for c in contrib] + ["Portfolio yield", "Expected default\nloss (5y avg)", "Expected return\nafter defaults"]
    heights = [c[1] for c in contrib] + [gross, avg_loss, gross - avg_loss]
    bottoms = list(np.cumsum([0] + [c[1] for c in contrib[:-1]])) + [0, gross - avg_loss, 0]
    colors = [RAMP[2]] * len(contrib) + [RAMP[4], RED, RAMP[6]]

    fig, ax = plt.subplots(1, 2, figsize=(15, 5), gridspec_kw={"width_ratios": [1, 1.25]})
    ax[0].bar(range(len(labels)), np.array(heights) * 100, bottom=np.array(bottoms) * 100, color=colors, width=0.62)
    for i, (b, h) in enumerate(zip(bottoms, heights)):
        txt = f"−{h * 100:.3f}%" if "loss" in labels[i] else f"{h * 100:.2f}%"
        _label(ax[0], i, (b + h) * 100, txt, dx=0, dy=8, ha="center", color=INK)
    ax[0].set_xticks(range(len(labels)), labels, fontsize=8)
    ax[0].set_ylim(0, gross * 115)
    ax[0].grid(axis="x", visible=False)
    ax[0].set(title="From yield to expected return after default losses", ylabel="% per year")

    yrs = yearly.year
    ax[1].bar(yrs, yearly.expected_return_after_defaults * 100, color=BLUE, width=0.55, label="Yield − expected default loss")
    for yr, v, l in zip(yrs, yearly.expected_return_after_defaults, yearly.expected_default_loss):
        _label(ax[1], yr, v * 100, f"{v * 100:.2f}%\n(loss {l * 1e4:.1f} bp)", dx=0, dy=-24, ha="center", color=SURFACE)
    m, lo, hi = (yearly[c] * 100 for c in ("sim_return_mean", "sim_return_p5", "sim_return_p95"))
    ax[1].errorbar(yrs + 0.33, m, yerr=[m - lo, hi - m], fmt="o", color=ORANGE, ecolor=MUTED, elinewidth=1.2,
                   capsize=3, ms=7, label="Simulated total return: mean, 5th-95th pct")
    for yr, v in zip(yrs, m):
        _label(ax[1], yr + 0.33, v, f"{v:.2f}%", dx=8)
    ax[1].axhline(0, color=INK2, lw=0.8)
    ax[1].set_ylim(min(lo.min() * 1.4, -1), hi.max() * 1.25)
    ax[1].set_xticks(yrs)
    ax[1].grid(axis="x", visible=False)
    ax[1].set(title="Expected return per year, 2027-2031", ylabel="% per year")
    ax[1].legend(loc="upper left", fontsize=8, ncol=2)
    fig.suptitle(f"Best feasible portfolio: {_mix(best, C.MAIN)}", x=0.01, ha="left", fontsize=10, color=INK2)
    _save(fig, "07_expected_return_after_defaults.png")


def portfolio_value(val, best):
    x = START + val.month / 12
    fig, ax = plt.subplots(figsize=(12, 5.6))
    ax.fill_between(x, val.p2_5, val.p97_5, color=RAMP[1], lw=0, label="95% band of outcomes (2.5th-97.5th pct)")
    ax.fill_between(x, val.p25, val.p75, color=RAMP[3], lw=0, alpha=0.6, label="50% band (25th-75th pct)")
    ax.plot(x, val["mean"], color=RAMP[6], label="Mean portfolio value")
    total = val["mean"] + val.benefits_paid
    ax.plot(x, total, color=ORANGE, lw=1.6, label="Mean value + benefits paid to date")
    ax.axhline(C.ASSETS0, color=INK2, lw=0.8)
    _label(ax, x.iloc[0], C.ASSETS0, "$100M start", dx=2, dy=6)
    end = val.iloc[-1]
    for v, lab in ((end.p97_5, "97.5th"), (end["mean"], "mean"), (end.p2_5, "2.5th")):
        _label(ax, x.iloc[-1], v, f"{lab} ${v:.1f}M", dx=5, color=INK)
    _label(ax, x.iloc[-1], total.iloc[-1], f"${total.iloc[-1]:.1f}M", dx=5)
    for i in range(12, C.MONTHS, 12):
        _label(ax, x[i], val["mean"][i], f"${val['mean'][i]:.1f}M", dx=0, dy=-12, ha="center")
    ax.set_xlim(x.iloc[0] - 0.05, x.iloc[-1] + 0.6)
    ax.set_title(f"Projected portfolio value: {_mix(best, C.MAIN)}")
    ax.set_ylabel("$ millions")
    ax.set_xlabel(f"$6M/yr paid out monthly. 95% confidence interval of the 2031 mean itself: "
                  f"±${end.mean_ci95_halfwidth:.2f}M ({C.N_PATHS:,} paths)", fontsize=8, color=MUTED)
    ax.legend(loc="upper left", fontsize=8)
    _save(fig, "08_portfolio_value.png")


def curve_views(views):
    """views: DataFrame with one row per curve view for the chosen portfolio."""
    colors = [INK2, BLUE, ORANGE, AQUA, YELLOW]
    fig, ax = plt.subplots(1, 2, figsize=(15, 5), gridspec_kw={"width_ratios": [1, 1.4]})
    for (name, bp), c in zip(C.CURVE_VIEWS.items(), colors):
        tv = C.curve_tilt(bp)
        ax[0].plot(C.TENORS, np.zeros_like(C.TENORS) if tv is None else tv * 1e4, color=c, marker="o", ms=4,
                   lw=1.8, label=name)
    ax[0].axhline(0, color=INK2, lw=0.8)
    ax[0].set(title="Curve views: total yield change by Oct 2031", xlabel="Maturity (years)", ylabel="bp")
    ax[0].legend(loc="upper center", bbox_to_anchor=(0.5, -0.14), ncol=3, fontsize=8)
    y = np.arange(len(views))[::-1]
    for yi, r, c in zip(y, views.itertuples(), colors):
        ax[1].errorbar(r.fs_end_mean * 100, yi, xerr=[[(r.fs_end_mean - r.fs_end_p5) * 100], [(r.fs_end_p95 - r.fs_end_mean) * 100]],
                       fmt="o", color=c, ecolor=c, elinewidth=2, capsize=4, ms=8)
        _label(ax[1], r.fs_end_p95 * 100, yi, f"mean {r.fs_end_mean:.0%}, Sharpe {r.surplus_sharpe:+.2f}, "
               f"P(<100%) {r.prob_underfunded_end:.0%}", dx=8)
    ax[1].axvline(100, color=RED, lw=1)
    ax[1].set_yticks(y, views.view)
    ax[1].set_xlim(right=ax[1].get_xlim()[1] + 40)
    ax[1].grid(axis="y", visible=False)
    ax[1].set(title="Chosen portfolio's funded status in Oct 2031 under each view (5th-95th pct)",
              xlabel="Funded status (%)")
    _save(fig, "09_curve_views.png")


def index_history(idx):
    """ICE BofA sub-indices by rating and by maturity, 2006-2026."""
    groups = (("rating", ["CORP_AAA", "CORP_AA", "CORP_A", "CORP_BBB", "HY"], ["AAA", "AA", "A", "BBB", "HY"]),
              ("maturity", ["CORP_1_3", "CORP_3_5", "CORP_5_7", "CORP_7_10", "CORP_10P"],
               ["1-3y", "3-5y", "5-7y", "7-10y", "10y+"]))
    fig, ax = plt.subplots(1, 2, figsize=(15, 4.8))
    for a, (title, cols, labs) in zip(ax, groups):
        x = np.arange(len(cols))
        r, v, dd = idx.loc[cols, "ann_return"] * 100, idx.loc[cols, "ann_vol"] * 100, idx.loc[cols, "max_drawdown"] * 100
        a.bar(x - 0.2, r, width=0.38, color=BLUE, label="annualised total return")
        a.bar(x + 0.2, dd, width=0.38, color=RED, alpha=0.75, label="maximum drawdown")
        for xi, ri, vi, di in zip(x, r, v, dd):
            _label(a, xi - 0.2, ri, f"{ri:.1f}%\nvol {vi:.1f}%", dx=0, dy=12, ha="center")
            _label(a, xi + 0.2, di, f"{di:.0f}%", dx=0, dy=-8, ha="center")
        a.axhline(0, color=INK2, lw=0.8)
        a.set_xticks(x, labs)
        a.set_ylim(dd.min() * 1.25, r.max() * 2.6)
        a.grid(axis="x", visible=False)
        a.set(title=f"ICE BofA US corporate sub-indices by {title}, 2006-2026", ylabel="%")
        a.legend(loc="upper left", fontsize=8)
    _save(fig, "10_index_history.png")


def tower(tab, tw, spreads, mkt):
    """Bond-level data: yield vs duration on the pricing date, and the tower sleeve's OAS history."""
    fig, ax = plt.subplots(1, 2, figsize=(15, 5.2), gridspec_kw={"width_ratios": [1.1, 1]})
    a = ax[0]
    a.plot(mkt["ust_dur"], mkt["y0"] * 100, color=INK2, marker="o", ms=3, lw=1.2, label="Treasury curve (by duration)")
    has = tab.dropna(subset=["ytw", "mod_dur"]).astype({"usd_consistent": bool})
    groups = ((has.tower_sleeve, BLUE, "o", "tower sleeve (American Tower, Crown Castle)"),
              (has.usd_consistent & ~has.tower_sleeve, ORANGE, "s", "other USD bonds (not in sleeve)"),
              (~has.usd_consistent, MUTED, "x", "fails USD check (excluded)"))
    for mask, c, mk, lab in groups:
        g = has[mask]
        a.scatter(g.mod_dur, g.ytw * 100, color=c, marker=mk, s=45, zorder=3, label=lab)
    for b, r in has[has.usd_consistent & ~has.tower_sleeve].iterrows():
        left = r.mod_dur < 3.5
        _label(a, r.mod_dur, r.ytw * 100, b, dx=-7 if left else 7, ha="right" if left else "left", fontsize=7)
    a.scatter(tw["mod_dur"], tw["yield0"] * 100, s=170, marker="*", color=YELLOW, edgecolor=INK, lw=0.6, zorder=4,
              label=f"sleeve: duration {tw['mod_dur']:.2f}, YTW {tw['yield0']:.2%}")
    a.set(title="Bond-level yields to worst on the pricing date", xlabel="Modified duration (years)", ylabel="Yield (%)")
    a.legend(loc="upper left", fontsize=8)

    a = ax[1]
    o = tw["oas_series"] * 1e4
    a.plot(o.index, o, color=BLUE, lw=1.4, label="tower sleeve: average OAS")
    cdx = spreads["IG"].loc[o.index[0]:o.index[-1]] * 1e4
    a.plot(cdx.index, cdx, color=ORANGE, lw=1.4, label="CDX IG 5y")
    _label(a, o.index[-1], o.iloc[-1], f"{o.iloc[-1]:.0f} bp", dx=4)
    _label(a, cdx.index[-1], cdx.iloc[-1], f"{cdx.iloc[-1]:.0f} bp", dx=4)
    a.set(title=f"Tower sleeve OAS vs CDX IG (spread volatility {tw['spread_vol'] * 1e4:.0f} bp/yr)", ylabel="bp")
    a.legend(loc="upper right", fontsize=8)
    a.tick_params(axis="x", rotation=30)
    _save(fig, "11_tower_bonds.png")


def market_pricing(d, mkt, path, be, fc, implied):
    """What the market prices: policy path, forward curve for Oct 2031, inflation, CDX-implied defaults."""
    from .market import forward_par
    fig, ax = plt.subplots(2, 2, figsize=(15, 9))
    a = ax[0, 0]
    ff = path[path.instrument.str.startswith("FF")]
    sfr = path[path.instrument.str.startswith("SFR")]
    a.plot(ff.months_ahead, ff.rate_pct, color=BLUE, marker="o", ms=5, label="fed funds futures")
    a.plot(sfr.months_ahead, sfr.rate_pct, color=ORANGE, marker="s", ms=5, label="3m SOFR futures")
    top = path.rate_pct.iloc[0]
    a.axhspan(top - 0.25, top, color=MUTED, alpha=0.2, lw=0, label=f"target range today {top - 0.25:.2f}-{top:.2f}%")
    for r in path.itertuples():
        if r.instrument.split()[0] in ("FF1", "FF12", "SFR8"):
            _label(a, r.months_ahead, r.rate_pct, f"{r.rate_pct:.2f}%", dx=0, dy=9, ha="center")
    a.set(title="Market-implied policy path", xlabel="Months ahead (approx.)", ylabel="%")
    a.legend(loc="lower right", fontsize=8)

    a = ax[0, 1]
    lens = np.array([0.5, 1, 2, 3, 5, 7, 10, 20])
    fwd = [forward_par(mkt["y0"], 5, L) * 100 for L in lens]
    a.plot(C.TENORS, mkt["y0"] * 100, color=BLUE, marker="o", ms=4, label=f"today ({mkt['date']:%d %b %Y})")
    a.plot(lens, fwd, color=ORANGE, marker="o", ms=4, label="priced for Oct 2031 (5y forward par yields)")
    for t, v in zip(lens, fwd):
        if t in (2, 10):
            _label(a, t, v, f"{v:.2f}%", dx=0, dy=9, ha="center")
    for t in ("2", "10"):
        v = mkt["y0"][C.TENOR_LABELS.index(t)] * 100
        _label(a, float(t), v, f"{v:.2f}%", dx=0, dy=-10, ha="center")
    a.set(title="Treasury par curve: today vs priced for October 2031", xlabel="Maturity (years)", ylabel="%")
    a.legend(loc="lower right", fontsize=8)

    a = ax[1, 0]
    m = d.resample("ME").last()
    a.plot(m.index, m["CPI_YOY"], color=INK2, lw=1.3, label="CPI inflation, y/y")
    a.plot(m.index, m["UST5"] - m["TIPS5"], color=BLUE, lw=1.3, label="5y breakeven")
    a.plot(m.index, m["UST10"] - m["TIPS10"], color=ORANGE, lw=1.3, label="10y breakeven")
    a.axhline(2, color=MUTED, lw=0.8)
    _label(a, m.index[-1], be["5y5y"], f"5y5y {be['5y5y']:.2f}%", dx=4)
    a.set(title="Inflation vs what TIPS price", ylabel="%")
    a.legend(loc="upper left", fontsize=8)

    a = ax[1, 1]
    x = np.arange(len(implied))
    a.bar(x - 0.2, implied.implied_default * 100, width=0.38, color=RED, alpha=0.8, label="CDX-implied (risk-neutral)")
    a.bar(x + 0.2, implied.model_default * 100, width=0.38, color=BLUE, label="model, 2027-31 average (real-world)")
    for xi, r in zip(x, implied.itertuples()):
        _label(a, xi - 0.2, r.implied_default * 100, f"{r.implied_default:.2%}", dx=0, dy=8, ha="center")
        _label(a, xi + 0.2, r.model_default * 100, f"{r.model_default:.2%}", dx=0, dy=8, ha="center")
    a.set_yscale("log")
    a.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:g}%"))
    a.yaxis.set_minor_formatter(NullFormatter())
    a.set_ylim(top=implied.implied_default.max() * 100 * 4)
    a.set_xticks(x, [f"Investment grade (CDX IG)\nimplied / model = {implied.ratio.iloc[0]:.1f}x",
                     f"High yield (CDX HY) vs spec-grade\nimplied / model = {implied.ratio.iloc[1]:.1f}x"])
    a.grid(axis="x", visible=False)
    a.set(title="Default rates: priced by CDS vs the model's forecast", ylabel="% per year (log)")
    a.legend(loc="upper left", fontsize=8)
    _save(fig, "12_market_pricing.png")
