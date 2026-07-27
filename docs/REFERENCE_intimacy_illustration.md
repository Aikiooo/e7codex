# REFERENCE — Animated intimacy illustration pipeline (`tools/_illust_spike/`)

How the animated intimacy illustrations (`site/assets/<slug>/intimacy.webm`, the looping
idle on a hero detail page) are built: multi-layer Spine effect rigs composited and baked to
a seamless WebM loop. Covers the c2185 (Rhianna & Luciella) case end-to-end, the
**Spine 4.2.43** render method, and the deploy. Complements memory note
`project-e7-intimacy-webm` (base bake recipe) — read this for the flower fix, 4.2.43, deploy.

> **2026-07-27 — full catalog + lobby pipeline:** see
> **`docs/REFERENCE_lobby_illust_pipeline.md`** for `recipes.json`, CFX z-order,
> world0 lobby framing, deferred intro one-shots, batch bake ops, and **hosting
> 100 MB+ WebMs on R2** (Pages is 25 MiB/file). Prefer that doc for new work;
> this file keeps the c2185 deep-dive and 4.2.43 notes.
>
> **2026-07-27 — c1153 / c6005 FX motion frozen:** spine re-bake leaves petals
> and butterflies laggy / wrong positions vs the live site. Recipes use
> `bake: "reuse_site"` (copy `site/assets/<slug>/intimacy.webm`). Framing targets
> stay documented (`bg_ex` / `bg2`+bottom residual). See
> `recipes.json` → `_meta.deferred_intimacy_fx`. **c2185** spine bake is fine.
>
> **2026-07-27 — intimacy INTROS stopped / rejected:** `c2185_intro` +
> `c6005_intro` re-bakes look very bad vs game / prior spike. Do **not** ship.
> Full write-up: **§ Deferred intimacy INTROS** below.
> `recipes.json` → `_meta.deferred_intimacy_intro`.

## Where the art lives

In-game the intimacy screen is a stack of Spine effect rigs in
`extracted_data/output/effect/`, named `illeff_<slug>_*` (FX/background layers) and
`uieff_illust_<slug>` (the base illustration rig, when present). For c2185 the layers are
`illeff_c2185_{a,b,bg_back_2,bg_back_1_1_backup2_*,bg_back_1_2*,bg_front,*_butterfly*}`
(`_a`/`_b` are the two characters). `.scsp` + `.atlas` + `.sct`, same envelope as every
other rig. `decode_sct` is version-agnostic → textures always decode.

## The compositing pipeline (all in `tools/_illust_spike/`)

**Orchestrator (preferred):** `pipeline_illust.py` + `recipes.json` + `cfx_order.py`.
Catalogs every former pack (c1153 / c2066 / c2181 / c2185 / c6005 intimacy +
`vsu6aa_lobby`). Z-order comes from CFX primitive `z` (rank 2). Lobby packs use
`bake_lobby_hq.js` + `world0` framing; intimacy uses `bake.js` + slot AABB.
`list` / `dry-run` never bake — only `still` / `bake` / `full` start renders.

```
python tools/_illust_spike/pipeline_illust.py list
python tools/_illust_spike/pipeline_illust.py dry-run          # plan only
# python tools/_illust_spike/pipeline_illust.py full           # when ready
```

Encode env (shared via `encode_ffmpeg.js`): `E7_VP9_CPU_USED=2` (default, much
faster than libvpx’s 0), optional `E7_ENCODER=av1_amf` for AMD hardware previews.

1. **`stage_layers.py <base> <stem…>`** — `.scsp→json` (via `tools/scsp_to_json.py`), copy
   `.atlas` (rewriting the `.sct` page line to `.png`), decode `.sct→.png`. Auto-premultiplies
   ONLY straight-alpha FX pages (detects per page; idempotent). Output → `c2185/<stem>.{json,atlas,png}`.
2. **`rec.html`** — loads every layer as a spine-player 3.8 canvas in z-order, exposes
   `__aabb(slot)` (world AABB of an anchor slot), `__reframe(aabb,W,H,pad,crop)` (pins all
   layers to one world rect → they share coordinates), `__seek(t)` (deterministic frame), and
   a pre-rendered image-seq layer hook (see 4.2.43 below).
3. **`bake.js <base> <order> <out.webm> <fps> <anchor> <outH> <crop> <maxSec> <crf> <workers> [--keep-frames] [--pre …]`**
   — GPU + N parallel workers. Probes `__aabb(anchor)` + loop `__dur()`, derives
   `W = round(outH * aabb.w/aabb.h)` (so the world rect maps 1:1 to the canvas, no
   letterboxing), splits `[0,N)` across workers, each `__seek`s + screenshots `#wrap`. Each
   worker waits **2×`requestAnimationFrame`** after `__seek` before the screenshot (GL-composite
   settle; without it you get stale/stuttered frames at worker-range boundaries). 5 workers is
   the safe max for ~15 layers (8 OOMs). Lobby HQ variant: **`bake_lobby_hq.js`** with
   `world0` + `res=1920x1080`.
4. **`tail.js`** — renders N continuation frames past the loop end (same framing) for the crossfade.
5. **`xfadeloop.py <bodyDir> <tailDir> <out.webm> <fps> <crf>`** — crossfades the continuation
   tail into the loop head → a seamless wrap.
6. **`finalize.py <slug> <idle.webm> …`** — copies the idle WebM to `site/assets/<slug>/intimacy.webm`.

**Loop length principle:** pick `L = integer × (character anim period)` so the character is
byte-seamless at the wrap; the crossfade hides the few slower FX layers. For c2185, L=14s
(= 3×4.667s char = 1×14s bg). **Verify the seam:** adjacent-frame diff at the wrap (frame
N-1→0) should ≈ a mid-clip adjacent-frame diff (extract frames with ffmpeg `select`, compare
mean abs diff). c2185 with-char: seam 4.75 vs mid 3.45–5.14 = seamless.

## c2185 final recipe (SHIPPED 2026-06-09)

```
base=c2185  anchor=bg_b1  outH=1080  fps=30  loop=14s  xfade=30 frames  crf=24  workers=5
output 2396x1080, then CROPPED to 2380x1080 (see below)
order (15 layers, back→front):
  bg_back_2, bg_back_1_1_backup2_big1, bg_back_1_2_blue, blue_2, blue_3,
  pink_big, pink_small_1..5, b, a, bg_front, loop_butterfly_front
  (all prefixed illeff_c2185_)
```
Commands: `bake.js … 14 24 5 --keep-frames` → `tail.js … 14.0 30` → `xfadeloop.py` →
`ffmpeg crop=2380:1080:0:0`. The `--keep-frames` PNG dump is ~1GB transient (2.6MB×420),
consumed by xfadeloop, delete after.

### Flowers vs butterflies — the layer identities (don't relearn)

The c2185 bg layers' atlas region names tell you what each is:
- **`buts_*` (+`buts_01_glow`,`flash`) = BUTTERFLIES.** This is `bg_back_1_2` (the 4.2.43 master)
  AND its split children `bg_back_1_2_blue/blue_2/blue_3` (blue butterflies) and
  `pink_big/pink_small_*` (pink butterflies). The 4.2.43 master is the combined rig the
  blue/pink were split from → adding it DUPLICATES the butterflies already in the bake. Do not.
- **`bg_m1`/`bg_m1_1..7` = the FLOWER BED foliage.** Only in `bg_back_1_1_backup2_big1`. Its
  `big2`/`small` siblings are `buts_*` (extra butterflies only).

**The fix that shipped:** the original bake omitted the flowers. Add ONLY
`bg_back_1_1_backup2_big1` (the flowers) right after `bg_back_2` (near the back, behind chars).
**Do NOT add `big2`/`small`:** besides being redundant butterflies, having multiple of these
straight-alpha rigs together BLOWS OUT the whole background to white (persistent full-frame
additive washout; `pma=false`/pmaoff did NOT fix it; each rig alone is fine, the combination
is not — root cause unconfirmed, just avoid it). `big1` alone = flowers + intact night
background + the existing butterflies.

### 2380×1080 crop

There's a thin gap at the right edge when the foliage animates. Trim the right 16px:
`ffmpeg -i in.webm -vf crop=2380:1080:0:0 -c:v libvpx-vp9 -crf 24 -b:v 0 out.webm`. The pixel
crop preserves the xfade loop seam. (Equivalent in-pipeline: bake with `crop "0,0,0,~0.00615"`.)

### Characters-removed variant (personal use, NEVER on the site)

Same recipe, drop `illeff_c2185_b` and `illeff_c2185_a` from the order (13 layers). The
anchor `bg_b1` is in `bg_back_2`, so framing is unchanged. Kept local only.

## Spine 4.2.43 rigs — how to render them (the new capability)

E7 ships a THIRD Spine generation, version string `4.2.43` (TASKS #54). `scsp_to_json`'s two
converters can't read it (`detect_version`→None). **You don't need a converter — render it
directly with the official version-matched runtime:**

1. **Strip the E7 container.** LZ4-decompress the `.scsp` (the 2.1.27 converter's check step
   leaves a `.scsp.unpacked`). The body is `"scsp"` magic + a **16-byte** E7 header, then a
   STOCK Spine 4.2 `.skel`. Slice `body[16:]` → `flowers.skel`. (Verified: version "4.2.43" at
   body offset 25, then `referenceScale`=100 the 4.2 physics field; clean parse, e.g. 1517 bones.)
2. **Install the EXACT version-matched runtime.** npm publishes `@esotericsoftware/spine-webgl`
   per editor build, so a "4.2.43" export needs **`spine-webgl@4.2.43`** (4.2.10 = too old, fails
   at slots; 4.3.0 = reads the skeleton but the constraint/animation encoding diverges → 0 skins
   then a giant-alloc crash). `npm install @esotericsoftware/spine-webgl@4.2.43 --no-save --prefix ./_spine42`.
3. **Render with the 4.2 API:** `skeleton.setToSetupPose()`, `skeleton.updateWorldTransform(spine.Physics.update)`,
   `slot.getAttachment()`. Atlas uses the new 4.x `bounds:`/`offsets:` format (only the 4.x
   runtime reads it). Harness: `v42.html` (single-frame/probe) + `flowerseq.js`/`flowerseq.html`
   (bakes a transparent PNG sequence at the shared bake framing).

**Compositing a 4.2 layer into a 3.8 bake** (it renders via a separate runtime/canvas):
- `flowerseq.js` bakes the 4.2 layer to `_flowers_seq/f%04d.png` at the SHARED framing — camera
  `position=(aabb.x,aabb.y)`, `zoom=aabb.width/W`, canvas W×H. **Must render `flip=1`**
  (`skeleton.scaleX=-1; skeleton.x=2*cx`): the spine-webgl render is X-mirrored vs spine-player,
  so without the flip the layer lands on the wrong side.
- `rec.html` has a param-gated pre-rendered-seq layer (`preDir/preN/preDur/preZ`); spine layer
  z's are spread to `i*2` so it slots at an odd z. `bake.js`/`tail.js` pass it via `E7_PRE_*`
  env + `bake.js --pre <dir> <N> <dur> <z>`.

NOTE for c2185 this 4.2.43 capability was built but NOT used in the final illustration — its
rig (`bg_back_1_2`) is butterflies that duplicate existing layers (see above). Kept for the
next 4.2.x rig that actually matters (portrait/combat 4.2 rigs will need approach #1, a real
binary→JSON converter — TASKS #54).

## Deploying an updated `intimacy.webm`

1. Re-bake + stage over `site/assets/<slug>/intimacy.webm` (back up the old one OUTSIDE `site/`).
2. **Re-run `build_index.py`** — it appends `?v=<file mtime>` to the intimacy URL in `units.json`
   (build_index.py ~L666). This is the cache-bust; without a fresh `?v` the CF edge serves the
   stale clip for ~4h (`max-age=14400`). `-SkipSync` skips build_index, so run it by hand:
   `python build_index.py --img <IMG_DIR> --raw <RAW_DIR> --out ./site` (paths from `tools/paths.py`).
3. **`./deploy.ps1 -SkipSync -SkipR2`** — intimacy.webm is a Pages asset (NOT in the R2 manifest,
   which only globs `<slug>/<slug>.{json,atlas,png}` + combat), so skip R2; Step 2b leak gate still
   runs. Verify: `curl -sI https://e7codex.com/assets/<slug>/intimacy.webm?v=<mtime>` →
   `200`, right `content-length`, `cf-cache-status: MISS`.

**Size cap:** Cloudflare Pages free plan is **25 MiB per file**. Current shipped intimacy
WebMs are ~7–22 MB (OK). Anything larger (lobby HQ ~100 MB) must go to **R2**
(`assets.e7codex.com`) — see `REFERENCE_lobby_illust_pipeline.md` § Hosting.

## Quality ceiling (don't chase this again)

The intimacy render looks softer than the official unit-PV. Cause: the **extracted textures are
lower-res than the output** (e.g. c2185 `bg_back_2` background is 1448×860 stretched to 2380×1080;
foliage `big1` is 1780×256). So:
- **2× supersampling does nothing** (no detail beyond the source to resolve) — confirmed, dropped.
- **Sharpening (unsharp)** crisps it but the user judged the original better — dropped.
The PV's sharpness comes from high-res illustration masters NOT in the game client, so it's
unreachable from extracted assets. The straight render at output size is the practical ceiling.

---

## Deferred intimacy INTROS (2026-07-27 — STOP)

**Status: rejected / stop.** User QA: latest intro WebMs look **very bad**. The prior
`c6005_intro.webm` in the spike was **closer to the truth** than the 2026-07-27 re-bake.
That former file was **overwritten** during the session; **no backup** was found under the
repo. Rejected artifacts were renamed:

| Pack | Rejected files (spike) |
|------|------------------------|
| c2185 | `c2185_intro.rejected_2026-07-27.webm`, `c2185_intro_still.rejected_2026-07-27.png` |
| c6005 | `c6005_intro.rejected_2026-07-27.webm`, `c6005_intro_still.rejected_2026-07-27.png` |

Recipes: `deferred: true` on both packs. Catalog pointer:
`tools/_illust_spike/recipes.json` → `_meta.deferred_intimacy_intro`.

**Do not** re-bake, ship, or `finalize` intros until engine camera + screen-space FX are
modeled correctly (not approximate hacks). Idle intimacy work is separate
(`deferred_intimacy_fx` for c1153/c6005 petals; c2185 idle is fine).

### CFX / clip facts (rank-2 — keep)

| Pack | CFX stems | Layer order source | Clip map |
|------|-----------|--------------------|----------|
| `c2185_intro` | `illeff_c2185_intro_bg_b`, `illeff_c2185_intro`, `illeff_c2185_intro_bg_f` | CFX `z` merge; exclude washout `backup2_big2` / `backup2_small` | CFX `ani`: char layers **`intro_1_en`**, bg layers **`intro`**, butterfly only has `animation` |
| `c6005_intro` | `illeff_illust_c6005_1_intro` | same stems as idle stack (`_bg`, `_b`, `_sphere`, `_a`, `_f`) | CFX `ani` = **`intro`** on all layers (~21s) |

Pipeline already wires CFX `ani` → `E7_LAYER_ANIMS` / rec.html `LAYER_ANIMS` (per-stem clip).
`actanim` alone cannot express mixed clip names (c2185 char vs bg).

### c2185 intro — symptoms & probes

- **Symptom (rejected bake):** dramatic head-back pose with a **face floating near the moon**;
  bodies/FX otherwise composite. Looks wrong next to idle intimacy (faces on bodies).
- CFX map is correct (`illeff_c2185_a/b` = `intro_1_en`, bg = `intro`). Phase report confirms.
- `intro` vs `intro_1_en`: layer **a** bones/slots **identical**; layer **b** only tiny face-bone
  value diffs. Switching clip name alone does **not** reattach the moon face.
- Idle `animation` keys `ree2_head_up` / `ru_head_up`; intro clips **do not** key those bones.
  Intro **does** key face parents with large local offsets (e.g. `bone11` translate ~x=401,
  `ru5` large y) for the whole clip — consistent with a broken parent chain / missing head
  follow, **or** authored cinema that spine-player does not composite the way the engine does.
- `max_sec=10` truncates butterfly master ~11.47s (intentional first-phase cut before delayed
  `animation_intro` in CFX delay chain).
- **Open:** whether moon face is engine-correct, converter bone error, or needs multi-track
  mix — **not resolved**; do not ship until A/B vs game.

### c6005 intro — symptoms & probes

- **Symptom (rejected bake):** either empty/dezoom, full white wash, or “pretty still but
  wrong motion / lighting / enter” vs user memory of the **former** spike webm.
- **Camera bone (rank-2):** on `_a` / `_b` / `_sphere` / `_f`, `camera` parents `ch` (and glows).
  Idle `animation` leaves camera near identity; **`intro` keys large camera translate/scale**
  (e.g. t0 translate ~3433,1432 scale ~2.49). Engine treats this as a **view matrix**;
  spine-player treats it as a mesh parent → character ejects fixed AABB / “dezooms”.
- **`cam_neutral` (rec.html `camneutral=1`):** after `apply`, reset bones named `camera` to
  setup, then `updateWorldTransform`. Restores idle-like framing for body under fixed AABB.
  **Incomplete:** does not recreate engine view; screen-space FX still wrong.
- **`fade` slot (f layer):** attachment `eff_sprite/t_sphere_03`; color timeline hits
  `FFFFFFFF` at several times (screen flash). Under fixed AABB this **washes the frame**.
  A/B: `ehide=fade` → white%~13%; `ehide=prism` alone does **not** fix wash. Recipe field
  `ehide` → `E7_EHIDE` (pipeline + bake.js + dbg.js). Hiding fade is a **hack**, not proof
  the enter/FX match the game.
- **`prism_total`:** scale ~130× on intro (additive prism flashes under `total`, not under
  `camera`). Not the primary wash source in A/B; still camera-space-ish FX risk.
- **Body enter:** many `ch_*` attachments are **null until t≈3.03s** (authored). Stills at
  t=0.5 are empty of character by design; recipe `still_t` (default 0.5) exists for mid-clip
  stills — do not treat empty t0 as a bug.
- **Layer isolation:** dropping f-layer entirely also removed wash (loses front FX). Full
  stack without engine camera remains unfaithful.

### Plumbing added this session (keep; intros stay deferred)

| Piece | Role |
|-------|------|
| `pipeline_illust.anims_csv` / `E7_LAYER_ANIMS` | CFX per-stem `ani` |
| `cam_neutral` / `E7_CAM_NEUTRAL` / rec.html `CAM_NEUTRAL` | reset `camera` bone after apply |
| `ehide` / `E7_EHIDE` / rec.html `EHIDE` | zero alpha on slots whose **name contains** token |
| `still_t` | intimacy still time for dbg (intro enter delay) |
| dbg.js | passes `anims`, `camneutral`, `ehide` |

### What “correct later” needs (fail closed)

1. **Engine camera / EffectPlay view** for hierarchical `camera` bones — not only
   setup-reset, and not screenshot-fitted pan/zoom.
2. **Screen-space fade/prism** as viewport overlays (or faithful blend), not mesh parents
   under a neutralized camera.
3. **c2185 head attachment chain** under intro clips — RE or multi-track mix; do not
   eyeball-nudge bone positions.
4. **Restore or re-derive a good baseline** before overwriting: always copy prior
   `*_intro.webm` to a timestamped backup before bake.
5. A/B only against game / known-good spike; pixel-mean white% is not a golden metric.

### Related open work (unchanged)

- **c1153 / c6005 idle FX motion** — still `bake: reuse_site` (`deferred_intimacy_fx`).
- **c2185 idle** — spine bake OK; not blocked by intro rejection.
- Tori / lobby intros (`vva5aa_*`) remain deferred catalog entries only.
