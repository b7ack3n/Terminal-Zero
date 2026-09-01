"""Tests for rooms: manifest round-trip, save/load, materialise filters, summary."""

import sqlite3
import unittest

from terminal_zero import room
from terminal_zero.store import SCHEMA, Observation, insert_observations


def mem_store() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def industry_obs(concept, geo, year, value, mtype="stock"):
    return Observation(
        subject_type="industry",
        subject_id="NAICS:334413",
        geo=geo,
        taxonomy="bls-qcew",
        concept=concept,
        unit="employees",
        measure_type=mtype,
        period_start=f"{year}-01-01" if mtype == "flow" else None,
        period_end=f"{year}-12-31",
        fiscal_year=year,
        fiscal_period="A",
        value=value,
        source="bls-qcew",
        source_url="https://data.bls.gov/x.csv",
        retrieved_at="2026-09-01T00:00:00+00:00",
        licence_class="us-gov-public-domain",
    )


def seed(conn):
    insert_observations(conn, [
        industry_obs("annual_avg_emplvl", "US", 2022, 199_367),
        industry_obs("annual_avg_emplvl", "US", 2023, 203_618),
        industry_obs("annual_avg_emplvl", "STATE:06", 2023, 45_740),
        industry_obs("annual_avg_emplvl", "STATE:48", 2023, 34_374),
        industry_obs("annual_avg_estabs", "US", 2023, 2_423),
    ])


class ManifestRoundTrip(unittest.TestCase):
    def test_to_from_json(self):
        d = room.RoomDefinition(name="r", subject_ids=["NAICS:334413"], year_start=2019)
        back = room.RoomDefinition.from_json(d.to_json())
        self.assertEqual(back, d)


class SaveLoad(unittest.TestCase):
    def test_save_load_and_upsert(self):
        conn = mem_store()
        d = room.RoomDefinition(name="r", note="v1")
        room.save(conn, d)
        self.assertEqual(room.list_rooms(conn), ["r"])
        room.save(conn, room.RoomDefinition(name="r", note="v2"))  # upsert, no dup
        self.assertEqual(room.list_rooms(conn), ["r"])
        self.assertEqual(room.load(conn, "r").note, "v2")

    def test_load_missing_is_none(self):
        self.assertIsNone(room.load(mem_store(), "nope"))


class Materialise(unittest.TestCase):
    def setUp(self):
        self.conn = mem_store()
        seed(self.conn)

    def test_no_filters_returns_all(self):
        d = room.RoomDefinition(name="all")
        self.assertEqual(len(room.materialise(self.conn, d)), 5)

    def test_concept_and_geo_filter(self):
        d = room.RoomDefinition(name="r", concepts=["annual_avg_emplvl"], geos=["US"])
        rows = room.materialise(self.conn, d)
        self.assertEqual(len(rows), 2)  # US employment for 2022 + 2023
        self.assertTrue(all(r["geo"] == "US" for r in rows))

    def test_year_range_filter(self):
        d = room.RoomDefinition(name="r", year_start=2023, year_end=2023)
        rows = room.materialise(self.conn, d)
        self.assertTrue(all(r["fiscal_year"] == 2023 for r in rows))
        self.assertEqual(len(rows), 4)


class Summary(unittest.TestCase):
    def test_summary_coverage(self):
        conn = mem_store()
        seed(conn)
        s = room.summary(conn, room.RoomDefinition(name="r", subject_ids=["NAICS:334413"]))
        self.assertEqual(s["observations"], 5)
        self.assertEqual(s["subjects"], 1)
        self.assertEqual(s["geos"], 3)          # US, CA, TX
        self.assertEqual(s["concepts"], 2)      # employment, establishments
        self.assertEqual(s["year_range"], (2022, 2023))
        self.assertEqual(s["sources"], ["bls-qcew"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
