// shared.js — tiny shared runtime helpers for index.html + viewer.html.
// No build step: a plain classic script that exposes one global `E7` object.
// Loaded via <script src="shared.js"> BEFORE each page's inline script.
"use strict";
const E7 = (() => {
  // Local-dev hostnames use relative asset paths (python -m http.server from
  // site/, file://, or LAN IPs so the viewer works across a local network
  // without hitting CDN CORS); everything else — production e7codex.com,
  // Pages preview URLs — uses the R2-backed CDN. Single source of truth:
  // index.html keys voice clips off this, viewer.html keys spine rigs off it.
  const h = location.hostname;
  const isLocal = h === "localhost" || h === "127.0.0.1" || h === "" ||
    /^192\.168\.|^10\.|^172\.(1[6-9]|2\d|3[01])\./.test(h);
  const CDN = "https://assets.e7codex.com";
  const escapeHtml = (s) => String(s ?? "").replace(/[&<>"']/g,
    c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  return {
    isLocal,
    spineBase: isLocal ? "assets" : CDN,
    voiceBase: isLocal ? "voice" : CDN + "/voice",
    escapeHtml,
  };
})();
