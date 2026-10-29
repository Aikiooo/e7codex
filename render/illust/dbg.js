// Diagnostic still: composite the layers at a chosen time + animation, reframed
// on the anchor slot, and screenshot #wrap. Mirrors bake.js framing.
// Usage: node dbg.js <base> <order> <out.png> <t> [anchor] [crop t,b,l,r] [outH] [actanim] [aspect]
//   anchor: slot name | skel | char_skel | union (union = full-scene AABB at t)
//   aspect: "auto" (keep AABB aspect) or a number — trims the union symmetrically
//           to that aspect so the output frame has it (no non-uniform stretch).
// Env (same as bake.js): E7_LAYER_ANIMS, E7_CAM_NEUTRAL, E7_LAYER_ANIM, E7_ACTANIM
const puppeteer = require("puppeteer");
const http = require("http");
const fs = require("fs");
const path = require("path");
const ROOT = __dirname;

const [base, order, out, tA = "0", anchor = "bg2",
       cropA = "0,0,0,0", outHA = "1040", actanim = "", aspectA = "auto"] = process.argv.slice(2);
const t = parseFloat(tA), outH = parseInt(outHA, 10);
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
  const srv = await serve();
  const port = srv.address().port;
  const browser = await puppeteer.launch({ headless: "new",
    args: ["--no-sandbox", "--ignore-gpu-blocklist"] });
  const page = await browser.newPage();
  await page.setViewport({ width: 2200, height: 1400, deviceScaleFactor: 1 });
  const actFromEnv = process.env.E7_ACTANIM || actanim;
  const act = actFromEnv ? "&actanim=" + encodeURIComponent(actFromEnv) : "";
  const anim = process.env.E7_LAYER_ANIM
    ? "&anim=" + encodeURIComponent(process.env.E7_LAYER_ANIM) : "";
  const anims = process.env.E7_LAYER_ANIMS
    ? "&anims=" + encodeURIComponent(process.env.E7_LAYER_ANIMS) : "";
  const camn = process.env.E7_CAM_NEUTRAL === "1" ? "&camneutral=1" : "";
  const ehide = process.env.E7_EHIDE
    ? "&ehide=" + encodeURIComponent(process.env.E7_EHIDE) : "";
  const pmaoff = process.env.E7_PMAOFF
    ? "&pmaoff=" + encodeURIComponent(process.env.E7_PMAOFF) : "";
  const pma0 = process.env.E7_PMA === "0" ? "&pma=0" : "";
  const unionstems = process.env.E7_UNION_STEMS
    ? "&unionstems=" + encodeURIComponent(process.env.E7_UNION_STEMS) : "";
  await page.goto(
    `http://localhost:${port}/rec.html?base=${base}&order=${order}&w=2048&h=${outH}${act}${anim}${anims}${camn}${ehide}${pmaoff}${pma0}${unionstems}`,
    { waitUntil: "networkidle0", timeout: 90000 }
  );
  await page.waitForFunction("window.__ready === true", { timeout: 90000 });

  const useSkel = anchor === "skel" || anchor === "char_skel";
  const useUnion = anchor === "union";
  // Union framing measures the scene at the still time (FX may move/shrink),
  // so the frame cannot clip anything visible at the seek pose. __seek is
  // deterministic/pure — re-seeking after __reframe is safe.
  if (useUnion) await page.evaluate((tt) => window.__seek(tt), t);
  const aabb = await page.evaluate((s, skel, un) => {
    if (un && typeof window.__union_aabb === "function") return window.__union_aabb();
    if (skel && typeof window.__char_skel_aabb === "function") return window.__char_skel_aabb();
    return window.__aabb(s);
  }, anchor, useSkel, useUnion);
  if (!aabb) { console.error("anchor not found", anchor); process.exit(1); }
  // Target aspect override (wallpapers): trim the union symmetrically so the
  // reframe rect has exactly that aspect — keeps the 1:1 world→pixel mapping.
  let trim = crop;
  const aspect = parseFloat(aspectA);
  if (useUnion && isFinite(aspect) && aspect > 0) {
    const ar = aabb.width / aabb.height;
    if (ar > aspect) {
      const cut = 1 - aspect / ar;
      trim = { t: 0, b: 0, l: cut / 2, r: cut / 2 };
    } else if (ar < aspect) {
      const cut = 1 - ar / aspect;
      trim = { t: cut / 2, b: cut / 2, l: 0, r: 0 };
    }
  }
  const cropW = aabb.width * (1 - trim.l - trim.r);
  const cropH = aabb.height * (1 - trim.t - trim.b);
  let W = Math.round(outH * (cropW / cropH)); if (W % 2) W += 1;
  const H = outH % 2 ? outH + 1 : outH;
  await page.evaluate((a, w, h, c) => window.__reframe(a, w, h, 0, c), aabb, W, H, trim);
  await page.evaluate((tt) => new Promise((res) => {
    window.__seek(tt); requestAnimationFrame(() => requestAnimationFrame(res));
  }), t);
  const wrap = await page.$("#wrap");
  await wrap.screenshot({ path: out });
  const phase = await page.evaluate(() =>
    typeof window.__phaseReport === "function" ? window.__phaseReport() : null
  );
  if (phase && phase.layers) {
    console.log(
      "clips:",
      phase.layers.map((L) => `${L.stem}=${L.anim}@${L.dur != null ? L.dur.toFixed(2) + "s" : "?"}`).join("  ")
    );
  }
  const anchorName = useSkel ? "skel" : (useUnion ? "union" : anchor);
  console.log(`${out}  ${W}x${H}  anchor=${anchorName}  dur=${await page.evaluate("window.__dur()")}`);
  await browser.close(); srv.close();
})();
