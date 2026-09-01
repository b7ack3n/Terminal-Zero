"""Load one QCEW industry-year into the real store and read it back.

    export TERMINAL_ZERO_CONTACT="Your Name your.email@example.com"
    python scripts/load_qcew.py 334413 2023

Proves the full path for an industry source: fetch (rate-limited, cached) ->
parse (flow/stock aware) -> store (provenance, idempotent) -> query back out.
"""

import sys

from terminal_zero.bls import qcew
from terminal_zero.edgar.fetcher import Fetcher
from terminal_zero.store import connect, count, insert_observations


def main() -> None:
    naics = sys.argv[1] if len(sys.argv) > 1 else "334413"
    year = int(sys.argv[2]) if len(sys.argv) > 2 else 2023

    fetcher = Fetcher()
    conn = connect()

    observations = qcew.industry_observations(fetcher, naics, year)
    before = count(conn)
    inserted = insert_observations(conn, observations)
    print(f"NAICS {naics}, {year}: parsed {len(observations)} observations, "
          f"inserted {inserted} new (store now holds {count(conn)}, was {before})")

    # Read the US national picture back OUT of the store (not the parser).
    print(f"\n=== US national, NAICS {naics}, {year} (from the store) ===")
    rows = conn.execute(
        """
        SELECT concept, unit, measure_type, value, source, retrieved_at
        FROM observations
        WHERE subject_id = ? AND geo = 'US' AND fiscal_year = ?
        ORDER BY concept
        """,
        (f"NAICS:{naics}", year),
    ).fetchall()
    for r in rows:
        print(f"  {r['concept']:<20} {r['value']:>18,.0f} {r['unit']:<14} "
              f"[{r['measure_type']}]")
    if rows:
        print(f"  provenance: source={rows[0]['source']} retrieved_at={rows[0]['retrieved_at']}")

    # Top 5 states by employment — a real slice of an industry brief.
    print(f"\n=== top 5 states by employment, NAICS {naics}, {year} ===")
    states = conn.execute(
        """
        SELECT geo, value FROM observations
        WHERE subject_id = ? AND fiscal_year = ?
          AND concept = 'annual_avg_emplvl' AND geo LIKE 'STATE:%'
        ORDER BY value DESC LIMIT 5
        """,
        (f"NAICS:{naics}", year),
    ).fetchall()
    for r in states:
        print(f"  {r['geo']:<12} {r['value']:>12,.0f} employees")


if __name__ == "__main__":
    main()
