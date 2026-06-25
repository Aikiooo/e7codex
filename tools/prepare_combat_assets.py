"""
Stage E7 combat rigs (output/model/) into site/assets/<slug>/combat/.

Combat rigs ship the skill1/skill2/skill3/run/knock_down/rise animations
the lobby/portrait rigs lack. They are char-name keyed (abigail.scsp), not
c#### keyed, so we resolve each filename to a c-slug via HeroDatabase.json.

For each mapped (and 3.8.99) rig, produces:
  site/assets/<cslug>/combat/<cslug>.json   Spine JSON
  site/assets/<cslug>/combat/<cslug>.atlas  atlas with .sct → .png rewrite
  site/assets/<cslug>/combat/<cslug>.png    decoded texture
  site/assets/<cslug>/combat/<cslug>.timeline   (optional — copied if exists)

Both Spine versions are staged. 2.1.27 dispatches to convert_2_1 +
post_process_2_1_27 (spine-player 3.8 compatibility patches); 3.8.99
dispatches to convert_3_8 directly. The 2.1.27 path was unblocked
2026-05-22 by decoding modes 9/10 and skipping per-animation trailers
via scan-forward — see [[project-e7-2127-mode9-blocker]] in memory.

Usage:
  python prepare_combat_assets.py [--all] [--stems abigail harsetti] [--force]
  python prepare_combat_assets.py --report   # print mapping/version table, no staging
"""
from __future__ import annotations
import argparse, json, re, shutil, sys, traceback
from pathlib import Path

THIS  = Path(__file__).resolve()
REPO  = THIS.parents[1]
ROOT  = REPO.parent
SITE  = REPO / "site" / "assets"

sys.path.insert(0, str(THIS.parent))
from paths import RAW_DIR  # central data-dir config
MODEL = RAW_DIR / "model"
from decode_sct import decode_one as decode_sct
import scsp_to_json


# Suffix peeling: combat-rig stems use underscore-separated variants
# (abigail_m, harsetti_s01) parallel to our site/assets c-slug suffixes
# (c1144_m, c1153_s01). Order longest-first so 'm_s01' wins over 'm'.
SUFFIX_PEEL = [
    "_m_s01", "_a01", "_m2", "_m", "_s01", "_s02", "_t",
    "_busking", "_trans", "_evil", "_specter", "_c",
]

# Residual manual overrides — combat-rig stems the DB model-map AND the kebab
# lookup both miss. Everything else (romanizations like victorica/wildred, ML &
# seasonal forms like ras_m/iseria_a01, collab bare-names, internal codenames
# like torami, and _m_s01 skins-of-ML) is now resolved authoritatively from the
# DB model-map — character_player.db col[20], via load_db_model_map() in
# map_stem(). The ~110 hand-curated entries this file used to carry collapsed
# into that one lookup; only these three lack a DB col[20] row:
STEM_OVERRIDE: dict[str, str] = {
    "flan_m":     "c2110",      # Pirate Captain Flan  — in no player DB (base/grade2/grade3)
    "flan_m_s01": "c2110_s01",  # skin of Pirate Captain Flan — in no player DB
    "ludwig_a01": "c5069",      # Aubade Ludwig — in no player DB
}
# (The elemental Adin / Inheritor Amiki overrides that briefly lived here on
# 2026-05-29 were removed once build_names.py started reading the grade3 player
# table: character_player_grade3.db col[20] maps c4141-4144→adin_<element> and
# c4158→amiki_c directly, so the DB layer resolves them — see "Combat rig
# recovery" in CLAUDE.md + docs/TASKS.md #39b.)
# (SPELLING_ALIAS removed 2026-05-29.) The dump's romanizations were a "fix the
# kebab" workaround; col[20] IS the real filename, so the DB layer resolves them
# directly with nothing to correct.

# Dual-rig units: one c-slug whose combat is TWO separate full rigs in the dump.
# c2185_1 "Rhianna and Luciella" ships rhianna_m + luciella_m — both complete
# 3.8.99 combat rigs (skill1/2/3, run, knock_down, …), but neither maps via the
# DB/kebab (the unit is in no player DB, and the rigs carry the auxiliary `_m`
# name with no base sibling). Staged side-by-side in the unit's combat/ dir: the
# FIRST is the primary (file == <cslug>.json, so the default viewer load + the
# has_combat check still work), the rest get <cslug>__<label>.json. A
# combat/rigs.json manifest drives the viewer's rig switcher. Order = display
# order; first entry loads by default.
DUAL_COMBAT: dict[str, list[tuple[str, str]]] = {
    "c2185_1": [("rhianna_m", "Rhianna"), ("luciella_m", "Luciella")],
}

# PRIMARY_SWAP entries — keep in sync with build_index.py:PRIMARY_SWAP.
# For these slugs the bare c#### directory holds the backdrop rig and the
# character lives at <slug>_1. Combat rigs (which animate the character,
# not the backdrop) must be routed to the _1 staging dir so the detail
# page picks them up. Without this redirect, units.json never sees the
# combat rig because the bare slug is rolled up as an "extra" and the
# _1 entry has no combat/ subdir to flag has_combat on.
PRIMARY_SWAP_BARE = {
    "c1046_s02", "c1180", "c1183", "c2076", "c2112_s01",
    "c2181", "c2184", "c2185", "c6024",
    # 2026-06-25 release backdrop-swaps (keep in sync with build_index.PRIMARY_SWAP):
    # routes their combat rig into the _1 sibling so has_combat surfaces on the
    # character, not the demoted backdrop.
    "c5147", "c2113_s01",
}

# Stems we KNOW the dump doesn't carry enough atlas data to render
# usefully. The 3.8.99 converter still emits a parseable .json/.atlas
# pair, but a large fraction of the region attachments reference
# atlas regions that aren't in the .sct (probably an AssetRipper
# extraction gap). Even with the orphan-attachment patcher dropping
# the unresolvable references, the visible rig is broken — setup-pose
# slots are blank and animations are missing limb/clothing swaps.
# Better to skip than ship a broken viewer.
INCOMPATIBLE_STEMS = {
    # (empty) — robin was removed 2026-05-29. Its combat atlas in the dump was
    # STALE (declared size 795x246, 128 regions) while the dump's robin.sct
    # texture is the current 1194x249 page with all parts. The "missing" 26
    # region attachments were never absent from the source texture — only from
    # the stale .atlas. The current data.pack ships a matching atlas
    # (1194x249, 155 regions); it was re-extracted into the dump and the rig
    # now renders cleanly. Decode was never the problem (decode_sct is
    # byte-exact for robin.sct). See docs/TASKS.md #39b.
}


def load_kebab_to_cslug() -> dict[str, str]:
    hdb_path = REPO / "data_external" / "HeroDatabase.json"
    hdb = json.loads(hdb_path.read_text(encoding="utf-8"))
    return {k: v["id"] for k, v in hdb.items()}


_DB_MODEL_MAP: dict[str, list[str]] | None = None


def load_db_model_map() -> dict[str, list[str]]:
    """Inverse of character_player.db col[20]: combat-rig stem -> [c-slugs that
    use it]. Built by tools/build_names.py into data_external/model_map_from_db.json
    (which excludes unreleased units). This is the AUTHORITATIVE source for hero
    rig names — handles romanizations, ML/seasonal forms, and internal codenames
    the ceciliabot kebab can't. Cached; returns {} if the file isn't present
    (then map_stem just falls back to kebab + suffix-peel)."""
    global _DB_MODEL_MAP
    if _DB_MODEL_MAP is None:
        p = REPO / "data_external" / "model_map_from_db.json"
        inv: dict[str, list[str]] = {}
        if p.exists():
            for cslug, model in json.loads(p.read_text(encoding="utf-8")).items():
                inv.setdefault(model, []).append(cslug)
        _DB_MODEL_MAP = inv
    return _DB_MODEL_MAP


_ATTR_MAP: dict[str, str] | None = None
ELEMENTS = {"fire", "ice", "wind", "light", "dark"}


def load_attributes() -> dict[str, str]:
    """c-slug -> attribute (fire/ice/wind/light/dark), from names_from_db.json.
    Used to pick the right element skin on the shared soldier/monster combat
    rigs (see merge_element_skin)."""
    global _ATTR_MAP
    if _ATTR_MAP is None:
        p = REPO / "data_external" / "names_from_db.json"
        m: dict[str, str] = {}
        if p.exists():
            for cslug, rec in json.loads(p.read_text(encoding="utf-8")).items():
                a = rec.get("attribute")
                if a in ELEMENTS:
                    m[cslug] = a
        _ATTR_MAP = m
    return _ATTR_MAP


def merge_element_skin(json_path: Path, attribute: str | None) -> int:
    """Several old 3★/4★ units share generic class/element soldier rigs
    (`onehanded_wind`, `axe_fire`, `meca_golem`, …) whose body lives in an
    element-NAMED skin (`fire`/`ice`/`wind`/`light`/`dark`), not in `default`
    (which is just a sparse base: shadow + a couple of shared pieces). The live
    viewer renders the `default` skin, so without this the rig shows shadow-only.

    Fix: merge the appropriate element skin's attachments into `default` so the
    combat JSON is self-contained (no viewer/skin-picker change needed). Target
    element = the unit's `attribute` when an element skin of that name exists,
    else the sole element skin if there's exactly one. Idempotent (re-merging the
    same attachments is a no-op). Returns the number of attachments merged.
    Single-skin rigs and rigs with no element-named skin are untouched."""
    data = json.loads(json_path.read_text(encoding="utf-8"))
    skins = data.get("skins")
    if not skins:
        return 0
    # 3.8 JSON skins are a list [{name, attachments}]; tolerate the dict form too.
    if isinstance(skins, dict):
        names = list(skins.keys())
        get_att = lambda n: skins.get(n) or {}
    else:
        byname = {s["name"]: s for s in skins}
        names = list(byname.keys())
        get_att = lambda n: byname[n].get("attachments", {})
    if "default" not in names:
        return 0
    elem = [n for n in names if n in ELEMENTS]
    if not elem:
        return 0
    if attribute in elem:
        tgt = attribute
    elif len(elem) == 1:
        tgt = elem[0]
    else:
        return 0  # multiple element skins, no attribute hint — leave alone
    dft, src = get_att("default"), get_att(tgt)
    added = 0
    for slot, atts in src.items():
        d = dft.setdefault(slot, {})
        for an, av in atts.items():
            d[an] = av
            added += 1
    if added:
        json_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return added


def _resolve(cslug: str, staged: set[str]) -> str | None:
    """If cslug is a PRIMARY_SWAP backdrop, redirect to its _1 sibling.
    Returns the staged slug or None."""
    if cslug in PRIMARY_SWAP_BARE:
        x1 = cslug + "_1"
        return x1 if x1 in staged else None
    return cslug if cslug in staged else None


def map_stem(stem: str, kebab_map: dict[str, str], staged: set[str],
             db_map: dict[str, list[str]] | None = None) -> str | None:
    """Map a combat-rig stem to a staged c-slug. Returns None if unmappable
    or the target slug isn't in site/assets/.

    Resolution order: explicit override -> npc/m9/pet/af prefix -> ceciliabot
    kebab -> autoslayer c-token -> DB model-map (col[20]) -> suffix-peel guess.
    The kebab lookup stays AHEAD of the DB map on purpose: a few item/scroll
    entities share a hero's rig under a `d####` c-slug (e.g. the DB ties `adin`
    to d3143 "Adin's Secret Scroll"), and kebab gets the real hero card first."""
    if db_map is None:
        db_map = load_db_model_map()

    if stem in STEM_OVERRIDE:
        return _resolve(STEM_OVERRIDE[stem], staged)

    # Direct npc/m/pet/af prefix (already in c-slug form)
    if stem in staged and re.match(r"^(npc|m9|pet_|af)\d", stem):
        return stem

    # Direct kebab lookup
    kebab = stem.replace("_", "-")
    if kebab in kebab_map:
        return _resolve(kebab_map[kebab], staged)

    # autoslayer_c2124 etc — c-slug embedded in token
    for tok in stem.split("_"):
        if tok.startswith("c") and tok[1:].isdigit():
            r = _resolve(tok, staged)
            if r:
                return r

    # DB model-map — authoritative for hero rigs the kebab missed
    # (romanizations / ML / seasonal / internal codenames). Heroes/skins only
    # (c-prefix); the d-prefix item entities sharing a rig are skipped.
    for cslug in db_map.get(stem, ()):
        if re.match(r"^c\d", cslug):
            r = _resolve(cslug, staged)
            if r:
                return r

    # Peel suffix, lookup base kebab, append suffix to base c-slug (last resort)
    for suf in SUFFIX_PEEL:
        if stem.endswith(suf):
            base = stem[: -len(suf)]
            base_kebab = base.replace("_", "-")
            if base_kebab in kebab_map:
                return _resolve(kebab_map[base_kebab] + suf, staged)
            if base in STEM_OVERRIDE:
                return _resolve(STEM_OVERRIDE[base] + suf, staged)
    return None


def stage_atlas(src_atlas: Path, dst_atlas: Path, png_name: str) -> None:
    out, swapped = [], False
    for line in src_atlas.read_text(encoding="utf-8").splitlines():
        if not swapped and line.strip().endswith(".sct"):
            out.append(png_name)
            swapped = True
        else:
            out.append(line)
    dst_atlas.write_text("\n".join(out) + "\n", encoding="utf-8")


def _parse_atlas_regions(atlas_path: Path) -> set[str]:
    """Extract atlas region names. A region line is non-blank, doesn't
    contain a colon (which marks attribute lines), and isn't the page
    filename header."""
    regions = set()
    for line in atlas_path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or ":" in s:
            continue
        if s.endswith((".png", ".jpg", ".jpeg", ".atlas")):
            continue
        regions.add(s)
    return regions


def patch_orphan_attachments(json_path: Path, atlas_path: Path) -> tuple[int, int]:
    """Fix attachments that reference atlas regions that don't exist.

    Two cases handled:

    1. **Linkedmesh redirect.** spine-player 3.8 resolves a linkedmesh's
       atlas region from its `path` field, defaulting to the attachment
       name when `path` is absent. When the converter omits `path` and
       the attachment name doesn't exist as a region (e.g.
       c1153_s01/combat's `leg_3_reverse2`, parent `leg_3` IS in the
       atlas), spine-player fails with "Region not found in atlas".
       Fix: set `path = parent_path` so the linkedmesh shares the
       parent's region.

    2. **Region/mesh deletion.** Some combat rigs reference region
       attachments whose textures were never extracted into the atlas
       (e.g. c1169/combat Robin has 25 hand/coat/etc. attachments
       missing — `hand_6b`, `hand_8`, `mouth_2`, etc.). These look like
       skill-swap textures that the AssetRipper dump lost. Without
       these regions spine-player aborts the whole skeleton load.
       Fix: drop the orphan attachments from the skin so the rest of
       the rig still renders. Animations that needed those swaps will
       show empty slots (visual gaps) but the base pose and most
       motions remain.

    Returns (linkedmesh_patched, region_dropped).
    """
    regions = _parse_atlas_regions(atlas_path)
    data = json.loads(json_path.read_text(encoding="utf-8"))
    skins = data.get("skins", [])

    def find_parent(skin_name: str, slot: str, parent_name: str) -> dict | None:
        for s in skins:
            if s.get("name") != skin_name:
                continue
            atts = s.get("attachments", {}).get(slot, {})
            return atts.get(parent_name)
        return None

    linked_patched = 0
    region_dropped = 0
    # Track which (skin, slot, attachment_name) we removed so we can prune
    # the matching animation references below. Without this pass, dropping
    # a skin attachment leaves dangling deform timelines and slot-swap
    # keyframes pointing at it; spine-player errors at load with
    # "Deform attachment not found: undefined".
    dropped_keys: set[tuple[str, str, str]] = set()

    for skin in skins:
        for slot_name, slot_atts in list(skin.get("attachments", {}).items()):
            for att_name in list(slot_atts.keys()):
                att = slot_atts[att_name]
                t = att.get("type")
                if t == "linkedmesh":
                    if "path" in att:
                        continue
                    if att_name in regions:
                        continue
                    parent_name = att.get("parent")
                    parent_skin = att.get("skin", "default")
                    if not parent_name:
                        continue
                    parent = find_parent(parent_skin, slot_name, parent_name)
                    if parent is None:
                        continue
                    parent_path = parent.get("path", parent_name)
                    if parent_path not in regions:
                        continue
                    att["path"] = parent_path
                    linked_patched += 1
                elif t in (None, "region", "mesh"):
                    # Default type is "region" when absent.
                    path = att.get("path", att_name)
                    if path in regions:
                        continue
                    del slot_atts[att_name]
                    dropped_keys.add((skin.get("name", ""), slot_name, att_name))
                    region_dropped += 1
            if not slot_atts:
                del skin["attachments"][slot_name]

    # Prune animation timelines that reference dropped attachments.
    # Whether an attachment_name is "dropped" depends on the skin context
    # for deform timelines, but slot.attachment keyframes are skin-agnostic
    # so we collapse to attachment names dropped in any skin and check
    # against every remaining (slot, name) pair.
    if dropped_keys:
        dropped_names_per_slot: dict[str, set[str]] = {}
        for _skin, slot, name in dropped_keys:
            dropped_names_per_slot.setdefault(slot, set()).add(name)
        # Build the set of (slot, attachment_name) still present in ANY skin
        # so we can confirm a swap keyframe really points at nothing.
        remaining_slot_names: set[tuple[str, str]] = set()
        for s in skins:
            for slot, atts in s.get("attachments", {}).items():
                for n in atts.keys():
                    remaining_slot_names.add((slot, n))

        for anim_name, anim in list(data.get("animations", {}).items()):
            # Deform timelines: deform[skin][slot][attachment] -> frames
            deform = anim.get("deform")
            if isinstance(deform, dict):
                for skin_name, skin_data in list(deform.items()):
                    for slot, slot_data in list(skin_data.items()):
                        for att in list(slot_data.keys()):
                            if (skin_name, slot, att) in dropped_keys:
                                del slot_data[att]
                        if not slot_data:
                            del skin_data[slot]
                    if not skin_data:
                        del deform[skin_name]
                if not deform:
                    del anim["deform"]
            # Slot attachment timelines: slots[slot].attachment[] keyframes
            slots_block = anim.get("slots")
            if isinstance(slots_block, dict):
                for slot, slot_data in list(slots_block.items()):
                    att_tl = slot_data.get("attachment")
                    if isinstance(att_tl, list):
                        new_tl = []
                        for frame in att_tl:
                            name = frame.get("name")
                            if name is None or (slot, name) in remaining_slot_names:
                                new_tl.append(frame)
                            else:
                                # Replace orphan keyframe with a "clear" frame —
                                # spine-player hides the slot at that time.
                                new_tl.append({**frame, "name": None})
                        if new_tl:
                            slot_data["attachment"] = new_tl
                        else:
                            del slot_data["attachment"]
                    if not slot_data:
                        del slots_block[slot]
                if not slots_block:
                    del anim["slots"]

    if linked_patched or region_dropped:
        json_path.write_text(json.dumps(data), encoding="utf-8")
    return linked_patched, region_dropped


# Back-compat alias for any external callers.
def patch_orphan_linkedmeshes(json_path: Path, atlas_path: Path) -> int:
    l, _ = patch_orphan_attachments(json_path, atlas_path)
    return l


def stage_combat(stem: str, cslug: str, version: str | None, force: bool = False,
                 out_name: str | None = None) -> tuple[bool, str]:
    """Stage one combat rig. Returns (ok, note). `version` is the pre-detected
    spine version ("3.8.99" or "2.1.27"); pass None to detect lazily.
    `out_name` is the basename of the staged files (default == cslug); pass a
    distinct name to stage a secondary rig of a DUAL_COMBAT unit alongside the
    primary <cslug>.json without clobbering it."""
    out_name = out_name or cslug
    scsp  = MODEL / f"{stem}.scsp"
    atlas = MODEL / f"{stem}.atlas"
    sct   = MODEL / f"{stem}.sct"
    timeline = MODEL / f"{stem}.timeline"

    if not (scsp.exists() and atlas.exists() and sct.exists()):
        return False, f"missing source files for {stem}"

    dst_dir   = SITE / cslug / "combat"
    dst_json  = dst_dir / f"{out_name}.json"
    dst_atlas = dst_dir / f"{out_name}.atlas"
    dst_png   = dst_dir / f"{out_name}.png"
    dst_tl    = dst_dir / f"{out_name}.timeline"
    dst_dir.mkdir(parents=True, exist_ok=True)

    if force or not dst_json.exists():
        v = version or scsp_to_json.detect_version(scsp)
        if v == "3.8.99":
            ok = scsp_to_json.convert_3_8(scsp, dst_json)
        elif v == "2.1.27":
            ok = scsp_to_json.convert_2_1(scsp, dst_json)
            if ok:
                scsp_to_json.post_process_2_1_27(dst_json)
        else:
            return False, f"unknown spine version for {stem}"
        if not ok:
            return False, f"convert_{v.replace('.', '_')} failed for {stem}"

    if force or not dst_png.exists():
        decode_sct(sct, dst_png)

    if force or not dst_atlas.exists():
        stage_atlas(atlas, dst_atlas, f"{out_name}.png")

    if timeline.exists() and (force or not dst_tl.exists()):
        shutil.copy2(timeline, dst_tl)

    # Orphan attachment fixup — runs after both JSON and atlas exist.
    linked, dropped = patch_orphan_attachments(dst_json, dst_atlas)
    # Element-skin merge for shared soldier/monster rigs (idempotent).
    merged = merge_element_skin(dst_json, load_attributes().get(cslug))
    bits = []
    if linked:  bits.append(f"patched {linked} linkedmesh")
    if dropped: bits.append(f"dropped {dropped} orphan region/mesh")
    if merged:  bits.append(f"merged {merged} element-skin atts")
    return True, ", ".join(bits)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true",
                    help="stage every mappable 3.8.99 combat rig")
    ap.add_argument("--stems", nargs="*", default=[],
                    help="explicit combat-rig stems (e.g. harsetti victorica)")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--report", action="store_true",
                    help="print mapping/version table, don't stage")
    a = ap.parse_args()

    kebab_map = load_kebab_to_cslug()
    db_map = load_db_model_map()                       # rig stem -> [c-slugs]
    staged = {p.name for p in SITE.iterdir()
              if p.is_dir() and not p.name.startswith("_")}

    all_stems = sorted(p.stem for p in MODEL.glob("*.scsp"))

    if a.stems:
        # Explicit subset: model-file-driven over exactly the given stems.
        rows = [(s, scsp_to_json.detect_version(MODEL / f"{s}.scsp"),
                 map_stem(s, kebab_map, staged, db_map)) for s in a.stems]
    else:
        # Destination-keyed jobs (one rig per c-slug), from two sources:
        #  Pass A — DB cslug-driven map (authoritative; also recovers SHARED
        #    rigs like c1078<-ras that the model-file sweep assigns to the base
        #    c-slug). Heroes/skins only (c-prefix); d-prefix item entities that
        #    reuse a hero rig are skipped.
        #  Pass B — model-file sweep via map_stem, covering everything NOT in
        #    the DB: collabs, npc/monster/pet, autoslayer stubs.
        # Pass A wins on conflict (populated first; Pass B only fills gaps).
        job: dict[str, str] = {}                       # dest c-slug -> rig stem
        cslug_model_path = REPO / "data_external" / "model_map_from_db.json"
        if cslug_model_path.exists():
            for cslug, model in json.loads(
                    cslug_model_path.read_text(encoding="utf-8")).items():
                if not re.match(r"^c\d", cslug):
                    continue
                if not (MODEL / f"{model}.scsp").exists():
                    continue
                t = _resolve(cslug, staged)
                if t:
                    job.setdefault(t, model)
        for stem in all_stems:
            c = map_stem(stem, kebab_map, staged, db_map)
            if c and c not in job:
                job[c] = stem
        rows = [(stem, scsp_to_json.detect_version(MODEL / f"{stem}.scsp"), c)
                for c, stem in sorted(job.items())]

    # autoslayer_c#### rigs are 1-2 anim training-dummy stubs. When a real
    # hero rig (aram->c5175, hwayoung_a01->c5128) maps to the same c-slug, the
    # alphabetically-later stem wins the staging overwrite — so the stub can
    # silently clobber a full combat rig (observed: aram c5175 17->1 anims).
    # Drop stub rows whose c-slug a real rig also claims; keep stubs that are
    # the only mapping for their slug (e.g. autoslayer_c2124).
    real_claims = {c for stem, v, c in rows if c and not stem.startswith("autoslayer")}
    kept = []
    for stem, v, c in rows:
        if stem.startswith("autoslayer") and c in real_claims:
            print(f"[skip] {stem}: c-slug {c} also staged by a real rig — autoslayer stub skipped")
            continue
        kept.append((stem, v, c))
    rows = kept

    if a.report:
        v_count = {"3.8.99": 0, "2.1.27": 0, None: 0}
        mapped = {"3.8.99": 0, "2.1.27": 0}
        for stem, v, c in rows:
            v_count[v] = v_count.get(v, 0) + 1
            if v in mapped and c:
                mapped[v] += 1
        print(f"[counts] 3.8.99={v_count.get('3.8.99', 0)}  "
              f"2.1.27={v_count.get('2.1.27', 0)}  "
              f"unknown={v_count.get(None, 0)}")
        print(f"[mapped] 3.8.99={mapped['3.8.99']}  2.1.27={mapped['2.1.27']}  "
              f"total={mapped['3.8.99'] + mapped['2.1.27']}")
        return

    ok = skip = fail = 0
    for stem, v, c in rows:
        if v is None:
            print(f"[skip] {stem}: unknown spine version")
            skip += 1
            continue
        if not c:
            skip += 1
            continue
        if stem in INCOMPATIBLE_STEMS:
            # Tear down any previously-staged combat dir so units.json
            # stops flagging has_combat for this slug.
            existing = SITE / c / "combat"
            if existing.exists():
                shutil.rmtree(existing)
                print(f"[skip] {stem}: in INCOMPATIBLE_STEMS — removed prior stage at {existing}")
            else:
                print(f"[skip] {stem}: in INCOMPATIBLE_STEMS (broken source data)")
            skip += 1
            continue
        try:
            done, note = stage_combat(stem, c, version=v, force=a.force)
            if done:
                ok += 1
                suffix = f"   ({note})" if note else ""
                print(f"[ok]   {stem:40s} -> site/assets/{c}/combat/{suffix}")
            else:
                fail += 1
                print(f"[fail] {stem}: {note}")
        except Exception as e:
            fail += 1
            print(f"[fail] {stem}: {e}")
            if a.force:
                traceback.print_exc()

    # ---- DUAL_COMBAT: units whose combat is two separate rigs (rig switcher) ----
    # Staged regardless of the kebab/DB mapping (these rigs resolve to None). The
    # first rig is the primary (<cslug>.json — keeps the default load + has_combat
    # check working); the rest are <cslug>__<label>.json, and a combat/rigs.json
    # manifest lists all of them for the viewer's rig <select>.
    for cslug, rigs in DUAL_COMBAT.items():
        if cslug not in staged:
            continue                      # target unit dir not staged yet
        if a.stems and not any(stem in a.stems for stem, _ in rigs):
            continue                      # --stems run that doesn't touch this unit
        manifest = []
        for i, (stem, label) in enumerate(rigs):
            out_name = cslug if i == 0 else f"{cslug}__{label.lower()}"
            v = scsp_to_json.detect_version(MODEL / f"{stem}.scsp")
            if v is None:
                print(f"[fail] {stem} (dual {cslug}): unknown/absent spine rig"); fail += 1; continue
            try:
                done, note = stage_combat(stem, cslug, version=v, force=a.force, out_name=out_name)
            except Exception as e:
                done, note = False, str(e)
                if a.force: traceback.print_exc()
            if done:
                ok += 1
                manifest.append({"file": f"{out_name}.json", "atlas": f"{out_name}.atlas",
                                 "label": label, "stem": stem})
                tag = "primary" if i == 0 else "alt"
                extra = f"   ({note})" if note else ""
                print(f"[ok]   {stem:40s} -> site/assets/{cslug}/combat/{out_name}.json  [{label} · {tag}]{extra}")
            else:
                fail += 1
                print(f"[fail] {stem} (dual {cslug}): {note}")
        if len(manifest) > 1:
            (SITE / cslug / "combat" / "rigs.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=0) + "\n", encoding="utf-8")
            print(f"       wrote site/assets/{cslug}/combat/rigs.json ({len(manifest)} rigs)")

    print(f"\n[summary] staged={ok} skipped={skip} failed={fail}")


if __name__ == "__main__":
    main()
