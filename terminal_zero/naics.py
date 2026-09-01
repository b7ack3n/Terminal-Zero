"""The NAICS backbone: the canonical industry spine and browsable tree.

Terminal Zero resolves a plain-English industry to codes, and every report is a
node in an industry taxonomy. That needs a *universe* to resolve into and browse
— the full NAICS classification, not a hand-curated handful. This module is that
universe: every NAICS code (sector down to 6-digit national industry), its
title, its level, and its place in the hierarchy.

Source: the BLS QCEW "industry titles" file, which lists every NAICS code BLS
publishes, each titled ``NAICS <code> <title>``. It is public domain, a clean
CSV, and comes from a source we already fetch (BLS), so it needs no new
credentials. The extra rows BLS adds for its own aggregation levels (e.g.
"10 Total, all industries") carry no ``NAICS `` prefix and are dropped — we keep
only true NAICS codes.

This is *reference taxonomy*, not fetched observations, so the file lives in the
repo (``data/reference/naics_titles.csv``, committed) and must be present for
resolution to work offline. Refresh it with ``scripts/load_naics.py`` when BLS
publishes a NAICS revision.

Hierarchy is implicit in the code: 2-digit = sector, 3 = subsector, 4 = industry
group, 5 = NAICS industry, 6 = national industry. Three sectors are published as
digit ranges (31-33 Manufacturing, 44-45 Retail trade, 48-49 Transportation);
we keep the range as the sector's code and map member prefixes onto it.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from pathlib import Path

from terminal_zero import config

# The taxonomy lives in the repo — it is the classification itself, not data
# points fetched from it, and must be available without a network round-trip.
NAICS_TITLES_CSV = config.ROOT / "data" / "reference" / "naics_titles.csv"

# The three NAICS sectors published as digit ranges. A code's leading two
# digits are mapped through this to find its sector code.
_RANGE_SECTORS = {
    "31": "31-33", "32": "31-33", "33": "31-33",
    "44": "44-45", "45": "44-45",
    "48": "48-49", "49": "48-49",
}
_TITLE_PREFIX = "NAICS "


@dataclass(frozen=True)
class NaicsNode:
    code: str      # e.g. "334413", or a range sector like "31-33"
    title: str     # clean title, e.g. "Semiconductor and related device mfg"
    level: int     # 2 (sector) .. 6 (national industry)


def level_of(code: str) -> int:
    """NAICS level from the code alone. Range sectors (with a dash) are level 2."""
    return 2 if "-" in code else len(code)


def sector_of(code: str) -> str:
    """The 2-digit (or range) sector a code belongs to."""
    if "-" in code:
        return code
    two = code[:2]
    return _RANGE_SECTORS.get(two, two)


def parent(code: str) -> str | None:
    """The immediate parent code, or None for a sector.

    3-digit subsectors roll up to their (possibly range) sector; everything
    deeper drops its last digit.
    """
    if "-" in code or len(code) <= 2:
        return None
    if len(code) == 3:
        return sector_of(code)
    return code[:-1]


def parse_titles_csv(text: str) -> list[NaicsNode]:
    """Parse a BLS industry-titles CSV into NAICS nodes.

    Pure — text in, nodes out (fixture-tested). Only rows whose title begins
    with ``NAICS `` are kept, dropping BLS aggregation rows. Each title is
    cleaned of its ``NAICS <code> `` prefix so it reads as a plain name.
    """
    nodes: list[NaicsNode] = []
    for row in csv.DictReader(io.StringIO(text)):
        code = (row.get("industry_code") or "").strip()
        raw = (row.get("industry_title") or "").strip()
        if not code or not raw.startswith(_TITLE_PREFIX):
            continue
        title = raw[len(_TITLE_PREFIX):]
        if title.startswith(code):
            title = title[len(code):]
        nodes.append(NaicsNode(code=code, title=title.strip(), level=level_of(code)))
    return nodes


class Naics:
    """The loaded NAICS backbone, queryable by code, level, parent, and text."""

    def __init__(self, nodes: list[NaicsNode]):
        self._by_code: dict[str, NaicsNode] = {n.code: n for n in nodes}
        self._children: dict[str, list[str]] = {}
        for n in nodes:
            p = parent(n.code)
            if p is not None:
                self._children.setdefault(p, []).append(n.code)

    def __len__(self) -> int:
        return len(self._by_code)

    def __contains__(self, code: str) -> bool:
        return code in self._by_code

    def get(self, code: str) -> NaicsNode | None:
        return self._by_code.get(code)

    def title(self, code: str) -> str | None:
        node = self._by_code.get(code)
        return node.title if node else None

    def children(self, code: str) -> list[NaicsNode]:
        """Direct descendants of a code, sorted by code."""
        return [self._by_code[c] for c in sorted(self._children.get(code, []))]

    def sectors(self) -> list[NaicsNode]:
        """The top-level sectors — the roots of the browsable tree."""
        return sorted((n for n in self._by_code.values() if n.level == 2),
                      key=lambda n: n.code)

    def industries(self, level: int = 6) -> list[NaicsNode]:
        """All nodes at one level (default: 6-digit national industries)."""
        return sorted((n for n in self._by_code.values() if n.level == level),
                      key=lambda n: n.code)

    def ancestors(self, code: str) -> list[NaicsNode]:
        """The chain from sector down to (but excluding) `code`, top first."""
        chain: list[NaicsNode] = []
        p = parent(code)
        while p is not None:
            node = self._by_code.get(p)
            if node:
                chain.append(node)
            p = parent(p)
        return list(reversed(chain))

    def search(self, text: str, level: int | None = None) -> list[NaicsNode]:
        """Substring/code search, ranked exact-code, then prefix, then contains.

        A deliberately simple first hop — the AI/NL resolver layers on top of
        this later. Restrict to one level with `level` (e.g. 6 for national
        industries only).
        """
        q = text.strip().lower()
        if not q:
            return []
        hits = []
        for node in self._by_code.values():
            if level is not None and node.level != level:
                continue
            t = node.title.lower()
            if q == node.code or q in t:
                hits.append(node)

        def rank(node: NaicsNode):
            t = node.title.lower()
            if q == node.code:
                return (0, node.code)
            if t.startswith(q):
                return (1, node.code)
            return (2, node.code)

        return sorted(hits, key=rank)


def load(path: Path | None = None) -> Naics:
    """Load the vendored NAICS backbone (or a CSV at `path`)."""
    text = (path or NAICS_TITLES_CSV).read_text(encoding="utf-8")
    return Naics(parse_titles_csv(text))
