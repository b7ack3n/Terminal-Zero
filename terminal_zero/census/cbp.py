"""Parse Census County Business Patterns (CBP) into observations.

CBP gives establishment counts, employment and payroll by NAICS, and — crucially
for competitive structure — the distribution of establishments across employment
size classes. That size distribution is the raw material for a concentration /
rivalry read (are there a few big players or a long tail of small ones?).

CBP uses a different methodology than QCEW (it excludes some workers and counts
differently), so its employment will not match QCEW's. We store CBP figures under
their own concepts ('cbp_*') so the two sources are never silently conflated.

Establishment size class is a dimension the store has no column for, so we encode
it in the concept name ('cbp_estab_size:<code>'). Payroll (PAYANN) arrives in
thousands of dollars; we store absolute USD.
"""

from __future__ import annotations

import json

from terminal_zero.edgar.fetcher import Fetcher
from terminal_zero.store import Observation

# EMPSZES code -> human label (for later rendering).
SIZE_LABELS = {
    "210": "<5 employees", "220": "5–9", "230": "10–19", "241": "20–49",
    "242": "50–99", "251": "100–249", "252": "250–499", "254": "500–999",
    "260": "1,000+",
}


def totals_url(naics: str, year: int) -> str:
    return (f"https://api.census.gov/data/{year}/cbp?get=ESTAB,EMP,PAYANN"
            f"&NAICS2017={naics}&for=us:1")


def size_url(naics: str, year: int) -> str:
    return (f"https://api.census.gov/data/{year}/cbp?get=ESTAB,EMPSZES_LABEL"
            f"&NAICS2017={naics}&EMPSZES=*&for=us:1")


def _rows(text: str):
    data = json.loads(text)
    header = data[0]
    return {h: i for i, h in enumerate(header)}, data[1:]


def _base(naics, year, source, source_url, retrieved_at, licence_class):
    return dict(
        subject_type="industry", subject_id=f"NAICS:{naics}", geo="US",
        taxonomy="census-cbp", period_end=f"{year}-12-31",
        fiscal_year=year, fiscal_period="A", source=source, source_url=source_url,
        retrieved_at=retrieved_at, licence_class=licence_class,
    )


def parse_totals(text, *, naics, year, source, source_url, retrieved_at, licence_class):
    idx, data = _rows(text)
    b = _base(naics, year, source, source_url, retrieved_at, licence_class)
    out = []
    for r in data:
        out.append(Observation(concept="cbp_establishments", unit="establishments",
                               measure_type="stock", value=float(r[idx["ESTAB"]]), **b))
        out.append(Observation(concept="cbp_employment", unit="employees",
                               measure_type="stock", value=float(r[idx["EMP"]]), **b))
        out.append(Observation(concept="cbp_annual_payroll", unit="USD",
                               measure_type="flow", period_start=f"{year}-01-01",
                               value=float(r[idx["PAYANN"]]) * 1000, **b))
    return out


def parse_size(text, *, naics, year, source, source_url, retrieved_at, licence_class):
    idx, data = _rows(text)
    b = _base(naics, year, source, source_url, retrieved_at, licence_class)
    out = []
    for r in data:
        code = r[idx["EMPSZES"]]
        if code == "001":       # "all establishments" — already in totals
            continue
        out.append(Observation(concept=f"cbp_estab_size:{code}", unit="establishments",
                               measure_type="stock", value=float(r[idx["ESTAB"]]), **b))
    return out


def industry_observations(fetcher: Fetcher, naics: str, year: int) -> list[Observation]:
    obs = []
    for url, parse in ((totals_url(naics, year), parse_totals),
                       (size_url(naics, year), parse_size)):
        res = fetcher.get(url)
        obs += parse(res.body.decode("utf-8"), naics=naics, year=year,
                     source=res.source, source_url=res.url,
                     retrieved_at=res.retrieved_at, licence_class=res.licence_class)
    return obs
