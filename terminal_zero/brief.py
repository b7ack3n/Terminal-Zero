"""Render a room as an industry brief (HTML).

"A report is one rendering of a room." Every figure here is pulled from the
store via the room — nothing is hand-typed. The charts are computed from the
observation values, so the brief cannot drift from its sources.

Output is a self-contained HTML fragment (title + fonts + styles + markup),
suitable for publishing as an Artifact.
"""

from __future__ import annotations

import sqlite3

from terminal_zero import geo, room

# ---- data assembly (all numbers come from the store) ---------------------


def _us_series(conn: sqlite3.Connection, subject_id: str) -> list[dict]:
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


def _top_states(conn, subject_id, year, limit=8) -> list[dict]:
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


def _provenance(conn, subject_id) -> dict:
    row = conn.execute(
        """
        SELECT MIN(retrieved_at) AS first, MAX(retrieved_at) AS last,
               source, licence_class
        FROM observations WHERE subject_id=?
        """,
        (subject_id,),
    ).fetchone()
    return dict(row) if row else {}


# ---- formatting ----------------------------------------------------------


def _int(v) -> str:
    return f"{v:,.0f}"


def _usd_b(v) -> str:
    return f"${v / 1e9:,.1f}B"


def _pct(first, last) -> str:
    if not first:
        return "—"
    p = (last - first) / first * 100
    return f"{p:+.1f}%"


# ---- svg marks (computed from data) --------------------------------------


def _sparkline(values: list[float]) -> str:
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
        f'role="img" aria-hidden="true">'
        f'<polygon class="spark-area" points="{area}"/>'
        f'<polyline class="spark-line" points="{line}"/>'
        f"</svg>"
    )


def _bars(rows: list[dict]) -> str:
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
        parts.append(
            f'<text class="bar-label" x="{labelw}" y="{mid}" text-anchor="end" '
            f'dominant-baseline="central">{r["label"]}</text>'
        )
        parts.append(
            f'<rect class="bar-track" x="{trackx}" y="{y}" width="{trackw}" '
            f'height="{barh}" rx="4"/>'
        )
        parts.append(
            f'<rect class="bar" x="{trackx}" y="{y}" width="{bw:.1f}" height="{barh}" '
            f'rx="4"><title>{r["label"]}: {_int(r["value"])} employees</title></rect>'
        )
        parts.append(
            f'<text class="bar-value" x="{trackx + bw + 8:.1f}" y="{mid}" '
            f'dominant-baseline="central">{_int(r["value"])}</text>'
        )
    parts.append("</svg>")
    return "".join(parts)


# ---- the page ------------------------------------------------------------

STYLE = """
<style>
:root{
  --bg:#F5F7FA; --surface:#FFFFFF; --ink:#14181F; --muted:#5B6673;
  --faint:#8A94A2; --line:#E3E8EF; --track:#EDF1F6;
  --accent:#0E7C86; --accent-ink:#0B5F67; --accent-fill:rgba(14,124,134,.14);
}
:root:not([data-theme="light"]){ }
@media (prefers-color-scheme:dark){
  :root:not([data-theme="light"]){
    --bg:#0C0F14; --surface:#12161D; --ink:#E7ECF3; --muted:#9BA6B4;
    --faint:#6B7686; --line:#232A34; --track:#1B2129;
    --accent:#3FB6C4; --accent-ink:#7FD4DE; --accent-fill:rgba(63,182,196,.16);
  }
}
:root[data-theme="dark"]{
  --bg:#0C0F14; --surface:#12161D; --ink:#E7ECF3; --muted:#9BA6B4;
  --faint:#6B7686; --line:#232A34; --track:#1B2129;
  --accent:#3FB6C4; --accent-ink:#7FD4DE; --accent-fill:rgba(63,182,196,.16);
}
*{box-sizing:border-box}
body{
  background:var(--bg); color:var(--ink);
  font-family:"IBM Plex Sans",system-ui,-apple-system,sans-serif;
  line-height:1.55; -webkit-font-smoothing:antialiased;
}
.wrap{max-width:900px;margin:0 auto;padding:56px 28px 80px}
.mono{font-family:"IBM Plex Mono",ui-monospace,monospace}
.eyebrow{
  font-family:"IBM Plex Mono",monospace;font-size:.72rem;letter-spacing:.22em;
  text-transform:uppercase;color:var(--accent-ink);margin:0 0 14px
}
h1{
  font-family:"IBM Plex Serif",Georgia,serif;font-weight:600;
  font-size:clamp(2rem,4.2vw,2.9rem);line-height:1.08;letter-spacing:-.01em;
  text-wrap:balance;margin:0 0 12px
}
.dek{color:var(--muted);font-size:1.05rem;max-width:60ch;margin:0}
.masthead{border-bottom:1px solid var(--line);padding-bottom:26px;margin-bottom:8px}
.coverage{
  font-family:"IBM Plex Mono",monospace;font-size:.8rem;color:var(--faint);
  margin-top:18px;display:flex;flex-wrap:wrap;gap:6px 22px
}
.coverage b{color:var(--muted);font-weight:500}
section{margin-top:44px}
.label{
  font-family:"IBM Plex Mono",monospace;font-size:.74rem;letter-spacing:.16em;
  text-transform:uppercase;color:var(--faint);margin:0 0 18px;
  display:flex;align-items:center;gap:12px
}
.label::after{content:"";flex:1;height:1px;background:var(--line)}
.tiles{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}
@media(max-width:680px){.tiles{grid-template-columns:1fr}}
.tile{
  background:var(--surface);border:1px solid var(--line);border-radius:10px;
  padding:20px 20px 14px;display:flex;flex-direction:column;gap:2px
}
.tile .k{font-family:"IBM Plex Mono",monospace;font-size:.72rem;
  letter-spacing:.12em;text-transform:uppercase;color:var(--muted)}
.tile .v{font-family:"IBM Plex Mono",monospace;font-size:1.7rem;font-weight:600;
  font-variant-numeric:tabular-nums;letter-spacing:-.01em;margin-top:4px}
.tile .chg{font-family:"IBM Plex Mono",monospace;font-size:.8rem;
  color:var(--accent-ink);font-variant-numeric:tabular-nums}
.spark{display:block;width:100%;height:58px;margin-top:14px}
.spark-area{fill:var(--accent-fill)}
.spark-line{fill:none;stroke:var(--accent);stroke-width:2;
  stroke-linecap:round;stroke-linejoin:round;vector-effect:non-scaling-stroke}
.bars{width:100%;height:auto}
.bar-track{fill:var(--track)}
.bar{fill:var(--accent)}
.bar-label{font-family:"IBM Plex Sans",sans-serif;font-size:13px;fill:var(--ink)}
.bar-value{font-family:"IBM Plex Mono",monospace;font-size:12.5px;
  fill:var(--muted);font-variant-numeric:tabular-nums}
.chartcard{background:var(--surface);border:1px solid var(--line);
  border-radius:10px;padding:24px}
.chartcard .cap{font-family:"IBM Plex Mono",monospace;font-size:.74rem;
  color:var(--faint);margin:16px 0 0}
.prov{background:var(--surface);border:1px solid var(--line);border-radius:10px;
  padding:22px 24px;font-size:.9rem;color:var(--muted)}
.prov h3{font-family:"IBM Plex Mono",monospace;font-size:.74rem;letter-spacing:.14em;
  text-transform:uppercase;color:var(--faint);margin:0 0 12px;font-weight:500}
.prov dl{display:grid;grid-template-columns:auto 1fr;gap:8px 18px;margin:0}
.prov dt{font-family:"IBM Plex Mono",monospace;color:var(--faint);font-size:.8rem}
.prov dd{margin:0;font-family:"IBM Plex Mono",monospace;font-size:.8rem;
  color:var(--ink);word-break:break-all}
.foot{margin-top:40px;padding-top:20px;border-top:1px solid var(--line);
  font-family:"IBM Plex Mono",monospace;font-size:.74rem;color:var(--faint);
  display:flex;justify-content:space-between;flex-wrap:wrap;gap:8px}
</style>
"""


def render(conn: sqlite3.Connection, naics: str, title: str) -> str:
    subject = f"NAICS:{naics}"
    series = _us_series(conn, subject)
    if not series:
        raise ValueError(f"no observations for {subject} — load data first")
    first, last = series[0], series[-1]
    year0, year1 = first["year"], last["year"]
    top = _top_states(conn, subject, year1)
    prov = _provenance(conn, subject)
    cov = room.summary(conn, room.RoomDefinition(name="_", subject_ids=[subject]))

    estabs = [s["estabs"] for s in series]
    emp = [s["emp"] for s in series]
    wages = [s["wages"] for s in series]

    tiles = [
        ("Establishments", _int(last["estabs"]), _pct(first["estabs"], last["estabs"]), _sparkline(estabs)),
        ("Employment", _int(last["emp"]), _pct(first["emp"], last["emp"]), _sparkline(emp)),
        ("Total annual wages", _usd_b(last["wages"]), _pct(first["wages"], last["wages"]), _sparkline(wages)),
    ]
    tiles_html = "".join(
        f'<div class="tile"><span class="k">{k}</span>'
        f'<span class="v">{v}</span>'
        f'<span class="chg">{chg} since {year0}</span>{spark}</div>'
        for k, v, chg, spark in tiles
    )

    retrieved = (prov.get("last") or "")[:10]

    return f"""<title>{title}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Serif:wght@500;600&display=swap">
{STYLE}
<div class="wrap">
  <header class="masthead">
    <p class="eyebrow">Terminal Zero · Industry Brief</p>
    <h1>{title}</h1>
    <p class="dek">A provenance-first snapshot of the U.S. semiconductor
      manufacturing industry. Every figure is drawn from a cited source and can
      be traced to the observation it came from.</p>
    <div class="coverage">
      <span><b>NAICS</b> {naics}</span>
      <span><b>Period</b> {year0}–{year1}</span>
      <span><b>Geographies</b> {cov['geos']}</span>
      <span><b>Observations</b> {cov['observations']}</span>
      <span><b>Source</b> {', '.join(cov['sources'])}</span>
    </div>
  </header>

  <section>
    <p class="label">Key figures · {year1}</p>
    <div class="tiles">{tiles_html}</div>
  </section>

  <section>
    <p class="label">Geographic concentration · employment, {year1}</p>
    <div class="chartcard">
      {_bars(top)}
      <p class="cap">Top {len(top)} states by average annual employment, private
        ownership. Source: BLS QCEW.</p>
    </div>
  </section>

  <section>
    <p class="label">Provenance</p>
    <div class="prov">
      <h3>How to trace these numbers</h3>
      <dl>
        <dt>Source</dt><dd>{prov.get('source','')}</dd>
        <dt>Dataset</dt><dd>Quarterly Census of Employment and Wages (annual)</dd>
        <dt>Endpoint</dt><dd>https://data.bls.gov/cew/data/api/&lt;year&gt;/a/industry/{naics}.csv</dd>
        <dt>Licence</dt><dd>{prov.get('licence_class','')}</dd>
        <dt>Retrieved</dt><dd>{retrieved}</dd>
        <dt>Scope</dt><dd>Private ownership; U.S. + states; suppressed cells omitted</dd>
      </dl>
    </div>
  </section>

  <div class="foot">
    <span>Generated from the observation store — no figure hand-entered.</span>
    <span>Terminal Zero</span>
  </div>
</div>
"""
