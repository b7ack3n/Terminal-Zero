"""Rooms: saved definitions of a slice of the store, materialised on demand.

A room is a *manifest*, not a copy. It records which subjects, concepts,
geographies, sources and years make up a slice; materialising it is just a
query over the shared observation store. Because rooms are definitions rather
than copies, they overlap freely and cost almost nothing to keep — and every
figure a room surfaces is still the same provenance-bearing observation row.

This is the substrate the "head" stands on: the visualiser renders a
materialised room, and the gen-AI layer answers questions by querying one.
Neither invents numbers — they read observations out of a room.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

ROOM_SCHEMA = """
CREATE TABLE IF NOT EXISTS rooms (
    id         INTEGER PRIMARY KEY,
    name       TEXT UNIQUE NOT NULL,
    definition TEXT NOT NULL,      -- JSON manifest (the slice definition)
    created_at TEXT NOT NULL
);
"""


@dataclass(frozen=True)
class RoomDefinition:
    """The manifest: which slice of the store this room is.

    Every filter is optional except the name — an empty filter means "no
    restriction on this axis". Materialising applies them as an AND query.
    """

    name: str
    subject_ids: list[str] = field(default_factory=list)   # e.g. ["NAICS:334413"]
    concepts: list[str] = field(default_factory=list)      # e.g. ["annual_avg_emplvl"]
    geos: list[str] = field(default_factory=list)          # e.g. ["US", "STATE:06"]
    sources: list[str] = field(default_factory=list)       # e.g. ["bls-qcew"]
    year_start: int | None = None
    year_end: int | None = None
    note: str = ""

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @staticmethod
    def from_json(text: str) -> "RoomDefinition":
        return RoomDefinition(**json.loads(text))


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(ROOM_SCHEMA)


def save(conn: sqlite3.Connection, room: RoomDefinition) -> None:
    """Persist a room definition (upsert by name). Stores the manifest only."""
    ensure_schema(conn)
    conn.execute(
        """
        INSERT INTO rooms (name, definition, created_at) VALUES (?, ?, ?)
        ON CONFLICT(name) DO UPDATE SET definition=excluded.definition
        """,
        (room.name, room.to_json(), datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()


def load(conn: sqlite3.Connection, name: str) -> RoomDefinition | None:
    ensure_schema(conn)
    row = conn.execute("SELECT definition FROM rooms WHERE name=?", (name,)).fetchone()
    return RoomDefinition.from_json(row[0]) if row else None


def list_rooms(conn: sqlite3.Connection) -> list[str]:
    ensure_schema(conn)
    return [r[0] for r in conn.execute("SELECT name FROM rooms ORDER BY name")]


def _where(room: RoomDefinition) -> tuple[str, list]:
    """Build the AND-filter SQL and params for a room's manifest."""
    clauses, params = [], []

    def in_clause(column: str, values: list):
        placeholders = ",".join("?" for _ in values)
        clauses.append(f"{column} IN ({placeholders})")
        params.extend(values)

    if room.subject_ids:
        in_clause("subject_id", room.subject_ids)
    if room.concepts:
        in_clause("concept", room.concepts)
    if room.geos:
        in_clause("geo", room.geos)
    if room.sources:
        in_clause("source", room.sources)
    if room.year_start is not None:
        clauses.append("fiscal_year >= ?")
        params.append(room.year_start)
    if room.year_end is not None:
        clauses.append("fiscal_year <= ?")
        params.append(room.year_end)

    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    return where, params


def materialise(conn: sqlite3.Connection, room: RoomDefinition) -> list[sqlite3.Row]:
    """Return the observations that make up this room, straight from the store."""
    where, params = _where(room)
    return conn.execute(
        f"""
        SELECT subject_id, geo, taxonomy, concept, unit, measure_type,
               period_start, period_end, fiscal_year, value,
               source, source_url, accession, retrieved_at, licence_class
        FROM observations{where}
        ORDER BY concept, geo, fiscal_year
        """,
        params,
    ).fetchall()


def summary(conn: sqlite3.Connection, room: RoomDefinition) -> dict:
    """Coverage of a room: counts, distinct axes, year range, sources.

    Useful for honesty (what the room actually contains) and for the head to
    know what it can and cannot say.
    """
    where, params = _where(room)
    row = conn.execute(
        f"""
        SELECT count(*) AS n,
               count(DISTINCT subject_id) AS subjects,
               count(DISTINCT geo) AS geos,
               count(DISTINCT concept) AS concepts,
               min(fiscal_year) AS year_min,
               max(fiscal_year) AS year_max
        FROM observations{where}
        """,
        params,
    ).fetchone()
    sources = [
        r[0]
        for r in conn.execute(
            f"SELECT DISTINCT source FROM observations{where} ORDER BY source", params
        )
    ]
    return {
        "observations": row["n"],
        "subjects": row["subjects"],
        "geos": row["geos"],
        "concepts": row["concepts"],
        "year_range": (row["year_min"], row["year_max"]),
        "sources": sources,
    }
