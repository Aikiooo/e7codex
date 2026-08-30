/**
 * High-quality multi-layer lobby/illust bake (cfx-order, idle anim).
 *
 *   node bake_lobby_hq.js <base> <order-csv> <out.webm> [outH=1440] [fps=30] [crf=12] [workers=6] [anchor] [res=WxH]
 *
 * `anchor` (optional, default `bg`):
 *   - slot name → world AABB of that attachment across layers (legacy intimacy)
 *   - `skel`    → rank-2 char skeleton JSON w/h, centered on that layer's mesh
 *   - `world0`  → rank-1 engine ortho DESIGN/BASE_SCALE about origin (0,0)
 *                 (lobby/CFX EffectPlay default: scaleFactor=BASE_SCALE)
 *
 * `res` (optional): authored display aspect, e.g. DESIGN `1920x1080` (rank 1)
 * or `profile_spine_illust_resolution.db` (rank 2, e.g. 1580x720). When set,
 * the world AABB is center-cropped to that aspect before mapping to output
 * pixels — no screenshot-fitted crop fractions. Output W = outH * (resW/resH).
 * Without res, W follows the AABB aspect (legacy). For `world0`, res also
 * supplies DESIGN_W/H used in BASE_SCALE (default 1920x1080).
 *
 * Env:
 *   E7_LAYER_SCALES=stem:scale,stem:scale  rank-2 CFX primitive scale (rec.html)
 *   E7_STILL_ONLY=1                        still PNG only
 *   E7_PMA / E7_PMAOFF                     alpha mode overrides
 *
 * Differences from bake.js for HQ preview:
 *  - viewport sized to the full output WxH (no clip on element screenshots)
 *  - default higher res + lower VP9 CRF
 *  - also writes a still PNG at t=0.5s next to the webm
 *  - keeps frame PNGs only with --keep-frames
 *  - applies CFX scale under world0 so UI illust packs (scale≈2.24) fill frame
 */
const puppeteer = require("puppeteer");
const http = require("http");
const fs = require("fs");
const path = require("path");
const os = require("os");
const { execFileSync, fork } = require("child_process");
const { encodeArgs, encodeLabel } = require("./encode_ffmpeg");

const ROOT = __dirname;
const GPU_ARGS = [
  "--no-sandbox",
  "--ignore-gpu-blocklist",
  "--enable-gpu-rasterization",
  "--enable-zero-copy",
  "--disable-frame-rate-limit",
];

function serve() {
  return new Promise((res) => {
    const srv = http.createServer((req, rq) => {
      let f = decodeURIComponent(req.url.split("?")[0]);
      if (f === "/") f = "/rec.html";
      const fp = path.join(ROOT, f);
      fs.readFile(fp, (e, d) => {
        if (e) {
          rq.writeHead(404);
          rq.end();
          return;
        }
        const ext = path.extname(fp).slice(1);
        const ct = {
          html: "text/html",
          js: "text/javascript",
          css: "text/css",
          json: "application/json",
          png: "image/png",
          atlas: "text/plain",
        }[ext] || "application/octet-stream";
        rq.writeHead(200, { "Content-Type": ct });
        rq.end(d);
      });
    });
    srv.listen(0, () => res(srv));
  });
}

async function loadPage(port, base, order, viewW, viewH) {
  const browser = await puppeteer.launch({ headless: "new", args: GPU_ARGS });
  const page = await browser.newPage();
  // Viewport must cover the final wrap size so element screenshots aren't clipped.
  await page.setViewport({
    width: Math.max(viewW + 40, 1280),
    height: Math.max(viewH + 40, 720),
    deviceScaleFactor: 1,
  });
  page.on("pageerror", (e) => console.error("[pageerror]", e.message));
  page.on("console", (m) => {
    if (m.type() === "error") console.error("[console]", m.text());
  });
  const pma = process.env.E7_PMA === "0" ? "&pma=0" : "";
  const pmaoff = process.env.E7_PMAOFF
    ? "&pmaoff=" + encodeURIComponent(process.env.E7_PMAOFF)
    : "";
  // Rank-2 CFX scales: stem:scale pairs (pipeline sets E7_LAYER_SCALES).
  const scales = process.env.E7_LAYER_SCALES
    ? "&scales=" + encodeURIComponent(process.env.E7_LAYER_SCALES)
    : "";
  // Shared clip (e.g. story_en) so multi-layer FX stay on the same timeline.
  const anim = process.env.E7_LAYER_ANIM
    ? "&anim=" + encodeURIComponent(process.env.E7_LAYER_ANIM)
    : "";
  // Per-layer clips stem:anim,stem:anim (rank-2 CFX ani or recipe override).
  const anims = process.env.E7_LAYER_ANIMS
    ? "&anims=" + encodeURIComponent(process.env.E7_LAYER_ANIMS)
    : "";
  // One-shot enter/touch: layers that carry it play once (rec.html ACTANIM).
  const actanim = process.env.E7_ACTANIM
    ? "&actanim=" + encodeURIComponent(process.env.E7_ACTANIM)
    : "";
  const comp = process.env.E7_COMP ? "&comp=" + encodeURIComponent(process.env.E7_COMP) : "";
  const ehide = process.env.E7_EHIDE ? "&ehide=" + encodeURIComponent(process.env.E7_EHIDE) : "";
  // Load at a modest probe size first; __reframe will resize wrap + viewports.
  const loadW = Math.min(viewW, 2000);
  const loadH = Math.min(viewH, 1400);
  const url =
    `http://localhost:${port}/rec.html?base=${encodeURIComponent(base)}` +
    `&order=${encodeURIComponent(order)}&w=${loadW}&h=${loadH}${pma}${pmaoff}${scales}${anim}${anims}${actanim}${comp}${ehide}`;
  await page.goto(url, { waitUntil: "networkidle0", timeout: 120000 });
  await page.waitForFunction("window.__ready === true", { timeout: 120000 });
  const err = await page.evaluate(() => window.__err || []);
  if (err.length) console.warn("layer errors:", err);
  if (process.env.E7_LAYER_SCALES) {
    console.log("CFX scales:", process.env.E7_LAYER_SCALES);
  }
  if (process.env.E7_LAYER_ANIM) {
    console.log("layer anim:", process.env.E7_LAYER_ANIM);
  }
  if (process.env.E7_ACTANIM) {
    console.log("act anim:", process.env.E7_ACTANIM);
  }
  // Log chosen clip + phase-lock policy (rec.html __seek) so mismatched
  // durations never ship silently (Luluca 6s waves vs 8s body).
  const picks = await page.evaluate(() =>
    (window.__players || []).map((p) => {
      const tr = p.animationState && p.animationState.getCurrent(0);
      const a = tr && tr.animation;
      return {
        stem: p.__stem || "?",
        anim: a ? a.name : null,
        dur: a ? a.duration : null,
      };
    })
  );
  if (picks.length) {
    console.log(
      "clips:",
      picks.map((x) => `${x.stem}=${x.anim}@${x.dur != null ? x.dur.toFixed(2) + "s" : "?"}`).join("  ")
    );
  }
  const phase = await page.evaluate(() =>
    typeof window.__phaseReport === "function" ? window.__phaseReport() : null
  );
  if (phase && phase.layers && phase.layers.length) {
    const parts = phase.layers.map((L) => {
      const d = L.dur != null ? L.dur.toFixed(2) + "s" : "?";
      return `${L.stem}:${L.policy}@${d}`;
    });
    const mixed = phase.layers.some((L) => L.policy === "near-stretch" || L.policy === "short-loop");
    console.log(
      `phase-lock: master=${phase.master.toFixed(2)}s near≥${phase.nearRatio}` +
        (mixed ? " (auto-sync active)" : " (uniform)") +
        "  " +
        parts.join("  ")
    );
  }
  return { browser, page };
}

async function worker() {
  const [
    port,
    base,
    order,
    framesDir,
    Ws,
    Hs,
    aabbJSON,
    cropJSON,
    durS,
    Ns,
    startS,
    endS,
  ] = process.argv.slice(3);
  const W = parseInt(Ws, 10);
  const H = parseInt(Hs, 10);
  const aabb = JSON.parse(aabbJSON);
  const crop = JSON.parse(cropJSON);
  const dur = parseFloat(durS);
  const N = parseInt(Ns, 10);
  const start = parseInt(startS, 10);
  const end = parseInt(endS, 10);
  const { browser, page } = await loadPage(port, base, order, W, H);
  // Grow viewport after reframe so the wrap fits fully.
  await page.setViewport({
    width: W + 40,
    height: H + 40,
    deviceScaleFactor: 1,
  });
  await page.evaluate(
    (a, w, h, c) => window.__reframe(a, w, h, 0, c),
    aabb,
    W,
    H,
    crop
  );
  await new Promise((r) => setTimeout(r, 400));
  const wrap = await page.$("#wrap");
  for (let i = start; i < end; i++) {
    const t = i * (dur / N);
    await page.evaluate(
      (tt) =>
        new Promise((res) => {
          window.__seek(tt);
          requestAnimationFrame(() =>
            requestAnimationFrame(() => setTimeout(res, 60))
          );
        }),
      t
    );
    await wrap.screenshot({
      path: path.join(framesDir, `f${String(i).padStart(4, "0")}.png`),
      omitBackground: false,
    });
  }
  await browser.close();
  process.exit(0);
}

/** Center-crop fractions so world AABB matches authored display aspect. */
function aspectCrop(aabbW, aabbH, resW, resH) {
  const target = resW / resH;
  const src = aabbW / aabbH;
  // crop = {t,b,l,r} fractions of the AABB edges to trim (see rec.html __reframe).
  if (Math.abs(src - target) < 1e-6) return { t: 0, b: 0, l: 0, r: 0 };
  if (src > target) {
    // AABB wider than target → trim left/right.
    const keep = target / src; // fraction of width to keep
    const side = (1 - keep) / 2;
    return { t: 0, b: 0, l: side, r: side };
  }
  // AABB taller relative to width → trim top/bottom.
  const keep = src / target;
  const side = (1 - keep) / 2;
  return { t: side, b: side, l: 0, r: 0 };
}

async function orchestrate() {
  const args = process.argv.slice(2).filter((a) => a !== "--keep-frames");
  const [
    base = "vsu6aa_lobby",
    order = "",
    out = "lobby_preview.webm",
    outHA = "1440",
    fpsA = "30",
    crfA = "12",
    workersA = "",
    anchor = "bg",
    resA = "",
  ] = args;

  if (!order) {
    console.error(
      "usage: node bake_lobby_hq.js <base> <order-csv> <out.webm> [outH] [fps] [crf] [workers] [anchor=bg|skel|world0] [res=WxH]"
    );
    process.exit(1);
  }

  const fps = parseInt(fpsA, 10) || 30;
  const outH = parseInt(outHA, 10) || 1440;
  const crf = String(crfA || "12");
  const nWorkers =
    parseInt(workersA, 10) || Math.min(6, Math.max(1, os.cpus().length - 2));
  let crop = { t: 0, b: 0, l: 0, r: 0 };
  let authoredRes = null;
  if (resA && /^\d+x\d+$/i.test(resA)) {
    const [rw, rh] = resA.toLowerCase().split("x").map((n) => parseInt(n, 10));
    if (rw > 0 && rh > 0) authoredRes = { w: rw, h: rh };
  }

  const outPath = path.isAbsolute(out) ? out : path.join(ROOT, out);
  const framesDir = path.join(
    ROOT,
    "_frames_" + path.basename(outPath, path.extname(outPath))
  );
  fs.rmSync(framesDir, { recursive: true, force: true });
  fs.mkdirSync(framesDir, { recursive: true });
  fs.mkdirSync(path.dirname(outPath), { recursive: true });

  const srv = await serve();
  const port = srv.address().port;

  const t0 = Date.now();
  // Probe on a moderate viewport.
  const { browser, page } = await loadPage(port, base, order, 2000, 1400);
  const gpu = await page.evaluate(() => {
    const c = document.createElement("canvas");
    const gl = c.getContext("webgl");
    const d = gl && gl.getExtension("WEBGL_debug_renderer_info");
    return d ? gl.getParameter(d.UNMASKED_RENDERER_WEBGL) : "unknown";
  });
  // Seek a stable pose before measuring mesh-centered skel AABB.
  await page.evaluate(
    () =>
      new Promise((res) => {
        window.__seek(0.5);
        requestAnimationFrame(() => requestAnimationFrame(res));
      })
  );
  const useSkel = anchor === "skel" || anchor === "char_skel";
  const useWorld0 = anchor === "world0" || anchor === "base_scale";
  // DESIGN for world0 / aspect: authored res or canonical 1920x1080 (rank 1).
  const designWH = authoredRes || { w: 1920, h: 1080 };
  const aabb = await page.evaluate(
    (mode, dw, dh) => {
      if (mode === "world0") return window.__world0_aabb(dw, dh);
      if (mode === "skel") return window.__char_skel_aabb();
      return window.__aabb(mode);
    },
    useWorld0 ? "world0" : useSkel ? "skel" : anchor,
    designWH.w,
    designWH.h
  );
  if (!aabb) {
    console.error(
      useWorld0
        ? "world0 AABB failed"
        : useSkel
          ? "char skeleton AABB not found (no player with skeleton.width>0)"
          : "anchor slot not found: " + anchor
    );
    process.exit(1);
  }
  let dur = await page.evaluate(() => window.__dur());
  // Still PNG before closing probe browser (reframe to final size).
  // Framing: slot / skel (rank 2) or world0=DESIGN/BASE_SCALE (rank 1).
  // Aspect crop only when world aspect != authored display aspect.
  // Never screenshot-fitted.
  if (useWorld0) {
    // Already DESIGN aspect by construction — no crop.
    crop = { t: 0, b: 0, l: 0, r: 0 };
    if (!authoredRes) authoredRes = designWH;
  } else if (authoredRes) {
    crop = aspectCrop(aabb.width, aabb.height, authoredRes.w, authoredRes.h);
  }
  const viewW = aabb.width * (1 - crop.l - crop.r);
  const viewH = aabb.height * (1 - crop.t - crop.b);
  const aspect = authoredRes
    ? authoredRes.w / authoredRes.h
    : viewW / viewH;
  let W = Math.round(outH * aspect);
  if (W % 2) W += 1;
  const H = outH % 2 ? outH + 1 : outH;
  const anchorLabel = useWorld0
    ? "world0"
    : useSkel
      ? "skel"
      : anchor;
  console.log(
    `anchor=${anchorLabel} world ${aabb.width.toFixed(1)}x${aabb.height.toFixed(1)} @ (${aabb.x.toFixed(1)},${aabb.y.toFixed(1)})` +
      (aabb.baseScale != null ? ` BASE_SCALE=${aabb.baseScale}` : "")
  );
  console.log(
    `crop fractions ${JSON.stringify(crop)}` +
      (authoredRes
        ? ` from authored res ${authoredRes.w}x${authoredRes.h}`
        : " (AABB aspect)")
  );

  await page.setViewport({ width: W + 40, height: H + 40, deviceScaleFactor: 1 });
  await page.evaluate(
    (a, w, h, c) => window.__reframe(a, w, h, 0, c),
    aabb,
    W,
    H,
    crop
  );
  await page.evaluate(
    (tt) =>
      new Promise((res) => {
        window.__seek(tt);
        requestAnimationFrame(() => requestAnimationFrame(res));
      }),
    0.5
  );
  const stillPath = outPath.replace(/\.webm$/i, "_still.png");
  const wrap = await page.$("#wrap");
  await wrap.screenshot({ path: stillPath, omitBackground: false });
  console.log("wrote still", stillPath);
  await browser.close();

  if (process.env.E7_STILL_ONLY === "1") {
    console.log("E7_STILL_ONLY=1 — skipping frame capture / encode");
    srv.close();
    return;
  }

  const N = Math.max(1, Math.round(dur * fps));
  console.log(`renderer: ${gpu}`);
  console.log(
    `rect ${aabb.width.toFixed(0)}x${aabb.height.toFixed(0)} -> ${W}x${H}  loop ${dur.toFixed(2)}s -> ${N} frames @ ${fps}fps  crf=${crf}  workers=${nWorkers}`
  );

  const per = Math.ceil(N / nWorkers);
  const jobs = [];
  for (let w = 0; w < nWorkers; w++) {
    const start = w * per;
    const endF = Math.min(N, start + per);
    if (start >= endF) break;
    jobs.push(
      new Promise((res, rej) => {
        const child = fork(
          __filename,
          [
            "--worker",
            String(port),
            base,
            order,
            framesDir,
            String(W),
            String(H),
            JSON.stringify(aabb),
            JSON.stringify(crop),
            String(dur),
            String(N),
            String(start),
            String(endF),
          ],
          { stdio: "inherit" }
        );
        child.on("exit", (code) =>
          code === 0 ? res() : rej(new Error("worker " + w + " exit " + code))
        );
      })
    );
  }
  await Promise.all(jobs);
  srv.close();

  const captured = fs
    .readdirSync(framesDir)
    .filter((f) => f.endsWith(".png")).length;
  console.log(
    `captured ${captured}/${N} frames in ${((Date.now() - t0) / 1000).toFixed(1)}s, encoding (${encodeLabel()})...`
  );

  // Default: libvpx-vp9 with cpu-used=2 (was implicit 0 → multi-minute encodes).
  // Override: E7_ENCODER=av1_amf for AMD hardware preview encodes.
  execFileSync(
    "ffmpeg",
    encodeArgs(fps, crf, path.join(framesDir, "f%04d.png"), outPath),
    { stdio: "inherit" }
  );
  const kb = (fs.statSync(outPath).size / 1024).toFixed(0);
  if (!process.argv.includes("--keep-frames")) {
    fs.rmSync(framesDir, { recursive: true, force: true });
  }
  console.log("wrote", outPath, kb + " KB");
}

if (process.argv[2] === "--worker") worker();
else orchestrate().catch((e) => {
  console.error(e);
  process.exit(1);
});
