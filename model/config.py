"""Every model input in one place.  Items marked ASSUMED are not in the data files."""
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DATA_XLSX = ROOT.parent / "fixed income data.xlsx"                  # Bloomberg pull
MOODYS_PDF = ROOT.parent / "default_and_recovery_rates_02_09.pdf"    # Moody's 1920-2008 study
OUT_DIR = ROOT / "output"
FIG_DIR = OUT_DIR / "figures"

# simulation
SEED, N_PATHS, YEARS = 2026, 5000, 5
MONTHS = 12 * YEARS
TENORS = np.array([1, 2, 3, 5, 7, 10, 20, 30], dtype=float)

# fund and liabilities
ASSETS0 = 100.0        # $M
PAYMENT = 6.0          # $M per year, paid monthly
LIAB_YEARS = 30        # level payments, discounted on the simulated Treasury curve

# competition rules
GOV_CAP = 0.15
DUR_RANGE = (4.0, 6.0)
GRID_STEP = 0.01

# Sleeves.  Treasuries are constant-maturity par bonds.  Index sleeves:
#   mod_dur      modified duration at the pricing date (ASSUMED: typical ICE index values)
#   match        Treasury tenors the base yield is taken from
#   spread       spread over base (ASSUMED: index yields are not in the pull)
#   ratio        yield = ratio * base + spread (ASSUMED muni/Treasury ratio for munis)
#   spread_beta  spread change per unit change in spec-grade default rate (Moody's Exh. 12)
#   mix          rating mix for default losses (ASSUMED: typical ICE IG index)
SLEEVES = {
    "UST2": dict(name="2y Treasury", tenor=2),
    "UST30": dict(name="30y Treasury", tenor=30),     # only for the "no rules" benchmark
    "CORP": dict(name="IG Corporate (C0A0)", mod_dur=6.6, match=[7, 10], spread=0.0090, ratio=1.0,
                 spread_beta=0.20, mix={"Aaa": .02, "Aa": .08, "A": .42, "Baa": .48}),
    "MUNI": dict(name="Municipal (U0A0)", mod_dur=6.2, match=[7, 10], spread=0.0, ratio=0.76,
                 spread_beta=0.06, pd={"benign": 1e-4, "stress": 5e-4}, recovery=0.60),  # ASSUMED
}
MAIN = ("UST2", "MUNI", "CORP")      # the allocation grid: government / municipal / corporate
BENCH = ("UST30", "MUNI", "CORP")    # same grid with long Treasuries, rules ignored

# credit-cycle model
FIT_START = 1970     # 1942-69 had ~zero defaults; fitting from 1920 finds that break, not cycles
SPREAD_AR = 0.90     # monthly persistence of spread noise

# Treasury drift in a stress year (bull steepener as the Fed cuts), demeaned across paths so the
# model carries no net rate view.  ASSUMED.
STRESS_DRIFT = np.interp(TENORS, [1, 10, 30], [-0.0125, -0.0070, -0.0050])

# curve views for the stress test: total yield change by Oct 2031 (bp) at 1y / 2y / 10y / 30y
CURVE_ANCHORS = [1, 2, 10, 30]
CURVE_VIEWS = {
    "Neutral (no view)": None,
    "Bull steepener": [-150, -150, -75, -50],
    "Bear steepener": [25, 25, 75, 125],
    "Bull flattener": [-25, -25, -75, -100],
    "Bear flattener": [150, 150, 75, 50],
}


def curve_tilt(bp):
    return None if bp is None else np.interp(TENORS, CURVE_ANCHORS, np.array(bp) / 1e4)
