// MOLGANG serverless QR helpers (ES module, dynamically imported by peer.js).
//
// drawQr(canvas, text) — renders the wallet-signed onboarding payload on the
// modal canvas. This build ships a clearly-labelled LEGIBLE TEXT fallback
// (not a scannable QR matrix): the payload is small JSON, so a second device
// can be onboarded by copying it manually until a real encoder lands. The
// payload itself is produced AND signed by the engine — this module never
// touches key material.
//
// scanQr(video, statusEl) — camera scanning is not available in this build;
// it rejects and the caller (peer.js scanPeerQr) surfaces the message.

export function drawQr(canvas, text) {
  const ctx = canvas.getContext("2d");
  // Crisp backing store independent of the 256px CSS size.
  const SIZE = 512;
  canvas.width = SIZE;
  canvas.height = SIZE;

  ctx.fillStyle = "#ffffff";
  ctx.fillRect(0, 0, SIZE, SIZE);

  // Header: make it unmistakable that this is the payload, not a QR matrix.
  ctx.fillStyle = "#0b0d12";
  ctx.font = "bold 20px ui-monospace, Menlo, monospace";
  ctx.fillText("MOLGANG peer payload", 18, 34);
  ctx.font = "13px ui-monospace, Menlo, monospace";
  ctx.fillStyle = "#444c60";
  ctx.fillText("(QR image fallback — copy this JSON to the", 18, 56);
  ctx.fillText("other device's “Scan peer” flow manually)", 18, 72);

  // Wrapped payload body.
  ctx.fillStyle = "#0b0d12";
  ctx.font = "12px ui-monospace, Menlo, monospace";
  const s = String(text == null ? "" : text);
  const WRAP = 46;              // chars per line at 12px mono in 512px − margins
  const LINE_H = 16;
  let y = 100;
  for (let i = 0; i < s.length && y < SIZE - 16; i += WRAP) {
    ctx.fillText(s.slice(i, i + WRAP), 18, y);
    y += LINE_H;
  }
  if (y >= SIZE - 16 && s.length > 0) {
    ctx.fillStyle = "#8a2d2d";
    ctx.fillText("… (truncated)", 18, SIZE - 8);
  }
}

export function scanQr(video, statusEl) {
  if (statusEl) statusEl.textContent = "camera scanning not available in this build";
  return Promise.reject(new Error("camera scanning not available in this build"));
}
