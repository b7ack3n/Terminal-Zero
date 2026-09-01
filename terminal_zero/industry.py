"""Industry name -> SIC code(s): the curated taxonomy layer.

This is the first hop of resolution, and it is deliberately *curated*, not a
fuzzy lookup. SIC is a coarse, decades-old government taxonomy, and the mapping
from a plain-English industry to SIC codes is a judgement call that belongs in
the open — the same spirit as "report what sources say, attributed and dated".

Concretely: the only public tree-nut processor, John B. Sanfilippo (JBSS), is
filed under SIC 2060 "Sugar & Confectionery Products", not under any "nuts"
code. And SIC 2068 / 0173 have zero public 10-K filers at all. So "tree nuts"
does not resolve cleanly from EDGAR, and pretending otherwise would fabricate
coverage. We record that honestly.

Each entry keeps a `note` explaining the choice, so a room built on it inherits
the reasoning, not just the codes.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class IndustryMapping:
    name: str
    sic: list[str] = field(default_factory=list)  # empty = no clean coverage
    note: str = ""


# The seed. Small on purpose — this grows one deliberate entry at a time.
INDUSTRY_SIC: dict[str, IndustryMapping] = {
    "semiconductors": IndustryMapping(
        name="semiconductors",
        sic=["3674"],
        note="SIC 3674 'Semiconductors & Related Devices'. Deep public coverage.",
    ),
    "airlines": IndustryMapping(
        name="airlines",
        sic=["4512"],
        note="SIC 4512 'Air Transportation, Scheduled'. Good public coverage.",
    ),
    "tree nuts": IndustryMapping(
        name="tree nuts",
        sic=[],
        note=(
            "No clean EDGAR coverage. SIC 2068 (Salted & Roasted Nuts & Seeds) "
            "and 0173 (Tree Nuts, farming) have zero public 10-K filers. The one "
            "public nut processor, JBSS, files under SIC 2060 (Sugar & "
            "Confectionery) — a superset, not a tree-nut industry. Reporting on "
            "this industry from EDGAR alone would overstate coverage."
        ),
    ),
}


def resolve(industry: str) -> IndustryMapping | None:
    """Look up an industry's mapping, case-insensitively. None if unknown."""
    return INDUSTRY_SIC.get(industry.strip().lower())
