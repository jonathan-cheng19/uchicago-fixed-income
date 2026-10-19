"""Run the full study: fit the credit model, simulate, test every allocation, write results and figures."""
import time

import numpy as np
import pandas as pd

from model import config as C
from model import credit, data, plots, portfolio
from model.simulation import simulate


def main():
    t0 = time.time()
    C.FIG_DIR.mkdir(parents=True, exist_ok=True)
    pd.set_option("display.width", 200)

    d = data.load_market()
    mkt = data.market_stats(d)
    dr, rec = data.moodys_tables()
    cr = credit.fit_credit(dr, rec)
    p0, term = credit.stress_prob(mkt["y0"])
    sim = simulate(mkt, cr, p0, np.random.default_rng(C.SEED))
    proj = credit.projection(sim)

    grid = portfolio.evaluate(sim, C.MAIN, portfolio.simplex(C.GRID_STEP))
    bench = portfolio.evaluate(sim, C.BENCH, portfolio.simplex(0.05))
    feas = grid[grid.feasible].sort_values("surplus_sharpe", ascending=False)
    best = feas.iloc[0]
    unc = bench.sort_values("surplus_sharpe").iloc[-1]
    muni = feas[feas.MUNI >= 0.5].iloc[0]
    w = best[list(C.MAIN)].values.astype(float)

    yearly = portfolio.yearly_returns(sim, C.MAIN, w)
    value = portfolio.value_projection(sim, C.MAIN, w)
    views = []
    for name, bp in C.CURVE_VIEWS.items():
        s = sim if bp is None else simulate(mkt, cr, p0, np.random.default_rng(C.SEED), tilt=C.curve_tilt(bp))
        views.append(portfolio.evaluate(s, C.MAIN, w[None]).assign(view=name))
    views = pd.concat(views, ignore_index=True)

    headline = pd.DataFrame([best, unc, muni], index=["best_feasible", "best_ignoring_rules", "best_muni_heavy"])
    for name, df in {"allocation_grid": grid, "headline_portfolios": headline, "credit_projection": proj,
                     "expected_return_by_year": yearly, "portfolio_value": value, "curve_views": views}.items():
        df.to_csv(C.OUT_DIR / f"{name}.csv", index=name == "headline_portfolios")

    plots.market(d)
    plots.credit(cr, dr, rec)
    plots.projection(proj, cr)
    plots.heatmap(grid, best)
    plots.frontier(grid, bench, best, unc)
    plots.funded_status(sim, [("best feasible", best, C.MAIN, plots.BLUE), ("best ignoring rules", unc, C.BENCH, plots.AQUA),
                              ("best muni-heavy", muni, C.MAIN, plots.ORANGE)])
    plots.expected_return(yearly, best, sim)
    plots.portfolio_value(value, best)
    plots.curve_views(views)

    P = cr["P"]
    print(f"Pricing date {mkt['date']:%Y-%m-%d}; 10y-1y {term:.2f}% -> P(stress 2027) {p0:.1%}")
    print(f"Recovery = {cr['rec_a']:.4f} {cr['rec_b']:+.4f} x SG default rate (R2 {cr['rec_r2']:.2f})")
    print(f"Regimes: P(benign->stress) {P[0, 1]:.3f}, P(stress->benign) {P[1, 0]:.3f}")
    print(f"Liabilities ${sim['L'][:, 0].mean():.2f}M -> starting funded status {C.ASSETS0 / sim['L'][:, 0].mean():.1%}")
    print("\nCredit projection:\n", proj.round(5).to_string(index=False))
    cols = list(C.MAIN) + ["mod_duration", "yield0", "exp_return_ann", "surplus_sharpe", "fs_end_mean",
                           "fs_end_median", "fs_end_p5", "fs_end_p95", "fs_vol_ann", "prob_underfunded_end"]
    print("\nTop feasible allocations:\n", feas[cols].head(5).round(4).to_string(index=False))
    print("\nHeadline portfolios:\n", headline.drop(columns="feasible").T.round(4).to_string())
    print("\nExpected return by year:\n", yearly.round(5).to_string(index=False))
    print("\nPortfolio value ($M):\n", value.iloc[::12].round(2).to_string(index=False))
    print("\nCurve views (chosen portfolio):\n", views[["view", "surplus_sharpe", "fs_end_mean", "fs_end_p5",
                                                        "prob_underfunded_end", "value_end_mean"]].round(4).to_string(index=False))
    print(f"\nDone in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
