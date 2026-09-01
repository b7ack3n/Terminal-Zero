"""The observation store — the atomic, cited unit of Terminal Zero.

An **observation** is one number, about one subject, over one period, from one
source, with everything needed to trace and re-verify it. Every figure a brief
ever shows resolves to a row in here.

Four of the spec's non-negotiables are enforced structurally, not by convention:

  1. Provenance is a column. source, source_url, accession, retrieved_at,
     licence_class ride on every row. You can always answer "where did this
     number come from, and when did we see it?"

  2. Never dedupe on ingest. Restatements mean the same concept+period exists
     under different accession numbers. Our uniqueness key *includes* the
     accession, so re-running ingest is idempotent but different vintages are
     all kept — which is what makes point-in-time queries possible later.

  3. Flow vs stock is explicit. A flow (revenue over a quarter) has a
     period_start AND period_end; a stock (cash at an instant) has period_end
     only. We store measure_type and guard the shape, so you can never
     silently sum a balance-sheet stock as if it were a flow.

  4. Guards raise, never coerce. validate() rejects a malformed observation
     loudly instead of quietly storing something wrong.

The schema is deliberately source-agnostic: subject_type distinguishes a
company fact ('company', subject_id 'CIK:0000002488') from an industry
aggregate ('industry', subject_id 'NAICS:111335', geo 'STATE:06').
"""

from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from terminal_zero import config

DB_PATH = config.ROOT / "data" / "store.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS observations (
    id            INTEGER PRIMARY KEY,

    -- SUBJECT: what the number is about
    subject_type  TEXT NOT NULL,      -- 'company' | 'industry'
    subject_id    TEXT NOT NULL,      -- 'CIK:0000002488' | 'NAICS:111335'
    geo           TEXT,               -- 'US' | 'STATE:06' | 'COUNTY:06001' | NULL

    -- MEASURE: the quantity being reported
    taxonomy      TEXT NOT NULL,      -- 'us-gaap' | 'dei' | 'bls-qcew' | ...
    concept       TEXT NOT NULL,      -- 'Revenues' | 'Assets' | 'employment'
    unit          TEXT NOT NULL,      -- 'USD' | 'shares' | 'employees'
    measure_type  TEXT NOT NULL,      -- 'flow' | 'stock'

    -- PERIOD: flow has start+end; stock has end (the instant) only
    period_start  TEXT,               -- ISO date, or NULL for a stock
    period_end    TEXT NOT NULL,      -- ISO date
    fiscal_year   INTEGER,
    fiscal_period TEXT,               -- 'FY' | 'Q1' | ...

    -- VALUE
    value         REAL NOT NULL,

    -- PROVENANCE: everything needed to trace and re-verify this exact number
    source        TEXT NOT NULL,      -- 'sec-edgar'
    source_url    TEXT NOT NULL,
    accession     TEXT,               -- vintage id; restatements differ here
    form          TEXT,               -- '10-K' | '10-Q'
    filed         TEXT,               -- filing date (ISO)
    frame         TEXT,               -- optional XBRL frame id
    retrieved_at  TEXT NOT NULL,      -- when we fetched it (vintage of retrieval)
    licence_class TEXT NOT NULL,
    ingested_at   TEXT NOT NULL       -- when this row was written
);

-- Idempotent ingest that does NOT collapse restatements: the identity of a
-- source assertion includes its accession. coalesce() makes NULL start /
-- accession compare equal across re-runs (SQLite treats raw NULLs as distinct).
CREATE UNIQUE INDEX IF NOT EXISTS ux_observation_identity ON observations(
    source, subject_id, taxonomy, concept, unit,
    coalesce(period_start, ''), period_end, coalesce(accession, '')
);

-- The read path we expect most: all vintages of a concept for a subject.
CREATE INDEX IF NOT EXISTS ix_subject_concept
    ON observations(subject_id, concept, period_end);
"""


@dataclass(frozen=True)
class Observation:
    """One number to be stored. Mirrors the table, minus id/ingested_at."""

    subject_type: str
    subject_id: str
    taxonomy: str
    concept: str
    unit: str
    measure_type: str          # 'flow' | 'stock'
    period_end: str
    value: float
    source: str
    source_url: str
    retrieved_at: str
    licence_class: str
    # optionals
    geo: str | None = None
    period_start: str | None = None
    fiscal_year: int | None = None
    fiscal_period: str | None = None
    accession: str | None = None
    form: str | None = None
    filed: str | None = None
    frame: str | None = None


def measure_type_for(period_start: str | None) -> str:
    """A fact with a start is a flow; a start-less fact is a stock instant."""
    return "flow" if period_start else "stock"


def validate(obs: Observation) -> None:
    """Reject a malformed observation loudly. Guards raise, never coerce."""
    required = {
        "subject_type": obs.subject_type,
        "subject_id": obs.subject_id,
        "taxonomy": obs.taxonomy,
        "concept": obs.concept,
        "unit": obs.unit,
        "period_end": obs.period_end,
        "source": obs.source,
        "source_url": obs.source_url,
        "retrieved_at": obs.retrieved_at,
        "licence_class": obs.licence_class,
    }
    missing = [name for name, val in required.items() if not (val and str(val).strip())]
    if missing:
        raise ValueError(f"observation missing required fields: {', '.join(missing)}")

    if obs.measure_type not in ("flow", "stock"):
        raise ValueError(f"measure_type must be 'flow' or 'stock', got {obs.measure_type!r}")

    # The flow/stock guard: the period shape and the declared type must agree.
    if obs.measure_type == "flow" and not obs.period_start:
        raise ValueError(
            f"flow observation '{obs.concept}' for {obs.subject_id} needs a period_start "
            "(a flow spans start..end); refusing to store it as if instantaneous"
        )
    if obs.measure_type == "stock" and obs.period_start:
        raise ValueError(
            f"stock observation '{obs.concept}' for {obs.subject_id} has a period_start "
            f"({obs.period_start}); a stock is a single instant — refusing to coerce"
        )

    if isinstance(obs.value, bool) or not isinstance(obs.value, (int, float)):
        raise ValueError(f"value must be a number, got {obs.value!r}")
    if isinstance(obs.value, float) and (math.isnan(obs.value) or math.isinf(obs.value)):
        raise ValueError(f"value must be finite, got {obs.value!r}")


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    """Open (creating if needed) the store and ensure the schema exists."""
    path = db_path or DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def insert_observations(conn: sqlite3.Connection, observations: Iterable[Observation]) -> int:
    """Validate and insert observations. Returns how many NEW rows were written.

    Uses INSERT OR IGNORE against the identity index: re-ingesting the same
    source assertion is a no-op, but a restatement (same concept/period, new
    accession) is a genuinely new row and is kept.
    """
    now = datetime.now(timezone.utc).isoformat()
    inserted = 0
    for obs in observations:
        validate(obs)  # raises before we touch the DB
        cur = conn.execute(
            """
            INSERT OR IGNORE INTO observations (
                subject_type, subject_id, geo,
                taxonomy, concept, unit, measure_type,
                period_start, period_end, fiscal_year, fiscal_period,
                value,
                source, source_url, accession, form, filed, frame,
                retrieved_at, licence_class, ingested_at
            ) VALUES (?,?,?, ?,?,?,?, ?,?,?,?, ?, ?,?,?,?,?,?, ?,?,?)
            """,
            (
                obs.subject_type, obs.subject_id, obs.geo,
                obs.taxonomy, obs.concept, obs.unit, obs.measure_type,
                obs.period_start, obs.period_end, obs.fiscal_year, obs.fiscal_period,
                float(obs.value),
                obs.source, obs.source_url, obs.accession, obs.form, obs.filed, obs.frame,
                obs.retrieved_at, obs.licence_class, now,
            ),
        )
        inserted += cur.rowcount  # 1 if inserted, 0 if ignored as duplicate
    conn.commit()
    return inserted


def count(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT count(*) FROM observations").fetchone()[0]
