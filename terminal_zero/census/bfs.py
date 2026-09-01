"""Parse Census Business Formation Statistics (BFS) into observations.

BFS tracks new-business applications and projected formations — the entry side
of "threat of new entrants". It is published only at NAICS-SECTOR level, so a
detailed industry like semiconductors maps to all Manufacturing (NAICSMNF), a
broad superset. Stored under a BFS subject and labelled honestly as such; the
industry-specific entry signal comes from QCEW establishment growth instead.

Monthly counts, seasonally adjusted. time_slot_id 0 is the monthly value.
"""

from __future__ import annotations

import calendar
import json

from terminal_zero.edgar.fetcher import Fetcher
from terminal_zero.store import Observation

BFS_BASE = "https://api.census.gov/data/timeseries/eits/bfs"

# data_type_code -> concept we store it as.
# BA_BA = business applications; BF_PBF8Q = projected formations within 8 quarters.
DATA_TYPES = {"BA_BA": "bfs_applications", "BF_PBF8Q": "bfs_formations"}


def bfs_url(category: str, data_type_code: str, from_year: int) -> str:
    return (f"{BFS_BASE}?get=cell_value,time_slot_id"
            f"&time=from+{from_year}-01&category_code={category}"
            f"&data_type_code={data_type_code}&seasonally_adj=yes&for=us:*")


def _month_end(year, month):
    return f"{year:04d}-{month:02d}-{calendar.monthrange(year, month)[1]:02d}"


def parse_bfs(text, *, category, concept, source, source_url, retrieved_at, licence_class):
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []                                  # error body / no data for this series
    idx = {h: i for i, h in enumerate(data[0])}
    out = []
    for r in data[1:]:
        if r[idx["time_slot_id"]] != "0":       # keep the monthly value only
            continue
        try:
            value = float(r[idx["cell_value"]])
        except (ValueError, TypeError):
            continue
        t = r[idx["time"]]                        # "YYYY-MM"
        year, month = int(t[:4]), int(t[5:7])
        out.append(Observation(
            subject_type="industry", subject_id=f"BFS:{category}", geo="US",
            taxonomy="census-bfs", concept=concept, unit="count", measure_type="flow",
            period_start=f"{year:04d}-{month:02d}-01", period_end=_month_end(year, month),
            fiscal_year=year, fiscal_period=f"M{month:02d}", value=value,
            source=source, source_url=source_url, retrieved_at=retrieved_at,
            licence_class=licence_class,
        ))
    return out


def sector_observations(fetcher: Fetcher, category: str, from_year: int) -> list[Observation]:
    obs = []
    for data_type_code, concept in DATA_TYPES.items():
        try:
            res = fetcher.get(bfs_url(category, data_type_code, from_year))
        except RuntimeError:
            continue
        obs += parse_bfs(res.body.decode("utf-8"), category=category, concept=concept,
                         source=res.source, source_url=res.url,
                         retrieved_at=res.retrieved_at, licence_class=res.licence_class)
    return obs
