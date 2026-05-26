// Compute bounding-box trim fractions for every pose.png and write a small
// pose_trim.json sidecar alongside it.  Run this once (or after re-renders):
//
//   node tools/compute_trim_data.js                            # all slugs missing pose_trim.json
//   node tools/compute_trim_data.js --force                    # recompute all
//   node tools/compute_trim_data.js c1001 c1046_s02_1         # specific slugs
//   node tools/compute_trim_data.js --threshold 40 --force c2009  # test a threshold value
//   node tools/compute_trim_data.js --alpha-only --threshold 20 --force c2076_1  # test alpha-only
//
// build_index.py reads pose_trim.json and inlines it into units.json so the
// hub can crop the detail-page pose.png with pure CSS math (no runtime canvas
// scan). Thumbnails do their own smart-crop at bake time in render_thumbs.js,
// so there is no thumb_trim sidecar to compute here.

const fs    = require("fs");
const fsp   = require("fs/promises");
const path  = require("path");
const sharp = require("sharp");

const SITE      = path.resolve(__dirname, "..", "site");
const ASSETS    = path.join(SITE, "assets");

// Default alpha threshold for the "visible character" bounding box.
// sharp.trim uses color-distance from background, so threshold:10 trims pixels
// that are barely different from transparent — near-transparent glow halos etc.
// See SLUG_THRESHOLDS below to override per slug without changing the global default.
const DEFAULT_THRESHOLD = 10;

// Per-slug overrides. A full --force rebuild always applies these, so the result
// is identical across machines and fresh dumps.
//
// Value forms:
//   N                       use sharp.trim with threshold N  (handles semi-transparent halos)
//   { threshold: N }        same
//   { threshold: N, alphaOnly: true }  pure alpha-channel bbox — use when the effect is
//                           *colored* (a red blood drop, a blue ice aura) so its RGB channels
//                           make sharp's color-distance metric ignore the threshold entirely.
//   { ..., pad: F }         after the bbox is computed, expand it outward by F (fraction of
//                           canvas) on every side. Use when percentile trimming clips outfit
//                           edges — pad recovers those pixels without re-admitting the outlier.
//
// Tuning guide:
//   higher threshold = more aggressive trim (excludes near-transparent colored effects)
//   alphaOnly: true  = ignore RGB, trim only by alpha value (right for colored near-transparent fx)
//   pad: 0.01–0.03   = outward expansion after percentile cut (recovers edge clipping)
const SLUG_THRESHOLDS = {
  "c2046_s01": 75,                              // speech bubble alpha ~20–75; threshold=75 excludes it
  "c2076_1":   { threshold: 75, alphaOnly: true },  // colored glow; alpha-only:75 is the tightest achievable
  "c4052":     20,                              // barely-visible square artifact
  "c2009":     40,                              // reddish aura (mostly left side)
  "c6005":     75,                              // light rays (right side)
  "c5070":     75,                              // smoke surrounding unit
  "c1148":     { threshold: 20, alphaOnly: true },  // icy blue aura extending right
  // c6050: blood drop alpha >240 — threshold can't exclude it; use percentile bbox
  // to reject the outermost 0.05% of pixel positions on each axis.
  // pad:0.015 recovers outfit pixels slightly over-clipped by the percentile cut.
  "c6050":     { threshold: 10, alphaOnly: true, percentile: 0.999, pad: 0.015 },
};

function listSlugs() {
  if (!fs.existsSync(ASSETS)) return [];
  return fs.readdirSync(ASSETS).filter(s => {
    const d = path.join(ASSETS, s);
    return fs.statSync(d).isDirectory()
        && fs.existsSync(path.join(d, "pose.png"));
  });
}

// Alpha-only bounding box: scan raw pixels and find the extent of pixels with
// alpha > threshold.  Correct for colored effects whose RGB values make
// sharp.trim's color-distance metric insensitive to the threshold parameter.
//
// percentile < 1.0: use marginal histograms to reject extreme outlier pixels.
// E.g. percentile=0.999 excludes the outermost 0.05% of alpha>threshold pixel
// positions on each axis — enough to clip an isolated blood drop or similar
// tiny opaque element that sits far from the main character.
async function alphaBbox(pngPath, alphaThreshold, percentile = 1.0) {
  const { data, info } = await sharp(pngPath)
    .raw()
    .toBuffer({ resolveWithObject: true });
  const { width, height, channels } = info;

  if (percentile >= 1.0) {
    // Fast path — simple min/max scan.
    let minX = width, maxX = -1, minY = height, maxY = -1;
    for (let y = 0; y < height; y++) {
      for (let x = 0; x < width; x++) {
        if (data[(y * width + x) * channels + channels - 1] > alphaThreshold) {
          if (x < minX) minX = x;
          if (x > maxX) maxX = x;
          if (y < minY) minY = y;
          if (y > maxY) maxY = y;
        }
      }
    }
    if (maxX < 0) return null;
    return { l: minX / width, t: minY / height,
             fw: (maxX - minX + 1) / width, fh: (maxY - minY + 1) / height };
  }

  // Percentile path — marginal histograms.
  const xHist = new Int32Array(width);
  const yHist = new Int32Array(height);
  let total = 0;
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      if (data[(y * width + x) * channels + channels - 1] > alphaThreshold) {
        xHist[x]++; yHist[y]++; total++;
      }
    }
  }
  if (total === 0) return null;

  const margin = Math.max(1, Math.floor(total * (1 - percentile) / 2));

  let cum = 0, minX = 0;
  for (let x = 0; x < width;  x++) { cum += xHist[x]; if (cum > margin) { minX = x; break; } }
  cum = 0; let maxX = width - 1;
  for (let x = width - 1; x >= 0; x--) { cum += xHist[x]; if (cum > margin) { maxX = x; break; } }
  cum = 0; let minY = 0;
  for (let y = 0; y < height; y++) { cum += yHist[y]; if (cum > margin) { minY = y; break; } }
  cum = 0; let maxY = height - 1;
  for (let y = height - 1; y >= 0; y--) { cum += yHist[y]; if (cum > margin) { maxY = y; break; } }

  return { l: minX / width, t: minY / height,
           fw: (maxX - minX + 1) / width, fh: (maxY - minY + 1) / height };
}

async function computeOne(slug, cliThreshold, cliAlphaOnly) {
  // Resolve effective settings: CLI flags (from --threshold / --alpha-only)
  // bypass per-slug overrides so you can test any value interactively.
  // When no CLI threshold was given, SLUG_THRESHOLDS applies.
  let threshold = cliThreshold ?? DEFAULT_THRESHOLD;
  let alphaOnly = cliAlphaOnly ?? false;
  let percentile = 1.0;
  let pad = 0;
  if (cliThreshold === null) {
    const ov = SLUG_THRESHOLDS[slug];
    if (ov !== undefined) {
      if (typeof ov === "object") {
        threshold  = ov.threshold;
        alphaOnly  = ov.alphaOnly  ?? false;
        percentile = ov.percentile ?? 1.0;
        pad        = ov.pad        ?? 0;
      } else { threshold = ov; }
    }
  }

  const pngPath  = path.join(ASSETS, slug, "pose.png");
  const trimPath = path.join(ASSETS, slug, "pose_trim.json");

  let l, t, fw, fh;
  if (alphaOnly) {
    const bb = await alphaBbox(pngPath, threshold, percentile);
    if (!bb) { l = 0; t = 0; fw = 1; fh = 1; }
    else      { ({ l, t, fw, fh } = bb); }
  } else {
    const orig = await sharp(pngPath).metadata();
    if (!orig.width || !orig.height) throw new Error("bad metadata");
    const { info } = await sharp(pngPath)
      .trim({ threshold })
      .toBuffer({ resolveWithObject: true });
    l  = -(info.trimOffsetLeft || 0) / orig.width;
    t  = -(info.trimOffsetTop  || 0) / orig.height;
    fw = (info.width  || orig.width)  / orig.width;
    fh = (info.height || orig.height) / orig.height;
  }

  // Expand bbox outward by pad (fraction of canvas) on every side — use when
  // percentile clipping slightly over-trims outfit edges.
  if (pad > 0) {
    const r = Math.min(1, l + fw + pad);
    const b = Math.min(1, t + fh + pad);
    l  = Math.max(0, l - pad);
    t  = Math.max(0, t - pad);
    fw = r - l;
    fh = b - t;
  }

  // Round to 5 decimal places — enough precision, keeps the file small.
  // Only write a sidecar when the crop is meaningful (either axis < 90% of full).
  const SKIP = 0.9;
  const data = (fw < SKIP || fh < SKIP) ? {
    l:  +l.toFixed(5),
    t:  +t.toFixed(5),
    fw: +fw.toFixed(5),
    fh: +fh.toFixed(5),
  } : null;
  await fsp.writeFile(trimPath, data ? JSON.stringify(data) : "null");
  return { data, threshold, alphaOnly };
}

(async () => {
  const args     = process.argv.slice(2);
  const force    = args.includes("--force");
  const tIdx     = args.indexOf("--threshold");
  // null = "not provided" — distinguishes from "user passed DEFAULT_THRESHOLD explicitly"
  const cliThreshold = tIdx !== -1 ? parseInt(args[tIdx + 1], 10) : null;
  const cliAlphaOnly = args.includes("--alpha-only") ? true : null;
  const only = args.filter((a, i) =>
    !a.startsWith("--") &&
    args[i - 1] !== "--threshold"
  );
  const slugs = (only.length ? only : listSlugs())
    .filter(s => fs.existsSync(path.join(ASSETS, s, "pose.png")))
    .filter(s => force || !fs.existsSync(path.join(ASSETS, s, "pose_trim.json")));

  if (!slugs.length) { console.log("nothing to compute."); process.exit(0); }
  if (cliThreshold !== null) {
    console.log(`threshold: ${cliThreshold}${cliAlphaOnly ? " alpha-only" : ""} (cli — slug overrides bypassed)`);
  }

  let ok = 0, fail = 0;
  for (const slug of slugs) {
    try {
      const { data, threshold, alphaOnly } = await computeOne(slug, cliThreshold, cliAlphaOnly);
      ok++;
      const info = data ? `l=${data.l} t=${data.t} fw=${data.fw} fh=${data.fh}` : "no-crop";
      const ov   = SLUG_THRESHOLDS[slug];
      const tag  = (ov !== undefined && cliThreshold === null)
        ? ` (threshold:${threshold}${alphaOnly ? " alpha-only" : ""})`
        : "";
      console.log(`[ok]   ${slug}  ${info}${tag}`);
    } catch (e) {
      fail++;
      console.log(`[fail] ${slug}: ${e.message}`);
    }
  }
  console.log(`\n[summary] ${ok} ok · ${fail} failed · ${slugs.length} total`);
  process.exit(fail ? 1 : 0);
})();
