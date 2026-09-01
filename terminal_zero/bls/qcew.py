"""Parse BLS QCEW industry data into observations.

QCEW (Quarterly Census of Employment and Wages) is a near-census of US
establishments covered by unemployment insurance — ~95% of jobs — reported by
NAICS industry and geography. No API key; the annual "open data" file for one
industry across all areas is a static CSV.

This is our first industry-grain source: each observation has
subject_type='industry', subject_id='NAICS:<code>', and a geo. The product's
core — cited industry numbers — starts here.

Design choices, each deliberate:

  * We keep only the PRIMARY measured quantities (establishments, employment,
    total wages) and skip QCEW's derived ratios (avg weekly wage, avg annual
    pay). Ratios are derivations — computed later from primaries, per the rule
    that numbers come from queries/scripts, not stored twice.

  * Flow vs stock is set per measure: wages are a flow (summed over the year);
    employment and establishment counts are levels (stocks) — never summed
    across years. The store guards this.

  * We ingest Private ownership only (own_code 5), the standard industry view,
    and US + state geographies for now (counties/MSAs skipped). Both are noted
    as deliberate scope, not silent drops.

  * Suppressed rows (disclosure_code 'N') are skipped, not stored as zero — an
    undisclosed value is a gap, and we report gaps as gaps.

IO is separated from parsing: `parse_industry_csv` is pure (testable without a
network), `industry_observations` fetches then calls it.
"""

from __future__ import annotations

import csv
import io

from terminal_zero.edgar.fetcher import Fetcher
from terminal_zero.store import Observation

# Primary QCEW measures we store: (csv column, unit, flow|stock).
QCEW_MEASURES: tuple[tuple[str, str, str], ...] = (
    ("total_annual_wages", "USD", "flow"),
    ("annual_avg_emplvl", "employees", "stock"),
    ("annual_avg_estabs", "establishments", "stock"),
)

PRIVATE_OWNERSHIP = "5"  # QCEW own_code for Private


def industry_url(naics: str, year: int) -> str:
    """Annual, all-areas open-data CSV for one industry."""
    return f"https://data.bls.gov/cew/data/api/{year}/a/industry/{naics}.csv"


def geo_for_area(area_fips: str) -> str | None:
    """Map a QCEW area_fips to our geo code. None => skip (county/MSA/other)."""
    if area_fips == "US000":
        return "US"
    if len(area_fips) == 5 and area_fips.isdigit() and area_fips.endswith("000"):
        return f"STATE:{area_fips[:2]}"
    return None


def parse_industry_csv(
    text: str,
    *,
    naics: str,
    year: int,
    source: str,
    source_url: str,
    retrieved_at: str,
    licence_class: str,
) -> list[Observation]:
    """Turn a QCEW industry CSV into observations. Pure — no network."""
    observations: list[Observation] = []
    reader = csv.DictReader(io.StringIO(text))

    for row in reader:
        if row.get("own_code") != PRIVATE_OWNERSHIP:
            continue
        geo = geo_for_area(row.get("area_fips", ""))
        if geo is None:
            continue
        if row.get("disclosure_code") == "N":  # suppressed — a gap, not a zero
            continue

        for column, unit, measure_type in QCEW_MEASURES:
            raw = row.get(column, "")
            if raw == "":
                continue
            period_start = f"{year}-01-01" if measure_type == "flow" else None
            observations.append(
                Observation(
                    subject_type="industry",
                    subject_id=f"NAICS:{naics}",
                    geo=geo,
                    taxonomy="bls-qcew",
                    concept=column,
                    unit=unit,
                    measure_type=measure_type,
                    period_start=period_start,
                    period_end=f"{year}-12-31",
                    fiscal_year=year,
                    fiscal_period="A",
                    value=float(raw),
                    source=source,
                    source_url=source_url,
                    retrieved_at=retrieved_at,
                    licence_class=licence_class,
                )
            )
    return observations


def industry_observations(fetcher: Fetcher, naics: str, year: int) -> list[Observation]:
    """Fetch one industry-year from QCEW and parse it into observations."""
    url = industry_url(naics, year)
    result = fetcher.get(url)
    return parse_industry_csv(
        result.body.decode("utf-8"),
        naics=naics,
        year=year,
        source=result.source,
        source_url=result.url,
        retrieved_at=result.retrieved_at,
        licence_class=result.licence_class,
    )
