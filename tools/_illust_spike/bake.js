// Fast deterministic frame-sequence WebM bake: GPU rendering + parallel workers.
// Same output as seq.js (deterministic seek, crop to anchor AABB) but uses the
// real GPU (no forced SwiftShader) and splits the frame range across N worker
// processes, so a bake that took minutes on one software-GL browser finishes in
// a fraction of the time on a multi-core box with a discrete GPU.
//
// Orchestrator: node bake.js <base> <order> <out.webm> <fps> <anchor> <outH> <crop> <maxSec> <crf> [workers]
// Worker (internal): node bake.js --worker <port> <base> <order> <framesDir> <W> <H> <aabbJSON> <cropJSON> <dur> <N> <start> <end>
const puppeteer = require("puppeteer");
const http = require("http");
const fs = require("fs");
const path = require("path");
const os = require("os");
const { execFileSync, fork } = require("child_process");
const { encodeArgs, encodeLabel } = require("./encode_ffmpeg");

const ROOT = __dirname;

// GPU-first launch args. Dropping --use-angle=swiftshader lets ANGLE pick the
// hardware D3D11 path; if the GPU is unavailable (headless under a virtual
// display, etc.) Chromium silently falls back to software, so this never breaks
// the bake — it just won't get the GPU speedup. Parallel workers still help then.
const GPU_ARGS = ["--no-sandbox", "--ignore-gpu-blocklist",
  "--enable-gpu-rasterization", "--enable-zero-copy",
  "--disable-frame-rate-limit"];

function serve() {
  return new Promise((res) => {
    const srv = http.createServer((req, rq) => {
      let f = decodeURIComponent(req.url.split("?")[0]);
      if (f === "/") f = "/rec.html";
      const fp = path.join(ROOT, f);
      fs.readFile(fp, (e, d) => {
        if (e) { rq.writeHead(404); rq.end(); return; }
        const ext = path.extname(fp).slice(1);
        const ct = { html: "text/html", js: "text/javascript", css: "text/css",
          json: "application/json", png: "image/png", atlas: "text/plain" }[ext] || "application/octet-stream";
        rq.writeHead(200, { "Content-Type": ct }); rq.end(d);
      });
    });
    srv.listen(0, () => res(srv));
  });
}

async function loadPage(port, base, order, W, H) {
  const browser = await puppeteer.launch({ headless: "new", args: GPU_ARGS });
  const page = await browser.newPage();
  await page.setViewport({ width: 2200, height: 1600, deviceScaleFactor: 1 });
  page.on("console", (m) => { if (m.type() === "error") {} });
  const pma = process.env.E7_PMA === "0" ? "&pma=0" : "";
  const pmaoff = process.env.E7_PMAOFF ? "&pmaoff=" + encodeURIComponent(process.env.E7_PMAOFF) : "";
  const ehide = process.env.E7_EHIDE ? "&ehide=" + encodeURIComponent(process.env.E7_EHIDE) : "";
  const actanim = process.env.E7_ACTANIM ? "&actanim=" + encodeURIComponent(process.env.E7_ACTANIM) : "";
  const pre = process.env.E7_PRE_DIR
    ? `&preDir=${encodeURIComponent(process.env.E7_PRE_DIR)}&preN=${process.env.E7_PRE_N}&preDur=${process.env.E7_PRE_DUR}&preZ=${process.env.E7_PRE_Z}` : "";
  const anim = process.env.E7_LAYER_ANIM
    ? "&anim=" + encodeURIComponent(process.env.E7_LAYER_ANIM)
    : "";
  // Per-stem CFX ani map (stem:anim,...) — intro packs with mixed clip names.
  const anims = process.env.E7_LAYER_ANIMS
    ? "&anims=" + encodeURIComponent(process.env.E7_LAYER_ANIMS)
    : "";
  // Neutralize hierarchical `camera` bones (c6005 intro dezoom fix).
  const camn = process.env.E7_CAM_NEUTRAL === "1" ? "&camneutral=1" : "";
  const url =
    `http://localhost:${port}/rec.html?base=${base}&order=${order}&w=${W}&h=${H}` +
    `${pma}${pmaoff}${ehide}${actanim}${pre}${anim}${anims}${camn}`;
  await page.goto(url, { waitUntil: "networkidle0", timeout: 90000 });
  await page.waitForFunction("window.__ready === true", { timeout: 90000 });
  // Phase-lock report (same as bake_lobby_hq) — multi-layer intimacy stacks
  // also go through rec.html __seek.
  if (process.env.E7_LAYER_ANIM) console.log("layer anim:", process.env.E7_LAYER_ANIM);
  if (process.env.E7_LAYER_ANIMS) console.log("layer anims:", process.env.E7_LAYER_ANIMS);
  if (process.env.E7_CAM_NEUTRAL === "1") console.log("cam neutral: on");
  const phase = await page.evaluate(() =>
    typeof window.__phaseReport === "function" ? window.__phaseReport() : null
  );
  if (phase && phase.layers && phase.layers.length > 1) {
    console.log(
      "clips:",
      phase.layers
        .map((L) => `${L.stem}=${L.anim}@${L.dur != null ? L.dur.toFixed(2) + "s" : "?"}`)
        .join("  ")
    );
    const mixed = phase.layers.some((L) => L.policy === "near-stretch" || L.policy === "short-loop");
    console.log(
      `phase-lock: master=${phase.master.toFixed(2)}s near≥${phase.nearRatio}` +
        (mixed ? " (auto-sync active)" : " (uniform)") +
        "  " +
        phase.layers.map((L) => `${L.stem}:${L.policy}`).join("  ")
    );
  }
  return { browser, page };
}

async function worker() {
  const [port, base, order, framesDir, Ws, Hs, aabbJSON, cropJSON, durS, Ns, startS, endS] =
    process.argv.slice(3);
  const W = parseInt(Ws, 10), H = parseInt(Hs, 10);
  const aabb = JSON.parse(aabbJSON), crop = JSON.parse(cropJSON);
  const dur = parseFloat(durS), N = parseInt(Ns, 10);
  const start = parseInt(startS, 10), end = parseInt(endS, 10);
  const { browser, page } = await loadPage(port, base, order, 2000, 1400);
  await page.evaluate((a, w, h, c) => window.__reframe(a, w, h, 0, c), aabb, W, H, crop);
  await new Promise((r) => setTimeout(r, 300));
  const wrap = await page.$("#wrap");
  for (let i = start; i < end; i++) {
    const t = i * (dur / N);
    // Seek (which calls drawFrame), then wait for TWO composited paints before
    // screenshotting — otherwise puppeteer can capture the previous frame's
    // composited pixels (the GL draw hasn't reached the screenshot buffer yet),
    // which shows up as stutter/repeated frames at the worker range boundaries.
    await page.evaluate((tt) => new Promise((res) => {
      window.__seek(tt);
      requestAnimationFrame(() => requestAnimationFrame(res));
    }), t);
    await wrap.screenshot({ path: path.join(framesDir, `f${String(i).padStart(4, "0")}.png`) });
  }
  await browser.close();
  process.exit(0);
}

async function orchestrate() {
  const [base = "c1153", order = "", out = "out.webm", fpsA = "30",
         anchor = "bg2", outHA = "1080", cropA = "0,0,0,0", maxSecA = "0",
         crfA = "20", workersA = ""] = process.argv.slice(2);
  const fps = parseInt(fpsA, 10);
  const outH = parseInt(outHA, 10);
  const [cT, cB, cL, cR] = cropA.split(",").map(parseFloat);
  const crop = { t: cT || 0, b: cB || 0, l: cL || 0, r: cR || 0 };
  const maxSec = parseFloat(maxSecA);
  const crf = crfA;
  const nWorkers = parseInt(workersA, 10) || Math.min(8, Math.max(1, os.cpus().length - 2));

  const framesDir = path.join(ROOT, "_frames_" + path.basename(out, ".webm"));
  fs.rmSync(framesDir, { recursive: true, force: true });
  fs.mkdirSync(framesDir);

  const srv = await serve();
  const port = srv.address().port;

  // Probe once: AABB of the anchor slot + loop duration, on a GPU browser.
  const t0 = Date.now();
  const { browser, page } = await loadPage(port, base, order, 2000, 1400);
  const gpu = await page.evaluate(() => {
    const c = document.createElement("canvas");
    const gl = c.getContext("webgl");
    const d = gl && gl.getExtension("WEBGL_debug_renderer_info");
    return d ? gl.getParameter(d.UNMASKED_RENDERER_WEBGL) : "unknown";
  });
  // anchor: slot name | skel | char_skel (rank-2 skeleton bounds when bg mesh is a thin strip)
  const useSkel = anchor === "skel" || anchor === "char_skel";
  const aabb = await page.evaluate((s, skel) => {
    if (skel && typeof window.__char_skel_aabb === "function") return window.__char_skel_aabb();
    return window.__aabb(s);
  }, anchor, useSkel);
  if (!aabb) {
    console.error(useSkel ? "char skeleton AABB not found" : "anchor slot not found: " + anchor);
    process.exit(1);
  }
  let dur = await page.evaluate("window.__dur()");
  const masterDur = await page.evaluate(() =>
    typeof window.__masterDur === "function" ? window.__masterDur() : 0
  );
  await browser.close();
  if (maxSec > 0 && dur > maxSec) {
    // Truncating below master cuts long ambient FX mid-timeline (c6005 petals
    // 33.3s under max_sec 21 → incomplete fall cycle that jumps on loop).
    if (masterDur > maxSec + 1e-3) {
      console.warn(
        `WARN: max_sec=${maxSec}s < master=${masterDur.toFixed(2)}s — ` +
          `long ambient FX will not complete one authored cycle. ` +
          `Raise max_sec to master (or 0) unless intentionally short.`
      );
    }
    dur = maxSec;
  }

  const cropW = aabb.width * (1 - crop.l - crop.r);
  const cropH = aabb.height * (1 - crop.t - crop.b);
  const aspect = cropW / cropH;
  let W = Math.round(outH * aspect); if (W % 2) W += 1;
  const H = outH % 2 ? outH + 1 : outH;
  const N = Math.max(1, Math.round(dur * fps));
  console.log(`renderer: ${gpu}`);
  console.log(
    `anchor=${useSkel ? "skel" : anchor} rect ${aabb.width.toFixed(0)}x${aabb.height.toFixed(0)} -> ${W}x${H}` +
    `  loop ${dur.toFixed(2)}s -> ${N} frames @ ${fps}fps  (${nWorkers} workers)`
  );

  // Split [0,N) into nWorkers contiguous ranges, fork a worker per range.
  const per = Math.ceil(N / nWorkers);
  const jobs = [];
  for (let w = 0; w < nWorkers; w++) {
    const start = w * per, endF = Math.min(N, start + per);
    if (start >= endF) break;
    jobs.push(new Promise((res, rej) => {
      const child = fork(__filename, ["--worker", String(port), base, order, framesDir,
        String(W), String(H), JSON.stringify(aabb), JSON.stringify(crop),
        String(dur), String(N), String(start), String(endF)], { stdio: "inherit" });
      child.on("exit", (code) => code === 0 ? res() : rej(new Error("worker " + w + " exit " + code)));
    }));
  }
  await Promise.all(jobs);
  srv.close();
  const captured = fs.readdirSync(framesDir).filter((f) => f.endsWith(".png")).length;
  console.log(`captured ${captured}/${N} frames in ${((Date.now() - t0) / 1000).toFixed(1)}s, encoding (${encodeLabel()})...`);

  const outAbs = path.isAbsolute(out) ? out : path.join(ROOT, out);
  execFileSync(
    "ffmpeg",
    encodeArgs(fps, crf, path.join(framesDir, "f%04d.png"), outAbs),
    { stdio: "ignore" }
  );
  const kb = (fs.statSync(outAbs).size / 1024).toFixed(0);
  // Drop the intermediate PNG dump — at 1080p it's ~2 MB/frame and we don't
  // need it once the WebM is written (keep --keep-frames to retain for debug).
  if (!process.argv.includes("--keep-frames")) fs.rmSync(framesDir, { recursive: true, force: true });
  console.log("wrote", outAbs, kb + " KB");
}

if (process.argv.includes("--pma0")) process.env.E7_PMA = "0";
const pmaoffIdx = process.argv.indexOf("--pmaoff");
if (pmaoffIdx !== -1 && process.argv[pmaoffIdx + 1]) process.env.E7_PMAOFF = process.argv[pmaoffIdx + 1];
const ehideIdx = process.argv.indexOf("--ehide");
if (ehideIdx !== -1 && process.argv[ehideIdx + 1]) process.env.E7_EHIDE = process.argv[ehideIdx + 1];
const actIdx = process.argv.indexOf("--actanim");
if (actIdx !== -1 && process.argv[actIdx + 1]) process.env.E7_ACTANIM = process.argv[actIdx + 1];
// --pre <dir> <N> <dur> <insertZ> : add a pre-rendered image-seq layer (e.g. 4.2.43 flowers)
const preIdx = process.argv.indexOf("--pre");
if (preIdx !== -1 && process.argv[preIdx + 4]) {
  process.env.E7_PRE_DIR = process.argv[preIdx + 1]; process.env.E7_PRE_N = process.argv[preIdx + 2];
  process.env.E7_PRE_DUR = process.argv[preIdx + 3]; process.env.E7_PRE_Z = process.argv[preIdx + 4];
}
if (process.argv[2] === "--worker") worker();
else orchestrate();
