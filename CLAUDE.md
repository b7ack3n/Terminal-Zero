# Terminal Zero

Provenance-first research infrastructure that produces **cited industry analysis
briefs**. A user picks an industry; the system resolves it to entities/concepts/
periods, pulls the latest public data, assembles a **room** (a materialised slice
of the store), and renders a framework-structured brief. Every figure traces to a
source or a versioned calculation — never hand-typed, never invented by a model.

Audience: consultants/operators/early-career who need to get across an industry
fast, below institutional pricing.

## The non-negotiable rule

**Every number is either sourced (cited, from data) or shows its work (a versioned
derivation with stated method).** A model may write prose and choose which
calculations to run, and may produce *transparent, labelled estimates*, but it
must never emit a naked number as if it were a fact. This is the whole moat.

## Product shape (decided)

- Core UX = a **browsable tree** of pre-computed, cited reports (Capital-IQ /
  Bloomberg-terminal register) — premium and fast because reports are
  pre-materialised, NOT generated on demand. **Not a chat wrapper.**
- Chat is a **secondary** feature: a grounded assistant beside a report.
- Report **style is standardised** (one house style; per-industry only a
  controlled accent). Report **structure is a standardised module library**;
  each brief **composes** only the modules its data supports (data-gated) — no
  fabrication, honest gaps.
- Geographic scope: **US-anchored + global trade lens**; expand later via UN
  Comtrade / FAO / Eurostat, always labelled.

## Architecture

```
industry.py (registry: name -> NAICS/SIC/BEA/HS/BFS/NASS codes + honest notes)
      │
sources.py (per-source host, rate limit, auth, licence)
      │
edgar/fetcher.py  (rate-limited, on-disk cache, KEY REDACTION before caching,
      │            vintage stamped at first fetch)
   parsers  → observations → store.py (SQLite, data/store.db)
      │        (bls/qcew, bea/gdp, bea/io, census/cbp, census/trade, census/bfs,
      │         usda/nass, edgar/entities)
      ▼
room.py (saved slice + materialise)  derive.py (versioned calculations)
      ▼
brief.py (room -> editorial HTML report)   → published as an Artifact
```

- **Observation** = the atomic cited row (store.py): subject, concept, unit,
  flow/stock, period, value + provenance (source, source_url, retrieved_at/
  vintage, licence). NEVER dedupe on ingest — keep every vintage/restatement
  (identity index includes accession + geo).
- Dimensions the schema has no column for (size class, IO counterparty, trade
  partner) are encoded in the `concept` string with a label reference module.

## How to run

```bash
export TERMINAL_ZERO_CONTACT="..."   # already in ~/.zshrc
# API keys (BEA_API_KEY, CENSUS_API_KEY, NASS_API_KEY) also in ~/.zshrc — never commit them
export PYTHONPATH=.

python scripts/refresh.py semiconductors        # pull the LATEST from every mapped source
python scripts/make_brief.py 334413 "U.S. Semiconductor Manufacturing" out.html
python -m unittest discover -s tests -q          # 56 tests
```

- `refresh.py <industry>` computes the data window from today's date and pulls
  the freshest available from every source the industry maps to; idempotent.
- Secrets: read from env vars, kept out of the repo AND the cache (fetcher caches
  the key-free canonical URL and redacts keys echoed in response bodies).

## Sources wired (8)

QCEW (employment/wages), SEC EDGAR (public filers), BEA GDP-by-Industry (gross
output + quarterly SAAR), BEA Input-Output (supplier/buyer structure), Census CBP
(establishment size distribution), Census trade (monthly HS + by-country
partners), Census BFS (business formation), USDA NASS (ag production value).

## Status

- Two industries proven end-to-end: **semiconductors** (NAICS 334413) and **tree
  nuts** (111335) — same engine + house style, industry-specific composition
  (tree nuts: NASS production sizing, no public players, no CBP concentration).
- All five Porter forces resolved (4 data-backed, substitutes honestly
  qualitative). Trade is global-by-country.
- Artifacts: semiconductors + tree-nut briefs published on claude.ai.

## Next / open

1. **Scale the registry**: load official crosswalks (NAICS↔SIC↔BEA↔HS) so most
   industry mappings are derived, not hand-curated; build a resolver
   (search text -> canonical industry, with disambiguation). Backbone for the
   browsable tree + search box.
2. **AI narrative layer** (needs `ANTHROPIC_API_KEY`): model reads a room, calls
   query/derivation tools for every figure, writes the framework prose — never
   emitting a number it can't cite. Query/derivation tool layer can be built
   first (no key) to prove the "numbers only from tools" guarantee.
3. Rank key players by revenue (EDGAR companyfacts); module-registry refactor for
   declarative show/hide; international sources (Comtrade/FAO).

## Conventions

- Python 3, standard library first. Parsers split pure `parse_*` (fixture-tested)
  from network `*_observations`. New parsers must tolerate non-JSON/error bodies
  (return []). New source = a parser + a `sources.py` entry + an `industry.py`
  mapping field.
- Commit per brick; end messages with the Co-Authored-By trailer.
