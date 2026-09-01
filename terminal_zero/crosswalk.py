"""Crosswalks: derive a source's native code from a NAICS code — Brick 3.

The linkage registry marks a source PENDING until a crosswalk can turn a NAICS
code into that source's own classification. This module holds those crosswalks.

Only NAICS -> BEA is bulk-derived here, and deliberately so:

  * BEA GDP-by-Industry uses a small, stable ~66-industry "Summary" scheme whose
    members are clean groupings of NAICS prefixes. That makes market size (gross
    output) derivable for almost any industry with high confidence — the single
    most valuable "get up to speed" number.

  * NAICS -> SIC and NAICS -> HS are NOT bulk-derived. SIC is a retired, coarse
    scheme whose mapping is a judgement call (the tree-nut case: the one public
    filer sits under Confectionery, not any nut code); HS is a huge many-to-many
    goods concordance. Auto-deriving either would manufacture coverage, which is
    the one thing this product must never do. They stay CURATED where we've
    vetted them and PENDING otherwise — an honest gap, not a wrong number.

The BEA concordance below is hand-encoded from BEA's published GDP-by-Industry
Summary structure. A NAICS code resolves to the BEA industry that *contains* it
(longest-prefix match); no match returns None, leaving the link PENDING rather
than guessing. Because BEA is coarser than NAICS, a derived match is a labelled
*superset* — the brief already says so.
"""

from __future__ import annotations

# BEA GDP-by-Industry Summary code -> the NAICS prefixes it covers. Encoded from
# BEA's published concordance; groupings (e.g. 311FT = food + beverage/tobacco)
# are BEA's own. Sectors BEA treats specially and NAICS restructured across
# vintages (Information 51, government 92, imputed housing) are left out — those
# stay PENDING rather than resolve to a shaky match.
_BEA_NAICS: dict[str, tuple[str, ...]] = {
    # Agriculture, forestry, fishing
    "111CA": ("111", "112"),
    "113FF": ("113", "114", "115"),
    # Mining
    "211": ("211",), "212": ("212",), "213": ("213",),
    # Utilities, construction
    "22": ("22",), "23": ("23",),
    # Manufacturing — nondurable
    "311FT": ("311", "312"),
    "313TT": ("313", "314"),
    "315AL": ("315", "316"),
    "322": ("322",), "323": ("323",), "324": ("324",),
    "325": ("325",), "326": ("326",),
    # Manufacturing — durable
    "321": ("321",), "327": ("327",),
    "331": ("331",), "332": ("332",), "333": ("333",),
    "334": ("334",), "335": ("335",),
    "3361MV": ("3361", "3362", "3363"),
    "3364OT": ("3364", "3365", "3366", "3369"),
    "337": ("337",), "339": ("339",),
    # Wholesale, retail
    "42": ("42",),
    "441": ("441",), "445": ("445",), "452": ("452",),
    "4A0": ("442", "443", "444", "446", "447", "448", "451", "453", "454"),
    # Transportation, warehousing
    "481": ("481",), "482": ("482",), "483": ("483",), "484": ("484",),
    "485": ("485",), "486": ("486",),
    "487OS": ("487", "488", "492"),
    "493": ("493",),
    # Finance, insurance
    "521CI": ("521", "522"),
    "523": ("523",), "524": ("524",), "525": ("525",),
    # Real estate, rental
    "ORE": ("531",),                 # imputed owner-occupied housing (HS) is separate
    "532RL": ("532", "533"),
    # Professional, scientific, technical
    "5411": ("5411",),
    "5415": ("5415",),
    "5412OP": ("5412", "5413", "5414", "5416", "5417", "5418", "5419"),
    # Management, admin, waste
    "55": ("55",), "561": ("561",), "562": ("562",),
    # Education, health, social
    "61": ("61",),
    "621": ("621",), "622": ("622",), "623": ("623",), "624": ("624",),
    # Arts, accommodation, other services
    "711AS": ("711", "712"),
    "713": ("713",), "721": ("721",), "722": ("722",),
    "81": ("81",),
}

# Invert to prefix -> BEA code for longest-prefix lookup.
_PREFIX_TO_BEA: dict[str, str] = {
    prefix: bea for bea, prefixes in _BEA_NAICS.items() for prefix in prefixes
}


def bea_for(naics: str) -> str | None:
    """The BEA Summary industry that contains this NAICS code, or None.

    Longest-prefix match (4 -> 3 -> 2 digits). None means no confident match —
    the registry keeps the BEA link PENDING rather than resolve to a guess.
    """
    code = naics.replace("-", "")
    for length in (4, 3, 2):
        if len(code) >= length:
            hit = _PREFIX_TO_BEA.get(code[:length])
            if hit:
                return hit
    return None
