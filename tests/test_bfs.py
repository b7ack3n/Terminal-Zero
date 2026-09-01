"""Fixture test for the Census BFS parser."""

import unittest

from terminal_zero.census import bfs

# time is auto-included in the response; time_slot_id 0 = monthly value.
FIXTURE = ('[["cell_value","time_slot_id","time","category_code","data_type_code","us"],'
           '["9097","0","2024-01","NAICSMNF","BA_BA","1"],'
           '["8538","0","2024-02","NAICSMNF","BA_BA","1"],'
           '["7137","5","2026-01","NAICSMNF","BA_BA","1"]]')   # non-zero slot -> skipped


class ParseBfs(unittest.TestCase):
    def setUp(self):
        self.obs = bfs.parse_bfs(FIXTURE, category="NAICSMNF", concept="bfs_applications",
                                 source="census", source_url="u",
                                 retrieved_at="2026-09-01T00:00:00+00:00",
                                 licence_class="us-gov-public-domain")

    def test_only_monthly_slot_kept(self):
        self.assertEqual(len(self.obs), 2)          # slot 5 dropped

    def test_shape(self):
        o = self.obs[0]
        self.assertEqual(o.subject_id, "BFS:NAICSMNF")
        self.assertEqual(o.value, 9097)
        self.assertEqual(o.measure_type, "flow")
        self.assertEqual(o.period_start, "2024-01-01")
        self.assertEqual(o.period_end, "2024-01-31")


if __name__ == "__main__":
    unittest.main(verbosity=2)
