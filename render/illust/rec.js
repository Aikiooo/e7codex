// WebM capture spike: load stacked illustration layers, composite each frame,
// record a looping WebM (no voicelines). Usage:
//   node rec.js <base> <order-comma> <out.webm> <durSec> <fps> <W> <H>
const puppeteer = require("puppeteer");
const http = require("http");
const fs = require("fs");
const path = require("path");

const ROOT = __dirname;
const [base = "c1153", order = "", out = "out.webm",
       durSec = "21", fps = "30", W = "1200", H = "1500"] = process.argv.slice(2);

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
  const srv = await serve();
  const port = srv.address().port;
  const browser = await puppeteer.launch({ headless: "new",
    args: ["--no-sandbox", "--use-gl=angle", "--use-angle=swiftshader",
           "--enable-features=MediaRecorder"] });
  const page = await browser.newPage();
  await page.setViewport({ width: +W + 40, height: +H + 40, deviceScaleFactor: 1 });
  page.on("console", (m) => { if (m.type() === "error") console.log("[page]", m.text()); });
  const url = `http://localhost:${port}/rec.html?base=${base}&order=${order}&w=${W}&h=${H}`;
  await page.goto(url, { waitUntil: "networkidle0", timeout: 60000 });
  await page.waitForFunction("window.__ready === true", { timeout: 60000 });
  const err = await page.evaluate("window.__err");
  if (err && err.length) console.log("layer errors:", err);
  // let the players warm up a beat so first frame isn't blank
  await new Promise((r) => setTimeout(r, 800));
  console.log(`recording ${durSec}s @ ${fps}fps ${W}x${H} ...`);
  const b64 = await page.evaluate((d, f) => window.__record(d * 1000, f, "#13141d"),
    parseFloat(durSec), parseInt(fps, 10));
  fs.writeFileSync(path.join(ROOT, out), Buffer.from(b64, "base64"));
  const kb = (fs.statSync(path.join(ROOT, out)).size / 1024).toFixed(0);
  console.log("wrote", out, kb + " KB");
  await browser.close(); srv.close();
})();
