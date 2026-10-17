"""Charts for the Monte Carlo allocation study.  Runs the model, then writes PNGs to output/figures."""
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap, TwoSlopeNorm
import numpy as np
import pandas as pd

import monte_carlo_allocation as mc

FIG_DIR = os.path.join(mc.OUT_DIR, "figures")

# reference palette (dataviz skill): categorical slots 1-3, text, surface, diverging poles
BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
INK, INK2, MUTED, GRID, SURFACE = "#0b0b0b", "#52514e", "#8a8984", "#e6e5e0", "#fcfcfb"
RED, NEUTRAL = "#e34948", "#f0efec"
BLUE_RAMP = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "axes.edgecolor": GRID, "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
    "text.color": INK, "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6,
    "axes.spines.top": False, "axes.spines.right": False, "axes.titleweight": "bold",
    "axes.titlesize": 12, "axes.titlelocation": "left", "font.size": 10, "lines.linewidth": 2,
    "legend.frameon": False, "figure.dpi": 130,
})


def save(fig, name):
    fig.tight_layout()
    fig.savefig(os.path.join(FIG_DIR, name), bbox_inches="tight")
    plt.close(fig)
    print("wrote", name)


def path_stats(sim, gkey, ckey, w):
    """Asset, liability and funded-status paths for one allocation (gov, muni, corp weights)."""
    R = sim["R"]
    rA = w[0] * R[gkey] + w[1] * R["MUNI"] + w[2] * R[ckey]
    A = np.empty((rA.shape[0], mc.MONTHS + 1))
    A[:, 0] = mc.ASSETS0
    for t in range(mc.MONTHS):
        A[:, t + 1] = np.maximum(A[:, t] * (1 + rA[:, t]) - mc.PAYMENT / 12, 0)
    return A, A / sim["L"]


def fig_market(d):
    fig, ax = plt.subplots(1, 3, figsize=(15, 4.2))
    t = mc.TENORS
    y_start, y_end = d.filter(like="UST").iloc[0].values, d.filter(like="UST").iloc[-1].values
    ax[0].plot(t, y_start, color=BLUE, marker="o", ms=5, label=f"{d.index[0]:%b %Y}")
    ax[0].plot(t, y_end, color=ORANGE, marker="o", ms=5, label=f"{d.index[-1]:%b %Y} (pricing date)")
    for x, y in zip(t, y_end):
        if x in (1, 10, 30):
            ax[0].annotate(f"{y:.2f}%", (x, y), textcoords="offset points", xytext=(0, 7),
                           ha="center", color=INK2, fontsize=8)
    ax[0].set(title="Treasury curve: one year of bear steepening", xlabel="Maturity (years)",
              ylabel="Yield (%)")
    ax[0].legend(loc="lower right")

    for col, c in [("UST2", BLUE), ("UST10", ORANGE), ("UST30", AQUA)]:
        ax[1].plot(d.index, d[col], color=c, lw=1.6, label=col.replace("UST", "") + "y")
    ax[1].set(title="Treasury yields, past year", ylabel="Yield (%)")
    ax[1].legend(loc="upper left")

    for col, c, lab, dy in [("CORP", BLUE, "IG Corp (C0A0)", -6), ("TEL15", ORANGE, "15+yr Telecom (C8R0)", 0),
                            ("MUNI", AQUA, "Muni (U0A0)", 6)]:
        s = d[col] / d[col].iloc[0] * 100
        ax[2].plot(d.index, s, color=c, lw=1.6, label=lab)
        ax[2].annotate(f"{lab.split(' (')[0]} {s.iloc[-1] - 100:+.1f}%", (d.index[-1], s.iloc[-1]),
                       textcoords="offset points", xytext=(4, dy), va="center", color=INK2, fontsize=8)
    ax[2].axhline(100, color=MUTED, lw=0.8)
    ax[2].set(title="ICE BofA total-return indices (start = 100)", ylabel="Index level")
    ax[2].legend(loc="lower left")
    for a in ax[1:]:
        a.tick_params(axis="x", rotation=30)
    save(fig, "01_market_data.png")


def fig_regimes(credit, recov, dr, rec):
    fig, ax = plt.subplots(1, 2, figsize=(14, 4.4), gridspec_kw={"width_ratios": [1.6, 1]})
    w = credit["weights"]
    sg = credit["dr"]["SG"] * 100
    ax[0].fill_between(w.index, 0, w["stress"] * sg.max() * 1.1, step="mid", color=RED, alpha=0.12,
                       lw=0, label="Pr(stress regime), scaled")
    ax[0].plot(sg.index, sg, color=BLUE, marker="o", ms=4, label="Spec-grade default rate")
    ax[0].plot(credit["dr"].index, credit["dr"]["Baa"] * 100 * 10, color=ORANGE, lw=1.4,
               label="Baa default rate x10")
    for k, lab in [("benign", "benign mean"), ("stress", "stress mean")]:
        v = credit["cond"].loc["SG", k] * 100
        ax[0].axhline(v, color=INK2, lw=0.8)
        ax[0].annotate(f"{lab} {v:.1f}%", (w.index[0], v), textcoords="offset points", xytext=(2, 3),
                       color=INK2, fontsize=8)
    ax[0].set(title="Moody's default history and the fitted 2-state credit regime (1970-2008)",
              ylabel="Annual default rate (%)")
    ax[0].legend(loc="upper right", fontsize=8)

    x = dr.loc[rec.index, "SG"] * 100
    ax[1].scatter(x, rec * 100, s=40, color=BLUE, edgecolor=SURFACE, linewidth=1.5, zorder=3)
    xx = np.linspace(0, x.max() * 1.05, 50)
    ax[1].plot(xx, (recov["a"] + recov["b"] * xx / 100) * 100, color=ORANGE,
               label=f"RR = {recov['a']:.3f} {recov['b']:+.2f} x DR  (R² {recov['r2']:.2f})")
    for yr in (1990, 2001, 2008, 2007):
        ax[1].annotate(str(yr), (x[yr], rec[yr] * 100), textcoords="offset points", xytext=(5, 2),
                       color=INK2, fontsize=8)
    ax[1].set(title="Recovery falls when defaults rise (Exh. 9 / 26)",
              xlabel="Spec-grade default rate (%)", ylabel="Sr. unsecured recovery (%)")
    ax[1].legend(loc="upper right", fontsize=8)
    save(fig, "02_credit_regimes.png")


def fig_projection(proj, credit):
    fig, ax = plt.subplots(1, 3, figsize=(15, 4.2))
    yrs = proj["year"]
    ax[0].bar(yrs, proj["P(stress)"] * 100, color=BLUE, width=0.6)
    for x, v in zip(yrs, proj["P(stress)"] * 100):
        ax[0].annotate(f"{v:.0f}%", (x, v), textcoords="offset points", xytext=(0, 3), ha="center",
                       color=INK2, fontsize=8)
    stat = credit["P"][0, 1] / (credit["P"][0, 1] + credit["P"][1, 0]) * 100
    ax[0].axhline(stat, color=INK2, lw=0.8)
    ax[0].annotate(f"long-run {stat:.0f}%", (yrs.iloc[0] - 0.4, stat), textcoords="offset points",
                   xytext=(0, 3), color=INK2, fontsize=8)
    ax[0].set(title="Probability of a credit-stress year", ylabel="%")

    for r, c in [("A", BLUE), ("Baa", ORANGE), ("Ba", AQUA)]:
        ax[1].plot(yrs, proj[r] * 100, color=c, marker="o", ms=5, label=r)
        ax[1].annotate(f"{proj[r].iloc[-1] * 100:.2f}%", (yrs.iloc[-1], proj[r].iloc[-1] * 100),
                       textcoords="offset points", xytext=(6, 0), va="center", color=INK2, fontsize=8)
    ax[1].set_yscale("log")
    ax[1].set(title="Predicted annual default rate by rating", ylabel="% per year (log)")
    ax[1].legend(loc="lower left", bbox_to_anchor=(0.02, 0.22), ncol=3)
    ax[1].set_xlim(yrs.iloc[0] - 0.3, yrs.iloc[-1] + 0.7)

    ax2 = ax[2]
    ax2.plot(yrs, proj["recovery"] * 100, color=BLUE, marker="o", ms=5)
    for x, v in zip(yrs, proj["recovery"] * 100):
        ax2.annotate(f"{v:.1f}%", (x, v), textcoords="offset points", xytext=(0, 6), ha="center",
                     color=INK2, fontsize=8)
    ax2.set(title="Predicted sr. unsecured recovery rate", ylabel="%")
    ax2.set_ylim(proj["recovery"].min() * 100 - 2, proj["recovery"].max() * 100 + 2)
    for a in ax:
        a.set_xticks(yrs)
    save(fig, "03_credit_projection.png")


def fig_heatmap(df, title, name):
    """Surplus Sharpe on the simplex: x = corporate weight, y = government weight, muni = rest."""
    piv = df.pivot_table(index="govt", columns="corp", values="surplus_sharpe")
    fig, ax = plt.subplots(figsize=(8.5, 6.2))
    cmap = LinearSegmentedColormap.from_list("div", [RED, NEUTRAL, BLUE])
    v = np.nanmax(np.abs(piv.values))
    m = ax.pcolormesh(piv.columns * 100, piv.index * 100, piv.values, cmap=cmap,
                      norm=TwoSlopeNorm(0, -v, v), shading="nearest")
    cb = fig.colorbar(m, ax=ax, pad=0.02)
    cb.set_label("Surplus Sharpe ratio", color=INK2)
    cb.outline.set_visible(False)
    feas = df.pivot_table(index="govt", columns="corp", values="feasible").astype(float)
    ax.contour(feas.columns * 100, feas.index * 100, feas.values, levels=[0.5], colors=INK, linewidths=1.4)
    ax.axhline(mc.GOV_CAP * 100, color=INK2, lw=0.8)
    ax.annotate("15% government cap", (2, mc.GOV_CAP * 100 + 1.5), color=INK2, fontsize=8)
    best = df[df.feasible].sort_values("surplus_sharpe").iloc[-1]
    ax.scatter(best.corp * 100, best.govt * 100, s=120, marker="*", color=ORANGE, edgecolor=SURFACE,
               linewidth=1.5, zorder=4)
    ax.annotate(f"best feasible\n{best.govt:.0%} gov / {best.muni:.0%} muni / {best.corp:.0%} corp\n"
                f"Sharpe {best.surplus_sharpe:.3f}", (best.corp * 100, best.govt * 100),
                textcoords="offset points", xytext=(-150, 30), color=INK, fontsize=8,
                arrowprops=dict(arrowstyle="-", color=INK2, lw=0.8))
    ax.set(title=title, xlabel="Corporate weight (%)", ylabel="Government weight (%)  (muni = remainder)")
    ax.grid(False)
    ax.annotate("outlined region: gov ≤ 15% and duration 4-6y", (0.99, 0.98), xycoords="axes fraction",
                ha="right", va="top", color=INK2, fontsize=8)
    save(fig, name)


def fig_frontier(coarse, best_row, unc_row):
    fig, ax = plt.subplots(figsize=(9, 5.6))
    inf = coarse[~coarse.feasible]
    fe = coarse[coarse.feasible]
    ax.scatter(inf.surplus_vol_ann * 100, inf.surplus_ret_ann * 100, s=9, color=MUTED, alpha=0.35,
               lw=0, label="breaks a rule")
    ax.scatter(fe.surplus_vol_ann * 100, fe.surplus_ret_ann * 100, s=14, color=BLUE, alpha=0.8,
               lw=0, label="meets gov cap + duration rule")
    for row, lab, c in [(best_row, "best feasible", ORANGE), (unc_row, "best ignoring rules", AQUA)]:
        ax.scatter(row.surplus_vol_ann * 100, row.surplus_ret_ann * 100, s=150, marker="*", color=c,
                   edgecolor=INK, linewidth=0.6, zorder=4, label=lab)
        ax.annotate(f"{lab}: {row.govt:.0%} {row.govt_sleeve} / {row.muni:.0%} muni / {row.corp:.0%} "
                    f"{row.corp_sleeve}\nSharpe {row.surplus_sharpe:.2f}, duration {row.mod_duration:.1f}y",
                    (row.surplus_vol_ann * 100, row.surplus_ret_ann * 100), textcoords="offset points",
                    xytext=(10, -22 if lab.startswith("best f") else 8), fontsize=8, color=INK)
    ax.axhline(0, color=INK2, lw=0.8)
    ax.set(title="Surplus risk vs. surplus return, every allocation (5% grid, all sleeve choices)",
           xlabel="Surplus volatility (% of assets, annualised)", ylabel="Expected surplus return (%/yr)")
    ax.legend(loc="lower right", fontsize=8)
    save(fig, "05_surplus_frontier.png")


def fig_variants(coarse):
    b = (coarse[coarse.feasible].sort_values("surplus_sharpe", ascending=False)
         .drop_duplicates(["govt_sleeve", "corp_sleeve"]))
    b = b.sort_values("surplus_sharpe")
    lab = [f"{r.govt_sleeve.replace('UST', 'UST ')}y + {r.corp_sleeve}   ({r.govt:.0%}/{r.muni:.0%}/{r.corp:.0%})"
           for r in b.itertuples()]
    fig, ax = plt.subplots(figsize=(9, 4.6))
    colors = [BLUE if v >= 0 else RED for v in b.surplus_sharpe]
    ax.barh(lab, b.surplus_sharpe, color=colors, height=0.6)
    for i, v in enumerate(b.surplus_sharpe):
        ax.annotate(f"{v:.3f}", (v, i), textcoords="offset points", xytext=(4 if v >= 0 else -4, 0),
                    ha="left" if v >= 0 else "right", va="center", fontsize=8, color=INK2)
    ax.axvline(0, color=INK2, lw=0.8)
    lo, hi = b.surplus_sharpe.min(), b.surplus_sharpe.max()
    ax.set_xlim(min(lo, 0) * 1.25, max(hi, 0) * 1.3 + 0.02)
    ax.grid(axis="y", visible=False)
    ax.set(title="Best feasible surplus Sharpe for each sleeve choice  (gov/muni/corp weights)",
           xlabel="Surplus Sharpe ratio")
    save(fig, "06_sleeve_choices.png")


def fig_funded(sim, best_row, unc_row, muni_row):
    months = np.arange(mc.MONTHS + 1) / 12 + 2026.79
    fig, ax = plt.subplots(1, 2, figsize=(15, 4.8), gridspec_kw={"width_ratios": [1.5, 1]})
    _, FS = path_stats(sim, best_row.govt_sleeve, best_row.corp_sleeve, (best_row.govt, best_row.muni, best_row.corp))
    p = np.percentile(FS * 100, [5, 25, 50, 75, 95], axis=0)
    ax[0].fill_between(months, p[0], p[4], color=BLUE_RAMP[1], lw=0, label="5th-95th percentile")
    ax[0].fill_between(months, p[1], p[3], color=BLUE_RAMP[3], lw=0, alpha=0.7, label="25th-75th percentile")
    ax[0].plot(months, p[2], color=BLUE_RAMP[6], label="median")
    ax[0].axhline(100, color=RED, lw=1)
    ax[0].annotate("fully funded", (months[0], 100), textcoords="offset points", xytext=(2, -11),
                   color=INK2, fontsize=8)
    for q, lab in [(0, "5th"), (2, "median"), (4, "95th")]:
        ax[0].annotate(f"{lab} {p[q, -1]:.0f}%", (months[-1], p[q, -1]), textcoords="offset points",
                       xytext=(4, 0), va="center", fontsize=8, color=INK2)
    ax[0].set(title=f"Funded status path, best feasible portfolio "
                    f"({best_row.govt:.0%} gov / {best_row.muni:.0%} muni / {best_row.corp:.0%} corp)",
              ylabel="Assets / PV(liabilities) (%)")
    ax[0].legend(loc="upper left", fontsize=8)

    bins = np.linspace(60, 170, 56)
    for row, c, lab in [(best_row, BLUE, "best feasible"), (unc_row, AQUA, "best ignoring rules"),
                        (muni_row, ORANGE, "best muni-heavy")]:
        _, F = path_stats(sim, row.govt_sleeve, row.corp_sleeve, (row.govt, row.muni, row.corp))
        ax[1].hist(F[:, -1] * 100, bins=bins, histtype="step", lw=2, color=c,
                   label=f"{lab}: median {np.median(F[:, -1]) * 100:.0f}%, "
                         f"P(<100%) {(F[:, -1] < 1).mean():.0%}")
    ax[1].axvline(100, color=RED, lw=1)
    ax[1].set(title="Funded status in October 2031", xlabel="Funded status (%)", ylabel="Paths")
    ax[1].legend(loc="upper left", fontsize=8)
    save(fig, "07_funded_status.png")


def main():
    os.makedirs(FIG_DIR, exist_ok=True)
    r = mc.main()
    d, credit, recov, sim, proj, coarse, fine = (r[k] for k in ["d", "credit", "recov", "sim", "proj", "coarse", "fine"])
    text = mc.pdf_text(mc.MOODYS_PDF)
    dr, rec = mc.parse_exhibit36(text), mc.parse_exhibit26(text)

    fig_market(d)
    fig_regimes(credit, recov, dr, rec)
    fig_projection(proj, credit)
    best = fine[fine.feasible].sort_values("surplus_sharpe").iloc[-1]
    sel = fine[(fine.govt_sleeve == best.govt_sleeve) & (fine.corp_sleeve == best.corp_sleeve)]
    fig_heatmap(sel, f"Surplus Sharpe across every allocation  ({best.govt_sleeve} gov sleeve, "
                     f"{best.corp_sleeve} corp sleeve, 1% grid)", "04_sharpe_heatmap.png")
    unc = coarse.sort_values("surplus_sharpe").iloc[-1]
    fig_frontier(coarse, best, unc)
    fig_variants(coarse)
    muni = coarse[coarse.feasible & (coarse.muni >= 0.5)].sort_values("surplus_sharpe").iloc[-1]
    fig_funded(sim, best, unc, muni)
    summary = pd.DataFrame([best, unc, muni], index=["best_feasible", "best_unconstrained", "best_muni_heavy"])
    summary.to_csv(os.path.join(mc.OUT_DIR, "headline_portfolios.csv"))
    print(summary.T)


if __name__ == "__main__":
    main()
