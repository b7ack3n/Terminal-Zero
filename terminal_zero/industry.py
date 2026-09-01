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
    sic: list[str] = field(default_factory=list)     # EDGAR axis (key players)
    naics: list[str] = field(default_factory=list)   # QCEW/Census axis (sizing)
    bea: list[str] = field(default_factory=list)      # BEA axis (sector market size)
    bea_note: str = ""                                # honest scope of the BEA match
    hs: list[str] = field(default_factory=list)        # HS codes (trade exposure)
    hs_note: str = ""                                 # honest scope of the HS match
    bfs: str = ""                                      # BFS sector code (new entrants)
    bfs_note: str = ""                                # honest scope of the BFS match
    nass: list[str] = field(default_factory=list)      # USDA NASS commodities (ag production)
    note: str = ""


# The seed. Small on purpose — this grows one deliberate entry at a time.
INDUSTRY_SIC: dict[str, IndustryMapping] = {
    "semiconductors": IndustryMapping(
        name="semiconductors",
        sic=["3674"],
        naics=["334413"],
        bea=["334"],
        bea_note="BEA industry 334 'Computer & electronic products' — a superset "
                 "of semiconductor manufacturing (BEA has no finer detail).",
        hs=["8542"],
        hs_note="HS 8542 'Electronic integrated circuits' — the industry's primary "
                "traded product (excludes discrete devices under HS 8541).",
        bfs="NAICSMNF",
        bfs_note="all Manufacturing (BFS sector level) — a broad superset; the "
                 "industry-specific entry signal is QCEW establishment growth.",
        note="SIC 3674 'Semiconductors & Related Devices'. Deep public coverage.",
    ),
    "airlines": IndustryMapping(
        name="airlines",
        sic=["4512"],
        naics=["481111"],
        note="SIC 4512 'Air Transportation, Scheduled'. Good public coverage.",
    ),
    "tree nuts": IndustryMapping(
        name="tree nuts",
        sic=[],
        naics=["111335"],
        bea=["111CA"],
        bea_note="BEA 'Farms' — all U.S. agriculture, a very broad superset; the "
                 "industry-specific size is USDA value of production.",
        hs=["0802"],
        hs_note="HS 0802 'Nuts, fresh or dried' (almonds, walnuts, pistachios, etc.).",
        bfs="NAICS11",
        bfs_note="all Agriculture (BFS sector) — a broad superset.",
        nass=["ALMONDS", "WALNUTS", "PISTACHIOS", "PECANS"],
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


def resolve_naics(naics: str) -> IndustryMapping | None:
    """Find the industry mapping that owns a NAICS code. None if unknown."""
    for mapping in INDUSTRY_SIC.values():
        if naics in mapping.naics:
            return mapping
    return None
