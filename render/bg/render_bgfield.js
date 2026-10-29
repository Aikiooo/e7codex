// Bake the plates staged by render/bg/bg_field.py with the game's own camera.
//
//   node render/bg/render_bgfield.js                    # every staged plate
//   node render/bg/render_bgfield.js ma_bg_epi5_1       # plates of these pack ids
//   node render/bg/render_bgfield.js --q 1.5            # px per design unit (default 1)
//   node render/bg/render_bgfield.js --index _index_story.json --force
//        # theme plates staged by the story background builder: each entry carries
//        # `out` (repo-relative base path); the plate is written to out + ".webp"
//        # (no thumb, no pack index) and results go to _index_story_baked.json.
//
// Output: site/assets/_bg_field_out/<pack>__<mode>.webp (+ _th) and
// _bg_field_out/_index.json with each plate's coverage (fraction of the frame
// that is painted). Nothing is cropped or re-framed here: the frame IS the
// game's window, so a hole the game would not show is a composition bug to fix
// in bg_field.py, not something to frame away.

const http = require("http");
const fs = require("fs");
const fsp = require("fs/promises");
const path = require("path");
const puppeteer = require("puppeteer");
const sharp = require("sharp");

const ROOT = path.resolve(__dirname, "..", "..");   // E7 Codex
const SRC = path.join(ROOT, "site", "assets", "_bg_field");
const OUT = path.join(ROOT, "site", "assets", "_bg_field_out");
const PORT = 8748;
const MIME = { ".html": "text/html", ".js": "application/javascript", ".css": "text/css",
               ".json": "application/json", ".png": "image/png", ".atlas": "text/plain" };

function server() {
  return http.createServer((req, res) => {
    const url = decodeURIComponent(req.url.split("?")[0]);
    const fp = path.normalize(path.join(ROOT, url));
    if (!fp.startsWith(ROOT) || !fs.existsSync(fp) || fs.statSync(fp).isDirectory()) {
      res.writeHead(404); return res.end();
    }
    res.writeHead(200, { "Content-Type": MIME[path.extname(fp).toLowerCase()] || "application/octet-stream" });
    fs.createReadStream(fp).pipe(res);
  });
}

async function coverage(buf) {
  const { data, info } = await sharp(buf).ensureAlpha().raw().toBuffer({ resolveWithObject: true });
  let painted = 0;
  for (let i = 3; i < data.length; i += 4) if (data[i] > 40) painted++;
  return painted / (info.width * info.height);
}

async function main() {
  const argv = process.argv.slice(2);
  const qi = argv.indexOf("--q");
  const q = qi >= 0 ? parseFloat(argv[qi + 1]) : 1;
  const ii = argv.indexOf("--index");
  const idxName = ii >= 0 ? argv[ii + 1] : "_index.json";
  const custom = idxName !== "_index.json";
  const only = argv.filter((a, i) => !a.startsWith("--") && argv[i - 1] !== "--q" && argv[i - 1] !== "--index");
  const force = argv.includes("--force");
  const index = JSON.parse(fs.readFileSync(path.join(SRC, idxName), "utf-8"));
  const todo = index.filter(m => !m.error && (!only.length || only.includes(m.id)));
  if (!custom) await fsp.mkdir(OUT, { recursive: true });
  const srv = server();
  await new Promise(r => srv.listen(PORT, r));
  const browser = await puppeteer.launch({ headless: "new" });
  const page = await browser.newPage();
  // The index is rewritten after every plate so an interrupted run keeps what it baked.
  const idxPath = custom ? path.join(SRC, idxName.replace(/\.json$/, "_baked.json"))
                         : path.join(OUT, "_index.json");
  let prev = [];
  try { prev = JSON.parse(fs.readFileSync(idxPath, "utf-8")); } catch {}
  const byName = new Map(prev.map(r => [r.name, r]));
  const save = () => fs.writeFileSync(idxPath, JSON.stringify([...byName.values()], null, 1));
  const results = [];
  for (const m of todo) {
    const target = m.out ? path.join(ROOT, m.out + ".webp") : path.join(OUT, m.name + ".webp");
    if (!force && byName.has(m.name) && !byName.get(m.name).error &&
        fs.existsSync(target)) continue;
    try {
      const w = Math.round(m.window.width * q), h = Math.round(m.window.height * q);
      await page.setViewport({ width: w + 40, height: h + 40, deviceScaleFactor: 1 });
      await page.goto(`http://localhost:${PORT}/render/bg/render_bgfield.html?name=${encodeURIComponent(m.name)}&q=${q}&src=${encodeURIComponent(m.src || "_bg_field")}`,
                      { waitUntil: "domcontentloaded" });
      await page.waitForFunction(() => window.__bgState && (window.__bgState.ready || window.__bgState.error),
                                 { timeout: 60000 });
      const st = await page.evaluate(() => window.__bgState);
      if (st.error) throw new Error(st.error);
      const canvas = await page.$("#stage canvas");
      const raw = await canvas.screenshot({ omitBackground: true });
      const cov = await coverage(raw);
      await fsp.mkdir(path.dirname(target), { recursive: true });
      await sharp(raw).webp({ quality: 92 }).toFile(target);
      if (!m.out) await sharp(raw).resize({ height: 480, fit: "inside" }).webp({ quality: 85 })
        .toFile(path.join(OUT, m.name + "_th.webp"));
      results.push({ id: m.id, mode: m.mode, name: m.name, theme: m.theme, w, h, out: m.out || undefined,
                     coverage: +cov.toFixed(4), skipped: m.report.skipped.length,
                     viewport: st.viewport });
      byName.set(m.name, results[results.length - 1]); save();
      console.log(`${m.name.padEnd(36)} ${w}x${h} coverage ${(cov * 100).toFixed(1)}%` +
                  ` skipped ${m.report.skipped.length}`);
    } catch (e) {
      results.push({ id: m.id, mode: m.mode, name: m.name, error: String(e.message).slice(0, 200) });
      byName.set(m.name, results[results.length - 1]); save();
      console.log(`FAIL ${m.name}: ${String(e.message).slice(0, 160)}`);
    }
  }
  await browser.close();
  srv.close();
  save();
  console.log(`baked ${results.filter(r => !r.error).length}, failed ${results.filter(r => r.error).length}`);
}

main().catch(e => { console.error(e); process.exit(1); });
