"""Parse USDA NASS Quick Stats into observations.

Agricultural production/acreage/value — the sizing source for industries that
are largely private and invisible to SEC/QCEW-financial views (e.g. tree nuts).
Stored under a commodity subject ('NASS:<COMMODITY>'); an industry links to its
commodities via the industry mapping.

NASS returns many rows per commodity (in-shell vs shelled, tons vs lb, utilized
vs total). We keep them all, keyed by the source's own short_desc, with the unit
NASS reports. Suppressed/withheld values ('(D)', '(NA)', ...) are skipped.
"""

from __future__ import annotations

import json

from terminal_zero.edgar.fetcher import Fetcher
from terminal_zero.store import Observation


def production_url(commodity: str, year: int) -> str:
    return ("https://quickstats.nass.usda.gov/api/api_GET/"
            f"?commodity_desc={commodity}&year={year}"
            "&statisticcat_desc=PRODUCTION&agg_level_desc=NATIONAL&format=JSON")


def _num(raw: str):
    try:
        return float(str(raw).replace(",", ""))
    except (ValueError, TypeError):
        return None


def parse_production(text, *, commodity, source, source_url, retrieved_at, licence_class):
    rows = json.loads(text).get("data", [])
    out = []
    for r in rows:
        value = _num(r.get("Value"))
        if value is None:                      # suppressed/withheld — a gap
            continue
        year = int(r["year"])
        # short_desc carries the precise measure; keep it as the concept detail.
        concept = "nass_production:" + r.get("short_desc", "").strip()
        out.append(Observation(
            subject_type="industry", subject_id=f"NASS:{commodity.upper()}", geo="US",
            taxonomy="usda-nass", concept=concept, unit=r.get("unit_desc", "").strip() or "unit",
            measure_type="flow", period_start=f"{year}-01-01", period_end=f"{year}-12-31",
            fiscal_year=year, fiscal_period="A", value=value,
            source=source, source_url=source_url, retrieved_at=retrieved_at,
            licence_class=licence_class,
        ))
    return out


def commodity_observations(fetcher: Fetcher, commodity: str, years) -> list[Observation]:
    obs = []
    for year in years:
        url = production_url(commodity, year)
        try:
            res = fetcher.get(url)
        except RuntimeError:
            continue
        obs += parse_production(res.body.decode("utf-8"), commodity=commodity,
                                source=res.source, source_url=res.url,
                                retrieved_at=res.retrieved_at, licence_class=res.licence_class)
    return obs
