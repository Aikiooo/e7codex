"""Stage E7 battle/stage backgrounds as single-skeleton Spine scenes.

A background in the dump is a *stack* of small Spine layer files that all share
one atlas + texture:

    output/bg/minetown.atlas   tiny PNG page (packed at 2/3 scale)
    output/bg/minetown.sct     the texture AssetRipper decoded to img_output
    output/bg/minetown_back.scsp, minetown_0.scsp … minetown_front.scsp

Each .scsp is a one- or few-slot skeleton sized in one shared authoring space, so
drawing them all at the same origin reproduces the in-game background. This tool
converts each layer to Spine 3.8 JSON (cache: --layers), merges the stack into a
SINGLE skeleton whose slot order is the draw order, and stages it under
site/assets/_bg_src/<name>/ as <name>.json + <name>.atlas + <name>.png — the
same shape the unit pipelines use, so the existing spine-player renderers and
site viewer can load it unchanged.

Layer→background assignment is by ATLAS REGION AFFINITY (a layer belongs to the
atlas whose region names it actually references), not by filename: layer names
and atlas names disagree often (bg/abyss1.scsp packs into abyss.atlas,
bg/forestatmosphere.scsp lifts region forest0, minetown2.atlas carries
abyss_light). Region affinity is the only rule that holds across the dump.

Usage:
    python render/bg/bg_stage.py                 # stage everything with a layer
    python render/bg/bg_stage.py --only arena minetown
    python render/bg/bg_stage.py --list          # inventory only, write nothing
"""
from __future__ import annotations

import argparse, collections, json, os, re, shutil, struct, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]   # repo root
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))          # repo root: makes e7lib importable
from e7lib.bootstrap import add_source_dirs  # noqa: E402
add_source_dirs(ROOT)
from e7lib.config import RAW_DIR, IMG_DIR, CDN_WORK_DIR  # noqa: E402
from e7lib.dbcrypto import cdbm_rows, outer_decrypt_db  # noqa: E402
RAW_BG = RAW_DIR / "bg"
IMG_BG = IMG_DIR / "bg"
LAYER_CACHE = CDN_WORK_DIR / "_bg_layers"
STAGE = ROOT / "site" / "assets" / "_bg_src"
OUT_JSON = ROOT / "site" / "data" / "backgrounds.json"

# ---------------------------------------------------------------- atlas parse

REGION_RE = re.compile(
    r"(?m)^(?P<name>[^\s:][^\n]*)\n"
    r"  rotate: (?P<rot>true|false)\n"
    r"  xy: (?P<x>\d+), (?P<y>\d+)\n"
    r"  size: (?P<w>\d+), (?P<h>\d+)\n"
)


def parse_atlas(path: Path) -> dict:
    """Return {region: {w, h}} plus the page size / image name."""
    text = path.read_text(encoding="utf-8", errors="replace").splitlines()
    image = text[0].strip()
    page = {}
    for line in text:
        if line.startswith("size: "):
            w, h = line[6:].split(",")
            page = {"w": int(w), "h": int(h)}
            break
    regions = {}
    for m in REGION_RE.finditer("\n".join(text)):
        regions[m.group("name").strip()] = {
            "rot": m.group("rot") == "true",
            "w": int(m.group("w")),
            "h": int(m.group("h")),
        }
    return {"image": image, "page": page, "regions": regions}


# ------------------------------------------------------------- layer refs

def layer_regions(data: dict) -> set[str]:
    """Atlas regions a converted layer references."""
    out: set[str] = set()
    for skin in data.get("skins", []) or []:
        for per_slot in (skin.get("attachments") or {}).values():
            for att in (per_slot or {}).values():
                if not att:
                    continue
                for key in ("path", "name"):
                    v = att.get(key)
                    if isinstance(v, str) and v:
                        out.add(v)
    return out


# ------------------------------------------------------------- draw order

# Rank = draw order, low behind high. Derived from the dump's own layer suffixes
# (back/sky -> 0s, digits -> 10s, props -> 40s, light/sun -> 60s, front -> 90s).
_SUFFIX_RULES: list[tuple[re.Pattern, int]] = [
    (re.compile(r"^back(\d*)$"), 0),
    (re.compile(r"^sky(\d*)$"), 4),
    (re.compile(r"^cloud_?([lr]?\d*)$"), 6),
    (re.compile(r"^(\d+)$"), 10),
    (re.compile(r"^land$"), 15),
    (re.compile(r"^floor$"), 16),
    (re.compile(r"^main$"), 18),
    (re.compile(r"^mid(\d*)$"), 20),
    (re.compile(r"^m(\d+)$"), 22),
    (re.compile(r"^b(\d+)$"), 24),
    (re.compile(r"^f(\d+)$"), 26),
    (re.compile(r"^(gate|gateway|door|pillar|cross|wall|fence|stairs|bridge)"), 40),
    (re.compile(r"^(tree|house|bush|rock|stone|torch|candle|chand|tent|flag|cannon|arrow|boat|bar|table|chair|egg|spider|waterfall|fish|bubble|duck|bird|bat|seal|chain|letter|monument|statue)"), 44),
    (re.compile(r"^(shadow|shade)"), 50),
    (re.compile(r"^(light|sun|glow|magic|mood|fire_light|front_?light)"), 64),
    (re.compile(r"^(effect|eff|spark|firework|smoke|dust|star|rain|snow|wind|storm|atmosphere|ambient|fog|bokeh)"), 72),
    (re.compile(r"^(ch|char|hero)"), 76),
    (re.compile(r"^(front|fg)"), 90),
]


def layer_rank(layer: str, base: str) -> tuple:
    suffix = layer[len(base):].lstrip("_") or layer
    for rex, r in _SUFFIX_RULES:
        m = rex.match(suffix)
        if m:
            tail = m.group(1) if m.groups() else ""
            n = int(tail) if tail.isdigit() else 0
            return (r, n, layer)
    return (55, 0, layer)          # unknown mid-depth, alphabetical


# ------------------------------------------------------------- merge

def merge_layers(name: str, layers: list[tuple[str, dict]], atlas_page: dict,
                 atlas_regions: set[str],
                 placements: list[dict | None] | None = None) -> tuple[dict, dict]:
    """Merge converted layer skeletons into one. Slot order == draw order.

    Attachments whose region is absent from the atlas (a layer placed by name
    kinship that actually lifts a region from a sibling page) are dropped along
    with their slot: spine refuses to load a skeleton referencing an unknown
    region, and one stray prop is not worth failing a whole background for.

    `placements[i]` wraps layer i in a container bone at (x, y) with scale /
    rotation — that is how db/background_main.db positions each part.
    """
    out_bones: list[dict] = []
    out_slots: list[dict] = []
    out_atts: dict[str, dict] = {}
    out_anims: dict[str, dict] = {}
    skipped: dict[str, int] = {}
    dropped: list[str] = []
    e7v21x = False

    for i, (lname, data) in enumerate(layers):
        pre = f"{i}_"
        keep_slots: set[str] = set()
        for skin in data.get("skins", []) or []:
            if skin.get("name") not in (None, "default"):
                continue
            for slot_name, per_slot in (skin.get("attachments") or {}).items():
                if not per_slot:
                    continue
                kept = {}
                for att_name, att in per_slot.items():
                    if not att:
                        continue
                    region = att.get("path") or att.get("name") or att_name
                    if atlas_regions and region not in atlas_regions:
                        continue
                    kept[att_name] = att
                if kept:
                    keep_slots.add(slot_name)
                    out_atts[pre + slot_name] = kept
        if not keep_slots:
            dropped.append(lname)
            continue

        place = placements[i] if placements else None
        cname = None
        if place:
            cname = f"c{i}"
            cb = {"name": cname, "x": place["x"], "y": place["y"],
                  "scaleX": place["scale"], "scaleY": place["scale"]}
            if place.get("rotation"):
                cb["rotation"] = place["rotation"]
            out_bones.append(cb)

        bmap = {}
        for b in data.get("bones", []) or []:
            nb = dict(b)
            nb["name"] = pre + b["name"]
            bmap[b["name"]] = nb["name"]
            if b.get("parent") in bmap:
                nb["parent"] = bmap[b["parent"]]
            elif cname:
                nb["parent"] = cname       # re-root the layer under its container
            else:
                nb.pop("parent", None)     # each layer's root stays a root
            out_bones.append(nb)

        for s in data.get("slots", []) or []:
            if s.get("name") not in keep_slots:
                continue
            ns = dict(s)
            ns["name"] = pre + s["name"]
            if s.get("bone") in bmap:
                ns["bone"] = bmap[s["bone"]]
            out_slots.append(ns)

        for anim_name, anim in (data.get("animations") or {}).items():
            tgt = out_anims.setdefault(anim_name, {})
            for key in ("bones", "slots"):
                for nm, tl in (anim.get(key) or {}).items():
                    if key == "slots" and nm not in keep_slots:
                        continue
                    tgt.setdefault(key, {})[pre + nm] = tl
            for key in ("drawOrder", "deform", "events", "attachments", "ffd"):
                if anim.get(key):
                    skipped[key] = skipped.get(key, 0) + 1

        # A 2.1.27 layer carries skeleton.e7v21x, the flag that switches
        # spine-player to 2.1.27 scalar (rather than matrix) scale inheritance.
        # The merged skeleton is a NEW block, so unless it is re-stated the
        # layers are drawn down the 3.8 path: children of a scaled bone (every
        # `scale: 2` backdrop layer has one) come out the wrong size.
        if (data.get("skeleton") or {}).get("e7v21x"):
            e7v21x = True

    if not out_anims:
        out_anims["idle"] = {}
    merged = {
        "skeleton": {
            "hash": f"bg-{name}",
            "spine": "3.8.99",
            "x": 0, "y": 0,
            "width": atlas_page.get("w", 0),
            "height": atlas_page.get("h", 0),
            "images": "", "audio": "",
        },
        "bones": out_bones,
        "slots": out_slots,
        "skins": [{"name": "default", "attachments": out_atts}],
        "animations": out_anims,
        "_bg": {"name": name, "layers": [ln for ln, _ in layers if ln not in dropped],
                "dropped": dropped, "skipped": skipped},
    }
    if e7v21x:
        merged["skeleton"]["e7v21x"] = True
    return merged, {"dropped": dropped, "slots": len(out_slots)}


# ------------------------------------------------- background_main.db

BG_DB = RAW_DIR / "db" / "background_main.db"


def load_bg_db() -> dict[str, list[dict]]:
    """The game's own composition table, scene -> ordered parts.

    Decoded with the shared YUNA/CDBM primitives from e7lib.dbcrypto
    (PLPcK outer-XOR, then a plaintext column row per record — this table needs
    no XXTEA pass). Schema of the 39 columns, as far as the pipeline uses them:

        [0]  id      <scene>_<n>              [8]  scale
        [1]  layer   draw order               [9]  x     (scene space)
        [5]  atlas   atlas name for a static part
        [6]  part    <region>.png  or  <layer>.scsp  or  <name>.cfx
        [7]  atlas   <atlas>.atlas for a .scsp part
        [18] alpha   [19][20] parallax            [23] rotation

    This is the authoritative part list: a scene's atlas holds regions that
    belong to OTHER scenes (the packer merges look-alike scenes into one page),
    so region ownership alone cannot recover a scene. 414 scenes, 7803 parts.
    """
    plain = outer_decrypt_db(BG_DB.read_bytes())
    out: dict[str, list[dict]] = {}
    for key, val in cdbm_rows(plain):
        if key.startswith(b"\t"):
            continue
        p = [c.decode("utf-8", "replace") for c in val.split(b"\x00")]
        if not any(p) or len(p) < 24:
            continue
        part = p[6]
        if part.endswith(".cfx"):
            continue                      # particle cue sheet — not a sprite
        scene = "_".join(p[0].split("_")[:-1])
        if not scene:
            continue
        try:
            rec = {
                "order": int(p[1]) if p[1].isdigit() else 0,
                "part": part,
                "atlas": (p[5].strip() or p[7].strip().removesuffix(".atlas")),
                "scale": float(p[8]) if p[8] else 1.0,
                "x": float(p[9]) if p[9] else 0.0,
                "y": float(p[10]) if p[10] else 0.0,
                "alpha": float(p[18]) if p[18] else 1.0,
                "rotation": float(p[23]) if p[23] else 0.0,
            }
        except ValueError:
            continue
        out.setdefault(scene, []).append(rec)
    for v in out.values():
        v.sort(key=lambda d: d["order"])
    return out


def static_layer(region: str, w: int, h: int) -> dict:
    """A one-slot skeleton that just draws an atlas region — the table's static
    parts (`b0.png`) have no .scsp of their own, only a name and a transform."""
    att = {"name": region, "path": region, "x": 0, "y": 0, "scaleX": 1, "scaleY": 1,
           "rotation": 0, "width": w, "height": h, "color": "FFFFFFFF"}
    return {
        "bones": [{"name": "root"}],
        "slots": [{"name": region, "bone": "root", "attachment": region}],
        "skins": [{"name": "default", "attachments": {region: {region: att}}}],
        "animations": {},
    }



def rewrite_atlas(src: Path, dst: Path, image_name: str) -> None:
    """Spine atlases name the texture on their first NON-BLANK line (the format
    opens with a blank line, which these files carry as a bare CRLF); point it
    at our PNG without disturbing the blank line or anything else."""
    lines = src.read_text(encoding="utf-8", errors="replace").split("\n")
    for i, line in enumerate(lines):
        if line.strip():
            lines[i] = image_name
            break
    dst.write_text("\n".join(lines), encoding="utf-8", newline="")


# ------------------------------------------------------------- inventory

def _norm(s: str) -> str:
    """Underscore-insensitive key. The dump spells a scene and its atlas
    inconsistently — layers `rta006_back` / `drptown_0` against atlases
    `rta_006` / `drp_town` — so the name hint has to ignore separators."""
    return s.replace("_", "").lower()


def _lead_token(stem: str) -> str:
    """Letters plus an optional leading digit run: `dis4_back` -> `dis4`."""
    m = re.match(r"[a-z]*\d*", _norm(stem))
    return m.group(0) if m and m.group(0) else _norm(stem)


def _subseq(tok: str, name: str) -> bool:
    it = iter(name)
    return all(ch in it for ch in tok)


def build_inventory() -> tuple[dict, list[str], dict, dict]:
    atlases = {}
    for p in sorted(RAW_BG.glob("*.atlas")):
        atlases[p.stem] = parse_atlas(p)
    norm_atlas: dict[str, list[str]] = {}
    for a in atlases:
        norm_atlas.setdefault(_norm(a), []).append(a)

    # How many atlases carry each region: the discriminator between a layer that
    # can only belong to one scene and one that shares a generic prop name
    # (`torch5` lives in 56 atlases, `temple3_light3` in 52).
    region_atlas_count: dict[str, int] = {}
    for at in atlases.values():
        for r in at["regions"]:
            region_atlas_count[r] = region_atlas_count.get(r, 0) + 1

    owners: dict[str, list[tuple[str, dict]]] = {k: [] for k in atlases}
    unmatched: list[str] = []
    stats = {"named": 0, "affinity": 0, "empty_refs": 0}
    for p in sorted(LAYER_CACHE.glob("*.json")):
        if p.name.startswith("_"):
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        stem = p.stem
        refs = layer_regions(data)
        if not refs:
            stats["empty_refs"] += 1

        # 1. The layer file is named after its scene: decisive, and the LONGEST
        #    matching atlas wins (abyss2 over abyss, rta_006 over rta_002).
        by_name = [(len(a), a) for a in norm_atlas.get(_norm(stem), [])]
        if not by_name:
            by_name = [(len(a), a) for a in atlases if _norm(stem).startswith(_norm(a))]
        if by_name:
            owners[max(by_name)[1]].append((stem, data))
            stats["named"] += 1
            continue

        # 2. Otherwise place it by REGION AFFINITY, and only when the evidence
        #    points at one atlas: every region it names resolves there, or the
        #    winner clearly dominates the runner-up. A layer built purely from
        #    names shared across dozens of atlases stays unassigned rather than
        #    being guessed into the wrong scene.
        if not refs:
            unmatched.append(stem)
            continue
        tok = _lead_token(stem)
        scores = []
        for aname, at in atlases.items():
            hits = refs & at["regions"].keys()
            if not hits:
                continue
            # IDF: a region carried by 60 atlases is almost no evidence, one
            # carried by a single atlas is decisive.
            idf = sum(1.0 / region_atlas_count.get(r, 999) for r in hits)
            scores.append((idf, _subseq(tok, _norm(aname)), aname))
        if not scores:
            unmatched.append(stem)
            continue
        scores.sort(key=lambda s: (s[1], s[0], -len(_norm(s[2])), s[2]), reverse=True)
        idf, kin, aname = scores[0]
        runner = scores[1][0] if len(scores) > 1 else 0.0
        # Assign on name kinship (the layer's leading token reads through the
        # atlas name: `dis1` -> dis_dimension1, `chg` -> chaosgate_01), or when
        # the winner owns a genuinely exclusive region AND beats the runner-up.
        # Anything else is shared-prop noise (`torch5`, `atmosphere`) and stays
        # out rather than being sprinkled into an arbitrary scene.
        if kin or (idf >= 1.0 and idf >= 1.5 * runner):
            owners[aname].append((stem, data))
            stats["affinity"] += 1
        else:
            unmatched.append(stem)

    out = {}
    for aname, items in owners.items():
        if not items:
            continue
        ordered = sorted(items, key=lambda t: layer_rank(t[0], aname))
        out[aname] = {
            "names": [n for n, _ in ordered],
            "raw": [d for _, d in ordered],
            "atlas": atlases[aname],
        }
    stats["unmatched"] = len(unmatched)
    return out, unmatched, atlases, stats


def load_layer(stem: str) -> dict | None:
    """Converted layer JSON from the cache (filled by render/bg/bg_convert_layers.py)."""
    global _LAYER_MEMO
    if stem in _LAYER_MEMO:
        return _LAYER_MEMO[stem]
    p = LAYER_CACHE / (stem + ".json")
    data = None
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            data = None
    _LAYER_MEMO[stem] = data
    return data


_LAYER_MEMO: dict[str, dict | None] = {}


def write_multi_atlas(scene: str, pages: list[str], atlases: dict, dst_dir: Path) -> None:
    """Write one Spine atlas holding a PAGE per source atlas the scene needs.

    A scene's parts are not all packed into the scene's own page: the background
    packer merged look-alike scenes, so `skn_castle` pulls from `rta_013.atlas`
    and `minetown2` carries `abyss_light`. Keeping only one page (which is what
    this tool used to do) silently drops every part whose region lives on
    another page — and the survivors then show up as hard-edged rectangles,
    because their neighbours are missing. Spine atlases are multi-page by
    design, so the fix is to concatenate the pages and hard-link each texture.
    """
    blocks = []
    for aname in pages:
        src = RAW_BG / f"{aname}.atlas"
        if not src.exists():
            continue
        lines = src.read_text(encoding="utf-8", errors="replace").split("\n")
        while lines and not lines[0].strip():     # the format opens with a blank line
            lines.pop(0)
        if not lines:
            continue
        tex_rel = f"{scene}__{aname}.png"
        lines[0] = tex_rel                        # the page's image name
        blocks.append("\n".join(lines).rstrip("\n"))
        tex_src = IMG_BG / f"{aname}.png"
        if not tex_src.is_file():
            continue
        dst = dst_dir / tex_rel
        try:
            if dst.exists():
                dst.unlink()
        except OSError:
            pass
        try:
            os.link(tex_src, dst)
        except OSError:
            shutil.copy2(tex_src, dst)
    (dst_dir / f"{scene}.atlas").write_text("\n" + "\n\n".join(blocks) + "\n",
                                            encoding="utf-8", newline="")


def build_inventory_from_db(atlases: dict, db: dict, y_sign: float = -1.0,
                            place: bool = True, kinds: tuple = ("png", "scsp"),
                            place_scsp: bool = False, scsp_mode: str = "scale") -> dict:
    """Compose each scene from background_main.db: the exact part list, in the
    exact draw order.

    Placement is applied to the STATIC parts only. A `.scsp` part is a Spine rig
    whose own bones already sit in scene space (that is why grouping a scene's
    `.scsp` layers at a common origin reproduced arena/minetown correctly long
    before this table was found); adding the row's x/y/scale on top would
    transform it twice. A `<region>.png` part has no rig of its own — it exists
    only as a region plus this row — so the row IS its transform.
    """
    out = {}
    region_owner: dict[str, str] = {}
    for aname, at in atlases.items():
        for r in at["regions"]:
            region_owner.setdefault(r, aname)

    for scene, parts in sorted(db.items()):
        counts = collections.Counter()
        for pt in parts:
            if pt["atlas"] in atlases:
                counts[pt["atlas"]] += 1
        if scene in atlases:
            counts[scene] += 1        # the scene name usually IS its atlas
        if not counts:
            # No part names an atlas and the scene has none of its own: fall back
            # to whichever atlas owns the first region we can resolve.
            for pt in parts:
                key = pt["part"][:-4] if pt["part"].endswith(".png") else None
                if key and key in region_owner:
                    counts[region_owner[key]] += 1
            if not counts:
                continue
        primary = counts.most_common(1)[0][0]

        # Resolve EVERY part to a page, primary first, so nothing is dropped.
        pages: list[str] = [primary]
        resolved: list[tuple[dict, str, str | None]] = []
        for pt in parts:
            part = pt["part"]
            if part.endswith(".scsp"):
                key, region = part[:-5], None
                page = pt["atlas"] if pt["atlas"] in atlases else primary
            elif part.endswith(".png"):
                region = part[:-4]
                key = region
                page = pt["atlas"] if pt["atlas"] in atlases else None
                if page is None or region not in atlases[page]["regions"]:
                    page = region_owner.get(region, primary)
            else:
                continue              # .cfx and anything else: not a sprite
            if page not in pages:
                pages.append(page)
            resolved.append((pt, key, region))
        at = atlases[primary]
        union_regions = set()
        for pg in pages:
            union_regions |= set(atlases[pg]["regions"])

        # A scene is built from ONE family. `<region>.png` parts are the scene's
        # painted layers and carry their transform in the table, so they compose
        # exactly. `.scsp` parts are the ANIMATED overlays (light shafts, fog,
        # dust): a scene made of them composes correctly too (arena, minetown,
        # battle2 are pure-scsp), but mixing the two families stacks the overlays
        # at full strength because the table's alpha/parallax columns are not
        # applied — so the majority family wins.
        #
        # Tried 2026-10-07 and REVERTED: letting a `.scsp`-majority scene also
        # take its `.png` parts, on the theory that dropping them punched holes
        # (tru_throne's `dungeon_5` floor plate was being dropped). It staged the
        # extra part but did NOT close tru_throne's uncovered wedges, so it was
        # churn without a verified gain — and it would have needed a full
        # re-render to keep the tree consistent. Re-test it per scene if a hole
        # is ever traced to a dropped static part.
        if kinds == ("auto",):
            n_png = sum(1 for p in parts if p["part"].endswith(".png"))
            n_scsp = sum(1 for p in parts if p["part"].endswith(".scsp"))
            use = ("png",) if n_png >= n_scsp else ("scsp",)
        else:
            use = kinds

        layers: list[tuple[str, dict]] = []
        places: list[dict | None] = []
        for pt, key, region in resolved:
            part = pt["part"]
            is_static = region is not None
            if not is_static and "scsp" not in use:
                continue
            if is_static and "png" not in use:
                continue
            if is_static:
                rg = None
                for pg in pages:
                    rg = atlases[pg]["regions"].get(region)
                    if rg:
                        break
                if not rg:
                    continue
                data = static_layer(region, rg["w"], rg["h"])
            else:
                data = load_layer(key)
            if data is None:
                continue
            layers.append((key, data))
            if not place:
                places.append(None)
            elif is_static:
                # A `<region>.png` part has no rig of its own: the row IS its
                # transform, position included.
                places.append({"x": pt["x"], "y": y_sign * pt["y"],
                               "scale": pt["scale"], "rotation": pt["rotation"]})
            elif scsp_mode == "full":
                places.append({"x": pt["x"], "y": y_sign * pt["y"],
                               "scale": pt["scale"], "rotation": pt["rotation"]})
            elif scsp_mode == "scale":
                # A `.scsp` part's own bones already sit in scene space (that is
                # why arena/minetown grouping at a common origin always looked
                # right), but its AUTHORED scale can differ from the scene's —
                # the table's `scale` is the correction (forest's effects are
                # authored ~7x too large). Its x/y is a parallax anchor, not a
                # position, so it must not be applied on top of the rig.
                places.append({"x": 0.0, "y": 0.0, "scale": pt["scale"],
                               "rotation": 0.0})
            else:
                places.append(None)
        if not layers:
            continue
        merged, info = merge_layers(scene, layers, at["page"], union_regions,
                                    places if place else None)
        out[scene] = {"names": [n for n, _ in layers], "merged": merged,
                      "atlas_name": primary, "pages": pages, "atlas": at, "info": info}
    return out


# ------------------------------------------------------------- main

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--min-layers", type=int, default=1)
    ap.add_argument("--affinity", action="store_true",
                    help="ignore background_main.db; group layers by name/region instead")
    ap.add_argument("--no-place", action="store_true",
                    help="use the db part list but not its x/y/scale containers")
    ap.add_argument("--y-sign", type=float, default=-1.0,
                    help="sign applied to the db's y (spine is y-up, the table is y-down)")
    ap.add_argument("--kinds", default="auto",
                    help="which db part kinds to include: auto (majority family), png, scsp")
    ap.add_argument("--place-scsp", action="store_true",
                    help="also wrap .scsp parts in their row's container")
    ap.add_argument("--scsp-scale", choices=("none", "scale", "full"), default="full",
                    help="how to apply a .scsp part's db row: 'none' ignores it, "
                         "'scale' applies only its scale, 'full' applies scale+x+y "
                         "(the default — see the module docstring)")
    a = ap.parse_args()

    atlases = {p.stem: parse_atlas(p) for p in sorted(RAW_BG.glob("*.atlas"))}

    if a.affinity:
        groups, unmatched, atlases, stats = build_inventory()
        scenes = {k: {"names": v["names"], "merged": None, "atlas_name": k,
                      "atlas": v["atlas"], "info": {}} for k, v in groups.items()}
        print(f"affinity grouping: {len(scenes)} scenes "
              f"(by name {stats['named']}, by region {stats['affinity']}, "
              f"unmatched {stats['unmatched']})")
    else:
        db = load_bg_db()
        scenes = build_inventory_from_db(atlases, db, y_sign=a.y_sign, place=not a.no_place,
                                        kinds=tuple(k.strip() for k in a.kinds.split(",") if k.strip()),
                                        place_scsp=a.place_scsp, scsp_mode=a.scsp_scale)
        # background_main.db covers 414 scenes; a handful of atlases have no row
        # at all (rta_020 and friends). Fall back to the name/region grouping for
        # exactly those, so nothing that already composed is lost.
        missing = set(atlases) - set(db)
        if missing:
            groups, _, _, stats_aff = build_inventory()
            added = 0
            for k, v in groups.items():
                if k in missing and k not in scenes:
                    scenes[k] = {"names": v["names"], "merged": None, "atlas_name": k,
                                 "atlas": v["atlas"], "info": {}}
                    added += 1
            print(f"  + {added} scenes from the name/region fallback "
                  f"({len(missing)} atlases have no db row)")
        unmatched, stats = [], {"db_scenes": len(db), "staged": len(scenes)}
        print(f"background_main.db: {len(db)} scenes, "
              f"{sum(len(v) for v in db.values())} parts -> {len(scenes)} composable, "
              f"placement={'off' if a.no_place else 'on'} y_sign={a.y_sign:g}")

    if a.list:
        for k in sorted(scenes, key=lambda k: -len(scenes[k]["names"])):
            print(f"  {len(scenes[k]['names']):3d}  {k}")
        return

    STAGE.mkdir(parents=True, exist_ok=True)
    index = []
    staged = 0
    for name in sorted(scenes):
        if a.only and name not in a.only:
            continue
        g = scenes[name]
        if len(g["names"]) < a.min_layers:
            continue
        tex_src = IMG_BG / f"{g['atlas_name']}.png"
        if not tex_src.is_file():
            print(f"  skip {name}: no texture {tex_src.name}")
            continue
        d = STAGE / name
        d.mkdir(parents=True, exist_ok=True)
        merged = g["merged"]
        if merged is None:
            merged, minfo = merge_layers(
                name, [(n, load_layer(n) or {}) for n in g["names"]],
                g["atlas"]["page"], set(g["atlas"]["regions"]))
        else:
            minfo = g["info"]
        # compressed like the other staged spine JSON (build_index/prepare_assets style)
        (d / f"{name}.json").write_text(
            json.dumps(merged, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        # One atlas, one page per source atlas the scene draws from — hard-linked
        # textures, so staging does not duplicate the dump's PNGs.
        write_multi_atlas(name, g.get("pages") or [g["atlas_name"]], atlases, d)
        index.append({"name": name, "atlas": g["atlas_name"],
                      "pages": g.get("pages") or [g["atlas_name"]],
                      "layers": len(merged["_bg"]["layers"]),
                      "dropped": len(merged["_bg"]["dropped"])})
        staged += 1
        if staged % 50 == 0:
            print(f"  staged {staged}", flush=True)

    print(f"staged {staged} backgrounds")
    (STAGE / "_inventory.json").write_text(
        json.dumps({"staged": index,
                    "groups": {k: v["names"] for k, v in scenes.items()},
                    "no_layers": sorted(set(atlases) - {v["atlas_name"] for v in scenes.values()}),
                    "unmatched_layers": sorted(unmatched)[:500],
                    "stats": stats},
                   indent=1, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
