"""Figures.  Colours follow the reference data-viz palette (validated for colour-vision deficiency)."""
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import LinearSegmentedColormap, TwoSlopeNorm

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
    ax.annotate(text, (x, y), textcoords="offset points", xytext=(dx, dy), fontsize=8,
                color=kw.pop("color", INK2), va=kw.pop("va", "center"), **kw)


def _save(fig, name):
    fig.tight_layout()
    fig.savefig(C.FIG_DIR / name, bbox_inches="tight")
    plt.close(fig)


def _mix(row, keys):
    return " / ".join(f"{row[k]:.0%} {C.SLEEVES[k]['name'].split(' (')[0]}" for k in keys if row[k] > 1e-9)


def market(d):
    fig, ax = plt.subplots(1, 3, figsize=(15, 4.2))
    for i, c, lab in ((0, BLUE, f"{d.index[0]:%b %Y}"), (-1, ORANGE, f"{d.index[-1]:%b %Y} (pricing date)")):
        ax[0].plot(C.TENORS, d[UST].iloc[i], color=c, marker="o", ms=5, label=lab)
    for t in (1, 10, 30):
        _label(ax[0], t, d[f"UST{t}"].iloc[-1], f"{d[f'UST{t}'].iloc[-1]:.2f}%", dx=0, dy=8, ha="center")
    ax[0].set(title="Treasury curve: one year of bear steepening", xlabel="Maturity (years)", ylabel="Yield (%)")
    ax[0].legend(loc="lower right")
    for col, c in (("UST2", BLUE), ("UST10", ORANGE), ("UST30", AQUA)):
        ax[1].plot(d.index, d[col], color=c, lw=1.6, label=col[3:] + "y")
    ax[1].set(title="Treasury yields, past year", ylabel="Yield (%)")
    ax[1].legend(loc="upper left")
    for col, c, lab, dy in (("CORP", BLUE, "IG Corp (C0A0)", -6), ("TEL15", ORANGE, "15+yr Telecom (C8R0)", 0),
                            ("MUNI", AQUA, "Muni (U0A0)", 6)):
        s = d[col] / d[col].iloc[0] * 100
        ax[2].plot(d.index, s, color=c, lw=1.6, label=lab)
        _label(ax[2], d.index[-1], s.iloc[-1], f"{lab.split(' (')[0]} {s.iloc[-1] - 100:+.1f}%", dy=dy)
    ax[2].axhline(100, color=MUTED, lw=0.8)
    ax[2].set(title="ICE BofA total-return indices (start = 100)", ylabel="Index level")
    ax[2].legend(loc="lower left")
    for a in ax[1:]:
        a.tick_params(axis="x", rotation=30)
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


def frontier(grid, bench, best, unc):
    fig, ax = plt.subplots(figsize=(9, 5.6))
    pts = ((bench, MUTED, 0.35, "30y Treasury sleeve (rules ignored)"),
           (grid[~grid.feasible], RAMP[1], 0.5, "2y Treasury sleeve, breaks a rule"),
           (grid[grid.feasible], BLUE, 0.9, "meets gov cap + duration rule"))
    for df, c, a, lab in pts:
        ax.scatter(df.surplus_vol_ann * 100, df.surplus_ret_ann * 100, s=9, color=c, alpha=a, lw=0, label=lab)
    for row, keys, lab, c, dy in ((best, C.MAIN, "best feasible", ORANGE, -24), (unc, C.BENCH, "best ignoring rules", AQUA, 10)):
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
