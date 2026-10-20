"""Every model input in one place.  Items marked ASSUMED are not in the data files; everything else is
read or estimated from the Bloomberg pull, the bond-level PDFs or the Moody's study at run time."""
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DATA_CSV = ROOT.parent / "fixed income mega data.csv"                # Bloomberg pull, daily 2006-2026
BOND_PDFS = [ROOT.parent / "FILE_1065.pdf",                          # 17 bonds: OAS, bid/mid/ask, YTW, mod. dur.
             ROOT.parent / "ddd (1).pdf fff.pdf"]                    # 10 bonds: OAS history
MOODYS_PDF = ROOT.parent / "default_and_recovery_rates_02_09.pdf"    # Moody's 1920-2008 study
OUT_DIR = ROOT / "output"
FIG_DIR = OUT_DIR / "figures"

# simulation
SEED, N_PATHS, YEARS = 2026, 5000, 5
MONTHS = 12 * YEARS
TENOR_LABELS = ["1m", "3m", "6m", "1", "2", "3", "5", "7", "10", "20", "30"]
TENORS = np.array([1 / 12, 0.25, 0.5, 1, 2, 3, 5, 7, 10, 20, 30])
COV_YEARS = 5          # window for the curve covariance and index rate betas = the simulation horizon

# fund and liabilities
ASSETS0 = 100.0        # $M
PAYMENT = 6.0          # $M per year, paid monthly
LIAB_YEARS = 30        # level payments, discounted on the simulated Treasury curve

# competition rules
GOV_CAP = 0.15
DUR_RANGE = (4.0, 6.0)
GRID_STEP = 0.01

# Sleeves.  Treasuries are constant-maturity par bonds; their pricing-date modified duration is
# Bloomberg's (filled in at run time).  Index sleeves:
#   mod_dur      modified duration at the pricing date (ASSUMED for the ICE indices: typical index values)
#   match        Treasury tenors the base yield is taken from
#   spread       spread over base (ASSUMED for the ICE indices: their yields are not in the pull)
#   ratio        yield = ratio * base + spread (ASSUMED muni/Treasury ratio for munis)
#   spread_beta  spread change per unit change in spec-grade default rate (ASSUMED, guided by Moody's Exh. 12)
#   mix          rating mix for default losses
# TOWER is built from bond-level data: yield, duration, spread, spread volatility and rate beta all come
# from the PDFs (bonds.tower_sleeve); only its rating is ASSUMED.
SLEEVES = {
    "UST2": dict(name="2y Treasury", tenor=2),
    "UST30": dict(name="30y Treasury", tenor=30),     # only for the "no rules" benchmark
    "CORP": dict(name="IG Corporate (C0A0)", mod_dur=6.6, match=[7, 10], spread=0.0090, ratio=1.0,
                 spread_beta=0.20, mix={"Aaa": .02, "Aa": .08, "A": .42, "Baa": .48}),
    "MUNI": dict(name="Municipal (U0A0)", mod_dur=6.2, match=[7, 10], spread=0.0, ratio=0.76,
                 spread_beta=0.06, pd={"benign": 1e-4, "stress": 5e-4}, recovery=0.60),  # ASSUMED
    "TOWER": dict(name="Baa Tower Corporate", ratio=1.0, mix={"Baa": 1.0}),               # rating ASSUMED
}
MAIN = ("UST2", "MUNI", "CORP")      # the allocation grid: government / municipal / corporate (ICE index)
SECTOR = ("UST2", "MUNI", "TOWER")   # same grid with the bond-level tower sleeve as the corporate position
BENCH = ("UST30", "MUNI", "CORP")    # same grid with long Treasuries, rules ignored

# Bond-level universe (CUSIP issuer prefixes 03027X = American Tower, 22822V = Crown Castle).  Only USD
# bonds that pass the currency check and have YTW and duration on the pricing date enter the sleeve.
TOWER_ISSUERS = ("03027X", "22822V")
USD_CHECK_FLOOR = 0.040   # YTW - OAS below this cannot be a USD benchmark (lowest US Treasury yield: 3.99%, 1m)

# credit-cycle model
FIT_START = 1970     # 1942-69 had ~zero defaults; fitting from 1920 finds that break, not cycles
SPREAD_AR = 0.90     # monthly persistence of spread noise
CDX_RECOVERY = {"IG": 0.40, "HY": 0.30}   # ISDA standard-model conventions for CDX quotes

# Treasury drift in a stress year: the average 12-month yield change after the two NBER business-cycle
# peaks in the sample, demeaned across paths so the model carries no net rate view.
NBER_PEAKS = ["2007-12", "2020-02"]

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
