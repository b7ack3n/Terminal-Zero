"""Generate a framework-structured industry brief HTML from the store.

    python scripts/make_brief.py 334413 "U.S. Semiconductor Manufacturing" out.html

Industry sizing comes from the store (QCEW). Key players are resolved live from
EDGAR (cached) via the industry's SIC code, then passed to the renderer.
"""

import sys

from terminal_zero import brief, industry
from terminal_zero.edgar import entities
from terminal_zero.edgar.fetcher import Fetcher
from terminal_zero.store import connect


def resolve_key_players(fetcher, naics):
    """Resolve public filers for the industry that owns this NAICS, via SIC."""
    mapping = industry.resolve_naics(naics)
    if not mapping or not mapping.sic:
        return None
    index = entities.load_entity_index(fetcher)
    players, sample = [], None
    for sic in mapping.sic:
        named = [f for f in entities.filers_for_sic(fetcher, sic, index=index, max_filers=300) if f.name]
        players.extend(named)
        sample = sample or (named[0] if named else None)
    if not players:
        return None
    return {
        "players": [{"ticker": p.ticker, "name": p.name, "cik": p.cik} for p in players],
        "sic": ",".join(mapping.sic),
        "source": sample.source,
        "source_url": sample.source_url,
        "retrieved_at": sample.retrieved_at,
        "total_named": len(players),
    }


def main() -> None:
    naics = sys.argv[1] if len(sys.argv) > 1 else "334413"
    title = sys.argv[2] if len(sys.argv) > 2 else "U.S. Semiconductor Manufacturing"
    out = sys.argv[3] if len(sys.argv) > 3 else "brief.html"

    fetcher = Fetcher()
    conn = connect()
    key_players = resolve_key_players(fetcher, naics)
    mapping = industry.resolve_naics(naics)
    bea_industry = mapping.bea[0] if mapping and mapping.bea else None
    bea_note = mapping.bea_note if mapping else ""
    html = brief.render(conn, naics, title, key_players=key_players,
                        bea_industry=bea_industry, bea_note=bea_note)
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    n = key_players["total_named"] if key_players else 0
    print(f"wrote {len(html):,} bytes -> {out} ({n} key players, bea={bea_industry})")


if __name__ == "__main__":
    main()
