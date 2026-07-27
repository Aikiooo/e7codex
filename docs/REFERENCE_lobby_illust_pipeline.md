# REFERENCE — Lobby / event illust + intimacy WebM pipeline

**Status (2026-07-27):** Catalog + automatic pipeline live under
`tools/_illust_spike/`. Batch bake of the **active** (non-deferred) set is in
progress / may be running. Framing for lobby packs is **world0** (rank-1
`BASE_SCALE` ortho). Do not invent screenshot crop fractions (see
`docs/GUIDELINES_exact_data.md`, skill `e7-exact-data`).

Related:
- `docs/REFERENCE_intimacy_illustration.md` — historical intimacy notes (c2185 flowers, 4.2.43)
- `tools/_illust_spike/recipes.json` — machine-readable pack catalog
- `s3_exact/docs/layout_constants.json` — `BASE_SCALE`, `WORLD_W0/H0`
- Memory: `project-e7-intimacy-webm` (older hand recipes; prefer this doc + recipes.json)

---

## What this pipeline bakes

| Kind | Meaning | Bake tool | Framing |
|------|---------|-----------|---------|
| **intimacy** | Hero detail looping illust (`intimacy.webm`) | `bake.js` | Slot AABB (rank-2). Crop default `0,0,0,0` |
| **lobby** | Event / lobby multi-layer art (non-interactive BG) | `bake_lobby_hq.js` | **`world0`** = `DESIGN/BASE_SCALE` about origin (rank-1 EffectPlay) |

**Not in scope (yet):** voice-synced reactions, lang-specific lip layers as
separate videos (same picture + VO later), static `img_intimacy_illust_*.webp`.

---

## Tooling map (`tools/_illust_spike/`)

| File | Role |
|------|------|
| **`recipes.json`** | Pack catalog: cfx roots, anchors, out paths, deferred flags |
| **`pipeline_illust.py`** | Orchestrator: stage → alpha_key → bake / still / dry-run / discover |
| **`cfx_order.py`** | CFX plist → z-sorted spine layer order (rank-2) |
| **`stage_layers.py`** | scsp→json, atlas rewrite, sct→png, straight-alpha premultiply |
| **`alpha_key.py`** | Additive slots: alpha = luminance (black-box FX fix) |
| **`bake.js`** | Intimacy multi-worker PNG sequence → VP9 WebM |
| **`bake_lobby_hq.js`** | Lobby HQ + still PNG; anchors `bg` \| `skel` \| **`world0`** |
| **`encode_ffmpeg.js`** | Shared encode: default VP9 `cpu-used=2`; optional `E7_ENCODER=av1_amf` |
| **`tail.js` + `xfadeloop.py`** | Crossfade loop for mismatched ambient periods |
| **`finalize.py`** | Copy idle WebM → `site/assets/<slug>/intimacy.webm` |
| **`run_batch_bake.py`** | Sequential bake of non-deferred packs; log `batch_bake.log` |
| **`rec.html`** | Multi-layer spine-player host; `__world0_aabb`, `__aabb`, `__reframe` |

### Commands (never auto-bake on list/dry-run)

```powershell
cd tools/_illust_spike

python pipeline_illust.py list              # all packs
python pipeline_illust.py list active       # bake set (default)
python pipeline_illust.py list deferred     # intro one-shots (later)
python pipeline_illust.py list lobby
python pipeline_illust.py discover          # CFX scan vs recipes
python pipeline_illust.py dry-run           # plan only
python pipeline_illust.py dry-run vva5aa_lobby

# Stage + alpha-key + bake one pack or the whole active set:
python pipeline_illust.py full c2181
python run_batch_bake.py                    # all non-deferred (long)
python run_batch_bake.py --skip-stage       # if already staged/akey'd

# Encode env
$env:E7_VP9_CPU_USED = "2"     # default in encode_ffmpeg.js
$env:E7_ENCODER = "av1_amf"    # optional AMD GPU preview encode
$env:E7_LEGACY_CROP = "1"      # only if you must match old screenshot crops
```

Logs: `batch_bake.log`, `batch_bake_console.log`, `stage_all.log`.

---

## Framing (lobby) — world0 × CFX scale

Non-interactive lobby / event backgrounds use engine defaults, **not** mesh-fit
or ShareX-tuned crops:

| Symbol | Value | Rank |
|--------|-------|------|
| `DESIGN_W/H` | 1920 × 1080 | 1 |
| `MODEL_DESIGN_HEIGHT` | 640 | 1 |
| `BASE_SCALE` | `(1080/640)*0.4` = **0.675** | 1 |
| `WORLD_W0/H0` | `DESIGN/BASE_SCALE` ≈ **2844.44 × 1600** | 1 |
| Center | Spine origin **(0, 0)** | 1 |
| **CFX `scale`** | per-primitive (often **2.24–2.25** on UI illust) | 2 |

**Letterbox root cause (fixed):** world0 alone is correct for packs with CFX
scale=1 (Aube, vsu4aa2, full-bleed beach shots). UI-panel packs
(`uieff_illust_vsu4aa1`, `vsu3aa*`, `vms03c`, intimacy CFX) author
`scale≈2.24` so the art panel fills the DESIGN viewport while FX overscan
renders outside. Bake must apply that scale to each skeleton under the fixed
world0 camera (`E7_LAYER_SCALES` → `rec.html` `skeleton.scaleX/Y`). Without it,
stills look like a small centered panel in a 3840×2160 dark frame.

Aube recipe notes + A/B log: `_scratch/lobby_aube/RECIPE.md`.  
User rejected skel-centered **D**; accepted **world0** (with scale when CFX says so).

Default bake: `outH=2160`, `res=1920x1080`, `crf=10–12`, `fps=30` → large WebMs
(~100 MB class for long HQ loops). See **Hosting** below.

### Idle / story animation (multi-layer sync)

Some stacks (e.g. `vms03c`) only ship `loop` / `off_loop` / `on` / `end`.
`rec.html` picks idle via preference: **`story_en` (if present)** → `animation`
→ `loop` → `off_loop` → `on` → first non-enter/touch.

#### Phase-lock (automatic on every bake)

All lobby/intimacy frame seeks go through `rec.html` `__seek` with a **shared
master clock** = max layer duration. Independent per-layer `t % layerDur` is
banned — that was Luluca (body float **8s** vs waves **6s**): waves restarted
mid-bob.

| Layer vs master | Policy | Example |
|-----------------|--------|---------|
| Same duration | `trackTime = mt` | uniform packs |
| ≥ 50% of master (`PHASE_NEAR_RATIO`) | **time-warp** into master period | waves 6s over float 8s |
| &lt; 50% of master | **short-loop** under shared clock (`mt % dur`) | stars/particles on long story |

Bake logs:

```
clips: …_back=animation@6.00s  …=animation@8.00s
phase-lock: master=8.00s near≥0.5 (auto-sync active)  …_back:near-stretch@6.00s  …:master@8.00s
```

Static audit (no bake):

```powershell
python pipeline_illust.py audit-sync          # all active staged packs
python pipeline_illust.py audit-sync vsu3aa1
```

#### Story stacks still need a shared clip name

Tears on companion FX are keyed to `story_en` / `story_ja`. If char layers play
short idle `animation` while FX play `story_*`, attachments leave the face even
with phase-lock (wrong clip, not just wrong period). Recipe field:

```json
"anim": "story_en"
```

→ `E7_LAYER_ANIM` → `rec.html?anim=…`. Prefer this when every (or most) layer
ships the same story clip. Do not hardcode `animation` in SpinePlayer.

---

## Layer order = CFX `z` (rank 2)

Merge all `cfx` roots in the recipe; sort primitives by `z` ascending (back→front).
Missing `z` → 0. Exclude only documented washout layers (c2185
`…backup2_big2` / `…small`).

Do **not** re-hand-order from memory unless CFX is wrong and RE says so.

### Known unit / event mapping (don’t re-confuse)

| Event codename | Title (updates.json) | Featured | Lobby pack id(s) |
|----------------|----------------------|----------|------------------|
| **vva5aa** | Sweet Chocolate Scandal! | **Tori `c1171`** | `vva5aa_lobby` |
| **vsu5aa** | Intense! Tropical Days!! | **Aram `c5175`** (+ Hwayoung beach, Peira) | `vsu5aa_1`, `vsu5aa_2_lobby` |
| **vsu6aa** | (Aube summer event) | **Aube `c5190`** | `vsu6aa_lobby` |

Aram is **not** Valentine `vva5aa`.

---

## Active catalog (bake set)

Default for `pipeline_illust.py bake` / `run_batch_bake.py` = packs with
`deferred` ≠ true.

### Intimacy (ship-to-site candidates)

| id | Unit | Anchor (slot) | Notes |
|----|------|---------------|-------|
| `c1153` | Harsetti | **`bg`** (not bg_02) | max_sec 21, fps 24, crf 20 |
| `c2066` | New Moon Luna | **`R_background4`** | max_sec 36, fps 24 |
| `c2181` | Notos → site **c2181_1** | `bg` | CFX order legs on top |
| `c2185` | R&L → site **c2185_1** | `bg_b1` | xfade 14s; exclude washout layers; optional post_crop 2380 |
| `c6005` | Lady of the Scales | `bg2` | xfade 21s; order bg,b,sphere,a,f |

### Lobby / event illust (world0)

| id | Label | primary / event |
|----|-------|-----------------|
| `vsu6aa_lobby` | Aube lobby BG | c5190 |
| `vva5aa_lobby` | Tori Valentine idle | c1171 / vva5aa |
| `vsu5aa_1`, `vsu5aa_2_lobby` | Summer 2025 | Aram event; **vsu5aa_2** = full `illeff_vsu5aa_2_story` (bg_+a/b+water+lens) |
| `vsu4aa1/2`, `vsu3aa1/2` | Summer 24/23 | |
| `vae2aa1` | Aespa multi-layer | (vae2aa2–5 single-layer optional later) |
| `vt41aa_1` | lang=en | |
| `vms03c_1` | | |
| `epma_04` | Episode main (Salome) | variants: **Idle** + **Story** (`epma_04_story`, deferred bake) |
| `imgsa_1_1` | 5th anniv group (9 layers) | |
| `vfr5aa_3` | Frieren event art | |
| `lobby_prequel_1/2` | Victorica prequel lobbies | |

Outputs: intimacy → `tools/_illust_spike/<id>_intimacy.webm`; lobby →
`_scratch/lobby_*` or `_scratch/lobby_events/` per recipe `out_dir`.

---

## Deferred — intro one-shots (later)

Listed in recipes with `"deferred": true`. **Not** in the default bake set.

| id | What |
|----|------|
| `c2185_intro` | R&L enter — **REJECTED 2026-07-27** (moon-face / wrong look). Do not bake. |
| `c6005_intro` | Lady of the Scales enter — **REJECTED 2026-07-27** (worse than prior spike; former webm overwritten). Do not bake. |
| `vva5aa_lobby_intro` | Tori lobby intro stack (bg_b, char, bg_f, eff) |
| `vva5aa_intro` | Tori illust intro only (`intro_b` / `intro_f`) |

**c2185 / c6005 intro stop:** see `docs/REFERENCE_intimacy_illustration.md` § Deferred
intimacy INTROS and `recipes.json` → `_meta.deferred_intimacy_intro`. Rejected
artifacts: `tools/_illust_spike/*_intro.rejected_2026-07-27.webm`.

```powershell
python pipeline_illust.py list deferred
# Do NOT: python pipeline_illust.py full deferred   # until camera/FX RE is done
```

### Lang swaps (very low priority)

Same video bytes for en/ja/ko/zhs character layers that only differ by lip/VO.
Bake once (we use `en`); attach audio later. Do **not** re-bake per language
unless the art itself differs.

### Catalog gaps (not exhaustive)

- `bgeff_wargod_island_bg_lobby` (12-layer lobby BG) — not in recipes yet
- Aespa `vae2aa2`–`5` single-layer (+ shadow companions)
- FX-only / UI lobbypack ornaments
- Static intimacy webps

Re-scan: `python pipeline_illust.py discover`.

---

## World0 recipe (Aube) — verified path

```powershell
# Prefer pipeline:
python pipeline_illust.py full vsu6aa_lobby

# Manual equivalent:
python stage_layers.py vsu6aa_lobby illeff_vsu6aa_01_bg_b illeff_vsu6aa_01_b illeff_vsu6aa_01 illeff_vsu6aa_01_bg_f
python alpha_key.py vsu6aa_lobby illeff_vsu6aa_01_bg_b illeff_vsu6aa_01_bg_f
node bake_lobby_hq.js vsu6aa_lobby <cfx-order-csv> <out.webm> 2160 30 10 6 world0 1920x1080
```

Proven output: `_scratch/lobby_aube/aube_lobby_idle_hq.webm` (~107 MB @ 3840×2160).

---

## Deploy intimacy (existing site path)

1. `python finalize.py <slug> <idle.webm>` → `site/assets/<slug>/intimacy.webm`
2. `python build_index.py …` — appends `?v=<mtime>` cache-bust on intimacy URL
3. `./deploy.ps1 -SkipSync -SkipR2` (intimacy is Pages-served **if under 25 MiB**)

Frontend: `units.json` field `intimacy` ending in `.webm` → `<video autoplay loop muted>`.

Shipped sizes today (all **under** Pages 25 MiB):

| slug | ~MB |
|------|-----|
| c1153 | 12.5 |
| c2066 | 21.9 |
| c2181_1 | 7.0 |
| c2185_1 | 17.0 |
| c6005 | 15.1 |

---

## Site: Wallpapers → Animated (tab) + unit Illustration

`#/wallpapers` is a **tabbed** page (Animated | Static), same subnav pattern as Updates:

- **Data:** `site/data/lobby_anims.json` (private repo / deploy only — not public GitHub)
- **Posters:** `site/assets/_illust/posters/*.jpg` (Pages; ~100–200 KB each)
- **Videos:** **R2 only** → `https://assets.e7codex.com/illust/<stem>.webm`
- **No auto-load:** poster + “▶ Play · duration · ~N MB”; click opens the video lightbox
- **Clip variants** (e.g. Salome Idle / Story): `variants[]` on one catalog card — Idle/Story
  tabs like cosmetic pose pills; Play uses the selected stem (`epma_04` vs `epma_04_story`)
- **Unit page:** same packs under Illustration (with intimacy), via `units: ["c…"]`
- **Nav pastille:** gold blink-dot on Wallpapers for ~14 days after a `new_since` wave;
  clears on first open (`localStorage e7_wp_nav_seen`). Card **NEW** badge is separate
  (e.g. Aube); do not conflate the two.

Publish videos:

```powershell
python tools/_illust_spike/publish_lobby_anims.py           # hardlink locals
python tools/_illust_spike/publish_lobby_anims.py --upload  # rclone → r2:e7codex-spine/illust/
```

Posters ship with normal Pages deploy (`deploy.ps1`). Videos are never on Pages (25 MiB limit).
Partial upload is OK if a deferred sibling (e.g. story) is still baking.

---

## Hosting large files (100 MB+ lobby HQ)

### Hard constraints

| Host | Per-file limit | File-count | Notes |
|------|----------------|------------|--------|
| **Cloudflare Pages (free)** | **25 MiB** hard | 20 000 / deploy | Combat already held off Pages for size; voice held for count |
| **Cloudflare R2** (`e7codex-spine`) | Object-size effectively unlimited for our scale | n/a | Public: **https://assets.e7codex.com** · **zero egress** · CORS already allows e7codex.com |

Aube-class HQ (~100 MB WebM) **cannot** ship on Pages. Intimacy at 1080p/crf20–24 **can** stay on Pages if kept under 25 MiB.

### Reliable approach (matches existing architecture)

**Put large WebMs on R2**, same bucket as spine + voice:

```
r2:e7codex-spine/illust/<pack_id>.webm
# or
r2:e7codex-spine/lobby/<pack_id>.webm
→ https://assets.e7codex.com/illust/<pack_id>.webm
```

Wire-up pattern (same as voice / combat):

1. Keep masters under `_scratch/` or a staging dir (not necessarily under `site/`).
2. `rclone copy` to `r2:e7codex-spine/illust/` (or extend `deploy.ps1` Step 3).
3. Point `<video src>` / `units.json` / a future lobby gallery JSON at
   `https://assets.e7codex.com/illust/...` (absolute URL), **not** a relative
   Pages path.
4. Optional: keep a **site-tier** encode on Pages (1080p, higher CRF, &lt;25 MiB)
   for hot-path intimacy; serve **HQ** only from R2 when the user opens fullscreen
   or a lobby gallery.

R2 free tier (see `docs/DEPLOYMENT.md`): 10 GB storage, 10M Class B reads/month —
plenty for a few dozen 100 MB videos at fan-site traffic. Set a **spend cap** on
the Cloudflare account regardless.

### What is *not* a good fit

| Option | Why avoid for now |
|--------|-------------------|
| Pages only | 25 MiB cap blocks HQ |
| YouTube / Streamable embed | Lossy re-encode, branding, no exact loop control |
| Git LFS / GitHub releases | Not a CDN; rate limits; bad for video seeking |
| Self-hosted VPS disk | Bandwidth cost; you already have zero-egress R2 |

### Recommended product split

| Asset class | Target size | Host |
|-------------|-------------|------|
| Intimacy idle (detail page) | 1080p, CRF ~20–24, **&lt;25 MiB** | Pages `assets/<slug>/intimacy.webm` (current) |
| Lobby / event HQ | 1440p–2160p, CRF ~10–12, **50–150 MiB** | **R2** `assets.e7codex.com/illust/…` |
| Deferred intros | same as above by class | same |

Re-encode HQ down for site only if you want a single host; quality ceiling is
often texture res anyway (intimacy doc “quality ceiling”).

---

## Batch status / ops

- Progress: `tools/_illust_spike/batch_bake.log`
- First-run fixes applied: c1153 anchor `bg`, c2066 anchor `R_background4`
  (failed once mid-batch; re-run those ids after the batch if still missing)
- After successful intimacy bake: `finalize.py` + `build_index` + deploy as above
- After lobby HQ bake: do **not** drop into Pages blindly — stage to R2 first

```powershell
# Re-bake only failed / specific packs
python run_batch_bake.py --skip-stage c1153 c2066
```

---

## Exact-data checklist (before claiming “matches game”)

1. Layer order from **CFX z**, not hand montage (except documented washout excludes).
2. Lobby framing **world0** (or another rank-1/2 source) — no ShareX-fitted zoom.
3. Intimacy crop fractions only from rig data or `E7_LEGACY_CROP` for reproduce-old.
4. A/B vs game is **verification only**, not a source of constants.
5. Additive FX: run `alpha_key.py` after stage.

---

## Session handoff (2026-07-27)

- Pipeline + recipes + deferred intros authored.
- Stage + alpha_key completed for active set.
- Batch bake started for 21 active packs; c2181 succeeded (~7 MB).
- Aube world0 HQ already on disk at `_scratch/lobby_aube/aube_lobby_idle_hq.webm` (~107 MB).
- Hosting decision pending product wiring: **R2 for 100 MB+**, Pages for sub-25 MiB intimacy.
