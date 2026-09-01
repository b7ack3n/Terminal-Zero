"""The source registry: one row per data source we fetch from.

Every source has its *own* rate limit, its *own* auth style, and its *own*
licensing. Putting them in one table means the fetcher can look up "how fast
may I hit this host, and how do I authenticate" from the URL alone — so adding
a source later is a data change here, not new fetching logic.

Rate limits below are deliberately conservative (at or under each publisher's
stated ceiling). Being a polite citizen costs us nothing and keeps us unblocked.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass(frozen=True)
class Source:
    key: str                      # stable id stamped onto every observation
    hosts: tuple[str, ...]        # hostnames that belong to this source
    requests_per_second: float    # our self-imposed ceiling for this host
    licence_class: str            # licensing of the data (provenance)
    docs: str                     # where the access rules are documented
    auth: str = "none"            # none | user_agent | query_param | bearer
    auth_env: str | None = None   # env var holding the key/contact/token
    auth_param: str | None = None # query_param style: the parameter name


# The registry. EDGAR is the only one wired end-to-end today; the rest are
# declared so their rate limits and auth are ready the moment we add them.
SOURCES: tuple[Source, ...] = (
    Source(
        key="sec-edgar",
        hosts=("www.sec.gov", "data.sec.gov", "efts.sec.gov"),
        requests_per_second=5.0,                       # SEC ceiling is 10/s
        licence_class="us-gov-public-domain",
        docs="https://www.sec.gov/os/webmaster-faq#developers",
        auth="user_agent",
        auth_env="TERMINAL_ZERO_CONTACT",
    ),
    Source(
        key="bls-qcew",
        hosts=("data.bls.gov", "www.bls.gov"),
        requests_per_second=2.0,                       # static CSV files; be polite
        licence_class="us-gov-public-domain",
        docs="https://www.bls.gov/cew/additional-resources/open-data/",
        auth="none",
    ),
    Source(
        key="census",
        hosts=("api.census.gov",),
        requests_per_second=3.0,                       # 500/day free without key
        licence_class="us-gov-public-domain",
        docs="https://www.census.gov/data/developers.html",
        auth="query_param",
        auth_env="CENSUS_API_KEY",
        auth_param="key",
    ),
    Source(
        key="usda-nass",
        hosts=("quickstats.nass.usda.gov",),
        requests_per_second=1.0,                       # 50k rows/query cap
        licence_class="us-gov-public-domain",
        docs="https://quickstats.nass.usda.gov/api",
        auth="query_param",
        auth_env="NASS_API_KEY",
        auth_param="key",
    ),
    Source(
        key="bea",
        hosts=("apps.bea.gov",),
        requests_per_second=1.5,                       # 100 req/min stated ceiling
        licence_class="us-gov-public-domain",
        docs="https://apps.bea.gov/api/",
        auth="query_param",
        auth_env="BEA_API_KEY",
        auth_param="UserID",                           # BEA names its key param UserID
    ),
    Source(
        # FRED aggregates 800k+ series from 100+ publishers behind one API. We
        # ingest ONLY series whose underlying publisher is US-gov public domain
        # (BLS, BEA, Census, Fed, EIA, Treasury) — never FRED's copyrighted
        # third-party series (OECD, World Bank, private) — and we always carry
        # the primary publisher as the citation. FRED is a convenience layer for
        # breadth, not a replacement for primary sources where granularity matters.
        key="fred",
        hosts=("api.stlouisfed.org",),
        requests_per_second=2.0,                       # FRED allows 120/min
        licence_class="us-gov-public-domain",          # enforced: gov-source series only
        docs="https://fred.stlouisfed.org/docs/api/fred/",
        auth="query_param",
        auth_env="FRED_API_KEY",
        auth_param="api_key",
    ),
    Source(
        # Wikipedia: qualitative CONTEXT only (history, what the industry is),
        # never a figure of record. CC BY-SA, so it is attributed wherever shown.
        key="wikipedia",
        hosts=("en.wikipedia.org",),
        requests_per_second=1.0,
        licence_class="cc-by-sa",
        docs="https://www.mediawiki.org/wiki/API:REST_API",
        auth="none",
    ),
    Source(
        key="usitc-dataweb",
        hosts=("datawebws.usitc.gov",),
        requests_per_second=1.0,
        licence_class="us-gov-public-domain",
        docs="https://www.usitc.gov/data/dataweb_api.htm",
        auth="bearer",
        auth_env="USITC_DATAWEB_TOKEN",
    ),
)

# host -> Source, built once.
_BY_HOST: dict[str, Source] = {host: s for s in SOURCES for host in s.hosts}

# Fallback for any host not in the registry: slow, unauthenticated, unknown licence.
UNKNOWN_SOURCE = Source(
    key="unknown",
    hosts=(),
    requests_per_second=1.0,
    licence_class="unknown",
    docs="",
    auth="none",
)


def for_url(url: str) -> Source:
    """Return the Source that owns this URL's host (or UNKNOWN_SOURCE)."""
    return _BY_HOST.get(urlparse(url).netloc.lower(), UNKNOWN_SOURCE)


def api_key(source: Source) -> str:
    """Return the configured key/token for a source, or raise if it's missing.

    Same discipline as the SEC contact: keys live in the environment, never in
    the repo, and we fail loudly rather than sending an empty credential.
    """
    if not source.auth_env:
        return ""
    value = os.environ.get(source.auth_env, "").strip()
    if not value:
        raise RuntimeError(
            f"Source '{source.key}' needs {source.auth_env} set.\n"
            f"    export {source.auth_env}=\"...\"\n"
            f"Get one / see the rules at: {source.docs}"
        )
    return value
