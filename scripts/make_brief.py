"""Generate an industry brief HTML from the store.

    python scripts/make_brief.py 334413 "U.S. Semiconductor Manufacturing" out.html
"""

import sys

from terminal_zero import brief
from terminal_zero.store import connect


def main() -> None:
    naics = sys.argv[1] if len(sys.argv) > 1 else "334413"
    title = sys.argv[2] if len(sys.argv) > 2 else "U.S. Semiconductor Manufacturing"
    out = sys.argv[3] if len(sys.argv) > 3 else "brief.html"

    conn = connect()
    html = brief.render(conn, naics, title)
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"wrote {len(html):,} bytes -> {out}")


if __name__ == "__main__":
    main()
