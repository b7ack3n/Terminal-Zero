"""Tests for the NAICS backbone.

The pure parser is tested on a small fixture; the loaded-registry behaviour is
tested against the vendored file so the real taxonomy stays coherent.
"""

import unittest

from terminal_zero import naics

# A miniature industry-titles file: a range sector, a plain sector, the chain
# down to a 6-digit industry, and two BLS aggregation rows that must be dropped.
FIXTURE = (
    '"industry_code","industry_title"\n'
    '"10","10 Total, all industries"\n'
    '"1013","1013 Manufacturing"\n'
    '"11","NAICS 11 Agriculture, forestry, fishing and hunting"\n'
    '"111","NAICS 111 Crop production"\n'
    '"1113","NAICS 1113 Fruit and tree nut farming"\n'
    '"11133","NAICS 11133 Noncitrus fruit and tree nut farming"\n'
    '"111335","NAICS 111335 Tree nut farming"\n'
    '"31-33","NAICS 31-33 Manufacturing"\n'
    '"334","NAICS 334 Computer and electronic product manufacturing"\n'
    '"334413","NAICS 334413 Semiconductor and related device manufacturing"\n'
)


class TestParse(unittest.TestCase):
    def setUp(self):
        self.nodes = naics.parse_titles_csv(FIXTURE)
        self.by_code = {n.code: n for n in self.nodes}

    def test_drops_bls_aggregation_rows(self):
        # "10" and "1013" have no "NAICS " prefix -> not real NAICS codes.
        self.assertNotIn("10", self.by_code)
        self.assertNotIn("1013", self.by_code)
        self.assertEqual(len(self.nodes), 8)

    def test_title_is_cleaned(self):
        self.assertEqual(self.by_code["111335"].title, "Tree nut farming")
        self.assertEqual(self.by_code["31-33"].title, "Manufacturing")

    def test_levels(self):
        self.assertEqual(self.by_code["11"].level, 2)
        self.assertEqual(self.by_code["31-33"].level, 2)   # range sector
        self.assertEqual(self.by_code["111"].level, 3)
        self.assertEqual(self.by_code["111335"].level, 6)


class TestHierarchy(unittest.TestCase):
    def test_sector_of(self):
        self.assertEqual(naics.sector_of("111335"), "11")
        self.assertEqual(naics.sector_of("334413"), "31-33")  # 33 -> range
        self.assertEqual(naics.sector_of("481111"), "48-49")
        self.assertEqual(naics.sector_of("31-33"), "31-33")

    def test_parent(self):
        self.assertIsNone(naics.parent("11"))
        self.assertIsNone(naics.parent("31-33"))
        self.assertEqual(naics.parent("111"), "11")        # subsector -> sector
        self.assertEqual(naics.parent("334"), "31-33")     # subsector -> range sector
        self.assertEqual(naics.parent("111335"), "11133")
        self.assertEqual(naics.parent("11133"), "1113")


class TestRegistry(unittest.TestCase):
    def setUp(self):
        self.n = naics.Naics(naics.parse_titles_csv(FIXTURE))

    def test_children_and_contains(self):
        self.assertIn("334413", self.n)
        self.assertEqual([c.code for c in self.n.children("31-33")], ["334"])
        self.assertEqual([c.code for c in self.n.children("11133")], ["111335"])

    def test_ancestors_chain(self):
        chain = [n.code for n in self.n.ancestors("111335")]
        self.assertEqual(chain, ["11", "111", "1113", "11133"])

    def test_search_ranks_exact_and_prefix(self):
        hits = self.n.search("tree nut")
        self.assertEqual(hits[0].code, "111335")  # title starts with "Tree nut"
        # exact code beats title match
        self.assertEqual(self.n.search("334413")[0].code, "334413")

    def test_sectors_and_industries(self):
        self.assertEqual({s.code for s in self.n.sectors()}, {"11", "31-33"})
        self.assertEqual(
            {i.code for i in self.n.industries(level=6)}, {"111335", "334413"})


class TestVendoredFile(unittest.TestCase):
    """The real committed taxonomy should load and be internally coherent."""

    @classmethod
    def setUpClass(cls):
        cls.n = naics.load()

    def test_has_full_taxonomy(self):
        # ~2,000+ NAICS codes across all levels. BLS lists the 20 standard
        # NAICS sectors plus sector 99 (nonclassifiable) = 21.
        self.assertGreater(len(self.n), 1500)
        self.assertEqual(len(self.n.sectors()), 21)

    def test_known_industries_present_and_titled(self):
        self.assertEqual(self.n.title("334413"),
                         "Semiconductor and related device manufacturing")
        self.assertEqual(self.n.title("111335"), "Tree nut farming")

    def test_every_nonsector_has_a_known_parent(self):
        # No orphans: every non-sector code's parent exists in the backbone.
        missing = [n.code for n in self.n.industries(level=6)
                   if naics.parent(n.code) not in self.n]
        self.assertEqual(missing, [])


if __name__ == "__main__":
    unittest.main()
