"""Automated tests for the observation store.

Unlike store_demo.py (which prints), these assert — so a regression fails the
build instead of quietly changing behaviour. Zero dependencies: stdlib unittest,
in-memory SQLite.

    python3 -m unittest tests.test_store      # or: python3 tests/test_store.py
"""

import sqlite3
import unittest

from terminal_zero.store import (
    Observation,
    SCHEMA,
    count,
    insert_observations,
    measure_type_for,
    validate,
)


def mem_store() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def obs(**overrides) -> Observation:
    """A valid baseline observation; override any field per test."""
    base = dict(
        subject_type="company",
        subject_id="CIK:0000002488",
        taxonomy="us-gaap",
        concept="Revenues",
        unit="USD",
        measure_type="flow",
        period_start="2023-01-01",
        period_end="2023-12-31",
        value=22_680_000_000,
        source="sec-edgar",
        source_url="https://data.sec.gov/x",
        retrieved_at="2026-09-01T00:00:00+00:00",
        licence_class="us-gov-public-domain",
        accession="0000002488-24-000012",
        form="10-K",
    )
    base.update(overrides)
    return Observation(**base)


class InsertAndIdempotency(unittest.TestCase):
    def test_insert_returns_new_row_count(self):
        conn = mem_store()
        n = insert_observations(conn, [obs()])
        self.assertEqual(n, 1)
        self.assertEqual(count(conn), 1)

    def test_reinsert_identical_is_idempotent(self):
        conn = mem_store()
        insert_observations(conn, [obs()])
        n = insert_observations(conn, [obs()])  # same assertion again
        self.assertEqual(n, 0)
        self.assertEqual(count(conn), 1)

    def test_flow_and_stock_are_distinct_rows(self):
        conn = mem_store()
        flow = obs(concept="Revenues", measure_type="flow", period_start="2023-01-01")
        stock = obs(concept="Assets", measure_type="stock", period_start=None)
        n = insert_observations(conn, [flow, stock])
        self.assertEqual(n, 2)

    def test_same_measure_different_geo_are_distinct_rows(self):
        # Regression: geo is part of identity — an industry figure for two
        # places must not collapse into one row.
        conn = mem_store()
        us = obs(subject_type="industry", subject_id="NAICS:334413", accession=None,
                 concept="annual_avg_emplvl", measure_type="stock", period_start=None,
                 geo="US", value=203618)
        ca = obs(subject_type="industry", subject_id="NAICS:334413", accession=None,
                 concept="annual_avg_emplvl", measure_type="stock", period_start=None,
                 geo="STATE:06", value=60000)
        n = insert_observations(conn, [us, ca])
        self.assertEqual(n, 2)


class KeepEveryVintage(unittest.TestCase):
    def test_restatement_new_accession_is_kept(self):
        conn = mem_store()
        original = obs(value=22_680_000_000, accession="0000002488-24-000012")
        restated = obs(value=22_110_000_000, accession="0000002488-25-000009")
        insert_observations(conn, [original])
        n = insert_observations(conn, [restated])
        self.assertEqual(n, 1, "a restatement under a new accession must be kept")
        rows = conn.execute(
            "SELECT value FROM observations WHERE concept='Revenues' "
            "AND period_end='2023-12-31' ORDER BY value"
        ).fetchall()
        self.assertEqual([r["value"] for r in rows], [22_110_000_000, 22_680_000_000])

    def test_same_concept_period_same_accession_not_duplicated(self):
        conn = mem_store()
        insert_observations(conn, [obs()])
        insert_observations(conn, [obs(value=999)])  # same identity, different value
        # Same accession+concept+period => same identity => second is ignored.
        self.assertEqual(count(conn), 1)


class FlowStockGuards(unittest.TestCase):
    def test_flow_without_start_raises(self):
        with self.assertRaises(ValueError):
            validate(obs(measure_type="flow", period_start=None))

    def test_stock_with_start_raises(self):
        with self.assertRaises(ValueError):
            validate(obs(measure_type="stock", period_start="2023-01-01"))

    def test_bad_measure_type_raises(self):
        with self.assertRaises(ValueError):
            validate(obs(measure_type="average"))

    def test_measure_type_for_infers_from_period(self):
        self.assertEqual(measure_type_for("2023-01-01"), "flow")
        self.assertEqual(measure_type_for(None), "stock")


class ValueAndRequiredFieldGuards(unittest.TestCase):
    def test_missing_required_field_raises(self):
        with self.assertRaises(ValueError):
            validate(obs(source=""))

    def test_non_numeric_value_raises(self):
        with self.assertRaises(ValueError):
            validate(obs(value="lots"))

    def test_boolean_value_raises(self):
        with self.assertRaises(ValueError):
            validate(obs(value=True))

    def test_nan_value_raises(self):
        with self.assertRaises(ValueError):
            validate(obs(value=float("nan")))

    def test_insert_validates_before_writing(self):
        conn = mem_store()
        with self.assertRaises(ValueError):
            insert_observations(conn, [obs(measure_type="flow", period_start=None)])
        self.assertEqual(count(conn), 0)  # nothing written on a bad batch member


if __name__ == "__main__":
    unittest.main(verbosity=2)
