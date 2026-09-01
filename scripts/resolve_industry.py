"""Resolve an industry to its public filers, end to end.

    export TERMINAL_ZERO_CONTACT="Your Name your.email@example.com"
    python scripts/resolve_industry.py semiconductors
    python scripts/resolve_industry.py "tree nuts"

With no argument it demonstrates both a well-covered industry and one with no
clean EDGAR coverage, so the contrast is visible.
"""

import sys

from terminal_zero import industry
from terminal_zero.edgar.entities import filers_for_sic, load_entity_index
from terminal_zero.edgar.fetcher import Fetcher

# Keep the demo quick; real resolution can lift this.
MAX_FILERS = 300


def resolve_and_print(name: str, fetcher: Fetcher, index) -> None:
    mapping = industry.resolve(name)
    print(f"\n{'=' * 64}\nINDUSTRY: {name}\n{'=' * 64}")

    if mapping is None:
        print(f"  Unknown industry '{name}'. Known: {', '.join(industry.INDUSTRY_SIC)}")
        return

    print(f"  note: {mapping.note}")

    if not mapping.sic:
        print("  -> resolves to 0 SIC codes. No public filers to report.")
        print("     (This is the honest answer, not an error.)")
        return

    for sic in mapping.sic:
        filers = filers_for_sic(fetcher, sic, index=index, max_filers=MAX_FILERS)
        named = [f for f in filers if f.name]
        print(f"\n  SIC {sic}: {len(filers)} filers, {len(named)} with known names")
        for f in named[:8]:
            print(f"    {f.ticker or '—':<7} CIK{f.cik}  {f.name}")
        if filers:
            # Show the provenance carried on every row.
            p = filers[0]
            print(f"\n    provenance (per row): source={p.source} "
                  f"licence={p.licence_class}")
            print(f"      retrieved_at={p.retrieved_at}")
            print(f"      source_url={p.source_url}")


def main() -> None:
    fetcher = Fetcher()
    index = load_entity_index(fetcher)  # load once, reuse across industries

    names = sys.argv[1:] or ["semiconductors", "tree nuts"]
    for name in names:
        resolve_and_print(name, fetcher, index)


if __name__ == "__main__":
    main()
