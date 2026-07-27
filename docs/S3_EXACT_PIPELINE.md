# Skill-3 "Exact Replay" pipeline — investigation & design brief

_Status: investigation complete (fable5 4-agent map + Opus synthesis), 2026-07-04. No code changed yet._

## TL;DR verdict

**Yes — a clear, deterministic "copy the game exactly" chain is buildable, and it is the right move.**
The current Skill-3 system is lackluster because it **throws away an authored camera/scene-director
track that the game ships on disk** and substitutes ~15 VOD-fitted magic constants. The authored data
exists, is parseable today, and most of the fix needs **zero new reverse-engineering** — it's a
compile + compositing rewrite, gated on **two small, bounded** RE extractions for byte-exact camera
placement.

Original hypothesis was right with **one correction**: the authored track is **not in `.timeline`** —
it's in the sibling **`output/stagept/c_<stem>_skill_NN.stg`** node-graph. `.timeline` only carries
self-anchored FX spawn cues.

## What the game actually does (confirmed from on-disk data)

Each skill is a `.stg` **node+edge graph program** (`entities[]` with `etty` type + `guid`,
`connections[]` with `from/to/when/delay`). Edge timing is RE-validated: `when:1` = fire on FROM
**start** (+delay ms); absent = fire on FROM **complete** (+delay ms); `when:2` = param attach.
Fleet counts across 505 `skill_03` graphs:

| Channel | Node (count) | Authored fields |
|---|---|---|
| **Camera** | `CAM` (2256), `ZOOM` (2402), `MOVE` (300), `SHAKE` (734) | location enum, x/y, **absolute scale 0.6–2.0**, cubic-bezier `curve` ("c1x,c1y,c2x,c2y"), tween `time` ms; SHAKE → a real camera Spine rig |
| **Camera rigs** | `output/camera/*_cm.scsp` (1677 files, 708/708 SHAKE sources resolve) | bones `[root, camera]` with a **per-frame `camera` translate timeline** — the literal camera path (estelle finale = ±100u shake waveform). Convert today with `tools/scsp_to_json.py`. |
| **Scene director** | `LAYOUT` (737), `BGSHOW` (812), `DARK` (515), `COLOR_BLEND` (937), `BGHATCH` (119) | field on/off/restore, `alone` isolate-caster; fullscreen fade color/opacity/fadeIn/fadeOut/z; team tint; speed-lines |
| **Post-process** | `PPEFFECT` (278: `sprite_blur`×275, `sprite_invert`×3) + `SINE_VALUE` (275 on `u_range`) | GLSL program name + direction_x/y, u_sample (samples), u_range (radius) oscillated by SINE |
| **Content** | `ANI`/`ANI_SCOPE`, `EFFECT`/`HIT`, `CUTIN` (407), `NODE_ANI` (442) | spine anim + event scoping, FX spawns, cut-in webp + curtain, node-graph sub-anims |

**Anchor enum FULLY DECODED** from the decrypted LuaJIT bundle (`game_bin_decrypted.bin`, proto 34076
KGC table 2 = `LOCATION_TYPE_VER2`):

```
Screen_Center=0  Attach_Self=1  Attach_Target=2  Attach_Object=3
Unit_Self=5      Unit_Target=6  Field_Self=11    Field_Target=12
Field_TargetFront=16  Field_OurFront=31  Field_OurCenter=32
Field_ForFront=41     Field_ForCenter=42
```
Sibling tables recovered: `LOCATION_LAYER` (Field/Effect/Ui/Cutin), `CAMERA_MODE`
(Setup/Current/Tracking), `CAMERA_FOCUS` (Self/Target/Object/Location/In/Out), `MOVE_STYLE`.
Runtime anchor semantics confirmed in Lua (protos 4755, 34543): **Attach_\*** = addFollower +
getBonePosition (follows model/bone); **Unit_\*** = getWorldPosition snapshot; **Field_\*** =
`BattleLayout.getTeamLayout` team-slot (static compile-time constants); **Screen_Center** =
DESIGN_WIDTH/DESIGN_HEIGHT screen space.

**Blend modes are authored and already in the staged JSONs.** 81% (3600/4425) of FX rigs carry
additive/screen/multiply slots; 1063/1157 particle emitters are additive `(SRC_ALPHA,ONE)=770,1`.
The wrong colors are a **compositing-architecture bug, not missing data**.

**`rs_<cslug>` Lua tables are a red herring for main battle** — they're the *Rumble* mode's
simplified script (`RumbleUnitAnim`, loaded from `output/rumble/*.rtg`). The `.stg` graph is the
authoritative main-battle spawn+camera script. The "~81 Lua-only units" premise is **inverted**:
those units (Byblis etc.) have fully authored `.stg` graphs; the executor just doesn't read them.

## Root-cause diagnosis (ranked by visible damage)

1. **Authored camera discarded → content-follow heuristic.** `prepare_fx_assets.py:104-106` literally
   says _"Camera (CAM/ZOOM/MOVE/SHAKE-rigs) + post (PPEFFECT/DARK/LAYOUT) are timing pass-throughs only
   — not rendered yet."_ The whole track collapses to one boolean `s3.cinecam` (`:447-455`), which
   merely authorizes `viewer.html`'s median-follow + cover-zoom camera (`~1930-2070`) built from ~15
   fitted constants (3650u window, 0.55x zoom floor, 900/1700u snap, 0.30s settle, 0.8s grace, 64×40
   ink probe…). **On-disk proof: `cinecam=0` on ALL staged units** → the heuristic runs everywhere.
   ⇒ wrong zoom/pan, invented moves, wobble/settle artifacts, per-unit manual fixing. **This is the
   "lackluster + needs a ton of fixing" complaint.**
2. **Cross-layer blend flattened.** Each FX rig renders additive/screen/multiply slots into its own
   transparent premultiplied canvas, then all layers composite **source-over** (`bake_skill3.js:356-407`,
   viewer `canvases()`). Additive never blends against the backdrop ⇒ **doris yellow/teal vs in-game
   white/blue.** Data is present; architecture is wrong.
3. **DARK overlays dropped.** Authored fullscreen fades (estelle whiteout `255,255,255` fadeIn390
   fadeOut600; black opacity 0.7 curtain) are removed; band-aided by a frame-**delete** hack
   (`bake_skill3.js:567-584`). ⇒ the transparent curtain-gap frame; missing whiteout/dim beats.
4. **Anchor enum mis-decoded.** `STG_TGT_LOCS={5,6,41,42}` treats `5=Unit_Self` (the **caster**) as
   enemy-side and omits real target codes 2/12/16; everything collapses to loc 1/5 + a fixed 600px
   phantom-enemy offset (`FX_TARGET_DX`). ⇒ wrong-side / wrong-position spawns; screen-center finales
   drift with the camera instead of staying screen-locked.
5. **Continuous z collapsed to binary.** `globalZ`+`localZ` (one continuous axis) is reduced to
   behind/in-front-of-character (`viewer.html:2199`). ⇒ layers land on the wrong side of the character.
6. **PPEFFECT / COLOR_BLEND / BGHATCH not applied**; **`.cfx` `attach`/`actions`/`color`/`disable`
   fields dropped** (567 bone-parents, 320 procedural tweens, 30 shipped-but-disabled prims);
   **skill_01/02 `.stg` ignored** (executor reads `skill_03` only → convention-guesses the rest).
7. **Floor-ride / reframe-up** (`bake_skill3.js:336-405`) — a per-scene-type pixel-feet hack
   substituting for the authored scene-camera relation. Generalizes to nothing. ⇒ the floor seam.

> The **scheduling layer is already faithful** (graph executor, edge semantics, EFFECT-completion =
> cfx tail, cut-in field-pause, track-time bake clock — VOD-verified to ~0.2s). Divergence is
> concentrated in **camera, post, blend, anchors** — not timing.

## The exact chain (proposed)

**Source of truth:** `output/stagept/c_<stem>_skill_NN.stg` for *all* skills (retire skill_03-only +
convention-guessing + rumble-as-authoritative merge).

**Stage 1 — Compile (`prepare_fx_assets.py`, camera/director rewrite).** Stop collapsing to `cinecam`.
Emit the full authored tracks keyed to graph-edge start times:
- `camera[]`: per CAM/ZOOM/MOVE node → `{startMs, location(decoded), x, y, scale, curve, timeMs}`;
  per SHAKE → `{startMs, cmRig, powerX, powerY, timeScale}`.
- `overlays[]`: DARK / COLOR_BLEND / BGHATCH with params + z + fade curves.
- `post[]`: PPEFFECT `{program, direction, u_sample, u_range, sine}`.
- Anchors: decode via `LOCATION_TYPE_VER2` (fix the `STG_TGT_LOCS` bug; distinguish Attach follow vs
  Unit snapshot vs Field team-slot vs Screen_Center screen-space + `LOCATION_LAYER`).
- `.cfx`: compile `attach` (cross-rig bone parent), `actions` (Move/Scale/Fire tweens w/ `a~b`
  ranges), `color`, `disable`; honor particle `blendFunc`.

**Stage 2 — Replay (`viewer.html` FX engine).**
- **Camera:** one OrthoCamera driven by the authored track — interpolate ZOOM.scale + CAM anchor/offset
  with the authored **bezier over authored time**; add the cm-rig `camera`-bone translate for shake;
  compose the scene rig's `camera`/`camera_scale` bone during cutaways. **Delete** median-follow,
  cover-zoom, ink-probe, settle/freeze/grace, floor-ride, reframe-up (~15 constants gone).
- **Compositing:** single shared render target so authored slot blend modes blend against the real
  backdrop (**closes the color gap, zero RE**); real continuous `globalZ/localZ` z-sort with the live
  rig inserted at its authored global-Z (delete the binary split).
- **Overlays/post:** DARK/COLOR_BLEND/BGHATCH + PPEFFECT (approx blur/invert first) as canvas/WebGL
  passes at authored z/time.

**Stage 3 — Bake (`bake_skill3.js`).** Camera now comes from the engine — render the OrthoCamera frame
at design resolution. Remove union-viewport/minFrame/floor-ride/reframe and the DARK frame-drop hack.

## RE / decode gaps (all bounded)

| # | Gap | Where to look | Blocker for |
|---|---|---|---|
| 1 | **BATTLE layout constants** (TEAM_X/Y, TEAM_WIDTH/HEIGHT, X_GAP, TEAM_INDENT, FLY_HEIGHT, GLOBAL_EFFECT_POS, DEF_CAM_SCALE, DESIGN_WIDTH/HEIGHT) — field-name strings are in the Lua; numbers are in the proto **KN array**, not yet extracted | Extend `_lj_skill_tables.py` with a KN/bytecode-aware pass — **no new Ghidra run** | Absolute Field_\*/Screen_Center anchors; base camera window |
| 2 | **Base battle-camera projection** the ZOOM.scale multiplies + CAM offsets into (world origin, base zoom, px vs world coord space) | Mostly reuses #1; if exact C++ needed, one targeted Ghidra pass on the CAM consumer (`getEffectLocation`/`BindLocationPivot` leads) | Byte-exact framing |
| 3 | **cm-rig → camera application convention** (do powerX/Y/timeScale scale the bone track? how does it compose with ZOOM/CAM?) | Ghidra stagept SHAKE handler, or empirical VOD fit | Exact shake feel |
| 4 | **PPEFFECT GLSL** (`sprite_blur`, `sprite_invert`) | game shader cache / embedded strings | Pixel-exact post (approximable first) |

## Feasibility per subsystem

| Subsystem | Rating | Blocking item |
|---|---|---|
| Blend / color | **feasible now** | none — shared render target |
| Z-order | **feasible now** | none — insert char at authored global-Z |
| Camera (relative zoom/pan/shake shape) | **feasible now** | none — replay authored bezier tracks |
| Camera (absolute pixel-exact) | needs-RE | #1 layout constants (+ maybe #2) |
| Anchors (self/target/field/screen) | **feasible now** for self/target; needs-RE for exact Field slots | #1 |
| DARK / COLOR_BLEND / BGHATCH overlays | **feasible now** | none — params authored |
| PPEFFECT post | partial | approximate now, #4 for exact |
| cm-rig shake | partial | #3 convention |
| Particles + .cfx fields | **feasible now** | none — data authored |

## Recommended plan (smallest-first, each independently shippable)

1. **Cheapest proof of the whole thesis — do this first (est. S–M):** take **estelle** (already
   VOD-verified; ZOOM 1.65, CAM location 11≈centre, cm rig converted) and (a) apply the **shared-render-
   target blend fix**, (b) replay her **authored ZOOM+CAM+SHAKE track (relative)** with the content
   heuristic disabled. Compare to VOD. If framing + colors snap to the game with **no magic constants**,
   the approach is proven. Needs no RE (ZOOM relative, loc 11 known). Two orthogonal signals: the blend
   fix alone proves the color diagnosis; the camera replay proves the framing diagnosis.
2. **Blend/z compositing rewrite fleet-wide (M):** shared render target + real z-sort. Highest ROI,
   zero RE, fixes the color complaint everywhere.
3. **Camera-track compile + replay fleet-wide (M+M):** emit `camera[]`, drive the OrthoCamera, delete
   the heuristic stack. Relative first; wire in constants from step 4 for absolute.
4. **Extract BATTLE layout constants (S–M, Lua only):** unblocks absolute anchors + base camera.
5. **Anchors + .cfx fields + particles (M); DARK/overlays/PPEFFECT (M); cm-rig shake (S after #3 gap).**
6. **Extend executor to skill_01/02 `.stg` (M):** retire convention-guessing → real coverage.

**Risks:** spine-player 3.8 may not expose a clean camera override (mitigate: transform the composited
frame — fine for ortho); constants #1/#2 might not reconcile exactly → residual offset needing one
Ghidra pass; cm-rig convention (#3) is the least-certain piece; a few units route spawns through
`NODE_ANI`/spani orchestrators whose event timelines are currently read-and-discarded.

## Open questions for the owner
- Ship target: **near-exact now** (relative camera + blend, no RE) then iterate to byte-exact, or hold
  until the layout constants land?
- Is the current `S3_DEV`/`-IncludeSkill3` local-only gate the right home to prototype this behind?
- Priority: fix the whole **fleet's colors** first (step 2, broad + cheap) or nail **one unit end-to-end**
  first (step 1, deep proof)? Recommendation: step 1 then step 2.
