"""Render a room as a framework-structured industry analysis brief (HTML).

"A report is one rendering of a room." The brief is organised the way an
analyst would structure it — industry sizing, key players, competitive forces
(Porter's Five Forces), market constraints — and every figure is pulled from
the store, never hand-typed.

Sections split into two kinds:
  * DATA-BACKED (Industry sizing from QCEW, Key players from EDGAR): fully
    cited, computed from observations / resolved entities.
  * SCAFFOLD (Five Forces, Market constraints): the framework is laid out and
    each force names the data that will drive it, marked clearly as pending —
    we show the structure without fabricating analysis the data can't yet
    support. The AI narrative and the extra sources fill these in later.
"""

from __future__ import annotations

import sqlite3

from terminal_zero import derive, geo, room

# ---- data assembly (all numbers come from the store) ---------------------


def _us_series(conn, subject_id):
    rows = conn.execute(
        """
        SELECT fiscal_year AS year,
               MAX(CASE WHEN concept='annual_avg_estabs'  THEN value END) AS estabs,
               MAX(CASE WHEN concept='annual_avg_emplvl'  THEN value END) AS emp,
               MAX(CASE WHEN concept='total_annual_wages' THEN value END) AS wages
        FROM observations WHERE subject_id=? AND geo='US'
        GROUP BY fiscal_year ORDER BY fiscal_year
        """,
        (subject_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def _top_states(conn, subject_id, year, limit=8):
    rows = conn.execute(
        """
        SELECT geo, value FROM observations
        WHERE subject_id=? AND fiscal_year=? AND concept='annual_avg_emplvl'
          AND geo LIKE 'STATE:%'
        ORDER BY value DESC LIMIT ?
        """,
        (subject_id, year, limit),
    ).fetchall()
    return [{"label": geo.label(r["geo"]), "value": r["value"]} for r in rows]


def _provenance(conn, subject_id):
    row = conn.execute(
        "SELECT MIN(retrieved_at) AS first, MAX(retrieved_at) AS last, "
        "source, licence_class FROM observations WHERE subject_id=?",
        (subject_id,),
    ).fetchone()
    return dict(row) if row else {}


# ---- formatting ----------------------------------------------------------

def _int(v): return f"{v:,.0f}"
def _usd_b(v): return f"${v / 1e9:,.1f}B"


def _pct(first, last):
    if not first:
        return "—"
    return f"{(last - first) / first * 100:+.1f}%"


# ---- svg marks (computed from data) --------------------------------------


def _sparkline(values):
    w, h, pad = 220, 56, 6
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1
    n = len(values)
    xs = [pad + (w - 2 * pad) * i / (n - 1) for i in range(n)]
    ys = [h - pad - (h - 2 * pad) * (v - lo) / span for v in values]
    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys))
    area = f"{xs[0]:.1f},{h - pad} " + line + f" {xs[-1]:.1f},{h - pad}"
    return (
        f'<svg class="spark" viewBox="0 0 {w} {h}" preserveAspectRatio="none" '
        f'role="img" aria-hidden="true"><polygon class="spark-area" points="{area}"/>'
        f'<polyline class="spark-line" points="{line}"/></svg>'
    )


def _index_chart(years, series_map):
    """Multi-series line chart, each series indexed to its first year = 100.

    One shared scale (indexing solves the different-magnitude problem without a
    forbidden dual axis). Series are distinguished by ink value + dash + a direct
    end-label, so identity never rests on colour alone. Emphasis order matters:
    the first series gets the accent.
    """
    w, h = 660, 300
    ml, mr, mt, mb = 40, 104, 18, 32
    pw, ph = w - ml - mr, h - mt - mb
    indexed = {k: derive.apply("index_to_base", v, v[0]) for k, v in series_map.items()}
    allv = [x for vs in indexed.values() for x in vs]
    lo, hi = min(allv + [100]), max(allv)
    pad = (hi - lo) * 0.12 or 8
    ymin, ymax = lo - pad, hi + pad
    n = len(years)

    def X(i): return ml + pw * i / (n - 1)
    def Y(v): return mt + ph * (1 - (v - ymin) / (ymax - ymin))

    parts = [f'<svg class="idx" viewBox="0 0 {w} {h}" role="img">']
    # baseline at index 100
    y100 = Y(100)
    parts.append(f'<line class="idx-base" x1="{ml}" y1="{y100:.1f}" x2="{ml + pw}" y2="{y100:.1f}"/>')
    parts.append(f'<text class="idx-axis" x="{ml - 8}" y="{y100:.1f}" text-anchor="end" dominant-baseline="central">100</text>')
    # x-axis year labels
    for i, yr in enumerate(years):
        parts.append(f'<text class="idx-axis" x="{X(i):.1f}" y="{h - 8}" text-anchor="middle">{yr}</text>')
    # one line + end label per series
    for cls, (name, vals) in enumerate(indexed.items()):
        pts = " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(vals))
        parts.append(f'<polyline class="idx-line idx-{cls}" points="{pts}"/>')
        ex, ey = X(n - 1), Y(vals[-1])
        parts.append(f'<circle class="idx-dot idx-{cls}" cx="{ex:.1f}" cy="{ey:.1f}" r="3"/>')
        parts.append(f'<text class="idx-end idx-{cls}t" x="{ex + 8:.1f}" y="{ey:.1f}" dominant-baseline="central">{name} {vals[-1]:.0f}</text>')
    parts.append("</svg>")
    return "".join(parts)


def _bars(rows):
    w, barh, gap, labelw, valuew = 660, 28, 12, 150, 96
    trackx = labelw + 10
    trackw = w - trackx - valuew
    maxv = max(r["value"] for r in rows) or 1
    svgh = len(rows) * (barh + gap) - gap
    parts = [f'<svg class="bars" viewBox="0 0 {w} {svgh}" role="img">']
    for i, r in enumerate(rows):
        y = i * (barh + gap)
        bw = trackw * r["value"] / maxv
        mid = y + barh / 2
        parts.append(f'<text class="bar-label" x="{labelw}" y="{mid}" text-anchor="end" dominant-baseline="central">{r["label"]}</text>')
        parts.append(f'<rect class="bar-track" x="{trackx}" y="{y}" width="{trackw}" height="{barh}" rx="4"/>')
        parts.append(f'<rect class="bar" x="{trackx}" y="{y}" width="{bw:.1f}" height="{barh}" rx="4"><title>{r["label"]}: {_int(r["value"])} employees</title></rect>')
        parts.append(f'<text class="bar-value" x="{trackx + bw + 8:.1f}" y="{mid}" dominant-baseline="central">{_int(r["value"])}</text>')
    parts.append("</svg>")
    return "".join(parts)


# ---- section builders ----------------------------------------------------


def _section_head(num, title):
    return f'<div class="sect-head"><span class="sect-num">{num}</span><h2>{title}</h2></div>'


def _market_size_banner(conn, bea_industry, bea_note):
    """Market-size banner from BEA gross output, or an honest pending state."""
    rows = []
    if bea_industry:
        rows = conn.execute(
            "SELECT fiscal_year, value FROM observations WHERE subject_id=? "
            "AND concept='gross_output' AND geo='US' ORDER BY fiscal_year",
            (f"BEA:{bea_industry}",),
        ).fetchall()
    if not rows:
        return (
            '<div class="marketsize">'
            '<span class="ms-k">Market size · gross output</span>'
            '<span class="ms-v">Pending</span>'
            '<span class="pending">Add a BEA key to source this (BEA gross output by industry)</span>'
            "</div>"
        )
    first, last = rows[0], rows[-1]
    y0, y1 = first["fiscal_year"], last["fiscal_year"]
    cagr = derive.apply("cagr", first["value"], last["value"], max(y1 - y0, 1))
    return (
        '<div class="marketsize done">'
        '<div class="ms-main">'
        f'<span class="ms-k">Market size · gross output · {y1}</span>'
        f'<span class="ms-big">${last["value"] / 1e9:,.0f}B</span>'
        f'<span class="ms-chg">{cagr:+.1%}/yr since {y0}</span>'
        "</div>"
        f'<p class="ms-note">{bea_note} Source: BEA GDP-by-Industry (gross output).</p>'
        "</div>"
    )


def _key_players_section(num, key_players):
    body = ""
    if not key_players or not key_players.get("players"):
        body = (
            '<p class="empty">No public companies are classified in this industry '
            "under EDGAR — a sign the industry is largely private. Coverage of "
            "private players comes from the sizing sources, not company filings.</p>"
        )
        cite = ""
    else:
        players = sorted(key_players["players"], key=lambda p: (p["name"] or ""))
        shown = players[:15]
        rows = "".join(
            f'<tr><td class="tk">{p["ticker"] or "—"}</td><td>{p["name"]}</td>'
            f'<td class="ck">CIK{p["cik"]}</td></tr>'
            for p in shown
        )
        body = (
            '<table class="players"><thead><tr><th>Ticker</th><th>Company</th>'
            '<th>Filer</th></tr></thead><tbody>' + rows + "</tbody></table>"
        )
        total = key_players["total_named"]
        more = f" Showing 15 of {total} public filers with identifiable tickers." if total > 15 else ""
        body += (
            f'<p class="cap">Public companies classified in SIC {key_players["sic"]} '
            f"(EDGAR).{more} Ranking by revenue is a pending enrichment.</p>"
        )
        cite = key_players
    return f'<section>{_section_head(num, "Key players")}{body}</section>', cite


FORCES = [
    ("Competitive rivalry",
     "Number of players and market concentration — establishment counts (QCEW/CBP) and size distribution (CBP)."),
    ("Threat of new entrants",
     "Capital intensity and establishment birth/death rates (Census Business Formation Statistics)."),
    ("Threat of substitutes",
     "Output and pricing of adjacent industries (BEA industry accounts, trade)."),
    ("Supplier power",
     "Upstream input costs and concentration (BEA input-output, trade in components)."),
    ("Buyer power",
     "Downstream demand concentration and export dependence (Census / USITC trade)."),
]


def _forces_section(num):
    cards = "".join(
        f'<div class="force"><span class="force-k">{name}</span>'
        f"<p>{driver}</p><span class=\"pending\">Awaiting data + AI analysis</span></div>"
        for name, driver in FORCES
    )
    return (
        f'<section>{_section_head(num, "Competitive forces")}'
        '<p class="sect-lede">Porter\'s Five Forces. Each force names the data that '
        "will drive it; the analysis is written by the model over that data, with "
        'every figure cited.</p>'
        f'<div class="forces">{cards}</div></section>'
    )


def _constraints_section(num):
    items = [
        ("Trade exposure", "Import penetration and export dependence (Census / USITC trade, by HS code)."),
        ("Input sensitivity", "Cost and availability of key inputs (BEA input-output)."),
        ("Labor availability", "Employment levels, wages, and geographic concentration (QCEW — partially available)."),
    ]
    rows = "".join(
        f'<div class="force"><span class="force-k">{k}</span><p>{v}</p>'
        '<span class="pending">Awaiting data + AI analysis</span></div>'
        for k, v in items
    )
    return f'<section>{_section_head(num, "Market constraints")}<div class="forces">{rows}</div></section>'


# ---- styles --------------------------------------------------------------

STYLE = """
<style>
:root{
  --bg:#F5F7FA; --surface:#FFFFFF; --ink:#14181F; --muted:#5B6673;
  --faint:#8A94A2; --line:#E3E8EF; --track:#EDF1F6;
  --accent:#0E7C86; --accent-ink:#0B5F67; --accent-fill:rgba(14,124,134,.14);
  --pending:#B06A17; --pending-bg:rgba(176,106,23,.10);
}
@media (prefers-color-scheme:dark){
  :root:not([data-theme="light"]){
    --bg:#0C0F14; --surface:#12161D; --ink:#E7ECF3; --muted:#9BA6B4;
    --faint:#6B7686; --line:#232A34; --track:#1B2129;
    --accent:#3FB6C4; --accent-ink:#7FD4DE; --accent-fill:rgba(63,182,196,.16);
    --pending:#E0A85B; --pending-bg:rgba(224,168,91,.12);
  }
}
:root[data-theme="dark"]{
  --bg:#0C0F14; --surface:#12161D; --ink:#E7ECF3; --muted:#9BA6B4;
  --faint:#6B7686; --line:#232A34; --track:#1B2129;
  --accent:#3FB6C4; --accent-ink:#7FD4DE; --accent-fill:rgba(63,182,196,.16);
  --pending:#E0A85B; --pending-bg:rgba(224,168,91,.12);
}
*{box-sizing:border-box}
body{background:var(--bg);color:var(--ink);
  font-family:"IBM Plex Sans",system-ui,sans-serif;line-height:1.55;
  -webkit-font-smoothing:antialiased}
.wrap{max-width:900px;margin:0 auto;padding:56px 28px 80px}
.eyebrow{font-family:"IBM Plex Mono",monospace;font-size:.72rem;letter-spacing:.22em;
  text-transform:uppercase;color:var(--accent-ink);margin:0 0 14px}
h1{font-family:"IBM Plex Serif",Georgia,serif;font-weight:600;
  font-size:clamp(2rem,4.2vw,2.9rem);line-height:1.08;letter-spacing:-.01em;
  text-wrap:balance;margin:0 0 12px}
.dek{color:var(--muted);font-size:1.05rem;max-width:60ch;margin:0}
.masthead{border-bottom:1px solid var(--line);padding-bottom:26px}
.coverage{font-family:"IBM Plex Mono",monospace;font-size:.8rem;color:var(--faint);
  margin-top:18px;display:flex;flex-wrap:wrap;gap:6px 22px}
.coverage b{color:var(--muted);font-weight:500}
section{margin-top:52px}
.sect-head{display:flex;align-items:baseline;gap:14px;margin:0 0 8px;
  padding-bottom:14px;border-bottom:1px solid var(--line)}
.sect-num{font-family:"IBM Plex Mono",monospace;font-size:.9rem;color:var(--accent-ink);
  font-weight:500}
.sect-head h2{font-family:"IBM Plex Serif",Georgia,serif;font-weight:600;
  font-size:1.5rem;margin:0;letter-spacing:-.01em}
.sect-lede{color:var(--muted);max-width:64ch;margin:16px 0 22px}
.label{font-family:"IBM Plex Mono",monospace;font-size:.72rem;letter-spacing:.14em;
  text-transform:uppercase;color:var(--faint);margin:22px 0 16px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(172px,1fr));gap:16px}
@media(max-width:680px){.tiles{grid-template-columns:repeat(auto-fit,minmax(150px,1fr))}}
.marketsize{display:flex;align-items:baseline;gap:14px 20px;flex-wrap:wrap;
  background:var(--surface);border:1px solid var(--line);border-left:3px solid var(--accent);
  border-radius:10px;padding:18px 22px;margin-bottom:20px}
.marketsize .ms-k{font-family:"IBM Plex Mono",monospace;font-size:.72rem;letter-spacing:.12em;
  text-transform:uppercase;color:var(--muted)}
.marketsize .ms-v{font-family:"IBM Plex Serif",Georgia,serif;font-size:1.3rem;font-weight:600;
  color:var(--faint)}
.marketsize.done{flex-direction:column;align-items:flex-start;gap:8px}
.ms-main{display:flex;align-items:baseline;gap:14px;flex-wrap:wrap}
.ms-big{font-family:"IBM Plex Serif",Georgia,serif;font-size:2rem;font-weight:600;
  color:var(--ink);letter-spacing:-.01em;font-variant-numeric:tabular-nums}
.ms-chg{font-family:"IBM Plex Mono",monospace;font-size:.85rem;color:var(--accent-ink);
  font-variant-numeric:tabular-nums}
.ms-note{margin:0;color:var(--muted);font-size:.82rem;max-width:72ch}
.idx{display:block;width:100%;height:auto;margin-top:4px}
.idx-base{stroke:var(--line);stroke-width:1;stroke-dasharray:2 3}
.idx-axis{font-family:"IBM Plex Mono",monospace;font-size:11px;fill:var(--faint)}
.idx-line{fill:none;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}
.idx-0{stroke:var(--accent)} .idx-1{stroke:var(--muted)}
.idx-2{stroke:var(--faint);stroke-dasharray:5 3}
.idx-dot.idx-0{fill:var(--accent)} .idx-dot.idx-1{fill:var(--muted)} .idx-dot.idx-2{fill:var(--faint)}
.idx-end{font-family:"IBM Plex Mono",monospace;font-size:11.5px;font-variant-numeric:tabular-nums}
.idx-0t{fill:var(--accent-ink)} .idx-1t{fill:var(--muted)} .idx-2t{fill:var(--faint)}
.tile{background:var(--surface);border:1px solid var(--line);border-radius:10px;
  padding:20px 20px 14px;display:flex;flex-direction:column;gap:2px}
.tile .k{font-family:"IBM Plex Mono",monospace;font-size:.72rem;letter-spacing:.12em;
  text-transform:uppercase;color:var(--muted)}
.tile .v{font-family:"IBM Plex Mono",monospace;font-size:1.7rem;font-weight:600;
  font-variant-numeric:tabular-nums;letter-spacing:-.01em;margin-top:4px}
.tile .chg{font-family:"IBM Plex Mono",monospace;font-size:.8rem;color:var(--accent-ink);
  font-variant-numeric:tabular-nums}
.spark{display:block;width:100%;height:58px;margin-top:14px}
.spark-area{fill:var(--accent-fill)}
.spark-line{fill:none;stroke:var(--accent);stroke-width:2;stroke-linecap:round;
  stroke-linejoin:round;vector-effect:non-scaling-stroke}
.chartcard{background:var(--surface);border:1px solid var(--line);border-radius:10px;
  padding:24px}
.bars{width:100%;height:auto}
.bar-track{fill:var(--track)}
.bar{fill:var(--accent)}
.bar-label{font-family:"IBM Plex Sans",sans-serif;font-size:13px;fill:var(--ink)}
.bar-value{font-family:"IBM Plex Mono",monospace;font-size:12.5px;fill:var(--muted);
  font-variant-numeric:tabular-nums}
.cap{font-family:"IBM Plex Mono",monospace;font-size:.74rem;color:var(--faint);
  margin:16px 0 0}
.players{width:100%;border-collapse:collapse;font-size:.92rem}
.players th{text-align:left;font-family:"IBM Plex Mono",monospace;font-size:.7rem;
  letter-spacing:.1em;text-transform:uppercase;color:var(--faint);font-weight:500;
  padding:0 0 10px;border-bottom:1px solid var(--line)}
.players td{padding:11px 0;border-bottom:1px solid var(--line)}
.players .tk{font-family:"IBM Plex Mono",monospace;color:var(--accent-ink);font-weight:500}
.players .ck{font-family:"IBM Plex Mono",monospace;color:var(--faint);font-size:.78rem}
.empty{color:var(--muted);max-width:60ch}
.forces{display:grid;grid-template-columns:repeat(2,1fr);gap:14px;margin-top:22px}
@media(max-width:680px){.forces{grid-template-columns:1fr}}
.force{background:var(--surface);border:1px solid var(--line);border-radius:10px;
  padding:18px 18px 16px;display:flex;flex-direction:column;gap:8px}
.force-k{font-family:"IBM Plex Sans",sans-serif;font-weight:600;font-size:1rem}
.force p{margin:0;color:var(--muted);font-size:.88rem;flex:1}
.pending{align-self:flex-start;font-family:"IBM Plex Mono",monospace;font-size:.66rem;
  letter-spacing:.06em;text-transform:uppercase;color:var(--pending);
  background:var(--pending-bg);padding:4px 8px;border-radius:5px}
.prov{background:var(--surface);border:1px solid var(--line);border-radius:10px;
  padding:22px 24px}
.prov h3{font-family:"IBM Plex Mono",monospace;font-size:.72rem;letter-spacing:.14em;
  text-transform:uppercase;color:var(--faint);margin:0 0 14px;font-weight:500}
.prov dl{display:grid;grid-template-columns:auto 1fr;gap:8px 18px;margin:0}
.prov dt{font-family:"IBM Plex Mono",monospace;color:var(--faint);font-size:.78rem}
.prov dd{margin:0;font-family:"IBM Plex Mono",monospace;font-size:.78rem;color:var(--ink);
  word-break:break-all}
.foot{margin-top:44px;padding-top:20px;border-top:1px solid var(--line);
  font-family:"IBM Plex Mono",monospace;font-size:.74rem;color:var(--faint);
  display:flex;justify-content:space-between;flex-wrap:wrap;gap:8px}
</style>
"""


def render(conn: sqlite3.Connection, naics: str, title: str, key_players=None,
           bea_industry=None, bea_note="") -> str:
    subject = f"NAICS:{naics}"
    series = _us_series(conn, subject)
    if not series:
        raise ValueError(f"no observations for {subject} — load data first")
    first, last = series[0], series[-1]
    y0, y1 = first["year"], last["year"]
    top = _top_states(conn, subject, y1)
    prov = _provenance(conn, subject)
    cov = room.summary(conn, room.RoomDefinition(name="_", subject_ids=[subject]))

    # Series for each measure, plus two derived series (all via the registry).
    estabs = [s["estabs"] for s in series]
    emp = [s["emp"] for s in series]
    wages = [s["wages"] for s in series]
    pay = [derive.apply("avg_annual_pay", s["wages"], s["emp"]) for s in series]
    size = [derive.apply("avg_establishment_size", s["emp"], s["estabs"]) for s in series]
    n_years = max(y1 - y0, 1)

    def cagr_label(vals):
        return f"{derive.apply('cagr', vals[0], vals[-1], n_years):+.1%}/yr"

    tiles = [
        ("Establishments", _int(estabs[-1]), cagr_label(estabs), _sparkline(estabs)),
        ("Employment", _int(emp[-1]), cagr_label(emp), _sparkline(emp)),
        ("Total annual wages", _usd_b(wages[-1]), cagr_label(wages), _sparkline(wages)),
        ("Avg pay / worker", f"${_int(pay[-1])}", cagr_label(pay), _sparkline(pay)),
        ("Workers / establishment", f"{size[-1]:.0f}", cagr_label(size), _sparkline(size)),
    ]
    tiles_html = "".join(
        f'<div class="tile"><span class="k">{k}</span><span class="v">{v}</span>'
        f'<span class="chg">{chg} · since {y0}</span>{spark}</div>'
        for k, v, chg, spark in tiles
    )
    index_chart = _index_chart(
        [s["year"] for s in series],
        {"Wages": wages, "Establishments": estabs, "Employment": emp},
    )

    players_section, players_cite = _key_players_section("II", key_players)
    has_bea = bool(bea_industry and conn.execute(
        "SELECT 1 FROM observations WHERE subject_id=? AND concept='gross_output' LIMIT 1",
        (f"BEA:{bea_industry}",)).fetchone())
    retrieved = (prov.get("last") or "")[:10]

    # Provenance rows — list every source the brief actually drew on.
    prov_rows = [
        ("Sizing source", f"{prov.get('source', '')} · Quarterly Census of Employment and Wages"),
        ("Sizing endpoint", f"https://data.bls.gov/cew/data/api/&lt;year&gt;/a/industry/{naics}.csv"),
    ]
    if players_cite:
        prov_rows.append(("Key players source", "sec-edgar · company classification by SIC"))
        prov_rows.append(("Key players endpoint", f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&SIC={players_cite['sic']}"))
    if has_bea:
        prov_rows.append(("Market size source", "bea · GDP-by-Industry, gross output (TableID 15)"))
        prov_rows.append(("Market size endpoint", "https://apps.bea.gov/api/data/?method=GetData&datasetname=GDPbyIndustry&TableID=15"))
    prov_rows += [
        ("Licence", prov.get("licence_class", "")),
        ("Retrieved", retrieved),
        ("Scope", "Private ownership; U.S. + states; suppressed cells omitted"),
    ]
    prov_html = "".join(f"<dt>{k}</dt><dd>{v}</dd>" for k, v in prov_rows)

    return f"""<title>{title}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Serif:wght@500;600&display=swap">
{STYLE}
<div class="wrap">
  <header class="masthead">
    <p class="eyebrow">Terminal Zero · Industry Analysis</p>
    <h1>{title}</h1>
    <p class="dek">A framework-structured brief. The analysis is organised the way
      an analyst would build it — sizing, players, forces, constraints — and every
      figure traces to a cited source in the store.</p>
    <div class="coverage">
      <span><b>NAICS</b> {naics}</span>
      <span><b>Period</b> {y0}–{y1}</span>
      <span><b>Geographies</b> {cov['geos']}</span>
      <span><b>Observations</b> {cov['observations']}</span>
      <span><b>Sources</b> {', '.join(cov['sources'])}{', sec-edgar' if players_cite else ''}{', bea' if has_bea else ''}</span>
    </div>
  </header>

  <section>
    {_section_head("I", "Industry sizing")}
    {_market_size_banner(conn, bea_industry, bea_note)}
    <p class="label">Key figures · {y1}</p>
    <div class="tiles">{tiles_html}</div>
    <p class="label">Indexed growth · {y0} = 100</p>
    <div class="chartcard">{index_chart}
      <p class="cap">Each series indexed to its {y0} level. Wages outpacing
        employment means pay per worker is rising. Source: BLS QCEW; growth via
        derivation cagr/index_to_base v1.0.0.</p></div>
    <p class="label">Geographic concentration · employment, {y1}</p>
    <div class="chartcard">{_bars(top)}
      <p class="cap">Top {len(top)} states by average annual employment, private
        ownership. Source: BLS QCEW.</p></div>
  </section>

  {players_section}

  {_forces_section("III")}

  {_constraints_section("IV")}

  <section>
    {_section_head("V", "Provenance")}
    <div class="prov"><h3>How to trace these numbers</h3><dl>{prov_html}</dl></div>
  </section>

  <div class="foot">
    <span>Generated from the observation store — no figure hand-entered.</span>
    <span>Terminal Zero</span>
  </div>
</div>
"""
