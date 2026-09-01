"""The linkage registry: bind an industry to its data sources — Brick 2.

Scaling to every NAICS industry ran into a hard truth: the sources DON'T share a
classification. QCEW/CBP key on NAICS; BEA has its own industry codes; trade is
HS; EDGAR is SIC; specialised sources (EIA, USGS, CMS) don't crosswalk to NAICS
at all. Forcing everything into one NAICS bucket would fabricate coverage.

So the registry does NOT flatten sources onto NAICS. NAICS is the ORGANISING
spine (browse + search, `naics.py`) and the crosswalk hub. For an industry, this
module returns a *linkage set*: one SourceLink per source, each tagged with how
we know it and how much to trust it:

  NATIVE   — the source uses the NAICS code directly (QCEW, CBP). Highest trust.
  DERIVED  — computed from the code by a rule (BFS sector; a candidate FRED PPI
             series id). A proposal, verified when we actually fetch it.
  CURATED  — a hand-authored judgement with an honesty note (BEA/SIC/HS/NASS for
             industries we've vetted, e.g. semis -> BEA 334, a labelled superset).
  PENDING  — a crosswalk exists in principle but isn't loaded yet (BEA/SIC/HS for
             arbitrary industries). Honest "in development", not a guess.
  GAP      — no coverage, and we say so (EDGAR for tree-nut farming).

This is what lets 2,144 industries resolve without hand-authoring each: most
links are NATIVE or DERIVED; curation is reserved for judgement calls; and the
data-gated brief renders exactly the modules whose links actually return data.
The next bricks (BEA/SIC/HS crosswalk loaders) turn PENDING links into DERIVED
ones without touching this model.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from terminal_zero import industry, naics


class Tier(str, Enum):
    NATIVE = "native"      # source keys on the NAICS code directly
    DERIVED = "derived"    # computed from the code by a rule; verify at fetch
    CURATED = "curated"    # hand-authored judgement with an honesty note
    PENDING = "pending"    # crosswalk exists but isn't loaded yet
    GAP = "gap"            # no coverage — reported, not filled


@dataclass(frozen=True)
class SourceLink:
    source: str                 # registry key: 'bls-qcew', 'bea', 'fred', ...
    tier: Tier
    subject_id: str | None      # store subject the source writes under; None if PENDING/GAP
    confidence: str             # 'high' | 'medium' | 'low' | 'none'
    note: str = ""
    primary: str | None = None  # FRED links: the primary publisher to cite


# NAICS sector -> Census BFS series code. Plain sectors are NAICS<code>; three
# sectors carry BFS's own abbreviations. Sectors we're unsure of are omitted, so
# they get a PENDING link rather than a wrong code.
_BFS_SECTOR = {
    "11": "NAICS11", "21": "NAICS21", "22": "NAICS22", "23": "NAICS23",
    "42": "NAICS42", "51": "NAICS51", "52": "NAICS52", "53": "NAICS53",
    "54": "NAICS54", "55": "NAICS55", "56": "NAICS56", "61": "NAICS61",
    "62": "NAICS62", "71": "NAICS71", "72": "NAICS72", "81": "NAICS81",
    "31-33": "NAICSMNF", "44-45": "NAICSRET", "48-49": "NAICSTW",
}


def _curated_by_naics() -> dict[str, industry.IndustryMapping]:
    """Index the hand-authored overrides by NAICS code (vetted BEA/SIC/HS/NASS)."""
    idx: dict[str, industry.IndustryMapping] = {}
    for m in industry.INDUSTRY_SIC.values():
        for code in m.naics:
            idx[code] = m
    return idx


_CURATED = _curated_by_naics()


def links_for(code: str) -> list[SourceLink]:
    """Return the linkage set for a NAICS code."""
    curated = _CURATED.get(code)
    sector = naics.sector_of(code)
    subject = f"NAICS:{code}"
    links: list[SourceLink] = [
        # NATIVE — key on the NAICS code itself.
        SourceLink("bls-qcew", Tier.NATIVE, subject, "high",
                   "employment, wages, establishments by NAICS"),
        SourceLink("census", Tier.NATIVE, subject, "high",
                   "CBP establishment size distribution by NAICS"),
    ]

    # DERIVED — Census BFS at sector grain (a labelled superset).
    bfs_code = _BFS_SECTOR.get(sector)
    if bfs_code:
        links.append(SourceLink("census", Tier.DERIVED, f"BFS:{bfs_code}", "medium",
                                f"business formation, sector {sector} (superset)"))
    else:
        links.append(SourceLink("census", Tier.PENDING, None, "none",
                                f"BFS sector code for {sector} not yet mapped"))

    # DERIVED — candidate BLS PPI series via FRED (6-digit industries only).
    if len(code) == 6:
        links.append(SourceLink("fred", Tier.DERIVED, f"FRED:PCU{code}{code}", "low",
                                "candidate BLS PPI series — verify it exists at fetch",
                                primary="BLS PPI"))

    # CURATED / PENDING / GAP — cross-classified sources.
    links.append(_cross("bea", getattr(curated, "bea", None), "BEA:",
                        "market size (gross output / value added)", curated, sector))
    links.append(_cross("sec-edgar", getattr(curated, "sic", None), "SIC:",
                        "public filers (key players)", curated, sector))
    links.append(_cross("census", getattr(curated, "hs", None), "HS:",
                        "trade exposure by HS product", curated, sector))
    links.append(_cross("usda-nass", getattr(curated, "nass", None), "NASS:",
                        "agricultural production value", curated, sector))
    return links


def _cross(src, codes, prefix, label, curated, sector):
    """Build one cross-classified link, honest about how much we know."""
    if src == "usda-nass":
        if codes:
            return SourceLink(src, Tier.CURATED, f"{prefix}{codes[0]}", "high", label)
        if sector == "11":
            return SourceLink(src, Tier.PENDING, None, "none",
                            "NASS commodity mapping not loaded for this crop")
        return SourceLink(src, Tier.GAP, None, "none", "not an agricultural industry")

    if curated is None:
        return SourceLink(src, Tier.PENDING, None, "none",
                        f"{label}: NAICS crosswalk not loaded yet")
    if codes:
        return SourceLink(src, Tier.CURATED, f"{prefix}{codes[0]}", "high", label)
    # Curated entry with a deliberately empty list -> honest, explained gap.
    reason = curated.note.split(". ")[0] if curated.note else f"no {label} coverage"
    return SourceLink(src, Tier.GAP, None, "none", reason)


def coverage(code: str) -> dict[str, int]:
    """Summarise a linkage set by tier — the brief's data gate reads this."""
    out = {t.value: 0 for t in Tier}
    for link in links_for(code):
        out[link.tier.value] += 1
    return out
