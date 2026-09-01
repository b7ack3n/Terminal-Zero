"""Tests for the geography reference labels."""

import unittest

from terminal_zero import geo


class GeoLabels(unittest.TestCase):
    def test_us(self):
        self.assertEqual(geo.label("US"), "United States")

    def test_states(self):
        self.assertEqual(geo.label("STATE:06"), "California")
        self.assertEqual(geo.label("STATE:48"), "Texas")
        self.assertEqual(geo.label("STATE:11"), "District of Columbia")
        self.assertEqual(geo.label("STATE:72"), "Puerto Rico")

    def test_unknown_code_passes_through(self):
        self.assertEqual(geo.label("STATE:99"), "STATE:99")
        self.assertEqual(geo.label("COUNTY:06085"), "COUNTY:06085")

    def test_none_and_empty(self):
        self.assertEqual(geo.label(None), "—")
        self.assertEqual(geo.label(""), "—")

    def test_reference_is_complete(self):
        # 50 states + DC + 5 territories = 56 entries.
        self.assertEqual(len(geo.FIPS_STATE), 56)


if __name__ == "__main__":
    unittest.main(verbosity=2)
