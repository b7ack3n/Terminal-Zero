"""Parse BEA Input-Output (Use table) into observations.

The Use table is a matrix: rows are commodities (inputs), columns are industries
(users). For one industry it yields two things the Five Forces need:

  * SUPPLIER side — what the industry BUYS (its column): the mix and
    concentration of inputs. Diversified inputs ⇒ low supplier power.
  * BUYER side — who buys the industry's OUTPUT (its row): the mix and
    concentration of customers, including exports. Diversified/export-heavy
    demand ⇒ lower buyer power.

Stored under the industry's BEA subject as io_input:<code> / io_output:<code>
(the counterparty code encoded in the concept; labels live in io_labels).
Aggregate rows/cols (totals 'T…', value-added 'V…') are excluded — they aren't
counterparties. Values arrive in millions of USD.
"""

from __future__ import annotations

import json

from terminal_zero.bea.gdp import BEA_BASE
from terminal_zero.edgar.fetcher import Fetcher
from terminal_zero.store import Observation

USE_TABLE_ID = "259"           # "Use of Commodities by Industries - Summary"
_MILLIONS = 1_000_000.0


def use_url(year: int) -> str:
    return (f"{BEA_BASE}?method=GetData&datasetname=InputOutput"
            f"&TableID={USE_TABLE_ID}&Year={year}&ResultFormat=JSON")


def _results(payload):
    # A year with no data comes back as an Error body (HTTP 200, no Results).
    r = payload.get("BEAAPI", {}).get("Results")
    if not r:
        return {}
    r = r[0] if isinstance(r, list) else r
    return r if isinstance(r, dict) and "Data" in r else {}


def _is_aggregate(code: str) -> bool:
    # Totals (T001, T005, T019, …) and value-added (V001, VAPRO, …) are not
    # counterparties. No real BEA summary industry code starts with T or V.
    return code[:1] in ("T", "V")


def _num(raw):
    try:
        return float(str(raw).replace(",", ""))
    except (ValueError, TypeError):
        return None


def parse_use_table(text, *, industry, source, source_url, retrieved_at, licence_class):
    data = _results(json.loads(text)).get("Data", [])
    out = []
    for x in data:
        year = int(x["Year"])
        base = dict(
            subject_type="industry", subject_id=f"BEA:{industry}", geo="US",
            taxonomy="bea-io", unit="USD", measure_type="flow",
            period_start=f"{year}-01-01", period_end=f"{year}-12-31",
            fiscal_year=year, fiscal_period="A", source=source, source_url=source_url,
            retrieved_at=retrieved_at, licence_class=licence_class,
        )
        # input side: this industry as the buyer (column)
        if x["ColCode"] == industry and x["RowCode"] != industry and not _is_aggregate(x["RowCode"]):
            v = _num(x["DataValue"])
            if v and v > 0:
                out.append(Observation(concept=f"io_input:{x['RowCode']}", value=v * _MILLIONS, **base))
        # output side: this industry as the supplier (row)
        if x["RowCode"] == industry and x["ColCode"] != industry and not _is_aggregate(x["ColCode"]):
            v = _num(x["DataValue"])
            if v and v > 0:
                out.append(Observation(concept=f"io_output:{x['ColCode']}", value=v * _MILLIONS, **base))
    return out


def use_observations(fetcher: Fetcher, industry: str, year: int) -> list[Observation]:
    res = fetcher.get(use_url(year))
    return parse_use_table(res.body.decode("utf-8"), industry=industry, source=res.source,
                           source_url=res.url, retrieved_at=res.retrieved_at,
                           licence_class=res.licence_class)
