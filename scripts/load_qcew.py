"""Load QCEW industry data across several years into the store, then read back.

    export TERMINAL_ZERO_CONTACT="Your Name your.email@example.com"
    python scripts/load_qcew.py 334413 2019 2024

Args: NAICS [start_year] [end_year]. Defaults: 334413, 2019, 2024.

Proves the full industry pipeline as a time series: fetch (rate-limited,
cached) -> parse (flow/stock aware) -> store (provenance, idempotent) -> query.
"""

import sys

from terminal_zero import geo
from terminal_zero.bls import qcew
from terminal_zero.edgar.fetcher import Fetcher
from terminal_zero.store import connect, count, insert_observations


def main() -> None:
    naics = sys.argv[1] if len(sys.argv) > 1 else "334413"
    start_year = int(sys.argv[2]) if len(sys.argv) > 2 else 2019
    end_year = int(sys.argv[3]) if len(sys.argv) > 3 else 2024

    fetcher = Fetcher()
    conn = connect()
    subject = f"NAICS:{naics}"

    print(f"=== loading NAICS {naics}, {start_year}-{end_year} ===")
    for year in range(start_year, end_year + 1):
        try:
            observations = qcew.industry_observations(fetcher, naics, year)
        except RuntimeError as exc:
            print(f"  {year}: unavailable ({str(exc).splitlines()[0][:60]})")
            continue
        inserted = insert_observations(conn, observations)
        print(f"  {year}: parsed {len(observations):>3}, inserted {inserted:>3} new")
    print(f"store now holds {count(conn):,} observations")

    # US time series — the shape of a trend a brief would report.
    print(f"\n=== United States, NAICS {naics}: employment & wages by year ===")
    rows = conn.execute(
        """
        SELECT fiscal_year,
               MAX(CASE WHEN concept='annual_avg_emplvl'  THEN value END) AS emp,
               MAX(CASE WHEN concept='total_annual_wages' THEN value END) AS wages,
               MAX(CASE WHEN concept='annual_avg_estabs'  THEN value END) AS estabs
        FROM observations
        WHERE subject_id=? AND geo='US'
        GROUP BY fiscal_year ORDER BY fiscal_year
        """,
        (subject,),
    ).fetchall()
    print(f"  {'year':<6}{'establishments':>16}{'employment':>14}{'total wages':>20}")
    for r in rows:
        print(f"  {r['fiscal_year']:<6}{r['estabs']:>16,.0f}{r['emp']:>14,.0f}"
              f"{r['wages']:>20,.0f}")

    # Latest year, top states by employment — with readable names now.
    latest = rows[-1]["fiscal_year"] if rows else end_year
    print(f"\n=== top 8 states by employment, {latest} ===")
    states = conn.execute(
        """
        SELECT geo, value FROM observations
        WHERE subject_id=? AND fiscal_year=? AND concept='annual_avg_emplvl'
          AND geo LIKE 'STATE:%'
        ORDER BY value DESC LIMIT 8
        """,
        (subject, latest),
    ).fetchall()
    for r in states:
        print(f"  {geo.label(r['geo']):<22}{r['value']:>12,.0f} employees")


if __name__ == "__main__":
    main()
