"use strict";
// MOLGANG bar — vanilla JS client. Subscribes to world updates when available,
// falls back to /api/state polling, and renders the same API a bot would drive.

const $ = (id) => document.getElementById(id);
// API base resolution (see config.js):
//  • window.MOLGANG_API set  → cross-origin backend (Fly/Render/VPS), CORS required.
//  • empty/unset             → SAME-ORIGIN: works whether served at the root or under
//                              a subpath like https://5mart.ml/molgang/ (path-prefix-safe),
//                              or self-served by `molgang serve`.
const BASE = (typeof window !== "undefined" && window.MOLGANG_API)
  ? window.MOLGANG_API.replace(/\/$/, "")
  : location.pathname.replace(/\/(index\.html)?$/, "");
const friendlyApiError = (status, data, retryAfter) => {
  if (status === 0) {
    // network-level failure: fetch threw (server down / restarted / no route).
    // t() falls back to the key's default text if the translation is missing.
    return t("err.offline") || "⚠ Can't reach the server — is it running? Try again in a moment.";
  }
  if (status === 429) {
    return retryAfter ? t("err.tooManyRetry", { s: retryAfter }) : t("err.tooMany");
  }
  return (data && data.error) || t("err.failed", { status });
};
const api = async (path, method = "GET", body = null) => {
  let r;
  try {
    r = await fetch(BASE + path, {
      method,
      headers: body ? { "Content-Type": "application/json" } : {},
      body: body ? JSON.stringify(body) : null,
    });
  } catch (e) {
    // fetch rejects on a dead/unreachable server — return an error object so
    // every `if (r.error) showToast(...)` call site surfaces it instead of the
    // click handler rejecting silently (a dead server used to look like "nothing
    // happens" on the knit / pulse buttons).
    return { ok: false, status: 0, error: friendlyApiError(0, {}, 0) };
  }
  let data = {};
  try {
    data = await r.json();
  } catch (e) {
    data = {};
  }
  if (!r.ok) {
    const retryAfter = Number(r.headers.get("Retry-After") || data.retry_after || 0);
    return { ...data, ok: false, status: r.status, error: friendlyApiError(r.status, data, retryAfter) };
  }
  return data;
};

const avatarImg = (id, cls = "av-img") => `<img class="${cls}" src="avatars/${id}.svg" alt="" />`;
// thousands-separated number + HTML-escape helpers (used by the Monitor tab)
const fmt = (n) => (n == null ? 0 : Number(n)).toLocaleString();
const esc = (s) => (s == null ? "" : String(s)).replace(/[&<>"]/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

let sid = localStorage.getItem("molgang_sid") || null;
let chosenAvatar = null;
let view = "bar";
let table = localStorage.getItem("molgang_table") || null;
let refreshTimer = null;
let worldSocket = null;
let worldSocketSid = null;
let worldSocketOpen = false;
let worldSocketReconnectTimer = null;
const TUTORIAL_DONE_KEY = "molgang_tutorial_done_v1";
const WORLD_SOCKET_RECONNECT_MS = 2000;

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

// ---- i18n (chrome-wide, #117) — locale data lives in web/locales/*.json ----
// window.I18N (web/i18n.js) owns loading, [data-i18n] scanning and persistence.
// Keep the historical t()/locale() names as thin delegates for existing callers.
function locale() { return window.I18N ? I18N.locale() : "en"; }
function t(key, vars) { return window.I18N ? I18N.t(key, vars) : key; }

const TOUR_STEPS = [
  {
    id: "walkin",
    target: "#enter .card",
    title: "tutorial.walkin.title",
    body: "tutorial.walkin.body",
    primary: "tutorial.walkin.primary",
    action: () => $("name").focus(),
  },
  {
    id: "seat",
    target: "#floor .table-card .join-table",
    title: "tutorial.seat.title",
    body: "tutorial.seat.body",
    primary: "tutorial.seat.primary",
    action: () => document.querySelector("#floor .table-card .join-table")?.click(),
  },
  {
    id: "knit",
    target: "#term",
    title: "tutorial.knit.title",
    body: "tutorial.knit.body",
    primary: "tutorial.knit.primary",
    action: () => {
      $("term").value = "H2O";
      $("knit").click();
    },
  },
  {
    id: "vote",
    target: "#seats",
    title: "tutorial.vote.title",
    body: "tutorial.vote.body",
    primary: "tutorial.vote.primary",
    action: () => {
      tour.step = Math.max(tour.step, 4);
      renderTutorial();
    },
  },
  {
    id: "fabric",
    target: "#fabric",
    title: "tutorial.fabric.title",
    body: "tutorial.fabric.body",
    primary: "tutorial.fabric.primary",
    action: () => finishTutorial(),
  },
];

let tour = { active: false, step: 0, lastState: null };

function tutorialDone() {
  return Boolean(localStorage.getItem(TUTORIAL_DONE_KEY));
}

function setupTutorialUi() {
  const replay = $("tutorial-replay");
  if (replay) {
    replay.textContent = t("tutorial.replay");
    replay.title = t("tutorial.replayTitle");
    replay.onclick = () => startTutorial(true);
  }
  if ($("tour-layer")) return;
  const layer = document.createElement("div");
  layer.id = "tour-layer";
  layer.className = "tour-layer hidden";
  layer.innerHTML = `
    <div id="tour-dim" class="tour-dim"></div>
    <div id="tour-highlight" class="tour-highlight"></div>
    <div id="tour-card" class="tour-card" role="dialog" aria-live="polite">
      <div id="tour-kicker" class="tour-kicker"></div>
      <h3 id="tour-title"></h3>
      <p id="tour-body"></p>
      <div class="tour-actions">
        <button id="tour-skip" class="ghost"></button>
        <button id="tour-primary"></button>
      </div>
    </div>`;
  document.body.appendChild(layer);
  $("tour-skip").onclick = skipTutorial;
  window.addEventListener("resize", renderTutorial);
  window.addEventListener("scroll", renderTutorial, true);
}

function startTutorial(force = false) {
  setupTutorialUi();
  if (!force && tutorialDone()) return;
  tour.active = true;
  tour.step = force && sid ? tutorialStepFromState(tour.lastState) : 0;
  renderTutorial();
}

function skipTutorial() {
  localStorage.setItem(TUTORIAL_DONE_KEY, "skipped");
  hideTutorial();
}

function finishTutorial() {
  localStorage.setItem(TUTORIAL_DONE_KEY, "done");
  hideTutorial();
  if (sid) showToast(t("tutorial.done"));
}

function hideTutorial() {
  tour.active = false;
  $("tour-layer")?.classList.add("hidden");
  document.querySelectorAll(".tour-target").forEach((el) => el.classList.remove("tour-target"));
}

function tutorialStepFromState(s) {
  if (!sid || !$("enter")?.classList.contains("hidden")) return 0;
  if (!s || !s.you || !s.you.table) return 1;
  if ((s.you.knits_made || 0) <= 0) return 2;
  const current = (s.tables || []).find((x) => x.id === s.you.table);
  if (current && (current.fabric || []).length && tour.step >= 4) return 4;
  return 3;
}

function syncTutorial(s) {
  if (!tour.active) return;
  tour.lastState = s || tour.lastState;
  tour.step = Math.max(tour.step, tutorialStepFromState(s));
  requestAnimationFrame(renderTutorial);
}

function clamp(n, lo, hi) {
  return Math.max(lo, Math.min(hi, n));
}

function renderTutorial() {
  setupTutorialUi();
  const layer = $("tour-layer");
  if (!tour.active || !layer) return;
  const step = TOUR_STEPS[clamp(tour.step, 0, TOUR_STEPS.length - 1)];
  const target = document.querySelector(step.target);
  layer.classList.remove("hidden");
  document.querySelectorAll(".tour-target").forEach((el) => el.classList.remove("tour-target"));
  if (target) target.classList.add("tour-target");

  $("tour-kicker").textContent = `${t("tutorial.step")} ${tour.step + 1}/${TOUR_STEPS.length}`;
  $("tour-title").textContent = t(step.title);
  $("tour-body").textContent = t(step.body);
  $("tour-skip").textContent = t("tutorial.skip");
  $("tour-primary").textContent = t(step.primary);
  $("tour-primary").onclick = step.action;

  const hl = $("tour-highlight");
  const card = $("tour-card");
  if (!target) {
    hl.classList.add("hidden");
    card.style.left = "50%";
    card.style.top = "50%";
    card.style.transform = "translate(-50%, -50%)";
    return;
  }
  const r = target.getBoundingClientRect();
  hl.classList.remove("hidden");
  hl.style.left = `${Math.max(8, r.left - 8)}px`;
  hl.style.top = `${Math.max(8, r.top - 8)}px`;
  hl.style.width = `${r.width + 16}px`;
  hl.style.height = `${r.height + 16}px`;

  const cardW = Math.min(360, window.innerWidth - 28);
  const left = clamp(r.left, 14, window.innerWidth - cardW - 14);
  const below = r.bottom + 14;
  const top = below < window.innerHeight - 190 ? below : Math.max(14, r.top - 214);
  card.style.width = `${cardW}px`;
  card.style.left = `${left}px`;
  card.style.top = `${top}px`;
  card.style.transform = "none";
}

// ---- walk-in ----
async function boot() {
  setupTutorialUi();
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
  if (!sid && !tutorialDone()) startTutorial();
  if (sid) { $("enter").classList.add("hidden"); start(); }
}

async function walkIn() {
  const name = $("name").value.trim() || "guest";
  const res = await api("/api/join", "POST", { name, avatar: chosenAvatar, device: DEVICE_ID });
  if (res.error) { showToast(res.error); return; }
  sid = res.sid; localStorage.setItem("molgang_sid", sid);
  localStorage.setItem("molgang_name", name);
  if (chosenAvatar) localStorage.setItem("molgang_avatar", chosenAvatar);
  $("enter").classList.add("hidden");
  start();
}

async function reconnectDevice() {
  const name = localStorage.getItem("molgang_name") || $("name").value.trim() || "guest";
  const avatar = localStorage.getItem("molgang_avatar") || chosenAvatar;
  const res = await api("/api/join", "POST", { name, avatar, device: DEVICE_ID });
  if (!res || !res.sid) return false;
  sid = res.sid;
  localStorage.setItem("molgang_sid", sid);
  if (avatar) localStorage.setItem("molgang_avatar", avatar);
  return true;
}

function start() {
  setupTutorialUi();
  $("me").classList.remove("hidden");
  $("tabs").classList.remove("hidden");
  document.querySelectorAll("#tabs button").forEach((b) => {
    b.onclick = () => { view = b.dataset.view; setActiveTab(); refresh(); };
  });
  $("spiral-close").onclick = closeSpiralModal;
  $("spiral-submit").onclick = submitSpiral;
  $("me-cert").onclick = requestCertificate;
  $("spiral-links").oninput = updateSpiralCost;
  $("spiral-modal").onclick = (e) => { if (e.target.id === "spiral-modal") closeSpiralModal(); };
  $("lb-all").onclick = () => { lbSeason = "all"; refresh(); };
  $("lb-season").onclick = () => { lbSeason = "season"; refresh(); };
  setActiveTab();
  refresh();
  connectWorldSocket();
  if (refreshTimer) clearInterval(refreshTimer);
  refreshTimer = setInterval(() => {
    if (isWorldSocketOpen()) return;
    refresh();
    connectWorldSocket();
  }, 1500);
}

function resetSession() {
  closeWorldSocket();
  sid = null;
  table = null;
  localStorage.removeItem("molgang_sid");
  localStorage.removeItem("molgang_table");
  if (refreshTimer) clearInterval(refreshTimer);
  refreshTimer = null;
  $("me").classList.add("hidden");
  $("tabs").classList.add("hidden");
  ["floor", "table", "ledger", "explorer", "web", "progress", "records", "monitor"].forEach((v) => $(v).classList.add("hidden"));
  $("enter").classList.remove("hidden");
}

function setActiveTab() {
  document.querySelectorAll("#tabs button").forEach((b) => {
    const on = b.dataset.view === view;
    b.classList.toggle("active", on);
    b.setAttribute("aria-selected", on ? "true" : "false");
  });
  ["floor", "table", "ledger", "explorer", "web", "progress", "records", "monitor"].forEach((v) => $(v).classList.add("hidden"));
  if (view === "ledger") $("ledger").classList.remove("hidden");
  else if (view === "explorer") $("explorer").classList.remove("hidden");
  else if (view === "web") $("web").classList.remove("hidden");
  else if (view === "progress") $("progress").classList.remove("hidden");
  else if (view === "records") $("records").classList.remove("hidden");
  else if (view === "monitor") $("monitor").classList.remove("hidden");
  else $(table ? "table" : "floor").classList.remove("hidden");
}

// ---- render ----
let offlineToastShown = false;
async function refresh() {
  let s;
  try {
    s = await api("/api/state?sid=" + encodeURIComponent(sid));
  } catch (e) {
    // network blip: show ONE non-blocking reconnecting toast, keep the last
    // rendered state on screen, and let the poll interval retry cleanly (#116)
    if (!offlineToastShown) { offlineToastShown = true; showToast(t("toast.reconnecting")); }
    return;
  }
  if (offlineToastShown) { offlineToastShown = false; showToast(t("toast.reconnected")); }
  return renderState(s);
}

function worldSocketUrl() {
  const url = new URL(BASE + "/ws/world/", location.href);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  url.searchParams.set("sid", sid || "");
  return url.toString();
}

function isWorldSocketOpen() {
  return Boolean(
    worldSocketOpen &&
    worldSocket &&
    typeof WebSocket !== "undefined" &&
    worldSocket.readyState === WebSocket.OPEN
  );
}

function connectWorldSocket() {
  if (!sid || typeof WebSocket === "undefined") return;
  if (worldSocketReconnectTimer) {
    clearTimeout(worldSocketReconnectTimer);
    worldSocketReconnectTimer = null;
  }
  if (
    worldSocket &&
    worldSocketSid === sid &&
    (worldSocket.readyState === WebSocket.OPEN || worldSocket.readyState === WebSocket.CONNECTING)
  ) {
    return;
  }

  closeWorldSocket();
  let socket;
  try {
    socket = new WebSocket(worldSocketUrl());
  } catch (e) {
    scheduleWorldSocketReconnect();
    return;
  }

  worldSocket = socket;
  worldSocketSid = sid;
  worldSocketOpen = false;
  socket.onopen = () => { worldSocketOpen = true; };
  socket.onmessage = (event) => {
    let payload = null;
    try {
      payload = JSON.parse(event.data);
    } catch (e) {
      return;
    }
    if (payload && payload.type === "world.state" && payload.state) {
      renderState(payload.state);
    }
  };
  socket.onerror = () => { worldSocketOpen = false; };
  socket.onclose = () => {
    if (worldSocket === socket) {
      worldSocket = null;
      worldSocketSid = null;
      worldSocketOpen = false;
      scheduleWorldSocketReconnect();
    }
  };
}

function closeWorldSocket() {
  if (worldSocketReconnectTimer) {
    clearTimeout(worldSocketReconnectTimer);
    worldSocketReconnectTimer = null;
  }
  const socket = worldSocket;
  worldSocket = null;
  worldSocketSid = null;
  worldSocketOpen = false;
  if (socket && socket.readyState !== WebSocket.CLOSED) {
    socket.close();
  }
}

function scheduleWorldSocketReconnect() {
  if (!sid || worldSocketReconnectTimer) return;
  worldSocketReconnectTimer = setTimeout(() => {
    worldSocketReconnectTimer = null;
    connectWorldSocket();
  }, WORLD_SOCKET_RECONNECT_MS);
}

async function renderState(s) {
  renderPulseHost(s.pulse_host);
  if (sid && !s.you) {
    if (await reconnectDevice()) {
      connectWorldSocket();
      return refresh();
    }
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
  else if (view === "progress") renderProgress(s);
  else if (view === "records") renderRecords(s);
  else if (view === "monitor") renderMonitor();
  else if (table) renderTable(s);
  else renderFloor(s);
  setActiveTab();
  syncTutorial(s);
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
      const st = await api("/api/sit", "POST", { sid, table: t.id });
      if (st.error) { showToast(st.error); return; }
      table = st.you ? st.you.table : t.id;
      view = "bar"; refresh();
    };
    f.appendChild(card);
  });
}

function renderTable(s) {
  const t = s.tables.find((x) => x.id === table);
  if (!t) { table = null; return; }
  $("table-name").textContent = "🍸 " + t.name;
  $("rename-table").classList.toggle("hidden", !t.can_rename);
  $("seats").innerHTML = t.seated.map((p) =>
    `<div class="seat ${p.you ? "you" : ""}">${avatarImg(p.avatar, "seat-av")}
      <div><b>${p.name}</b><br><span class="dim small">L${p.level} ${p.title} · ${p.woven}🧬</span></div></div>`).join("");
  $("leave-table").onclick = async () => {
    const r = await api("/api/stand", "POST", { sid });
    if (r.error) { showToast(r.error); return; }
    table = null;
    localStorage.removeItem("molgang_table");
    setActiveTab();
    refresh();
  };
  $("rename-table").onclick = async () => {
    const nextName = prompt("Rename this table", t.name);
    if (nextName === null) return;
    const r = await api("/api/table/rename", "POST", { sid, table: t.id, name: nextName });
    if (r.error) alert(r.error);
    else refresh();
  };
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

// 🏅 Progress — quests, achievements & seasonal standing (#110/#111/#112). All reputation/XP,
// never tokens. Reads the dedicated /api endpoints scoped to the current player.
let lbSeason = "all";   // "all" | "season" — leaderboard toggle state

async function renderProgress(s) {
  const player = s && s.you ? s.you.name : "";

  // 🧗 Reputation ladder — current title, XP to next, and unlocked perks (#113)
  const you = (s && s.you) || {};
  const nxt = you.next || {};
  const climb = nxt.at_max
    ? `<span class="dim small">max rank reached 🎓</span>`
    : (nxt.next_title ? `<span class="dim small">${fmt(nxt.xp_to_next)} XP to <b>${esc(nxt.next_title)}</b></span>` : "");
  $("ladder").innerHTML =
    `<div class="ladder-now">🏅 <b>L${you.level || 1} ${esc(you.title || "Apprentice")}</b> · ${fmt(you.xp || 0)} XP ${climb}</div>` +
    `<ul class="perks">${(you.perks || []).map((p) => `<li>✓ ${esc(p)}</li>`).join("")}</ul>`;

  const q = await api("/api/quests?player=" + encodeURIComponent(player));
  $("quests-list").innerHTML = (q.all || []).map((x) =>
    `<div class="progress-item ${x.complete ? "done" : ""}" data-quest="${esc(x.id)}">
       <span class="pi-title">${x.complete ? "✅" : "🎯"} ${esc(x.title)}</span>
       <span class="pi-desc dim small">${esc(x.desc)}</span>
       <span class="pi-bar"><i style="width:${Math.max(0, Math.min(100, x.pct))}%"></i></span>
       <span class="pi-meta dim small">${x.done}/${x.need} · ${fmt(x.xp_reward)} XP</span>
     </div>`).join("") || '<p class="dim small">No quests yet — weave a molecule to start.</p>';

  const a = await api("/api/achievements?player=" + encodeURIComponent(player));
  $("achievements-list").innerHTML = (a.achievements || []).map((x) =>
    `<span class="badge ${x.unlocked ? "unlocked" : "locked"}" data-badge="${esc(x.id)}"
       title="${esc(x.desc)}">${x.unlocked ? "🏅" : "🔒"} ${esc(x.title)}</span>`).join("");

  $("lb-all").classList.toggle("active", lbSeason === "all");
  $("lb-season").classList.toggle("active", lbSeason === "season");
  const lb = await api("/api/leaderboard?season=" + (lbSeason === "season" ? "current" : "all"));
  const rows = lb.rows || [];
  $("season-board").innerHTML = rows.length
    ? rows.map((r, i) => {
        const rank = ["🥇", "🥈", "🥉"][i] || ("#" + (i + 1));
        return `<div class="record-row">
          <span class="record-rank">${rank}</span>
          <span><b>${esc(r.player)}</b> <span class="dim small">· ${fmt(r.molecules)} molecules · ${esc(r.title)}</span></span>
          <span class="record-len">${fmt(r.xp)} XP</span>
        </div>`;
      }).join("")
    : `<div class="dim small">no ranked players ${lbSeason === "season" ? "this season yet" : "yet"} — weave a molecule to appear here</div>`;
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
        showToast(`${t("toast.spiral.captured")} ${sp.length} links · ${sp.by}`);
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

// Download a public PoUW Certificate PDF for the current wallet. Bearer/private
// certificate export is local-CLI only; the browser endpoint is always redacted.
async function requestCertificate() {
  if (!sid) return;
  const ok = confirm(
    "Download your Proof of Useful Work certificate?\n\n" +
    "This public certificate redacts private wallet material and can be shared as proof of useful work.");
  if (!ok) return;
  showToast("🏅 Generating your PoUW certificate…");
  try {
    const r = await fetch(BASE + "/api/certificate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sid }),
    });
    if (!r.ok) {
      let data = {};
      try { data = await r.json(); } catch (e) { data = {}; }
      const retryAfter = Number(r.headers.get("Retry-After") || data.retry_after || 0);
      showToast(friendlyApiError(r.status, data, retryAfter));
      return;
    }
    const blob = await r.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "pouw-certificate.pdf";
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    showToast("🏅 Public certificate downloaded.");
  } catch (e) {
    showToast("Could not generate certificate.");
  }
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
  // type-ahead datalist of the woven vocabulary (case-insensitive lookup means any case works)
  $("gx-names").innerHTML = (w.terms || []).map((t) => `<option value="${t}"></option>`).join("");
  renderGraph();
}

// clickable "did you mean: …" suggestions; clicking one fills `input` and re-runs `rerun`
function gxSuggest(suggestions, input, rerun) {
  if (!suggestions || !suggestions.length) return "";
  setTimeout(() => {
    document.querySelectorAll("#gx-result a[data-t]").forEach((a) => {
      a.onclick = (e) => { e.preventDefault(); input.value = a.dataset.t; rerun(); };
    });
  }, 0);
  return ` <span class="dim small">did you mean:</span> ` +
    suggestions.map((s) => `<a href="#" class="chip" data-t="${s}">${s}</a>`).join(" ");
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
    $("gx-result").innerHTML = !n
      ? `<span class="dim">“${t}” isn't in the web yet.</span>` + gxSuggest(r.suggestions, $("gx-term"), $("gx-go").onclick)
      : `<b>${n.term}</b> → ${(n.out.map((x) => `${x.relation} <span class="chip">${x.to}</span>`).join(", ") || "—")}<br>
         <b>${n.term}</b> ← ${(n.in.map((x) => `<span class="chip">${x.from}</span> ${x.relation}`).join(", ") || "—")}`;
  };
  $("gx-path").onclick = async () => {
    const a = $("gx-a").value.trim(), b = $("gx-b").value.trim(); if (!a || !b) return;
    const r = await api(`/api/graph?from=${encodeURIComponent(a)}&to=${encodeURIComponent(b)}`);
    const p = r.path;
    if (!p) {
      const miss = r.missing || [];
      const box = (miss.length && a.toLowerCase() === String(miss[0]).toLowerCase()) ? $("gx-a") : $("gx-b");
      $("gx-result").innerHTML = `<span class="dim">${(miss.join(", ") || "one of those terms")} isn't woven yet.</span>`
        + gxSuggest(r.suggestions, box, $("gx-path").onclick);
      return;
    }
    $("gx-result").innerHTML = p.path
      ? `path (${p.hops} hops): ${p.path.map((x) => `<span class="chip">${x}</span>`).join(" → ")}`
      : `<span class="dim">no path between “${p.from}” and “${p.to}” yet.</span>`;
  };
}

// ---- 📡 Monitor: node/p2p status + the local woven knitweb (:8990) ----
const MON_LANGS = [["en", "🇬🇧 EN"], ["ru", "🇷🇺 RU"], ["zh", "🇨🇳 ZH"], ["ar", "🇸🇦 AR"]];
const MON_TENSION = { taut: "#22e3ff", neutral: "#ff5cf0", slack: "#6b7689", contested: "#ff7a18" };
let monNet = null, monCenter = null, monSimNet = null;

async function renderMonitor() {
  // Wire the simulation button once.
  if ($("btn-sim") && !$("btn-sim")._wired) {
    $("btn-sim")._wired = true;
    $("btn-sim").onclick = runSim;
  }
  const m = await api("/api/monitor");
  if (!m || m.error) {
    $("mon-nodes").innerHTML = `<span class="dim">monitor unavailable — use simulation above to preview the p2p network</span>`;
    // Auto-run simulation with default nodes so the tab is never empty.
    if (parseInt($("sim-n").value) > 0) runSim();
    return;
  }
  renderMonStatus(m.status);
  renderMonKg(m.kg);
  // centre the compact graph on the top hub once (then leave it; it polls on its own cadence).
  if (!monCenter && m.kg.hubs && m.kg.hubs.length) monFocus(m.kg.hubs[0].term);
}

// ---- P2P simulation ----
async function runSim() {
  const n = parseInt($("sim-n").value) || 6;
  if (n < 1) { $("mon-sim-net").style.display = "none"; monSimNet = null; return; }
  const d = await api("/api/monitor/simulate?n=" + n);
  if (!d || d.error) {
    $("mon-sim-net").style.display = "none";
    monSimNet = null;
    return;
  }
  const nodesEl = $("mon-nodes");
  nodesEl.replaceChildren(...d.nodes.map((nd) => {
    const div = document.createElement("div");
    div.className = "mon-node";
    const dot = document.createElement("span"); dot.className = "mdot up";
    const lbl = document.createElement("b"); lbl.textContent = nd.label;
    const prt = document.createElement("span"); prt.className = "dim small"; prt.textContent = `:${nd.port}`;
    const live = document.createElement("span"); live.className = "pos small"; live.textContent = "● live (sim)";
    const info = document.createElement("span"); info.className = "dim small";
    info.textContent = `· ${nd.peers} peers · ${nd.fibers} fibers · ${fmt(nd.balance_pls)} PLS`;
    const addr = document.createElement("span"); addr.className = "mono small dim"; addr.title = nd.address;
    addr.textContent = ` ${nd.address.slice(0, 12)}…`;
    div.append(dot, lbl, " ", prt, " ", live, " ", info, " ", addr);
    return div;
  }));
  const statsEl = $("mon-sim-stats");
  statsEl.replaceChildren(...[
    ["🌐", d.node_count, "nodes (simulated)"],
    ["🔗", d.edges.length, "p2p links"],
    ["⚡", fmt(d.total_balance_pls), "PLS total"],
    ["🧵", d.total_fibers, "fibers"],
  ].map(([icon, val, label]) => {
    const sp = document.createElement("span"); sp.className = "bal";
    sp.textContent = `${icon} ${val} ${label}`;
    return sp;
  }));
  $("mon-sim-net").style.display = "";
  if (typeof vis !== "undefined") {
    const nodes = new vis.DataSet(d.nodes.map((nd) => ({
      id: nd.id, label: nd.label,
      title: `${nd.address}\n${fmt(nd.balance_pls)} PLS · ${nd.fibers} fibers`,
      color: { background: "#0d2240", border: "#22e3ff" },
      font: { color: "#bfe9f5", size: 13 }, shape: "dot", size: 16,
    })));
    const edges = new vis.DataSet(d.edges.map((e, i) => ({
      id: i, from: e.from, to: e.to, label: e.label, arrows: "to",
      color: { color: e.label === "webrtc" ? "#ffd24a" : "#22e3ff", opacity: 0.75 },
      dashes: e.label !== "webrtc",
      font: { color: "#7e8aa8", size: 10, strokeWidth: 0 },
    })));
    if (!monSimNet) {
      monSimNet = new vis.Network($("mon-p2p-net"), { nodes, edges }, {
        physics: { stabilization: { iterations: 100 }, barnesHut: { springLength: 110, avoidOverlap: 0.5 } },
        interaction: { hover: true, tooltipDelay: 80 },
        nodes: { shape: "dot", size: 16, borderWidth: 2 },
        edges: { smooth: { type: "continuous" } },
      });
    } else {
      monSimNet.setData({ nodes, edges });
    }
  }
}

function renderMonStatus(st) {
  $("mon-nodes").innerHTML = (st.nodes || []).map((n) => {
    const dot = n.live ? `<span class="mdot up"></span>` : `<span class="mdot down"></span>`;
    const port = n.port ? `<span class="dim small">:${n.port}</span>` : "";
    return `<div class="mon-node">${dot}<b>${n.label}</b> ${port}
      <span class="${n.live ? "pos" : "neg"} small">${n.live ? "● live" : "● down"}</span></div>`;
  }).join("") || `<span class="dim">no nodes configured</span>`;
  const w = st.web || {}, h = st.pulse_host;
  $("mon-web").innerHTML =
    `<span class="bal">🔵 <b>${w.nodes || 0}</b> web nodes</span>
     <span class="bal">🔗 <b>${w.edges || 0}</b> edges</span>
     <span class="bal mono small">root ${(w.state_root || "").slice(0, 14)}…</span>` +
    (h && h.address ? `<span class="bal mono small" title="${h.address}">📡 host ${h.address.slice(0, 10)}… · ${h.balance_pls || 0} PLS</span>` : "");
  const a = st.anchor || {};
  $("mon-anchor").innerHTML = a.ual
    ? `🔗 OriginTrail: <span class="mono small">${a.ual}</span>
       <span class="dim small">· ${a.nodes}n/${a.edges}e · ${a.verified ? '<span class="pos">✓ verified</span>' : "unverified"}</span>`
    : `<span class="dim">shared web not yet anchored</span>`;
}

function renderMonKg(kg) {
  $("mon-src").textContent = kg.source ? "⛓ " + kg.source : "";
  $("mon-kg-stats").innerHTML =
    `<span class="bal">🔵 <b>${fmt(kg.nodes)}</b> nodes</span>
     <span class="bal">🔗 <b>${fmt(kg.edges)}</b> edges</span>
     <span class="bal">🔵 <b>${fmt(kg.concepts)}</b> concepts</span>
     <span class="bal">🧩 <b>${kg.clusters}</b> clusters</span>
     <span class="bal">density <b>${kg.density}</b></span>`;
  const L = kg.languages || {};
  $("mon-langs").innerHTML = MON_LANGS.map(([code, lbl]) =>
    `<span class="mon-lang"><span>${lbl}</span><b>${fmt(L[code] || 0)}</b></span>`).join("");
  const t = kg.tension || {}, b = t.bands || {};
  const sw = (c) => `<i class="sw" style="background:${c}"></i>`;
  $("mon-tension").innerHTML =
    `<div class="row"><span>${sw(MON_TENSION.taut)}taut</span><b>${fmt(b.taut || 0)}</b></div>
     <div class="row"><span>${sw(MON_TENSION.neutral)}neutral</span><b>${fmt(b.neutral || 0)}</b></div>
     <div class="row"><span>${sw(MON_TENSION.slack)}slack</span><b>${fmt(b.slack || 0)}</b></div>
     <div class="row"><span>${sw(MON_TENSION.contested)}snapped</span><b>${fmt(b.contested || 0)}</b></div>
     <div class="row"><span class="dim">avg tautness</span><b>${t.avg_tautness ?? "–"} / ${(t.thresholds || {}).scale || 1000}</b></div>`;
  $("mon-hubs").innerHTML = (kg.hubs || []).map((h) =>
    `<span class="chip mon-hub" data-t="${esc(h.term)}" title="centrality ${h.centrality}">${esc(h.term)} <span class="dim">·${h.degree}</span></span>`).join("");
  $("mon-hubs").querySelectorAll(".mon-hub").forEach((c) => { c.onclick = () => monFocus(c.dataset.t); });
}

function monNodeStyle(n) {
  if (n.center) return { color: { background: "#ffd24a", border: "#fff" }, font: { color: "#fff", size: 16 } };
  if (n.concept) return { color: { background: "#8b5cff", border: "#c4b5ff" }, font: { color: "#eaf1fb" } };
  return { color: { background: "#123", border: "#22e3ff" }, font: { color: "#bfe9f5" }, shape: "box" };
}

async function monFocus(term) {
  if (!term || typeof vis === "undefined") return;
  const sg = await api("/api/monitor/kg/subgraph?depth=2&term=" + encodeURIComponent(term));
  if (!sg || sg.error || !sg.nodes) return;
  monCenter = sg.center;
  const nodes = new vis.DataSet(sg.nodes.map((n) => ({
    id: n.id, label: n.id, title: (n.definition || "") + (n.formula ? " [" + n.formula + "]" : ""),
    ...monNodeStyle(n),
  })));
  const edges = new vis.DataSet(sg.edges.map((e, i) => {
    const col = MON_TENSION[e.tension_band || "neutral"] || "#ff5cf0";
    const slack = e.tension_band === "slack" || e.tension_band === "contested";
    return {
      id: i, from: e.from, to: e.to, label: e.relation, arrows: "to",
      width: 1 + Math.round((typeof e.tautness === "number" ? e.tautness : 500) / 250),
      dashes: slack, color: { color: col, opacity: 0.7 },
      title: "tension: " + (e.tension_band || "neutral") + " · tautness " + (e.tautness ?? "?") + " · cost " + (e.cost ?? "?"),
      font: { color: "#7e8aa8", size: 10, strokeWidth: 0 },
    };
  }));
  if (!monNet) {
    monNet = new vis.Network($("mon-net"), { nodes, edges }, {
      physics: { stabilization: { iterations: 140 }, barnesHut: { springLength: 120, avoidOverlap: 0.4 } },
      interaction: { hover: true, tooltipDelay: 120 },
      nodes: { shape: "dot", size: 14, borderWidth: 2 },
      edges: { smooth: { type: "continuous" } },
    });
    monNet.on("click", (p) => { if (p.nodes.length) monFocus(p.nodes[0]); });
  } else {
    monNet.setData({ nodes, edges });
  }
}

// ── PWA install affordance (#115) ──────────────────────────────────────────
// Chrome/Android fire `beforeinstallprompt` when the manifest + icons qualify.
// We surface a dismissible button; dismissal persists in localStorage next to
// molgang_device so we never nag a peer twice.
let deferredInstall = null;
window.addEventListener("beforeinstallprompt", (e) => {
  if (localStorage.getItem("molgang_install_dismissed")) return;
  e.preventDefault();
  deferredInstall = e;
  if (document.getElementById("pwa-install")) return;
  const b = document.createElement("button");
  b.id = "pwa-install";
  b.textContent = "📲 Install MOLGANG";
  b.style.cssText = "position:fixed;right:14px;bottom:14px;z-index:60;padding:10px 14px;" +
    "border-radius:10px;border:1px solid #8b5cff;background:#0b1020;color:#fff;" +
    "font-weight:700;cursor:pointer;box-shadow:0 6px 24px rgba(139,92,255,.35)";
  const x = document.createElement("span");
  x.textContent = " ✕";
  x.style.cssText = "color:#8a93b2;margin-left:8px;cursor:pointer";
  x.onclick = (ev) => {
    ev.stopPropagation();
    localStorage.setItem("molgang_install_dismissed", "1");
    b.remove();
  };
  b.appendChild(x);
  b.onclick = async () => {
    if (!deferredInstall) return;
    deferredInstall.prompt();
    await deferredInstall.userChoice;
    deferredInstall = null;
    b.remove();
  };
  document.body.appendChild(b);
});
window.addEventListener("appinstalled", () => {
  const b = document.getElementById("pwa-install");
  if (b) b.remove();
});

// ── offline-first service worker (#116) ────────────────────────────────────
if ("serviceWorker" in navigator) {
  // relative registration → correct scope at / AND under a subpath like /molgang/
  navigator.serviceWorker.register("sw.js").catch(() => {/* http/unsupported: fine */});
}

// ── i18n boot: load locale, translate static chrome, wire the switcher (#117)
(async () => {
  if (window.I18N) {
    await I18N.ready;
    I18N.apply();
    // Language switcher UX: visible inline until the player has used it once,
    // then it retires into a background settings (⚙) popover — the choice is
    // made, the chrome gets the space back.
    const sw = document.getElementById("lang-switch");
    const inline = document.getElementById("lang-inline");
    const gear = document.getElementById("settings-gear");
    const pop = document.getElementById("settings-pop");
    const retire = () => {
      if (!inline || !gear || !pop) return;
      const label = document.createElement("label");
      label.textContent = "Language / Taal";
      pop.innerHTML = "";
      pop.appendChild(label);
      pop.appendChild(sw);                       // move the SAME select into the popover
      inline.classList.add("hidden");
      gear.classList.remove("hidden");
    };
    if (sw) {
      sw.onchange = async () => {
        await I18N.setLocale(sw.value);
        if (!localStorage.getItem("molgang_lang_seen")) {
          localStorage.setItem("molgang_lang_seen", "1");
          retire();
          if (pop) pop.classList.add("hidden");
        }
      };
      if (localStorage.getItem("molgang_lang_seen")) retire();   // returning player: gear only
    }
    if (gear && pop) gear.onclick = () => pop.classList.toggle("hidden");
    // #139 COPPA/GDPR-K age/consent gate: the faucet/join (#go) stays disabled
    // until the player acknowledges 13+/guardian permission. Persisted per device.
    const ageBox = document.getElementById("age-ok");
    const goBtn = document.getElementById("go");
    if (ageBox && goBtn) {
      // #119 RTL: mirror the chrome when an RTL UI locale is active (AR is a
      // first-class content language). Uses the same lang+base-direction W3C
      // approach as the KG term-nodes.
      const RTL = new Set(["ar", "he", "fa", "ur"]);
      const applyDir = () => {
        const l = (window.I18N && I18N.locale && I18N.locale()) ||
                  document.documentElement.lang || "en";
        document.documentElement.dir = RTL.has(String(l).slice(0, 2)) ? "rtl" : "ltr";
      };
      applyDir();
      document.addEventListener("i18n:changed", applyDir);
      // Esc closes the spiral modal (keyboard operability, #119)
      document.addEventListener("keydown", (e) => {
        if (e.key === "Escape") {
          const m = document.getElementById("spiral-modal");
          if (m && !m.classList.contains("hidden")) closeSpiralModal();
        }
      });
      const already = localStorage.getItem("molgang_age_ok") === "1";
      ageBox.checked = already;
      goBtn.disabled = !already;
      ageBox.addEventListener("change", () => {
        goBtn.disabled = !ageBox.checked;
        localStorage.setItem("molgang_age_ok", ageBox.checked ? "1" : "0");
      });
    }
  }
  boot();
})();
