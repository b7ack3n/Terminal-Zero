"""Tests for the QCEW parser — pure, no network, using a small CSV fixture.

The fixture exercises every branch: a US row, a state row, a suppressed row,
a county row, and a non-Private ownership row.
"""

import unittest

from terminal_zero.bls import qcew

# Header trimmed to the columns the parser reads; extra columns are ignored by
# DictReader. Rows, in order:
#   1. US national, Private            -> kept (US)
#   2. California state, Private       -> kept (STATE:06)
#   3. Texas state, Private, suppressed-> skipped (disclosure_code N)
#   4. a county, Private               -> skipped (geo None)
#   5. US national, State Government   -> skipped (own_code != 5)
FIXTURE = (
    "area_fips,own_code,industry_code,disclosure_code,"
    "annual_avg_estabs,annual_avg_emplvl,total_annual_wages\n"
    "US000,5,334413,,2423,203618,41003903590\n"
    "06000,5,334413,,600,60000,15000000000\n"
    "48000,5,334413,N,0,0,0\n"
    "06085,5,334413,,120,20000,5000000000\n"
    "US000,2,334413,,10,500,90000000\n"
)


def parse(text):
    return qcew.parse_industry_csv(
        text,
        naics="334413",
        year=2023,
        source="bls-qcew",
        source_url="https://data.bls.gov/x.csv",
        retrieved_at="2026-09-01T00:00:00+00:00",
        licence_class="us-gov-public-domain",
    )


class GeoMapping(unittest.TestCase):
    def test_us_state_county(self):
        self.assertEqual(qcew.geo_for_area("US000"), "US")
        self.assertEqual(qcew.geo_for_area("06000"), "STATE:06")
        self.assertIsNone(qcew.geo_for_area("06085"))       # county
        self.assertIsNone(qcew.geo_for_area("C0602"))       # MSA


class ParseIndustryCsv(unittest.TestCase):
    def setUp(self):
        self.obs = parse(FIXTURE)

    def test_only_us_and_state_private_disclosed_kept(self):
        geos = {o.geo for o in self.obs}
        self.assertEqual(geos, {"US", "STATE:06"})  # TX suppressed, county+gov skipped

    def test_three_measures_per_kept_row(self):
        # 2 kept rows x 3 measures = 6 observations
        self.assertEqual(len(self.obs), 6)

    def test_flow_and_stock_classification(self):
        by_concept = {o.concept: o for o in self.obs if o.geo == "US"}
        self.assertEqual(by_concept["total_annual_wages"].measure_type, "flow")
        self.assertEqual(by_concept["total_annual_wages"].period_start, "2023-01-01")
        self.assertEqual(by_concept["annual_avg_emplvl"].measure_type, "stock")
        self.assertIsNone(by_concept["annual_avg_emplvl"].period_start)
        self.assertEqual(by_concept["annual_avg_estabs"].measure_type, "stock")

    def test_values_and_units(self):
        us = {o.concept: o for o in self.obs if o.geo == "US"}
        self.assertEqual(us["annual_avg_emplvl"].value, 203618)
        self.assertEqual(us["annual_avg_emplvl"].unit, "employees")
        self.assertEqual(us["total_annual_wages"].value, 41003903590)
        self.assertEqual(us["total_annual_wages"].unit, "USD")

    def test_subject_and_provenance(self):
        o = self.obs[0]
        self.assertEqual(o.subject_type, "industry")
        self.assertEqual(o.subject_id, "NAICS:334413")
        self.assertEqual(o.source, "bls-qcew")
        self.assertEqual(o.taxonomy, "bls-qcew")


if __name__ == "__main__":
    unittest.main(verbosity=2)
