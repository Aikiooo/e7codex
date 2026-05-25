#!/usr/bin/env python3
"""
E7 Codex — site index builder (v4, name + variant aware).

The site enumerates units by **portrait ID** (c1001, npc1467, m9181, …) because
that's the unit of artwork we can reliably bake — see `tools/render_poses.js`.

For every ID with a baked pose at site/assets/<id>/pose.png we produce a
units.json entry: kind (from ID prefix), pose path, artwork matches, skill
animation stills, update-codename tags, and — if we know a name for it —
display name + ceciliabot kebab slug.

Names come from two community-maintained JSONs in `data_external/`:
  - HeroDatabase.json  c####           -> {_id, name, rarity, ...}
  - HeroSkins.json     c####_sNN       -> {_id, name}   (skin variants)

Both are one-shot snapshots from CeciliaBot/E7Tools — the encrypted output/db
is the long-term source of truth, but no decoder exists publicly. See
project_e7_db_encrypted memory note.

Run:
    python build_index.py --img D:/Claude/E7/img_output --raw D:/Claude/E7/output --out ./site
"""
from __future__ import annotations
import argparse, json, os, re, shutil, sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "tools"))
from scsp_to_json import detect_version as _detect_scsp_version

# Codename pattern: v + 2-letter theme + (year-2020) digit + 'aa'
KNOWN_UPDATES: dict[str, str] = {
    "vsu1aa": "Summer 2021",   "vsu2aa": "Summer 2022", "vsu3aa": "Summer 2023",
    "vsu4aa": "Summer 2024",   "vsu5aa": "Summer 2025",
    "vva0aa": "Valentine 2020","vva1aa": "Valentine 2021","vva5aa": "Valentine 2025",
    "vch0aa": "Christmas 2020","vch1aa": "Christmas 2021",
    "vch2aa": "Christmas 2022","vch3aa": "Christmas 2023",
    "vha0aa": "Halloween 2020","vha2aa": "Halloween 2022",
    "vfa2aa": "Fullmetal Alchemist collab (2022)",
    "vae2aa": "Aespa collab (2022)",
    "vfr5aa": "Frieren collab (2025)",
    "vma1aa": "Update 2021 (vma1aa)",
    "vt41aa": "Update 2021 (vt41aa)",
    "vfm0aa": "Update 2020 (vfm0aa)",
    "vfm3aa": "Update 2023 (vfm3aa)",
}
CODE_RE = re.compile(r"(?:^|(?<=[^a-z0-9]))(v[a-z0-9]{3}aa)(?![a-z])", re.I)
CECILIA_BASE = "https://ceciliabot.github.io/#/hero"
CECILIA_INDEX = "https://ceciliabot.github.io/#/heroes"
CECILIA_ARTIFACT = "https://ceciliabot.github.io/#/artifacts"

IMG_EXT = {".png", ".webp", ".jpg", ".jpeg"}
# Suffixes that mark a variant of the same character (skin/ML/alt-form).
# Order matters: longest first so '_m_s01' wins over '_m'. The trailing '_1'
# marker (an extra-asset rig for the same logical variant) is handled
# separately by split_variant — see EXTRA_SUFFIX below.
VARIANT_SUFFIXES = ["_m_s01", "_a01", "_m2", "_m", "_s01",
                    "_s02", "_t", "_busking", "_trans", "_evil", "_specter"]
EXTRA_SUFFIX = "_1"   # peeled before variant matching; marks the rig as an
                      # alt asset of the bare-slug variant (e.g. c1046_s02_1
                      # is an extra rig for c1046_s02, not its own skin).

# Slugs whose `_1` sibling should actually be the primary rig, with the bare
# slug demoted to an extra. Used when the bare slug ships a backdrop scene
# (table, curtains, sound stage) and the `_1` sibling carries the character.
# `label` overrides the default "alt rig N" tag on the detail page.
#   Discovered by manual inspection — extend as more come up.
PRIMARY_SWAP: dict[str, dict] = {
    "c1046_s02": {"label": "backdrop"},   # Lidica's Sunday Service skin
    "c1180":     {"label": "backdrop"},
    "c1183":     {"label": "backdrop"},
    "c2076":     {"label": "backdrop"},
    "c2112_s01": {"label": "backdrop"},   # detected by find_backdrops.py (eff_back_* slots)
    "c2181":     {"label": "backdrop"},
    "c2184":     {"label": "backdrop"},
    "c2185":     {"label": "backdrop"},
    "c6024":     {"label": "backdrop"},
}

# Arbitrary slug → parent mappings that don't follow the _1 suffix convention.
# Each entry is attached as an extra rig on the parent's detail page.
# Use when the same character ships under two unrelated IDs (e.g. an older
# lobby-only rig alongside the full battle rig released later).
SLUG_PARENT: dict[str, dict] = {
    "c1084": {"parent": "c1142", "label": "lobby rig"},  # Eligos legacy 2.1.27 sprite
}


def split_variant(slug: str) -> tuple[str, str, bool]:
    """Return (base_id, suffix, is_extra).

    If the slug ends with `_1` we peel that first and mark `is_extra=True`;
    the bare slug then goes through the regular variant match. This lets
    `c1046_s02_1` resolve to (c1046, '_s02', True) — same variant key as
    `c1046_s02` but flagged so the caller can attach it as an extra rig
    rather than a separate unit/tab.
    """
    is_extra = False
    bare = slug
    if slug.endswith(EXTRA_SUFFIX) and len(slug) > len(EXTRA_SUFFIX):
        bare = slug[:-len(EXTRA_SUFFIX)]
        is_extra = True
    for suf in VARIANT_SUFFIXES:
        if bare.endswith(suf) and len(bare) > len(suf):
            return bare[:-len(suf)], suf, is_extra
    return bare, "", is_extra


def kind_of(slug: str) -> str:
    if slug.startswith("npc"):      return "npc"
    if slug.startswith("pet"):      return "pet"
    if slug.startswith("af"):       return "artifact"
    if re.match(r"^m\d", slug):     return "monster"
    if re.match(r"^d\d", slug):     return "monster"
    if re.match(r"^s\d", slug):     return "special"
    if re.match(r"^c\d", slug):     return "unit"
    return "other"


def walk(root: Path):
    if not root.exists(): return
    for dp, _, fs in os.walk(root):
        for f in fs:
            yield Path(dp) / f


def kebab(s: str) -> str:
    """Make a name like 'Lionheart Cermia' into 'lionheart-cermia'."""
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def load_name_db(root: Path) -> tuple[dict, dict]:
    """Load HeroDatabase + HeroSkins and layer in the rtastats scrape.

    HeroDatabase is preferred when present because it carries the canonical
    kebab `_id` used by ceciliabot's URL routing. The rtastats fallback only
    fills in heroes the snapshot misses (c1144+); we synthesise a kebab from
    the name so ceciliabot links still work for those (they may 404 on
    ceciliabot itself but at least carry the right shape).
    """
    base: dict[str, dict] = {}
    skin: dict[str, dict] = {}
    p1 = root / "data_external" / "HeroDatabase.json"
    p2 = root / "data_external" / "HeroSkins.json"
    p3 = root / "data_external" / "HeroNames_rtastats.json"
    if p1.exists():
        for v in json.loads(p1.read_text("utf-8")).values():
            base[v["id"]] = v
    if p2.exists():
        for hero_key, skin_list in json.loads(p2.read_text("utf-8")).items():
            for s in skin_list:
                skin[s["id"]] = {**s, "_hero_key": hero_key}
    if p3.exists():
        payload = json.loads(p3.read_text("utf-8"))
        for code, rec in payload.get("heroes", {}).items():
            if code in base:
                continue                          # HeroDatabase wins on overlap
            base[code] = {
                "id":   code,
                "_id":  kebab(rec["name"]),
                "name": rec["name"],
                **{k: rec[k] for k in ("attribute", "role") if k in rec},
            }
    return base, skin


def load_artifact_db(root: Path) -> dict[str, dict]:
    """Load ceciliabot Artifacts.json keyed by in-game id (`art####`).

    Source: `https://ceciliabot.github.io/data/artifacts.json` cached locally.
    Records: {_id (kebab url slug), id (art####), name, rarity, role, ...}.
    """
    p = root / "data_external" / "Artifacts.json"
    if not p.exists():
        return {}
    by_id: dict[str, dict] = {}
    for v in json.loads(p.read_text("utf-8")).values():
        gid = v.get("id")
        if isinstance(gid, str) and gid.startswith("art"):
            by_id[gid] = v
    return by_id


def build(img: Path, raw: Path, out: Path) -> None:
    site_assets = out / "assets"
    if not site_assets.exists():
        raise SystemExit(f"no {site_assets} — run `python tools/prepare_assets.py --from-yes` then "
                          "`node tools/render_poses.js` first")

    name_base, name_skin = load_name_db(out.parent if out.name == "site" else Path("."))

    # Step 1: every staged dir with a pose.png is a unit. Two-pass approach so
    # the PRIMARY_SWAP override works regardless of iteration order:
    #   pass 1: figure out each slug's role — "primary" or "extra of X".
    #           Normally X is the parent slug (bare = primary, X_1 = extra).
    #           For slugs in PRIMARY_SWAP we flip the roles: the bare slug
    #           becomes an extra and the X_1 sibling becomes primary.
    #   pass 2: materialize units, attaching extras as we go.
    _RESERVED_ASSET_DIRS = {"_updates", "_artifacts"}
    all_dirs = [d for d in sorted(site_assets.iterdir())
                if d.is_dir() and d.name not in _RESERVED_ASSET_DIRS
                and (d / "pose.png").exists()]
    staged = {d.name for d in all_dirs}

    # slug -> ("primary", "")   or   ("extra", parent_slug)
    role: dict[str, tuple[str, str]] = {}
    for slug in staged:
        is_x1 = slug.endswith(EXTRA_SUFFIX) and len(slug) > len(EXTRA_SUFFIX)
        bare = slug[:-len(EXTRA_SUFFIX)] if is_x1 else slug
        x1   = slug if is_x1 else (slug + EXTRA_SUFFIX)
        # Swap case: the bare slug is in PRIMARY_SWAP and its _1 sibling exists.
        if bare in PRIMARY_SWAP and x1 in staged:
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
            # Optional label override from PRIMARY_SWAP or SLUG_PARENT.
            if slug in PRIMARY_SWAP and "label" in PRIMARY_SWAP[slug]:
                extra["label"] = PRIMARY_SWAP[slug]["label"]
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
            # isn't locatable (e.g. pre-converted rigs from yes/).
            src_scsp = raw / "portrait" / f"{slug}.scsp"
            src_ver = (_detect_scsp_version(src_scsp) if src_scsp.exists() else None) or "3.8.99"
            unit["spine"] = [{
                "json":    f"assets/{slug}/{slug}.json",
                "atlas":   f"assets/{slug}/{slug}.atlas",
                "version": src_ver,
            }]

        # Combat rig (skill1/skill2/skill3/run/knock_down/rise animations).
        # Staged by tools/prepare_combat_assets.py from output/model/. Only
        # the 3.8.99 subset is currently supported — 2.1.27 combat rigs are
        # blocked on multi-day RE (events block + post-events deferred
        # linked-mesh table; see docs/TASKS.md "Combat rig live viewer").
        combat_json = d / "combat" / f"{slug}.json"
        if combat_json.exists():
            unit["has_combat"] = True

        trim_path = d / "pose_trim.json"
        if trim_path.exists():
            with open(trim_path) as tf:
                trim = json.load(tf)
            if trim:
                unit["pose_trim"] = trim

        # Character-only hub thumbnail (Task #8). Only emitted for slugs whose
        # rig has any FX/aura/backdrop slots — tools/render_thumbs.js skips
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

    # For PRIMARY_SWAP cases the bare slug (e.g. c1183) holds the face/skill
    # assets (face_c1183_*.png, sk_c1183_3.webp) but the _1 sibling is the
    # primary unit in `units`. Build a map bare→primary so asset scans can
    # route matches to the right unit.
    swap_alias: dict[str, str] = {
        bare: bare + EXTRA_SUFFIX
        for bare in PRIMARY_SWAP
        if (bare + EXTRA_SUFFIX) in units
    }

    # Step 2: artwork matching — count every img_output file whose name/parent
    # references the unit ID, but only COPY the face/* PNGs into the site bundle.
    # Include swap_alias keys so bare-slug face images land on the primary unit.
    all_match_slugs = sorted(set(units) | set(swap_alias), key=len, reverse=True)
    slug_re = {s: re.compile(rf"(?:^|[^a-z0-9]){re.escape(s)}(?:[^a-z0-9]|$)", re.I)
               for s in all_match_slugs}
    counts: dict[str, int] = defaultdict(int)

    for p in walk(img):
        if p.suffix.lower() not in IMG_EXT: continue
        # Skip categories we'll handle separately below.
        rel_parent = p.parent.name.lower()
        if rel_parent in {"cut", "fhd"}:  # handled in skills step
            continue
        haystack = f"{p.stem} {p.parent.name}"
        is_face = (rel_parent == "face")
        for s in all_match_slugs:
            if slug_re[s].search(haystack):
                primary = swap_alias.get(s, s)
                counts[primary] += 1
                if is_face:
                    dst = site_assets / primary / f"face_{p.name}"
                    if not dst.exists():
                        try:    shutil.copy2(p, dst)
                        except OSError: continue
                    rel = f"assets/{primary}/{dst.name}"
                    if rel not in units[primary]["artworks"]:
                        units[primary]["artworks"].append(rel)
                break
    for s, n in counts.items():
        if s in units:
            units[s]["artworks_count"] = n

    # Step 3: skill animations from img_output/cut/fhd/sk_<id>_3*.webp
    # The third skill (S3) is the one E7 dumps as a still; we copy it next to
    # the pose so the detail page can render it without a second fetch path.
    # swap_alias resolves bare-slug skill files to the correct primary unit.
    fhd = img / "cut" / "fhd"
    if fhd.exists():
        sk_re = re.compile(r"^sk_(.+?)_3(?:_\d+)?\.(?:webp|png|jpg)$", re.I)
        for p in fhd.iterdir():
            m = sk_re.match(p.name)
            if not m: continue
            slug = m.group(1)
            primary = swap_alias.get(slug, slug)
            if primary not in units: continue
            dst = site_assets / primary / f"skill_{p.name}"
            if not dst.exists():
                try: shutil.copy2(p, dst)
                except OSError: continue
            units[primary]["skills"].append(f"assets/{primary}/{dst.name}")

    # Step 3b: intimacy illustrations — story/bg/img_intimacy_illust_c<id>.webp (skip _th).
    intimacy_re = re.compile(r"^img_intimacy_illust_(c\d+)\.webp$", re.I)
    _intimacy_dir = img / "story" / "bg"
    if _intimacy_dir.exists():
        for p in _intimacy_dir.iterdir():
            m = intimacy_re.match(p.name)
            if not m:
                continue
            slug = m.group(1)
            primary = swap_alias.get(slug, slug)
            if primary not in units:
                continue
            dst = site_assets / primary / "intimacy.webp"
            if not dst.exists():
                try:    shutil.copy2(p, dst)
                except OSError: continue
            units[primary]["intimacy"] = f"assets/{primary}/intimacy.webp"

    # Step 4: update gallery — copy banner art + story images per KNOWN_UPDATE codename.
    updates_dir = site_assets / "_updates"
    updates_dir.mkdir(exist_ok=True)
    banners_per_code: dict[str, list[str]] = defaultdict(list)
    story_per_code:  dict[str, list[str]] = defaultdict(list)
    STORY_SKIP = re.compile(r"_th\.|_blur\.|(?:^|_)silhouette", re.I)

    for p in walk(img / "banner"):
        if p.suffix.lower() not in IMG_EXT: continue
        codes = {c.lower() for c in CODE_RE.findall(p.name.lower())} & set(KNOWN_UPDATES)
        for c in codes:
            dst = updates_dir / c / p.name
            dst.parent.mkdir(exist_ok=True)
            if not dst.exists():
                try: shutil.copy2(p, dst)
                except OSError: continue
            banners_per_code[c].append(f"assets/_updates/{c}/{p.name}")

    story_bg = img / "story" / "bg"
    if story_bg.exists():
        for p in sorted(story_bg.iterdir()):
            if p.suffix.lower() not in IMG_EXT: continue
            if STORY_SKIP.search(p.name): continue
            codes = {c.lower() for c in CODE_RE.findall(p.name.lower())} & set(KNOWN_UPDATES)
            for c in codes:
                dst = updates_dir / c / p.name
                dst.parent.mkdir(exist_ok=True)
                if not dst.exists():
                    try: shutil.copy2(p, dst)
                    except OSError: continue
                story_per_code[c].append(f"assets/_updates/{c}/{p.name}")

    # Step 4b: artifacts — copy art####_fu.png (portrait full art) + matching
    # art####_l.jpg (horizontal lobby cut) into site/assets/_artifacts/.
    # Name/rarity/role enriched from ceciliabot's Artifacts.json snapshot.
    # Orphans (PNGs with no matching JSON record) get slug-only labels so they
    # still appear in the grid — the dump occasionally retains retired art.
    artifact_db = load_artifact_db(out.parent if out.name == "site" else Path("."))
    arti_dir = site_assets / "_artifacts"
    arti_dir.mkdir(exist_ok=True)
    ARTI_ID_RE = re.compile(r"^(art\d+(?:_\d+)?)_(fu\.png|l\.jpg)$", re.I)
    arti_files: dict[str, dict[str, str]] = defaultdict(dict)
    arti_src = img / "item_arti"
    if arti_src.exists():
        for p in sorted(arti_src.iterdir()):
            m = ARTI_ID_RE.match(p.name)
            if not m:
                continue
            aid = m.group(1).lower()
            suf = m.group(2).lower()
            dst = arti_dir / p.name
            if not dst.exists():
                try: shutil.copy2(p, dst)
                except OSError: continue
            arti_files[aid]["full" if suf.startswith("fu") else "lobby"] = (
                f"assets/_artifacts/{p.name}"
            )
    artifacts_out: list[dict] = []
    for aid, paths in arti_files.items():
        if "full" not in paths:
            continue                          # no portrait → not card-worthy
        rec = artifact_db.get(aid, {})
        entry: dict = {"id": aid, "art_full": paths["full"]}
        if "lobby" in paths: entry["art_lobby"] = paths["lobby"]
        if rec.get("name"):       entry["name"]    = rec["name"]
        if rec.get("_id"):        entry["slug"]    = rec["_id"]
        if rec.get("rarity"):     entry["rarity"]  = rec["rarity"]
        if rec.get("role"):       entry["role"]    = rec["role"]
        entry["cecilia"] = (f"{CECILIA_ARTIFACT}/{rec['_id']}" if rec.get("_id")
                            else CECILIA_INDEX)
        artifacts_out.append(entry)
    artifacts_out.sort(key=lambda a: (-(a.get("rarity") or 0), a["id"]))

    # Step 5: emote gallery — img_output/emoticon/<id>_<theme>_001.webp (animated)
    # and img_output/emoticon_chat/<id>_<theme>_001.png (static chat sticker).
    # Filename grammar: <id> is usually c#### but sometimes a hero slug
    # (e.g. alki_glasses_001.png) where the slug part is multi-token. We group
    # entries by everything up to the trailing `_<theme>_<NNN>` segment.
    emotes_dir = site_assets / "_emotes"
    emotes_dir.mkdir(exist_ok=True)
    emote_re = re.compile(r"^(?P<id>.+?)_(?P<theme>[a-z]+)_(?P<n>\d+)\.(?:webp|png)$", re.I)
    emote_groups: dict[str, dict] = {}
    for sub, animated in (("emoticon", True), ("emoticon_chat", False)):
        d = img / sub
        if not d.exists(): continue
        for p in sorted(d.iterdir()):
            m = emote_re.match(p.name)
            if not m: continue
            eid   = m.group("id").lower()
            # Skip icon_c#### duplicates — chat-sticker pngs that mirror the
            # animated c#### emote under a separate id. Always duplicates of
            # an existing bare-id entry; would otherwise appear as a second
            # group for the same character in the gallery.
            if eid.startswith("icon_"):
                continue
            theme = m.group("theme").lower()
            dst = emotes_dir / p.name
            if not dst.exists():
                try: shutil.copy2(p, dst)
                except OSError: continue
            rec = emote_groups.setdefault(eid, {"id": eid, "emotes": []})
            rec["emotes"].append({
                "file":     f"assets/_emotes/{p.name}",
                "theme":    theme,
                "animated": animated,
            })
    # Link each group to a known unit if possible (so the gallery can deep-link
    # to the detail page). The character ID in the emote filename is usually
    # c#### but sometimes a hero slug (alki_glasses_001.png). Resolution
    # order: staged unit (links to /#/u/<base>) -> HeroDatabase by id ->
    # HeroDatabase by kebab slug. Name comes from whichever resolves first.
    name_base_by_slug = {v["_id"]: v for v in name_base.values()}
    emotes_list = []
    for eid, rec in sorted(emote_groups.items()):
        lookup = eid
        unit = units.get(lookup) or next(
            (units[s] for s in units if units[s].get("base_id") == lookup), None)
        if unit:
            rec["base_id"]   = unit.get("base_id", unit["id"])
            rec["hero_name"] = unit.get("hero_name") or unit.get("name") or ""
            rec["slug"]      = unit.get("slug") or ""
        elif lookup in name_base:                    # c#### in HeroDatabase
            rec["hero_name"] = name_base[lookup]["name"]
            rec["slug"]      = name_base[lookup]["_id"]
        elif lookup in name_base_by_slug:            # filename uses kebab slug
            rec["hero_name"] = name_base_by_slug[lookup]["name"]
            rec["slug"]      = lookup
        emotes_list.append(rec)

    # Step 6: wallpaper gallery. Pulls four buckets and tags them by category:
    #   lobby   img_output/bgpack/*.{png,webp}           5 files  (~4 MB)
    #   event   img_output/item/art/lp_*.png             23 files (event splashes,
    #                                                              ML rerun, collab themes)
    #   episode img_output/episode/{_cm,cimg,img}_*.*    129 files (chapter art)
    #   story   img_output/story/bg/*.{png,webp}         filtered to skip the
    #                                                    _silhouette_ / _th /
    #                                                    blur variants that are
    #                                                    just low-res or alt-mood
    #                                                    versions of the same art
    # storytool_data is intentionally skipped: it's a folder of *prop* sheets
    # (clouds, tile cuts) the dev tooling assembles into scenes, not standalone
    # wallpapers.
    wp_dir = site_assets / "_wallpapers"
    wp_dir.mkdir(exist_ok=True)
    wallpapers: list[dict] = []
    seen_dst: set[str] = set()
    STORY_BG_SKIP = re.compile(r"(?:^|/|_)(?:silhouette|blur|_th)|_th\.|_blur\.", re.I)

    def humanise(stem: str, category: str) -> str:
        # Strip the dump-side prefixes that aren't part of the human name.
        s = stem
        if category == "event":
            s = re.sub(r"^lp_", "", s, flags=re.I)
        elif category == "episode":
            s = re.sub(r"^(?:_cm_|cimg_|img_)", "", s, flags=re.I)
        elif category == "story":
            s = re.sub(r"^bg_", "", s, flags=re.I)
        # Insert space between digits and letters so 2023summer -> 2023 summer.
        s = re.sub(r"(\d)([A-Za-z])", r"\1 \2", s)
        s = re.sub(r"([A-Za-z])(\d)", r"\1 \2", s)
        return s.replace("_", " ").strip().title()

    def add_wallpaper(src: Path, category: str, sub: str | None = None) -> None:
        # Copy under _wallpapers/<category>/[<sub>/]<file>. Skip duplicates by
        # destination path so a rebuild is idempotent.
        rel = Path(category)
        if sub: rel = rel / sub
        dst = wp_dir / rel / src.name
        rel_str = f"assets/_wallpapers/{rel.as_posix()}/{src.name}"
        if rel_str in seen_dst:
            return
        seen_dst.add(rel_str)
        dst.parent.mkdir(parents=True, exist_ok=True)
        if not dst.exists():
            try: shutil.copy2(src, dst)
            except OSError: return
        wallpapers.append({
            "file":     rel_str,
            "name":     humanise(src.stem, category),
            "stem":     src.stem,
            "category": category,
        })

    for p in sorted((img / "bgpack").iterdir() if (img / "bgpack").exists() else []):
        if p.suffix.lower() not in IMG_EXT: continue
        add_wallpaper(p, "lobby")

    art_dir = img / "item" / "art"
    if art_dir.exists():
        for p in sorted(art_dir.iterdir()):
            if p.suffix.lower() not in IMG_EXT: continue
            if not p.name.lower().startswith("lp_"): continue
            add_wallpaper(p, "event")

    ep_dir = img / "episode"
    if ep_dir.exists():
        for p in sorted(ep_dir.iterdir()):
            if p.suffix.lower() not in IMG_EXT: continue
            # Skip dev/test placeholders.
            if p.stem.lower().startswith("test"): continue
            add_wallpaper(p, "episode")

    story_bg = img / "story" / "bg"
    if story_bg.exists():
        for p in sorted(story_bg.iterdir()):
            if p.suffix.lower() not in IMG_EXT: continue
            if STORY_BG_SKIP.search(p.name):
                continue
            add_wallpaper(p, "story")

    # Step 7: write outputs.
    data = out / "data"
    data.mkdir(parents=True, exist_ok=True)
    (data / "units.json").write_text(
        json.dumps(sorted(units.values(), key=lambda u: u["id"]),
                   indent=1, ensure_ascii=False), "utf-8")
    updates_out = {}
    for c in KNOWN_UPDATES:
        banners = sorted(set(banners_per_code[c]))
        story   = sorted(set(story_per_code[c]))
        if not banners and not story:
            continue
        entry: dict = {"codename": c, "banners": banners}
        if story:
            entry["story"] = story
        updates_out[KNOWN_UPDATES[c]] = entry
    (data / "updates.json").write_text(
        json.dumps(updates_out, indent=1, ensure_ascii=False), "utf-8")
    (data / "emotes.json").write_text(
        json.dumps(emotes_list, indent=1, ensure_ascii=False), "utf-8")
    (data / "wallpapers.json").write_text(
        json.dumps(wallpapers, indent=1, ensure_ascii=False), "utf-8")
    (data / "artifacts.json").write_text(
        json.dumps(artifacts_out, indent=1, ensure_ascii=False), "utf-8")

    # Summary.
    by_kind: dict[str, int] = defaultdict(int)
    with_art = with_spine = with_name = with_skill = with_intimacy = 0
    for u in units.values():
        by_kind[u["kind"]] += 1
        if u["artworks"]: with_art += 1
        if u.get("spine"): with_spine += 1
        if u.get("name"): with_name += 1
        if u["skills"]: with_skill += 1
        if u.get("intimacy"): with_intimacy += 1
    print(f"\n[units] {len(units)} total")
    for k, n in sorted(by_kind.items(), key=lambda x: -x[1]):
        print(f"  {k:10s} {n}")
    print(f"\n[names]   {with_name} units with display name "
          f"(from HeroDatabase.json + HeroSkins.json)")
    print(f"[artwork] {with_art} units with at least one face PNG bundled")
    print(f"[skills]  {with_skill} units with S3 skill animation")
    print(f"[spine]   {with_spine} units with live-viewer JSON")
    print(f"[intim]   {with_intimacy} units with intimacy illustration")
    print(f"[emotes]  {len(emotes_list)} character emote groups "
          f"({sum(len(g['emotes']) for g in emotes_list)} files; "
          f"{sum(1 for g in emotes_list if g.get('base_id'))} linked to a unit)")
    print(f"[wallpr]  {len(wallpapers)} wallpapers")
    print(f"[updates] {len(updates_out)} codenames with banner art "
          f"({sum(len(v['banners']) for v in updates_out.values())} banners total) "
          f"out of {len(KNOWN_UPDATES)} known")
    named_arti = sum(1 for a in artifacts_out if a.get("name"))
    print(f"[arti]    {len(artifacts_out)} artifacts ({named_arti} named "
          f"from Artifacts.json, {len(artifacts_out)-named_arti} orphan)")
    print(f"\n-> {data / 'units.json'}\n-> {data / 'updates.json'}"
          f"\n-> {data / 'emotes.json'}\n-> {data / 'wallpapers.json'}"
          f"\n-> {data / 'artifacts.json'}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--img", required=True, help="img_output root (decoded PNGs)")
    ap.add_argument("--raw", required=True, help="output/ root (story paths for codename scan)")
    ap.add_argument("--out", default="./site")
    a = ap.parse_args()
    build(Path(a.img), Path(a.raw), Path(a.out))
