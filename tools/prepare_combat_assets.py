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
via scan-forward.

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
MODEL = ROOT / "output" / "model"
SITE  = REPO / "site" / "assets"

sys.path.insert(0, str(THIS.parent))
from decode_sct import decode_one as decode_sct
import scsp_to_json


# Suffix peeling: combat-rig stems use underscore-separated variants
# (abigail_m, harsetti_s01) parallel to our site/assets c-slug suffixes
# (c1144_m, c1153_s01). Order longest-first so 'm_s01' wins over 'm'.
SUFFIX_PEEL = [
    "_m_s01", "_a01", "_m2", "_m", "_s01", "_s02", "_t",
    "_busking", "_trans", "_evil", "_specter", "_c",
]

# Manual overrides — combat-rig stems whose ceciliabot kebab is not the
# obvious underscore→hyphen form. Maps stem → target c-slug directly.
STEM_OVERRIDE: dict[str, str] = {
    "wukong": "c1161",          # kebab is 'immortal-wukong'
    # ML / alt-form combat rigs -> their DISTINCT special-unit c-slug.
    # ML units are separate units (different art) that only share the base
    # character's lore name, so the <base>_m rig belongs to the c2xxx/c5xxx
    # form, not the base. Mapped by single-candidate name-token match and
    # VISUALLY VERIFIED 2026-05-24 (combat render vs known pose.png).
    "araminta_m": "c2048",   # Silver Blade Aramintha
    "aria_m":     "c2129",   # Disciplinary Prefect Aria
    "baal_sezan_m": "c2015", # Sage Baal & Sezan
    "byblis_a01": "c5154",   # Perfumer Byblis
    "cecilia_m":  "c2002",   # Fallen Cecilia
    "celine_m":   "c2103",   # Spirit Eye Celine
    "charles_m":  "c2027",   # Closer Charles
    "chou_m":     "c2101",   # Urban Shadow Choux
    "clarisa_m":  "c2028",   # Kitty Clarissa
    "corvus_m":   "c2012",   # Dark Corvus
    "crozet_m":   "c2036",   # Troublemaker Crozet
    "diene_m":    "c2076_1", # Shepherd of the Dark Diene
    "elena_m":    "c2091",   # Astromancer Elena
    "haste_m":    "c2039",   # Blood Moon Haste
    "ken_m":      "c2047",   # Martial Artist Ken
    "kise_m":     "c2006",   # Judge Kise
    "landy_m":    "c2109",   # Navy Captain Landy
    "leo_m":      "c2029",   # Roaming Warrior Leo
    "lots_m":     "c2031",   # Auxiliary Lots
    "maya_m":     "c2032",   # Fighter Maya
    "pavel_m":    "c2080",   # Commander Pavel
    "peira_m":    "c2125",   # Lone Wolf Peira
    "ravi_m":     "c2019",   # Apocalypse Ravi
    "ray_m":      "c2090",   # Death Dealer Ray
    "silk_m":     "c2004",   # Wanderer Silk
    "tywin_m":    "c2042",   # Ambitious Tywin
    "violetto_m": "c2074",   # Remnant Violet
    "vivian_m":   "c2088",   # Sylvan Sage Vivian
    "wildred_m":  "c2007",   # Arbiter Vildred
    "yulha_m":    "c2131",   # School Nurse Yulha
    "zerato_m":   "c2010",   # Champion Zerato
    # Multi-form characters disambiguated by suffix->c-slug series
    # (_m -> c2xxx ML, _a01 -> c5xxx seasonal, _m2 -> c6xxx anniversary).
    # VISUALLY VERIFIED 2026-05-24 (each form renders distinct + matches pose).
    "achates_m":   "c2017",  # Shooting Star Achates
    "achates_m2":  "c6017",  # Infinite Horizon Achates
    "angelica_m":  "c2062",  # Sinful Angelica
    "angelica_m2": "c6062",  # Angel of Light Angelica
    "bellona_m":   "c2071",  # Lone Crescent Bellona
    "charlotte_m": "c2009",  # Little Queen Charlotte
    "dominiel_m2": "c6037",  # Moon Bunny Dominiel
    "flan_a01":    "c5110",  # Afternoon Soak Flan
    "iseria_a01":  "c5024",  # Summertime Iseria
    "iseria_m":    "c2024",  # Briar Witch Iseria
    "iseria_m2":   "c6024_1",# Monarch of the Sword Iseria
    "karin_m":     "c2011",  # Blood Blade Karin
    "karin_m2":    "c6011",  # Last Piece Karin
    "krau_a01":    "c5070",  # Guard Captain Krau
    "krau_m":      "c2070",  # Last Rider Krau
    "lidica_a01":  "c5046",  # Blooming Lidica
    "lidica_m":    "c2046",  # Faithless Lidica
    "lilias_a01":  "c5089",  # Midnight Gala Lilias
    "lilias_m":    "c2089",  # Conqueror Lilias
    "ludwig_a01":  "c5069",  # Aubade Ludwig
    "ludwig_m":    "c2069",  # Eternal Wanderer Ludwig
    "mercedes_m":  "c2005",  # Celestial Mercedes
    "ras_m":       "c2001",  # Genesis Ras
    "rose_m":      "c2003",  # Shadow Rose
    "rose_m2":     "c6003",  # Wretched Rose
    "schuri_m":    "c2020",  # Watcher Schuri
    "surin_m":     "c2065",  # Tempest Surin
    "surin_m2":    "c6065",  # Sealed Eye Surin
    "tenebria_a01":"c5050",  # Fairytale Tenebria
    "tenebria_m":  "c2050",  # Specter Tenebria
    "tenebria_m2": "c6050",  # Witch of the Mere Tenebria
    "yupine_a01":  "c5016",  # Holiday Yufine
    "yupine_m":    "c2016",  # Abyssal Yufine
    # Recovered 2026-05-24 session 2 after the trailer-skip false-header fix
    # (these previously crashed the 2.1.27 converter mid-parse). Verified.
    "chloe_m":      "c2049", # Maid Chloe
    "aither_m":     "c2018", # Guider Aither
    "furious_m":    "c2087", # Peacemaker Furious
    "kaweric_m":    "c2073", # Mediator Kawerik
    "sharun_m":     "c2132", # Dragon King Sharun
    "bellona_a01":  "c5071", # Seaside Bellona
    "charlotte_a01":"c5009", # Summer Break Charlotte
    "chermia_m":    "c2079", # Lionheart Cermia
    "dominiel_m":   "c2037", # Challenger Dominiel
    "flan_m":       "c2110", # Pirate Captain Flan
    "schuri_m2":    "c6020", # (Schuri c6xxx form)
    "senya_m":      "c2106", # (Senya ML form)
    # Collab units whose rig drops the HeroDatabase 'ae-' prefix (aespa collab).
    # Rig 'winter' = aewinter = c1139, etc. Verified 2026-05-24.
    "winter":       "c1139", # ae-WINTER
    "giselle":      "c1138", # ae-GISELLE
    "ningning":     "c1140", # ae-NINGNING
    "karina":       "c1137", # ae-KARINA (NB: regular Karin is 'karin*'->c1011;
                             #  c1112 is Politis, not Karina)
    # Other collab / bare-name rigs (kebab carries collab full-name; rig uses
    # the bare character name). Found via recoverable_sweep.py, verified.
    "ainz":         "c1155", # Ainz Ooal Gown (Overlord collab)
    "edward":       "c1134", # Edward Elric (Fullmetal Alchemist collab)
    "roy":          "c1135", # Roy Mustang (FMA collab)
    "riza":         "c1136", # Riza Hawkeye (FMA collab)
    "kanna":        "c1097", # Bomb Model Kanna
    "laika":        "c1099", # Command Model Laika
    # 2026-05-24 session 3: AMBIG resolved by suffix->series rule + name match.
    # (luluka/politis AMBIG had both c2xxx and c5xxx candidates; _m->c2xxx,
    # _a01->c5xxx disambiguates. hwayoung_a01 -> c5128 Argent Waves was missed
    # by the name-token matcher which only surfaced c2128.)
    "luluka_m":     "c2082",  # Top Model Luluca
    "luluka_a01":   "c5082",  # Ocean Breeze Luluca
    "politis_m":    "c2112",  # Sea Phantom Politis
    "eda_a01":      "c5111",  # Festive Eda
    "hwayoung_m":   "c2128",  # Bystander Hwayoung
    "hwayoung_a01": "c5128",  # Argent Waves Hwayoung
    # _m_s01 = skin of an ML form. Target is the _m form's c-slug + _s01 (all
    # staged portraits). The longest-first suffix peel mis-resolves these to
    # <base>_m_s01 (e.g. c1079_m_s01, unstaged) so they need explicit entries.
    # politis_m_s01 -> c2112_s01 routes through _resolve to its _1 swap sibling.
    "politis_m_s01":   "c2112_s01",  # skin of Sea Phantom Politis
    "angelica_m_s01":  "c2062_s01",  # skin of Sinful Angelica
    "cecilia_m_s01":   "c2002_s01",  # skin of Fallen Cecilia
    "celine_m_s01":    "c2103_s01",  # skin of Spirit Eye Celine
    "charlotte_m_s01": "c2009_s01",  # skin of Little Queen Charlotte
    "chermia_m_s01":   "c2079_s01",  # skin of Lionheart Cermia
    "chloe_m_s01":     "c2049_s01",  # skin of Maid Chloe
    "flan_m_s01":      "c2110_s01",  # skin of Pirate Captain Flan
    "iseria_m_s01":    "c2024_s01",  # skin of Briar Witch Iseria
    "kaweric_m_s01":   "c2073_s01",  # skin of Mediator Kawerik
    "kise_m_s01":      "c2006_s01",  # skin of Judge Kise
    "krau_m_s01":      "c2070_s01",  # skin of Last Rider Krau
    "lidica_m_s01":    "c2046_s01",  # skin of Faithless Lidica
    "ravi_m_s01":      "c2019_s01",  # skin of Apocalypse Ravi
    "surin_m_s01":     "c2065_s01",  # skin of Tempest Surin
    "tenebria_m_s01":  "c2050_s01",  # skin of Specter Tenebria
    "vivian_m_s01":    "c2088_s01",  # skin of Sylvan Sage Vivian
    "wildred_m_s01":   "c2007_s01",  # skin of Arbiter Vildred
}

# Romanization aliases — the dump's combat-rig filenames use a different
# transliteration than the ceciliabot kebab for these base heroes, so the
# normal kebab lookup misses them even though the rig is present and
# converts cleanly. Maps dump spelling → ceciliabot kebab. Applied to both
# the bare-stem and suffix-peeled-base lookups in map_stem(). Verified
# 2026-05-24: all 11 convert via convert_2_1 and resolve to a staged unit.
SPELLING_ALIAS: dict[str, str] = {
    "alensia":  "alencia",
    "araminta": "aramintha",
    "ceris":    "cerise",
    "chermia":  "cermia",
    "chou":     "choux",
    "violetto": "violet",
    "yupine":   "yufine",
    "kaweric":  "kawerik",
    "clarisa":  "clarissa",
    "serilla":  "serila",
    "wildred":  "vildred",
    "luluka":   "luluca",   # recovered after trailer-skip false-header fix
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
    # c1169 Robin combat: 26 region attachments missing from atlas
    # (hand_6a/6b/8/10/11/12/14, mouth_2, suit_side_a/b, coat_*, sweat,
    # face_all_3c, case_opened_*). Even idle shows visible gaps.
    "robin",
}


def load_kebab_to_cslug() -> dict[str, str]:
    hdb_path = REPO / "data_external" / "HeroDatabase.json"
    hdb = json.loads(hdb_path.read_text(encoding="utf-8"))
    return {k: v["id"] for k, v in hdb.items()}


def _resolve(cslug: str, staged: set[str]) -> str | None:
    """If cslug is a PRIMARY_SWAP backdrop, redirect to its _1 sibling.
    Returns the staged slug or None."""
    if cslug in PRIMARY_SWAP_BARE:
        x1 = cslug + "_1"
        return x1 if x1 in staged else None
    return cslug if cslug in staged else None


def map_stem(stem: str, kebab_map: dict[str, str], staged: set[str]) -> str | None:
    """Map a combat-rig stem to a staged c-slug. Returns None if unmappable
    or the target slug isn't in site/assets/."""
    if stem in STEM_OVERRIDE:
        return _resolve(STEM_OVERRIDE[stem], staged)

    # Direct npc/m/pet/af prefix (already in c-slug form)
    if stem in staged and re.match(r"^(npc|m9|pet_|af)\d", stem):
        return stem

    # Direct kebab lookup (with romanization alias)
    kebab = stem.replace("_", "-")
    kebab = SPELLING_ALIAS.get(kebab, kebab)
    if kebab in kebab_map:
        return _resolve(kebab_map[kebab], staged)

    # autoslayer_c2124 etc — c-slug embedded in token
    for tok in stem.split("_"):
        if tok.startswith("c") and tok[1:].isdigit():
            r = _resolve(tok, staged)
            if r:
                return r

    # Peel suffix, lookup base kebab, append suffix to base c-slug
    for suf in SUFFIX_PEEL:
        if stem.endswith(suf):
            base = stem[: -len(suf)]
            base_kebab = base.replace("_", "-")
            base_kebab = SPELLING_ALIAS.get(base_kebab, base_kebab)
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


def stage_combat(stem: str, cslug: str, version: str | None, force: bool = False) -> tuple[bool, str]:
    """Stage one combat rig. Returns (ok, note). `version` is the pre-detected
    spine version ("3.8.99" or "2.1.27"); pass None to detect lazily."""
    scsp  = MODEL / f"{stem}.scsp"
    atlas = MODEL / f"{stem}.atlas"
    sct   = MODEL / f"{stem}.sct"
    timeline = MODEL / f"{stem}.timeline"

    if not (scsp.exists() and atlas.exists() and sct.exists()):
        return False, f"missing source files for {stem}"

    dst_dir   = SITE / cslug / "combat"
    dst_json  = dst_dir / f"{cslug}.json"
    dst_atlas = dst_dir / f"{cslug}.atlas"
    dst_png   = dst_dir / f"{cslug}.png"
    dst_tl    = dst_dir / f"{cslug}.timeline"
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
        stage_atlas(atlas, dst_atlas, f"{cslug}.png")

    if timeline.exists() and (force or not dst_tl.exists()):
        shutil.copy2(timeline, dst_tl)

    # Orphan attachment fixup — runs after both JSON and atlas exist.
    linked, dropped = patch_orphan_attachments(dst_json, dst_atlas)
    bits = []
    if linked:  bits.append(f"patched {linked} linkedmesh")
    if dropped: bits.append(f"dropped {dropped} orphan region/mesh")
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
    staged = {p.name for p in SITE.iterdir()
              if p.is_dir() and not p.name.startswith("_")}

    all_stems = sorted(p.stem for p in MODEL.glob("*.scsp"))

    if a.stems:
        candidates = a.stems
    else:
        candidates = all_stems

    rows = []
    for stem in candidates:
        v = scsp_to_json.detect_version(MODEL / f"{stem}.scsp")
        c = map_stem(stem, kebab_map, staged)
        rows.append((stem, v, c))

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

    print(f"\n[summary] staged={ok} skipped={skip} failed={fail}")


if __name__ == "__main__":
    main()
