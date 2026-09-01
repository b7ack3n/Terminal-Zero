"""Parse FRED series into observations — the free breadth layer.

FRED (Federal Reserve Economic Data, St. Louis Fed) re-publishes 800k+ time
series from 100+ agencies behind one API and one free key. It is a *convenience
layer*: one integration reaches a large slice of the sources Terminal Zero wants
(BLS PPI/CPI/CES/JOLTS/productivity, BEA, Census, Fed, EIA macro). It does NOT
replace primary sources where fine industry granularity is the point (QCEW at
6-digit NAICS, CBP size distribution) — FRED does not carry those at that grain.

Two disciplines, both load-bearing for the moat:

  * PROVENANCE STAYS PRIMARY. We fetch from FRED, so `source` is 'fred' and
    `source_url` is the FRED series URL — but the caller passes the *primary*
    publisher (`primary`), which we record so a brief can cite "BLS PPI (via
    FRED)", never a bare "FRED". FRED is where we got it; BLS is who made it.

  * PUBLIC-DOMAIN SERIES ONLY. FRED mixes US-gov public-domain series with
    copyrighted third-party ones (OECD, World Bank, private). We only ever point
    this at gov-source series; the linkage registry, not this parser, decides
    which series an industry maps to.

IO is separated from parsing: `parse_series_observations` is pure (fixture-
tested), `series_observations` fetches then calls it.
"""

from __future__ import annotations

import json

from terminal_zero.edgar.fetcher import Fetcher
from terminal_zero.store import Observation

_OBSERVATIONS_ENDPOINT = "https://api.stlouisfed.org/fred/series/observations"
# FRED marks a missing value with a lone period.
_MISSING = "."


def observations_url(series_id: str, *, observation_start: str | None = None) -> str:
    """Canonical (key-free) observations URL for one series."""
    url = f"{_OBSERVATIONS_ENDPOINT}?series_id={series_id}&file_type=json"
    if observation_start:
        url += f"&observation_start={observation_start}"
    return url


def series_url(series_id: str) -> str:
    """Human-facing FRED page for the series — names the primary publisher."""
    return f"https://fred.stlouisfed.org/series/{series_id}"


def parse_series_observations(
    payload: dict | bytes | str,
    *,
    series_id: str,
    concept: str,
    unit: str,
    measure_type: str,          # 'flow' | 'stock' — index levels are 'stock'
    frequency: str,             # 'A' | 'Q' | 'M' — sets fiscal_period + span
    source: str,
    source_url: str,
    retrieved_at: str,
    licence_class: str,
    primary: str,               # primary publisher, e.g. 'BLS PPI' — for the cite
) -> list[Observation]:
    """Turn a FRED observations payload into observations. Pure — no network.

    Each FRED observation is dated at the START of its period; we derive the
    period end from the frequency so flow/stock semantics stay honest. Missing
    values ('.') are skipped — a gap, never a zero.
    """
    if isinstance(payload, (bytes, str)):
        payload = json.loads(payload)

    out: list[Observation] = []
    for row in payload.get("observations", []):
        raw = (row.get("value") or "").strip()
        if raw == "" or raw == _MISSING:
            continue
        start = row.get("date")               # ISO date, period start
        if not start:
            continue
        year = int(start[:4])
        period_start, period_end, fiscal_period = _period(start, year, frequency)
        # Index levels (PPI/CPI/INDPRO) are stocks: a level at a period, never
        # summed. Only genuine flows get a period_start.
        ps = period_start if measure_type == "flow" else None
        out.append(
            Observation(
                subject_type="industry",
                subject_id=f"FRED:{series_id}",
                taxonomy="fred",
                concept=concept,
                unit=unit,
                measure_type=measure_type,
                period_start=ps,
                period_end=period_end,
                fiscal_year=year,
                fiscal_period=fiscal_period,
                value=float(raw),
                source=source,
                source_url=source_url,
                # Primary publisher rides in `frame` so a brief can cite it and
                # never present a bare "FRED" as the origin.
                frame=f"primary:{primary}",
                retrieved_at=retrieved_at,
                licence_class=licence_class,
            )
        )
    return out


def _period(start: str, year: int, frequency: str) -> tuple[str, str, str]:
    """(period_start, period_end, fiscal_period) from a FRED start date."""
    if frequency == "A":
        return f"{year}-01-01", f"{year}-12-31", "A"
    if frequency == "Q":
        q = (int(start[5:7]) - 1) // 3 + 1
        end_month = q * 3
        last_day = "31" if end_month in (3, 12) else "30"
        return start, f"{year}-{end_month:02d}-{last_day}", f"Q{q}"
    # Monthly (and anything else): treat the dated month as the period.
    month = int(start[5:7])
    last = _month_end(year, month)
    return start, f"{year}-{month:02d}-{last:02d}", f"M{month:02d}"


def _month_end(year: int, month: int) -> int:
    if month == 2:
        leap = year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
        return 29 if leap else 28
    return 30 if month in (4, 6, 9, 11) else 31


def series_observations(
    fetcher: Fetcher,
    series_id: str,
    *,
    concept: str,
    unit: str,
    measure_type: str,
    frequency: str,
    primary: str,
    observation_start: str | None = None,
) -> list[Observation]:
    """Fetch one FRED series and parse it into observations."""
    url = observations_url(series_id, observation_start=observation_start)
    result = fetcher.get(url)
    return parse_series_observations(
        result.body,
        series_id=series_id,
        concept=concept,
        unit=unit,
        measure_type=measure_type,
        frequency=frequency,
        source=result.source,
        source_url=series_url(series_id),   # cite the FRED page (names the publisher)
        retrieved_at=result.retrieved_at,
        licence_class=result.licence_class,
        primary=primary,
    )
