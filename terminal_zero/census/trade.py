"""Parse Census international-trade (HS) into observations.

Monthly US exports and imports by Harmonized System (HS) commodity code — the
raw material for a trade-exposure read (how export-oriented is the industry, how
much import competition). Trade is HS-coded, so we store it under an HS subject
('HS:<code>'); an industry links to its HS codes via the industry mapping.

Values are monthly USD (absolute). We store each month as a flow spanning that
month, so a trailing-12-month total is a simple query later.
"""

from __future__ import annotations

import calendar
import json

from terminal_zero.edgar.fetcher import Fetcher
from terminal_zero.store import Observation

# direction -> (endpoint, value field, commodity field)
_DIRS = {
    "exports": ("exports", "ALL_VAL_MO", "E_COMMODITY"),
    "imports": ("imports", "GEN_VAL_MO", "I_COMMODITY"),
}


def trade_url(direction: str, hs: str, year: int) -> str:
    endpoint, value_field, commodity_field = _DIRS[direction]
    return (f"https://api.census.gov/data/timeseries/intltrade/{endpoint}/hs"
            f"?get={value_field},{commodity_field}&{commodity_field}={hs}"
            f"&CTY_CODE=-&time={year}")


def _month_end(year: int, month: int) -> str:
    return f"{year:04d}-{month:02d}-{calendar.monthrange(year, month)[1]:02d}"


def parse_trade(text, *, direction, hs, source, source_url, retrieved_at, licence_class):
    value_field = _DIRS[direction][1]
    data = json.loads(text)
    idx = {h: i for i, h in enumerate(data[0])}
    out = []
    for r in data[1:]:
        raw = r[idx[value_field]]
        t = r[idx["time"]]                    # "YYYY-MM"
        try:
            value = float(raw)
        except (ValueError, TypeError):
            continue
        year, month = int(t[:4]), int(t[5:7])
        out.append(Observation(
            subject_type="industry", subject_id=f"HS:{hs}", geo="US",
            taxonomy="census-trade", concept=f"{direction}_value", unit="USD",
            measure_type="flow", period_start=f"{year:04d}-{month:02d}-01",
            period_end=_month_end(year, month), fiscal_year=year,
            fiscal_period=f"M{month:02d}", value=value,
            source=source, source_url=source_url, retrieved_at=retrieved_at,
            licence_class=licence_class,
        ))
    return out


def hs_observations(fetcher: Fetcher, hs: str, years) -> list[Observation]:
    obs = []
    for direction in _DIRS:
        for year in years:
            url = trade_url(direction, hs, year)
            try:
                res = fetcher.get(url)
            except RuntimeError:
                continue                       # a year with no data yet
            obs += parse_trade(res.body.decode("utf-8"), direction=direction, hs=hs,
                               source=res.source, source_url=res.url,
                               retrieved_at=res.retrieved_at, licence_class=res.licence_class)
    return obs
