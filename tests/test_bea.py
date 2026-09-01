"""Tests for the BEA GDP-by-Industry parser — pure, no network."""

import unittest

from terminal_zero.bea import gdp

# Minimal shape of a BEA GetData response, with one suppressed value.
FIXTURE = """
{"BEAAPI":{"Results":[{"Data":[
  {"Industry":"334","IndustrYDescription":"Computer and electronic products","Year":"2022","DataValue":"402.6"},
  {"Industry":"334","IndustrYDescription":"Computer and electronic products","Year":"2023","DataValue":"399.4"},
  {"Industry":"334","IndustrYDescription":"Computer and electronic products","Year":"2024","DataValue":"(D)"}
]}]}}
"""


def parse(text):
    return gdp.parse_gdp_json(
        text, concept="gross_output", source="bea",
        source_url="https://apps.bea.gov/api/data/?...",
        retrieved_at="2026-09-01T00:00:00+00:00", licence_class="us-gov-public-domain",
    )


class ParseGdp(unittest.TestCase):
    def setUp(self):
        self.obs = parse(FIXTURE)

    def test_suppressed_skipped(self):
        # (D) row dropped -> 2 observations, not 3
        self.assertEqual(len(self.obs), 2)

    def test_billions_to_usd(self):
        o = {o.fiscal_year: o for o in self.obs}
        self.assertAlmostEqual(o[2023].value, 399.4e9, places=0)

    def test_subject_and_shape(self):
        o = self.obs[0]
        self.assertEqual(o.subject_id, "BEA:334")   # own subject, not NAICS
        self.assertEqual(o.taxonomy, "bea-gdp-by-industry")
        self.assertEqual(o.unit, "USD")
        self.assertEqual(o.measure_type, "flow")     # annual output spans the year
        self.assertEqual(o.period_start, "2022-01-01")
        self.assertEqual(o.geo, "US")


if __name__ == "__main__":
    unittest.main(verbosity=2)
