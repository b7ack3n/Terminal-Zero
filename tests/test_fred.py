"""Tests for the FRED connector (pure parser)."""

import json
import unittest

from terminal_zero import fred

# A miniature FRED observations payload: two good annual points, one missing.
ANNUAL_PAYLOAD = json.dumps({
    "observations": [
        {"date": "2023-01-01", "value": "100.0"},
        {"date": "2024-01-01", "value": "."},        # missing -> skipped
        {"date": "2025-01-01", "value": "112.4"},
    ]
})

MONTHLY_PAYLOAD = json.dumps({
    "observations": [
        {"date": "2025-02-01", "value": "58.2"},
    ]
})


def _parse(payload, **kw):
    base = dict(
        series_id="PCU334413334413", concept="ppi_industry", unit="index",
        measure_type="stock", frequency="A", source="fred",
        source_url="https://fred.stlouisfed.org/series/PCU334413334413",
        retrieved_at="2026-09-01T00:00:00Z", licence_class="us-gov-public-domain",
        primary="BLS PPI",
    )
    base.update(kw)
    return fred.parse_series_observations(payload, **base)


class TestParse(unittest.TestCase):
    def test_skips_missing_and_keeps_values(self):
        obs = _parse(ANNUAL_PAYLOAD)
        self.assertEqual([o.value for o in obs], [100.0, 112.4])
        self.assertEqual([o.fiscal_year for o in obs], [2023, 2025])

    def test_native_subject_and_taxonomy(self):
        o = _parse(ANNUAL_PAYLOAD)[0]
        self.assertEqual(o.subject_id, "FRED:PCU334413334413")
        self.assertEqual(o.taxonomy, "fred")

    def test_primary_publisher_recorded_for_citation(self):
        # Provenance is FRED, but the primary publisher must survive so a brief
        # can cite "BLS PPI (via FRED)", never a bare "FRED".
        o = _parse(ANNUAL_PAYLOAD)[0]
        self.assertEqual(o.source, "fred")
        self.assertEqual(o.frame, "primary:BLS PPI")

    def test_index_level_is_stock_no_period_start(self):
        o = _parse(ANNUAL_PAYLOAD)[0]
        self.assertEqual(o.measure_type, "stock")
        self.assertIsNone(o.period_start)
        self.assertEqual(o.period_end, "2023-12-31")

    def test_flow_gets_period_start(self):
        o = _parse(ANNUAL_PAYLOAD, measure_type="flow")[0]
        self.assertEqual(o.period_start, "2023-01-01")
        self.assertEqual(o.period_end, "2023-12-31")

    def test_monthly_period_end(self):
        o = _parse(MONTHLY_PAYLOAD, frequency="M")[0]
        self.assertEqual(o.period_end, "2025-02-28")   # 2025 not a leap year
        self.assertEqual(o.fiscal_period, "M02")

    def test_accepts_raw_bytes(self):
        obs = _parse(ANNUAL_PAYLOAD.encode("utf-8"))
        self.assertEqual(len(obs), 2)


class TestUrls(unittest.TestCase):
    def test_observations_url_is_key_free(self):
        url = fred.observations_url("INDPRO", observation_start="2019-01-01")
        self.assertIn("series_id=INDPRO", url)
        self.assertIn("observation_start=2019-01-01", url)
        self.assertNotIn("api_key", url)   # key is added by the fetcher, not cached


if __name__ == "__main__":
    unittest.main()
