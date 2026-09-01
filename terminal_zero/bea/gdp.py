"""Parse BEA GDP-by-Industry into observations (gross output, value added).

BEA measures industries at its own summary granularity — the finest electronics
industry is "334 Computer and electronic products", a *superset* of semiconductor
manufacturing (NAICS 334413). So BEA gives sector-level market size, and we store
it under its own subject id ("BEA:334") — never conflated with the NAICS-precise
QCEW data. The brief labels it honestly as the broader sector.

Values arrive in billions of dollars; we store absolute USD so units match the
rest of the store. Annual output is a flow (spans the year).

IO is separated from parsing: parse_gdp_json is pure and testable.
"""

from __future__ import annotations

import calendar
import json

from terminal_zero.edgar.fetcher import Fetcher
from terminal_zero.store import Observation

BEA_BASE = "https://apps.bea.gov/api/data/"

# TableID -> the concept we store it as.
TABLES = {"15": "gross_output", "1": "value_added"}

_BILLIONS = 1_000_000_000.0

# BEA quarter labels -> (first month, last month, ordinal).
QUARTERS = {"I": (1, 3, 1), "II": (4, 6, 2), "III": (7, 9, 3), "IV": (10, 12, 4)}


def data_url(table_id: str, industry: str, years) -> str:
    """Canonical BEA GetData URL WITHOUT the key (the fetcher adds UserID)."""
    yrs = ",".join(str(y) for y in years)
    return (
        f"{BEA_BASE}?method=GetData&datasetname=GDPbyIndustry"
        f"&TableID={table_id}&Frequency=A&Year={yrs}&Industry={industry}&ResultFormat=JSON"
    )


def _results(payload: dict) -> dict:
    r = payload["BEAAPI"]["Results"]
    return r[0] if isinstance(r, list) else r


def parse_gdp_json(
    text: str,
    *,
    concept: str,
    source: str,
    source_url: str,
    retrieved_at: str,
    licence_class: str,
) -> list[Observation]:
    """Turn one BEA GDP-by-Industry response into observations. Pure — no network."""
    rows = _results(json.loads(text)).get("Data", [])
    out: list[Observation] = []
    for row in rows:
        raw = str(row.get("DataValue", "")).replace(",", "").strip()
        try:
            value = float(raw) * _BILLIONS
        except ValueError:
            continue  # (D)/(NA)/blank — a gap, not a zero
        year = int(row["Year"])
        out.append(
            Observation(
                subject_type="industry",
                subject_id=f"BEA:{row['Industry']}",
                geo="US",
                taxonomy="bea-gdp-by-industry",
                concept=concept,
                unit="USD",
                measure_type="flow",                 # annual output spans the year
                period_start=f"{year}-01-01",
                period_end=f"{year}-12-31",
                fiscal_year=year,
                fiscal_period="A",
                value=value,
                source=source,
                source_url=source_url,
                retrieved_at=retrieved_at,
                licence_class=licence_class,
            )
        )
    return out


def quarterly_url(industry: str, years) -> str:
    yrs = ",".join(str(y) for y in years)
    return (f"{BEA_BASE}?method=GetData&datasetname=GDPbyIndustry"
            f"&TableID=15&Frequency=Q&Year={yrs}&Industry={industry}&ResultFormat=JSON")


def parse_quarterly(text, *, source, source_url, retrieved_at, licence_class):
    """Quarterly gross output (seasonally-adjusted annual rate). Stored under a
    distinct concept so it is never mixed with the annual gross_output series."""
    rows = _results(json.loads(text)).get("Data", [])
    out = []
    for row in rows:
        raw = str(row.get("DataValue", "")).replace(",", "").strip()
        q = row.get("Quarter", "")
        if q not in QUARTERS:
            continue
        try:
            value = float(raw) * _BILLIONS
        except ValueError:
            continue
        year = int(row["Year"])
        m0, m1, n = QUARTERS[q]
        out.append(Observation(
            subject_type="industry", subject_id=f"BEA:{row['Industry']}", geo="US",
            taxonomy="bea-gdp-by-industry", concept="gross_output_saar",
            unit="USD/yr", measure_type="flow",
            period_start=f"{year}-{m0:02d}-01",
            period_end=f"{year}-{m1:02d}-{calendar.monthrange(year, m1)[1]:02d}",
            fiscal_year=year, fiscal_period=f"Q{n}", value=value,
            source=source, source_url=source_url, retrieved_at=retrieved_at,
            licence_class=licence_class,
        ))
    return out


def industry_observations(fetcher: Fetcher, bea_industry: str, years,
                          quarters=None) -> list[Observation]:
    """Fetch annual gross output + value added, and (optionally) quarterly SAAR."""
    observations: list[Observation] = []
    for table_id, concept in TABLES.items():
        result = fetcher.get(data_url(table_id, bea_industry, years))
        observations += parse_gdp_json(
            result.body.decode("utf-8"), concept=concept, source=result.source,
            source_url=result.url, retrieved_at=result.retrieved_at,
            licence_class=result.licence_class)
    if quarters:
        result = fetcher.get(quarterly_url(bea_industry, quarters))
        observations += parse_quarterly(
            result.body.decode("utf-8"), source=result.source, source_url=result.url,
            retrieved_at=result.retrieved_at, licence_class=result.licence_class)
    return observations
