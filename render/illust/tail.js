// Render a short run of continuation frames at t = start + j*(1/fps), reusing one
// browser/page, so a crossfade-loop can blend the seam. Mirrors bake.js framing.
// Usage: node tail.js <base> <order> <outDir> <anchor> <crop t,b,l,r> <outH> <fps> <start> <count> [actanim]
const puppeteer = require("puppeteer");
const http = require("http");
const fs = require("fs");
const path = require("path");
const ROOT = __dirname;

const [base, order, outDir, anchor, cropA, outHA, fpsA, startA, countA, actanim = ""] =
  process.argv.slice(2);
const outH = parseInt(outHA, 10), fps = parseInt(fpsA, 10);
const start = parseFloat(startA), count = parseInt(countA, 10);
const [cT, cB, cL, cR] = cropA.split(",").map(parseFloat);
const crop = { t: cT || 0, b: cB || 0, l: cL || 0, r: cR || 0 };

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
  fs.mkdirSync(outDir, { recursive: true });
  const srv = await serve();
  const port = srv.address().port;
  const browser = await puppeteer.launch({ headless: "new",
    args: ["--no-sandbox", "--ignore-gpu-blocklist"] });
  const page = await browser.newPage();
  await page.setViewport({ width: 2200, height: 1400, deviceScaleFactor: 1 });
  const act = actanim ? "&actanim=" + encodeURIComponent(actanim) : "";
  const pre = process.env.E7_PRE_DIR
    ? `&preDir=${encodeURIComponent(process.env.E7_PRE_DIR)}&preN=${process.env.E7_PRE_N}&preDur=${process.env.E7_PRE_DUR}&preZ=${process.env.E7_PRE_Z}` : "";
  await page.goto(`http://localhost:${port}/rec.html?base=${base}&order=${order}&w=2048&h=${outH}${act}${pre}`,
    { waitUntil: "networkidle0", timeout: 90000 });
  await page.waitForFunction("window.__ready === true", { timeout: 90000 });
  const aabb = await page.evaluate((s) => {
    if (s === "world0" || s === "base_scale") return window.__world0_aabb(1920, 1080);
    return window.__aabb(s);
  }, anchor);
  if (!aabb) { console.error("tail: aabb null for anchor", anchor); process.exit(1); }
  const cropW = aabb.width * (1 - crop.l - crop.r), cropH = aabb.height * (1 - crop.t - crop.b);
  let W = Math.round(outH * (cropW / cropH)); if (W % 2) W += 1;
  const H = outH % 2 ? outH + 1 : outH;
  await page.evaluate((a, w, h, c) => window.__reframe(a, w, h, 0, c), aabb, W, H, crop);
  const wrap = await page.$("#wrap");
  for (let j = 0; j < count; j++) {
    const t = start + j / fps;
    await page.evaluate((tt) => new Promise((res) => {
      window.__seek(tt); requestAnimationFrame(() => requestAnimationFrame(res));
    }), t);
    await wrap.screenshot({ path: path.join(outDir, `t${String(j).padStart(4, "0")}.png`) });
  }
  console.log(`tail: ${count} frames @ ${W}x${H} from t=${start}`);
  await browser.close(); srv.close();
})();
