"""Run the full study: load and check the data, fit the credit model, simulate, test every allocation,
write results and figures."""
import time

import numpy as np
import pandas as pd

from model import bonds, credit, data, market, plots, portfolio
from model import config as C
from model.simulation import simulate


def build_inputs():
    """Market data, credit model and the bond-level tower sleeve; fills the data-derived sleeve fields."""
    d = data.load_market()
    mkt = data.market_stats(d)
    dr, rec = data.moodys_tables()
    cr = credit.fit_credit(dr, rec)
    p0, term = credit.stress_prob(d)

    for key in ("UST2", "UST30"):                                  # Bloomberg modified duration, pricing date
        C.SLEEVES[key]["mod_dur"] = float(mkt["ust_dur"][list(C.TENORS).index(C.SLEEVES[key]["tenor"])])

    full, oas = bonds.load_bonds()
    tab = bonds.bond_table(full, oas, mkt["y0"], mkt["ust_dur"], mkt["date"])
    tw = bonds.tower_sleeve(full, oas, tab, d, mkt["y0"], mkt["ust_dur"], C.SLEEVES["CORP"]["spread"],
                            C.SLEEVES["CORP"]["spread_beta"])
    C.SLEEVES["TOWER"].update(mod_dur=tw["mod_dur"], match=tw["match"], spread=tw["spread"], spread_beta=tw["spread_beta"])
    mkt["rate_dur"]["TOWER"] = tw["rate_beta"] * tw["mod_dur"]
    mkt["resid_vol"]["TOWER"] = tw["spread_vol"] * tw["mod_dur"]     # simulation divides by mod_dur again
    return d, mkt, dr, rec, cr, p0, term, full, oas, tab, tw


def inputs_table(mkt, cr, p0, term, tw, spreads, beta_ig_hy, dts):
    """Every number the simulation uses, with where it came from."""
    S, y0 = C.SLEEVES, mkt["y0"]
    rows = [("Pricing date", f"{mkt['date']:%Y-%m-%d}", "Data: Bloomberg")]
    rows += [(f"Treasury {l} yield", f"{y:.3%}", "Data: Bloomberg USGG generic") for l, y in zip(C.TENOR_LABELS, y0)]
    rows += [(f"Treasury {l} modified duration", f"{v:.3f}", f"{'Data: Bloomberg' if s == 'Bloomberg' else 'Computed: par-bond formula'}")
             for l, v, s in zip(C.TENOR_LABELS, mkt["ust_dur"], mkt["ust_dur_src"])]
    rows += [("Curve covariance window", f"{mkt['cov_window'][0]:%Y-%m-%d} to {mkt['cov_window'][1]:%Y-%m-%d} "
              f"({mkt['n_weeks']} weekly changes)", "Estimated"),
             ("10y-3m spread (1-month average)", f"{term:.3f} pp", "Data: Bloomberg"),
             ("P(credit-stress year) 2027", f"{p0:.1%}", "Estimated: NY Fed probit"),
             ("P(benign -> stress), P(stress -> benign)", f"{cr['P'][0, 1]:.3f}, {cr['P'][1, 0]:.3f}", "Estimated: HMM on Moody's"),
             ("Recovery model", f"{cr['rec_a']:.4f} {cr['rec_b']:+.4f} x SG default rate, resid sd {cr['rec_sd']:.3f}",
              "Estimated: Moody's Exh. 26 vs 36")]
    rows += [(f"Stress-year Treasury drift {l}", f"{v * 1e4:+.0f} bp", "Estimated: NBER recessions 2007-08, 2020"
              if ok else "Interpolated between observed tenors")
             for l, v, ok in zip(C.TENOR_LABELS, mkt["stress_drift"], mkt["stress_tenors_ok"])]
    for k in ("CORP", "MUNI", "TOWER"):
        s = S[k]
        src = "Data: bond-level PDFs" if k == "TOWER" else "ASSUMED"
        rows += [(f"{s['name']}: yield", f"{portfolio.sleeve_yield(k, y0):.3%}", src),
                 (f"{s['name']}: modified duration", f"{s['mod_dur']:.2f}", src),
                 (f"{s['name']}: rate beta (empirical / mod. duration)",
                  f"{min(mkt['rate_dur'][k] / s['mod_dur'], 1):.3f}", "Estimated"),
                 (f"{s['name']}: spread_beta", f"{s['spread_beta']:.3f}",
                  "Estimated: IG assumption x DTS ratio" if k == "TOWER" else "ASSUMED")]
    rows += [("Tower sleeve: bonds, average OAS", f"{tw['n_bonds']} bonds, {tw['oas_bp']:.1f} bp", "Data: bond-level PDFs"),
             ("Tower sleeve: spread volatility (monthly OAS changes)", f"{tw['spread_vol'] * 1e4:.1f} bp/yr", "Estimated"),
             ("DTS check: relative spread vol, tower OAS vs CDX IG", f"{dts[0]:.2f} vs {dts[1]:.2f}", "Estimated"),
             ("CDX IG / HY 5y spread", f"{spreads['IG'].iloc[-1] * 1e4:.1f} / {spreads['HY'].iloc[-1] * 1e4:.1f} bp", "Data / Estimated (HY from price)"),
             ("IG spread sensitivity cross-check (CDX beta x Moody's Exh. 12)", f"{beta_ig_hy[1]:.3f} (assumed {S['CORP']['spread_beta']:.2f})", "Estimated")]
    return pd.DataFrame(rows, columns=["input", "value", "source"])


def main():
    t0 = time.time()
    C.FIG_DIR.mkdir(parents=True, exist_ok=True)
    pd.set_option("display.width", 220)
    pd.set_option("display.max_columns", 30)

    d, mkt, dr, rec, cr, p0, term, full, oas, tab, tw = build_inputs()
    sim = simulate(mkt, cr, p0, np.random.default_rng(C.SEED))
    proj = credit.projection(sim)

    simplex = portfolio.simplex(C.GRID_STEP)
    grid = portfolio.evaluate(sim, C.MAIN, simplex)
    sector = portfolio.evaluate(sim, C.SECTOR, simplex)
    bench = portfolio.evaluate(sim, C.BENCH, portfolio.simplex(0.05))
    feas = grid[grid.feasible].sort_values("surplus_sharpe", ascending=False)
    feas_s = sector[sector.feasible].sort_values("surplus_sharpe", ascending=False)
    best, best_s = feas.iloc[0], feas_s.iloc[0]
    unc = bench.sort_values("surplus_sharpe").iloc[-1]
    muni = feas[feas.MUNI >= 0.5].iloc[0]
    w = best[list(C.MAIN)].values.astype(float)

    # does splitting the chosen corporate weight between the index and the tower sleeve help?
    keys4 = ("UST2", "MUNI", "CORP", "TOWER")
    split = np.array([[best.UST2, best.MUNI, best.CORP * (1 - f), best.CORP * f] for f in np.linspace(0, 1, 11)])
    mix = portfolio.evaluate(sim, keys4, split).assign(tower_share_of_corporate=np.linspace(0, 1, 11))

    yearly = portfolio.yearly_returns(sim, C.MAIN, w)
    value = portfolio.value_projection(sim, C.MAIN, w)
    views = []
    for name, bp in C.CURVE_VIEWS.items():
        s = sim if bp is None else simulate(mkt, cr, p0, np.random.default_rng(C.SEED), tilt=C.curve_tilt(bp))
        views.append(portfolio.evaluate(s, C.MAIN, w[None]).assign(view=name))
    views = pd.concat(views, ignore_index=True)

    spreads = market.cdx_spreads(d)
    model_dr = {r: proj[r].mean() for r in ("IG", "SG")}
    implied = market.implied_defaults(spreads, model_dr)
    beta_ig_hy = market.ig_hy_beta(spreads)
    path, be = market.policy_path(d), market.breakevens(d)
    fc = market.forecast_2031(d, mkt["y0"], sim)
    macro, idx = market.macro_dashboard(d, spreads), market.index_history(d)
    cdx_win = spreads["IG"].loc[tw["oas_series"].index[0]:tw["oas_series"].index[-1]]
    dts = (tw["spread_vol"] / tw["oas_series"].mean(),
           cdx_win.resample("ME").last().diff().std() * np.sqrt(12) / cdx_win.mean())
    inputs = inputs_table(mkt, cr, p0, term, tw, spreads, beta_ig_hy, dts)

    headline = pd.DataFrame([best, best_s, unc, muni],
                            index=["best_feasible", "best_feasible_tower_sleeve", "best_ignoring_rules", "best_muni_heavy"])
    outputs = {"model_inputs": inputs, "allocation_grid": grid, "allocation_grid_tower": sector,
               "headline_portfolios": headline, "corporate_split": mix, "credit_projection": proj,
               "expected_return_by_year": yearly, "portfolio_value": value, "curve_views": views,
               "bond_universe": tab, "policy_path": path, "forecast_2031": fc, "implied_defaults": implied,
               "macro_dashboard": macro, "index_history": idx}
    for name, df in outputs.items():
        df.to_csv(C.OUT_DIR / f"{name}.csv", index=name in ("headline_portfolios", "bond_universe", "index_history"))

    plots.market(d, mkt)
    plots.credit(cr, dr, rec)
    plots.projection(proj, cr)
    plots.heatmap(grid, best)
    plots.frontier(grid, sector, bench, best, best_s, unc)
    plots.funded_status(sim, [("best feasible", best, C.MAIN, plots.BLUE), ("best, tower sleeve", best_s, C.SECTOR, plots.YELLOW),
                              ("best ignoring rules", unc, C.BENCH, plots.AQUA), ("best muni-heavy", muni, C.MAIN, plots.ORANGE)])
    plots.expected_return(yearly, best, sim)
    plots.portfolio_value(value, best)
    plots.curve_views(views)
    plots.index_history(idx)
    plots.tower(tab, tw, spreads, mkt)
    plots.market_pricing(d, mkt, path, be, fc, implied)

    print(f"Pricing date {mkt['date']:%Y-%m-%d}; 10y-3m (1-month avg) {term:.2f} pp -> P(stress 2027) {p0:.1%}")
    print(f"Recovery = {cr['rec_a']:.4f} {cr['rec_b']:+.4f} x SG default rate (R2 {cr['rec_r2']:.2f})")
    print(f"Regimes: P(benign->stress) {cr['P'][0, 1]:.3f}, P(stress->benign) {cr['P'][1, 0]:.3f}")
    print(f"Liabilities ${sim['L'][:, 0].mean():.2f}M -> starting funded status {C.ASSETS0 / sim['L'][:, 0].mean():.1%}")
    print("\nModel inputs:\n", inputs.to_string(index=False))
    print("\nBond universe (pricing date):\n", tab.drop(columns=["history_from"]).round(4).to_string())
    print("\nCredit projection:\n", proj.round(5).to_string(index=False))
    cols = list(C.MAIN) + ["mod_duration", "yield0", "exp_return_ann", "surplus_sharpe", "fs_end_mean",
                           "fs_end_median", "fs_end_p5", "fs_end_p95", "fs_vol_ann", "prob_underfunded_end"]
    print("\nTop feasible allocations:\n", feas[cols].head(5).round(4).to_string(index=False))
    cols_s = [c if c != "CORP" else "TOWER" for c in cols]
    print("\nTop feasible allocations, tower sleeve:\n", feas_s[cols_s].head(5).round(4).to_string(index=False))
    print("\nHeadline portfolios:\n", headline.drop(columns="feasible").T.round(4).to_string())
    print("\nSplitting the corporate weight between C0A0 and the tower sleeve:\n",
          mix[["tower_share_of_corporate", "yield0", "mod_duration", "surplus_sharpe", "fs_end_mean", "fs_vol_ann",
               "prob_underfunded_end"]].round(4).to_string(index=False))
    print("\nExpected return by year:\n", yearly.round(5).to_string(index=False))
    print("\nPortfolio value ($M):\n", value.iloc[::12].round(2).to_string(index=False))
    print("\nCurve views (chosen portfolio):\n", views[["view", "surplus_sharpe", "fs_end_mean", "fs_end_p5",
                                                        "prob_underfunded_end", "value_end_mean"]].round(4).to_string(index=False))
    print("\nMarket-implied policy path:\n", path.round(3).to_string(index=False))
    print("\nBreakeven inflation (%):", {k: round(v, 3) for k, v in be.items()})
    print("\nForecast for October 2031:\n", fc.round(4).to_string(index=False))
    print("\nCDX-implied vs model default rates:\n", implied.round(5).to_string(index=False))
    print(f"CDX IG/HY weekly beta {beta_ig_hy[0]:.3f} -> IG spread sensitivity to SG default {beta_ig_hy[1]:.3f}")
    print("\nMacro dashboard:\n", macro.round(3).to_string(index=False))
    print("\nICE index history 2006-2026:\n", idx.round(4).to_string())
    print(f"\nDone in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
