"""Step 1: staged rig dirs -> role map -> materialized `units` entries.

Two passes, so the PRIMARY_SWAP override works regardless of `iterdir()` order:
pass 1 (`plan_roles`) decides each staged slug's role — "primary", or "extra of
X"; pass 2 (`build_units`) materializes the primaries and attaches the extras,
which is only possible once every primary exists.

`swap_alias_map` then maps the bare slug of a backdrop/character pair to its
promoted `_1` primary, so the artwork/skill scans can route bare-slug files
(`face_c1183_*.png`, `sk_c1183_3.webp`) to the unit that is actually public.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from scsp_to_json import detect_version as _detect_scsp_version

from .slugs import kind_of, split_variant
from .tables import CECILIA_BASE, EXTRA_SUFFIX, SLUG_PARENT


def staged_unit_dirs(site_assets: Path) -> list[Path]:
    """Every staged dir with a baked pose.png is a unit."""
    _RESERVED_ASSET_DIRS = {"_updates", "_artifacts"}
    return [d for d in sorted(site_assets.iterdir())
            if d.is_dir() and d.name not in _RESERVED_ASSET_DIRS
            and (d / "pose.png").exists()]


def plan_roles(staged: set[str], swap: dict[str, dict]) -> dict[str, tuple[str, str]]:
    """slug -> ("primary", "")  or  ("extra", parent_slug).

    Normally the bare slug is the primary and its X_1 sibling is an extra. For
    slugs in `swap` (an explicit PRIMARY_SWAP entry or an auto-detected
    (X, X_1) pair) the roles flip: the bare slug becomes an extra and the X_1
    sibling becomes primary. SLUG_PARENT covers the ids outside that convention.
    """
    role: dict[str, tuple[str, str]] = {}
    for slug in staged:
        is_x1 = slug.endswith(EXTRA_SUFFIX) and len(slug) > len(EXTRA_SUFFIX)
        bare = slug[:-len(EXTRA_SUFFIX)] if is_x1 else slug
        x1   = slug if is_x1 else (slug + EXTRA_SUFFIX)
        # Swap case: the pair is a backdrop/character split (explicit
        # PRIMARY_SWAP or auto-detected) and its _1 sibling exists.
        if bare in swap and x1 in staged:
            role[slug] = ("extra", x1) if slug == bare else ("primary", "")
            continue
        # Explicit parent override for slugs that don't use the _1 convention.
        if slug in SLUG_PARENT and SLUG_PARENT[slug]["parent"] in staged:
            role[slug] = ("extra", SLUG_PARENT[slug]["parent"])
            continue
        # Normal: X_1 attaches to X if X exists.
        if is_x1 and bare in staged:
            role[slug] = ("extra", bare)
            continue
        role[slug] = ("primary", "")
    return role


def build_units(all_dirs: list[Path], raw: Path, name_base: dict, name_skin: dict,
                swap: dict[str, dict], role: dict[str, tuple[str, str]]) -> dict[str, dict]:
    """Materialize one `units` entry per primary staged slug, extras attached."""
    extras_for: dict[str, list[dict]] = {}
    units: dict[str, dict] = {}
    for d in all_dirs:
        slug = d.name
        spine_json  = d / f"{slug}.json"
        spine_atlas = d / f"{slug}.atlas"
        spine_png   = d / f"{slug}.png"
        base_id, variant_suf, _ = split_variant(slug)

        r, parent_slug = role[slug]
        if r == "extra":
            extra = {
                "id":   slug,
                "pose": f"assets/{slug}/pose.png",
            }
            if spine_json.exists() and spine_atlas.exists() and spine_png.exists():
                extra["json"]  = f"assets/{slug}/{slug}.json"
                extra["atlas"] = f"assets/{slug}/{slug}.atlas"
            # Optional label override from the swap map (PRIMARY_SWAP) or SLUG_PARENT.
            if slug in swap and "label" in swap[slug]:
                extra["label"] = swap[slug]["label"]
            elif slug in SLUG_PARENT and "label" in SLUG_PARENT[slug]:
                extra["label"] = SLUG_PARENT[slug]["label"]
            extras_for.setdefault(parent_slug, []).append(extra)
            continue

        unit = {
            "id":       slug,
            "base_id":  base_id,
            "variant":  variant_suf.lstrip("_") if variant_suf else "",
            "kind":     kind_of(slug),
            "pose":     f"assets/{slug}/pose.png",
            "artworks": [],
            "skills":   [],
            "updates":  [],
        }
        # `cecilia` is set ONLY inside the name-resolution branches below, and
        # only when we resolve a base hero kebab. Non-unit kinds (npc/monster/
        # pet/artifact-rig/special) never get a cecilia field — ceciliabot
        # only hosts pages for playable heroes (Units page) and the in-game
        # artifacts table (Artifacts page; handled separately in Step 4b).

        # Step 1a: name resolution.
        # Priority: exact skin match -> bare-slug skin match (for promoted _1
        # rigs whose own slug isn't in HeroSkins.json) -> base hero match.
        skin_key = slug
        if skin_key not in name_skin and skin_key.endswith(EXTRA_SUFFIX):
            skin_key = skin_key[:-len(EXTRA_SUFFIX)]
        if skin_key in name_skin:
            sk = name_skin[skin_key]
            # The skin's *own* name is the variant label; the base hero's name
            # is the grouping label. ceciliabot only hosts a page per base
            # hero — there are no per-costume URLs — so `cecilia` is pointed
            # at the base hero below when we can resolve it, and falls back
            # to the heroes index otherwise (never the skin kebab, which
            # would 404).
            unit["name"] = sk["name"]
            unit["slug"] = sk["_id"]
            # Promote the base hero's metadata if we know it.
            base_hero_key = sk.get("_hero_key")
            base_meta = name_base.get(base_id) if base_id != slug else None
            if base_meta:
                unit["hero_name"] = base_meta["name"]
                unit["hero_slug"] = base_meta["_id"]
                unit["cecilia"] = f"{CECILIA_BASE}/{base_meta['_id']}"
                for k in ("rarity", "attribute", "role"):
                    if k in base_meta: unit[k] = base_meta[k]
        elif base_id in name_base:
            bm = name_base[base_id]
            unit["name"] = bm["name"]
            unit["slug"] = bm["_id"]
            unit["hero_name"] = bm["name"]
            unit["hero_slug"] = bm["_id"]
            unit["cecilia"] = f"{CECILIA_BASE}/{bm['_id']}"
            for k in ("rarity", "attribute", "role"):
                if k in bm: unit[k] = bm[k]

        if spine_json.exists() and spine_atlas.exists() and spine_png.exists():
            # Source-format version (2.1.27 vs 3.8.99) from the portrait .scsp.
            # The staged JSON can't tell us — the 2.1.27 converter rewrites
            # skeleton.spine to "3.8.99" for spine-player compatibility — so we
            # re-detect from the raw .scsp. Fall back to 3.8.99 when the source
            # .scsp isn't locatable.
            src_scsp = raw / "portrait" / f"{slug}.scsp"
            src_ver = (_detect_scsp_version(src_scsp) if src_scsp.exists() else None) or "3.8.99"
            unit["spine"] = [{
                "json":    f"assets/{slug}/{slug}.json",
                "atlas":   f"assets/{slug}/{slug}.atlas",
                "version": src_ver,
            }]

        # Combat rig (skill1/skill2/skill3/run/knock_down/rise animations).
        # Staged by pipeline/prepare_combat_assets.py from output/model/. Only
        # the 3.8.99 subset is currently supported — 2.1.27 combat rigs are
        # blocked on multi-day RE (events block + post-events deferred
        # linked-mesh table; see docs/TASKS.md "Combat rig live viewer").
        combat_json = d / "combat" / f"{slug}.json"
        if combat_json.exists():
            unit["has_combat"] = True
            # Dual-rig units (e.g. c2185_1 Rhianna & Luciella) stage a
            # combat/rigs.json manifest listing each rig + a display label; the
            # viewer renders a rig <select> from it. The primary's file is
            # always <slug>.json, so the default load path is unchanged.
            rigs_manifest = d / "combat" / "rigs.json"
            if rigs_manifest.exists():
                unit["combat_rigs"] = json.loads(rigs_manifest.read_text(encoding="utf-8"))
            # Full skill-3 clip baked by render/skill3.js (TASKS #57).
            # R2-served like the rest of combat/ — the frontend builds the URL
            # from E7.spineBase, so only a flag is emitted here.
            if (d / "combat" / "sk3_full.webp").exists():
                unit["skill3_full"] = True

        trim_path = d / "pose_trim.json"
        if trim_path.exists():
            with open(trim_path) as tf:
                trim = json.load(tf)
            if trim:
                unit["pose_trim"] = trim

        # Character-only hub thumbnail (Task #8). Only emitted for slugs whose
        # rig has any FX/aura/backdrop slots — render/thumbs.js skips
        # zero-hit slugs so their hub card falls back to pose.png. The smart-
        # crop (SLUG_THRESHOLDS) is baked into thumb.png at render time, so no
        # thumb_trim sidecar is needed. The detail page always uses pose.png.
        thumb_png = d / "thumb.png"
        if thumb_png.exists():
            unit["thumb"] = f"assets/{slug}/thumb.png"

        units[slug] = unit

    # Attach extras now that every primary unit has been created. (Done in a
    # second pass so swap-case extras land on their promoted sibling
    # regardless of iteration order.)
    for primary_slug, extras in extras_for.items():
        if primary_slug in units:
            units[primary_slug]["extras"] = extras
        else:
            for e in extras:
                print(f"  ! orphan extra {e['id']}: primary {primary_slug} missing")
    return units


def swap_alias_map(swap: dict[str, dict], units: dict) -> dict[str, str]:
    """bare -> promoted `_1` primary.

    For PRIMARY_SWAP cases the bare slug (e.g. c1183) holds the face/skill
    assets (face_c1183_*.png, sk_c1183_3.webp) but the `_1` sibling is the
    primary unit in `units`; the asset scans route matches through this.
    """
    return {
        bare: bare + EXTRA_SUFFIX
        for bare in swap
        if (bare + EXTRA_SUFFIX) in units
    }
