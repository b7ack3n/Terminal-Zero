"""Tests for the linkage registry (Brick 2).

Verifies the tiering: curated industries keep their vetted links and honest
gaps, while an arbitrary NAICS code still resolves (NATIVE + DERIVED links)
with its cross-classified sources marked PENDING rather than guessed.
"""

import unittest

from terminal_zero import registry
from terminal_zero.registry import Tier


def _by_subject(links):
    return {(l.source, l.subject_id): l for l in links}


class TestCuratedSemiconductors(unittest.TestCase):
    def setUp(self):
        self.links = registry.links_for("334413")

    def test_native_qcew_and_cbp(self):
        d = _by_subject(self.links)
        self.assertEqual(d[("bls-qcew", "NAICS:334413")].tier, Tier.NATIVE)
        self.assertEqual(d[("census", "NAICS:334413")].tier, Tier.NATIVE)

    def test_bea_sic_hs_are_curated(self):
        tiers = {(l.source, l.subject_id): l.tier for l in self.links}
        self.assertEqual(tiers[("bea", "BEA:334")], Tier.CURATED)
        self.assertEqual(tiers[("sec-edgar", "SIC:3674")], Tier.CURATED)
        self.assertEqual(tiers[("census", "HS:8542")], Tier.CURATED)

    def test_bfs_derived_from_manufacturing_sector(self):
        bfs = next(l for l in self.links if l.subject_id and l.subject_id.startswith("BFS:"))
        self.assertEqual(bfs.subject_id, "BFS:NAICSMNF")
        self.assertEqual(bfs.tier, Tier.DERIVED)

    def test_fred_ppi_candidate_derived_with_primary(self):
        fred = next(l for l in self.links if l.source == "fred")
        self.assertEqual(fred.subject_id, "FRED:PCU334413334413")
        self.assertEqual(fred.tier, Tier.DERIVED)
        self.assertEqual(fred.primary, "BLS PPI")

    def test_nass_is_a_gap_for_a_manufacturing_industry(self):
        nass = next(l for l in self.links if l.source == "usda-nass")
        self.assertEqual(nass.tier, Tier.GAP)
        self.assertIn("not an agricultural", nass.note)


class TestCuratedTreeNuts(unittest.TestCase):
    def setUp(self):
        self.links = registry.links_for("111335")

    def test_edgar_is_an_honest_gap(self):
        # Tree-nut farming has sic=[] with an explanatory note -> GAP, not PENDING.
        edgar = next(l for l in self.links if l.source == "sec-edgar")
        self.assertEqual(edgar.tier, Tier.GAP)
        self.assertTrue(edgar.note)  # carries the "why" from the curated note

    def test_nass_is_curated(self):
        nass = next(l for l in self.links if l.source == "usda-nass")
        self.assertEqual(nass.tier, Tier.CURATED)
        self.assertTrue(nass.subject_id.startswith("NASS:"))

    def test_bea_and_hs_curated(self):
        subs = {l.subject_id for l in self.links}
        self.assertIn("BEA:111CA", subs)
        self.assertIn("HS:0802", subs)


class TestArbitraryIndustry(unittest.TestCase):
    """An uncurated NAICS code still resolves — that's the whole point."""

    def setUp(self):
        # 311230 Breakfast cereal manufacturing — never hand-authored.
        self.links = registry.links_for("311230")

    def test_native_links_present(self):
        d = _by_subject(self.links)
        self.assertEqual(d[("bls-qcew", "NAICS:311230")].tier, Tier.NATIVE)
        self.assertEqual(d[("census", "NAICS:311230")].tier, Tier.NATIVE)

    def test_bea_now_derived_via_crosswalk(self):
        # 311230 was never curated, but the NAICS->BEA crosswalk resolves it.
        bea = next(l for l in self.links if l.source == "bea")
        self.assertEqual(bea.tier, Tier.DERIVED)
        self.assertEqual(bea.subject_id, "BEA:311FT")

    def test_edgar_still_pending_not_guessed(self):
        # SIC has no bulk crosswalk on purpose -> honest PENDING, never fabricated.
        edgar = next(l for l in self.links if l.source == "sec-edgar")
        self.assertEqual(edgar.tier, Tier.PENDING)

    def test_bfs_still_derived_for_manufacturing(self):
        bfs = next(l for l in self.links if l.subject_id and l.subject_id.startswith("BFS:"))
        self.assertEqual(bfs.subject_id, "BFS:NAICSMNF")

    def test_coverage_summary(self):
        cov = registry.coverage("311230")
        self.assertGreaterEqual(cov["native"], 2)
        self.assertGreaterEqual(cov["pending"], 1)  # BEA/SIC not yet crosswalked


class TestMappingFor(unittest.TestCase):
    """resolve() folded onto the registry: curated keeps vetted, else derived."""

    def test_curated_name_keeps_vetted_mapping(self):
        m = registry.mapping_for("semiconductors")
        self.assertEqual(m.naics, ["334413"])
        self.assertEqual(m.hs, ["8542"])          # curated HS survives

    def test_arbitrary_name_derives(self):
        m = registry.mapping_for("breakfast cereal")
        self.assertEqual(m.naics, ["311230"])
        self.assertEqual(m.bea, ["311FT"])        # via crosswalk
        self.assertEqual(m.bfs, "NAICSMNF")       # via sector
        self.assertEqual(m.hs, [])                # honest gap, not fabricated

    def test_raw_naics_code_resolves(self):
        m = registry.mapping_for("325412")
        self.assertEqual(m.naics, ["325412"])
        self.assertEqual(m.bea, ["325"])
        self.assertIn("Pharmaceutical", m.name)

    def test_unknown_returns_none(self):
        self.assertIsNone(registry.mapping_for("zzzz not a real industry zzzz"))


if __name__ == "__main__":
    unittest.main()
