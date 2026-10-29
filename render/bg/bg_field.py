"""Compose a Hero View "Background Pack" plate EXACTLY the way the game does.

This is a port of the game's own Lua (LuaJIT bytecode in game.bin, decrypted to
<dump>/_game_re/game_bin_decrypted.bin), not a fit to captures. Every
number below has a rank-1 source; proto indices are positions in that bundle's
proto stream (tools: _game_re/_lj_disasm.py; extended reader used to find
them: ktab/upvalue decoding, see docs/reference/bg_field.md).

Chain, outermost first (cocos2d-x node semantics):

  UnitZoom.setBackground(item, prebake, rot)   proto 23792
      Portrait ("Vertical View") -> bg_portrait:setBackground(item, _, -90)
                                    + useRATIOScale (x VIEW_WIDTH/DESIGN_WIDTH)
      Landscape                  -> bg_landscape:setBackground(item, _)
  UIBackground.create cols       proto 23783 (UnitZoom.init)
      portrait : bg_position / bg_scale,              default_scale 3
      landscape: bg_position_landscape / bg_scale_landscape,
                 alt bg_position_hero / bg_scale_hero, default_scale 1.2
      both     : default_poses {0, 0, 0}
  UIBackground:setBackground                    proto 21292
      poses = split(row[pos_col]) -> alt -> default;  scale likewise
      bg, field = FIELD_NEW.create(bg_id, DESIGN_WIDTH*2)
      field:lockViewPortRange(-2*DESIGN_WIDTH, 2*DESIGN_WIDTH)
      game_layer:setAnchorPoint(0.5, 0.5)
      game_layer:setPosition(rot and -x or x, rot and -y or y)
      field:setViewPortPosition(poses[3])         (viewport.x)
      bg:setRotation(rot);  game_layer:setScale(scale)
  FIELD_NEW.makeField / create                  protos 43938 / 43918
      game_layer = BatchedLayer VIEW_WIDTH x VIEW_HEIGHT, ignoreAnchorPointForPosition
      viewport = {x=0, y=0, width=DESIGN_WIDTH, height=DESIGN_HEIGHT, scale=1}
      one FieldTilePropLayer per background row, added in row order
  rows: DB('background', '<theme>_<n>'), n = 1..150   proto 43883
      background.db is a YUNADBSET over background_tuto/_main/_sub_1..7
      scale, x, y  *= MODEL_SCALE_FACTOR (= DESIGN_HEIGHT / MODEL_DESIGN_HEIGHT)
  addOneLayer                                   proto 43937
      Node('--rotation') at (0,0), setRotation(row.rotation); layer inside it,
      layer at (viewport.width*CAM_ANCHOR_X, viewport.height*CAM_ANCHOR_Y)
  updateViewportByTransform                     proto 43903
      layer content size = (field width, field height) = (2*DESIGN_W, 1.1*DESIGN_H)
      anchor = ((vp.x*per_x/1) / w, (vp.y*per_y/0.6 + vp.h*CAM_ANCHOR_Y) / h)
      (divisors 1 and 0.6 are the module's local upvalues, proto 43945 pc 39-40)
  FieldTilePropInstancePool.createInstance      proto 43895
      sprite: anchor (0,0), scale = row.scale / FIELD_REDUCE_SCALE, setColor(r,g,b)
              size = contentSize * scale / FIELD_REDUCE_SCALE
      model : Spine 'bg/<spr>' + 'bg/<atlas>', idle at a RANDOM time,
              anchor (0,0), position (0, size.h/2), scale = row.scale,
              size = (viewport.w*scale, viewport.h*scale)
      flip_h / flip_v -> child setRotationSkewY / X (180): mirror about the child's
              own origin
      offset_x = row.x
      offset_y = field_height - row.y - (size.h - child.y)
  calcPatternInfo / updatePosition / tiling     protos 43892 / 43888 / 43911
      width == -1 : one instance, pattern.x = 0
      else        : W = row.width*row.scale (0 -> size.w), x0 = -viewport.w/2,
                    count = ceil(viewport.w / W)*4 + 1,
                    inbounds = floor(|anchor.x*layer_w - offset_x| / W) - 2,
                    instance k=1..count at x0 + (inbounds + k - 1)*W
      instance position = (offset_x + pattern_x, offset_y)

Story scene backgrounds (THEME-keyed entry point, no pack offsets):
  story setup_bg (proto 47647 in game_bin_decrypted_20261007.bin, the story
  player's bg handler).  A beat's `bg` string is routed by plain string tests:
      contains ".png"/".webp" -> flat image `story/bg/<name>` (cc.Sprite)
      "special:" / ".cfx"     -> illust / particle cue
      otherwise               -> FIELD_NEW.create(<name>)  [pc120-124: the bare
                                 name is the background THEME, no width arg]
                                 field:setViewPortPosition(DESIGN_WIDTH * 0.5)
                                 [pc127-131; vy untouched]  then updateViewport()
  The returned `bg` node is the 1920x1080 cc.Layer made by FIELD_NEW.create
  (proto 48728: anchor (0,0), position (0,0)); the field branch never calls
  bg:setPosition (pc295-296 skip the pc297-303 setPosition, which only the
  special/.cfx branch runs) and there is no setScale on game_layer, so the
  story camera is the identity on game_layer space: window [0,1920]x[0,1080],
  scale 1, offset (0,0), viewport x = 960.  Same compose() math as the pack
  path, just a different frame (`story_frame()`).  Not recovered: the story
  scene's own `n_bg` csb node transform (assumed at the origin of a 16:9 UI
  layer, like VIEW == DESIGN below).

Fail-closed gaps (reported per plate, never guessed):
  * `.cfx` rows (cocos particle systems) — no particle engine here; skipped.
  * rows whose .scsp did not convert (e.g. 3.4.02) — skipped.
  * Spine idle phase: the game starts each model at a random time; we pin t=0.
  * smart_bg_id packs: BattleField:setChangeAnimation (layer on/off scripts)
    is not applied.
  * VIEW_WIDTH / VIEW_HEIGHT are never assigned in any offline artifact
    (s3_exact/docs/layout_constants.json). They equal DESIGN_* on a 16:9
    screen, which is the frame we bake; useRATIOScale is therefore 1.
"""
from __future__ import annotations

import argparse, json, math, os, re, shutil, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]   # repo root
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))          # repo root: makes e7lib importable
from e7lib.bootstrap import add_source_dirs  # noqa: E402
add_source_dirs(ROOT)
from e7lib.config import RAW_DIR, IMG_DIR, CDN_WORK_DIR  # noqa: E402
from e7lib.dbcrypto import cdbm_rows, outer_decrypt_db  # noqa: E402
DBDIR = RAW_DIR / "db"
RAW_BG = RAW_DIR / "bg"
IMG_BG = IMG_DIR / "bg"
LAYER_CACHE = CDN_WORK_DIR / "_bg_layers"
STAGE = ROOT / "site" / "assets" / "_bg_field"

# ---------------------------------------------------------------- constants
# rank 1 unless noted. s3_exact/docs/layout_constants.json carries the same.
DESIGN_W = 1920                 # init_resolution KN + FIT_*_LEGACY_FACTOR denominators
DESIGN_H = 1080
MODEL_DESIGN_HEIGHT = 640       # globals init proto 46479 pc56-57 (KSHORT 640)
MODEL_SCALE_FACTOR = DESIGN_H / MODEL_DESIGN_HEIGHT   # proto 46478 pc17-20
CAM_ANCHOR_X = 0.5              # proto 46478 pc40-41
CAM_ANCHOR_Y = 0.2              # proto 46478 pc42-43
FIELD_REDUCE_SCALE = 2 / 3      # proto 43945 pc0-1 (KNUM 0.6666666666666666)
PER_X_DIV = 1                   # proto 43945 pc39 (local 0, upvalue of 43901)
PER_Y_DIV = 0.6                 # proto 43945 pc40 (local 1, upvalue of 43901)
FIELD_W = DESIGN_W * 2          # proto 21292 pc140-142 create(bg, DESIGN_WIDTH*2); 43920
FIELD_H = DESIGN_H * 1.1        # proto 43923 getHeight default DESIGN_HEIGHT*1.1
VIEW_W, VIEW_H = DESIGN_W, DESIGN_H   # ASSUMED equal at 16:9 (see module doc)
RANGE_X = (-DESIGN_W * 2, DESIGN_W * 2)   # proto 21292 pc152-160 lockViewPortRange

MODES = {
    # proto 23783 pc77-88 / pc64-75; rotation from proto 23792 pc14 (KSHORT 65446 = -90)
    "portrait":  {"pos": "bg_position", "scale": "bg_scale",
                  "alt_pos": None, "alt_scale": None,
                  "default_scale": 3.0, "rotation": -90},
    "landscape": {"pos": "bg_position_landscape", "scale": "bg_scale_landscape",
                  "alt_pos": "bg_position_hero", "alt_scale": "bg_scale_hero",
                  "default_scale": 1.2, "rotation": None},
}


# ---------------------------------------------------------------- DB access

def _table(name: str) -> list[dict]:
    plain = outer_decrypt_db((DBDIR / f"{name}.db").read_bytes())
    meta = {k[1:].decode(): v for k, v in cdbm_rows(plain) if k.startswith(b"\t")}
    cols = [meta[str(i)].decode() for i in range(256) if str(i) in meta]
    rows = []
    for k, v in cdbm_rows(plain):
        if k.startswith(b"\t"):
            continue
        vals = [c.decode("utf-8", "replace") for c in v.split(b"\x00")]
        rows.append(dict(zip(cols, vals)))
    return rows


def load_background_set() -> dict[str, dict]:
    """DB('background', id): background.db is a YUNADBSET filter listing the
    shards it unions. Read that list instead of hard-coding it."""
    raw = (DBDIR / "background.db").read_bytes()
    shards = []
    if raw.startswith(b"YUNADBSET"):
        for line in raw.split(b"\n")[1:]:
            name = line.split(b"\t")[0].strip().decode()
            if name:
                shards.append(name)
    out: dict[str, dict] = {}
    for sh in shards:
        for r in _table(sh):
            if r.get("id"):
                out.setdefault(r["id"], r)
    return out


def load_packs() -> list[dict]:
    return [r for r in _table("item_material_bgpack") if r.get("id")]


def num(v, default=None):
    if v is None or v == "":
        return default
    try:
        return float(v)
    except ValueError:
        return default


# ---------------------------------------------------------------- atlases

def parse_atlas(path: Path) -> dict[str, dict]:
    """region -> {orig_w, orig_h} (cocos content size of a sprite frame)."""
    regions: dict[str, dict] = {}
    cur = None
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        if not line.startswith(" ") and ":" not in line:
            cur = line.strip()
            regions[cur] = {}
            continue
        if cur and line.startswith("  "):
            k, _, v = line.strip().partition(":")
            regions[cur][k] = v.strip()
    out = {}
    for name, r in regions.items():
        if "orig" not in r and "size" not in r:
            continue
        w, h = (int(x) for x in (r.get("orig") or r["size"]).split(","))
        out[name] = {"orig_w": w, "orig_h": h}
    return out


_ATLAS: dict[str, dict | None] = {}


def atlas(name: str) -> dict | None:
    if name not in _ATLAS:
        p = RAW_BG / f"{name}.atlas"
        _ATLAS[name] = parse_atlas(p) if p.exists() else None
    return _ATLAS[name]


def load_layer(stem: str) -> dict | None:
    p = LAYER_CACHE / f"{stem}.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


# ---------------------------------------------------------------- field rows

def field_layouts(theme: str, bgset: dict) -> tuple[list[dict], str | None]:
    """proto 43883: rows <theme>_1..150 in index order (the `layer` column is
    not read). bg_atlas comes from row _1."""
    first = bgset.get(f"{theme}_1") or {}
    bg_atlas = first.get("bg_atlas") or None
    rows = []
    for n in range(1, 151):
        r = bgset.get(f"{theme}_{n}")
        if not r or not r.get("spr"):
            continue
        lay = dict(r)
        lay["_n"] = n
        for k in ("scale", "x", "y"):
            v = num(r.get(k))
            lay[k] = None if v is None else v * MODEL_SCALE_FACTOR
        lay["width"] = num(r.get("width"), 0.0)
        rows.append(lay)
    return rows, bg_atlas


# ---------------------------------------------------------------- composition

def pack_frame(pack: dict, mode: str) -> dict:
    """proto 21292 pc36-124: poses + scale with primary -> alt -> default."""
    m = MODES[mode]

    def pick(col, alt):
        if pack.get(col):
            return pack[col]
        if alt and pack.get(alt):
            return pack[alt]
        return None

    pos_s = pick(m["pos"], m["alt_pos"])
    poses = [0.0, 0.0, 0.0]
    if pos_s:
        parts = pos_s.split(",")
        for i in range(min(3, len(parts))):
            poses[i] = num(parts[i], 0.0)
    sc = num(pick(m["scale"], m["alt_scale"]))
    scale = m["default_scale"] if sc is None else sc
    rot = m["rotation"]
    vx = min(max(poses[2], RANGE_X[0]), RANGE_X[1])   # proto 43932 math.clamp
    return {
        "mode": mode, "scale": scale, "rotation": rot,
        "pos": (-poses[0], -poses[1]) if rot else (poses[0], poses[1]),
        "vx": vx, "vy": 0.0,
        "source": {"pos": pos_s, "scale": pick(m["scale"], m["alt_scale"])},
    }


def story_frame() -> dict:
    """Story scene background camera (proto 47647 pc120-134, see module doc):
    FIELD_NEW.create(theme) + setViewPortPosition(DESIGN_WIDTH*0.5); bg layer at
    (0,0), game_layer unscaled/unoffset.  Landscape 1920x1080 window."""
    vx = DESIGN_W * 0.5
    # setViewPortPosition (proto 48722 pc44-63): with no lockViewPortRange the
    # x is clamped to [0, field width]; 960 is inside.
    vx = min(max(vx, 0.0), FIELD_W)
    return {"mode": "story", "scale": 1.0, "rotation": None, "pos": (0.0, 0.0),
            "vx": vx, "vy": 0.0,
            "source": {"pos": None, "scale": None, "proto": 47647}}


def window(frame: dict) -> dict:
    """The part of game_layer space the player sees, upright.

    Landscape: the 1920x1080 design screen. Portrait: bg is rotated -90 about
    its centre (cc.Layer, anchor 0.5) inside that same landscape screen, so the
    upright view is the screen rect rotated back about (960, 540)."""
    cx, cy = DESIGN_W / 2, DESIGN_H / 2
    if frame["rotation"] in (-90, 90, 270, -270):
        return {"x": cx - DESIGN_H / 2, "y": cy - DESIGN_W / 2,
                "width": DESIGN_H, "height": DESIGN_W}
    return {"x": 0, "y": 0, "width": DESIGN_W, "height": DESIGN_H}


def instances(lay: dict, size_w: float, vx: float) -> list[float]:
    """pattern_x of every instance the game positions (protos 43892/43911/43888)."""
    if lay["width"] == -1:
        return [0.0]
    W = lay["width"] * lay["scale"]
    if W == 0:
        W = size_w
    if W <= 0:
        return [0.0]
    x0 = -VIEW_W * 0.5
    count = math.ceil(VIEW_W / W) * 4 + 1
    per_x = num(lay.get("per_x"), 0.0) / PER_X_DIV
    left = vx * per_x - lay["x"]
    inb = math.floor(abs(left) / W) - 2
    return [x0 + (inb + k - 1) * W for k in range(1, count + 1)]


def compose(theme: str, frame: dict, bgset: dict, rows: set[int] | None = None) -> dict:
    """Merged Spine skeleton for one plate + an explicit camera window.
    `rows` (debug only) restricts the plate to those row indices."""
    lays, bg_atlas = field_layouts(theme, bgset)
    if rows:
        lays = [l for l in lays if l["_n"] in rows]
    report = {"theme": theme, "rows": len(lays), "skipped": [], "drawn": 0,
              "notes": []}
    s = frame["scale"]
    px, py = frame["pos"]
    cx, cy = VIEW_W / 2, VIEW_H / 2
    bones = [{"name": "root"},
             # game_layer: q = pos + c + s*(p - c)   (ignoreAnchorPointForPosition, anchor .5)
             {"name": "game", "parent": "root", "x": px + cx - s * cx,
              "y": py + cy - s * cy, "scaleX": s, "scaleY": s}]
    slots, atts, anims = [], {}, {"idle": {"bones": {}, "slots": {}}}
    pages: list[str] = []
    e7v21x = False

    for li, lay in enumerate(lays):
        spr = lay["spr"]
        tag = f"{lay['_n']}:{spr}"
        if lay["scale"] is None or lay["x"] is None or lay["y"] is None:
            report["skipped"].append((tag, "missing scale/x/y")); continue
        if spr.endswith(".cfx"):
            report["skipped"].append((tag, "cfx particle (no engine)")); continue
        per_x = num(lay.get("per_x"))
        if per_x is None:
            report["skipped"].append((tag, "missing per_x")); continue
        is_model = spr.endswith((".scsp", ".json", ".skel"))
        k = lay["scale"] if is_model else lay["scale"] / FIELD_REDUCE_SCALE
        fx = -1 if lay.get("flip_h") else 1
        fy = -1 if lay.get("flip_v") else 1
        rgb = [num(lay.get(c)) for c in ("r", "g", "b")]
        if any(v is None for v in rgb):
            report["notes"].append(f"{tag}: empty r/g/b -> white (c3b(nil) unverified)")
            rgb = [255 if v is None else v for v in rgb]
        op = num(lay.get("opacity"))
        alpha = 1.0 if op is None else op / 255.0
        color = "%02x%02x%02x%02x" % (int(rgb[0]), int(rgb[1]), int(rgb[2]),
                                      max(0, min(255, round(alpha * 255))))

        if is_model:
            stem = spr.rsplit(".", 1)[0]
            data = load_layer(stem)
            aname = (lay.get("atlas") or "").removesuffix(".atlas") or stem
            if data is None:
                report["skipped"].append((tag, "scsp not converted")); continue
            if atlas(aname) is None:
                report["skipped"].append((tag, f"atlas {aname} missing")); continue
            size_w, size_h = VIEW_W * lay["scale"], VIEW_H * lay["scale"]
            child_y = size_h / 2
        else:
            region = spr[:-4] if spr.endswith(".png") else spr
            aname = (lay.get("atlas") or "").removesuffix(".atlas") or bg_atlas
            reg = (atlas(aname) or {}).get(region) if aname else None
            if reg is None and bg_atlas and aname != bg_atlas:
                aname = bg_atlas
                reg = (atlas(aname) or {}).get(region)
            if reg is None:
                report["skipped"].append((tag, f"region {region} not in {aname}")); continue
            w, h = reg["orig_w"], reg["orig_h"]
            size_w, size_h = w * k, h * k
            child_y = 0.0
        if aname not in pages:
            pages.append(aname)
        offset_x = lay["x"]
        offset_y = FIELD_H - lay["y"] - (size_h - child_y)
        rot = num(lay.get("rotation"), 0.0)
        rb = f"r{li}"
        # Node('--rotation') at game_layer origin; cocos rotation is clockwise.
        bones.append({"name": rb, "parent": "game", "rotation": -rot})
        lb = f"l{li}"
        # FieldTilePropLayer: anchor point (vx*per_x, vy*per_y/0.6 + vh*0.2)
        # placed at (vw*0.5, vh*0.2)
        ax = frame["vx"] * per_x / PER_X_DIV
        ay = frame["vy"] * num(lay.get("per_y"), 0.0) / PER_Y_DIV + VIEW_H * CAM_ANCHOR_Y
        bones.append({"name": lb, "parent": rb,
                      "x": VIEW_W * CAM_ANCHOR_X - ax, "y": VIEW_H * CAM_ANCHOR_Y - ay})
        for ii, pxi in enumerate(instances(lay, size_w, frame["vx"])):
            ib = f"i{li}_{ii}"
            nx, ny = offset_x + pxi, offset_y
            if is_model:
                bones.append({"name": ib, "parent": lb, "x": nx, "y": ny + child_y,
                              "scaleX": fx * k, "scaleY": fy * k})
                pre = f"{li}_{ii}_"
                bmap = {}
                imap = {}          # layer bone index -> merged bone index
                for bi, b in enumerate(data.get("bones") or []):
                    nb = dict(b); nb["name"] = pre + b["name"]
                    bmap[b["name"]] = nb["name"]
                    nb["parent"] = bmap.get(b.get("parent"), ib)
                    imap[bi] = len(bones)
                    bones.append(nb)
                skin = next((sk for sk in data.get("skins") or []
                             if sk.get("name") in (None, "default")), None)
                satts = (skin or {}).get("attachments") or {}
                for sl in data.get("slots") or []:
                    ns = dict(sl); ns["name"] = pre + sl["name"]
                    ns["bone"] = bmap.get(sl.get("bone"), ib)
                    ns["color"] = _mul_color(sl.get("color"), color)
                    slots.append(ns)
                    if sl["name"] in satts:
                        atts[ns["name"]] = {an: _prefix_clip(_remap_weights(av, imap), pre)
                                            for an, av in satts[sl["name"]].items()}
                idle = (data.get("animations") or {}).get("idle") or {}
                for key in ("bones", "slots"):
                    for nm, tl in (idle.get(key) or {}).items():
                        anims["idle"][key][pre + nm] = tl
                # mesh FFD: offsets per vertex, independent of bone indices
                for sk_name, per_slot in (idle.get("deform") or {}).items():
                    if sk_name not in (None, "default"):
                        continue
                    dd = anims["idle"].setdefault("deform", {}).setdefault("default", {})
                    for nm, tl in per_slot.items():
                        dd[pre + nm] = tl
                if (data.get("skeleton") or {}).get("e7v21x"):
                    e7v21x = True
            else:
                bones.append({"name": ib, "parent": lb, "x": nx, "y": ny,
                              "scaleX": fx * k, "scaleY": fy * k})
                sn = f"s{li}_{ii}"
                slots.append({"name": sn, "bone": ib, "attachment": region,
                              "color": color})
                atts[sn] = {region: {"x": w / 2, "y": h / 2, "width": w,
                                     "height": h, "path": region}}
        report["drawn"] += 1

    skel = {
        "skeleton": {"hash": f"field-{theme}", "spine": "3.8.99", "x": 0, "y": 0,
                     "width": 0, "height": 0, "images": "", "audio": ""},
        "bones": bones, "slots": slots,
        "skins": [{"name": "default", "attachments": atts}],
        "animations": anims,
    }
    if e7v21x:
        skel["skeleton"]["e7v21x"] = True
    return {"skeleton": skel, "pages": pages, "window": window(frame),
            "frame": frame, "report": report}


def _prefix_clip(att: dict, pre: str) -> dict:
    """A clipping attachment names the slot that ends it; slots are prefixed."""
    if isinstance(att, dict) and att.get("type") == "clipping" and att.get("end"):
        return {**att, "end": pre + att["end"]}
    return att


def _remap_weights(att: dict, imap: dict[int, int]) -> dict:
    """Weighted vertices name bones by INDEX into the skeleton's bone list
    ([n, (bone, x, y, w) * n, ...]). Merging layers renumbers bones, so the
    indices must follow or the mesh binds to unrelated bones and stretches."""
    if not isinstance(att, dict) or att.get("type") not in ("mesh", "boundingbox",
                                                           "clipping", "path"):
        return att
    v = att.get("vertices") or []
    n_verts = att.get("vertexCount") or (len(att.get("uvs") or []) // 2)
    if not v or len(v) == n_verts * 2:
        return att                         # unweighted
    out = list(v)
    i = 0
    while i < len(out):
        n = int(out[i]); i += 1
        for _ in range(n):
            out[i] = imap.get(int(out[i]), int(out[i]))
            i += 4
    return {**att, "vertices": out}


def _mul_color(a: str | None, b: str) -> str:
    a = (a or "ffffffff").lower()
    if len(a) == 6:
        a += "ff"
    out = []
    for i in range(0, 8, 2):
        out.append(round(int(a[i:i+2], 16) * int(b[i:i+2], 16) / 255))
    return "".join("%02x" % v for v in out)


# ---------------------------------------------------------------- staging

def write_atlas(dst: Path, name: str, pages: list[str]) -> None:
    blocks = []
    for aname in pages:
        src = RAW_BG / f"{aname}.atlas"
        lines = src.read_text(encoding="utf-8", errors="replace").split("\n")
        while lines and not lines[0].strip():
            lines.pop(0)
        tex = f"{aname}.png"
        lines[0] = tex
        blocks.append("\n".join(lines).rstrip("\n"))
        t_src, t_dst = IMG_BG / tex, dst / tex
        if t_src.is_file() and not t_dst.exists():
            try:
                os.link(t_src, t_dst)
            except OSError:
                shutil.copy2(t_src, t_dst)
    (dst / f"{name}.atlas").write_text("\n" + "\n\n".join(blocks) + "\n",
                                       encoding="utf-8", newline="")


def stage(pack: dict, mode: str, bgset: dict, rows: set[int] | None = None,
          suffix: str = "") -> dict | None:
    theme = pack.get("background_id") or ""
    if not theme or theme.endswith(".png"):
        return None                       # flat bgpack sheet: separate path
    frame = pack_frame(pack, mode)
    comp = compose(theme, frame, bgset, rows)
    if not comp["skeleton"]["slots"]:
        return {"id": pack["id"], "mode": mode, "error": "nothing drawable",
                "report": comp["report"]}
    name = f"{pack['id']}__{mode}{suffix}"
    dst = STAGE / name
    dst.mkdir(parents=True, exist_ok=True)
    (dst / f"{name}.json").write_text(json.dumps(comp["skeleton"]), encoding="utf-8")
    write_atlas(dst, name, comp["pages"])
    meta = {"id": pack["id"], "mode": mode, "theme": theme, "name": name,
            "window": comp["window"], "frame": comp["frame"],
            "report": comp["report"], "smart_bg_id": pack.get("smart_bg_id") or None}
    (dst / "frame.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    return meta


def is_theme(theme: str, bgset: dict) -> bool:
    """A background THEME exists iff the db has drawable rows `<theme>_<n>`
    (the exact set the game's row loader, proto 43883, would read)."""
    return bool(theme) and bool(field_layouts(theme, bgset)[0])


def stage_theme(theme: str, bgset: dict, out: str | None = None,
                tag: str = "story") -> dict:
    """Stage one theme with the story camera as `<tag>__<theme>`.  `out` is the
    repo-relative base path (no extension) the baker should write the plate to."""
    frame = story_frame()
    comp = compose(theme, frame, bgset)
    rep = comp["report"]
    name = f"{tag}__{theme}"
    hard = [(t, why) for t, why in rep["skipped"] if not why.startswith("cfx")]
    meta = {"id": theme, "mode": "story", "theme": theme, "name": name,
            "window": comp["window"], "frame": comp["frame"], "report": rep,
            "out": out, "hard_skipped": hard}
    if not comp["skeleton"]["slots"]:
        meta["error"] = "nothing drawable"
        return meta
    dst = STAGE / name
    dst.mkdir(parents=True, exist_ok=True)
    (dst / f"{name}.json").write_text(json.dumps(comp["skeleton"]), encoding="utf-8")
    write_atlas(dst, name, comp["pages"])
    (dst / "frame.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    return meta


def write_frames() -> None:
    """site/data/bg_frames.json for the viewer's Background picker, one entry per
    pack that baked in BOTH modes (render/bg/render_bgfield.js output)."""
    out_dir = ROOT / "site" / "assets" / "_bg_field_out"
    baked = {(r["id"], r["mode"]): r for r in
             json.loads((out_dir / "_index.json").read_text(encoding="utf-8"))
             if not r.get("error")}
    names = {}
    bp = ROOT / "site" / "data" / "bg_packs.json"
    if bp.exists():
        names = {e["id"]: e.get("name") or "" for e in json.loads(bp.read_text(encoding="utf-8"))}
    staged = {(m["id"], m["mode"]): m for m in
              json.loads((STAGE / "_index.json").read_text(encoding="utf-8"))}
    frames, held = [], []
    for p in load_packs():
        L, P = baked.get((p["id"], "landscape")), baked.get((p["id"], "portrait"))
        if not (L and P):
            continue
        # Fail closed: a plate missing a layer that the game DOES draw (an
        # unconverted .scsp) is not the game's picture. Particles (.cfx) are a
        # known, uniform gap and do not hold a plate back.
        missing = [t for t, why in staged.get((p["id"], "landscape"), {}).get("report", {}).get("skipped", [])
                   if not why.startswith("cfx")]
        if missing:
            held.append((p["id"], missing[:3]))
            continue
        rel = "assets/_bg_field_out/"
        frames.append({
            "id": p["id"], "name": names.get(p["id"]) or p["id"],
            "scene": p.get("background_id"),
            "file": rel + L["name"] + ".webp", "thumb": rel + L["name"] + "_th.webp",
            "w": L["w"], "h": L["h"],
            "portrait": rel + P["name"] + ".webp",
            "portrait_thumb": rel + P["name"] + "_th.webp",
            "pw": P["w"], "ph": P["h"],
            "coverage": {"landscape": L["coverage"], "portrait": P["coverage"]},
            "skipped": max(L["skipped"], P["skipped"]),
        })
    (ROOT / "site" / "data" / "bg_frames.json").write_text(
        json.dumps(frames, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"wrote site/data/bg_frames.json: {len(frames)} packs; held back {len(held)}")
    for pid, why in held:
        print(f"  held {pid}: {why}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", action="store_true",
                    help="only write site/data/bg_frames.json from baked plates")
    ap.add_argument("ids", nargs="*", help="pack ids (default: all)")
    ap.add_argument("--mode", choices=list(MODES) + ["both"], default="both")
    ap.add_argument("--rows", help="debug: comma list of row indices; stages <id>__<mode>__rN")
    a = ap.parse_args()
    if a.frames:
        return write_frames()
    bgset = load_background_set()
    packs = load_packs()
    if a.ids:
        packs = [p for p in packs if p["id"] in set(a.ids)]
    modes = list(MODES) if a.mode == "both" else [a.mode]
    STAGE.mkdir(parents=True, exist_ok=True)
    index = []
    for p in packs:
        for m in modes:
            rows = {int(x) for x in a.rows.split(",")} if a.rows else None
            meta = stage(p, m, bgset, rows, f"__r{a.rows.replace(',', '-')}" if rows else "")
            if meta:
                index.append(meta)
                r = meta["report"]
                print(f"{meta['id']:<22} {m:<9} {r['theme']:<20} drawn {r['drawn']}/{r['rows']}"
                      f"  skipped {len(r['skipped'])}" + (f"  ERROR {meta['error']}" if meta.get('error') else ""))
    idx_path = STAGE / "_index.json"
    prev = json.loads(idx_path.read_text(encoding="utf-8")) if idx_path.exists() else []
    names = {m["name"] for m in index if "name" in m}
    index = [m for m in prev if m.get("name") not in names] + index
    idx_path.write_text(json.dumps(index, indent=1), encoding="utf-8")
    print(f"staged {len(index)} plates -> {STAGE.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
