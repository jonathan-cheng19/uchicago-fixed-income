"""Load the Bloomberg pull and the Moody's tables."""
import re

import numpy as np
import pandas as pd
from pypdf import PdfReader

from . import config as C

UST = [f"UST{t:g}" for t in C.TENORS]
RATINGS = ["Aaa", "Aa", "A", "Baa", "Ba", "B", "CaaC", "IG", "SG", "All"]


def load_market():
    """Daily yields (%) and ICE total-return index levels; holiday/weekend fill rows dropped."""
    x = pd.read_excel(C.DATA_XLSX, header=None).iloc[2:]
    x.columns = ["date", *UST, "CORP", "TEL15", "MUNI"]
    d = x.set_index(pd.to_datetime(x.pop("date").astype(float), unit="D", origin="1899-12-30")).astype(float)
    keep = d.diff().abs().sum(axis=1) > 0
    keep.iloc[0] = True
    return d[keep]


def market_stats(d):
    """Pricing-date curve, monthly covariance of curve moves, and each index's empirical rate
    sensitivity (average of weekly and monthly regressions on its matched Treasury yield)."""
    weekly = d.resample("W-FRI").last()
    cov_m = np.cov(weekly[UST].diff().dropna().values.T / 100) * 52 / 12
    rate_dur, resid_vol = {}, {}
    for key in ("CORP", "MUNI"):
        est = []
        for freq, per_yr in (("W-FRI", 52), ("ME", 12)):
            w = d.resample(freq).last()
            r = np.log(w[key]).diff().dropna()
            x = w[[f"UST{t}" for t in C.SLEEVES[key]["match"]]].mean(axis=1).diff().dropna() / 100
            b, a = np.polyfit(x, r, 1)
            est.append((-b, (r - a - b * x).std() * np.sqrt(per_yr)))
        rate_dur[key], resid_vol[key] = np.mean(est, axis=0)
    return dict(date=d.index[-1], y0=d[UST].iloc[-1].values / 100, cov_m=cov_m,
                rate_dur=rate_dur, resid_vol=resid_vol)


def moodys_tables():
    """Exhibit 36 (annual default rates by rating, 1920-2008) and Exhibit 26 (sr. unsecured
    recovery rates, 1982-2008), parsed straight from the PDF."""
    text = "\n".join(p.extract_text() or "" for p in PdfReader(C.MOODYS_PDF).pages)

    seg = text[text.index("Exhibit 36"):text.index("Exhibit 37")]
    rows = {}
    for line in seg.splitlines():
        tok = line.split()
        if not tok or not re.fullmatch(r"19[2-6]\d", tok[0]):
            continue
        cut = next((i for i, t in enumerate(tok) if i and re.fullmatch(r"19[6-9]\d|200\d", t)), len(tok))
        for half in filter(None, (tok[:cut], tok[cut:])):        # two years per printed line (1964 alone)
            vals = [float(v) for v in half[1:]]
            if len(vals) == 9:                                   # 1920 has no Caa-C entry
                vals.insert(6, np.nan)
            rows[int(half[0])] = vals
    dr = pd.DataFrame.from_dict(rows, orient="index", columns=RATINGS).sort_index() / 100

    seg = text[text.index("Exhibit 26"):text.index("Exhibit 27")]
    rec = pd.Series({int(t[0]): float(t[3].rstrip("%")) / 100 for t in map(str.split, seg.splitlines())
                     if t and re.fullmatch(r"198[2-9]|199\d|200\d", t[0])}).sort_index()

    assert len(dr) == 89 and len(rec) == 27, "Moody's tables did not parse as expected"
    return dr, rec
