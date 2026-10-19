"""Monthly Monte Carlo of the Treasury curve, credit regimes, spreads, default losses and liabilities."""
import numpy as np
from scipy.signal import lfilter

from . import config as C

T_IDX = {t: i for i, t in enumerate(C.TENORS)}


def par_bond_risk(y, n):
    """Modified duration and convexity of a semi-annual par bond with n years to maturity."""
    y = np.maximum(y, 1e-6)
    m = 2 * n

    def price(yy):
        return y / yy * (1 - (1 + yy / 2) ** -m) + (1 + yy / 2) ** -m

    e = 1e-4
    return (1 - (1 + y / 2) ** -m) / y, (price(y + e) + price(y - e) - 2) / e ** 2


def simulate(mkt, cr, p_stress0, rng, tilt=None):
    """tilt: optional curve view (total yield change by 2031 per tenor), added linearly."""
    N, M, Y5 = C.N_PATHS, C.MONTHS, C.YEARS

    # credit regime per year, then a Moody's year bootstrapped from the matching regime
    P = cr["P"]
    reg = np.empty((N, Y5), bool)
    reg[:, 0] = rng.random(N) < p_stress0
    for t in range(1, Y5):
        reg[:, t] = rng.random(N) < np.where(reg[:, t - 1], P[1, 1], P[0, 1])
    yrs = np.empty((N, Y5), int)
    for state, col in ((False, "benign"), (True, "stress")):
        mask = reg == state
        yrs[mask] = rng.choice(len(cr["dr"]), mask.sum(), p=(cr["weights"][col] / cr["weights"][col].sum()).values)
    DR = {r: cr["dr"][r].values[yrs] for r in cr["dr"]}
    RR = np.clip(cr["rec_a"] + cr["rec_b"] * DR["SG"] + cr["rec_sd"] * rng.standard_normal((N, Y5)), 0.05, 0.95)

    # Treasury curve: empirical covariance, stress-year rally demeaned across paths (no net view)
    stress_m = np.repeat(reg, 12, axis=1)[..., None] * (C.STRESS_DRIFT / 12)
    drift = stress_m - stress_m.mean(axis=0)
    if tilt is not None:
        drift = drift + tilt / M
    shocks = rng.standard_normal((N, M, len(C.TENORS))) @ np.linalg.cholesky(mkt["cov_m"]).T
    Y = np.concatenate([np.broadcast_to(mkt["y0"], (N, 1, len(C.TENORS))),
                        np.maximum(mkt["y0"] + np.cumsum(drift + shocks, axis=1), 5e-4)], axis=1)
    dY = np.diff(Y, axis=1)

    R, loss = {}, {}
    sg_m = np.repeat(DR["SG"], 12, axis=1)
    for key, s in C.SLEEVES.items():
        if "tenor" in s:                                          # Treasury, rolled monthly
            j = T_IDX[s["tenor"]]
            D, Cx = par_bond_risk(Y[:, :-1, j], s["tenor"])
            R[key] = Y[:, :-1, j] / 12 - D * dY[:, :, j] + 0.5 * Cx * dY[:, :, j] ** 2
            continue
        base = Y[:, :, [T_IDX[t] for t in s["match"]]].mean(axis=2)
        beta = min(mkt["rate_dur"][key] / s["mod_dur"], 1.0)      # spreads partly offset rate moves
        eps = mkt["resid_vol"][key] / s["mod_dur"] / np.sqrt(12) * rng.standard_normal((N, M))
        spread = np.concatenate([np.full((N, 1), s["spread"]), s["spread"] + s["spread_beta"] *
                                 (sg_m - cr["sg_benign"]) + lfilter([1], [1, -C.SPREAD_AR], eps, axis=1)], axis=1)
        if "mix" in s:
            loss[key] = sum(w * DR[r] for r, w in s["mix"].items()) * (1 - RR)
        else:
            loss[key] = np.where(reg, s["pd"]["stress"], s["pd"]["benign"]) * (1 - s["recovery"])
        dyld = beta * np.diff(base, axis=1) + np.diff(spread, axis=1)
        D = s["mod_dur"]
        R[key] = ((s["ratio"] * base + spread)[:, :-1] / 12 - D * dyld + 0.55 * D ** 2 * dyld ** 2
                  - np.repeat(loss[key], 12, axis=1) / 12)

    # liabilities: PV of remaining monthly payments on each path's zero curve
    pay = C.PAYMENT / 12
    tau = np.arange(1, 12 * C.LIAB_YEARS + 1) / 12
    k = np.clip(np.searchsorted(C.TENORS, tau) - 1, 0, len(C.TENORS) - 2)
    wk = np.clip((tau - C.TENORS[k]) / (C.TENORS[k + 1] - C.TENORS[k]), 0, 1)
    Z = 2 * np.log1p(Y / 2)                                       # par ~ zero, continuous comp.
    L = np.empty((N, M + 1))
    for t in range(M + 1):
        n = len(tau) - t
        z = Z[:, t, k[:n]] * (1 - wk[:n]) + Z[:, t, k[:n] + 1] * wk[:n]
        L[:, t] = pay * np.exp(-z * tau[:n]).sum(axis=1)

    return dict(R=R, L=L, RL=(L[:, 1:] + pay) / L[:, :-1] - 1, reg=reg, DR=DR, RR=RR, loss=loss, y0=mkt["y0"])
