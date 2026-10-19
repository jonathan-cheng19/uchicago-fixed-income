"""Credit cycle (2-state HMM on Moody's defaults), recovery model and current-regime probability."""
import numpy as np
import pandas as pd
from scipy.stats import norm

from . import config as C


def fit_hmm(y, n_iter=500, tol=1e-9):
    """Baum-Welch for a 2-state Gaussian HMM.  Returns transition matrix and smoothed state
    probabilities, ordered [benign, stress]."""
    mu, sd = np.percentile(y, [30, 85]), np.full(2, 0.6 * y.std())
    P, pi = np.array([[0.85, 0.15], [0.35, 0.65]]), np.array([0.7, 0.3])
    for _ in range(n_iter):
        B = norm.pdf(y[:, None], mu, sd)
        a, c = np.empty_like(B), np.empty(len(y))
        for t in range(len(y)):
            a[t] = (pi if t == 0 else a[t - 1] @ P) * B[t]
            c[t] = a[t].sum()
            a[t] /= c[t]
        b = np.ones_like(B)
        for t in range(len(y) - 2, -1, -1):
            b[t] = P @ (B[t + 1] * b[t + 1]) / c[t + 1]
        g = a * b
        xi = a[:-1, :, None] * P * (B[1:] * b[1:])[:, None, :] / c[1:, None, None]
        P_new = xi.sum(0) / xi.sum((0, 2))[:, None]
        mu_new = g.T @ y / g.sum(0)
        sd = np.maximum(np.sqrt((g * (y[:, None] - mu_new) ** 2).sum(0) / g.sum(0)), 0.05)
        done = max(np.abs(P_new - P).max(), np.abs(mu_new - mu).max()) < tol
        P, mu, pi = P_new, mu_new, g[0]
        if done:
            break
    return (P[::-1, ::-1], g[:, ::-1]) if mu[0] > mu[1] else (P, g)


def fit_credit(dr, rec):
    """Regimes from the spec-grade default rate (FIT_START-2008), regime-conditional default
    rates by rating, and recovery = a + b * spec-grade default rate (Moody's Exh. 9 form)."""
    dr = dr.loc[C.FIT_START:]
    P, g = fit_hmm(np.log(dr["SG"].values + 1e-3))
    w = pd.DataFrame(g, index=dr.index, columns=["benign", "stress"])
    cond = pd.DataFrame({s: dr.mul(w[s], axis=0).sum() / w[s].sum() for s in w})
    x = dr["SG"].loc[rec.index]
    b, a = np.polyfit(x, rec, 1)
    resid = rec - (a + b * x)
    return dict(dr=dr, P=P, weights=w, cond=cond, rec_a=a, rec_b=b, rec_sd=resid.std(ddof=2),
                rec_r2=1 - resid.var() / rec.var(), sg_benign=cond.loc["SG", "benign"])


def stress_prob(y0):
    """NY Fed / Estrella-Mishkin probit on the 10y - 3m spread; the 1y bill stands in for 3m."""
    term = (y0[list(C.TENORS).index(10)] - y0[0]) * 100
    return float(norm.cdf(-0.5333 - 0.6330 * term)), term


def projection(sim):
    """Expected default rates, recovery and sleeve losses by year in the simulated regimes."""
    rows = []
    for y in range(C.YEARS):
        row = {"year": 2027 + y, "p_stress": sim["reg"][:, y].mean(), "recovery": sim["RR"][:, y].mean()}
        row |= {r: sim["DR"][r][:, y].mean() for r in ["A", "Baa", "Ba", "B", "IG", "SG"]}
        row |= {f"loss_{k}": v[:, y].mean() for k, v in sim["loss"].items()}
        rows.append(row)
    return pd.DataFrame(rows)
