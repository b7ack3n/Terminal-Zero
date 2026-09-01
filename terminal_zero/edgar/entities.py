"""Resolve an industry to its public filers.

The chain we care about:

    industry name  ->  SIC code(s)  ->  set of public filers (entities)

The second hop is what this module does. Given a SIC code, it asks EDGAR for
every filer classified under it and returns one `EntityRef` per company, each
carrying its own provenance (where the assertion came from, and when).

Two realities this code has to live with, both discovered by probing EDGAR:

  1. The SIC listing feed is authoritative for *membership* (which CIKs are in
     an industry) but its company *names* come back as a broken "ARRAY(0x..)"
     string. So we take CIK/SIC/state from the feed and enrich the human name
     from the ticker index (company_tickers.json), which we already cache.

  2. Name enrichment is therefore partial: a filer with no common-stock ticker
     won't be in that index, so its `name`/`ticker` stay None until a later,
     per-company fetch. We surface that gap rather than hiding it.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass

from terminal_zero.edgar.fetcher import Fetcher

# EDGAR's company-search feed, filtered by SIC. Returns Atom XML.
BROWSE_EDGAR = "https://www.sec.gov/cgi-bin/browse-edgar"
# The ticker -> CIK -> name index, used to attach human-readable names.
ENTITY_INDEX_URL = "https://www.sec.gov/files/company_tickers.json"


@dataclass(frozen=True)
class EntityRef:
    """A single filer, resolved from a SIC listing, with provenance.

    `source_url` + `retrieved_at` pin *where* the membership claim came from
    and *when* we saw it — the same vintage discipline as the fetcher, carried
    up to the entity level so a room can cite it.
    """

    cik: str                 # 10-digit zero-padded, e.g. "0000320193"
    name: str | None         # human name, enriched from the ticker index
    ticker: str | None       # common-stock ticker, if the filer has one
    sic: str                 # the SIC code EDGAR reports for this filer
    state: str | None        # business-address state code
    source: str              # "sec-edgar"
    source_url: str          # the exact feed URL this row came from
    retrieved_at: str        # when we fetched that feed (vintage)
    licence_class: str       # licensing class of the source data


def load_entity_index(fetcher: Fetcher) -> dict[str, tuple[str, str]]:
    """Return a map: 10-digit CIK -> (ticker, company name).

    Sourced from company_tickers.json. Only covers filers that have a ticker,
    which is exactly why name enrichment below is partial.
    """
    result = fetcher.get(ENTITY_INDEX_URL)
    index: dict[str, tuple[str, str]] = {}
    for row in result.json().values():
        cik10 = str(row["cik_str"]).zfill(10)
        index[cik10] = (row["ticker"], row["title"])
    return index


def _sic_page_url(sic: str, start: int, count: int) -> str:
    return (
        f"{BROWSE_EDGAR}?action=getcompany&SIC={sic}"
        f"&owner=include&count={count}&start={start}&output=atom"
    )


def filers_for_sic(
    fetcher: Fetcher,
    sic: str,
    *,
    index: dict[str, tuple[str, str]] | None = None,
    max_filers: int = 2000,
) -> list[EntityRef]:
    """Resolve every public filer under one SIC code.

    Pages through the EDGAR feed (100 at a time) until it runs out or hits
    `max_filers`. Names are enriched from the ticker index; pass a pre-loaded
    `index` to avoid re-reading it when resolving several SIC codes.
    """
    if index is None:
        index = load_entity_index(fetcher)

    results: list[EntityRef] = []
    count, start = 100, 0

    while start < max_filers:
        url = _sic_page_url(sic, start, count)
        result = fetcher.get(url)
        root = ET.fromstring(result.body)

        # `{*}` is an ElementTree namespace wildcard — the feed puts every tag
        # in the Atom namespace, and we'd rather not hard-code that URL.
        entries = root.findall("{*}entry")
        if not entries:
            break

        for entry in entries:
            cik_el = entry.find(".//{*}cik")
            if cik_el is None or not cik_el.text:
                continue
            cik = cik_el.text.strip().zfill(10)

            sic_el = entry.find(".//{*}sic")
            state_el = entry.find(".//{*}state")
            ticker, name = index.get(cik, (None, None))

            results.append(
                EntityRef(
                    cik=cik,
                    name=name,
                    ticker=ticker,
                    sic=(sic_el.text.strip() if sic_el is not None and sic_el.text else str(sic)),
                    state=(state_el.text.strip() if state_el is not None and state_el.text else None),
                    source=result.source,
                    source_url=url,
                    retrieved_at=result.retrieved_at,
                    licence_class=result.licence_class,
                )
            )

        # A short page means we've reached the end of the listing.
        if len(entries) < count:
            break
        start += count

    return results
