"""Allocation grid, portfolio paths and surplus / funded-status metrics."""
import numpy as np
import pandas as pd

from . import config as C
from .simulation import T_IDX, par_bond_risk


def sleeve_yield(key, y0):
    s = C.SLEEVES[key]
    if "tenor" in s:
        return y0[T_IDX[s["tenor"]]]
    return s["ratio"] * np.mean([y0[T_IDX[t]] for t in s["match"]]) + s["spread"]


def sleeve_duration(key, y0):
    s = C.SLEEVES[key]
    return float(par_bond_risk(y0[T_IDX[s["tenor"]]], s["tenor"])[0]) if "tenor" in s else s["mod_dur"]


def simplex(step):
    """Every (w1, w2, w3) on the given step that sums to 1."""
    n = int(round(1 / step))
    return np.array([(i, j, n - i - j) for i in range(n + 1) for j in range(n + 1 - i)]) / n


def asset_paths(rA):
    """Monthly-rebalanced fund: grow by the portfolio return, then pay the benefit.  rA: (..., M)."""
    A = np.empty(rA.shape[:-1] + (C.MONTHS + 1,))
    A[..., 0] = C.ASSETS0
    for t in range(C.MONTHS):
        A[..., t + 1] = np.maximum(A[..., t] * (1 + rA[..., t]) - C.PAYMENT / 12, 0.0)
    return A


def portfolio_returns(sim, keys, w):
    return sum(wi * sim["R"][k] for wi, k in zip(w, keys))


def evaluate(sim, keys, W, batch=25):
    """Metrics for every weight row in W (columns follow keys)."""
    R = np.stack([sim["R"][k] for k in keys])
    L, RL = sim["L"], sim["RL"]
    yld = np.array([sleeve_yield(k, sim["y0"]) for k in keys])
    dur = np.array([sleeve_duration(k, sim["y0"]) for k in keys])
    loss = np.array([sim["loss"][k].mean() if k in sim["loss"] else 0.0 for k in keys])
    out = []
    for s in range(0, len(W), batch):
        Wb = W[s:s + batch]
        rA = np.einsum("ks,snm->knm", Wb, R)
        A = asset_paths(rA)
        FS = A / L
        rS = rA - L[:, :-1] / np.maximum(A[..., :-1], 1e-9) * RL     # surplus return per $ of assets
        mu, sd = rS.mean(axis=(1, 2)) * 12, rS.std(axis=(1, 2)) * np.sqrt(12)
        end = FS[..., -1]
        p5, p50, p95 = np.percentile(end, [5, 50, 95], axis=1)
        out.append(pd.DataFrame({
            **{k: Wb[:, i] for i, k in enumerate(keys)},
            "yield0": Wb @ yld, "exp_default_loss": Wb @ loss, "mod_duration": Wb @ dur,
            "exp_return_ann": ((np.prod(1 + rA, axis=2) ** (1 / C.YEARS)) - 1).mean(axis=1),
            "surplus_ret_ann": mu, "surplus_vol_ann": sd, "surplus_sharpe": mu / sd,
            "fs_end_mean": end.mean(axis=1), "fs_end_median": p50, "fs_end_p5": p5, "fs_end_p95": p95,
            "fs_end_std": end.std(axis=1), "fs_vol_ann": np.diff(FS, axis=2).std(axis=(1, 2)) * np.sqrt(12),
            "prob_underfunded_end": (end < 1).mean(axis=1), "value_end_mean": A[..., -1].mean(axis=1)}))
    df = pd.concat(out, ignore_index=True)
    gov = sum(df[k] for k in keys if "tenor" in C.SLEEVES[k])
    df["feasible"] = (gov <= C.GOV_CAP + 1e-9) & df["mod_duration"].between(*C.DUR_RANGE)
    return df


def yearly_returns(sim, keys, w):
    """Yield, expected default loss and simulated total return by year for one allocation."""
    w = np.asarray(w)
    yld = w @ [sleeve_yield(k, sim["y0"]) for k in keys]
    loss = sum(wi * sim["loss"][k] for wi, k in zip(w, keys) if k in sim["loss"]).mean(axis=0)
    ann = np.prod(1 + portfolio_returns(sim, keys, w).reshape(-1, C.YEARS, 12), axis=2) - 1
    p5, p95 = np.percentile(ann, [5, 95], axis=0)
    return pd.DataFrame({"year": np.arange(2027, 2027 + C.YEARS), "portfolio_yield": yld,
                         "expected_default_loss": loss, "expected_return_after_defaults": yld - loss,
                         "sim_return_mean": ann.mean(axis=0), "sim_return_p5": p5, "sim_return_p95": p95})


def value_projection(sim, keys, w):
    """Mean portfolio value with 50% and 95% bands, plus benefits paid to date."""
    A = asset_paths(portfolio_returns(sim, keys, w))
    q = np.percentile(A, [2.5, 25, 75, 97.5], axis=0)
    months = np.arange(C.MONTHS + 1)
    return pd.DataFrame({"month": months, "mean": A.mean(axis=0), "p2_5": q[0], "p25": q[1], "p75": q[2],
                         "p97_5": q[3], "mean_ci95_halfwidth": 1.96 * A.std(axis=0) / np.sqrt(len(A)),
                         "benefits_paid": C.PAYMENT / 12 * months})
