// Bake one static PNG per slug from site/assets/<slug>/ using spine-player 3.8 in
// headless Chrome. Output: site/assets/<slug>/pose.png.
//
// Usage:
//   node tools/render_poses.js                 # render every prepared slug
//   node tools/render_poses.js c1001 c0002     # only these
//   node tools/render_poses.js --force         # re-render even if pose.png exists
//   node tools/render_poses.js --dsr 4         # force a fixed device scale factor
//
// Requires: puppeteer (already in package.json), and tools/spine-player.{js,css}
// must exist (one-shot setup: see tools/fetch_spine_player.sh equivalent in README).

const http = require("http");
const fs   = require("fs");
const fsp  = require("fs/promises");
const path = require("path");
const puppeteer = require("puppeteer");
const sharp = require("sharp");

const ROOT  = path.resolve(__dirname, "..");        // E7 Codex
const TOOLS = __dirname;
const SITE  = path.join(ROOT, "site");
const PORT  = 8742;

const TARGET_HEIGHT = 3120;    // pose.png height upper bound (px). The
                               // detail page displays the pose up to 78vh
                               // (~840 px on a 1080p screen, ~1684 px on a
                               // DPR=2 retina), and the hub card thumbnails
                               // are ~280 CSS px, so 3120 gives every view
                               // a clean downsample path.
// Earlier attempts here bumped puppeteer's deviceScaleFactor to "force a
// higher-resolution render". That was wrong: spine-player's WebGL canvas
// sets its backing buffer to `canvas.clientWidth` (CSS pixels) every
// frame in scene-renderer.js:9655-9659 — it does NOT multiply by DPR. So
// DSR only forced Chromium to bilinear-upscale a 600×780 spine render
// when capturing the screenshot. The picture looked higher-res but was
// just an upscale of a low-res draw. Render fidelity is now controlled
// by the CSS size of #stage in tools/render.html (currently 6000×7800),
// which is the canvas's clientWidth/Height and therefore the real WebGL
// backing-buffer size. DSR stays at 1.
const RENDER_DSR    = 1;
// Some skeletons auto-frame with so much padding that the trimmed
// character is shorter than TARGET_HEIGHT even at full canvas size. We
// could lanczos-upscale to fill TARGET_HEIGHT, but the upscale bakes in
// blur. Better to save at native size and let the browser downsample
// from whatever we have.
const ENLARGE_PAST_NATIVE = false;

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

// trimAndResize: returns {buf, trimmedHeight} so the caller can decide whether
// the source was big enough to downscale into TARGET_HEIGHT or whether a
// higher-DSR re-render is needed.
async function trimAndResize(raw) {
  try {
    const trimmed = await sharp(raw).trim({ threshold: 1 }).png().toBuffer();
    const meta    = await sharp(trimmed).metadata();
    const buf     = await sharp(trimmed)
      .resize({ height: TARGET_HEIGHT, fit: "inside",
               withoutEnlargement: !ENLARGE_PAST_NATIVE })
      .png()
      .toBuffer();
    return { buf, trimmedHeight: meta.height || 0 };
  } catch {
    return { buf: raw, trimmedHeight: 0 };
  }
}

async function captureAt(page, slug, _dsrIgnored) {
  // Puppeteer viewport must be at least as big as the stage CSS so the
  // canvas isn't constrained by the viewport. The stage in tools/render.html
  // is 4800×6240; we give the viewport a little headroom for body padding.
  await page.setViewport({ width: 4900, height: 6340, deviceScaleFactor: RENDER_DSR });
  await page.goto(`http://localhost:${PORT}/tools/render.html?slug=${encodeURIComponent(slug)}`,
                  { waitUntil: "domcontentloaded" });
  await page.waitForFunction(
    () => window.__renderState && (window.__renderState.ready || window.__renderState.error),
    { timeout: 30000 }
  );
  const result = await page.evaluate(() => window.__renderState);
  if (result.error) throw new Error(result.error);
  await new Promise(r => setTimeout(r, 120));
  const stage = await page.$("#stage canvas");
  if (!stage) throw new Error("no canvas in #stage");
  const raw = await stage.screenshot({ omitBackground: true });
  return { raw, result };
}

// Single-pass pipeline. Now that the stage CSS is large (6000×7800), the
// spine-player canvas backing buffer is large directly — no DSR escalation
// trick. We screenshot the canvas at DSR=1, trim to silhouette, and resize
// down to TARGET_HEIGHT when the trimmed source is taller.
async function renderOne(page, slug, _forcedDsrIgnored) {
  const { raw, result } = await captureAt(page, slug);
  const { buf, trimmedHeight } = await trimAndResize(raw);
  await fsp.writeFile(path.join(SITE, "assets", slug, "pose.png"), buf);
  return { anims: result.anims.length, skins: result.skins.length,
           dsr: RENDER_DSR, srcH: trimmedHeight, bounds: result.bounds };
}

(async () => {
  const args  = process.argv.slice(2);
  const force = args.includes("--force");
  let forcedDsr = 0;
  const dsrIdx = args.indexOf("--dsr");
  if (dsrIdx >= 0) forcedDsr = parseInt(args[dsrIdx + 1], 10);
  const onlySlugs = args.filter((a, i) => !a.startsWith("--") && args[i-1] !== "--dsr");
  const slugs = (onlySlugs.length ? onlySlugs : listSlugs())
    .filter(s => force || !fs.existsSync(path.join(SITE, "assets", s, "pose.png")));

  if (!slugs.length) { console.log("nothing to render."); process.exit(0); }
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
      const info = await renderOne(page, slug, forcedDsr);
      ok++;
      const b = info.bounds;
      const boundsStr = b ? ` bounds=${Math.round(b.w)}x${Math.round(b.h)}` : " bounds=none";
      console.log(`[ok]   ${slug}  anims=${info.anims} skins=${info.skins}` +
                  `  dsr=${info.dsr} srcH=${info.srcH}${boundsStr}`);
    } catch (e) {
      fail++; console.log(`[fail] ${slug}: ${e.message}`);
    }
  }
  console.log(`\n[summary] ${ok} ok · ${fail} failed · ${slugs.length} total`);
  await browser.close(); server.close();
  process.exit(fail ? 1 : 0);
})();
