"""Load BEA gross output + value added for a BEA industry into the store.

    export BEA_API_KEY="..."
    python scripts/load_bea.py 334 2019 2024
"""

import sys

from terminal_zero.bea import gdp
from terminal_zero.edgar.fetcher import Fetcher
from terminal_zero.store import connect, count, insert_observations


def main() -> None:
    industry = sys.argv[1] if len(sys.argv) > 1 else "334"
    y0 = int(sys.argv[2]) if len(sys.argv) > 2 else 2019
    y1 = int(sys.argv[3]) if len(sys.argv) > 3 else 2025

    fetcher = Fetcher()
    conn = connect()
    # annual series + the two most recent years of quarters (for currency)
    obs = gdp.industry_observations(fetcher, industry, range(y0, y1 + 1),
                                    quarters=[y1, y1 + 1])
    inserted = insert_observations(conn, obs)
    print(f"BEA industry {industry}: parsed {len(obs)}, inserted {inserted} new "
          f"(store now {count(conn):,})")

    rows = conn.execute(
        "SELECT fiscal_year, concept, value FROM observations "
        "WHERE subject_id=? AND concept='gross_output' ORDER BY fiscal_year",
        (f"BEA:{industry}",),
    ).fetchall()
    print(f"\ngross output, BEA {industry} (from store):")
    for r in rows:
        print(f"  {r['fiscal_year']}  ${r['value']/1e9:,.1f}B")


if __name__ == "__main__":
    main()
