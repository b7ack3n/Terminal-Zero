"""Tests for the NAICS -> BEA crosswalk (Brick 3)."""

import unittest

from terminal_zero import crosswalk


class TestBeaCrosswalk(unittest.TestCase):
    def test_direct_three_digit(self):
        self.assertEqual(crosswalk.bea_for("334413"), "334")   # semiconductors
        self.assertEqual(crosswalk.bea_for("325199"), "325")   # chemicals

    def test_grouped_aggregates(self):
        self.assertEqual(crosswalk.bea_for("111335"), "111CA")  # tree nuts -> Farms
        self.assertEqual(crosswalk.bea_for("311230"), "311FT")  # cereal -> Food/bev/tobacco
        self.assertEqual(crosswalk.bea_for("336111"), "3361MV") # cars -> Motor vehicles
        self.assertEqual(crosswalk.bea_for("336510"), "3364OT") # rail stock -> Other transport

    def test_two_digit_fallback(self):
        self.assertEqual(crosswalk.bea_for("221111"), "22")     # utilities
        self.assertEqual(crosswalk.bea_for("541511"), "5415")   # computer systems design
        self.assertEqual(crosswalk.bea_for("541611"), "5412OP") # mgmt consulting -> misc prof

    def test_other_retail_bucket(self):
        self.assertEqual(crosswalk.bea_for("448140"), "4A0")    # clothing store -> Other retail

    def test_unmapped_returns_none(self):
        # Government (92) and the vintage-restructured Information codes are left
        # out on purpose -> None, so the registry keeps them PENDING not wrong.
        self.assertIsNone(crosswalk.bea_for("921110"))          # public admin
        self.assertIsNone(crosswalk.bea_for("999999"))


if __name__ == "__main__":
    unittest.main()
