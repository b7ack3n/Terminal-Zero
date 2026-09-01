"""Refresh the vendored NAICS backbone from BLS.

    PYTHONPATH=. python scripts/load_naics.py

Writes ``data/reference/naics_titles.csv`` from the BLS QCEW industry-titles
file — the taxonomy Terminal Zero resolves and browses. The parser
(``terminal_zero/naics.py``) reads that committed file; this script is how you
update it when BLS publishes a NAICS revision.

Reference taxonomy, not observations, so it lands in the repo — not the store.
Goes through the shared Fetcher, so it obeys the BLS rate limit and records
provenance like any other fetch.
"""

from terminal_zero import config, naics
from terminal_zero.edgar.fetcher import Fetcher

URL = "https://www.bls.gov/cew/classifications/industry/industry-titles.csv"


def main() -> None:
    res = Fetcher().get(URL)
    nodes = naics.parse_titles_csv(res.body.decode("utf-8"))
    if not nodes:
        raise SystemExit("refusing to write: parsed 0 NAICS codes from the BLS file")

    naics.NAICS_TITLES_CSV.parent.mkdir(parents=True, exist_ok=True)
    naics.NAICS_TITLES_CSV.write_bytes(res.body)

    backbone = naics.Naics(nodes)
    print(f"wrote {naics.NAICS_TITLES_CSV.relative_to(config.ROOT)} "
          f"— {len(backbone)} NAICS codes, {len(backbone.sectors())} sectors")


if __name__ == "__main__":
    main()
