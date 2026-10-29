# Exact Hero View background plates (`render/bg/bg_field.py`)

Recovered 2026-10-09 from the game's own Lua (LuaJIT bytecode,
`game_bin_decrypted.bin`). Rank-1 provenance throughout
(see `docs/reference/exact_data.md`); nothing here was
measured from a capture. Captures were used only for human A/B.

This **supersedes** the framing in `render/bg/render_backgrounds.js` (`bestWindow()`
largest-painted-16:9 search, `packWindow()` cover-fit). That approach is a
content-follow heuristic, which the exact-data rules ban as a camera. Keep it
only for the (removed) gallery tab's history.

## Pipeline

```
python render/bg/bg_field.py                 # stage every pack, both modes -> site/assets/_bg_field/
python render/bg/bg_field.py ma_bg_epi5_1    # one pack
node   render/bg/render_bgfield.js           # bake -> site/assets/_bg_field_out/<id>__<mode>.webp
python render/bg/bg_field.py --frames        # site/data/bg_frames.json for viewer.html's picker
```

`render_bgfield.js` resumes (skips baked plates; `--force` re-bakes) and reports
per-plate **coverage** = painted fraction of the game's window. No crop or
re-frame happens there: the window IS the game's camera, so a hole is a
composition bug to fix in `bg_field.py`.

`--rows 6,8` (debug) stages a pack with only those `background` rows, as
`<id>__<mode>__r6-8`. This is how the weighted-mesh bug below was found.

## How to find the protos again

Proto indices are positions in the bundle's proto stream as yielded by
`_game_re/_lj_disasm.iter_protos` (it recurses into nested chunks; it matches
`_lj_protos.pkl` 1:1). The stock disassembler doesn't decode `TDUP` table
constants or upvalue refs. The extended reader used for this
(ktab decode, `uv` refs, parent tree built from the post-order dump) lives in
the session scratchpad as `ljx.py`. To rebuild it: parse each proto again at
`abs_off` **in its own (possibly nested) buffer**, and decode KGC tag 1 tables
as `narray, nhash` + `ktabk` items (tag 0 nil, 1 false, 2 true, 3 int, 4 num,
≥5 string). Note `pr['kgc']` from `_lj_disasm` is already **reversed**
(bytecode-operand order).

| Proto | What |
|---|---|
| 46478 | `init_resolution_constanst`: `MODEL_SCALE_FACTOR = DESIGN_H / MODEL_DESIGN_HEIGHT`, `CAM_ANCHOR_X = 0.5`, `CAM_ANCHOR_Y = 0.2`, `BASE_SCALE` |
| 46479 | globals: `MODEL_DESIGN_HEIGHT = 640`, `WIDGET_DESIGN_WIDTH = 1280` |
| 43945 | field module root: `FIELD_REDUCE_SCALE = 2/3`, `FIELD_SCROLL_ANCHOR_RATE = 0.025`, locals `1`, `0.6` (parallax divisors, upvalues of 43901/43883) |
| 43883 | row loader: `DB('background', theme..'_'..n)` n = 1..150; column list (TDUP) `spr scale x y width per_x per_y scroll type zoom_scale r g b anchor_y atlas roof_obj main_land main_ground rotation alias opacity flip_h flip_v time_scale`; `scale/x/y *= MODEL_SCALE_FACTOR`; `width` default 0; `bg_atlas` from row `_1` |
| 43918 | field create: viewport `{x=0,y=0,w=DESIGN_W,h=DESIGN_H,scale=1}`, `setWidth(DESIGN_W*2)`, one `addOneLayer` per row in order |
| 43920 / 43923 | `getWidth` = `max_width or DESIGN_W*2`; `getHeight` = `max_height or DESIGN_H*1.1` |
| 43932 | `setViewPortPosition`: `viewport.x = clamp(x, minRangeX, maxRangeX)`; y untouched when nil |
| 43937 | `addOneLayer`: `Node('--rotation')` at game_layer origin, `setRotation(row.rotation)`; layer at `(vp.w*CAM_ANCHOR_X, vp.h*CAM_ANCHOR_Y)`; `setOpacity(row.opacity)` |
| 43884 | `FieldLayer` = `BatchedLayer`, `ignoreAnchorPointForPosition(false)`, cascade opacity |
| 43899 | layer content size = `(field:getWidth(), field:getHeight())` |
| 43903 | `updateViewportByTransform`: anchor = `((vp.x*per_x/1)/w, (vp.y*per_y/0.6 + vp.h*CAM_ANCHOR_Y)/h)` |
| 43885 | `field_getSprite`: `.scsp/.json/.skel` → `ur.Model('bg/'..spr, 'bg/'..atlas)` idle at `math.random()`; `.cfx` → particle effect; else `SpriteCache:getSprite(atlas..'/'..spr) or getSprite(spr)` |
| 43895 | `createInstance`: sprite anchor (0,0), `setScale(scale/FIELD_REDUCE_SCALE)`, size = content×scale/FRS; model anchor (0,0), `setPosition(0, size.h/2)`, `setScale(scale)`, size = `(vp.w*scale, vp.h*scale)`; `setColor(r,g,b)`; flip_h/flip_v → children `setRotationSkewY/X(180)`; `offset_x = row.x`, `offset_y = field_h − row.y − (size.h − child.y)` |
| 43892 | `calcPatternInfo`: `width == -1` → 1 instance at x 0; else `W = width*scale` (0 → size.w), `x0 = −vp.w/2`, `count = ceil(vp.w/W)*4 + 1` |
| 43911 / 43910 / 43888 | tiling: `inbounds = floor(|anchor.x*layer_w − offset_x| / W) − 2`, instance k = 1..count at `x0 + (inbounds + k − 1)*W`; `setPosition(offset_x + pattern_x, offset_y)` |
| 43938 | `makeField`: game_layer = `BatchedLayer(VIEW_W, VIEW_H)`, `ignoreAnchorPointForPosition(true)`, anchor `(CAM_ANCHOR_X, CAM_ANCHOR_Y)`, named `@field_game_layer` |
| 21290 | `UIBackground:init(parent, vp_idx, bg_col, scale_col, opts)`: `default_poses` (else `{0,0,VIEW_W/2}`), `default_scale` (else 1), alt columns |
| 21292 | `UIBackground:setBackground(item, prebake, rot)`: poses/scale primary → alt → default; `FIELD_NEW.create(bg, DESIGN_W*2)`; `lockViewPortRange(±2·DESIGN_W)`; game_layer anchor (0.5,0.5), `setPosition(rot and −x or x, rot and −y or y)`; `setViewPortPosition(poses[3])`; `bg:setRotation(rot)`; `game_layer:setScale(scale)`. Flat `.png` branch: `cc.Sprite`, anchor .5, at its own half-size, scale, rotation, no poses |
| 21293 | `useRATIOScale`: game_layer scale ×= `VIEW_W / DESIGN_W` |
| 23783 | `UnitZoom` init: `bg_landscape` = cols `bg_position_landscape/bg_scale_landscape`, alt `bg_position_hero/bg_scale_hero`, `default_scale 1.2`, `default_poses {0,0,0}`; `bg_portrait` = cols `bg_position/bg_scale`, `default_scale 3`, `default_poses {0,0,0}` |
| 23792 | `UnitZoom` apply: `Portrait` → `bg_portrait:setBackground(item, _, −90)` + `useRATIOScale`; else `bg_landscape:setBackground(item, _)` |
| 26354 | `UnitMain` (hero list): `bg_position_hero / bg_scale_hero`, `default_scale 1.2` |
| 21391 | Pet House: `bg_position_pet / bg_scale_pet` |

## Data facts

* `background.db` is a `YUNADBSET` filter over `background_tuto`, `background_main`,
  `background_sub_1..7`. There's no id overlap, so `DB('background', id)` is their union.
  `bg_field.load_background_set()` reads the filter list from the file.
* Each `.db` names its own columns in the `\t<i>` metadata rows. **Use them.** The
  old `bg_stage.py` hand labels were wrong: `[18]` is `anchor_y` (was "alpha"),
  `[19]`/`[20]` are `zoom_scale`/`per_x` (was "parallax"), and `[23]` is `scroll`
  (was "rotation"; the real `rotation` is `[33]`). So `bg_stage.py` rotated parts by
  their scroll speed.
* `item_material_bgpack.db` columns: `id, export_id, background_id, bg_scale,
  bg_position, bg_scale_landscape, bg_position_landscape, bg_scale_pet,
  bg_position_pet, bg_scale_hero, bg_position_hero, ambient_color, lobby,
  smart_bg_id`. `bg_position` is `"x,y,z"`: x,y = game_layer offset (negated in
  portrait), **z = field viewport x**, NOT a pan. That's why `sks_forest`'s
  `3600` looked like nonsense when treated as an offset.
* `ambient_color` is the custom-lobby UI theme colour (proto 13157), not a plate tint.

## The camera, as applied

Game-layer space p (y up) → screen q: `q = P + c + s·(p − c)`, c = (960, 540),
P = (x, y), or (−x, −y) in portrait. Field layer content (X, Y) → p:
`p = (vp.w/2 − vp.x·per_x + X, Y)`. The 0.2·vp.h terms cancel because vp.y = 0.
Upright window in q: landscape `[0,1920]×[0,1080]`; portrait (bg rotated −90 about
the screen centre) `[420,1500]×[−420,1500]`, 1080×1920.

Sanity check, from authored data only: `sks_forest` portrait (scale 1.8, y −50)
sees field y ≈ 34…1101, i.e. the 1188-unit field height. Every one of the first
eight plates came out at 100 % coverage with no framing search.

## Weighted meshes on merge

Weighted mesh vertices name bones **by index** into the skeleton's bone array.
Merging layers into one skeleton renumbers bones, so the indices have to be remapped
(`_remap_weights`). Without it the mesh binds to unrelated bones and stretches
across the plate (`tireil_4_garden` rows 6/8). `bg_stage.merge_layers` has the
same latent bug.

## Fail-closed gaps (reported, never guessed)

* `.cfx` rows: cocos particle systems, no engine. Skipped (~550 rows).
* `com1_*` layers are Spine 3.4.02, which no converter handles. Skipped.
* Model idle phase: the game uses `math.random()`, and we pin t=0.
* `smart_bg_id` packs (8): `BattleField:setChangeAnimation` layer scripts are not applied.
* Flat `bgpack/*.png` packs (5): the sprite goes under `UnitZoom`'s container,
  whose transform is not recovered yet. Not baked.
* `VIEW_WIDTH/HEIGHT` are never assigned offline. They equal DESIGN_* at 16:9
  (the baked frame), so `useRATIOScale` = 1.
* Layer opacity is cascade opacity on the whole layer; we apply it per slot.
  That's exact unless a model's own slots overlap.
* Empty `r/g/b` cells render white (cocos `c3b(nil)` behaviour unverified).
