"""Bond-level Bloomberg data (two PDF exports) and the tower-sector sleeve built from it."""
import re

import numpy as np
import pandas as pd
from pypdf import PdfReader

from . import config as C

TICKER = re.compile(r"([0-9A-Z]{9,12}) Corp")
FIELD = re.compile(r"spread\(spread_type=OAS\)|px_bid\(\)|px_mid\(\)|px_ask\(\)|"
                   r"yield\(yield_type=YTW,side=MID\)|duration\(duration_type=MODIFIED\)")
NAMES = {"spread(spread_type=OAS)": "oas", "px_bid()": "bid", "px_mid()": "mid", "px_ask()": "ask",
         "yield(yield_type=YTW,side=MID)": "ytw", "duration(duration_type=MODIFIED)": "mod_dur"}


def parse_pdf(path):
    """The PDFs are spreadsheets printed down then across: the first column block carries the dates,
    later blocks continue the columns for the same rows.  The first page of every block repeats the field
    header, which is how a new block is recognised.  Returns a (date x [bond, field]) frame."""
    tickers, fields, blocks = [], [], []
    for page in PdfReader(path).pages:
        lines = (page.extract_text() or "").splitlines()
        if any(FIELD.search(line) for line in lines):
            blocks.append([])
        for line in lines:
            if TICKER.search(line):
                tickers += TICKER.findall(line)
            elif FIELD.search(line):
                fields += FIELD.findall(line)
            else:
                blocks[-1].append(line.split())
    n = len(blocks[0])
    assert all(len(b) == n for b in blocks), "column blocks do not line up"
    tab = np.hstack([np.array(b, dtype=object) for b in blocks])
    per = len(fields) // len(tickers)
    assert tab.shape[1] - 1 == len(fields) and fields == fields[:per] * len(tickers), "header does not match data"
    vals = pd.DataFrame(tab[:, 1:]).replace("#N/A", np.nan).astype(float)
    vals.index = pd.to_datetime(tab[:, 0].astype(float), unit="D", origin="1899-12-30")
    vals.columns = pd.MultiIndex.from_product([tickers, [NAMES[f] for f in fields[:per]]])
    return vals


def load_bonds():
    """Both exports merged.  Bonds in both files must agree exactly, which checks the parsing."""
    full, oas_only = (parse_pdf(p) for p in C.BOND_PDFS)
    oas = full.xs("oas", axis=1, level=1)
    extra = oas_only.xs("oas", axis=1, level=1)
    for b in extra.columns.intersection(oas.columns):
        both = oas[b].notna() & extra[b].notna()
        assert np.allclose(oas.loc[both, b], extra.loc[both, b]), f"{b}: the two PDFs disagree"
    oas = oas.combine_first(extra)
    return full, oas


def bond_table(full, oas, y0, ust_dur, date):
    """Pricing-date snapshot per bond.  OAS uses the last value on or before the pricing date (Bloomberg
    leaves it blank on the pricing date itself).  The duration-matched Treasury yield interpolates the
    curve in duration space using Bloomberg's modified durations of the generic Treasuries."""
    snap = full.loc[date].unstack()
    tab = pd.DataFrame(index=oas.columns)
    tab["issuer_prefix"] = [b[:6] if b[:2] != "XS" else "XS" for b in tab.index]
    for f in ("bid", "mid", "ask", "ytw", "mod_dur"):
        tab[f] = snap[f] if f in snap else np.nan
    tab["ytw"] /= 100
    last = oas.loc[:date].ffill().iloc[-1]
    tab["oas_bp"] = last
    tab["oas_date"] = oas.loc[:date].apply(lambda s: s.last_valid_index())
    tab["history_from"] = oas.apply(lambda s: s.first_valid_index())
    tab["ust_matched"] = np.interp(tab["mod_dur"], ust_dur, y0)
    tab["spread_vs_ust_bp"] = (tab["ytw"] - tab["ust_matched"]) * 1e4
    tab["implied_benchmark"] = tab["ytw"] - tab["oas_bp"] / 1e4
    testable = tab["implied_benchmark"].notna()                      # OAS-only bonds cannot be checked
    tab["usd_consistent"] = (tab["implied_benchmark"] >= C.USD_CHECK_FLOOR).where(testable)
    tab["below_par"] = (tab["mid"] < 100).where(tab["mid"].notna())
    tab["tower_sleeve"] = tab["issuer_prefix"].isin(C.TOWER_ISSUERS) & (tab["usd_consistent"] == True)  # noqa: E712
    return tab


def tower_sleeve(full, oas, tab, d, y0, ust_dur, corp_spread, corp_beta):
    """Equal-weighted tower sleeve.  Yield, duration and spread are the bonds' own pricing-date values;
    the base is the generic Treasury nearest in duration; spread volatility is the monthly change in the
    sleeve's average OAS; the rate beta is each bond's price sensitivity to its duration-matched Treasury
    divided by its modified duration; spread_beta scales the IG index assumption by relative yield spread
    over Treasuries (duration-times-spread: spread moves are proportional to spread level)."""
    m = tab[tab.tower_sleeve]
    dur, ytw = m["mod_dur"].mean(), m["ytw"].mean()
    j = int(np.argmin(np.abs(ust_dur - dur)))
    spread = ytw - y0[j]

    eq = oas[m.index].loc[:tab["oas_date"].max()]
    eq = eq.loc[eq.notna().all(axis=1)].mean(axis=1) / 1e4          # common history only
    mo = eq.resample("ME").last().diff().dropna()
    spread_vol = mo.std() * np.sqrt(12)

    betas = []
    for b in m.index:
        px = full[(b, "mid")].dropna()
        x = d.loc[px.index.intersection(d.index), [f"UST{l}" for l in C.TENOR_LABELS]]
        md = full[(b, "mod_dur")].reindex(x.index).ffill()
        ym = pd.Series([np.interp(dd, ust_dur, row) for dd, row in zip(md.values, x.values / 100)], index=x.index)
        w = pd.concat([np.log(px.reindex(x.index)), ym, md], axis=1).resample("W-FRI").last().diff().dropna()
        w.columns = ["r", "dy", "md"]
        slope = np.polyfit(w["dy"], w["r"], 1)[0]
        betas.append(-slope / md.mean())
    rate_beta = float(np.mean(betas))

    dts_ratio = spread / corp_spread                    # both are yield spreads over Treasuries
    return dict(mod_dur=dur, yield0=ytw, match=[float(C.TENORS[j])], spread=spread, spread_vol=spread_vol,
                rate_beta=rate_beta, rate_betas=betas, spread_beta=corp_beta * dts_ratio, dts_ratio=dts_ratio,
                n_bonds=len(m), oas_bp=m["oas_bp"].mean(), oas_series=eq, bonds=list(m.index))
