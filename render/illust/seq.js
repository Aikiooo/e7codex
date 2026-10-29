// Deterministic frame-sequence WebM bake, cropped to the picture rectangle.
// Probes the anchor slot's world AABB, reframes every layer onto it (clipping
// the outer effects), seeks to exact times, screenshots, assembles -> WebM.
// Usage: node seq.js <base> <order> <out.webm> <fps> <anchorSlot> <outH> [pad] [maxSec]
const puppeteer = require("puppeteer");
const http = require("http");
const fs = require("fs");
const path = require("path");
const { execFileSync } = require("child_process");

const ROOT = __dirname;
const [base = "c1153", order = "", out = "out.webm", fpsA = "24",
       anchor = "bg_2", outHA = "720", cropA = "0,0,0,0", maxSecA = "0",
       crfA = "28"] = process.argv.slice(2);
const fps = parseInt(fpsA, 10);
const outH = parseInt(outHA, 10);
const [cT, cB, cL, cR] = cropA.split(",").map(parseFloat);
const crop = { t: cT || 0, b: cB || 0, l: cL || 0, r: cR || 0 };
const maxSec = parseFloat(maxSecA);
const crf = crfA;

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

(async () => {
  const framesDir = path.join(ROOT, "_frames_" + path.basename(out, ".webm"));
  fs.rmSync(framesDir, { recursive: true, force: true });
  fs.mkdirSync(framesDir);

  const srv = await serve();
  const port = srv.address().port;
  const browser = await puppeteer.launch({ headless: "new",
    args: ["--no-sandbox", "--use-gl=angle", "--use-angle=swiftshader"] });
  const page = await browser.newPage();
  await page.setViewport({ width: 2200, height: 1600, deviceScaleFactor: 1 });
  page.on("console", (m) => { if (m.type() === "error") console.log("[page]", m.text()); });
  // load big so layers have room before reframe
  const url = `http://localhost:${port}/rec.html?base=${base}&order=${order}&w=2000&h=1400`;
  await page.goto(url, { waitUntil: "networkidle0", timeout: 60000 });
  await page.waitForFunction("window.__ready === true", { timeout: 60000 });
  const err = await page.evaluate("window.__err");
  if (err && err.length) console.log("layer errors:", err);

  const aabb = await page.evaluate((s) => window.__aabb(s), anchor);
  if (!aabb) { console.error("anchor slot not found:", anchor); process.exit(1); }
  const cropW = aabb.width * (1 - crop.l - crop.r);
  const cropH = aabb.height * (1 - crop.t - crop.b);
  const aspect = cropW / cropH;
  let W = Math.round(outH * aspect); if (W % 2) W += 1;
  const H = outH % 2 ? outH + 1 : outH;
  console.log(`rect ${aabb.width.toFixed(0)}x${aabb.height.toFixed(0)} crop[t${crop.t} b${crop.b} l${crop.l} r${crop.r}] -> ${W}x${H} (a=${aspect.toFixed(3)})`);
  await page.evaluate((a, w, h, c) => window.__reframe(a, w, h, 0, c), aabb, W, H, crop);
  await new Promise((r) => setTimeout(r, 400));

  let dur = await page.evaluate("window.__dur()");
  if (maxSec > 0 && dur > maxSec) dur = maxSec;
  const N = Math.max(1, Math.round(dur * fps));
  console.log(`loop ${dur.toFixed(2)}s -> ${N} frames @ ${fps}fps`);

  const wrap = await page.$("#wrap");
  for (let i = 0; i < N; i++) {
    const t = i * (dur / N);
    await page.evaluate((tt) => window.__seek(tt), t);
    await new Promise((r) => setTimeout(r, 25));
    await wrap.screenshot({ path: path.join(framesDir, `f${String(i).padStart(4, "0")}.png`) });
    if (i % 30 === 0) process.stdout.write(`  ${i}/${N}\r`);
  }
  console.log(`\ncaptured ${N} frames, encoding...`);
  await browser.close(); srv.close();

  execFileSync("ffmpeg", ["-y", "-framerate", String(fps),
    "-i", path.join(framesDir, "f%04d.png"),
    "-c:v", "libvpx-vp9", "-pix_fmt", "yuv420p", "-crf", crf, "-b:v", "0",
    "-an", path.join(ROOT, out)], { stdio: "ignore" });
  const kb = (fs.statSync(path.join(ROOT, out)).size / 1024).toFixed(0);
  console.log("wrote", out, kb + " KB");
})();
