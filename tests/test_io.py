"""Fixture test for the BEA Input-Output (Use table) parser."""

import unittest

from terminal_zero.bea import io

# Minimal Use-table cells for industry 334: inputs (col=334) and outputs (row=334),
# including aggregate codes that must be excluded.
FIXTURE = """
{"BEAAPI":{"Results":[{"Data":[
  {"Year":"2023","RowCode":"332","RowDescr":"Fabricated metal","ColCode":"334","ColDescr":"Computer","DataValue":"7601"},
  {"Year":"2023","RowCode":"VAPRO","RowDescr":"Value Added","ColCode":"334","ColDescr":"Computer","DataValue":"293761"},
  {"Year":"2023","RowCode":"334","RowDescr":"Computer","ColCode":"334","ColDescr":"Computer","DataValue":"50000"},
  {"Year":"2023","RowCode":"334","RowDescr":"Computer","ColCode":"F040","ColDescr":"Exports","DataValue":"130848"},
  {"Year":"2023","RowCode":"334","RowDescr":"Computer","ColCode":"T019","ColDescr":"Total use","DataValue":"1083300"}
]}]}}
"""


def parse():
    return io.parse_use_table(FIXTURE, industry="334", source="bea",
                              source_url="u", retrieved_at="2026-09-01T00:00:00+00:00",
                              licence_class="us-gov-public-domain")


class ParseUse(unittest.TestCase):
    def setUp(self):
        self.obs = {o.concept: o for o in parse()}

    def test_real_input_kept_aggregates_and_self_dropped(self):
        self.assertIn("io_input:332", self.obs)          # fabricated metal kept
        self.assertNotIn("io_input:VAPRO", self.obs)      # value-added dropped
        self.assertNotIn("io_input:334", self.obs)        # self-input dropped

    def test_real_buyer_kept_total_dropped(self):
        self.assertIn("io_output:F040", self.obs)         # exports kept
        self.assertNotIn("io_output:T019", self.obs)      # total dropped

    def test_millions_to_usd(self):
        self.assertEqual(self.obs["io_input:332"].value, 7601 * 1_000_000)
        self.assertEqual(self.obs["io_input:332"].measure_type, "flow")
        self.assertEqual(self.obs["io_input:332"].subject_id, "BEA:334")


if __name__ == "__main__":
    unittest.main(verbosity=2)
