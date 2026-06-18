"use strict";
// MOLGANG bar — vanilla JS client. Polls /api/state and renders the bar, your ledger,
// and the explorer (competing knits in columns). Same API a bot would drive.

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

// a stable per-device id (browser-legal stand-in for IMEI) → the same PLS wallet every visit
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
  $("spiral-close").onclick = closeSpiralModal;
  $("spiral-submit").onclick = submitSpiral;
  $("spiral-links").oninput = updateSpiralCost;
  $("spiral-modal").onclick = (e) => { if (e.target.id === "spiral-modal") closeSpiralModal(); };
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
  ["floor", "table", "ledger", "explorer", "web", "records"].forEach((v) => $(v).classList.add("hidden"));
  $("enter").classList.remove("hidden");
}

function setActiveTab() {
  document.querySelectorAll("#tabs button").forEach((b) =>
    b.classList.toggle("active", b.dataset.view === view));
  ["floor", "table", "ledger", "explorer", "web", "records"].forEach((v) => $(v).classList.add("hidden"));
  if (view === "ledger") $("ledger").classList.remove("hidden");
  else if (view === "explorer") $("explorer").classList.remove("hidden");
  else if (view === "web") $("web").classList.remove("hidden");
  else if (view === "records") $("records").classList.remove("hidden");
  else $(table ? "table" : "floor").classList.remove("hidden");
}

// ---- render ----
async function refresh() {
  const s = await api("/api/state?sid=" + encodeURIComponent(sid));
  renderPulseHost(s.pulse_host);
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
  detectCaptures(s);
  if (view === "ledger") renderLedger(s.my_knits);
  else if (view === "explorer") renderExplorer(s.explorer);
  else if (view === "web") renderWeb(await api("/api/web"));
  else if (view === "records") renderRecords(s);
  else if (table) renderTable(s);
  else renderFloor(s);
  setActiveTab();
}

function renderPulseHost(host) {
  if (!host || !host.account) {
    $("pulse-host").textContent = "";
    return;
  }
  const addr = host.account.address || "";
  const bal = host.account.balance_pls || 0;
  $("pulse-host").textContent = `Pulse host ${addr.slice(0, 10)}… · ${bal} PLS`;
  $("pulse-host").title = `${addr}\nwallet: ${host.wallet || ""}`;
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
  renderSpirals(t);
  $("fabric").innerHTML = t.fabric.length ? t.fabric.map((w) =>
    `<span class="woven" title="Fiber ${w.fiber_cid}">${w.term} <span class="dim small">·${w.confirmations}✓</span></span>`).join("") :
    `<span class="dim">nothing woven yet</span>`;
}

// escalating silk to weave a spiral of n links — mirrors game.spiral_silk_cost (1 + i//3).
function spiralSilkCost(n) {
  let c = 0;
  for (let i = 0; i < n; i++) c += 1 + Math.floor(i / 3);
  return c;
}

// parse the textarea into link lines (non-blank), so the modal can preview cost/length.
function spiralLines() {
  return $("spiral-links").value.split("\n").map((l) => l.trim()).filter(Boolean);
}

function updateSpiralCost() {
  const lines = spiralLines(), n = lines.length;
  const el = $("spiral-cost");
  if (n === 0) { el.textContent = "Add 2–7 link lines (e.g. H2O -> O2)."; return; }
  const cost = spiralSilkCost(n);
  let msg = `${n} link${n === 1 ? "" : "s"} · costs 🧵 ${cost} silk · backers stake ⚡ ${n} PLS each`;
  if (n < 2) msg += " — need ≥2 links";
  else if (n > 7) msg += " — max 7 links";
  el.textContent = msg;
}

function openSpiralModal() {
  $("spiral-error").textContent = "";
  $("spiral-modal").classList.remove("hidden");
  updateSpiralCost();
  $("spiral-links").focus();
}
function closeSpiralModal() { $("spiral-modal").classList.add("hidden"); }

async function submitSpiral() {
  const lines = spiralLines();
  if (lines.length < 2 || lines.length > 7) {
    $("spiral-error").textContent = "A spiral needs 2–7 links (one A -> B per line).";
    return;
  }
  const r = await api("/api/spiral/propose", "POST", { sid, links: lines });
  if (r.error) { $("spiral-error").textContent = r.error; return; }
  $("spiral-links").value = "";
  closeSpiralModal();
  refresh();
}

function renderSpirals(t) {
  $("table-spiral-record").textContent =
    t.spiral_record ? `· 🏆 longest captured here: ${t.spiral_record} links` : "";
  $("start-spiral").onclick = openSpiralModal;
  const list = t.spirals || [];
  $("spirals").innerHTML = list.length ? list.map((sp) => {
    const v = sp.votes, captured = sp.state === "capture";
    const path = sp.links.map((lk, i) => {
      // each link is "A → B"; chain them without repeating the shared node.
      const [a, b] = lk.split("→").map((x) => x.trim());
      return (i === 0 ? `<span class="chip">${a}</span>` : "") +
        ` <span class="spiral-arrow">→</span> <span class="chip">${b}</span>`;
    }).join("");
    const stateLabel = captured ? "🕸 capture" : "auxiliary";
    const acts = (sp.mine || sp.backed)
      ? `<span class="dim small">${sp.mine ? "your spiral" : "backed ✓"}</span>`
      : `<button class="back" data-cid="${sp.cid}" data-v="confirm">⚡ Back (pulse)</button>
         <button class="reject" data-cid="${sp.cid}" data-v="mismatch">✗ Reject</button>`;
    return `<div class="spiral ${captured ? "captured" : ""}" data-cid="${sp.cid}">
      <div class="spiral-top">
        <span class="spiral-state ${captured ? "capture" : ""}">${stateLabel}</span>
        <b>by ${sp.by}</b>
        <span class="spiral-len">${sp.length} links</span>
      </div>
      <div class="spiral-path">${path}</div>
      <div class="spiral-meta">
        <span>✓ ${v.confirm} · ✗ ${v.mismatch} · ${v.total} backers</span>
        <span class="spiral-stake">my stake if I back: ⚡ ${sp.stake} PLS</span>
        <span class="spiral-actions">${acts}</span>
      </div>
    </div>`;
  }).join("") : `<div class="dim">no open spirals — start one above</div>`;
  $("spirals").querySelectorAll("button.back, button.reject").forEach((b) => {
    b.onclick = async () => {
      const r = await api("/api/spiral/vote", "POST",
        { sid, cid: b.dataset.cid, verdict: b.dataset.v });
      if (r.error) alert(r.error);
      refresh();
    };
  });
}

function renderRecords(s) {
  const board = s.spiral_leaderboard || [];
  $("records-board").innerHTML = board.length ? board.map((r, i) => {
    const rank = ["🥇", "🥈", "🥉"][i] || ("#" + (i + 1));
    return `<div class="record-row">
      <span class="record-rank">${rank}</span>
      <span><b>${r.by}</b> <span class="dim small">· ${r.table}</span></span>
      <span class="record-len">🕸 ${r.length} links</span>
    </div>`;
  }).join("") : `<div class="dim">no spirals captured yet — weave one at a table to set the record</div>`;
}

// brief teal toast + flash when a spiral we can see flips into capture.
let _capturedSeen = new Set();
let _toastTimer = null;
function detectCaptures(s) {
  const now = new Set();
  (s.tables || []).forEach((t) => (t.spirals || []).forEach((sp) => {
    if (sp.state === "capture") {
      now.add(sp.cid);
      if (!_capturedSeen.has(sp.cid)) {
        showToast(`🕸 Spiral captured! ${sp.length} links by ${sp.by}`);
        const card = document.querySelector(`.spiral[data-cid="${sp.cid}"]`);
        if (card) card.classList.add("flash");
      }
    }
  }));
  _capturedSeen = now;
}

function showToast(msg) {
  const el = $("toast");
  el.textContent = msg;
  el.classList.remove("hidden");
  if (_toastTimer) clearTimeout(_toastTimer);
  _toastTimer = setTimeout(() => el.classList.add("hidden"), 3200);
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
