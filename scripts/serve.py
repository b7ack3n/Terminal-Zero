"""A minimal local web server for the engine — the search box, made live.

    PYTHONPATH=. python scripts/serve.py            # http://localhost:8777

Type a name or NAICS code. The registry resolves it; if the industry's data is
already in the store the brief renders on the spot, otherwise the server pulls it
live from every mapped source (refresh) and then renders. Stdlib only — this is a
local demo of the pipeline in a browser, not a production deployment.
"""

from __future__ import annotations

import html
import json
import subprocess
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from terminal_zero import brief, config, naics, registry
from terminal_zero.store import connect

PORT = 8777
_BACKBONE = naics.load()


_fetcher = None


def _wiki_context(name: str) -> dict | None:
    """Best-effort Wikipedia context for an industry (qualitative, lower-trust).

    Fetches the REST summary for the industry title; shows the band only if a
    substantial, non-disambiguation extract comes back. No match -> no band
    (an honest omission, never a fabricated context).
    """
    global _fetcher
    from terminal_zero.edgar.fetcher import Fetcher
    if _fetcher is None:
        _fetcher = Fetcher()
    title = urllib.parse.quote(name.strip().replace(" ", "_"))
    url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{title}"
    try:
        payload = _fetcher.get(url).json()
    except Exception:
        return None
    extract = (payload.get("extract") or "").strip()
    if len(extract) < 120 or payload.get("type") == "disambiguation":
        return None
    return {"lead": extract,
            "note": f'From the Wikipedia article "{payload.get("title", name)}" · '
                    "CC BY-SA — qualitative context, not a figure of record."}


def _has_data(conn, code: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM observations WHERE subject_id=? LIMIT 1",
        (f"NAICS:{code}",)).fetchone() is not None


def _loaded_industries(conn) -> list[tuple[str, str]]:
    """(code, title) for NAICS subjects already in the store, for quick links."""
    rows = conn.execute(
        "SELECT DISTINCT subject_id FROM observations WHERE subject_id LIKE 'NAICS:%'"
    ).fetchall()
    out = []
    for (sid,) in rows:
        code = sid.split(":", 1)[1]
        out.append((code, _BACKBONE.title(code) or code))
    return sorted(out, key=lambda t: t[1])


PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Terminal Zero</title>
<style>
:root{{color-scheme:dark}}
*{{box-sizing:border-box}}
body{{margin:0;min-height:100vh;background:#0a0e15;color:#e8edf4;
 font-family:"Libre Franklin",system-ui,-apple-system,sans-serif;
 display:flex;flex-direction:column;align-items:center;padding:0 20px}}
.wrap{{width:100%;max-width:640px;text-align:center;padding-top:16vh}}
.glyph{{display:inline-grid;place-items:center;width:34px;height:34px;border-radius:8px;
 background:#1c3f6e;color:#fff;font-family:ui-monospace,monospace;font-weight:600;font-size:19px;
 margin-bottom:22px}}
h1{{font-family:Georgia,"Times New Roman",serif;font-weight:500;font-size:clamp(30px,6vw,48px);
 letter-spacing:-.02em;margin:0 0 8px}}
h1 em{{font-style:italic;color:#7ca6db}}
p.lede{{color:#98a4b5;font-size:16px;margin:0 auto 32px;max-width:44ch;line-height:1.6}}
form{{position:relative;display:flex;gap:8px;background:#121924;border:1px solid #334154;
 border-radius:14px;padding:6px 6px 6px 18px}}
form:focus-within{{border-color:#7ca6db}}
.ac{{position:absolute;left:0;right:0;top:calc(100% + 8px);background:#121924;
 border:1px solid #334154;border-radius:12px;overflow:hidden;display:none;z-index:20;
 text-align:left;box-shadow:0 24px 60px rgba(0,0,0,.5)}}
.ac.open{{display:block}}
.acrow{{display:flex;justify-content:space-between;align-items:center;gap:12px;
 padding:11px 16px;text-decoration:none;color:#e8edf4;border-bottom:1px solid #1b2430}}
.acrow:last-child{{border-bottom:0}}
.acrow:hover,.acrow.hl{{background:#0f1520}}
.acname{{font-size:14.5px}}
.acmeta{{font-family:ui-monospace,monospace;font-size:11.5px;color:#6c7788;white-space:nowrap}}
.acmeta .rdy{{color:#54b7ac}}
input{{flex:1;border:0;background:transparent;color:#e8edf4;font-size:17px;padding:12px 0;outline:none}}
input::placeholder{{color:#6c7788}}
button{{border:0;background:#1c3f6e;color:#fff;font-weight:600;font-size:15px;
 padding:11px 20px;border-radius:9px;cursor:pointer}}
button:hover{{filter:brightness(1.12)}}
.chips{{margin-top:16px;display:flex;gap:8px;flex-wrap:wrap;justify-content:center}}
.chip{{font-family:ui-monospace,monospace;font-size:12.5px;color:#98a4b5;background:#121924;
 border:1px solid #222c3a;border-radius:20px;padding:5px 13px;text-decoration:none}}
.chip:hover{{border-color:#7ca6db;color:#7ca6db}}
.foot{{margin-top:40px;color:#6c7788;font-size:12.5px;line-height:1.6}}
.loaded{{margin-top:44px;text-align:left}}
.loaded h2{{font-family:Georgia,serif;font-weight:500;font-size:15px;color:#98a4b5;
 border-top:1px solid #222c3a;padding-top:22px;margin:0 0 12px}}
.msg{{background:#121924;border:1px solid #334154;border-radius:14px;padding:28px;margin-top:20px;text-align:left}}
.msg b{{color:#7ca6db}}
a.act{{display:inline-block;margin-top:14px;background:#1c3f6e;color:#fff;text-decoration:none;
 font-weight:600;padding:11px 20px;border-radius:9px}}
</style></head><body><div class="wrap">
<span class="glyph">0</span>
<h1>Know an industry<br>by <em>tomorrow morning.</em></h1>
<p class="lede">Type any U.S. industry — a name or a NAICS code. Every figure is pulled live from the store.</p>
<form action="/brief" method="get">
 <input name="q" autofocus autocomplete="off" placeholder="e.g. semiconductors, breweries, 325412…">
 <button type="submit">Open brief</button>
</form>
<div class="chips">{chips}</div>
{body}
<p class="foot">Local engine · {n} industries loaded · resolves any of {total:,} NAICS codes</p>
</div></body></html>"""


AUTOCOMPLETE = """<script>
const input=document.querySelector('input[name=q]');
const box=document.createElement('div');box.className='ac';input.parentElement.appendChild(box);
let items=[],idx=-1,timer;
input.addEventListener('input',()=>{clearTimeout(timer);timer=setTimeout(run,110);});
async function run(){
  const q=input.value.trim();
  if(q.length<2){close();return;}
  try{const r=await fetch('/search?q='+encodeURIComponent(q));items=await r.json();}
  catch(e){items=[];}
  idx=-1;render();
}
function render(){
  if(!items.length){close();return;}
  box.innerHTML=items.map((it,i)=>
    '<a class="acrow'+(i===idx?' hl':'')+'" href="/brief?q='+it.code+'">'+
    '<span class="acname">'+it.title+'</span>'+
    '<span class="acmeta">'+it.code+(it.loaded?' · <span class="rdy">ready</span>':'')+'</span></a>').join('');
  box.classList.add('open');
}
function close(){box.classList.remove('open');box.innerHTML='';idx=-1;}
input.addEventListener('keydown',e=>{
  if(!box.classList.contains('open'))return;
  if(e.key==='ArrowDown'){e.preventDefault();idx=Math.min(idx+1,items.length-1);render();}
  else if(e.key==='ArrowUp'){e.preventDefault();idx=Math.max(idx-1,0);render();}
  else if(e.key==='Enter'&&idx>=0){e.preventDefault();location.href='/brief?q='+items[idx].code;}
  else if(e.key==='Escape'){close();}
});
document.addEventListener('click',e=>{if(!e.target.closest('form'))close();});
</script>"""


def landing(conn, body: str = "") -> str:
    loaded = _loaded_industries(conn)
    chips = "".join(
        f'<a class="chip" href="/brief?q={c}">{html.escape(t)}</a>' for c, t in loaded[:8])
    page = PAGE.format(chips=chips, body=body, n=len(loaded), total=len(_BACKBONE))
    return page.replace("</body>", AUTOCOMPLETE + "</body>")


def not_loaded_page(conn, code: str, title: str) -> str:
    body = (f'<div class="msg"><b>{html.escape(title)}</b> (NAICS {code}) isn\'t in the store yet. '
            f'Pull it live from every mapped source — takes ~20–40s.'
            f'<br><a class="act" href="/refresh?q={code}">Pull it live &rarr;</a></div>')
    return landing(conn, body)


def unresolved_page(conn, q: str) -> str:
    body = (f'<div class="msg">Couldn\'t resolve <b>{html.escape(q)}</b> to a NAICS industry. '
            f'Try a clearer name or a NAICS code (e.g. 334413).</div>')
    return landing(conn, body)


class Handler(BaseHTTPRequestHandler):
    def _send(self, body: str, status: int = 200):
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_json(self, obj):
        data = json.dumps(obj).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        q = (urllib.parse.parse_qs(parsed.query).get("q") or [""])[0].strip()
        conn = connect()

        if parsed.path == "/":
            return self._send(landing(conn))

        if parsed.path == "/search":
            loaded = {c for c, _ in _loaded_industries(conn)}
            results = [
                {"code": n.code, "title": n.title, "level": n.level,
                 "loaded": n.code in loaded}
                for n in _BACKBONE.search(q, limit=8)]
            return self._send_json(results)

        if parsed.path == "/brief":
            m = registry.mapping_for(q)
            if not m:
                return self._send(unresolved_page(conn, q))
            code = m.naics[0]
            if not _has_data(conn, code):
                return self._send(not_loaded_page(conn, code, m.name))
            return self._send(brief.render(
                conn, code, f"U.S. {m.name.title()}",
                bea_industry=m.bea[0] if m.bea else None, bea_note=m.bea_note,
                hs=m.hs[0] if m.hs else None, bfs=m.bfs, nass=m.nass or None,
                context=_wiki_context(m.name)))

        if parsed.path == "/refresh":
            m = registry.mapping_for(q)
            if not m:
                return self._send(unresolved_page(conn, q))
            code = m.naics[0]
            # Reuse the tested refresh path exactly; inherits env (keys) from us.
            subprocess.run([sys.executable, "scripts/refresh.py", code],
                           cwd=str(config.ROOT), env={**__import__("os").environ, "PYTHONPATH": "."},
                           timeout=180)
            # Redirect back to the brief now that data is loaded.
            self.send_response(303)
            self.send_header("Location", f"/brief?q={code}")
            self.end_headers()
            return

        self._send("not found", 404)

    def log_message(self, *a):
        pass


def main():
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"Terminal Zero engine live at http://localhost:{PORT}")
    print("Ctrl-C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
