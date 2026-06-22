"""MOLGANG knowledge-graph **explorer** — a stdlib HTTP server at :8990.

A read-only lens on the *state* of the woven p2p web. It loads a knitweb `gateway.App`
store dump (the woven web on disk, e.g. ``/tmp/chem_web.json``) — or, alternatively, the
molgang shared world (``~/.molgang/world.json``) — into a `networkx.DiGraph` via
``molgang.graphx`` and serves an interactive single-page explorer plus a small JSON API:

    GET  /                                  the interactive single-page UI
    GET  /api/kg/stats                      nodes/edges/clusters/density + per-language label counts
    GET  /api/kg/hubs                       top terms by degree + centrality (NetworkX)
    GET  /api/kg/tension                    fiber-tension stats: per-band edge counts + avg tautness/cost
    GET  /api/kg/neighbors?term=            in/out neighbours (with relations)
    GET  /api/kg/path?from=&to=             shortest path between two terms
    GET  /api/kg/concept?key=               a concept's 4 language labels (en/ru/zh/ar) + relations
    GET  /api/kg/subgraph?term=&depth=2     a focused subgraph (nodes+edges) for the viz
    GET  /api/kg/names                      all node names (for the UI type-ahead datalist)

Term lookups (neighbors/path/concept/subgraph) resolve **case-insensitively** (trimmed +
casefolded), so ``v2o5`` / ``" V2O5 "`` / ``V2o5`` all hit the node ``V2O5``. On a miss the
API returns ``{"missing":[…], "suggestions":[…]}`` (substring/prefix node-name matches) so
the UI can offer "did you mean …".

    PYTHONPATH=src:/tmp/knitweb-py/src python3 -m molgang.explorer --web /tmp/chem_web.json --port 8990

The graph is built once at boot from ``--web`` (a gateway.App store) or ``--world`` (a
molgang world.json). If neither is present a tiny sample web is generated so the server
still boots. The viz never renders the whole 2600-node web at once: it centres on a
searched term / top hub and expands focused subgraphs on click, so it stays interactive.
"""

from __future__ import annotations

import argparse
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import graphx

DEFAULT_WEB = "/tmp/chem_web.json"
DEFAULT_WORLD = os.path.expanduser("~/.molgang/world.json")


def _world_to_store(path: str) -> dict:
    """Convert a molgang world.json (``{items:[WovenItem,…]}``) to a gateway.App store dump."""
    with open(os.path.expanduser(path), encoding="utf-8") as fh:
        data = json.load(fh)
    records: list[dict] = []
    seen_terms: set[str] = set()

    def term_record(t: str) -> None:
        if t and t not in seen_terms:
            seen_terms.add(t)
            records.append({"t": "record", "data": {"kind": "term", "key": t}})

    for it in data.get("items", []):
        kind = it.get("kind", "term")
        conf = max(1, it.get("confirmations", 1) or 1)
        if kind == "link":
            term_record(it.get("subject", ""))
            term_record(it.get("object", ""))
            records.append({"t": "link", "subject": it.get("subject"), "object": it.get("object"),
                            "relation": it.get("relation") or "links", "weight": conf})
        elif kind == "spiral":
            for pl in it.get("links", []):
                term_record(pl.get("subject", ""))
                term_record(pl.get("object", ""))
                records.append({"t": "link", "subject": pl.get("subject"), "object": pl.get("object"),
                                "relation": pl.get("relation") or "links", "weight": conf})
        else:
            term_record(it.get("term", ""))
    return {"name": "molgang-world", "balances": {}, "records": records}


def load_graph(web: str | None = None, world: str | None = None):
    """Build the DiGraph from a gateway.App store (``web``) or molgang world (``world``).

    Falls back, in order: explicit ``web`` → explicit ``world`` → DEFAULT_WEB →
    DEFAULT_WORLD → a tiny built-in sample (so the server always boots). Returns
    ``(graph, source_label)``.
    """
    if web and os.path.exists(os.path.expanduser(web)):
        return graphx.load_web(web), os.path.expanduser(web)
    if world and os.path.exists(os.path.expanduser(world)):
        return graphx.build_from_web(_world_to_store(world)), os.path.expanduser(world)
    if web is None and world is None:
        if os.path.exists(DEFAULT_WEB):
            return graphx.load_web(DEFAULT_WEB), DEFAULT_WEB
        if os.path.exists(DEFAULT_WORLD):
            return graphx.build_from_web(_world_to_store(DEFAULT_WORLD)), DEFAULT_WORLD
    return graphx.build_from_web(graphx.sample_web()), "sample (built-in)"


def make_handler(g, source: str):
    class Handler(BaseHTTPRequestHandler):
        def _json(self, code: int, obj) -> None:
            body = json.dumps(obj, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _html(self, body: str) -> None:
            b = body.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def do_GET(self) -> None:
            p = urlparse(self.path)
            path, q = p.path, parse_qs(p.query)
            if path in ("/", ""):
                return self._html(PAGE)
            if path == "/api/kg/stats":
                s = graphx.web_stats(g)
                s["source"] = source
                return self._json(200, s)
            if path == "/api/kg/hubs":
                n = int((q.get("n") or ["12"])[0])
                return self._json(200, {"hubs": graphx.centrality_hubs(g, n)})
            if path == "/api/kg/tension":
                return self._json(200, graphx.tension_stats(g))
            if path == "/api/kg/names":
                limit = int((q.get("limit") or ["0"])[0]) or None
                return self._json(200, {"names": graphx.node_names(g, limit)})
            if path == "/api/kg/neighbors":
                term = (q.get("term") or [""])[0]
                nb = graphx.neighbors(g, term)
                if nb is None:
                    return self._json(404, {"error": f"term not in graph: {term!r}",
                                            "missing": [term],
                                            "suggestions": graphx.suggest(g, term)})
                return self._json(200, nb)
            if path == "/api/kg/path":
                frm, to = (q.get("from") or [""])[0], (q.get("to") or [""])[0]
                res = graphx.path(g, frm, to)
                if res is None:
                    missing = [t for t in (frm, to) if graphx.resolve(g, t) is None]
                    suggestions = sorted({s for t in missing for s in graphx.suggest(g, t)})
                    return self._json(404, {"error": "term(s) not in graph",
                                            "missing": missing, "suggestions": suggestions})
                return self._json(200, res)
            if path == "/api/kg/concept":
                key = (q.get("key") or [""])[0]
                c = graphx.concept(g, key)
                if c is None:
                    return self._json(404, {"error": f"concept not in graph: {key!r}",
                                            "missing": [key],
                                            "suggestions": graphx.suggest(g, key)})
                return self._json(200, c)
            if path == "/api/kg/subgraph":
                term = (q.get("term") or [""])[0]
                depth = int((q.get("depth") or ["2"])[0])
                langs = q.get("lang")
                langset = set(langs) if langs else None
                sg = graphx.subgraph(g, term, depth, langs=langset)
                if sg is None:
                    return self._json(404, {"error": f"term not in graph: {term!r}",
                                            "missing": [term],
                                            "suggestions": graphx.suggest(g, term)})
                return self._json(200, sg)
            return self._json(404, {"error": "not found"})

        def log_message(self, *args) -> None:
            pass

    return Handler


# -- the interactive single-page UI (self-contained, vis-network via CDN) ----
PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>MOLGANG — knowledge-graph explorer</title>
<script src="https://unpkg.com/vis-network@9.1.6/standalone/umd/vis-network.min.js"></script>
<style>
:root{
  --bg:#070912; --bg2:#0b1020; --panel:rgba(22,28,42,.78); --line:rgba(120,140,180,.20);
  --ink:#eaf1fb; --dim:#93a3bd; --accent:#8b5cff; --accent2:#22e3ff; --accent3:#ff5cf0;
  --ok:#34f5b0; --gold:#ffd24a; --radius:16px;
}
*{box-sizing:border-box}
body{margin:0;height:100vh;display:flex;flex-direction:column;color:var(--ink);
  font:14px/1.5 -apple-system,Segoe UI,Inter,Helvetica,Arial,sans-serif;
  background:radial-gradient(1100px 620px at 78% -12%,rgba(139,92,255,.18),transparent 60%),
    radial-gradient(900px 560px at 8% 8%,rgba(34,227,255,.12),transparent 55%),
    linear-gradient(180deg,var(--bg2),var(--bg));overflow:hidden}
header{display:flex;align-items:center;gap:14px;padding:10px 18px;border-bottom:1px solid var(--line);
  flex-wrap:wrap}
header b{color:#fff}.dim{color:var(--dim)}.mono{font-family:SFMono-Regular,Menlo,monospace}
.brand{font-size:16px;font-weight:700}
main{flex:1;display:flex;min-height:0}
#side{width:340px;min-width:340px;border-right:1px solid var(--line);overflow:auto;padding:14px;
  display:flex;flex-direction:column;gap:14px;background:rgba(11,16,32,.5)}
#graph{flex:1;min-width:0;position:relative}
#net{position:absolute;inset:0}
.card{background:var(--panel);border:1px solid var(--line);border-radius:var(--radius);padding:12px}
.card h3{margin:0 0 8px;font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:var(--dim)}
input,select{width:100%;padding:9px 11px;border-radius:11px;border:1px solid var(--line);
  background:rgba(7,9,18,.7);color:var(--ink);font:inherit;outline:none}
input:focus,select:focus{border-color:var(--accent2)}
button{cursor:pointer;border:0;border-radius:11px;padding:9px 13px;font:inherit;font-weight:700;color:#fff;
  background:linear-gradient(135deg,var(--accent),var(--accent3));white-space:nowrap}
button.ghost{background:rgba(255,255,255,.06);border:1px solid var(--line)}
.row{display:flex;gap:8px}.row>*{flex:1}
.stat{display:flex;justify-content:space-between;padding:3px 0;border-bottom:1px dashed rgba(120,140,180,.12)}
.stat b{color:var(--accent2)}
.lang{display:inline-flex;align-items:center;gap:6px;padding:5px 9px;border-radius:9px;
  border:1px solid var(--line);cursor:pointer;user-select:none;font-weight:700;background:rgba(7,9,18,.5)}
.lang.on{border-color:var(--accent2);box-shadow:0 0 12px rgba(34,227,255,.4);background:rgba(34,227,255,.1)}
.langs{display:flex;gap:8px;flex-wrap:wrap}
.hub{display:flex;justify-content:space-between;gap:8px;padding:5px 7px;border-radius:9px;cursor:pointer}
.hub:hover{background:rgba(139,92,255,.16)}
.hub .deg{color:var(--gold);font-weight:700}
.pill{display:inline-block;padding:1px 7px;border-radius:99px;background:rgba(34,227,255,.14);
  color:var(--accent2);font-size:11px;margin:2px 3px 0 0}
.rel{color:var(--accent3)}
.rtl{direction:rtl;text-align:right;font-size:18px}
#detail{font-size:13px}
#detail .lbl{display:flex;justify-content:space-between;padding:4px 0;border-bottom:1px dashed rgba(120,140,180,.12)}
#detail .lbl .v{font-weight:700}
.muted{color:var(--dim);font-size:12px}
.suggest{margin-top:7px;font-size:12px}.suggest:empty{display:none}
.suggest .lead{color:var(--dim);margin-right:4px}
.suggest a{display:inline-block;padding:2px 8px;margin:2px 4px 0 0;border-radius:99px;
  border:1px solid var(--line);background:rgba(34,227,255,.10);color:var(--accent2);
  text-decoration:none;font-weight:700;cursor:pointer}
.suggest a:hover{border-color:var(--accent2);box-shadow:0 0 10px rgba(34,227,255,.35)}
.legend{position:absolute;left:12px;bottom:12px;background:var(--panel);border:1px solid var(--line);
  border-radius:11px;padding:8px 10px;font-size:12px;z-index:5}
.legend span{display:inline-flex;align-items:center;gap:5px;margin-right:10px}
.dot{width:11px;height:11px;border-radius:50%;display:inline-block}
</style>
</head>
<body>
<header>
  <div class="brand">🕸 <b>MOLGANG</b> <span class="dim">· knowledge-graph explorer</span></div>
  <div id="src" class="dim mono" style="font-size:12px"></div>
</header>
<main>
  <div id="side">
    <div class="card">
      <h3>Search a term</h3>
      <div class="row">
        <input id="q" list="names" autocomplete="off" placeholder="e.g. H2O, oxygen, V2O5" />
        <button onclick="focusTerm(document.getElementById('q').value.trim())" style="flex:0 0 auto">Go</button>
      </div>
      <div id="qsugg" class="suggest"></div>
      <div class="muted" style="margin-top:6px">Case-insensitive — <span class="mono">v2o5</span> finds <span class="mono">V2O5</span>. Renders a focused subgraph (expand on click).</div>
    </div>
    <datalist id="names"></datalist>

    <div class="card">
      <h3>Languages</h3>
      <div class="langs" id="langs">
        <span class="lang on" data-l="en">🇬🇧 EN</span>
        <span class="lang on" data-l="ru">🇷🇺 RU</span>
        <span class="lang on" data-l="zh">🇨🇳 ZH</span>
        <span class="lang on" data-l="ar">🇸🇦 AR</span>
      </div>
      <div class="muted" style="margin-top:6px">Filter <span class="mono">label:&lt;lang&gt;</span> edges. Arabic shown RTL.</div>
    </div>

    <div class="card">
      <h3>Shortest path</h3>
      <div class="row"><input id="pf" list="names" autocomplete="off" placeholder="from (H2O)"/><input id="pt" list="names" autocomplete="off" placeholder="to (oxygen)"/></div>
      <button class="ghost" style="margin-top:8px;width:100%" onclick="findPath()">Find path</button>
      <div id="pathout" class="muted" style="margin-top:8px"></div>
      <div id="pathsugg" class="suggest"></div>
    </div>

    <div class="card">
      <h3>Stats</h3>
      <div id="stats" class="muted">loading…</div>
    </div>

    <div class="card">
      <h3>Fiber tension</h3>
      <div id="tension" class="muted">loading…</div>
    </div>

    <div class="card">
      <h3>Top hubs</h3>
      <div id="hubs" class="muted">loading…</div>
    </div>

    <div class="card" id="detailCard" style="display:none">
      <h3>Concept</h3>
      <div id="detail"></div>
    </div>
  </div>

  <div id="graph">
    <div id="net"></div>
    <div class="legend">
      <span><span class="dot" style="background:#ffd24a"></span>centre</span>
      <span><span class="dot" style="background:#8b5cff"></span>concept</span>
      <span><span class="dot" style="background:#22e3ff"></span>label</span>
      <br/>
      <span class="dim" style="margin-right:6px">fiber tension:</span>
      <span><span class="dot" style="background:#22e3ff"></span>taut</span>
      <span><span class="dot" style="background:#ff5cf0"></span>neutral</span>
      <span><span class="dot" style="background:#6b7689"></span>slack</span>
      <span><span class="dot" style="background:#ff7a18"></span>contested</span>
    </div>
  </div>
</main>

<script>
const LANGS = ["en","ru","zh","ar"];
let net=null, nodes=null, edges=null, expanded=new Set();

function activeLangs(){
  return [...document.querySelectorAll('.lang.on')].map(e=>e.dataset.l);
}
document.querySelectorAll('.lang').forEach(el=>el.onclick=()=>{
  el.classList.toggle('on');
  if(currentCenter) focusTerm(currentCenter); // re-render with the new filter
});

async function j(url){ const r=await fetch(url); return {ok:r.ok, data: await r.json()}; }

async function loadStats(){
  const {data}=await j('/api/kg/stats');
  document.getElementById('src').textContent = '⛓ '+ (data.source||'');
  const L=data.languages||{};
  document.getElementById('stats').innerHTML =
    `<div class="stat"><span>nodes</span><b>${data.nodes}</b></div>`+
    `<div class="stat"><span>edges</span><b>${data.edges}</b></div>`+
    `<div class="stat"><span>concepts</span><b>${data.concepts}</b></div>`+
    `<div class="stat"><span>clusters</span><b>${data.clusters}</b></div>`+
    `<div class="stat"><span>density</span><b>${data.density}</b></div>`+
    `<div style="margin-top:8px" class="muted">label edges per language</div>`+
    LANGS.map(l=>`<div class="stat"><span>${l.toUpperCase()}</span><b>${L[l]||0}</b></div>`).join('');
}

async function loadTension(){
  const {data}=await j('/api/kg/tension');
  const b=data.bands||{};
  const swatch=c=>`<span class="dot" style="background:${c};margin-right:5px"></span>`;
  document.getElementById('tension').innerHTML =
    `<div class="stat"><span>${swatch('#22e3ff')}taut</span><b>${b.taut||0}</b></div>`+
    `<div class="stat"><span>${swatch('#ff5cf0')}neutral</span><b>${b.neutral||0}</b></div>`+
    `<div class="stat"><span>${swatch('#6b7689')}slack</span><b>${b.slack||0}</b></div>`+
    `<div class="stat"><span>${swatch('#ff7a18')}contested</span><b>${b.contested||0}</b></div>`+
    `<div class="stat"><span>avg tautness</span><b>${data.avg_tautness} / ${(data.thresholds||{}).scale||1000}</b></div>`+
    `<div class="stat"><span>avg cost</span><b>${data.avg_cost}</b></div>`+
    `<div class="muted" style="margin-top:6px">taut = low cost (preferred) · slack = high cost · contested → snap</div>`;
}

async function loadHubs(){
  const {data}=await j('/api/kg/hubs?n=14');
  document.getElementById('hubs').innerHTML = (data.hubs||[]).map(h=>
    `<div class="hub" onclick="focusTerm('${h.term.replace(/'/g,"\\'")}')">`+
    `<span>${h.concept?'🔵 ':''}${esc(h.term)}</span><span class="deg">${h.degree}</span></div>`).join('');
}

function esc(s){const d=document.createElement('div');d.textContent=s==null?'':s;return d.innerHTML;}

// render clickable "did you mean: …" suggestions into a box; onPick re-runs the search
function renderSuggest(box, suggestions, onPick){
  box.innerHTML='';
  if(!suggestions || !suggestions.length) return;
  let html='<span class="lead">did you mean:</span>';
  html += suggestions.map(s=>`<a href="#" data-t="${esc(s)}">${esc(s)}</a>`).join('');
  box.innerHTML=html;
  box.querySelectorAll('a').forEach(a=>a.onclick=(e)=>{ e.preventDefault(); onPick(a.dataset.t); });
}

let currentCenter=null;
async function focusTerm(term){
  if(!term) return;
  const sugg=document.getElementById('qsugg');
  const {ok,data}=await j('/api/kg/subgraph?depth=2&term='+encodeURIComponent(term)
    + activeLangs().map(l=>'&lang='+l).join(''));
  if(!ok){
    document.getElementById('q').value=term;
    renderSuggest(sugg, data.suggestions, t=>{ document.getElementById('q').value=t; focusTerm(t); });
    document.getElementById('pathout').textContent =
      (data.suggestions && data.suggestions.length) ? '' : (data.error||'not found');
    return;
  }
  sugg.innerHTML='';
  currentCenter=data.center;               // the *resolved* node (e.g. V2O5 for "v2o5")
  document.getElementById('q').value=data.center;
  expanded=new Set([data.center]);
  render(data);
  showConcept(data.center);
}

function nodeStyle(n){
  if(n.center) return {color:{background:'#ffd24a',border:'#fff'},font:{color:'#fff',size:18}};
  if(n.concept) return {color:{background:'#8b5cff',border:'#c4b5ff'},font:{color:'#eaf1fb'}};
  return {color:{background:'#123', border:'#22e3ff'},font:{color:'#bfe9f5'},shape:'box'};
}
function isAr(label){ return /[؀-ۿ]/.test(label); }

// fiber-tension visual: colour + width by the edge's taut/slack/snapped state
const TENSION_COLOR = {taut:'#22e3ff', neutral:'#ff5cf0', slack:'#6b7689', contested:'#ff7a18'};
function tensionStyle(e){
  const band = e.tension_band || 'neutral';
  // width scales with tautness (taut = thick conductor; slack = thin wobble)
  const taut = (typeof e.tautness === 'number') ? e.tautness : 500;
  const width = 1 + Math.round(taut/250);          // 1..5px, integer-ish
  return {color: TENSION_COLOR[band] || '#ff5cf0', width,
          dashes: band==='slack' || band==='contested'};
}

function render(sg){
  nodes=new vis.DataSet(sg.nodes.map(n=>({
    id:n.id, label:n.id, title:(n.definition||'')+(n.formula?(' ['+n.formula+']'):''),
    ...nodeStyle(n), font:{...(nodeStyle(n).font||{}), face: isAr(n.id)?'Tahoma':undefined}
  })));
  edges=new vis.DataSet(sg.edges.map((e,i)=>{
    const ts=tensionStyle(e);
    return {
      id:i, from:e.from, to:e.to, label:e.relation, arrows:'to',
      width: ts.width, dashes: ts.dashes,
      title:'tension: '+(e.tension_band||'neutral')+' · tautness '+(e.tautness??'?')+' · cost '+(e.cost??'?'),
      color:{color: ts.color, opacity:0.7},
      font:{color:'#7e8aa8',size:10,strokeWidth:0,align:'middle'},
    };
  }));
  if(!net){
    net=new vis.Network(document.getElementById('net'), {nodes,edges}, {
      physics:{stabilization:{iterations:160}, barnesHut:{springLength:130,avoidOverlap:.4}},
      interaction:{hover:true, tooltipDelay:120},
      nodes:{shape:'dot',size:15,borderWidth:2},
      edges:{smooth:{type:'continuous'}}
    });
    net.on('click', p=>{ if(p.nodes.length) onNode(p.nodes[0]); });
    net.on('doubleClick', p=>{ if(p.nodes.length) expand(p.nodes[0]); });
  } else {
    net.setData({nodes,edges});
  }
}

async function onNode(id){ showConcept(id); }

async function expand(id){
  if(expanded.has(id)) { showConcept(id); return; }
  expanded.add(id);
  const langs=activeLangs(); const lq=langs.map(l=>'&lang='+l).join('');
  const {ok,data}=await j('/api/kg/subgraph?depth=1&term='+encodeURIComponent(id)+lq);
  if(!ok) return;
  data.nodes.forEach(n=>{ if(!nodes.get(n.id)) nodes.add({id:n.id,label:n.id,...nodeStyle({...n,center:false})}); });
  let mx=edges.length;
  data.edges.forEach(e=>{ const ts=tensionStyle(e); edges.add({id:'x'+(mx++), from:e.from,to:e.to,label:e.relation,arrows:'to',
    width:ts.width, color:{color:ts.color,opacity:.65}, dashes:ts.dashes,
    title:'tension: '+(e.tension_band||'neutral')+' · tautness '+(e.tautness??'?'),
    font:{color:'#7e8aa8',size:10}}); });
}

async function showConcept(key){
  const {ok,data}=await j('/api/kg/concept?key='+encodeURIComponent(key));
  const card=document.getElementById('detailCard'), box=document.getElementById('detail');
  if(!ok){ card.style.display='none'; return; }
  card.style.display='block';
  const L=data.labels||{};
  let html=`<div style="font-weight:700;font-size:15px">${esc(data.key)}</div>`;
  if(data.formula) html+=`<div class="muted mono">formula: ${esc(data.formula)}</div>`;
  if(data.definition) html+=`<div class="muted" style="margin:6px 0">${esc(data.definition)}</div>`;
  html+=`<div style="margin-top:8px">`+
    `<div class="lbl"><span>🇬🇧 EN</span><span class="v">${esc(L.en)||'—'}</span></div>`+
    `<div class="lbl"><span>🇷🇺 RU</span><span class="v">${esc(L.ru)||'—'}</span></div>`+
    `<div class="lbl"><span>🇨🇳 ZH</span><span class="v">${esc(L.zh)||'—'}</span></div>`+
    `<div class="lbl"><span>🇸🇦 AR</span><span class="v rtl">${esc(L.ar)||'—'}</span></div></div>`;
  const rels=(data.relations||[]).concat(data.incoming||[]);
  if(rels.length){
    html+=`<div class="muted" style="margin-top:8px">relations (double-click a node to expand)</div>`;
    html+=rels.slice(0,40).map(r=> r.dir==='out'
      ? `<span class="pill"><span class="rel">${esc(r.relation)}</span> → <a href="#" onclick="focusTerm('${(r.to||'').replace(/'/g,"\\'")}');return false">${esc(r.to)}</a></span>`
      : `<span class="pill"><a href="#" onclick="focusTerm('${(r.from||'').replace(/'/g,"\\'")}');return false">${esc(r.from)}</a> <span class="rel">${esc(r.relation)}</span> →</span>`
    ).join('');
  }
  box.innerHTML=html;
}

async function findPath(){
  const f=document.getElementById('pf').value.trim(), t=document.getElementById('pt').value.trim();
  if(!f||!t) return;
  const out=document.getElementById('pathout'), sugg=document.getElementById('pathsugg');
  const {ok,data}=await j('/api/kg/path?from='+encodeURIComponent(f)+'&to='+encodeURIComponent(t));
  if(!ok){
    out.innerHTML='<span style="color:#ff6f93">'+esc((data.missing||[]).join(', ')||data.error)+' not in graph</span>';
    // clicking a suggestion fills whichever box is still unresolved, then retries
    renderSuggest(sugg, data.suggestions, x=>{
      const miss=data.missing||[];
      if(miss.length && f.toLowerCase()===String(miss[0]).toLowerCase()) document.getElementById('pf').value=x;
      else document.getElementById('pt').value=x;
      findPath();
    });
    return;
  }
  sugg.innerHTML='';
  if(!data.path){ out.innerHTML='<span style="color:#ff6f93">no path</span>'; return; }
  out.innerHTML='<b style="color:var(--ok)">'+data.hops+' hops</b>: '+data.path.map(esc).join(' <span class="rel">→</span> ');
  document.getElementById('pf').value=data.from; document.getElementById('pt').value=data.to;
  focusTerm(data.from);
}

document.getElementById('q').addEventListener('keydown',e=>{ if(e.key==='Enter') focusTerm(e.target.value.trim()); });

async function loadNames(){
  const {data}=await j('/api/kg/names');
  const dl=document.getElementById('names');
  dl.innerHTML=(data.names||[]).map(n=>`<option value="${esc(n)}"></option>`).join('');
}

(async function init(){
  await loadStats(); await loadTension(); await loadHubs(); await loadNames();
  const {data}=await j('/api/kg/hubs?n=1');
  if(data.hubs && data.hubs.length) focusTerm(data.hubs[0].term);
})();
</script>
</body>
</html>"""


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="MOLGANG knowledge-graph explorer (:8990)")
    ap.add_argument("--port", type=int, default=8990)
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--web", default=None,
                    help=f"gateway.App store JSON (the woven web; default {DEFAULT_WEB} if present)")
    ap.add_argument("--world", default=None,
                    help=f"alternate source: molgang world.json (default {DEFAULT_WORLD} if present)")
    a = ap.parse_args([x for x in argv[1:] if x != "explore"])

    g, source = load_graph(a.web, a.world)
    s = graphx.web_stats(g)
    srv = ThreadingHTTPServer((a.host, a.port), make_handler(g, source))
    print(f"  🕸 MOLGANG knowledge-graph explorer at http://localhost:{a.port}")
    print(f"     source: {source}")
    print(f"     graph: {s['nodes']} nodes · {s['edges']} edges · {s['concepts']} concepts · "
          f"languages {s['languages']}")
    print("     (Ctrl-C to stop)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n  explorer closed.")
    return 0


if __name__ == "__main__":
    import sys

    raise SystemExit(main(sys.argv))
