// MOLGANG client config — loaded BEFORE app.js.
//
// The static UI (e.g. https://5mart.ml/molgang/) and the Python API can live on
// different hosts. Plain shared webhosting can serve these files but CANNOT keep
// `molgang serve` running, so the API usually lives on a tiny always-on box
// (Fly.io / Render / a VPS). Point the UI at it here.
//
// Leave MOLGANG_API empty ("") for SAME-ORIGIN — correct when the API is reverse-
// proxied under the same path (e.g. nginx `location /molgang/`), or when you run
// `molgang serve` which serves this UI itself.
//
// Otherwise set the FULL origin of your backend (no trailing slash), e.g.:
//   window.MOLGANG_API = "https://molgang.fly.dev";
// The backend must send CORS headers (molgang serve does, see --cors / always-on).
//
// >>> OWNER: fill this in once the backend is up, then re-upload config.js. <<<
window.MOLGANG_API = "";   // e.g. "https://molgang.fly.dev"

// ── P2P bootstrap nodes ──────────────────────────────────────────────────────
// The chem-field knowledge graph and the game sync from these peers, first
// reachable wins, then the same-origin snapshot. knitweb.art = node 1, 5mart.ml =
// node 2. A molgang-served node sends CORS, so cross-origin retrieval works.
// (knitweb.art is pending domain verification; until it resolves, node 2 + the
//  local snapshot serve the graph — the waterfall degrades gracefully.)
window.MOLGANG_PEERS = [
  { name: "knitweb.art", base: "https://knitweb.art/chem" },
  { name: "5mart.ml",    base: "https://5mart.ml/molgang" }
];
window.MOLGANG_GRAPH_ENDPOINTS = [
  "https://knitweb.art/chem/molgang/explorer-graph.json",
  "https://5mart.ml/molgang/explorer-graph.json",
  "explorer-graph.json",
  "molgang/explorer-graph.json"
];

// ── Fleet scoreboard (dashboard.html, #131) ──────────────────────────────────
// List the relay API bases the public "Road to 1M" dashboard should union across
// for a cross-region total (dedup by pubkey — a wallet on two relays counts once).
// Each base must serve /api/relay/telemetry with CORS (molgang serve + the PHP
// relay both do). Leave EMPTY to show only this origin's single-scope numbers.
window.MOLGANG_FLEET_RELAYS = [
  // "https://eu.5mart.ml/molgang/api/relay",
  // "https://us.example/molgang/api/relay",
];
