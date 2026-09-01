"""Configuration for Terminal Zero.

Kept deliberately small and explicit. The one value you *must* set is the
SEC contact string — see `sec_contact()` below.
"""

from __future__ import annotations

import os
from pathlib import Path

# Repo root = one level above this package directory.
ROOT = Path(__file__).resolve().parent.parent

# Where raw fetched responses live. Gitignored: this is a cache, not source.
CACHE_DIR = ROOT / "data" / "cache"

# SEC asks callers to identify themselves in the User-Agent header so they can
# contact you if your traffic misbehaves. It is their fair-access policy, not
# optional — requests without a sensible User-Agent can be rejected.
#
# We read it from the environment so your personal contact info never gets
# hard-coded into the repo (and never committed). Set it once per shell:
#
#     export TERMINAL_ZERO_CONTACT="Your Name your.email@example.com"
#
SEC_CONTACT_ENV = "TERMINAL_ZERO_CONTACT"

# SEC's published ceiling is 10 requests/second. We stay well under it by
# default — being a polite citizen costs us nothing at this stage.
DEFAULT_REQUESTS_PER_SECOND = 5.0


def sec_contact() -> str:
    """Return the User-Agent contact string, or raise if it isn't set.

    We raise loudly rather than guessing. A silent default here would either
    get you rate-limited by the SEC or, worse, put someone else's contact
    details on your traffic.
    """
    value = os.environ.get(SEC_CONTACT_ENV, "").strip()
    if not value:
        raise RuntimeError(
            f"Set {SEC_CONTACT_ENV} before fetching from the SEC, e.g.\n"
            f'    export {SEC_CONTACT_ENV}="Your Name your.email@example.com"\n'
            "The SEC requires a contact string in the User-Agent header."
        )
    return value
