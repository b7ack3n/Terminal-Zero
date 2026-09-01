"""Smoke test for the EDGAR fetcher.

Run it twice and watch the difference:

    export TERMINAL_ZERO_CONTACT="Your Name your.email@example.com"
    python scripts/smoke_fetch.py

First run hits the SEC over the network. Second run serves from the on-disk
cache and reports the *same* retrieved_at — proving vintage is pinned at first
fetch, not re-stamped on every read.

What it fetches: EDGAR's master entity index (company_tickers.json), which
maps ticker -> CIK -> company name. This is the universe of public filers we
will later slice by industry. Nothing here is parsed into the store yet; this
is only proving the fetch + cache + provenance layer.
"""

from terminal_zero.edgar.fetcher import Fetcher

# The SEC's canonical ticker -> CIK -> name index.
ENTITY_INDEX_URL = "https://www.sec.gov/files/company_tickers.json"


def main() -> None:
    fetcher = Fetcher()

    result = fetcher.get(ENTITY_INDEX_URL)
    entities = result.json()  # dict keyed "0", "1", ... -> {cik_str, ticker, title}

    print("=== fetch provenance ===")
    print(f"url          : {result.url}")
    print(f"status       : {result.status}")
    print(f"retrieved_at : {result.retrieved_at}")
    print(f"from_cache   : {result.from_cache}")
    print(f"bytes        : {len(result.body):,}")
    print()

    print(f"=== entity index: {len(entities):,} public filers ===")
    for row in list(entities.values())[:5]:
        cik = str(row["cik_str"]).zfill(10)  # SEC APIs want 10-digit zero-padded CIKs
        print(f"  {row['ticker']:<8} CIK{cik}  {row['title']}")
    print()

    # A tiny taste of "resolve toward entities": who here looks nut-related?
    needle = "nut"
    hits = [
        r for r in entities.values()
        if needle in r["title"].lower()
    ]
    print(f'=== companies whose name contains "{needle}" ({len(hits)}) ===')
    for row in hits[:10]:
        cik = str(row["cik_str"]).zfill(10)
        print(f"  {row['ticker']:<8} CIK{cik}  {row['title']}")


if __name__ == "__main__":
    main()
