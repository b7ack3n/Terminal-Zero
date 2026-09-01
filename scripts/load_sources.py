"""Load CBP, trade, and NASS data into the store.

    export CENSUS_API_KEY=... NASS_API_KEY=...
    python scripts/load_sources.py cbp    334413 2023
    python scripts/load_sources.py trade  8542   2024 2026
    python scripts/load_sources.py nass   ALMONDS 2019 2024
"""

import sys

from terminal_zero.census import cbp, trade
from terminal_zero.usda import nass
from terminal_zero.edgar.fetcher import Fetcher
from terminal_zero.store import connect, count, insert_observations


def main() -> None:
    kind = sys.argv[1]
    fetcher, conn = Fetcher(), connect()

    if kind == "cbp":
        naics, year = sys.argv[2], int(sys.argv[3])
        obs = cbp.industry_observations(fetcher, naics, year)
    elif kind == "trade":
        hs, y0, y1 = sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
        obs = trade.hs_observations(fetcher, hs, range(y0, y1 + 1))
    elif kind == "nass":
        commodity, y0, y1 = sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
        obs = nass.commodity_observations(fetcher, commodity, range(y0, y1 + 1))
    else:
        raise SystemExit(f"unknown kind {kind!r} (cbp|trade|nass)")

    inserted = insert_observations(conn, obs)
    print(f"{kind}: parsed {len(obs)}, inserted {inserted} new (store now {count(conn):,})")


if __name__ == "__main__":
    main()
