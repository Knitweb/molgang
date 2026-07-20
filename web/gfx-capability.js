/* gfx-capability.js — MOLGANG decentralized-app graphics guard.
 *
 * "Render well and fast on every system, and fall back where no suitable graphics are found."
 * The PWA's 3D views (three.js) need WebGL; without it they throw or show a black canvas. This
 * shared, dependency-free helper detects capability BEFORE a page builds its renderer, picks a
 * quality tier so it stays fast on weak devices, and shows a friendly fallback where 3D is
 * impossible — so the decentralized app degrades gracefully on any phone, laptop or PC.
 *
 * Load as a plain <script> (not a module) in <head> so window.MolgangGfx is ready before the
 * page's module runs:  <script src="gfx-capability.js"></script>
 */
(function () {
  "use strict";

  function detectWebGL2() {
    try {
      var c = document.createElement("canvas");
      return !!(window.WebGL2RenderingContext && c.getContext("webgl2"));
    } catch (e) { return false; }
  }
  function detectWebGL() {
    try {
      var c = document.createElement("canvas");
      return !!(window.WebGLRenderingContext &&
        (c.getContext("webgl") || c.getContext("experimental-webgl")));
    } catch (e) { return false; }
  }

  var cap = null;
  function detect() {
    if (cap) return cap;
    cap = {
      webgpu: ("gpu" in navigator),
      webgl2: detectWebGL2(),
      webgl: false,
    };
    cap.webgl = cap.webgl2 || detectWebGL();
    // a quick device-class hint for the quality tier
    cap.cores = navigator.hardwareConcurrency || 4;
    cap.memory = navigator.deviceMemory || 4;          // GB, coarse
    cap.mobile = /Mobi|Android|iPhone|iPad/i.test(navigator.userAgent || "");
    try { localStorage.setItem("molgang_gfx", JSON.stringify(cap)); } catch (e) {}
    return cap;
  }

  /* 'high' | 'medium' | 'low' — how hard a 3D page should push this device. */
  function tier() {
    var c = detect();
    if (!c.webgl) return "none";
    var score = 0;
    if (c.webgl2) score += 2;
    if (c.webgpu) score += 1;
    if (c.cores >= 8) score += 2; else if (c.cores >= 4) score += 1;
    if (c.memory >= 8) score += 2; else if (c.memory >= 4) score += 1;
    if (c.mobile) score -= 2;
    if (score >= 5) return "high";
    if (score >= 2) return "medium";
    return "low";
  }

  /* Renderer hints per tier — pass into new THREE.WebGLRenderer / setPixelRatio. */
  function rendererHints() {
    var t = tier();
    return {
      tier: t,
      antialias: t === "high",
      pixelRatio: t === "high" ? Math.min(devicePixelRatio || 1, 2)
        : t === "medium" ? Math.min(devicePixelRatio || 1, 1.25) : 1,
      shadows: t === "high",
      maxLights: t === "high" ? 4 : t === "medium" ? 2 : 1,
    };
  }

  /* Show a friendly fallback covering the page; hide a canvas if one is given. */
  function showFallback(canvasEl, message) {
    if (canvasEl) canvasEl.style.display = "none";
    if (document.getElementById("molgang-gfx-fallback")) return;
    var d = document.createElement("div");
    d.id = "molgang-gfx-fallback";
    d.style.cssText = "position:fixed;inset:0;z-index:99999;display:flex;align-items:center;" +
      "justify-content:center;padding:24px;background:radial-gradient(1200px 800px at 50% 0," +
      "#141824,#0a0c12);font-family:'Noto Sans',Arial,sans-serif;color:#e6ebf5";
    d.innerHTML =
      '<div style="max-width:540px;text-align:center;border:1px solid #2a3550;border-radius:16px;' +
      'padding:32px;background:rgba(20,26,42,.7)">' +
      '<div style="font-size:30px;font-weight:800;letter-spacing:2px;color:#7fd4ff">MOLGANG</div>' +
      '<h2 style="margin:.3em 0 .5em;font-size:19px;color:#fff">3D view unavailable on this device</h2>' +
      '<p style="line-height:1.55;color:#c4cee0">' + (message ||
        "This view needs <b>WebGL</b>, which your browser or device doesn't provide.") + "</p>" +
      '<p style="font-size:13px;color:#8fa0bd">Try a recent Chrome, Firefox, Edge or Safari, or ' +
      'enable hardware acceleration. The rest of MOLGANG still works — ' +
      '<a href="./" style="color:#7fd4ff">back to the bar</a>.</p></div>';
    document.body.appendChild(d);
  }

  /* Gate a 3D page: returns true if WebGL is available (with capability + hints), else shows the
     fallback and returns false. Call this BEFORE building a THREE.WebGLRenderer. */
  function guard(canvasEl, message) {
    var c = detect();
    if (!c.webgl) {
      showFallback(canvasEl, message);
      return false;
    }
    return true;
  }

  window.MolgangGfx = {
    detect: detect,
    tier: tier,
    rendererHints: rendererHints,
    guard: guard,
    showFallback: showFallback,
  };
  try {
    var c = detect();
    console.log("[MOLGANG] gfx capability:", "webgl2=" + c.webgl2, "webgpu=" + c.webgpu,
      "tier=" + tier());
  } catch (e) {}
})();
