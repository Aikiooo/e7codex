// Quality metrics for rendered backgrounds: how much of the frame is actually
// opaque. In-game these scenes are full-bleed, so a low opaque fraction means
// the layer stack is incomplete (a base layer that lives in another atlas, an
// outlier layer inflating the frame, …). Same alpha cutoff as the gate in
// render_backgrounds.js so the two agree on what "opaque" means.
//
//   node render/bg/bg_report.js            # table for every rendered background
//   node render/bg/bg_report.js --json     # machine-readable
const fs = require("fs");
const path = require("path");
const sharp = require("sharp");

const ROOT = path.resolve(__dirname, "..", "..");   // E7 Codex
const OUT = path.join(ROOT, "site", "assets", "_bg");

async function metrics(file) {
  const im = sharp(file);
  const meta = await im.metadata();
  const { data, info } = await im.ensureAlpha().raw().toBuffer({ resolveWithObject: true });
  let opaque = 0, nonEmpty = 0;
  const n = info.width * info.height;
  for (let i = 3; i < data.length; i += 4) {
    const a = data[i];
    if (a > 200) opaque++;
    if (a > 8) nonEmpty++;
  }
  return { w: meta.width, h: meta.height, opaque: opaque / n, nonEmpty: nonEmpty / n };
}

async function main() {
  const files = fs.readdirSync(OUT).filter(f => f.endsWith(".webp") && !f.endsWith("_th.webp"));
  const rows = [];
  for (const f of files) {
    const m = await metrics(path.join(OUT, f));
    rows.push({ name: f.replace(/\.webp$/, ""), ...m });
  }
  rows.sort((a, b) => a.opaque - b.opaque);
  if (process.argv.includes("--json")) {
    console.log(JSON.stringify(rows, null, 1));
    return;
  }
  const low = rows.filter(r => r.opaque < 0.85);
  console.log(`rendered: ${rows.length}   opaque<0.85: ${low.length}`);
  console.log("lowest 40:");
  for (const r of rows.slice(0, 40)) {
    console.log(`  ${r.opaque.toFixed(3)}  ${String(r.w) + "x" + r.h}  ${r.name}`);
  }
  const buckets = [0.1, 0.3, 0.5, 0.7, 0.85, 0.95, 1.01];
  let prev = 0, acc = [];
  for (const b of buckets) {
    const c = rows.filter(r => r.opaque >= prev && r.opaque < b).length;
    acc.push(`${prev}-${b}:${c}`); prev = b;
  }
  console.log("histogram:", acc.join("  "));
}

main().catch(e => { console.error(e); process.exit(1); });
