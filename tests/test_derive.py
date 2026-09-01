"""Tests for the versioned derivation registry."""

import unittest

from terminal_zero import derive


class Derivations(unittest.TestCase):
    def test_avg_annual_pay(self):
        # $41,003,903,590 / 203,618 ≈ 201,376
        pay = derive.apply("avg_annual_pay", 41_003_903_590, 203_618)
        self.assertAlmostEqual(pay, 201_376, delta=1)

    def test_avg_establishment_size(self):
        size = derive.apply("avg_establishment_size", 203_618, 2_423)
        self.assertAlmostEqual(size, 84.03, places=1)

    def test_cagr(self):
        # wages 30.7B -> 52.1B over 5 years ≈ 11.2%/yr
        c = derive.apply("cagr", 30_728_797_884, 52_147_348_965, 5)
        self.assertAlmostEqual(c, 0.1116, places=3)

    def test_yoy(self):
        self.assertAlmostEqual(derive.apply("yoy", 100, 110), 0.10, places=6)

    def test_index_to_base(self):
        self.assertEqual(derive.apply("index_to_base", [100, 150, 200], 100),
                         [100.0, 150.0, 200.0])

    def test_guards_raise(self):
        with self.assertRaises(ValueError):
            derive.apply("avg_annual_pay", 100, 0)
        with self.assertRaises(ValueError):
            derive.apply("cagr", 0, 100, 5)
        with self.assertRaises(ValueError):
            derive.apply("yoy", 0, 100)

    def test_unknown_derivation_raises(self):
        with self.assertRaises(KeyError):
            derive.apply("magic", 1, 2)

    def test_versions_present(self):
        for name in derive.DERIVATIONS:
            self.assertTrue(derive.version(name))


if __name__ == "__main__":
    unittest.main(verbosity=2)
