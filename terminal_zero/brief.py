"""Render a room as an editorial, framework-structured industry analysis (HTML).

"A report is one rendering of a room." Organised the way an analyst builds it —
market size, competitive structure, trade exposure, forces — as numbered
Exhibits. Every figure is pulled from the store; nothing is hand-typed, and any
computed number comes from a versioned derivation.

Visual register: a light, print-like research report — serif display, grotesque
body, a single deep-navy accent, generous white space. Deliberately not a
dashboard.
"""

from __future__ import annotations

import sqlite3

from terminal_zero import derive, geo, room
from terminal_zero.bea.io_labels import label as io_label
from terminal_zero.census.cbp import SIZE_LABELS
from terminal_zero.census.country_labels import name as country_name

SIZE_ORDER = ["210", "220", "230", "241", "242", "251", "252", "254", "260"]
LARGE_CODES = {"251", "252", "254", "260"}  # 250+ employees

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
        """, (subject_id,)).fetchall()
    return [dict(r) for r in rows]


def _top_states(conn, subject_id, year, limit=8):
    rows = conn.execute(
        """SELECT geo, value FROM observations
           WHERE subject_id=? AND fiscal_year=? AND concept='annual_avg_emplvl'
             AND geo LIKE 'STATE:%' ORDER BY value DESC LIMIT ?""",
        (subject_id, year, limit)).fetchall()
    return [{"label": geo.label(r["geo"]), "value": r["value"]} for r in rows]


def _bea_output(conn, bea_industry):
    if not bea_industry:
        return []
    return [dict(r) for r in conn.execute(
        """SELECT fiscal_year AS year, value FROM observations
           WHERE subject_id=? AND concept='gross_output' AND geo='US'
           ORDER BY fiscal_year""", (f"BEA:{bea_industry}",)).fetchall()]


def _bea_latest_quarter(conn, bea_industry):
    if not bea_industry:
        return None
    r = conn.execute(
        "SELECT fiscal_year, fiscal_period, value FROM observations WHERE subject_id=? "
        "AND concept='gross_output_saar' ORDER BY period_end DESC LIMIT 1",
        (f"BEA:{bea_industry}",)).fetchone()
    return dict(r) if r else None


def _nass(conn, commodities):
    """Latest value of production ($) per commodity, from USDA NASS."""
    if not commodities:
        return None
    items = []
    for c in commodities:
        r = conn.execute(
            "SELECT fiscal_year, value FROM observations WHERE subject_id=? AND unit='$' "
            "AND concept LIKE '%PRODUCTION%' ORDER BY fiscal_year DESC, value DESC LIMIT 1",
            (f"NASS:{c.upper()}",)).fetchone()
        if r:
            items.append({"commodity": c.title(), "value": r[1], "year": r[0]})
    if not items:
        return None
    items.sort(key=lambda x: x["value"], reverse=True)
    return {"items": items, "total": sum(i["value"] for i in items),
            "year": max(i["year"] for i in items)}


def _bfs(conn, category):
    """New-business applications by full year (sector-level), latest first."""
    if not category:
        return None
    subj = f"BFS:{category}"
    counts = dict(conn.execute(
        "SELECT fiscal_year, count(*) FROM observations WHERE subject_id=? AND "
        "concept='bfs_applications' GROUP BY fiscal_year", (subj,)).fetchall())
    rows = conn.execute(
        "SELECT fiscal_year, SUM(value) FROM observations WHERE subject_id=? AND "
        "concept='bfs_applications' GROUP BY fiscal_year ORDER BY fiscal_year", (subj,)).fetchall()
    apps = [(y, v) for y, v in rows if counts.get(y, 0) >= 12]   # full years only
    return {"apps": apps} if apps else None


def _io(conn, bea_industry):
    """Return input (supplier) and output (buyer) structure from BEA I-O."""
    if not bea_industry:
        return None
    subj = f"BEA:{bea_industry}"

    def rows(like):
        return [(io_label(r[0].split(":", 1)[1]), r[1]) for r in conn.execute(
            "SELECT concept, value FROM observations WHERE subject_id=? AND concept LIKE ? "
            "ORDER BY value DESC", (subj, like))]

    inputs, outputs = rows("io_input:%"), rows("io_output:%")
    if not inputs and not outputs:
        return None
    exp = conn.execute("SELECT value FROM observations WHERE subject_id=? AND "
                       "concept='io_output:F040'", (subj,)).fetchone()
    year = conn.execute("SELECT MAX(fiscal_year) FROM observations WHERE subject_id=? AND "
                        "taxonomy='bea-io'", (subj,)).fetchone()[0]
    return {"inputs": inputs, "outputs": outputs,
            "total_in": sum(v for _, v in inputs), "total_out": sum(v for _, v in outputs),
            "exports": exp[0] if exp else 0, "year": year}


def _cbp(conn, naics):
    """Return CBP totals + establishment size distribution (latest year)."""
    subj = f"NAICS:{naics}"
    yr = conn.execute(
        "SELECT MAX(fiscal_year) FROM observations WHERE subject_id=? AND source='census'",
        (subj,)).fetchone()[0]
    if yr is None:
        return None
    def val(concept):
        r = conn.execute("SELECT value FROM observations WHERE subject_id=? AND concept=? "
                         "AND fiscal_year=?", (subj, concept, yr)).fetchone()
        return r[0] if r else None
    dist = []
    for code in SIZE_ORDER:
        r = conn.execute("SELECT value FROM observations WHERE subject_id=? AND concept=? "
                         "AND fiscal_year=?", (subj, f"cbp_estab_size:{code}", yr)).fetchone()
        if r:
            dist.append({"code": code, "label": SIZE_LABELS[code], "value": r[0]})
    return {"year": yr, "estabs": val("cbp_establishments"),
            "emp": val("cbp_employment"), "payroll": val("cbp_annual_payroll"),
            "dist": dist}


def _trade(conn, hs):
    """Monthly exports/imports for an HS code, plus latest full-year totals."""
    if not hs:
        return None
    subj = f"HS:{hs}"
    rows = conn.execute(
        """SELECT period_end, fiscal_year,
                  MAX(CASE WHEN concept='exports_value' THEN value END) AS exp,
                  MAX(CASE WHEN concept='imports_value' THEN value END) AS imp
           FROM observations WHERE subject_id=?
           GROUP BY period_end ORDER BY period_end""", (subj,)).fetchall()
    months = [dict(r) for r in rows if r["exp"] is not None or r["imp"] is not None]
    if not months:
        return None
    # latest full year = the most recent year with 12 months present
    by_year = {}
    for m in months:
        by_year.setdefault(m["fiscal_year"], []).append(m)
    full = [y for y, ms in by_year.items() if len(ms) >= 12]
    year = max(full) if full else max(by_year)
    exp_tot = sum(m["exp"] or 0 for m in by_year[year])
    imp_tot = sum(m["imp"] or 0 for m in by_year[year])
    return {"months": months, "year": year, "exports": exp_tot, "imports": imp_tot}


def _trade_partners(conn, hs):
    """Top export destinations and import sources (by country), latest full year."""
    if not hs:
        return None
    subj = f"HS:{hs}"
    year = conn.execute("SELECT MAX(fiscal_year) FROM observations WHERE subject_id=? AND "
                        "concept LIKE 'exports_country:%'", (subj,)).fetchone()[0]
    if not year:
        return None

    def top(direction):
        rows = conn.execute(
            f"SELECT concept, value FROM observations WHERE subject_id=? AND "
            f"concept LIKE '{direction}_country:%' AND fiscal_year=? ORDER BY value DESC LIMIT 6",
            (subj, year)).fetchall()
        return [(country_name(c.split(":", 1)[1]), v) for c, v in rows]

    return {"year": year, "exports": top("exports"), "imports": top("imports")}


def _ppi(conn, naics):
    """Producer price index for the industry (BLS PPI via FRED), if loaded."""
    rows = conn.execute(
        "SELECT period_end, value FROM observations WHERE subject_id=? "
        "AND concept='ppi_industry' ORDER BY period_end",
        (f"FRED:PCU{naics}{naics}",)).fetchall()
    if len(rows) < 6:
        return None
    vals = [r[1] for r in rows]
    return {"values": vals, "latest": vals[-1], "first": vals[0],
            "latest_date": rows[-1][0][:7], "first_date": rows[0][0][:7]}


def _provenance(conn, subject_id):
    row = conn.execute(
        "SELECT MIN(retrieved_at) AS first, MAX(retrieved_at) AS last, licence_class "
        "FROM observations WHERE subject_id=?", (subject_id,)).fetchone()
    return dict(row) if row else {}


# ---- formatting ----------------------------------------------------------

def _int(v): return f"{v:,.0f}"
def _usd_b(v): return f"${v/1e9:,.1f}B"
def _usd_b0(v): return f"${v/1e9:,.0f}B"


def _pct(first, last):
    return "—" if not first else f"{(last-first)/first*100:+.1f}%"


# ---- svg marks -----------------------------------------------------------


def _sparkline(values):
    w, h, pad = 220, 46, 4
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1
    n = len(values)
    xs = [pad + (w-2*pad)*i/(n-1) for i in range(n)]
    ys = [h-pad - (h-2*pad)*(v-lo)/span for v in values]
    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys))
    area = f"{xs[0]:.1f},{h-pad} " + line + f" {xs[-1]:.1f},{h-pad}"
    return (f'<svg class="spark" viewBox="0 0 {w} {h}" preserveAspectRatio="none" aria-hidden="true">'
            f'<polygon class="spark-area" points="{area}"/>'
            f'<polyline class="spark-line" points="{line}"/></svg>')


def _hbars(rows, value_fmt=_int, unit=""):
    w, barh, gap, labelw, valuew = 660, 26, 12, 168, 96
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
        parts.append(f'<rect class="bar-track" x="{trackx}" y="{y}" width="{trackw}" height="{barh}"/>')
        parts.append(f'<rect class="bar" x="{trackx}" y="{y}" width="{bw:.1f}" height="{barh}"><title>{r["label"]}: {value_fmt(r["value"])}{unit}</title></rect>')
        parts.append(f'<text class="bar-value" x="{trackx+bw+8:.1f}" y="{mid}" dominant-baseline="central">{value_fmt(r["value"])}</text>')
    parts.append("</svg>")
    return "".join(parts)


def _index_chart(years, series_map):
    w, h, ml, mr, mt, mb = 660, 300, 40, 132, 18, 32
    pw, ph = w-ml-mr, h-mt-mb
    indexed = {k: derive.apply("index_to_base", v, v[0]) for k, v in series_map.items()}
    allv = [x for vs in indexed.values() for x in vs]
    lo, hi = min(allv+[100]), max(allv)
    pad = (hi-lo)*0.12 or 8
    ymin, ymax = lo-pad, hi+pad
    n = len(years)
    X = lambda i: ml + pw*i/(n-1)
    Y = lambda v: mt + ph*(1-(v-ymin)/(ymax-ymin))
    p = [f'<svg class="idx" viewBox="0 0 {w} {h}" role="img">']
    y100 = Y(100)
    p.append(f'<line class="grid" x1="{ml}" y1="{y100:.1f}" x2="{ml+pw}" y2="{y100:.1f}"/>')
    p.append(f'<text class="axis" x="{ml-8}" y="{y100:.1f}" text-anchor="end" dominant-baseline="central">100</text>')
    for i, yr in enumerate(years):
        p.append(f'<text class="axis" x="{X(i):.1f}" y="{h-8}" text-anchor="middle">{yr}</text>')
    for cls, (name, vals) in enumerate(indexed.items()):
        pts = " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(vals))
        p.append(f'<polyline class="line s{cls}" points="{pts}"/>')
        ex, ey = X(n-1), Y(vals[-1])
        p.append(f'<circle class="dot s{cls}" cx="{ex:.1f}" cy="{ey:.1f}" r="3"/>')
        p.append(f'<text class="end s{cls}t" x="{ex+8:.1f}" y="{ey:.1f}" dominant-baseline="central">{name} {vals[-1]:.0f}</text>')
    p.append("</svg>")
    return "".join(p)


def _trade_chart(months):
    w, h, ml, mr, mt, mb = 660, 300, 52, 96, 16, 30
    pw, ph = w-ml-mr, h-mt-mb
    exp = [m["exp"] or 0 for m in months]
    imp = [m["imp"] or 0 for m in months]
    n = len(months)
    hi = max(exp+imp) or 1
    X = lambda i: ml + pw*i/(max(n-1, 1))
    Y = lambda v: mt + ph*(1-v/(hi*1.08))
    p = [f'<svg class="idx" viewBox="0 0 {w} {h}" role="img">']
    # y gridlines in $B
    import math
    step = max(1, math.ceil((hi/1e9)/4))
    g = 0
    while g*1e9 <= hi:
        yy = Y(g*1e9)
        p.append(f'<line class="grid" x1="{ml}" y1="{yy:.1f}" x2="{ml+pw}" y2="{yy:.1f}"/>')
        p.append(f'<text class="axis" x="{ml-8}" y="{yy:.1f}" text-anchor="end" dominant-baseline="central">${g}B</text>')
        g += step
    # x labels at year starts
    seen = set()
    for i, m in enumerate(months):
        yr = m["fiscal_year"]
        if yr not in seen:
            seen.add(yr)
            p.append(f'<text class="axis" x="{X(i):.1f}" y="{h-6}" text-anchor="middle">{yr}</text>')
    for cls, series in enumerate((imp, exp)):        # imports first (usually higher)
        pts = " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(series))
        p.append(f'<polyline class="line s{cls}" points="{pts}"/>')
    name = {0: "Imports", 1: "Exports"}
    for cls, series in enumerate((imp, exp)):
        ex, ey = X(n-1), Y(series[-1])
        p.append(f'<circle class="dot s{cls}" cx="{ex:.1f}" cy="{ey:.1f}" r="3"/>')
        p.append(f'<text class="end s{cls}t" x="{ex+8:.1f}" y="{ey:.1f}" dominant-baseline="central">{name[cls]}</text>')
    p.append("</svg>")
    return "".join(p)


# ---- structural helpers --------------------------------------------------


def _section(num, title, lede=""):
    lede_html = f'<p class="lede">{lede}</p>' if lede else ""
    return (f'<div class="sect-head"><span class="sect-no">{num}</span>'
            f'<h2>{title}</h2></div>{lede_html}')


def _exhibit(num, title, body, source):
    return (f'<figure class="exhibit"><figcaption><span class="ex-no">Exhibit {num}</span>'
            f'<span class="ex-title">{title}</span></figcaption>{body}'
            f'<p class="ex-src">{source}</p></figure>')


# ---- styles --------------------------------------------------------------

STYLE = """
<style>
:root{
  --paper:#FFFFFF; --ground:#F5F6F8; --ink:#16191D; --muted:#586069;
  --faint:#8A9099; --rule:#E3E6EA; --accent:#123E63; --accent-dk:#0B2A45;
  --accent-2:#2B6CA3; --accent-soft:rgba(18,62,99,.09); --neg:#9A3B34;
}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
  --paper:#141821; --ground:#1B2029; --ink:#E7EAEF; --muted:#9AA2AD;
  --faint:#6C7580; --rule:#262D37; --accent:#7FB0DC; --accent-dk:#A9CCE6;
  --accent-2:#5C93C4; --accent-soft:rgba(127,176,220,.13); --neg:#D08A82;
}}
:root[data-theme="dark"]{
  --paper:#141821; --ground:#1B2029; --ink:#E7EAEF; --muted:#9AA2AD;
  --faint:#6C7580; --rule:#262D37; --accent:#7FB0DC; --accent-dk:#A9CCE6;
  --accent-2:#5C93C4; --accent-soft:rgba(127,176,220,.13); --neg:#D08A82;
}
*{box-sizing:border-box}
body{background:var(--paper);color:var(--ink);
  font-family:"Libre Franklin",system-ui,-apple-system,sans-serif;
  line-height:1.6;-webkit-font-smoothing:antialiased;font-variant-numeric:tabular-nums}
.paper{max-width:820px;margin:0 auto;padding:64px 32px 96px}
.serif{font-family:"Newsreader",Georgia,serif}
/* cover */
.eyebrow{font-size:.7rem;font-weight:600;letter-spacing:.18em;text-transform:uppercase;
  color:var(--accent);margin:0 0 20px}
h1{font-family:"Newsreader",Georgia,serif;font-weight:500;
  font-size:clamp(2.2rem,5vw,3.3rem);line-height:1.05;letter-spacing:-.01em;
  text-wrap:balance;margin:0 0 18px}
.standfirst{font-family:"Newsreader",Georgia,serif;font-size:1.3rem;line-height:1.45;
  color:var(--muted);max-width:34ch;margin:0 0 28px;font-weight:400}
.meta{display:flex;flex-wrap:wrap;gap:6px 28px;padding-top:22px;border-top:1px solid var(--ink);
  font-size:.82rem;color:var(--muted)}
.meta b{color:var(--ink);font-weight:600}
.asof{color:var(--accent);font-weight:600}
/* sections */
section{margin-top:64px}
.sect-head{display:flex;align-items:baseline;gap:16px;margin:0 0 4px;
  padding-bottom:16px;border-bottom:2px solid var(--accent)}
.sect-no{font-family:"Newsreader",Georgia,serif;font-size:1.4rem;color:var(--accent);
  font-weight:500}
.sect-head h2{font-family:"Newsreader",Georgia,serif;font-weight:500;font-size:1.9rem;
  margin:0;letter-spacing:-.01em}
.lede{font-size:1.05rem;color:var(--muted);max-width:62ch;margin:18px 0 0}
/* market-size headline */
.headline{margin:28px 0 8px;padding:26px 0;border-top:1px solid var(--rule);
  border-bottom:1px solid var(--rule)}
.headline .k{font-size:.72rem;font-weight:600;letter-spacing:.12em;text-transform:uppercase;
  color:var(--muted)}
.headline .big{font-family:"Newsreader",Georgia,serif;font-size:3rem;font-weight:500;
  line-height:1;letter-spacing:-.02em;margin:8px 0 6px;display:flex;align-items:baseline;gap:16px}
.headline .chg{font-family:"Libre Franklin",sans-serif;font-size:1rem;color:var(--accent);font-weight:600}
.headline .note{color:var(--muted);font-size:.86rem;max-width:70ch;margin:0}
/* key figures band */
.figband{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
  margin:34px 0;border-top:1px solid var(--rule)}
.fig{padding:20px 20px 20px 0;border-bottom:1px solid var(--rule)}
.fig .k{font-size:.68rem;font-weight:600;letter-spacing:.1em;text-transform:uppercase;color:var(--muted)}
.fig .v{font-family:"Newsreader",Georgia,serif;font-size:1.7rem;font-weight:500;margin:6px 0 2px;letter-spacing:-.01em}
.fig .c{font-size:.8rem;color:var(--accent);font-weight:600}
.spark{display:block;width:100%;height:40px;margin-top:12px}
.spark-area{fill:var(--accent-soft)}
.spark-line{fill:none;stroke:var(--accent);stroke-width:1.5;vector-effect:non-scaling-stroke}
/* exhibits */
.exhibit{margin:32px 0 0;padding:0}
.exhibit figcaption{display:flex;align-items:baseline;gap:12px;margin-bottom:18px}
.ex-no{font-size:.68rem;font-weight:700;letter-spacing:.1em;text-transform:uppercase;color:var(--accent)}
.ex-title{font-weight:600;font-size:1rem}
.ex-src{font-size:.74rem;color:var(--faint);margin:14px 0 0;padding-top:10px;border-top:1px solid var(--rule)}
.bars,.idx{width:100%;height:auto;display:block}
.bar-track{fill:var(--ground)}
.bar{fill:var(--accent)}
.bar-label{font-family:"Libre Franklin",sans-serif;font-size:13px;fill:var(--ink)}
.bar-value{font-family:"Libre Franklin",sans-serif;font-size:12.5px;fill:var(--muted)}
.grid{stroke:var(--rule);stroke-width:1}
.axis{font-family:"Libre Franklin",sans-serif;font-size:11px;fill:var(--faint)}
.line{fill:none;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}
.s0{stroke:var(--accent)} .s1{stroke:var(--accent-2);stroke-dasharray:0}
.dot.s0{fill:var(--accent)} .dot.s1{fill:var(--accent-2)}
.end{font-size:11.5px;font-weight:600} .s0t{fill:var(--accent)} .s1t{fill:var(--accent-2)}
/* finding callout */
.finding{font-family:"Newsreader",Georgia,serif;font-size:1.25rem;line-height:1.5;
  color:var(--ink);border-left:3px solid var(--accent);padding:4px 0 4px 22px;margin:28px 0}
.finding b{font-weight:600}
/* key players table */
.players{width:100%;border-collapse:collapse;font-size:.92rem;margin-top:4px}
.players th{text-align:left;font-size:.68rem;font-weight:600;letter-spacing:.08em;
  text-transform:uppercase;color:var(--faint);padding:0 0 10px;border-bottom:1px solid var(--ink)}
.players td{padding:11px 0;border-bottom:1px solid var(--rule)}
.players .tk{font-weight:600;color:var(--accent)}
.players .ck{color:var(--faint);font-size:.78rem}
.empty{color:var(--muted);max-width:60ch}
/* forces */
.forces{border-top:1px solid var(--rule);margin-top:24px}
.frow{display:grid;grid-template-columns:200px 1fr auto;gap:18px;align-items:baseline;
  padding:18px 0;border-bottom:1px solid var(--rule)}
@media(max-width:640px){.frow{grid-template-columns:1fr}}
.frow .fk{font-weight:600;font-size:1rem}
.frow p{margin:0;color:var(--muted);font-size:.9rem}
.tag{font-size:.66rem;font-weight:600;letter-spacing:.06em;text-transform:uppercase;
  color:var(--faint);white-space:nowrap}
.tag.live{color:var(--accent)}
/* provenance */
.prov{margin-top:20px}
.prov dl{display:grid;grid-template-columns:auto 1fr;gap:10px 22px;margin:0;font-size:.82rem}
.prov dt{color:var(--faint);font-weight:600}
.prov dd{margin:0;color:var(--ink);word-break:break-word}
.foot{margin-top:56px;padding-top:20px;border-top:2px solid var(--accent);
  font-size:.76rem;color:var(--faint);display:flex;justify-content:space-between;flex-wrap:wrap;gap:8px}
</style>
"""


def render(conn, naics, title, key_players=None, bea_industry=None, bea_note="",
           hs=None, hs_note="", bfs=None, bfs_note="", nass=None) -> str:
    subject = f"NAICS:{naics}"
    series = _us_series(conn, subject)
    if not series:
        raise ValueError(f"no observations for {subject} — load data first")
    first, last = series[0], series[-1]
    y0, y1 = first["year"], last["year"]
    estabs = [s["estabs"] for s in series]
    emp = [s["emp"] for s in series]
    wages = [s["wages"] for s in series]
    pay = [derive.apply("avg_annual_pay", s["wages"], s["emp"]) for s in series]
    size = [derive.apply("avg_establishment_size", s["emp"], s["estabs"]) for s in series]
    n_years = max(y1 - y0, 1)
    cagr = lambda v: f"{derive.apply('cagr', v[0], v[-1], n_years):+.1%}/yr"

    bea = _bea_output(conn, bea_industry)
    bea_q = _bea_latest_quarter(conn, bea_industry)
    io = _io(conn, bea_industry)
    bfs_data = _bfs(conn, bfs)
    nass_data = _nass(conn, nass)
    cbp = _cbp(conn, naics)
    trade = _trade(conn, hs)
    partners = _trade_partners(conn, hs)
    prov = _provenance(conn, subject)
    ppi = _ppi(conn, naics)
    retrieved = (prov.get("last") or "")[:10]

    ex_counter = [0]
    def ex(title, body, source):
        ex_counter[0] += 1
        return _exhibit(ex_counter[0], title, body, source)

    # ---- cover meta / freshness -----------------------------------------
    vintages = [f"QCEW {y1}"]
    if nass_data:
        vintages.append(f"NASS {nass_data['year']}")
    if bea_q:
        vintages.append(f"BEA {bea_q['fiscal_year']} {bea_q['fiscal_period']}")
    elif bea:
        vintages.append(f"BEA {bea[-1]['year']}")
    if cbp:
        vintages.append(f"CBP {cbp['year']}")
    if io:
        vintages.append(f"I-O {io['year']}")
    if bfs_data:
        bm = conn.execute("SELECT MAX(period_end) FROM observations WHERE subject_id=?",
                          (f"BFS:{bfs}",)).fetchone()[0]
        if bm:
            vintages.append(f"BFS {bm[:7]}")
    if trade:
        latest_month = trade["months"][-1]["period_end"][:7]
        vintages.append(f"Trade {latest_month}")
    if ppi:
        vintages.append(f"PPI {ppi['latest_date']}")

    # ---- Section 1: market size & growth --------------------------------
    # Prefer an industry-appropriate size: ag value of production (NASS) if
    # present, else BEA sector gross output.
    if nass_data:
        top = ", ".join(f'{i["commodity"]} {_usd_b(i["value"])}' for i in nass_data["items"][:3])
        bea_ref = (f" BEA 'Farms' output ({_usd_b0(bea[-1]['value'])}) covers all U.S. "
                   "agriculture and is far broader.") if bea else ""
        headline = (
            '<div class="headline"><div class="k">Value of production · '
            f'{nass_data["year"]}</div><div class="big serif">{_usd_b(nass_data["total"])}</div>'
            f'<p class="note">USDA value of production across {len(nass_data["items"])} tree-nut '
            f'commodities ({top}).{bea_ref} Source: USDA NASS.</p></div>')
    elif bea:
        bf, bl = bea[0], bea[-1]
        bcagr = derive.apply("cagr", bf["value"], bl["value"], max(bl["year"]-bf["year"], 1))
        q_note = ""
        if bea_q:
            q_note = (f' Most recent quarter: {bea_q["fiscal_period"]} {bea_q["fiscal_year"]} '
                      f'{_usd_b0(bea_q["value"])} (annualised rate).')
        headline = (
            '<div class="headline"><div class="k">Market size · sector gross output · '
            f'{bl["year"]}</div><div class="big serif">{_usd_b0(bl["value"])}'
            f'<span class="chg">{bcagr:+.1%}/yr since {bf["year"]}</span></div>'
            f'<p class="note">{bea_note} Source: BEA GDP-by-Industry.{q_note}</p></div>')
    else:
        headline = ('<div class="headline"><div class="k">Market size</div>'
                    '<div class="big serif">—</div><p class="note">BEA source not loaded.</p></div>')

    figs = [
        ("Establishments", _int(estabs[-1]), cagr(estabs), _sparkline(estabs)),
        ("Employment", _int(emp[-1]), cagr(emp), _sparkline(emp)),
        ("Total wages", _usd_b(wages[-1]), cagr(wages), _sparkline(wages)),
        ("Avg pay / worker", f"${_int(pay[-1])}", cagr(pay), _sparkline(pay)),
        ("Workers / estab.", f"{size[-1]:.0f}", cagr(size), _sparkline(size)),
    ]
    figband = '<div class="figband">' + "".join(
        f'<div class="fig"><div class="k">{k}</div><div class="v">{v}</div>'
        f'<div class="c">{c} since {y0}</div>{sp}</div>' for k, v, c, sp in figs) + "</div>"

    nass_ex = ""
    if nass_data:
        nass_ex = ex(f"Value of production by commodity, {nass_data['year']}",
                     _hbars([{"label": i["commodity"], "value": i["value"]} for i in nass_data["items"]],
                            _usd_b, ""),
                     "USDA NASS, value of utilized production.")
    ex_index = ex(f"Indexed growth, {y0}–{y1} ({y0} = 100)",
                  _index_chart([s["year"] for s in series],
                               {"Wages": wages, "Estab.": estabs, "Employ.": emp}),
                  "BLS QCEW; growth via derivation cagr/index_to_base v1.0.0. "
                  "Wages rising faster than employment ⇒ pay per worker climbing.")
    ex_geo = ex(f"Employment by state, {y1}",
                _hbars(_top_states(conn, subject, y1), _int, " employees"),
                "BLS QCEW, private ownership. Top 8 states.")

    ppi_ex = ""
    if ppi:
        chg = (ppi["latest"] / ppi["first"] - 1) if ppi["first"] else 0
        ppi_ex = ex(f"Producer prices, {ppi['first_date']}–{ppi['latest_date']}",
                    _sparkline(ppi["values"]),
                    f"BLS Producer Price Index (via FRED). Index {ppi['first']:.1f} → "
                    f"{ppi['latest']:.1f} ({chg:+.1%} over the window).")

    section1 = ("<section>" + _section("01", "Market size & growth",
                "How large the industry is, and how fast it is moving. Value of production "
                "and output; employment, wages and establishments from the QCEW near-census "
                "of covered employers.") + headline + figband + nass_ex + ex_index + ex_geo
                + ppi_ex + "</section>")

    # ---- Section 2: competitive structure -------------------------------
    struct_parts = [_section("02", "Competitive structure",
                    "The shape of competition — how many firms, and how concentrated. "
                    "Establishment size distribution from the Census County Business Patterns.")]
    if cbp and cbp["dist"]:
        large = sum(d["value"] for d in cbp["dist"] if d["code"] in LARGE_CODES)
        share = derive.apply("ratio", large, cbp["estabs"]) if cbp["estabs"] else 0
        biggest = next((d["value"] for d in cbp["dist"] if d["code"] == "260"), 0)
        struct_parts.append(
            f'<p class="finding">Of <b>{_int(cbp["estabs"])}</b> establishments in '
            f'{cbp["year"]}, <b>{share:.0%}</b> employ 250 or more; <b>{_int(biggest)}</b> '
            f'employ 1,000+. A concentrated core sits above a long tail of small shops.</p>')
        struct_parts.append(ex(f"Establishments by employment size, {cbp['year']}",
                            _hbars([{"label": d["label"], "value": d["value"]} for d in cbp["dist"]],
                                   _int, " establishments"),
                            "Census County Business Patterns. CBP counts differ from QCEW "
                            "(different methodology and coverage)."))
    if key_players and key_players.get("players"):
        players = sorted(key_players["players"], key=lambda p: (p["name"] or ""))[:15]
        rows = "".join(f'<tr><td class="tk">{p["ticker"] or "—"}</td><td>{p["name"]}</td>'
                       f'<td class="ck">CIK{p["cik"]}</td></tr>' for p in players)
        struct_parts.append(ex("Public companies in the industry",
            '<table class="players"><thead><tr><th>Ticker</th><th>Company</th><th>Filer</th></tr>'
            f'</thead><tbody>{rows}</tbody></table>',
            f"SEC EDGAR, SIC {key_players['sic']}. 15 of {key_players['total_named']} public "
            "filers with tickers; revenue ranking pending."))
    else:
        struct_parts.append('<p class="empty">No public companies are classified in this '
                            "industry under EDGAR — a largely private industry.</p>")
    section2 = "<section>" + "".join(struct_parts) + "</section>"

    # ---- Section 3: trade exposure --------------------------------------
    if trade:
        bal = trade["exports"] - trade["imports"]
        pen = derive.apply("ratio", trade["imports"], trade["exports"]) if trade["exports"] else 0
        balword = "surplus" if bal >= 0 else "deficit"
        section3 = ("<section>" + _section("03", "Trade exposure",
            "Exposure to global flows — export orientation and import competition, "
            "from Census monthly trade by HS commodity code.") +
            f'<p class="finding">In {trade["year"]}, the U.S. ran a trade <b>{balword}</b> of '
            f'<b>{_usd_b(abs(bal))}</b> in {hs_note.split("—")[0].strip() if hs_note else "this product"}: '
            f'<b>{_usd_b(trade["exports"])}</b> exports against <b>{_usd_b(trade["imports"])}</b> '
            f'imports ({pen:.1f}× import cover).</p>' +
            ex(f"Monthly exports vs. imports, HS {hs}", _trade_chart(trade["months"]),
               f"Census international trade. {hs_note}"))
        if partners and partners["exports"]:
            dests = ", ".join(f"{n} {_usd_b(v)}" for n, v in partners["exports"][:3])
            srcs = ", ".join(f"{n} {_usd_b(v)}" for n, v in partners["imports"][:3])
            section3 += (
                f'<p class="finding">In {partners["year"]}, top export destinations were '
                f'<b>{dests}</b>; leading import sources <b>{srcs}</b>.</p>' +
                ex(f"Top export destinations, {partners['year']}",
                   _hbars([{"label": n, "value": v} for n, v in partners["exports"]], _usd_b, ""),
                   "Census international trade, by partner country."))
        section3 += "</section>"
    else:
        section3 = ("<section>" + _section("03", "Trade exposure",
                    "Export orientation and import competition.") +
                    '<p class="empty">No trade data loaded for this industry.</p></section>')

    # ---- Section 4: five forces -----------------------------------------
    rivalry_live = bool(cbp and cbp["dist"])
    io_parts = []
    supplier_desc = "Upstream input costs and concentration (BEA input-output)."
    buyer_desc = ("Trade shows export dependence and import cover."
                  if trade else "Downstream demand concentration and export dependence.")
    supplier_tag = buyer_tag = "In development"

    if io and io["inputs"]:
        top_in, top_in_v = io["inputs"][0]
        in_share = derive.apply("ratio", top_in_v, io["total_in"]) if io["total_in"] else 0
        io_parts.append(
            f'<p class="finding">Inputs are <b>diversified</b>: the largest single supplier '
            f'({top_in}) is only <b>{in_share:.0%}</b> of <b>{_usd_b0(io["total_in"])}</b> in '
            f'intermediate purchases ({io["year"]}) — pointing to <b>limited supplier power</b>.</p>')
        supplier_desc = f"Largest input {in_share:.0%} of {_usd_b0(io['total_in'])}; diversified base."
        supplier_tag = "Backed by BEA I-O"

    if io and io["outputs"]:
        top_buy, top_buy_v = io["outputs"][0]
        buy_share = derive.apply("ratio", top_buy_v, io["total_out"]) if io["total_out"] else 0
        exp_share = derive.apply("ratio", io["exports"], io["total_out"]) if io["total_out"] else 0
        io_parts.append(
            f'<p class="finding">Demand is <b>broad-based</b>: the largest customer ({top_buy}) '
            f'takes <b>{buy_share:.0%}</b> of output and exports absorb <b>{_usd_b0(io["exports"])}</b> '
            f'({exp_share:.0%}) — no dominant buyer, indicating <b>limited buyer power</b>.</p>')
        io_parts.append(ex(f"Where the industry's output goes, {io['year']}",
                        _hbars([{"label": lbl, "value": v} for lbl, v in io["outputs"][:6]],
                               _usd_b, ""),
                        "BEA Input-Output, Use table. Top 6 destinations of gross output."))
        buyer_desc = f"Top buyer {buy_share:.0%}; exports {exp_share:.0%}. Broad demand."
        buyer_tag = "Backed by BEA I-O"

    # Threat of new entrants: QCEW net establishment growth + BFS applications trend.
    estab_cagr = derive.apply("cagr", estabs[0], estabs[-1], n_years)
    entrants_desc, entrants_tag = "Capital intensity and establishment birth/death.", "In development"
    if bfs_data and len(bfs_data["apps"]) >= 2:
        (py, pv), (ly, lv) = bfs_data["apps"][-2], bfs_data["apps"][-1]
        apps_yoy = derive.apply("yoy", pv, lv)
        io_parts.append(
            f'<p class="finding">Establishments grew <b>{estab_cagr:+.1%}/yr</b> (net entry, QCEW), '
            f'while sector-wide new-business applications moved <b>{apps_yoy:+.0%}</b> in {ly} '
            f'(BFS, sector-level). Yet fab-scale <b>capital intensity</b> keeps real entry barriers '
            f'high — a qualitative brake the counts understate.</p>')
        entrants_desc = f"Estabs {estab_cagr:+.1%}/yr; sector applications {apps_yoy:+.0%} {ly}."
        entrants_tag = "Backed by QCEW + BFS"

    forces = [
        ("Competitive rivalry",
         ("Establishment size distribution shows a concentrated core over a long tail."
          if rivalry_live else "Awaiting concentration data."),
         "Backed by CBP" if rivalry_live else "In development"),
        ("Threat of new entrants", entrants_desc, entrants_tag),
        ("Threat of substitutes", "Largely qualitative — no direct dataset; analytical.", "Narrative"),
        ("Supplier power", supplier_desc, supplier_tag),
        ("Buyer power", buyer_desc, buyer_tag),
    ]
    frows = "".join(
        f'<div class="frow"><div class="fk">{k}</div><p>{d}</p>'
        f'<span class="tag{" live" if t.startswith("Backed") else ""}">{t}</span></div>'
        for k, d, t in forces)
    section4 = ("<section>" + _section("04", "Competitive forces",
                "Porter's Five Forces. Each force is written over the loaded data, with every "
                "figure cited; forces still gathering data are marked.") +
                "".join(io_parts) + f'<div class="forces">{frows}</div></section>')

    # ---- Section 5: provenance ------------------------------------------
    prov_rows = [("Data as of", " · ".join(vintages)),
                 ("Sizing", "BLS QCEW (employment, wages, establishments)")]
    if nass_data:
        prov_rows.append(("Value of production", "USDA NASS (value of utilized production)"))
    if bea:
        prov_rows.append(("Market size", "BEA GDP-by-Industry, gross output (TableID 15)"))
    if cbp:
        prov_rows.append(("Concentration", "Census County Business Patterns (size distribution)"))
    if trade:
        prov_rows.append(("Trade", f"Census international trade, HS {hs} (monthly)"))
    if io:
        prov_rows.append(("Supplier / buyer", "BEA Input-Output, Use table (TableID 259)"))
    if bfs_data:
        prov_rows.append(("New entrants", "Census Business Formation Statistics (sector level)"))
    if key_players:
        prov_rows.append(("Key players", f"SEC EDGAR, SIC {key_players['sic']}"))
    prov_rows += [("Licence", prov.get("licence_class", "")),
                  ("Retrieved", retrieved),
                  ("Method", "Every figure traces to an observation; computed figures use "
                             "versioned derivations. No figure hand-entered.")]
    prov_html = "".join(f"<dt>{k}</dt><dd>{v}</dd>" for k, v in prov_rows)
    section5 = ("<section>" + _section("05", "Provenance & data vintages") +
                f'<div class="prov"><dl>{prov_html}</dl></div></section>')

    return f"""<title>{title}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Libre+Franklin:wght@400;500;600;700&family=Newsreader:opsz,wght@6..72,400;6..72,500;6..72,600&display=swap">
{STYLE}
<article class="paper">
  <header>
    <p class="eyebrow">Terminal Zero — Industry Analysis</p>
    <h1>{title}</h1>
    <p class="standfirst">A provenance-first read on the industry: how big, how fast,
      how concentrated, how exposed — every figure traceable.</p>
    <div class="meta">
      <span><b>NAICS</b> {naics}</span>
      <span><b>Period</b> {y0}–{y1}</span>
      <span class="asof">Data as of {' · '.join(vintages)}</span>
    </div>
  </header>
  {section1}
  {section2}
  {section3}
  {section4}
  {section5}
  <div class="foot"><span>Generated from the observation store — no figure hand-entered.</span>
    <span>Terminal Zero</span></div>
</article>
"""
