// Bake a character-only thumb.png per slug from site/assets/<slug>/ using
// spine-player 3.8 in headless Chrome. Sibling of render_poses.js; the
// difference is that tools/render.html is called with `&thumb=1`, which
// wipes FX/aura/backdrop slot attachments from every skin before the
// player computes its auto-fit viewport — so the result is a tightly
// framed character with no aura/halo/backdrop bleed.
//
// Output: site/assets/<slug>/thumb.png (only when the slug actually has
// any FX slots; otherwise thumb would be byte-identical to pose.png and
// we skip it. build_index.py + index.html fall back to pose.png when
// thumb.png is absent).
//
// Usage:
//   node tools/render_thumbs.js                 # render every prepared slug w/ FX slots
//   node tools/render_thumbs.js c5070 c1148     # only these
//   node tools/render_thumbs.js --force         # re-render even if thumb.png exists
//   node tools/render_thumbs.js --all           # render even slugs with zero FX hits
//                                                 (produces a file identical to pose.png;
//                                                 useful only for debugging)
//
// The hide regex lives in tools/render.html (kept there so the browser
// pass sees the same patterns). This file mirrors the regex purely as a
// pre-filter so we never spin up a Puppeteer page for a no-op slug.

const http = require("http");
const fs   = require("fs");
const fsp  = require("fs/promises");
const path = require("path");
const puppeteer = require("puppeteer");
const sharp = require("sharp");

const ROOT  = path.resolve(__dirname, "..");
const TOOLS = __dirname;
const SITE  = path.join(ROOT, "site");
const PORT  = 8743;                  // distinct from render_poses.js (8742)

const TARGET_HEIGHT = 3120;          // match render_poses.js — the hub card
                                     // displays the thumb at ~280 CSS px so
                                     // 3120 gives every device a clean
                                     // downsample path.
const RENDER_DSR    = 1;             // CSS stage size drives fidelity, not DSR

// Alpha threshold for the visible-character bounding box. sharp.trim's
// color-distance metric treats anything closer to fully transparent than
// this as "background" — threshold:10 cuts the semi-transparent halo pixels
// that threshold:1 keeps. Pose renders stay on the permissive trim:1 because
// the detail page shows the full art; thumbs are explicitly meant to be tight,
// so we trim aggressively at bake time and drop the runtime trim sidecar.
const DEFAULT_THRESHOLD = 10;

// Per-slug overrides. Identical shape to the table that used to live in
// tools/compute_trim_data.js — see that file's history for tuning notes.
//   N                      sharp.trim with threshold N
//   { threshold, alphaOnly:true }       pure alpha-channel bbox (for colored
//                                       near-transparent fx whose RGB defeats
//                                       sharp's color-distance metric).
//   { ..., percentile:0–1 }             marginal-histogram trim to reject the
//                                       outermost fraction of alpha>threshold
//                                       pixels (isolated blood drop on c6050).
//   { ..., pad: 0.01–0.03 }             outward expansion after percentile cut
//                                       to recover edges over-clipped by it.
const SLUG_THRESHOLDS = {
  "c2046_s01": 75,                                              // speech bubble alpha
  "c2076_1":   { threshold: 75, alphaOnly: true },              // colored glow
  "c4052":     20,                                              // barely-visible artifact
  "c2009":     40,                                              // reddish aura
  "c6005":     75,                                              // light rays
  "c5070":     75,                                              // smoke
  "c1148":     { threshold: 20, alphaOnly: true },              // icy blue aura
  "c6050":     { threshold: 10, alphaOnly: true, percentile: 0.999, pad: 0.015 },  // blood drop
};

function resolveTrim(slug) {
  const ov = SLUG_THRESHOLDS[slug];
  if (ov === undefined) return { threshold: DEFAULT_THRESHOLD, alphaOnly: false, percentile: 1, pad: 0 };
  if (typeof ov === "object") return {
    threshold:  ov.threshold,
    alphaOnly:  ov.alphaOnly  ?? false,
    percentile: ov.percentile ?? 1,
    pad:        ov.pad        ?? 0,
  };
  return { threshold: ov, alphaOnly: false, percentile: 1, pad: 0 };
}

// Alpha-channel bounding box on a raw RGBA buffer. Mirrors the implementation
// previously in tools/compute_trim_data.js — we need it here because some
// SLUG_THRESHOLDS entries set alphaOnly:true (colored fx that sharp.trim's
// color-distance metric can't separate from the character).
async function alphaBbox(buf, alphaThreshold, percentile = 1.0) {
  const { data, info } = await sharp(buf).raw().toBuffer({ resolveWithObject: true });
  const { width, height, channels } = info;
  const A = channels - 1;

  if (percentile >= 1.0) {
    let minX = width, maxX = -1, minY = height, maxY = -1;
    for (let y = 0; y < height; y++) {
      for (let x = 0; x < width; x++) {
        if (data[(y * width + x) * channels + A] > alphaThreshold) {
          if (x < minX) minX = x;
          if (x > maxX) maxX = x;
          if (y < minY) minY = y;
          if (y > maxY) maxY = y;
        }
      }
    }
    if (maxX < 0) return null;
    return { l: minX, t: minY, w: maxX - minX + 1, h: maxY - minY + 1, W: width, H: height };
  }

  const xHist = new Int32Array(width);
  const yHist = new Int32Array(height);
  let total = 0;
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      if (data[(y * width + x) * channels + A] > alphaThreshold) { xHist[x]++; yHist[y]++; total++; }
    }
  }
  if (!total) return null;
  const margin = Math.max(1, Math.floor(total * (1 - percentile) / 2));
  let cum = 0, minX = 0;
  for (let x = 0; x < width;  x++) { cum += xHist[x]; if (cum > margin) { minX = x; break; } }
  cum = 0; let maxX = width - 1;
  for (let x = width - 1; x >= 0; x--) { cum += xHist[x]; if (cum > margin) { maxX = x; break; } }
  cum = 0; let minY = 0;
  for (let y = 0; y < height; y++) { cum += yHist[y]; if (cum > margin) { minY = y; break; } }
  cum = 0; let maxY = height - 1;
  for (let y = height - 1; y >= 0; y--) { cum += yHist[y]; if (cum > margin) { maxY = y; break; } }
  return { l: minX, t: minY, w: maxX - minX + 1, h: maxY - minY + 1, W: width, H: height };
}

// Apply the smart-crop to a buffer. Falls back to the original buffer if
// nothing visible is detected (which would only happen on a fully-blank image).
async function smartCrop(buf, opts) {
  const { threshold, alphaOnly, percentile, pad } = opts;
  if (alphaOnly) {
    const bb = await alphaBbox(buf, threshold, percentile);
    if (!bb) return buf;
    let { l, t, w, h, W, H } = bb;
    if (pad > 0) {
      const padX = Math.round(W * pad);
      const padY = Math.round(H * pad);
      const r = Math.min(W, l + w + padX);
      const b = Math.min(H, t + h + padY);
      l = Math.max(0, l - padX);
      t = Math.max(0, t - padY);
      w = r - l;
      h = b - t;
    }
    return sharp(buf).extract({ left: l, top: t, width: w, height: h }).png().toBuffer();
  }
  return sharp(buf).trim({ threshold }).png().toBuffer();
}

// Mirror the slot-name regex in tools/render.html exactly. The pre-filter
// uses this to skip slugs with zero FX hits so we don't pay the spine-player
// init cost for a no-op render. If you tweak one, tweak the other.
// Kept in lockstep with tools/render.html — see comments there for the why
// behind each pattern. If you tweak one, tweak the other.
const HIDE_PREFIX = /^(bground|bgshadow|bg(?![a-z])|back(?![a-z])|cloud|sky|stage|background|effect|eff(?:[/_]|$)|eff\d|ef[/_]|ef\d|efef|d_|\d+_chick|ttt\d|sdss|bbfire|bfire|pfire|lfire|dfire|afire|panicfx|wingsFx|flare\d?|spark|particle|smoke|dust|aura|glow|halo|light[_]?\d|fx|stone(?:[\d _]|fx|bb|y\d)|maple_?\d|star[_\d]|fl_\d|fly\d|ss_\d{4,}|\d+$|\d+(?:particle|eff|fx|spark|smoke|flame|aura))/i;
const HIDE_FX_SUFFIX = /[a-z_ ]fx[a-z\d]*$|_particle\d*\b|[a-z_ \d\/]eff\d*$/i;
const HIDE_FX_TOKEN  = /(?:[\/_](?:particle|spark|smoke|flame|aura|glow|halo|flare|effect)(?:[\d_\/]|$))|(?:(?:^|[\s\/_])(?:eff|fx)[\/_])/i;
// Mirror SLUG_EXTRA_HIDE in tools/render.html. The browser uses the full
// table to decide what to strip; this Node-side copy is purely for the
// pre-filter (countHits) so opt-in slugs aren't skipped over.
const SLUG_EXTRA_HIDE = {
  "c1067_s02": [
    /^glo_\d+$/i,
    /^spt(?:_\d+(?:_\d+)?)?$/i,
    /^balloon(?:_\d+)?$/i,
    /^b_star_\d+$/i,
    /^rrione_\d+$/i,
    /^ttt$/i,
    /^bone88dg$/i,
    /^white$/i,
  ],
};
function shouldHide(name, protectNumeric, slug) {
  const extras = SLUG_EXTRA_HIDE[slug];
  if (extras) for (const re of extras) if (re.test(name)) return true;
  if (protectNumeric && /^\d+$/.test(name)) return false;
  return HIDE_PREFIX.test(name) || HIDE_FX_SUFFIX.test(name) || HIDE_FX_TOKEN.test(name);
}

// Mirror of tools/render.html runtime check. Rigs whose `default` skin is
// >30% numerically-named slots treat those as body (c1172 / c5033 / c6050 /
// c2112_s01_1 / npc1157 / etc.), so we suppress the `^\d+$` hide rule for
// them to avoid stripping the body in thumb mode.
function computeProtectNumeric(j) {
  const def = (j.skins || []).find(s => s && s.name === "default");
  if (!def) return false;
  const atts = def.attachments || {};
  const total = Object.keys(atts).length;
  if (!total) return false;
  let numeric = 0;
  for (const k of Object.keys(atts)) if (/^\d+$/.test(k)) numeric++;
  return numeric / total > 0.30;
}

const MIME = {".html":"text/html",".js":"application/javascript",".css":"text/css",
              ".json":"application/json",".png":"image/png",".atlas":"text/plain"};

function makeServer() {
  return http.createServer((req, res) => {
    let url = decodeURIComponent(req.url.split("?")[0]);
    if (url === "/") url = "/tools/render.html";
    const fp = path.normalize(path.join(ROOT, url));
    if (!fp.startsWith(ROOT) || !fs.existsSync(fp) || fs.statSync(fp).isDirectory()) {
      res.writeHead(404); return res.end("404 " + url);
    }
    res.writeHead(200, { "Content-Type": MIME[path.extname(fp).toLowerCase()] || "application/octet-stream",
                         "Access-Control-Allow-Origin": "*" });
    fs.createReadStream(fp).pipe(res);
  });
}

function listSlugs() {
  const dir = path.join(SITE, "assets");
  if (!fs.existsSync(dir)) return [];
  return fs.readdirSync(dir).filter(s => {
    const d = path.join(dir, s);
    return fs.statSync(d).isDirectory()
        && fs.existsSync(path.join(d, s + ".json"))
        && fs.existsSync(path.join(d, s + ".atlas"))
        && fs.existsSync(path.join(d, s + ".png"));
  });
}

// Pre-filter: count how many slot names match the hide regex. Lets us
// skip rendering for rigs that would produce a thumb identical to pose.png.
function countHits(slug) {
  try {
    const f = path.join(SITE, "assets", slug, slug + ".json");
    const j = JSON.parse(fs.readFileSync(f, "utf-8"));
    const protectNumeric = computeProtectNumeric(j);
    const slots = (j.slots || []).map(s => s.name);
    return slots.filter(n => shouldHide(n, protectNumeric, slug)).length;
  } catch {
    return 0;
  }
}

async function trimAndResize(raw, slug) {
  try {
    const trimmed = await smartCrop(raw, resolveTrim(slug));
    const meta    = await sharp(trimmed).metadata();
    const buf     = await sharp(trimmed)
      .resize({ height: TARGET_HEIGHT, fit: "inside", withoutEnlargement: true })
      .png()
      .toBuffer();
    return { buf, trimmedHeight: meta.height || 0 };
  } catch {
    return { buf: raw, trimmedHeight: 0 };
  }
}

async function captureAt(page, slug) {
  await page.setViewport({ width: 4900, height: 6340, deviceScaleFactor: RENDER_DSR });
  await page.goto(`http://localhost:${PORT}/tools/render.html?slug=${encodeURIComponent(slug)}&thumb=1`,
                  { waitUntil: "domcontentloaded" });
  // 60s is generous — most rigs settle in under 5s, but a handful of heavy
  // 2.1.27 rigs (c1153_s01, c1169, c2079_s01, c1180_1, c2113, …) cross the
  // 30s ceiling render_poses.js uses, and a few cross 45s during batch
  // runs (CPU contention from puppeteer + sharp). Cheap to widen here.
  await page.waitForFunction(
    () => window.__renderState && (window.__renderState.ready || window.__renderState.error),
    { timeout: 60000 }
  );
  const result = await page.evaluate(() => window.__renderState);
  if (result.error) throw new Error(result.error);
  await new Promise(r => setTimeout(r, 120));
  const stage = await page.$("#stage canvas");
  if (!stage) throw new Error("no canvas in #stage");
  const raw = await stage.screenshot({ omitBackground: true });
  return { raw, result };
}

async function renderOne(page, slug) {
  const { raw, result } = await captureAt(page, slug);
  const { buf, trimmedHeight } = await trimAndResize(raw, slug);
  await fsp.writeFile(path.join(SITE, "assets", slug, "thumb.png"), buf);
  return { hideCount: result.hideCount || 0, srcH: trimmedHeight, bounds: result.bounds };
}

(async () => {
  const args  = process.argv.slice(2);
  const force = args.includes("--force");
  const all   = args.includes("--all");
  const onlySlugs = args.filter(a => !a.startsWith("--"));

  let slugs = (onlySlugs.length ? onlySlugs : listSlugs())
    .filter(s => force || !fs.existsSync(path.join(SITE, "assets", s, "thumb.png")));

  // Pre-filter on hit count unless --all or explicit slug list.
  let preFiltered = 0;
  if (!all && !onlySlugs.length) {
    const filtered = [];
    for (const s of slugs) {
      if (countHits(s) > 0) filtered.push(s);
      else preFiltered++;
    }
    slugs = filtered;
  }

  if (!slugs.length) {
    console.log(preFiltered ? `nothing to render (${preFiltered} slugs have no FX slots — they fall back to pose.png).`
                            : "nothing to render.");
    process.exit(0);
  }
  if (!fs.existsSync(path.join(TOOLS, "spine-player.js"))) {
    console.error("missing tools/spine-player.js — see README for the one-shot fetch."); process.exit(2);
  }

  const server = makeServer();
  await new Promise(r => server.listen(PORT, r));
  const browser = await puppeteer.launch({ headless: "new" });
  const page    = await browser.newPage();

  let ok = 0, fail = 0;
  for (const slug of slugs) {
    try {
      const info = await renderOne(page, slug);
      ok++;
      const b = info.bounds;
      const boundsStr = b ? ` bounds=${Math.round(b.w)}x${Math.round(b.h)}` : " bounds=none";
      console.log(`[ok]   ${slug}  hide=${info.hideCount} srcH=${info.srcH}${boundsStr}`);
    } catch (e) {
      fail++; console.log(`[fail] ${slug}: ${e.message}`);
    }
  }
  const skippedNote = preFiltered ? ` · ${preFiltered} skipped (no FX slots)` : "";
  console.log(`\n[summary] ${ok} ok · ${fail} failed · ${slugs.length} attempted${skippedNote}`);
  await browser.close(); server.close();
  process.exit(fail ? 1 : 0);
})();
