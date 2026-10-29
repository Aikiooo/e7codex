// Bake one PNG per staged background (site/assets/_bg_src/<name>/) with
// spine-player 3.8 in headless Chrome. Output: site/assets/_bg/<name>.png
// plus a _th thumbnail.
//
//   node render/bg/render_backgrounds.js                 # every staged background
//   node render/bg/render_backgrounds.js arena minetown  # only these
//   node render/bg/render_backgrounds.js --force         # re-render existing
//
// The input rigs come from render/bg/bg_stage.py, which merges a background's Spine
// layer stack into a single skeleton (slot order == draw order) — see that file
// for the format notes. Requires render/bg/render_bg.html + render/vendor/spine-player.js.

const http = require("http");
const fs   = require("fs");
const fsp  = require("fs/promises");
const path = require("path");
const puppeteer = require("puppeteer");
const sharp = require("sharp");

const ROOT  = path.resolve(__dirname, "..", "..");   // E7 Codex
const SRC   = path.join(ROOT, "site", "assets", "_bg_src");
const OUT   = path.join(ROOT, "site", "assets", "_bg");
const PACK_OUT = path.join(ROOT, "site", "assets", "_bg_packs");
const PACK_LIST = path.join(ROOT, "site", "data", "bg_packs.json");
const PORT  = 8747;

// Long-side cap for the gallery still. The dump packs every background atlas at
// 2/3 scale, so a background's native resolution is its union bounds in atlas
// units; 1600 keeps a comfortable downscale path for any screen without
// upscaling past what the texture actually holds.
const FULL_LONG = 1600;
const THUMB_LONG = 480;
// "scene" keeps the game's 16:9 frame on the drawn content (the gallery view);
// "content" crops to the densest content; "full" keeps the spine auto-fit union.
let RENDER_MODE = "scene";

const MIME = { ".html": "text/html", ".js": "application/javascript", ".css": "text/css",
               ".json": "application/json", ".png": "image/png", ".atlas": "text/plain" };

// How many dump-side layers went into a staged scene (from the `_bg` block
// render/bg/bg_stage.py leaves in the merged JSON).
function stagedLayerCount(name) {
  try {
    const j = JSON.parse(fs.readFileSync(path.join(SRC, name, name + ".json"), "utf-8"));
    return (j._bg && j._bg.layers ? j._bg.layers.length : 0);
  } catch { return 0; }
}

function makeServer() {
  return http.createServer((req, res) => {
    let url = decodeURIComponent(req.url.split("?")[0]);
    const fp = path.normalize(path.join(ROOT, url));
    if (!fp.startsWith(ROOT) || !fs.existsSync(fp) || fs.statSync(fp).isDirectory()) {
      res.writeHead(404); return res.end("404 " + url);
    }
    res.writeHead(200, { "Content-Type": MIME[path.extname(fp).toLowerCase()] || "application/octet-stream",
                         "Access-Control-Allow-Origin": "*" });
    fs.createReadStream(fp).pipe(res);
  });
}

function listStaged() {
  if (!fs.existsSync(SRC)) return [];
  // The atlas is self-describing: it names its own page textures, and with
  // write_multi_atlas() those are `<scene>__<atlas>.png` (one per page), so a
  // bare `<scene>.png` no longer exists. Requiring it here silently matched
  // zero scenes.
  return fs.readdirSync(SRC).filter(s => {
    const d = path.join(SRC, s);
    return fs.statSync(d).isDirectory()
        && fs.existsSync(path.join(d, s + ".json"))
        && fs.existsSync(path.join(d, s + ".atlas"));
  });
}

// Crop box for a rendered scene. Spine auto-frames on the union of every
// slot's bounds, so ONE layer parked away from the scene (a stray prop placed
// by a guessy assignment, or a sibling page's region) stretches the frame and
// leaves a dead band in the middle of the picture — which an alpha-boundary
// crop dutifully keeps, because the band is inside the boundary.
//
// So trim by content density instead: count opaque pixels per row and per
// column and keep the span where either is at least a fifth of its peak. A
// full-bleed scene loses nothing (every row is at the peak); a scene with an
// outlier collapses onto its real content. `opaqueFrac` is then measured
// inside the box, which is what separates a real scene from a handful of props
// floating in empty space.
async function contentBox(raw) {
  const { data, info } = await sharp(raw).ensureAlpha().raw()
    .toBuffer({ resolveWithObject: true });
  const W = info.width, H = info.height;
  const row = new Int32Array(H), col = new Int32Array(W);
  let rowMax = 0, colMax = 0, opaque = 0;
  for (let y = 0; y < H; y++) {
    let r = 0;
    const base = y * W * 4;
    for (let x = 0; x < W; x++) {
      if (data[base + x * 4 + 3] > 200) { r++; col[x]++; }
    }
    row[y] = r;
    if (r > rowMax) rowMax = r;
  }
  for (let x = 0; x < W; x++) if (col[x] > colMax) colMax = col[x];
  const rThr = rowMax * 0.2, cThr = colMax * 0.2;
  let top = 0, bottom = H - 1, left = 0, right = W - 1;
  while (top < bottom && row[top] < rThr) top++;
  while (bottom > top && row[bottom] < rThr) bottom--;
  while (left < right && col[left] < cThr) left++;
  while (right > left && col[right] < cThr) right--;
  const width = right - left + 1, height = bottom - top + 1;
  for (let y = top; y <= bottom; y++) {
    const base = y * W * 4;
    for (let x = left; x <= right; x++) if (data[base + x * 4 + 3] > 200) opaque++;
  }
  return { left, top, width, height, opaqueFrac: opaque / (width * height) };
}

// Full-frame box: the spine auto-fit viewport itself, i.e. the union of every
// part's bounds. This is the BATTLE framing — the scene as the game lays it out
// — and it is what the in-game Hero View "Background Pack" pans and zooms
// (db/item_material_bgpack.db scale/offset). Content-density cropping is right
// for a gallery thumbnail but wrong here: it turns the window into a rectangle
// with cut edges, which no longer matches the game's frame.
async function fullBox(raw, thr = 8) {
  const { data, info } = await sharp(raw).ensureAlpha().raw()
    .toBuffer({ resolveWithObject: true });
  const W = info.width, H = info.height;
  let opaque = 0, left = W, top = H, right = -1, bottom = -1;
  for (let y = 0; y < H; y++) {
    const base = y * W * 4;
    for (let x = 0; x < W; x++) {
      if (data[base + x * 4 + 3] > thr) {
        opaque++;
        if (x < left) left = x;
        if (x > right) right = x;
        if (y < top) top = y;
        if (y > bottom) bottom = y;
      }
    }
  }
  if (right < left) return { left: 0, top: 0, width: W, height: H, opaqueFrac: 0 };
  const width = right - left + 1, height = bottom - top + 1;
  return { left, top, width, height, opaqueFrac: opaque / (width * height) };
}

// ── Hero View "Background Pack" framing ─────────────────────────────────────
// db/item_material_bgpack.db frames a scene for the in-game Hero View: a 16:9
// window over the scene's battle framing (the union of its parts), zoomed by
// `scale` and panned by `offset`. Verified against captures for scale and for
// the vertical pan on `scale`/centred rows; the offset's exact origin is still
// being pinned down (a scene whose offset x is 3600 renders centred), so the pan
// is applied relative to the union centre and logged for comparison.
function packWindow(bounds, canvas, solid, pack) {
  // The pack zooms INTO the scene's own frame (which is cover-fit 16:9, see
  // sceneWindow), so the window is that frame divided by the pack scale, still
  // 16:9, then panned by the row's offset.
  const s = Math.min(canvas.width / bounds.w, canvas.height / bounds.h);
  const f = sceneWindow(canvas, solid);
  const scale = pack.scale || 1;
  const width = Math.max(16, Math.round(f.width / scale));
  const height = Math.max(9, Math.round(f.height / scale));
  const cx = f.left + f.width / 2 + (pack.offset?.[0] || 0) * s;
  const cy = f.top + f.height / 2 + (pack.offset?.[1] || 0) * s;
  return {
    left: Math.max(0, Math.round(cx - width / 2)),
    top: Math.max(0, Math.round(cy - height / 2)),
    width, height,
  };
}

// The frame, chosen by search rather than by heuristic: the LARGEST 16:9 window
// whose area is (almost) entirely painted. That is the property we actually
// want — "matches the background content size" *and* "full-bleed" — and it can
// be measured, so it does not need inferring.
//
// It runs on a downscaled solid/empty mask with a summed-area table, so the
// whole scan is a few hundred thousand integer ops: for each candidate width
// (largest first) find the best placement, and take the first width that clears
// the coverage target. Returns canvas pixels; callers scale nothing.
//
// Why not the alpha bbox or a row/column span: a scene is often not rectangular
// (a palace's ceiling and outer columns are wider than its floor), so a bbox or
// a span-product still hangs over uncovered corners — the wedges — and can even
// include a transparent band elsewhere (arena).
async function bestWindow(raw, target = 0.995) {
  const cm = await sharp(raw).metadata();
  const W = cm.width, H = cm.height;
  const MW = 480;
  const MH = Math.max(1, Math.round(H * MW / W));
  const mask = await sharp(raw).ensureAlpha().extractChannel("alpha")
    .resize(MW, MH, { fit: "fill" }).raw().toBuffer();
  const ii = new Int32Array((MW + 1) * (MH + 1));
  for (let y = 0; y < MH; y++) {
    let rowSum = 0;
    for (let x = 0; x < MW; x++) {
      rowSum += mask[y * MW + x] > 40 ? 1 : 0;   // >40: semi-transparent plates count as painted; only true holes (alpha 0) do not
      ii[(y + 1) * (MW + 1) + (x + 1)] = ii[y * (MW + 1) + (x + 1)] + rowSum;
    }
  }
  const frac = (x, y, w, h) => {
    const x2 = x + w, y2 = y + h;
    const s = ii[y2 * (MW + 1) + x2] - ii[y * (MW + 1) + x2]
            - ii[y2 * (MW + 1) + x] + ii[y * (MW + 1) + x];
    return s / (w * h);
  };
  let best = null;
  for (let w = MW; w >= 96; w -= 4) {
    const h = Math.round(w * 9 / 16);
    if (h > MH) continue;
    let bestF = -1, bx = 0, by = 0;
    for (let y = 0; y + h <= MH; y += 2) {
      for (let x = 0; x + w <= MW; x += 2) {
        const f = frac(x, y, w, h);
        if (f > bestF) { bestF = f; bx = x; by = y; }
      }
    }
    if (bestF >= target) { best = { x: bx, y: by, w, h, coverage: bestF }; break; }
  }
  if (!best) return null;
  const s = W / MW;
  return {
    left: Math.max(0, Math.round(best.x * s)),
    top: Math.max(0, Math.round(best.y * s)),
    width: Math.round(best.w * s),
    height: Math.round(best.h * s),
    opaqueFrac: best.coverage,
  };
}

// Robust "covered core": the LONGEST CONTIGUOUS span of columns and of rows
// whose solid-pixel count clears a small floor. Fallback only — bestWindow()
// answers the same question properly; this is kept for a scene where no window
// reaches the coverage target (then the widest plausible frame is better than
// failing the bake).
async function coreBox(raw, thr = 200, floor = 0.06) {
  const { data, info } = await sharp(raw).ensureAlpha().raw()
    .toBuffer({ resolveWithObject: true });
  const W = info.width, H = info.height;
  const col = new Int32Array(W), row = new Int32Array(H);
  for (let y = 0; y < H; y++) {
    const base = y * W * 4;
    let r = 0;
    for (let x = 0; x < W; x++) if (data[base + x * 4 + 3] > thr) { r++; col[x]++; }
    row[y] = r;
  }
  // longest run of indices where count >= min
  const longestRun = (arr, min) => {
    let bestFrom = 0, bestLen = 0, from = -1;
    for (let i = 0; i <= arr.length; i++) {
      const ok = i < arr.length && arr[i] >= min;
      if (ok) { if (from < 0) from = i; }
      else if (from >= 0) {
        if (i - from > bestLen) { bestLen = i - from; bestFrom = from; }
        from = -1;
      }
    }
    if (!bestLen) return [0, arr.length - 1];
    return [bestFrom, bestFrom + bestLen - 1];
  };
  const [x0, x1] = longestRun(col, H * floor);
  const [y0, y1] = longestRun(row, W * floor);
  return { left: x0, top: y0, width: x1 - x0 + 1, height: y1 - y0 + 1 };
}

// The game frame: the largest 16:9 rectangle that fits INSIDE the core, so it is
// full-bleed by construction. Not upscaled — the bake crops the canvas at its own
// resolution (`withoutEnlargement` below), and the display fits the 16:9 plate to
// a 16:9 stage one-to-one, so nothing is ever stretched to fill.
function sceneWindow(canvas, core) {
  const ar = core.width / core.height;
  let width, height;
  if (ar >= 16 / 9) {          // core wider than the frame: match height, crop sides
    height = core.height;
    width = height * 16 / 9;
  } else {                      // core taller: match width, crop top/bottom
    width = core.width;
    height = width * 9 / 16;
  }
  width = Math.max(64, Math.round(width));
  height = Math.max(36, Math.round(height));
  return {
    left: Math.max(0, Math.round(core.left + core.width / 2 - width / 2)),
    top: Math.max(0, Math.round(core.top + core.height / 2 - height / 2)),
    width, height,
  };
}

async function renderOne(page, name, mode, pack, outName) {
  await page.setViewport({ width: 4200, height: 2400, deviceScaleFactor: 1 });
  await page.goto(`http://localhost:${PORT}/render/bg/render_bg.html?name=${encodeURIComponent(name)}`,
                  { waitUntil: "domcontentloaded" });
  await page.waitForFunction(
    () => window.__bgState && (window.__bgState.ready || window.__bgState.error),
    { timeout: 30000 });
  const st = await page.evaluate(() => window.__bgState);
  if (st.error) throw new Error(st.error);
  await new Promise(r => setTimeout(r, 120));
  const canvas = await page.$("#stage canvas");
  if (!canvas) throw new Error("no canvas in #stage");
  const raw = await canvas.screenshot({ omitBackground: true });

  const union = await fullBox(raw);
  const solid = await fullBox(raw, 200);
  let box = union, packInfo = null;
  if (pack) {
    const cm = await sharp(raw).metadata();
    // Anchor on the SOLID content (alpha > 200), not on every faint pixel: a
    // half-transparent haze layer parked to one side stretches the alpha box
    // and drags a "centred" window off the picture (that is what pushed Politia
    // into the right half of its frame).
    box = packWindow(st.bounds, { width: cm.width, height: cm.height }, solid, pack);
    if (box.left + box.width > cm.width || box.top + box.height > cm.height) {
      // A row whose offset pushes the window past the canvas would come out
      // blank; clamp it back inside and say so, rather than shipping a hole.
      box.left = Math.max(0, Math.min(box.left, cm.width - box.width));
      box.top = Math.max(0, Math.min(box.top, cm.height - box.height));
    }
    packInfo = { union: st.bounds, solid, frame: box, scale: pack.scale,
                 offset: pack.offset, pxPerUnit: Math.min(cm.width / st.bounds.w, cm.height / st.bounds.h) };
  } else if (mode === "full") {
    box = union;
  } else if (mode === "content") {
    box = await contentBox(raw);
  } else {
    const bw = await bestWindow(raw);
    if (bw) {
      box = bw;                                   // largest ~fully-covered 16:9
    } else {
      const core = await coreBox(raw);
      box = sceneWindow(null, core);
    }
    if (box.opaqueFrac === undefined) {
      // measure the chosen frame's true solid fraction on its alpha
      const alpha = await sharp(raw)
        .extract({ left: box.left, top: box.top, width: box.width, height: box.height })
        .ensureAlpha().extractChannel("alpha").raw().toBuffer();
      let solid = 0;
      for (let i = 0; i < alpha.length; i++) if (alpha[i] > 200) solid++;
      box.opaqueFrac = solid / alpha.length;
    }
  }
  const cropped = await sharp(raw)
    .extract({ left: box.left, top: box.top, width: box.width, height: box.height })
    .png()
    .toBuffer();
  const meta = await sharp(cropped).metadata();

  const long = Math.max(meta.width || 0, meta.height || 0);
  const landscape = (meta.width || 0) >= (meta.height || 0);
  // WebP, not PNG: a 1600 px scene is ~2 MB as PNG (the art is all soft
  // gradients) and ~150 KB at q92 — and WebP is already the house format here
  // (site/webp-wasm.js ships for the story/emote viewers).
  const targetLong = pack ? Math.max(FULL_LONG, long) : FULL_LONG;
  const full = await sharp(cropped)
    .resize({ width: landscape ? targetLong : undefined,
              height: landscape ? undefined : targetLong,
              fit: "inside", withoutEnlargement: true })
    .webp({ quality: 92, effort: 5 })
    .toBuffer();
  const thumb = await sharp(cropped)
    .resize({ width: landscape ? THUMB_LONG : undefined,
              height: landscape ? undefined : THUMB_LONG,
              fit: "inside", withoutEnlargement: true })
    .webp({ quality: 86, effort: 5 })
    .toBuffer();
  const outDir = pack ? PACK_OUT : OUT;
  const outBase = outName || name;
  await fsp.mkdir(outDir, { recursive: true });
  await fsp.writeFile(path.join(outDir, outBase + ".webp"), full);
  await fsp.writeFile(path.join(outDir, outBase + "_th.webp"), thumb);
  return { ...st, w: meta.width, h: meta.height, long, opaqueFrac: box.opaqueFrac, packInfo };
}

// Human label from the dump's scene id: minetown2 -> "Minetown 2",
// rta_020 -> "RTA 020", e7wc2024_back -> "E7WC 2024 Back".
const ACRONYM = new Set(["rta", "e7wc", "ggst", "drp", "vc", "grw", "gre", "wis", "nd", "e7", "lc", "as", "fma", "aos"]);
function labelFor(name) {
  const parts = name.split("_").filter(Boolean);
  const words = [];
  for (const p of parts) {
    // Match an acronym against the whole token BEFORE splitting, so `e7wc`
    // survives as E7WC instead of becoming "E 7 Wc". An acronym prefix only
    // counts when it ends the token or is followed by a digit (`e7wc2023`),
    // never by another letter (`ash` must not read as AS-h).
    const lower = p.toLowerCase();
    let acr = "";
    for (const a of ACRONYM) {
      if (lower.startsWith(a) && a.length > acr.length) {
        const rest = lower.slice(a.length);
        if (!rest || /^\d/.test(rest)) acr = a;
      }
    }
    let tail = p;
    if (acr) {
      words.push(acr.toUpperCase());
      tail = p.slice(acr.length);
      if (!tail) continue;
    }
    const expanded = tail.replace(/(\d)([a-z])/g, "$1 $2").replace(/([a-z])(\d)/g, "$1 $2");
    for (const w of expanded.split(/\s+/).filter(Boolean)) {
      words.push(/^\d+$/.test(w) ? w : w[0].toUpperCase() + w.slice(1));
    }
  }
  return words.join(" ");
}

// Site-data gate. A background has to look like ONE scene: the frame must be
// continuous. The opacity floor is high on purpose — a scene whose parts do not
// tile leaves the page colour showing between them (visible as hard plates),
// and that is exactly the "badly cut" look. Those still measure 45-90% opaque,
// so a lenient floor publishes collages.
const MIN_W = 600, MIN_H = 240, MIN_OPAQUE = 0.90, ASPECT = [0.75, 4.5];

// Scenes whose composition is visibly BROKEN — the parts sit as flat bands with
// hard seams instead of joining up, so the frame is opaque but reads as a
// collage (this is what "some backgrounds are still fucked up" was pointing at;
// the sample was rta_016, a sky plate stacked over a grey one). Opacity cannot
// catch these: the bands ARE drawn content, just in the wrong place.
//
// This is a curated hold-list, not a fix. The cause is the per-part placement
// problem recorded in CLAUDE.md (the table's x/y is a position for some scenes
// and already baked into the rig for others), and the real remedy is the
// two-variant bake: render each scene both ways and keep the frame that is more
// opaque. Re-check this list when that lands.
const BROKEN_SCENES = new Set([
  // Seen as banded/collaged after the window search landed. Re-check each of
  // these by eye before adding to it — the 2026-10-07 window rework fixed
  // several that were on this list (the wedges were a framing artefact):
  //   released after re-review: ma_church_underground, drp_town3, pars_aespa2,
  //   tru_throne, for_snowyfield2 (Moonlit Tundra — the opaque black rectangle
  //   is simply outside the new, larger-covered window).
  "trd_harbor",      // the icy plate cuts diagonally across the lower half
  "pab_inner2",      // hard horizontal seam: two wall plates at different shades
  "wip_dcave2",      // pink fog band ends abruptly over a rocky floor plate
  "rta_016",         // sky plate stacked over a dark band, hard seam
  "rta_018",         // a few plates floating on a grey field
]);

async function frameStats(name) {
  const p = path.join(OUT, name + ".webp");
  const meta = await sharp(p).metadata();
  const { data, info } = await sharp(p).ensureAlpha().raw()
    .toBuffer({ resolveWithObject: true });
  let opaque = 0;
  const n = info.width * info.height;
  for (let i = 3; i < data.length; i += 4) if (data[i] > 200) opaque++;
  // `name` rides along so rejectReason can consult BROKEN_SCENES — without it
  // that check silently never matches, which is how a hold-list becomes a no-op.
  return { name, w: meta.width, h: meta.height, opaque: opaque / n };
}

function rejectReason(s) {
  if (BROKEN_SCENES.has(s.name)) return "composition is a collage (see BROKEN_SCENES)";
  if (s.w < MIN_W || s.h < MIN_H) return `too small (${s.w}x${s.h})`;
  const ar = s.w / s.h;
  if (ar < ASPECT[0] || ar > ASPECT[1]) return `aspect ${ar.toFixed(2)}`;
  if (s.opaque < MIN_OPAQUE) return `only ${(s.opaque * 100).toFixed(0)}% opaque`;
  return null;
}

async function writeDataFile() {
  const kept = [], dropped = [];
  for (const name of listStaged().sort()) {
    if (!fs.existsSync(path.join(OUT, name + ".webp"))) continue;
    const s = await frameStats(name);
    const why = rejectReason(s);
    const row = {
      name,
      label: labelFor(name),
      file: `assets/_bg/${name}.webp`,
      thumb: `assets/_bg/${name}_th.webp`,
      w: s.w, h: s.h,
      layers: stagedLayerCount(name),
    };
    if (why) { dropped.push([name, why]); continue; }
    kept.push(row);
  }
  kept.sort((a, b) => a.label.localeCompare(b.label));
  await fsp.writeFile(path.join(ROOT, "site", "data", "backgrounds.json"),
                      JSON.stringify(kept, null, 1), "utf-8");
  await fsp.writeFile(path.join(SRC, "_quality.json"),
                      JSON.stringify({ kept: kept.length, dropped }, null, 1), "utf-8");
  console.log(`wrote site/data/backgrounds.json (${kept.length} entries, ${dropped.length} held back — see _quality.json)`);
}

// ── pack mode ───────────────────────────────────────────────────────────────
// Bake the in-game Hero View Background Pack: one full-bleed 16:9 frame per
// pack entry, framed per site/data/bg_packs.json (scene + scale + offset), so
// the result can sit behind a hero exactly as the game shows it.
async function mainPack({ force, only }) {
  if (!fs.existsSync(PACK_LIST)) {
    throw new Error("site/data/bg_packs.json missing — run: python render/bg/bg_packs.py");
  }
  const packs = JSON.parse(fs.readFileSync(PACK_LIST, "utf-8"));
  const staged = new Set(listStaged());
  let todo = packs.filter(p => !p.flat && staged.has(p.scene));
  if (only.length) todo = todo.filter(p => only.includes(p.id) || only.includes(p.scene));
  if (!force) todo = todo.filter(p => !fs.existsSync(path.join(PACK_OUT, p.id + ".webp")));
  console.log(`pack entries: ${packs.length}; renderable now: ${todo.length}`);

  const server = makeServer();
  await new Promise(r => server.listen(PORT, r));
  const browser = await puppeteer.launch({ headless: "new" });
  const page = await browser.newPage();
  const failures = [];
  const frames = [];
  let done = 0;
  for (const p of todo) {
    try {
      const r = await renderOne(page, p.scene, "full", p, p.id);
      frames.push({ id: p.id, name: p.name, scene: p.scene, scale: p.scale,
                    offset: p.offset, tint: p.tint, w: r.w, h: r.h });
      done++;
      if (done % 20 === 0) {
        console.log(`  ${done}/${todo.length}  ${p.id} ${p.scene} ${r.w}x${r.h}`);
      }
    } catch (e) {
      failures.push([p.id, p.scene, String(e.message).slice(0, 160)]);
      console.log(`  FAIL ${p.id} (${p.scene}): ${String(e.message).slice(0, 120)}`);
    }
  }
  await browser.close();
  server.close();

  // Carry forward frames baked in earlier runs so a partial run keeps the list whole.
  const seen = new Set(frames.map(f => f.id));
  for (const p of packs) {
    if (seen.has(p.id) || p.flat || !fs.existsSync(path.join(PACK_OUT, p.id + ".webp"))) continue;
    const m = await sharp(path.join(PACK_OUT, p.id + ".webp")).metadata();
    frames.push({ id: p.id, name: p.name, scene: p.scene, scale: p.scale,
                  offset: p.offset, tint: p.tint, w: m.width, h: m.height });
  }
  frames.sort((a, b) => (a.name || a.id).localeCompare(b.name || b.id));
  await fsp.writeFile(path.join(ROOT, "site", "data", "bg_frames.json"),
                      JSON.stringify(frames, null, 1), "utf-8");
  await fsp.writeFile(path.join(SRC, "_pack_failures.json"),
                      JSON.stringify(failures, null, 1), "utf-8");
  console.log(`baked ${done}/${todo.length} pack frames; failures ${failures.length};`
    + ` site/data/bg_frames.json has ${frames.length}`);
}

async function main() {
  const argv = process.argv.slice(2);
  const force = argv.includes("--force");
  if (argv.includes("--full")) RENDER_MODE = "full";
  const packMode = argv.includes("--pack");
  const only = argv.filter(a => !a.startsWith("--"));

  if (packMode) return mainPack({ force, only });

  let names = listStaged();
  if (only.length) names = names.filter(n => only.includes(n));
  if (!force) names = names.filter(n => !fs.existsSync(path.join(OUT, n + ".webp")));
  console.log(`backgrounds to render: ${names.length}`);

  const server = makeServer();
  await new Promise(r => server.listen(PORT, r));

  // Multi-page atlases load one texture per page per scene, and a long run
  // eventually kills the renderer process — after which every remaining
  // `page.goto` fails with "Session closed", which is what turned one crash
  // into 488 reported failures. So: recycle the browser periodically, and treat
  // a dead session as a recoverable condition (relaunch + retry once).
  const RECYCLE_EVERY = 60;
  let browser = null, page = null;
  const launch = async () => {
    if (browser) { try { await browser.close(); } catch { /* already gone */ } }
    browser = await puppeteer.launch({ headless: "new" });
    page = await browser.newPage();
  };
  const dead = (e) => !browser || !browser.isConnected() ||
    /Session closed|Target closed|Protocol error/i.test(String(e && e.message));

  await launch();
  const fails = [];
  let done = 0, sinceLaunch = 0;
  for (const name of names) {
    if (sinceLaunch >= RECYCLE_EVERY) { await launch(); sinceLaunch = 0; }
    try {
      const r = await renderOne(page, name, RENDER_MODE);
      done++;
      sinceLaunch++;
      if (done % 20 === 0) {
        console.log(`  ${done}/${names.length}  ${name} ${r.w}x${r.h} opaque=${(r.opaqueFrac * 100).toFixed(0)}%`);
      }
    } catch (e) {
      if (dead(e)) {
        console.log(`  browser died at ${name}; relaunching and retrying`);
        await launch();
        sinceLaunch = 0;
        try {
          const r = await renderOne(page, name, RENDER_MODE);
          done++;
          sinceLaunch++;
          continue;
        } catch (e2) {
          fails.push([name, String(e2.message).slice(0, 200)]);
          console.log(`  FAIL ${name}: ${String(e2.message).slice(0, 140)}`);
          continue;
        }
      }
      fails.push([name, String(e.message).slice(0, 200)]);
      console.log(`  FAIL ${name}: ${String(e.message).slice(0, 140)}`);
    }
  }
  await browser.close();
  server.close();
  await fsp.writeFile(path.join(SRC, "_render_failures.json"),
                      JSON.stringify(fails, null, 1), "utf-8");
  await writeDataFile();
  console.log(`rendered ${done}/${names.length}; failures ${fails.length}`);
}

main().catch(e => { console.error(e); process.exit(1); });

