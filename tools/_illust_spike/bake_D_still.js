/** Still probe: char skeleton world + DESIGN 1920x1080 aspect (exact-data). */
const puppeteer = require("puppeteer");
const http = require("http");
const fs = require("fs");
const path = require("path");

const ROOT = path.join("D:", "Claude", "E7", "E7 Codex", "tools", "_illust_spike");
const OUT = path.join("D:", "Claude", "E7", "_scratch", "lobby_aube");
const order =
  "illeff_vsu6aa_01_bg_b,illeff_vsu6aa_01_b,illeff_vsu6aa_01,illeff_vsu6aa_01_bg_f";

// Rank 2: main char skeleton bounds (spine JSON) + runtime center of that layer
const WORLD = {
  x: 21.530401108311708,
  y: 85.89064455550897,
  width: 3886.5,
  height: 1855.5899658203125,
};
// Rank 1: DESIGN_WIDTH/HEIGHT 1920x1080
const RES = { w: 1920, h: 1080 };

function aspectCrop(aabbW, aabbH, resW, resH) {
  const t = resW / resH;
  const s = aabbW / aabbH;
  if (Math.abs(s - t) < 1e-6) return { t: 0, b: 0, l: 0, r: 0 };
  if (s > t) {
    const keep = t / s;
    const side = (1 - keep) / 2;
    return { t: 0, b: 0, l: side, r: side };
  }
  const keep = s / t;
  const side = (1 - keep) / 2;
  return { t: side, b: side, l: 0, r: 0 };
}

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

(async () => {
  const srv = await serve();
  const port = srv.address().port;
  const browser = await puppeteer.launch({
    headless: "new",
    args: [
      "--no-sandbox",
      "--ignore-gpu-blocklist",
      "--enable-gpu-rasterization",
    ],
  });
  const page = await browser.newPage();
  await page.setViewport({ width: 2100, height: 1500, deviceScaleFactor: 1 });
  const url =
    `http://localhost:${port}/rec.html?base=vsu6aa_lobby` +
    `&order=${encodeURIComponent(order)}&w=2000&h=1400`;
  await page.goto(url, { waitUntil: "networkidle0", timeout: 120000 });
  await page.waitForFunction("window.__ready === true", { timeout: 120000 });

  const crop = aspectCrop(WORLD.width, WORLD.height, RES.w, RES.h);
  const aspect = RES.w / RES.h;
  // 2x design HQ
  let H = 2160;
  let W = Math.round(H * aspect);
  if (W % 2) W += 1;
  if (H % 2) H += 1;
  console.log("out", W, H, "crop", JSON.stringify(crop));

  await page.setViewport({ width: W + 40, height: H + 40, deviceScaleFactor: 1 });
  await page.evaluate(
    (a, w, h, c) => window.__reframe(a, w, h, 0, c),
    WORLD,
    W,
    H,
    crop
  );

  for (const t of [0.5, 2.0, 5.0, 10.0]) {
    await page.evaluate(
      (tt) =>
        new Promise((r) => {
          window.__seek(tt);
          requestAnimationFrame(() => requestAnimationFrame(r));
        }),
      t
    );
    const wrap = await page.$("#wrap");
    const out = path.join(
      OUT,
      "still_D_t" + String(t).replace(".", "p") + ".png"
    );
    await wrap.screenshot({ path: out, omitBackground: false });
    console.log("wrote", out);
  }

  // Canonical still name
  fs.copyFileSync(
    path.join(OUT, "still_D_t0p5.png"),
    path.join(OUT, "aube_lobby_idle_hq_still.png")
  );

  await browser.close();
  srv.close();
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
