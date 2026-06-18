"use strict";
// MOLGANG bar — vanilla JS client. Polls /api/state and renders the bar, your ledger,
// and the explorer (competing knits in columns). Same API a bot would drive.

const $ = (id) => document.getElementById(id);
const api = async (path, method = "GET", body = null) => {
  const r = await fetch(path, {
    method,
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : null,
  });
  return r.json();
};

let sid = localStorage.getItem("molgang_sid") || null;
let chosenAvatar = null;
let view = "bar";
let table = localStorage.getItem("molgang_table") || null;

// ---- walk-in ----
async function boot() {
  const avs = (await api("/api/state")).avatars || [];
  $("avatars").innerHTML = "";
  avs.forEach((a, i) => {
    const b = document.createElement("button");
    b.className = "av-pick" + (i === 0 ? " sel" : "");
    b.textContent = a;
    b.onclick = () => {
      chosenAvatar = a;
      document.querySelectorAll(".av-pick").forEach((x) => x.classList.remove("sel"));
      b.classList.add("sel");
    };
    $("avatars").appendChild(b);
  });
  chosenAvatar = avs[0];
  $("go").onclick = walkIn;
  if (sid) { $("enter").classList.add("hidden"); start(); }
}

async function walkIn() {
  const name = $("name").value.trim() || "guest";
  const res = await api("/api/join", "POST", { name, avatar: chosenAvatar });
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
  setInterval(refresh, 1500);
}

function setActiveTab() {
  document.querySelectorAll("#tabs button").forEach((b) =>
    b.classList.toggle("active", b.dataset.view === view));
  ["floor", "table", "ledger", "explorer"].forEach((v) => $(v).classList.add("hidden"));
  if (view === "ledger") $("ledger").classList.remove("hidden");
  else if (view === "explorer") $("explorer").classList.remove("hidden");
  else $(table ? "table" : "floor").classList.remove("hidden");
}

// ---- render ----
async function refresh() {
  const s = await api("/api/state?sid=" + encodeURIComponent(sid));
  if (s.you) {
    $("me-av").textContent = s.you.avatar;
    $("me-name").textContent = s.you.name;
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
  else if (table) renderTable(s);
  else renderFloor(s);
  setActiveTab();
}

function renderFloor(s) {
  const f = $("floor"); f.innerHTML = "";
  s.tables.forEach((t) => {
    const card = document.createElement("div");
    card.className = "table-card";
    const chairs = Array.from({ length: t.seats }, (_, i) => {
      const occ = t.seated[i];
      return `<span class="chair ${occ ? "occ" : ""}" title="${occ ? occ.name : "empty"}">${occ ? occ.avatar : "·"}</span>`;
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
    `<div class="seat ${p.you ? "you" : ""}"><span class="av">${p.avatar}</span>
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

boot();
