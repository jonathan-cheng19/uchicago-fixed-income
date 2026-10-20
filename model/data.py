"""Load the Bloomberg pull and the Moody's tables."""
import csv
import re

import numpy as np
import pandas as pd
from pypdf import PdfReader

from . import config as C

UST = [f"UST{l}" for l in C.TENOR_LABELS]
RATINGS = ["Aaa", "Aa", "A", "Baa", "Ba", "B", "CaaC", "IG", "SG", "All"]

# Bloomberg ticker -> model column.  Index levels are ICE BofA total-return indices.
INDICES = {"C0A0": "CORP", "U0A0": "MUNI", "C8R0": "TEL15", "H0A0": "HY",
           "C0A1": "CORP_AAA", "C0A2": "CORP_AA", "C0A3": "CORP_A", "C0A4": "CORP_BBB",
           "C1A0": "CORP_1_3", "C2A0": "CORP_3_5", "C3A0": "CORP_5_7", "C4A0": "CORP_7_10", "C9A0": "CORP_10P"}
OTHER = {"FDTR": "FED_UPPER", "USURTOT": "UNEMP", "INJCJC": "CLAIMS", "NAPMPMI": "PMI", "IP CHNG": "IP_MOM",
         "GDP CQOQ": "GDP_QOQ", "BFCIUS": "BFCI", "VIX": "VIX", "CPI YOY": "CPI_YOY",
         "CDX IG CDSI GEN 5Y Corp": "CDX_IG", "CDX HY CDSI GEN 5Y Corp": "CDX_HY_PX"}
BILL = {"1M": "1m", "3M": "3m", "6M": "6m", "12M": "1"}


def _tenor(ticker):
    """'USGG10YR Index' -> '10', 'USGG3M Index' -> '3m'."""
    t = ticker.split()[0][4:]
    return BILL[t] if t in BILL else t.replace("YR", "")


def load_market():
    """Daily Bloomberg pull, 2006-2026.  The sheet has two header rows (ticker, field) with the ticker
    written only above the first of its fields.  Known quirks, handled here:
      * the first yield block's 20y and 30y px_last cells are date-formatted (e.g. '1/5/1900'), so yields
        come from the clean second block of px_last columns;
      * the USGG12M block (yield, duration, convexity) sits one row below its dates and is shifted back;
      * weekend and holiday rows repeat the previous value and are dropped."""
    with open(C.DATA_CSV, encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
    h1, h2, body = rows[0], rows[1], rows[2:]
    raw = pd.DataFrame(body).replace({"#N/A": np.nan, "": np.nan}).apply(pd.to_numeric, errors="coerce")
    dated = np.array([r[0] != "" for r in body])
    cols, start = {}, 0
    for i in range(1, len(h1)):
        if h1[i]:
            start = i                                                 # first column of this ticker's block
        ticker = h1[start]
        field = h2[i] or ["px_last", "#mod_dur", "#cnvx"][i - start]  # the USGG12M block has no field row
        col = raw[i]
        if not h2[i]:
            col = col.shift(-1)                                       # ...and is printed one row late
        key = (ticker, "px_clean") if (ticker, field) in cols else (ticker, field)   # second yield block
        cols[key] = col
    df = pd.DataFrame(cols)[dated]
    df.index = pd.to_datetime([r[0] for r in body if r[0]], format="%m/%d/%Y")

    out = pd.DataFrame(index=df.index)
    for (tk, fld), s in df.items():
        if tk.startswith("USGG") and not tk.startswith("USGGT"):
            t = _tenor(tk)
            if fld == "px_clean" or (fld == "px_last" and (tk, "px_clean") not in df):
                out[f"UST{t}"] = s
            elif fld == "#mod_dur":
                out[f"DUR{t}"] = s
            elif fld == "#cnvx":
                out[f"CNVX{t}"] = s
        elif tk.startswith("USGGT"):
            t = tk[5:7].lstrip("0")
            out[{"px_last": f"TIPS{t}", "#mod_dur": f"TIPSDUR{t}", "#cnvx": f"TIPSCNVX{t}"}[fld]] = s
        elif tk.split()[0] in INDICES:
            out[INDICES[tk.split()[0]]] = s
        elif tk.startswith(("FF", "SFR")):
            name = tk.split()[0]
            out[name if fld == "px_last" else f"{name}_RATE"] = s
        else:
            out[OTHER[tk.replace(" Index", "")]] = s
    trade = out[UST + list(INDICES.values())]
    keep = trade.diff().abs().sum(axis=1) > 0
    keep.iloc[0] = True
    return out[keep]


def market_stats(d):
    """Pricing-date curve and analytics, monthly covariance of curve moves over the last COV_YEARS
    (weekly changes), each index's empirical rate sensitivity (average of weekly and monthly regressions
    on its matched Treasury yield), and the stress-year Treasury drift from the NBER recessions."""
    from .simulation import par_bond_risk

    date = d.index[-1]
    win = d.loc[date - pd.DateOffset(years=C.COV_YEARS):]
    weekly = win.resample("W-FRI").last()
    chg = weekly[UST].diff().dropna()
    cov_m = np.cov(chg.values.T / 100) * 52 / 12

    rate_dur, resid_vol = {}, {}
    for key in ("CORP", "MUNI"):
        est = []
        for freq, per_yr in (("W-FRI", 52), ("ME", 12)):
            w = win.resample(freq).last()
            r = np.log(w[key]).diff().dropna()
            x = w[[f"UST{t}" for t in C.SLEEVES[key]["match"]]].mean(axis=1).diff().dropna() / 100
            b, a = np.polyfit(x, r, 1)
            est.append((-b, (r - a - b * x).std() * np.sqrt(per_yr)))
        rate_dur[key], resid_vol[key] = np.mean(est, axis=0)

    y0 = d[UST].iloc[-1].values / 100
    dur = np.array([d[f"DUR{l}"].iloc[-1] if f"DUR{l}" in d else np.nan for l in C.TENOR_LABELS])
    cnvx = np.array([d[f"CNVX{l}"].iloc[-1] * 100 if f"CNVX{l}" in d else np.nan for l in C.TENOR_LABELS])
    calc = np.array([par_bond_risk(y, t) for y, t in zip(y0, C.TENORS)])
    dur_src = np.where(np.isnan(dur), "computed", "Bloomberg")
    dur, cnvx = np.where(np.isnan(dur), calc[:, 0], dur), np.where(np.isnan(cnvx), calc[:, 1], cnvx)

    m = d[UST].resample("ME").last()
    moves = []
    for peak in C.NBER_PEAKS:
        p = pd.Period(peak, "M")
        moves.append((m.loc[str(p + 12)].iloc[0] - m.loc[str(p)].iloc[0]).values / 100)
    moves = np.array(moves)
    ok = ~np.isnan(moves).any(axis=0)                                  # tenors observed in every episode
    stress_drift = np.interp(C.TENORS, C.TENORS[ok], moves[:, ok].mean(axis=0))

    return dict(date=date, y0=y0, ust_dur=dur, ust_cnvx=cnvx, ust_dur_src=dur_src, ust_dur_calc=calc[:, 0],
                cov_m=cov_m, cov_window=(win.index[0], date), n_weeks=len(chg), rate_dur=rate_dur,
                resid_vol=resid_vol, stress_drift=stress_drift, stress_moves=moves, stress_tenors_ok=ok)


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
