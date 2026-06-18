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
