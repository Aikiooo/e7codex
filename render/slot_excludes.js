// Shared loader for site/data/slot_excludes.json — the per-slug list of
// permanently-excluded slot names (broken/junk assets). Consumed by the
// offline bake (render_poses.js / render_thumbs.js) so excluded slots are
// stripped from pose.png + thumb.png; the live viewer (site/viewer.html)
// reads the same JSON directly at runtime.
//
// Exact slot names are converted to anchored, regex-escaped patterns so they
// can ride the existing render.html `?ehide=` mechanism (which compiles each
// comma-separated, URL-encoded entry to `new RegExp(decoded, "i")`).

const fs   = require("fs");
const path = require("path");

const SITE = path.resolve(__dirname, "..", "site");
const EXCLUDES_PATH = path.join(SITE, "data", "slot_excludes.json");

let _cache = null;
function loadExcludes() {
  if (_cache) return _cache;
  try {
    const raw = JSON.parse(fs.readFileSync(EXCLUDES_PATH, "utf-8"));
    _cache = {};
    for (const k of Object.keys(raw)) {
      if (k.startsWith("_")) continue;            // skip _doc
      if (Array.isArray(raw[k])) _cache[k] = raw[k].filter(s => typeof s === "string" && s.length);
    }
  } catch {
    _cache = {};
  }
  return _cache;
}

// Exact names for a slug (array, possibly empty).
function excludesFor(slug) {
  return loadExcludes()[slug] || [];
}

function escapeRegex(s) {
  return s.replace(/[.*+?^${}()|[\]\\/]/g, "\\$&");
}

// Build the `ehide=` query VALUE (already URL-encoded, comma-joined) for a
// slug's excludes, or "" when it has none. Each exact name becomes the
// anchored pattern ^<escaped>$ so e.g. "155" doesn't also match "1155".
function ehideParamFor(slug) {
  const names = excludesFor(slug);
  if (!names.length) return "";
  return names.map(n => encodeURIComponent("^" + escapeRegex(n) + "$")).join(",");
}

module.exports = { loadExcludes, excludesFor, ehideParamFor };
