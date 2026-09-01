"""Pull the LATEST available data for an industry from every source it maps to.

    python scripts/refresh.py semiconductors

No years to specify. The window is computed from today's date; each source
returns whatever it has published, and unpublished periods are skipped. Ingest
is idempotent, so this is safe to re-run — it only adds newly-released data.

This is the answer to "just pull the latest": the fetch→parse→store spine was
built for it (idempotent, gap-tolerant, vintage-stamped); this driver just asks
every source for a rolling window ending now.
"""

import sys
from datetime import date

from terminal_zero import industry
from terminal_zero.bea import gdp, io
from terminal_zero.bls import qcew
from terminal_zero.census import bfs, cbp, trade
from terminal_zero.usda import nass
from terminal_zero.edgar.fetcher import Fetcher
from terminal_zero.store import connect, count, insert_observations


def _latest(conn, subject, concept="gross_output", col="fiscal_year"):
    return conn.execute(
        f"SELECT MAX({col}) FROM observations WHERE subject_id=? AND concept=?",
        (subject, concept)).fetchone()[0]


def main() -> None:
    name = sys.argv[1] if len(sys.argv) > 1 else "semiconductors"
    m = industry.resolve(name)
    if not m:
        raise SystemExit(f"unknown industry {name!r}; known: {', '.join(industry.INDUSTRY_SIC)}")

    naics = m.naics[0] if m.naics else None
    now = date.today().year
    fetcher, conn = Fetcher(), connect()
    before = count(conn)
    report = []

    # QCEW — annual, lags ~1yr. Request a rolling window; skip unpublished years.
    if naics:
        got = []
        for y in range(now - 6, now + 1):
            try:
                insert_observations(conn, qcew.industry_observations(fetcher, naics, y))
                got.append(y)
            except RuntimeError:
                pass
        report.append(("QCEW", max(got) if got else "—"))

    # BEA — annual range in one call (missing years just absent) + recent quarters.
    if m.bea:
        insert_observations(conn, gdp.industry_observations(
            fetcher, m.bea[0], range(now - 6, now + 1), quarters=[now - 1, now]))
        report.append(("BEA annual", _latest(conn, f"BEA:{m.bea[0]}", "gross_output")))
        report.append(("BEA quarter", conn.execute(
            "SELECT fiscal_year||' '||fiscal_period FROM observations WHERE subject_id=? "
            "AND concept='gross_output_saar' ORDER BY period_end DESC LIMIT 1",
            (f"BEA:{m.bea[0]}",)).fetchone()[0]))

    # CBP — annual, lags ~2yr. Walk back to the latest published year.
    if naics:
        for y in range(now, now - 5, -1):
            try:
                obs = cbp.industry_observations(fetcher, naics, y)
            except RuntimeError:
                continue
            if obs:
                insert_observations(conn, obs)
                report.append(("CBP", y))
                break

    # BEA Input-Output (Use table) — annual, lags ~2yr. Walk back to latest.
    if m.bea:
        for y in range(now, now - 5, -1):
            try:
                obs = io.use_observations(fetcher, m.bea[0], y)
            except RuntimeError:
                continue
            if obs:
                insert_observations(conn, obs)
                report.append(("BEA I-O", y))
                break

    # Trade — monthly, near-current. Recent years; skips months not yet posted.
    if m.hs:
        insert_observations(conn, trade.hs_observations(fetcher, m.hs[0], range(now - 2, now + 1)))
        latest = conn.execute("SELECT MAX(period_end) FROM observations WHERE subject_id=?",
                              (f"HS:{m.hs[0]}",)).fetchone()[0]
        report.append(("Trade", latest))

    # BFS — new-business applications/formations (sector level), monthly.
    if m.bfs:
        insert_observations(conn, bfs.sector_observations(fetcher, m.bfs, now - 2))
        latest = conn.execute("SELECT MAX(period_end) FROM observations WHERE subject_id=?",
                              (f"BFS:{m.bfs}",)).fetchone()[0]
        report.append(("BFS", latest))

    # USDA NASS — agricultural production per commodity (for ag industries).
    if m.nass:
        for commodity in m.nass:
            insert_observations(conn, nass.commodity_observations(fetcher, commodity, range(now - 6, now + 1)))
        report.append(("NASS", ", ".join(m.nass)))

    print(f"refreshed '{name}' (as of {date.today()}): store {before:,} -> {count(conn):,}")
    for src, v in report:
        print(f"  {src:<12} latest = {v}")


if __name__ == "__main__":
    main()
