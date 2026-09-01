"""Fixture tests for the CBP, trade, and NASS parsers — pure, no network."""

import unittest

from terminal_zero.census import cbp, trade
from terminal_zero.usda import nass

PROV = dict(source="x", source_url="u", retrieved_at="2026-09-01T00:00:00+00:00",
            licence_class="us-gov-public-domain")


class CBP(unittest.TestCase):
    TOTALS = '[["ESTAB","EMP","PAYANN","NAICS2017","us"],["822","116831","16028216","334413","1"]]'
    SIZE = ('[["ESTAB","EMPSZES_LABEL","NAICS2017","EMPSZES","us"],'
            '["822","All establishments","334413","001","1"],'
            '["287","<5","334413","210","1"],'
            '["22","1,000+","334413","260","1"]]')

    def test_totals(self):
        obs = {o.concept: o for o in cbp.parse_totals(self.TOTALS, naics="334413", year=2023, **PROV)}
        self.assertEqual(obs["cbp_establishments"].value, 822)
        self.assertEqual(obs["cbp_employment"].measure_type, "stock")
        self.assertEqual(obs["cbp_annual_payroll"].value, 16028216 * 1000)  # $1000s -> USD
        self.assertEqual(obs["cbp_annual_payroll"].measure_type, "flow")

    def test_size_skips_all_and_encodes_class(self):
        obs = cbp.parse_size(self.SIZE, naics="334413", year=2023, **PROV)
        concepts = {o.concept for o in obs}
        self.assertEqual(concepts, {"cbp_estab_size:210", "cbp_estab_size:260"})  # 001 skipped
        self.assertEqual({o.value for o in obs}, {287.0, 22.0})


class Trade(unittest.TestCase):
    EXPORTS = ('[["ALL_VAL_MO","E_COMMODITY","time"],'
               '["3762295868","8542","2025-11"],'
               '["4000000000","8542","2025-12"]]')

    def test_monthly_flows(self):
        obs = trade.parse_trade(self.EXPORTS, direction="exports", hs="8542", **PROV)
        self.assertEqual(len(obs), 2)
        o = obs[0]
        self.assertEqual(o.subject_id, "HS:8542")
        self.assertEqual(o.concept, "exports_value")
        self.assertEqual(o.measure_type, "flow")
        self.assertEqual(o.period_start, "2025-11-01")
        self.assertEqual(o.period_end, "2025-11-30")
        self.assertEqual(o.value, 3762295868)


class NASS(unittest.TestCase):
    DATA = ('{"data":[{"short_desc":"ALMONDS, UTILIZED - PRODUCTION, MEASURED IN TONS",'
            '"Value":"1,931,000","unit_desc":"TONS","year":"2023"},'
            '{"short_desc":"ALMONDS - X","Value":"(D)","unit_desc":"TONS","year":"2023"}]}')

    def test_parses_and_skips_suppressed(self):
        obs = nass.parse_production(self.DATA, commodity="almonds", **PROV)
        self.assertEqual(len(obs), 1)                       # (D) skipped
        o = obs[0]
        self.assertEqual(o.subject_id, "NASS:ALMONDS")
        self.assertEqual(o.value, 1_931_000)
        self.assertEqual(o.unit, "TONS")
        self.assertTrue(o.concept.startswith("nass_production:"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
