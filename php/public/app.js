"use strict";
// MOLGANG bar — vanilla JS client (dapp build). Polls /api/state and renders the bar,
// your ledger, and the explorer. Same API a bot would drive. Path-prefix-safe.

const $ = (id) => document.getElementById(id);
// Works whether served at the root or under a subpath like https://5mart.ml/molgang/.
const BASE = location.pathname.replace(/\/(index\.html)?$/, "");
const api = async (path, method = "GET", body = null) => {
  const r = await fetch(BASE + path, {
    method,
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : null,
  });
  return r.json();
};

const avatarImg = (id, cls = "av-img") => `<img class="${cls}" src="avatars/${id}.svg" alt="" />`;

let sid = localStorage.getItem("molgang_sid") || null;
let chosenAvatar = null;
let view = "bar";
let table = localStorage.getItem("molgang_table") || null;
let refreshTimer = null;

// a stable per-device id → the same PLS wallet every visit (shared with the desktop app)
const DEVICE_ID = (() => {
  let d = localStorage.getItem("molgang_device");
  if (!d) {
    d = (window.crypto && crypto.randomUUID) ? crypto.randomUUID()
      : "dev-" + Math.random().toString(36).slice(2) + Date.now().toString(36);
    localStorage.setItem("molgang_device", d);
  }
  return d;
})();

// ---- walk-in ----
async function boot() {
  const avs = (await api("/api/state")).avatars || [];
  $("avatars").innerHTML = "";
  avs.forEach((a, i) => {
    const b = document.createElement("button");
    b.className = "av-pick" + (i === 0 ? " sel" : "");
    b.title = a.name;
    b.innerHTML = `<img src="avatars/${a.id}.svg" alt="${a.name}" /><span>${a.name}</span>`;
    b.onclick = () => {
      chosenAvatar = a.id;
      document.querySelectorAll(".av-pick").forEach((x) => x.classList.remove("sel"));
      b.classList.add("sel");
    };
    $("avatars").appendChild(b);
  });
  chosenAvatar = avs[0].id;
  $("go").onclick = walkIn;
  if (sid) { $("enter").classList.add("hidden"); start(); }
}

async function walkIn() {
  const name = $("name").value.trim() || "guest";
  const res = await api("/api/join", "POST", { name, avatar: chosenAvatar, device: DEVICE_ID });
  sid = res.sid; localStorage.setItem("molgang_sid", sid);
  $("enter").classList.add("hidden");
  start();
}

function start() {
  $("me").classList.remove("hidden");
  $("tabs").classList.remove("hidden");
  document.querySelectorAll("#tabs button").forEach((b) => {
    b.onclick = () => { view = b.dataset.view; setActiveTab(); refresh(); };
  });
  setActiveTab();
  refresh();
  if (refreshTimer) clearInterval(refreshTimer);
  refreshTimer = setInterval(refresh, 1500);
}

function resetSession() {
  sid = null;
  table = null;
  localStorage.removeItem("molgang_sid");
  localStorage.removeItem("molgang_table");
  if (refreshTimer) clearInterval(refreshTimer);
  refreshTimer = null;
  $("me").classList.add("hidden");
  $("tabs").classList.add("hidden");
  ["floor", "table", "ledger", "explorer", "web"].forEach((v) => $(v).classList.add("hidden"));
  $("enter").classList.remove("hidden");
}

function setActiveTab() {
  document.querySelectorAll("#tabs button").forEach((b) =>
    b.classList.toggle("active", b.dataset.view === view));
  ["floor", "table", "ledger", "explorer", "web"].forEach((v) => $(v).classList.add("hidden"));
  if (view === "ledger") $("ledger").classList.remove("hidden");
  else if (view === "explorer") $("explorer").classList.remove("hidden");
  else if (view === "web") $("web").classList.remove("hidden");
  else $(table ? "table" : "floor").classList.remove("hidden");
}

// ---- render ----
async function refresh() {
  const s = await api("/api/state?sid=" + encodeURIComponent(sid));
  renderPulseHost(s.pulse_host);
  renderPresence(s.peers);
  if (sid && !s.you) {
    resetSession();
    return;
  }
  if (s.you) {
    $("me-av").innerHTML = avatarImg(s.you.avatar);
    $("me-name").textContent = s.you.name;
    if (s.you.address) {
      $("me-wallet").textContent = "👛 " + s.you.address.slice(0, 10) + "…";
      $("me-wallet").title = "your device wallet: " + s.you.address;
    }
    $("me-pulses").textContent = s.you.pulses;
    $("me-silk").textContent = s.you.silk;
    $("me-knits").textContent = s.you.knits_made;
    $("me-level").textContent = "L" + s.you.level;
    $("me-title").textContent = s.you.title;
    table = s.you.table; localStorage.setItem("molgang_table", table || "");
  }
  $("bar-woven").textContent = s.bar_woven;
  if (view === "ledger") renderLedger(s.my_knits);
  else if (view === "explorer") renderExplorer(s.explorer);
  else if (view === "web") renderWeb(await api("/api/web"));
  else if (table) renderTable(s);
  else renderFloor(s);
  setActiveTab();
}

function renderPulseHost(host) {
  if (!host || !host.account) { $("pulse-host").textContent = ""; return; }
  const addr = host.account.address || "";
  const bal = host.account.balance_pls || 0;
  $("pulse-host").textContent = `Pulse host ${addr.slice(0, 10)}… · ${bal} PLS`;
  $("pulse-host").title = `${addr}\nwallet: ${host.wallet || ""}`;
}

// Cross-client awareness: show whether the DESKTOP app is live / was used before (this is the
// browser, so we surface the *other* client). The desktop reads the same /api/presence to see us.
function renderPresence(peers) {
  const el = $("presence");
  if (!el || !peers || !peers.desktop) { if (el) el.textContent = ""; return; }
  const d = peers.desktop;
  if (d.active) {
    el.textContent = "🖥️ desktop active";
    el.style.color = "#3fb950";
  } else if (d.used_before) {
    const ago = d.last_seen ? Math.round((Date.now() / 1000 - d.last_seen) / 60) : null;
    el.textContent = "🖥️ desktop seen" + (ago != null ? ` ${ago}m ago` : " before");
    el.style.color = "";
  } else {
    el.textContent = "";
  }
  el.title = "same wallet on the desktop app — " + JSON.stringify(peers);
}

function renderFloor(s) {
  const f = $("floor"); f.innerHTML = "";
  s.tables.forEach((t) => {
    const card = document.createElement("div");
    card.className = "table-card";
    const chairs = Array.from({ length: t.seats }, (_, i) => {
      const occ = t.seated[i];
      return `<span class="chair ${occ ? "occ" : ""}" title="${occ ? occ.name : "empty"}">${occ ? avatarImg(occ.avatar, "chair-av") : "·"}</span>`;
    }).join("");
    card.innerHTML = `<h3>${t.name}</h3>
      <div class="chairs">${chairs}</div>
      <div class="dim small">${t.seated.length}/${t.seats} seated · ${t.fabric.length} woven</div>
      <button class="join-table">take a seat →</button>`;
    card.querySelector(".join-table").onclick = async () => {
      await api("/api/sit", "POST", { sid, table: t.id });
      table = t.id; view = "bar"; refresh();
    };
    f.appendChild(card);
  });
}

function renderTable(s) {
  const t = s.tables.find((x) => x.id === table);
  if (!t) { table = null; return; }
  $("table-name").textContent = "🍸 " + t.name;
  $("seats").innerHTML = t.seated.map((p) =>
    `<div class="seat ${p.you ? "you" : ""}">${avatarImg(p.avatar, "seat-av")}
      <div><b>${p.name}</b><br><span class="dim small">L${p.level} ${p.title} · ${p.woven}🧬</span></div></div>`).join("");
  $("leave-table").onclick = () => { table = null; setActiveTab(); };
  $("knit").onclick = async () => {
    const term = $("term").value.trim();
    if (!term) return;
    const r = await api("/api/propose", "POST", { sid, term });
    if (r.error) alert(r.error); else $("term").value = "";
    refresh();
  };
  $("suggest").innerHTML = "try: " + ["H2O","CO2","NaCl","CH4","NH3"].map((x) =>
    `<button class="chip" onclick="document.getElementById('term').value='${x}'">${x}</button>`).join("");
  $("open").innerHTML = t.open.length ? t.open.map((p) => {
    const v = p.votes;
    const buttons = (p.mine || p.voted) ? `<span class="dim small">${p.mine ? "your knit" : "voted ✓"}</span>` :
      `<button class="vote ok" data-pid="${p.pid}" data-v="confirm">👍 pulse</button>
       <button class="vote no" data-pid="${p.pid}" data-v="mismatch">👎 pulse</button>`;
    return `<div class="knit"><b>${p.term}</b> <span class="dim small">by ${p.by}</span>
      <span class="tally">✓${v.confirm} ✗${v.mismatch} · ${v.total}</span> ${buttons}</div>`;
  }).join("") : `<div class="dim">no open knits — brainstorm one above</div>`;
  $("open").querySelectorAll("button.vote").forEach((b) => {
    b.onclick = async () => {
      const r = await api("/api/vote", "POST", { sid, pid: b.dataset.pid, verdict: b.dataset.v });
      if (r.error) alert(r.error);
      refresh();
    };
  });
  $("fabric").innerHTML = t.fabric.length ? t.fabric.map((w) =>
    `<span class="woven" title="Fiber ${w.fiber_cid}">${w.term} <span class="dim small">·${w.confirmations}✓</span></span>`).join("") :
    `<span class="dim">nothing woven yet</span>`;
}

function renderLedger(mk) {
  if (!mk) return;
  $("ledger-summary").innerHTML =
    `<span class="bal">🪢 <b>${mk.knits_made}</b> knits</span>
     <span class="bal">🧬 <b>${mk.woven}</b> woven</span>
     <span class="bal">🗳️ <b>${mk.total_votes}</b> total votes on my knits</span>`;
  $("ledger-rows").innerHTML = mk.knits.map((k) => {
    const v = k.votes, st = k.woven ? "✅ woven" : (k.settled ? "✗ " + k.outcome : "… open");
    return `<tr><td><b>${k.term}</b></td><td class="dim">${k.topic}</td><td>${st}</td>
      <td>${v.confirm} / ${v.mismatch} / ${v.abstain} / <b>${v.total}</b></td>
      <td class="mono small">${k.fiber_cid ? k.fiber_cid.slice(0, 20) + "…" : "—"}</td></tr>`;
  }).join("") || `<tr><td colspan="5" class="dim">no knits yet — sit at a table and knit a term</td></tr>`;
}

function renderExplorer(rows) {
  $("explorer-rows").innerHTML = (rows || []).map((row) => {
    const cols = row.columns.map((c, i) => {
      const v = c.votes, rank = ["🥇","🥈","🥉"][i] || ("#" + (i + 1));
      return `<div class="ecol ${c.woven ? "won" : ""}">
        <div class="erank">${rank}</div>
        <div class="eterm"><b>${c.term}</b> <span class="dim small">by ${c.by}</span></div>
        <div class="evotes">net <b>${c.net}</b> · ✓${v.confirm} ✗${v.mismatch} – ${v.abstain} · total ${v.total}</div>
        <div class="mono small">${c.woven ? "Fiber " + (c.fiber_cid || "").slice(0, 16) + "…" : (c.settled ? c.outcome : "open")}</div>
      </div>`;
    }).join("");
    return `<div class="erow"><div class="etopic">${row.topic} <span class="dim small">(${row.competing})</span></div>
      <div class="ecols">${cols}</div></div>`;
  }).join("") || `<div class="dim">no knits yet</div>`;
}

function renderWeb(w) {
  $("web-stats").innerHTML =
    `<span class="bal">🔵 <b>${w.nodes}</b> nodes</span>
     <span class="bal">🔗 <b>${w.edges}</b> edges</span>
     <span class="bal mono small">root ${(w.state_root || "").slice(0, 16)}…</span>`;
  const a = w.anchor || {};
  $("web-anchor").innerHTML = a.ual
    ? `🔗 anchored to OriginTrail: <span class="mono small">${a.ual}</span>
       <span class="dim small">· ${a.nodes}n/${a.edges}e · verified ${a.verified}</span>`
    : `<span class="dim">not yet anchored — weave a term to extend the web</span>`;
  $("web-recent").innerHTML = (w.recent || []).map((r) =>
    `<span class="woven" title="Fiber ${r.fiber}">${r.kind === "link" ? "🔗" : "🧬"} ${r.label} <span class="dim small">·${r.confirmations}✓ ${r.by}</span></span>`).join("")
    || `<span class="dim">empty</span>`;
  $("web-links").innerHTML = (w.links || []).map((l) =>
    `<div class="linkrow"><span class="chip">${l.subject}</span> <span class="dim small">${l.relation} →</span> <span class="chip">${l.object}</span></div>`).join("")
    || `<span class="dim">no links yet — knit two terms with "=" (e.g. <code>V2O5 = vanadium pentoxide</code>)</span>`;
  renderGraph();
}

async function renderGraph() {
  const g = await api("/api/graph");
  const s = g.stats || {};
  $("gx-stats").innerHTML =
    `<span class="bal">🔵 <b>${s.nodes || 0}</b> nodes</span>
     <span class="bal">🔗 <b>${s.edges || 0}</b> edges</span>
     <span class="bal">🧩 <b>${s.clusters || 0}</b> clusters</span>
     <span class="bal">density <b>${s.density || 0}</b></span>`;
  $("gx-hubs").innerHTML = "<b>hubs:</b> " + ((g.hubs || []).map((h) =>
    `<span class="chip" title="centrality ${h.centrality}">${h.term} <span class="dim small">·${h.degree}</span></span>`).join(" ") || "<span class='dim'>none yet</span>");
  $("gx-go").onclick = async () => {
    const t = $("gx-term").value.trim(); if (!t) return;
    const r = await api("/api/graph?term=" + encodeURIComponent(t));
    const n = r.neighbors;
    $("gx-result").innerHTML = !n ? `<span class="dim">“${t}” isn't in the web yet.</span>`
      : `<b>${t}</b> → ${(n.out.map((x) => `${x.relation} <span class="chip">${x.to}</span>`).join(", ") || "—")}<br>
         <b>${t}</b> ← ${(n.in.map((x) => `<span class="chip">${x.from}</span> ${x.relation}`).join(", ") || "—")}`;
  };
  $("gx-path").onclick = async () => {
    const a = $("gx-a").value.trim(), b = $("gx-b").value.trim(); if (!a || !b) return;
    const r = await api(`/api/graph?from=${encodeURIComponent(a)}&to=${encodeURIComponent(b)}`);
    const p = r.path;
    $("gx-result").innerHTML = !p ? `<span class="dim">one of those terms isn't woven yet.</span>`
      : p.path ? `path (${p.hops} hops): ${p.path.map((x) => `<span class="chip">${x}</span>`).join(" → ")}`
      : `<span class="dim">no path between “${a}” and “${b}” yet.</span>`;
  };
}

boot();
