"""Prove the observation store's guarantees with hand-built rows.

No network, no parser — this is a focused test of the store's semantics:

  1. A flow and a stock go in cleanly.
  2. Re-inserting the SAME source assertion is idempotent (0 new rows).
  3. A RESTATEMENT (same concept+period, new accession) is KEPT, not collapsed.
  4. A malformed observation (flow with no start) is REJECTED loudly.

Runs against a throwaway in-memory database so it never touches your real store.
"""

import sqlite3

from terminal_zero.store import (
    Observation,
    count,
    insert_observations,
    measure_type_for,
)


def make(concept, value, *, start, end, accession, mtype):
    return Observation(
        subject_type="company",
        subject_id="CIK:0000002488",          # AMD
        taxonomy="us-gaap",
        concept=concept,
        unit="USD",
        measure_type=mtype,
        period_start=start,
        period_end=end,
        value=value,
        source="sec-edgar",
        source_url="https://data.sec.gov/api/xbrl/companyfacts/CIK0000002488.json",
        retrieved_at="2026-09-01T00:00:00+00:00",
        licence_class="us-gov-public-domain",
        accession=accession,
        form="10-K",
    )


def main() -> None:
    conn = _mem()  # throwaway in-memory store; never touches data/store.db

    # 1. One flow (revenue over a year) + one stock (assets at an instant).
    revenue = make("Revenues", 22_680_000_000, start="2023-01-01", end="2023-12-31",
                   accession="0000002488-24-000012", mtype="flow")
    assets = make("Assets", 67_580_000_000, start=None, end="2023-12-31",
                  accession="0000002488-24-000012", mtype="stock")
    n = insert_observations(conn, [revenue, assets])
    print(f"1. inserted flow + stock: {n} new rows (total {count(conn)})")

    # 2. Re-insert the exact same assertions — must be idempotent.
    n = insert_observations(conn, [revenue, assets])
    print(f"2. re-inserted identical rows: {n} new rows (total {count(conn)})  <- idempotent")

    # 3. A restatement: same concept + period, DIFFERENT accession (a later
    #    filing revised the number). Must be kept as a separate vintage.
    revenue_restated = make("Revenues", 22_110_000_000, start="2023-01-01", end="2023-12-31",
                            accession="0000002488-25-000009", mtype="flow")
    n = insert_observations(conn, [revenue_restated])
    print(f"3. inserted a restatement (new accession): {n} new row (total {count(conn)})  <- vintage kept")

    rows = conn.execute(
        "SELECT value, accession FROM observations WHERE concept='Revenues' "
        "AND period_end='2023-12-31' ORDER BY accession"
    ).fetchall()
    print("   both vintages of FY2023 Revenues now coexist:")
    for r in rows:
        print(f"     {r['value']:>18,.0f}  from {r['accession']}")

    # 4. The flow/stock guard: a flow with no start must be refused.
    print("4. try to store a flow with no period_start (should raise):")
    try:
        bad = make("Revenues", 1, start=None, end="2023-12-31",
                   accession="x", mtype="flow")
        insert_observations(conn, [bad])
        print("   ERROR: it did NOT raise (bug!)")
    except ValueError as e:
        print(f"   refused: {e}")

    # bonus: measure_type_for infers the right type from the period shape
    print(f"\n   measure_type_for(start='2023-01-01') = {measure_type_for('2023-01-01')}")
    print(f"   measure_type_for(start=None)         = {measure_type_for(None)}")


def _mem():
    """A store backed by an in-memory SQLite db (throwaway)."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    from terminal_zero.store import SCHEMA
    conn.executescript(SCHEMA)
    return conn


if __name__ == "__main__":
    main()
