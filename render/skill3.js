// Bake the FULL skill-3 clip (all chained skill3 segments + composited skill
// FX) per combat unit into site/assets/<slug>/combat/sk3_full.webp (animated
// WebP with alpha). TASKS #57.
//
// Strategy: drive site/viewer.html itself in headless Chrome — its FX engine
// (TASKS #58: cue scheduler, phantom-enemy offset, overscan layers) and its
// export composite (fxExportLayers: back-FX → character → front-FX, sampling
// the overscan centre) are reused verbatim. The chain is driven through
// animationState.addAnimation (NOT player.setAnimation, which would recompute
// the viewport per segment); framing is a UNION of every segment's
// calculateAnimationViewport, widened for enemy-side (tgt) FX spawns.
// Frames are captured with REAL timestamps and encoded with a per-frame delay
// array, so render lag can never speed the clip up. Encoding happens in node
// via sharp (libvips) — the in-page libwebp WASM heap aborts around ~190
// frames at 720p, too small for c1009's ~280-frame chain.
//
// Usage:
//   node render/skill3.js c1009 c1019 c1001 c1007     # explicit slugs
//   node render/skill3.js --all                       # every combat unit with a skill3
//   node render/skill3.js --all --force               # re-bake existing
//   flags: --maxh 720  --fps 24  --q 85  --effort 4       # quality knobs
//          (900px/30fps later = just --maxh 900 --fps 30)
//          --jobs 3   # concurrent workers, one browser instance each
//
// Throughput (2026-06-11): the serial pace was 11-15 units/h, dominated by
// (a) one-unit-at-a-time capture, (b) the encode ladder re-encoding every
// step from scratch, (c) one CDP round-trip per captured frame. Now: N
// workers each own a BROWSER INSTANCE (not just a page — the 16-context
// WebGL eviction cap is per GPU process, and two cinematic units sharing
// one browser would blank each other's scenes); the ladder jumps to the
// estimated-fitting step; frames transfer in batches; the warm-up pass
// runs at 3x timeScale (it only exists to warm FX rig fetch/parse caches).
// Capture stays track-time-driven, so GPU contention between workers can
// only make a bake slower, never wrong.
//
// Requires the staged combat rigs + combat/fx (prepare_combat_assets.py /
// prepare_fx_assets.py already run). GPU traps: see the e7-spine-render skill —
// fidelity comes from canvas CSS size (the Quality multiplier), never DSR.

const http = require("http");
const fs   = require("fs");
const fsp  = require("fs/promises");
const path = require("path");
const puppeteer = require("puppeteer");
const sharp = require("sharp");

const ROOT = path.resolve(__dirname, "..");
const SITE = path.join(ROOT, "site");
// Cut-in webps (the game's hand-drawn S3 inserts). Node can't import
// e7lib/config.py — mirror its default layout under the dump root like
// render/illust/bake.js does.
const CUT_DIR = path.join(ROOT, "..", "extracted_data", "img_output", "cut", "fhd");
const PORT = 8761;

// GPU-first launch (same rationale as render/illust/bake.js): let ANGLE
// pick the D3D11 hardware path; if unavailable Chromium falls back to software
// and the timestamped capture still produces a correct (if lower-fps) clip.
const GPU_ARGS = ["--no-sandbox", "--ignore-gpu-blocklist",
  "--enable-gpu-rasterization", "--enable-zero-copy",
  "--disable-frame-rate-limit",
  // Chrome silently loses the OLDEST WebGL context past 16 live ones —
  // estelle's skill3 runs 29 effect players and the cascade blanked whole
  // cinematic scenes (and once even the character player). The viewer's
  // lazy pool keeps the count near the edge; the bake simply raises the cap.
  "--max-active-webgl-contexts=64"];

const MIME = {".html":"text/html",".js":"application/javascript",".css":"text/css",
              ".json":"application/json",".png":"image/png",".atlas":"text/plain",
              ".webp":"image/webp",".wasm":"application/wasm"};

function makeServer() {
  return http.createServer((req, res) => {
    let url = decodeURIComponent(req.url.split("?")[0]);
    const fp = path.normalize(path.join(ROOT, url));
    if (!fp.startsWith(ROOT) || !fs.existsSync(fp) || fs.statSync(fp).isDirectory()) {
      res.writeHead(404); return res.end("404 " + url);
    }
    res.writeHead(200, { "Content-Type": MIME[path.extname(fp).toLowerCase()] || "application/octet-stream" });
    fs.createReadStream(fp).pipe(res);
  });
}

function listCombatSlugs() {
  const dir = path.join(SITE, "assets");
  return fs.readdirSync(dir).filter(s =>
    fs.existsSync(path.join(dir, s, "combat", s + ".json")));
}

// Natural sort so skill3_2 < skill3_10 and skill3 (bare) sorts first.
function natCompare(a, b) {
  const ta = a.split(/(\d+)/), tb = b.split(/(\d+)/);
  for (let i = 0; i < Math.max(ta.length, tb.length); i++) {
    const x = ta[i] ?? "", y = tb[i] ?? "";
    if (x === y) continue;
    const nx = parseInt(x, 10), ny = parseInt(y, 10);
    if (!isNaN(nx) && !isNaN(ny)) return nx - ny;
    return x < y ? -1 : 1;
  }
  return 0;
}

// Phantom-enemy distance for enemy-side (tgt) effects. The viewer defaults to
// 600 for its own stage box; the bake pushes the enemy out to match in-game
// footage (ravi's thrown axe / explosion separation — user screenshots
// 2026-06-10). Injected into the page via window.__fxTargetDx.
const TARGET_DX = 1100;

// World-space x/y extents the chain's FX cues need beyond the character's own
// animation bounds: cue x/y offsets plus the phantom-enemy offset for tgt
// spawns, with margin for the effect's own size.
function fxExtents(cues, chain) {
  const FX_TARGET_DX = TARGET_DX, MARGIN = 250;
  let minX = 0, maxX = 0, minY = 0, maxY = 0, any = false;
  for (const anim of chain) {
    for (const c of (cues && cues.anims && cues.anims[anim]) || []) {
      if (!c.spawn) continue;
      for (const prim of c.spawn.prims || []) {
        const x = (c.spawn.x || 0) + (prim.x || 0) + (c.spawn.tgt ? FX_TARGET_DX : 0);
        const y = (c.spawn.y || 0) + (prim.y || 0);
        any = true;
        minX = Math.min(minX, x - MARGIN); maxX = Math.max(maxX, x + MARGIN);
        minY = Math.min(minY, y - MARGIN); maxY = Math.max(maxY, y + MARGIN);
      }
    }
  }
  return any ? { minX, maxX, minY, maxY } : null;
}

async function bakeOne(browser, slug, opts, say = console.log) {
  const combatDir = path.join(SITE, "assets", slug, "combat");
  const outFile = path.join(combatDir, "sk3_full.webp");
  const cuesFile = path.join(combatDir, "fx", "cues.json");
  const hasFx = fs.existsSync(cuesFile);
  const cues = hasFx ? JSON.parse(fs.readFileSync(cuesFile, "utf8")) : null;

  const page = await browser.newPage();
  try {
    // 16:9-ish stage so wide skill scenes (character + enemy-side FX) fit;
    // Quality 2x below doubles the canvas backing buffer for supersampling.
    await page.setViewport({ width: 1600, height: 1000, deviceScaleFactor: 1 });
    page.on("pageerror", e => say(`  [pageerror] ${slug}: ${e.message}`));
    await page.evaluateOnNewDocument((dx, sharedGl) => {
      window.__fxTargetDx = dx;        // in-game enemy separation
      window.__fxScheduleMode = true;  // effects persist across segment switches
      // shared-GL compositor: re-draw visible spine FX into one framebuffer
      // per depth bucket with per-slot blend modes (fixes cross-rig additive
      // exported source-over — estelle's magenta finale core). --nosharedgl
      // reverts to the per-rig-canvas composite for A/B.
      window.__fxSharedGL = sharedGl;
    }, TARGET_DX, !opts.nosharedgl);
    await page.goto(`http://localhost:${PORT}/site/viewer.html?slug=${slug}&rig=combat`,
                    { waitUntil: "domcontentloaded" });
    await page.waitForFunction(
      "typeof player !== 'undefined' && player && player.skeleton && player.skeleton.data",
      { timeout: 60000 });
    if (hasFx) {
      // cues.json exists on disk, so the engine must come up; don't bake bare.
      await page.waitForFunction("typeof fxEngine !== 'undefined' && fxEngine !== null",
                                 { timeout: 15000 });
      // shared-GL compositor: wait until every mirror skeleton resolved, or
      // captures can race the atlas fetches and mix per-rig source-over
      // layers into shared frames mid-run (transient black/washed layers)
      await page.waitForFunction(
        "!fxEngine._sglReady || fxEngine._sglReady()", { timeout: 30000 });
    }

    // The schedule. Preferred source: combat/s3.json — the stagept
    // choreography compiled by prepare_fx_assets.py (segment starts incl.
    // engine HOLDS, cut-in splice points, end over effect tails; times are
    // SPINE-LOCAL ms). Fallback when no graph exists: the v1 natural-order
    // chain, rebuilt as a synthetic back-to-back schedule.
    const s3File = path.join(combatDir, "s3.json");
    let sched = null;
    if (fs.existsSync(s3File)) {
      const s3 = JSON.parse(fs.readFileSync(s3File, "utf8"));
      const t0 = s3.segments[0].t;   // drop the pre-roll before the first anim
      sched = {
        segments: s3.segments.map(s => ({ anim: s.anim, t: s.t - t0 })),
        cutins: (s3.cutins || []).map(c => ({ src: c.src, t: Math.max(0, c.t - t0) })),
        moves: (s3.moves || []).map(m => ({ ...m, t: Math.max(0, m.t - t0) })),
        end: s3.end - t0,
        fieldback: s3.fieldback != null ? Math.max(0, s3.fieldback - t0) : null,
        cutawayT: s3.cutaway_t != null ? Math.max(0, s3.cutaway_t - t0) : null,
        cutaway: !!s3.cutaway,
        // authored director track (compiled from the same stagept graph):
        // CAM/ZOOM tweens + cm-rig SHAKE paths, and DARK fullscreen fades
        camera: (s3.camera || []).map(c => ({ ...c, t: Math.max(0, c.t - t0) })),
        dark: (s3.dark || []).map(d => ({ ...d, t: Math.max(0, d.t - t0) })),
      };
    } else {
      const chain = (await page.evaluate(() =>
        player.skeleton.data.animations
          .filter(a => /^skill3(_|$)/.test(a.name) && a.duration > 0)
          .map(a => ({ name: a.name, duration: a.duration }))))
        .sort((a, b) => natCompare(a.name, b.name));
      if (!chain.length) return { skip: "no skill3 animations" };
      let acc = 0;
      const segments = chain.map(c => { const s = { anim: c.name, t: acc }; acc += c.duration * 1000; return s; });
      sched = { segments, cutins: [], end: acc };
      // Graphless units still flash their hand-drawn cut-in in-game: the
      // rig's own `cutin` spine event marks the splice point (same fallback
      // prepare_fx_assets uses when a graph carries no CUTIN node).
      const evs = await page.evaluate(names => {
        const out = [];
        for (const n of names) {
          const a = player.skeleton.data.animations.find(a => a.name === n);
          if (!a) continue;
          for (const tl of a.timelines || []) {
            if (!tl.events) continue;
            for (const ev of tl.events)
              if (ev.data && ev.data.name === "cutin") out.push({ anim: n, t: ev.time * 1000 });
          }
        }
        return out;
      }, segments.map(s => s.anim));
      if (evs.length) {
        const base = slug.split("_")[0];
        for (const cand of [`sk_${slug}_3.webp`, `sk_${base}_3.webp`]) {
          if (fs.existsSync(path.join(CUT_DIR, cand))) {
            const seg = segments.find(s => s.anim === evs[0].anim);
            sched.cutins.push({ src: cand, t: Math.round(seg.t + evs[0].t) });
            break;
          }
        }
      }
    }
    const names = [...new Set(sched.segments.map(s => s.anim))];
    const totalDur = sched.end / 1000;

    // Quality 2x — same dance the screenshot button does (the change event
    // doesn't fire handlers when set from script).
    await page.evaluate(async () => {
      qSel.value = "2"; zoom = 1; panX = 0; panY = 0; apply();
      window.dispatchEvent(new Event("resize"));
      await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));
    });

    // Union viewport across the chain + FX extents, pinned with the viewer's
    // absolute-unit padding. previousViewport=null kills the transition lerp.
    // Cinematic (stagept-scheduled) units get a MINIMUM frame: their scene
    // effect rigs are authored at screen scale (~1200+ world units), and a
    // short wind-up anim (estelle's 0.2 s skill3_1) would otherwise frame the
    // scenes 2-3x over-zoomed. No camera moves yet — one static frame.
    const ext = fxExtents(cues, names);
    const minFrame = (sched.cutins.length || fs.existsSync(s3File)) && hasFx
      ? { w: 1200, h: 700 } : null;
    const vpBox = await page.evaluate((names, ext, minFrame) => {
      let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
      for (const n of names) {
        const v = player.calculateAnimationViewport(n);
        if (!isFinite(v.x) || !isFinite(v.y) || v.width <= 0 || v.height <= 0) continue;
        minX = Math.min(minX, v.x); maxX = Math.max(maxX, v.x + v.width);
        minY = Math.min(minY, v.y); maxY = Math.max(maxY, v.y + v.height);
      }
      // the character's own envelope before FX widening — readability anchor
      const cMinY = minY, cMaxY = maxY, charH = maxY - minY;
      if (ext) {   // FX spawn points are absolute world coords (char origin ~0,
                   // phantom enemy at +600); union them in directly.
        minX = Math.min(minX, ext.minX); maxX = Math.max(maxX, ext.maxX);
        minY = Math.min(minY, ext.minY); maxY = Math.max(maxY, ext.maxY);
      }
      if (minFrame) {
        const padW = Math.max(0, minFrame.w - (maxX - minX)) / 2;
        const padH = Math.max(0, minFrame.h - (maxY - minY)) / 2;
        minX -= padW; maxX += padW; minY -= padH; maxY += padH;
      }
      // Char-readability height clamp: vertical stretch (high jump arcs,
      // sky-anchored FX cues) shrinks the character to a sliver in the
      // static frame — in-game the camera pans/zooms instead. Cap the
      // window at 2x the char's own envelope, positioned to keep the char
      // box fully framed, sliding within the union so we trim the far edge
      // (sky) before anything near the character.
      if (isFinite(charH) && charH > 0) {
        const capH = Math.max(charH * 2, minFrame ? minFrame.h : 0);
        if (maxY - minY > capH) {
          let y0 = cMinY - (capH - charH) / 2;
          y0 = Math.max(minY, Math.min(y0, maxY - capH));
          minY = y0; maxY = y0 + capH;
        }
      }
      player.currentViewport = { x: minX, y: minY, width: maxX - minX, height: maxY - minY,
                                 padLeft: 80, padRight: 80, padTop: 40, padBottom: 80 };
      player.previousViewport = null;
      return { w: Math.round(maxX - minX), h: Math.round(maxY - minY),
               charH: Math.round(charH) };
    }, names, ext, minFrame);
    say(`  [vp] world ${vpBox.w}x${vpBox.h} (char h=${vpBox.charH})`);

    // Schedule runner — drives segments at their stagept times (segment
    // switches via setAnimation give the engine HOLDS for free: a completed
    // non-loop track holds its last frame until the next switch) and records
    // cut-in SPLICE POINTS (frame index where the webp frames get inserted
    // in node; the field pauses under a cut-in in-game, and a zero-wall-time
    // splice reproduces exactly that). Used twice: dry run (warm-up: FX rig
    // fetch+parse caches) and capture.
    const runSchedule = async (sched, fps, maxH, dry, fxSettle) => {
      const canvas = stage.querySelector("canvas");
      const scale = Math.min(1, maxH / canvas.height);
      const w = Math.max(2, 2 * Math.round(canvas.width * scale / 2));
      const h = Math.max(2, 2 * Math.round(canvas.height * scale / 2));
      const off = document.createElement("canvas"); off.width = w; off.height = h;
      const ctx = off.getContext("2d");
      const frameMs = 1000 / fps;
      const stamps = [], raws = [], splices = [], cines = [];
      // stagept MOVE choreography: the CASTER node travels (ravi dashes
      // x=900 into the smoke at skill3_2 start, returns home for the catch).
      // Walked at composite time as a piecewise tween over world-x.
      const moves = sched.moves || [];
      const charDx = (tMs) => {
        let pos = 0;
        for (const m of moves) {
          if (tMs < m.t) break;
          if (!m.dur || tMs >= m.t + m.dur) { pos = m.x; continue; }
          let k = (tMs - m.t) / m.dur;
          k = k * k * (3 - 2 * k);   // smoothstep ≈ the authored ease curve
          pos = pos + (m.x - pos) * k;
        }
        return pos;
      };
      // ---- authored director track ------------------------------------
      // camera: CAM/ZOOM events fold sequentially (each tweens from the
      // value the previous ones left, exactly like charDx) with the
      // authored cubic-bezier ease; SHAKE events add a cm-rig camera path
      // (inlined translate keys, linear-sampled at (t-ev.t)*timeScale,
      // scaled by powerX/Y). Result pushed to the engine every frame via
      // fxEngine._setCam — the cine tick frames from it instead of the
      // content-follow heuristic. dark: fullscreen fades composited in
      // capture() (gz<=0 between char and scenes, gz>0 on top).
      const camEvs = (sched.camera || []).filter(e => e.kind !== "shake" && e.kind !== "node");
      const shakeEvs = (sched.camera || []).filter(e => e.kind === "shake");
      const nodeEvs = (sched.camera || []).filter(e => e.kind === "node");
      const bezY = (cv) => {
        if (!cv || cv.length !== 4) return k => k;
        const [x1, y1, x2, y2] = cv;
        return (u) => {              // solve x(t)=u by bisection, return y(t)
          let lo = 0, hi = 1, t = u;
          for (let i = 0; i < 22; i++) {
            const mt = 1 - t;
            const x = 3 * mt * mt * t * x1 + 3 * mt * t * t * x2 + t * t * t;
            if (x < u) lo = t; else hi = t;
            t = (lo + hi) / 2;
          }
          const mt = 1 - t;
          return 3 * mt * mt * t * y1 + 3 * mt * t * t * y2 + t * t * t;
        };
      };
      for (const ev of camEvs) ev._e = bezY(ev.curve);
      for (const ev of shakeEvs) {
        ev._kx = (ev.keys || []).filter(k => k.x !== undefined);
        ev._ky = (ev.keys || []).filter(k => k.y !== undefined);
      }
      for (const ev of nodeEvs) {
        ev._kx = (ev.tkeys || []).filter(k => k.x !== undefined);
        ev._ky = (ev.tkeys || []).filter(k => k.y !== undefined);
        ev._ks = (ev.skeys || []).filter(k => k.s !== undefined);
      }
      const sampleK = (ks, key, tt) => {
        if (!ks.length) return 0;
        if (tt <= ks[0].t) return ks[0][key];
        for (let i = 1; i < ks.length; i++) {
          if (tt <= ks[i].t) {
            const a = ks[i - 1], b = ks[i];
            return a[key] + (b[key] - a[key]) * ((tt - a.t) / (b.t - a.t || 1));
          }
        }
        return ks[ks.length - 1][key];
      };
      const camAt = (tMs) => {
        let x = 0, y = 0, zoom = 1;
        for (const ev of camEvs) {           // t-sorted by the compiler
          if (tMs < ev.t) break;
          const k = (!ev.dur || tMs >= ev.t + ev.dur)
            ? 1 : ev._e((tMs - ev.t) / ev.dur);
          if (ev.kind === "zoom") zoom += (ev.scale - zoom) * k;
          else { x += ((ev.x || 0) - x) * k; y += ((ev.y || 0) - y) * k; }
        }
        for (const ev of shakeEvs) {
          const local = (tMs - ev.t) * (ev.timeScale || 1);
          if (local < 0 || (ev.dur && local > ev.dur)) continue;
          x += sampleK(ev._kx, "x", local) * ((ev.power && ev.power[0]) || 1);
          y += sampleK(ev._ky, "y", local) * ((ev.power && ev.power[1]) || 1);
        }
        // NODE_ANI screen transform (screen' = S·p + T in design px):
        // camera equivalent = zoom ×S, centre at −T/S (doris's cutaway
        // punch-ins: 2.55x face closeup → 8.1x flash → 5.09x → 0.845x)
        for (const ev of nodeEvs) {
          const local = tMs - ev.t;
          if (local < 0 || local > ev.dur) continue;
          const S = sampleK(ev._ks, "s", local) || 1;
          zoom *= S;
          x += -sampleK(ev._kx, "x", local) / S;
          y += -sampleK(ev._ky, "y", local) / S;
        }
        return { x, y, zoom };
      };
      const hasCamTrack = camEvs.length > 0 || shakeEvs.length > 0 || nodeEvs.length > 0;
      // DARK fade model (from the observed payload shapes): ramp up over
      // fadeIn, hold for dur (dur<=0 → no timed hold), decay over fadeOut.
      // dur<=0 with NO fadeOut = authored hold (estelle's name-card
      // curtain) — released at fieldback, when the stage dressing resets.
      const darkAlpha = (ev, tMs) => {
        const lt = tMs - ev.t;
        if (lt < 0) return 0;
        const fi = ev.fadeIn || 0, fo = ev.fadeOut || 0;
        let a = (fi && lt < fi) ? lt / fi : 1;
        const hold = ev.dur > 0 ? ev.dur : 0;
        const after = lt - fi - hold;
        if (after > 0) {
          if (fo) a = Math.min(a, Math.max(0, 1 - after / fo));
          else if (ev.dur > 0) a = 0;              // timed, no fade: hard off
          else if (sched.fieldback != null && tMs >= sched.fieldback) a = 0;
        }
        return a * (ev.opacity != null ? ev.opacity : 1)
                 * (ev.color && ev.color[3] != null ? ev.color[3] / 255 : 1);
      };
      const darksMid = (sched.dark || []).filter(d => !(d.gz > 0));
      const darksTop = (sched.dark || []).filter(d => d.gz > 0);
      const drawDarks = (list, tMs) => {
        for (const ev of list) {
          const a = darkAlpha(ev, tMs);
          if (a <= 0.004) continue;
          const c = ev.color || [0, 0, 0, 255];
          ctx.save();
          ctx.setTransform(1, 0, 0, 1, 0, 0);   // full frame even mid-reframe
          ctx.globalAlpha = Math.min(1, a);
          ctx.fillStyle = `rgb(${c[0]},${c[1]},${c[2]})`;
          ctx.fillRect(0, 0, w, h);
          ctx.restore();
        }
      };
      let floorRef = null, floorN = 0;   // ref floor anchor + reframe ramp counter
      // feet of the live character (figure centre-x, lowest opaque row) in the
      // composite (w x h) frame — the pivot to scale her about when she rides
      // the floor. Scans a downscaled copy of her canvas once (at the ref).
      const _feetCv = document.createElement("canvas");
      _feetCv.width = 160; _feetCv.height = Math.max(1, Math.round(160 * h / w));
      const _feetCtx = _feetCv.getContext("2d", { willReadFrequently: true });
      const charFeet = (cv, dx, W, H) => {
        const pw = _feetCv.width, ph = _feetCv.height;
        _feetCtx.clearRect(0, 0, pw, ph);
        _feetCtx.drawImage(cv, 0, 0, pw, ph);
        const d = _feetCtx.getImageData(0, 0, pw, ph).data;
        let minX = pw, maxX = -1, maxY = -1, sumX = 0, nLow = 0;
        for (let py = ph - 1; py >= 0; py--) {
          let rowHit = false;
          for (let px = 0; px < pw; px++) {
            if (d[(py * pw + px) * 4 + 3] > 24) {
              rowHit = true; minX = Math.min(minX, px); maxX = Math.max(maxX, px);
              if (maxY < 0) maxY = py;           // first (lowest) opaque row
              if (py >= maxY - 2) { sumX += px; nLow++; }   // centre-x near feet
            }
          }
          if (maxY >= 0 && py < maxY - 4) break;  // sampled the bottom band; stop
        }
        if (maxY < 0) return [dx + W / 2, H * 0.6];   // empty → fallback
        const fxp = dx + (nLow ? sumX / nLow : (minX + maxX) / 2) / pw * W;
        const fyp = (maxY + 1) / ph * H;
        return [fxp, fyp];
      };
      // reframe-up: a floor cutaway's ground mesh has a flat base-fill dead-
      // zone below the painted hill that the camera-less window dips into as a
      // bottom seam. Once the live char is planted on the floor (below), crop
      // that band off by scaling the WHOLE composite (scene + char together, so
      // they stay registered) about the TOP edge — top fixed, bottom REFRAME_B
      // mapped past the frame edge. Ramped in over the scene start so it
      // doesn't pop. Only while a floor is up; identity otherwise.
      const REFRAME_B = 0.13, REFRAME_RAMP = 6;
      const capture = (tMs) => {
        const fa = (typeof fxEngine !== "undefined" && fxEngine && fxEngine._floorAnchor)
          ? fxEngine._floorAnchor() : null;
        const floorUp = !!(fa && fa.ns > 0);
        ctx.setTransform(1, 0, 0, 1, 0, 0);
        ctx.clearRect(0, 0, w, h);
        if (floorUp) {
          floorN = (floorN || 0) + 1;
          const b = REFRAME_B * Math.min(1, floorN / REFRAME_RAMP);
          const Z = 1 / (1 - b);
          ctx.setTransform(Z, 0, 0, Z, (w / 2) * (1 - Z), 0);  // pivot (w/2, 0)
        } else { floorN = 0; }
        const fx = fxExportLayers();
        // cutaway underlay: authored cameras can out-zoom the staged scene
        // art (estelle's finale pull-back leaves bare corners the game fills
        // with bloom/haze channels we don't render) — back the frame with a
        // cover-scaled blurred copy of the scene so voids never read black
        if (fx.cine && (fx.back.length || fx.front.length)) {
          ctx.save();
          ctx.filter = "blur(18px) brightness(0.92)";
          for (const s of fx.back.concat(fx.front))
            ctx.drawImage(s.canvas, s.sx + s.sw * 0.2, s.sy + s.sh * 0.2,
                          s.sw * 0.6, s.sh * 0.6,
                          -w * 0.3, -h * 0.3, w * 1.6, h * 1.6);
          ctx.restore();
        }
        for (const s of fx.back) ctx.drawImage(s.canvas, s.sx, s.sy, s.sw, s.sh, 0, 0, w, h);
        // cinematic cutaways that paint their OWN character replace the field
        // view in-game — skip the live char only then (hideChar). A cutaway
        // with no painted character (doris's tree) keeps the live rig, z-
        // ordered between the back and front FX so she stands in the scene.
        if (!fx.hideChar) {
          let dx = 0;
          if (moves.length) {
            const vp = player.currentViewport;
            const effW = vp.width + (vp.padLeft || 0) + (vp.padRight || 0);
            dx = charDx(tMs || 0) * (w / effW);
          }
          // RIDE the scene floor's zoom: a field-replacing cutaway whose
          // ground (the `bottom` mesh) carries its own zoom animation makes a
          // statically-drawn character float at a fixed size while the floor
          // scales under her (the doris tree scene). Scale her with the floor
          // about her own FEET (so she stays planted, like the VOD, rather
          // than sliding — the ground's world anchor points swing too wildly
          // to translate by). Ratio = the floor's RENDERED-extent ratio vs the
          // first cutaway frame (getBounds, not the 14..47x mesh-fill bone
          // scale that balloons her). No floor up (estelle, field FX) → fa
          // null → unchanged full-canvas draw.
          if (floorUp) {
            if (!floorRef) { floorRef = fa; floorRef.feet = charFeet(canvas, dx, w, h); }
            const [fxp, fyp] = floorRef.feet;
            // RIDE the floor: its real motion is a smooth vertical rise+recede
            // (the `bottom` bone's screen-Y glides while the getBounds WIDTH
            // saturates — so width gives no motion, position does). She tracks
            // the floor's screen-Y delta (damped — she sits higher on the
            // tilted plane than the foreground anchor, so she travels less) and
            // shrinks as it recedes, scaling about her own feet. Damped+clamped
            // so the wild early frames can't fling her off; ramped so it eases
            // in without a pop.
            const r = Math.min(1, floorN / REFRAME_RAMP);
            const dY = fa._bboneNy - floorRef._bboneNy;   // < 0 as the floor rises
            // she sits high on the tilted plane (the hilltop is near-stable in
            // our window) so she only DRIFTS subtly; the visible "ride" is the
            // recede SHRINK. Big translate detaches her into the sky.
            const ty = Math.max(-0.07, Math.min(0.07, dY * 0.12)) * h * r;
            const S = Math.max(0.6, Math.min(1.25, 1 + dY * 0.4 * r));
            ctx.save();
            ctx.translate(fxp, fyp + ty);
            ctx.scale(S, S);
            ctx.translate(-fxp, -fyp);
            ctx.drawImage(canvas, dx, 0, w, h);
            ctx.restore();
          } else {
            floorRef = null;   // out of a floor scene — re-anchor on the next
            ctx.drawImage(canvas, dx, 0, w, h);
          }
        }
        // authored DARK overlays under the scene layers (gz<=0: estelle's
        // name-card curtain darkens the FIELD during the cast beat). Only
        // while the field view is up — a full cutaway REPLACES the
        // curtained field, and rendering the curtain under the scenes
        // blacks out every pixel the scene art doesn't cover (it ate the
        // finale's underlay/corners).
        if (!fx.hideChar) drawDarks(darksMid, tMs || 0);
        for (const s of fx.front) ctx.drawImage(s.canvas, s.sx, s.sy, s.sw, s.sh, 0, 0, w, h);
        // cheap bloom on scene beats: the game's PPEFFECT sprite_blur
        // spreads every highlight (the finale flash washes the frame in
        // the VOD; unbloomed it reads as thin white streaks). Additive
        // blurred self-composite — dark stays dark, highlights spread.
        if (fx.cine) {
          if (!capture._bloomCv) {
            capture._bloomCv = document.createElement("canvas");
            capture._bloomCv.width = w; capture._bloomCv.height = h;
            capture._bloomCtx = capture._bloomCv.getContext("2d");
          }
          capture._bloomCtx.clearRect(0, 0, w, h);
          capture._bloomCtx.drawImage(off, 0, 0);
          ctx.save();
          ctx.setTransform(1, 0, 0, 1, 0, 0);
          ctx.globalCompositeOperation = "lighter";
          ctx.globalAlpha = 0.35;
          ctx.filter = "blur(14px)";
          ctx.drawImage(capture._bloomCv, 0, 0);
          ctx.restore();
        }
        // ...and above everything (gz>0: the finale whiteout flash)
        drawDarks(darksTop, tMs || 0);
        ctx.setTransform(1, 0, 0, 1, 0, 0);
        raws.push(ctx.getImageData(0, 0, w, h));
        cines.push(!!fx.cine);
      };
      const as = player.animationState;
      // The dry pass only exists to warm FX rig fetch/parse caches — run it
      // at 3x. Cues still fire (the schedule clock is track time), so every
      // rig of every segment still gets requested. The capture pass resets
      // to 1 explicitly (timeScale persists on the AnimationState).
      as.timeScale = dry ? 3 : 1;
      // wipe FX state left by the previous pass (held cinematic layers,
      // carried spawns) so frame 0 of THIS pass starts clean
      if (typeof fxEngine !== "undefined" && fxEngine && fxEngine._reset) fxEngine._reset();
      if (typeof fxEngine !== "undefined" && fxEngine && fxEngine._setCam)
        fxEngine._setCam(hasCamTrack ? camAt(0) : null);
      as.clearTracks();
      player.skeleton.setToSetupPose();
      as.setAnimation(0, sched.segments[0].anim, false);
      player.play();
      player.pause();
      await new Promise(r => requestAnimationFrame(r));
      // Prime the capture pipeline while paused: the first composite +
      // getImageData allocate lazily (~0.3s) — unprimed, the opening motion
      // lands inside one long first frame. TimeKeeper clamps the resume
      // delta, so pause/play is safe here.
      if (!dry) { capture(0); raws.length = 0; cines.length = 0; }
      // The FX engine's tick saw the first animation while paused and already
      // kicked off its player pool — let the rigs finish parsing so t=0 cues
      // fire on time instead of via the pending queue.
      if (fxSettle) await new Promise(r => setTimeout(r, fxSettle));
      const tr0 = as.getCurrent(0);
      if (tr0) tr0.trackTime = 0;
      let segIdx = 1, cutIdx = 0, segBase = 0, fbDone = false, cawDone = false;
      player.play();
      await new Promise(r => requestAnimationFrame(r));
      let lastCap = -Infinity;
      // A cutaway skill's clip IS the cinematic: it ends when the field
      // returns (fieldback). The authored skill `end` can run seconds longer
      // (doris's tree cutaway ends at 3.68s but `end` is 6.18s) — that tail is
      // the hero's on-field recovery, but with no battle arena to return to it
      // reads as her lingering after the scene already left (the user's "she
      // still shows after the background left"). In-game the engine cuts
      // straight back to battle at this beat, so stop here. Estelle already
      // satisfies fieldback>=end (no tail); this generalises the same shape to
      // cutaways whose skill anim outlasts the cinematic.
      const clipEnd = (sched.cutaway && sched.fieldback != null
                       && sched.fieldback < sched.end) ? sched.fieldback : sched.end;
      // Cutaway skills end AT the authored boundary — no tail margin. The
      // 250ms pad let post-fieldback field FX leak into the clip (estelle:
      // hit_new_blunt_01's fullscreen flash quads at 6.43s land in the pad
      // and render as a rainbow wash against the arena-less void — the
      // garbage last frames in every prior bake). Non-cutaway skills keep
      // the original 250ms tail.
      const endPad = (clipEnd < sched.end || sched.cutaway) ? 0 : 250;
      // The schedule clock is the CHARACTER'S TRACK TIME, never the wall
      // clock: spine-player's TimeKeeper clamps each frame delta to 64ms,
      // so whenever the page slows down (player creation, 15+ live WebGL
      // canvases, GC) the spine world falls behind real time. A wall-clock
      // schedule then switches segments / stamps frames ahead of the
      // animation — estelle's whole cutaway chain landed seconds late and
      // deduped to a frozen clip. Track-driven, a slow bake just takes
      // longer; the OUTPUT timeline is exact.
      await new Promise(resolve => {
        const loop = () => {
          const tr = as.getCurrent(0);
          const spineT = segBase + (tr ? tr.trackTime * 1000 : 0);
          if (spineT >= clipEnd + endPad) return resolve();
          while (segIdx < sched.segments.length && spineT >= sched.segments[segIdx].t) {
            segBase = sched.segments[segIdx].t;
            as.setAnimation(0, sched.segments[segIdx].anim, false);
            segIdx++;
          }
          while (cutIdx < sched.cutins.length && spineT >= sched.cutins[cutIdx].t) {
            splices.push({ at: raws.length, cut: cutIdx });
            cutIdx++;
          }
          // stagept BGSHOW-hide — the authored START of the cutaway: until
          // this beat the skill plays as field framing (doris's overlays)
          if (!cawDone && sched.cutawayT != null && spineT >= sched.cutawayT) {
            cawDone = true;
            if (typeof fxEngine !== "undefined" && fxEngine && fxEngine._cutawayOn)
              fxEngine._cutawayOn();
          }
          // stagept LAYOUT mode:1 — the authored end of the cutaway: kill
          // scene holds so the character plays the skill's tail on-field
          if (!fbDone && sched.fieldback != null && spineT >= sched.fieldback) {
            fbDone = true;
            if (typeof fxEngine !== "undefined" && fxEngine && fxEngine._fieldBack)
              fxEngine._fieldBack();
          }
          // authored camera replay: feed the current CAM/ZOOM/SHAKE state to
          // the engine every animation frame (the cine tick frames from it)
          if (hasCamTrack && typeof fxEngine !== "undefined" && fxEngine && fxEngine._setCam)
            fxEngine._setCam(camAt(spineT));
          if (!dry && spineT - lastCap >= frameMs - 1) {
            capture(spineT); stamps.push(spineT); lastCap = spineT;
            if (window.__bakeDebug && typeof fxEngine !== "undefined" && fxEngine && fxEngine._debug) {
              const d = fxEngine._debug();
              (window.__dbgRows = window.__dbgRows || []).push(
                `${Math.round(spineT)} trk=${(as.getCurrent(0) || {}).trackTime?.toFixed(2)} ` +
                `gt=${d.gt} idx=${d.idx} cine=${d.cineActive} ` +
                `vis=${d.vis.map(v => `${v.rig}${v.cine ? "*" : ""}[${v.key}]@${v.tt}` +
                  `${v.bnds ? ` b=${v.bnds.join("/")}` : ""}${v.cam ? ` c=${v.cam.join("/")}` : ""}`).join(" | ")}`);
            }
          }
          requestAnimationFrame(loop);
        };
        requestAnimationFrame(loop);
      });
      if (dry) return { dry: true };
      if (!raws.length) return { error: "no frames captured" };
      // Per-frame display durations from the real capture timestamps.
      const delays = stamps.map((t, i) =>
        Math.max(10, Math.round((i + 1 < stamps.length ? stamps[i + 1] : t + frameMs) - t)));
      // PNG-encode each frame (lossless intermediate, ~10-30x smaller than raw
      // RGBA over the CDP wire); stash for chunked pull from node.
      window.__bakePngs = [];
      const tmp = document.createElement("canvas"); tmp.width = w; tmp.height = h;
      const tctx = tmp.getContext("2d");
      for (const img of raws) {
        tctx.putImageData(img, 0, 0);
        const blob = await new Promise(r => tmp.toBlob(r, "image/png"));
        const buf = await blob.arrayBuffer();
        let bin = "";
        const u8 = new Uint8Array(buf);
        for (let i = 0; i < u8.length; i += 0x8000)
          bin += String.fromCharCode.apply(null, u8.subarray(i, i + 0x8000));
        window.__bakePngs.push(btoa(bin));
      }
      return { w, h, n: raws.length, delays, splices, cines };
    };

    // Warm-up: play the schedule once un-captured so every FX rig of every
    // segment is fetched + parsed (the per-anim player pool tears down and
    // recreates on segment switch; warm caches make capture-pass spawns land
    // on time instead of leaning on the pending-queue compensation).
    if (hasFx) await page.evaluate(runSchedule, sched, opts.fps, 64, true, 0);

    // Capture pass: viewer-export composite (fxExportLayers back → char →
    // front) sampled at the requested fps with REAL timestamps.
    if (process.env.BAKE_DEBUG) await page.evaluate(() => { window.__bakeDebug = 1; });
    const meta = await page.evaluate(runSchedule, sched, opts.fps, opts.maxh,
                                     false, hasFx ? 700 : 0);
    if (meta.error) throw new Error(meta.error);
    if (process.env.BAKE_DEBUG) {
      const rows = await page.evaluate(() => window.__dbgRows || []);
      for (const r of rows) console.log("  [dbg]", r);
    }

    // Pull frames in batches — one evaluate round-trip per frame was ~200
    // round-trips per unit. 12 PNGs ≈ 20-30 MB of base64 per call, well
    // under the CDP message ceiling.
    let frames = [];
    const BATCH = 12;
    for (let i = 0; i < meta.n; i += BATCH) {
      const batch = await page.evaluate((s, e) => window.__bakePngs.slice(s, e),
                                        i, Math.min(i + BATCH, meta.n));
      for (const b64 of batch) frames.push(Buffer.from(b64, "base64"));
    }
    await page.evaluate(() => { window.__bakePngs = null; });

    // Cut-in curtain gap: on cutaway skills, frames right after a splice
    // point that still composite the combat model (the next scene hasn't
    // lit yet) are covered by the cut-in's black curtain in-game — drop
    // them and hold the cut-in's last frame for that time instead
    // (estelle's 1-frame model flash between her cut-in and the beam).
    let delays = meta.delays;
    const sortedSp = (meta.splices || []).sort((a, b) => a.at - b.at);
    if (cues && cues.cutaway && sortedSp.length && meta.cines) {
      const cines = meta.cines;
      for (let s = 0; s < sortedSp.length; s++) {
        const a = sortedSp[s].at;
        let j = a, gap = 0;
        while (j < frames.length && !cines[j] && gap <= 900) { gap += delays[j]; j++; }
        if (j > a && j < frames.length && cines[j] && gap <= 900) {
          frames.splice(a, j - a);
          delays.splice(a, j - a);
          cines.splice(a, j - a);
          sortedSp[s].curtainMs = gap;
          for (let t = s + 1; t < sortedSp.length; t++) sortedSp[t].at -= (j - a);
        }
      }
    }

    // Cut-in splice: insert the game's hand-drawn webp frames at the recorded
    // splice indices with their OWN per-frame delays — the spine timeline
    // pauses underneath, exactly like the in-game field does during a cut-in.
    // COVER-fit, not contain: the assets are full-bleed strips wider than the
    // screen (estelle's is 1580x720, AR 2.19) and the game recrops them to
    // fill — contain-fit letterboxed every cut-in frame (user f019-23 notes).
    let nCut = 0;
    if (sortedSp.length) {
      let inserted = 0;
      for (const sp of sortedSp) {
        const src = sched.cutins[sp.cut] && sched.cutins[sp.cut].src;
        const file = src && path.join(CUT_DIR, src);
        if (!file || !fs.existsSync(file)) continue;
        const m = await sharp(file, { animated: true }).metadata();
        const cutFrames = [], cutDelays = m.delay || [];
        for (let i = 0; i < (m.pages || 1); i++) {
          cutFrames.push(await sharp(file, { page: i })
            .resize(meta.w, meta.h, { fit: "cover" })
            .png().toBuffer());
        }
        const at = sp.at + inserted;
        const insDelays = cutFrames.map((_, i) => Math.max(10, cutDelays[i] || 40));
        // dropped curtain-gap time holds on the cut-in's final frame
        if (sp.curtainMs) insDelays[insDelays.length - 1] += sp.curtainMs;
        frames = [...frames.slice(0, at), ...cutFrames, ...frames.slice(at)];
        delays = [...delays.slice(0, at), ...insDelays, ...delays.slice(at)];
        inserted += cutFrames.length;
        nCut++;
      }
    }

    // Adaptive ladder: FX-heavy chains (c1009's full-screen vortex runs for
    // seconds) blow way past the size target at q85 — animated WebP has no
    // motion compensation, so the only levers are quality then resolution.
    // The last ladder step is kept regardless.
    const ladder = [{ q: opts.q, scale: 1 },
                    ...[{ q: 70, scale: 1 }, { q: 55, scale: 1 }].filter(s => s.q < opts.q),
                    { q: 60, scale: 0.75 },
                    // particle-heavy clips (ravi's smoke fills the frame for
                    // seconds) still overshoot at 540p/q60 — keep stepping
                    { q: 45, scale: 0.75 }, { q: 40, scale: 0.6 }];
    // Each step is a FULL re-encode (libwebp, the bake's dominant cost) —
    // don't walk the ladder; jump to the first step whose ESTIMATED size
    // fits. Relative size ≈ (q/85)^1.8 · scale² (fitted on run-2 outputs;
    // estimate-only, the actual encode still decides — a miss just costs
    // one extra step, same as the old walk). Last step kept regardless.
    const weight = s => Math.pow(s.q / 85, 1.8) * s.scale * s.scale;
    let used, kb = 0, outW = meta.w, outH = meta.h, idx = 0;
    while (true) {
      const step = ladder[idx];
      used = step;
      let fr = frames;
      if (step.scale < 1) {
        outW = 2 * Math.round(meta.w * step.scale / 2);
        outH = 2 * Math.round(meta.h * step.scale / 2);
        fr = await Promise.all(frames.map(b => sharp(b).resize(outW, outH).png().toBuffer()));
      } else { outW = meta.w; outH = meta.h; }
      await sharp(fr, { join: { animated: true } })
        .webp({ quality: step.q, effort: opts.effort, loop: 0, delay: delays })
        .toFile(outFile);
      kb = Math.round(fs.statSync(outFile).size / 1024);
      if (kb <= opts.maxkb || idx === ladder.length - 1) break;
      let j = idx + 1;
      while (j < ladder.length - 1 &&
             kb * weight(ladder[j]) / weight(ladder[idx]) > opts.maxkb) j++;
      idx = j;
    }
    return { chain: names, dur: totalDur, frames: frames.length, cutins: nCut,
             w: outW, h: outH, kb, q: used.q, fx: hasFx,
             sched: fs.existsSync(s3File) };
  } finally {
    await page.close();
  }
}

(async () => {
  const args = process.argv.slice(2);
  const flag = (name, dflt) => {
    const i = args.indexOf("--" + name);
    return i >= 0 ? parseInt(args[i + 1], 10) : dflt;
  };
  const opts = { maxh: flag("maxh", 900), fps: flag("fps", 24),
                 q: flag("q", 85), effort: flag("effort", 4),
                 maxkb: flag("maxkb", 16384),
                 nosharedgl: args.includes("--nosharedgl") };
  const jobs  = Math.max(1, flag("jobs", 3));
  const force = args.includes("--force");
  const all   = args.includes("--all");
  const onlySlugs = args.filter((a, i) => !a.startsWith("--") &&
    !["maxh","fps","q","effort","maxkb","jobs"].includes((args[i-1] || "").replace(/^--/, "")));
  let slugs = all ? listCombatSlugs() : onlySlugs;
  if (!slugs.length) { console.log("usage: node render/skill3.js <slugs...> | --all [--force]"); process.exit(0); }
  if (!force) slugs = slugs.filter(s =>
    !fs.existsSync(path.join(SITE, "assets", s, "combat", "sk3_full.webp")));
  if (!slugs.length) { console.log("nothing to bake (all sk3_full.webp present; use --force)."); process.exit(0); }

  const server = makeServer();
  await new Promise(r => server.listen(PORT, r));

  // Worker pool: each worker owns a browser INSTANCE (own GPU process, own
  // WebGL context budget) and pulls slugs off a shared queue. Per-unit log
  // lines are buffered and printed atomically so workers don't interleave.
  // One automatic retry per unit covers the transient protocol timeouts /
  // file-write races seen on long runs.
  let ok = 0, fail = 0, skip = 0;
  const t0 = Date.now();
  const queue = slugs.slice();
  const worker = async () => {
    // protocolTimeout: a schedule pass is one long page.evaluate; when the
    // GPU is contended (other workers, screen recording, the game itself)
    // Chrome falls back to software rendering and the track-driven pass
    // legitimately takes minutes.
    const browser = await puppeteer.launch({ headless: "new", args: GPU_ARGS,
                                             protocolTimeout: 900000 });
    try {
      while (queue.length) {
        const slug = queue.shift();
        const lines = [];
        const say = s => lines.push(s);
        const tU = Date.now();
        let r = null, err = null;
        for (let attempt = 0; attempt < 2 && !r; attempt++) {
          try { err = null; r = await bakeOne(browser, slug, opts, say); }
          catch (e) { err = e; if (!attempt) say(`  [retry] ${slug}: ${e.message}`); }
        }
        const tookMin = ((Date.now() - tU) / 60000).toFixed(1);
        if (err) { fail++; say(`[fail] ${slug}: ${err.message}`); }
        else if (r.skip) { skip++; say(`[skip] ${slug}: ${r.skip}`); }
        else {
          ok++;
          say(`[ok]   ${slug}  ${r.chain.join("+")}  ${r.dur.toFixed(2)}s` +
              `  ${r.frames}f ${r.w}x${r.h}  ${r.kb} KB q${r.q}` +
              `${r.sched ? "" : "  (no stg)"}${r.cutins ? `  cutins=${r.cutins}` : ""}` +
              `${r.fx ? "" : "  (no fx)"}  [${tookMin}m]`);
        }
        console.log(lines.join("\n"));
      }
    } finally {
      await browser.close();
    }
  };
  await Promise.all(Array.from({ length: Math.min(jobs, slugs.length) }, worker));

  console.log(`\n[summary] ${ok} ok · ${skip} skipped · ${fail} failed · ` +
              `${((Date.now() - t0) / 1000 / 60).toFixed(1)} min`);
  server.close();
  process.exit(fail ? 1 : 0);
})();
