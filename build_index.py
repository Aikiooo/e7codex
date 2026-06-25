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
import argparse, html, json, os, re, shutil, sys
from collections import defaultdict
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent / "tools"))
from scsp_to_json import detect_version as _detect_scsp_version

# Codename pattern: v + 2-letter theme + (year-2020) digit + 'aa'.
# This map is a FALLBACK only — the in-game event titles come from
# data_external/codename_labels.json (built by tools/build_codename_labels.py
# from substory_main.db + text.db) and WIN on overlap. See load_event_labels().
# Year-tagged labels here stay around for codenames the DB doesn't carry yet,
# so the Updates view still has a meaningful heading even before a rebuild.
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

# Manual artifact names for art that ships ahead of the name data. New units'
# signature artifacts often arrive in img_output/item_arti before equip_item.db /
# text.db / the ceciliabot snapshot carry the name, so they'd otherwise render as
# nameless "ARTxxxx" orphans. Keyed by art_id; wins on name/rarity/role. DELETE an
# entry once the in-game DB or community snapshot supplies the name on its own.
MANUAL_ARTIFACTS: dict[str, dict] = {
    "art0244": {"name": "Butterfly's Baptism", "rarity": 5, "role": "thief"},  # Rhianna & Luciella (c2185), released 2026-06-04
    "art0241": {"name": "Refracted Desire", "rarity": 5, "role": "mage"},  # Eye of the Abyss Fumyr (c5147), released 2026-06-25
}

# Artifacts to withhold from the public site because they belong to an unreleased
# unit (the unreleased-unit guard covers units/voices/patches but NOT artifacts —
# they carry no unit link in the game data). Their _fu/_l images are dropped from
# site/assets/_artifacts so the deploy can't publish them. DELETE once the unit
# releases (then the artifact surfaces automatically).
UNRELEASED_ARTIFACTS: set[str] = {
    "art0243",   # Aubade Ludwig (c5069) — still in MANUAL_UNRELEASED
}

# A playable unit / artifact carries a "NEW" badge (and sorts to the top of its
# list) for this many days after it first appears released. See apply_new_flags.
NEW_WINDOW_DAYS = 21

# A unit carries a "MODIFIED" badge (and floats to the top of the hub, below NEW)
# for this many days after a curated change to an EXISTING unit — e.g. a new
# intimacy illustration added to an old hero. Declared, not auto-detected; see
# apply_modified_flags + data_external/modified.json.
MOD_WINDOW_DAYS = 14

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
    # 2026-06-25 release (bare rig is the scene, _1 is the character):
    "c5147":     {"label": "backdrop"},   # Eye of the Abyss Fumyr
    "c2113_s01": {"label": "backdrop"},   # Empyrean Ilynav skin
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
    """Make a name into a ceciliabot-style URL slug: 'Lionheart Cermia' ->
    'lionheart-cermia', "A Little Queen's Huge Crown" -> 'a-little-queens-huge-crown',
    'Air-to-Surface Missile: MISHA' -> 'airtosurface-missile-misha'. Matches
    ceciliabot's convention: punctuation (apostrophes, colons, intra-word hyphens)
    is DROPPED IN PLACE, not turned into a separator — only whitespace becomes a
    hyphen. Used to synthesise a slug when the community snapshot has none yet."""
    s = s.lower()
    s = re.sub(r"[^a-z0-9\s]", "", s)    # drop punctuation in place: queen's -> queens
    return re.sub(r"\s+", "-", s.strip())


def load_name_db(root: Path) -> tuple[dict, dict]:
    """Load HeroDatabase + HeroSkins, layer in the rtastats scrape, then
    overlay the in-game names_from_db.json.

    HeroDatabase carries the canonical kebab `_id` used by ceciliabot's URL
    routing (not present in the game data), so it remains the source for that.
    The rtastats fallback fills heroes the snapshot misses (c1144+).

    `names_from_db.json` (built by tools/build_names.py from the game's own
    character_player.db + text.db) is applied LAST and WINS on name / rarity /
    attribute / role — it covers ~700 c-slugs vs HeroDatabase's ~380 and is
    fully self-sufficient (see docs/TASKS.md #42). For c-slugs only the DB
    knows, we synthesise a kebab from the name so a ceciliabot link still has
    the right shape (may 404 on ceciliabot itself). Skin DISPLAY names stay
    with HeroSkins — the DB only carries the base hero's name per costume.
    """
    base: dict[str, dict] = {}
    skin: dict[str, dict] = {}
    p1 = root / "data_external" / "HeroDatabase.json"
    p2 = root / "data_external" / "HeroSkins.json"
    p3 = root / "data_external" / "HeroNames_rtastats.json"
    p4 = root / "data_external" / "names_from_db.json"
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
    if p4.exists():
        for code, rec in json.loads(p4.read_text("utf-8")).items():
            entry = base.get(code)
            if entry is None:
                entry = {"id": code, "_id": kebab(rec["name"])}
                base[code] = entry
            entry["name"] = rec["name"]           # in-game name wins
            for k in ("rarity", "attribute", "role"):
                if k in rec:
                    entry[k] = rec[k]
    return base, skin


def load_event_labels(root: Path) -> dict[str, str]:
    """Codename -> human event label, merged from the in-game DB and the
    legacy KNOWN_UPDATES fallback.

    `data_external/codename_labels.json` (built by tools/build_codename_labels.py
    from substory_main.db joined through text.db) carries the proper in-game
    event title for each codename (e.g. vsu5aa -> "Intense! Tropical Days!!").
    KNOWN_UPDATES is kept as the fallback for codenames the DB hasn't picked up
    yet — they still need a heading the user can read.

    Only updates-style codenames (v + 3 chars + 'aa', matching CODE_RE) flow
    into the Updates view. The DB also resolves story-style codenames
    (v1070a -> "My Knight Would Never!") and a handful of irregular shapes;
    those are returned too so future tabs can use them, but the path-token
    matcher in Step 4 deliberately narrows to updates-style.
    """
    labels: dict[str, str] = dict(KNOWN_UPDATES)
    p = root / "data_external" / "codename_labels.json"
    if p.exists():
        for code, lbl in json.loads(p.read_text("utf-8")).items():
            if lbl:
                labels[code] = lbl              # DB WINS on overlap
    return labels


def load_artifact_db(root: Path) -> dict[str, dict]:
    """Load the artifact catalog keyed by in-game id (`art####`).

    Two layers, applied in order; later wins on overlapping fields:

    1. `data_external/Artifacts.json` — community snapshot from ceciliabot
       (`https://ceciliabot.github.io/data/artifacts.json` cached locally).
       Source of `_id` (kebab url slug) and `tags`; neither is in the game data.
    2. `data_external/artifacts_from_db.json` — built by `tools/build_artifacts.py`
       from the game's own `equip_item.db` joined through `text.db`. Source of
       `name`, `rarity`, `role`, and `identifier`. Self-sufficient
       (`[[feedback-self-sufficient]]`) and a few entries ahead of the community
       snapshot when new artifacts ship.
    """
    by_id: dict[str, dict] = {}
    p = root / "data_external" / "Artifacts.json"
    if p.exists():
        for v in json.loads(p.read_text("utf-8")).values():
            gid = v.get("id")
            if isinstance(gid, str) and gid.startswith("art"):
                by_id[gid] = dict(v)   # copy so we can mutate
    # Layer the in-game source LAST: WINS on name/rarity/role + adds identifier.
    p_db = root / "data_external" / "artifacts_from_db.json"
    if p_db.exists():
        for aid, rec in json.loads(p_db.read_text("utf-8")).items():
            cur = by_id.setdefault(aid, {"id": aid})
            for k in ("name", "rarity", "role", "identifier"):
                v = rec.get(k)
                if v not in (None, "", 0):
                    cur[k] = v
    return by_id


def apply_new_flags(units: dict, artifacts: list, emotes: list, wallpapers: list) -> int:
    """Maintain data_external/first_seen.json (id -> first-seen ISO date) and flag
    units (kind=='unit'), artifacts, emote groups, and wallpapers seen within
    NEW_WINDOW_DAYS as `new` (plus `new_since`). Emote/wallpaper ledger keys are
    namespaced (`emote:` / `wp:`) so they can't collide with unit/artifact ids.

    Self-bootstrapping rollout: the first build that introduces a namespace (no
    key of that namespace is in the ledger yet) backdates its whole current batch
    to a sentinel old date, so the rollout does NOT flag every pre-existing asset
    as NEW. From then on a genuinely-new key is recorded at today's date and
    flags for the window — which also catches pre-staged unit releases that show
    as 'changed', not 'added', in the pack diff. The ledger is hand-editable:
    edit a date to extend/clear NEW, or delete an entry to re-flag it on the next
    build. Returns the count flagged."""
    import datetime
    path = Path(__file__).resolve().parent / "data_external" / "first_seen.json"
    ledger: dict = {}
    if path.exists():
        try: ledger = json.loads(path.read_text(encoding="utf-8"))
        except Exception: ledger = {}
    today = datetime.date.today().isoformat()
    SEED_OLD = "2025-01-01"   # backdate sentinel, well before any NEW window

    def seed(keys: list) -> None:
        # If the ledger already knows ANY of these keys, this namespace has been
        # rolled out → an unseen key is genuinely new (today). If it knows NONE,
        # this is the first build to see them → backdate the batch so nothing
        # floods the gallery with NEW badges.
        d = today if any(k in ledger for k in keys) else SEED_OLD
        for k in keys:
            ledger.setdefault(k, d)

    unit_keys  = [u["id"] for u in units.values() if u.get("kind") == "unit"]
    arti_keys  = [a["id"] for a in artifacts]
    emote_keys = [f"emote:{g['id']}" for g in emotes]
    wp_keys    = [f"wp:{w['file']}"  for w in wallpapers]
    for batch in (unit_keys, arti_keys, emote_keys, wp_keys):
        seed(batch)

    cutoff = (datetime.date.today() - datetime.timedelta(days=NEW_WINDOW_DAYS)).isoformat()
    n = 0
    def flag(obj: dict, key: str) -> None:
        nonlocal n
        if ledger.get(key, "") >= cutoff:
            obj["new"] = True; obj["new_since"] = ledger[key]; n += 1
    for u in units.values():
        if u.get("kind") == "unit": flag(u, u["id"])
    for a in artifacts:  flag(a, a["id"])
    for g in emotes:     flag(g, f"emote:{g['id']}")
    for w in wallpapers: flag(w, f"wp:{w['file']}")
    path.write_text(json.dumps(ledger, ensure_ascii=False, indent=0, sort_keys=True),
                    encoding="utf-8")
    return n


def apply_modified_flags(units: dict) -> int:
    """Flag EXISTING units changed recently (curated, not auto-detected) with
    `modified` / `modified_since` / `modified_parts`, for MOD_WINDOW_DAYS. Source
    is the hand-maintained, COMMITTED ledger data_external/modified.json:

        { "<unit_id>": {"since": "YYYY-MM-DD", "parts": ["intimacy", ...]}, ... }

    Unlike first_seen.json (auto-derived), this is declared: when you add a
    feature to an old unit (e.g. an animated intimacy illustration), add/refresh
    its entry here. The frontend shows a MODIFIED badge on the hub card (floats it
    up, below NEW) and on each named part of the detail page (`modified_parts`).
    Entries older than the window simply stop flagging; leave or prune them.
    Returns the count flagged."""
    import datetime
    path = Path(__file__).resolve().parent / "data_external" / "modified.json"
    if not path.exists():
        return 0
    try: ledger = json.loads(path.read_text(encoding="utf-8"))
    except Exception: return 0
    cutoff = (datetime.date.today() - datetime.timedelta(days=MOD_WINDOW_DAYS)).isoformat()
    n = 0
    for uid, info in ledger.items():
        u = units.get(uid)
        if not u or not isinstance(info, dict):
            continue
        since = info.get("since", "")
        if since >= cutoff:
            u["modified"] = True
            u["modified_since"] = since
            u["modified_parts"] = info.get("parts", [])
            n += 1
    return n


def apply_released_dates(units: dict) -> int:
    """Stamp each unit with `released` (ISO date) from the hand-curated release
    timeline at ../timeline/timeline.json (one dir above the repo, alongside the
    dump). The frontend hub sorts by this date in its default "Timeline" mode.

    The timeline is keyed by the in-game c-slug (`c1001`, `c2185_1`, …). We match
    a unit's own `id` first (so ML/seasonal/PRIMARY_SWAP `_1` forms get their own
    debut date), then fall back to `base_id` (so a skin like c1046_s02_1 inherits
    its base hero's date). Units with no timeline entry (NPCs, monsters, a few
    collab/test rigs) are left without `released` and the frontend sorts them
    after all dated units. Returns the count stamped."""
    path = Path(__file__).resolve().parent.parent / "timeline" / "timeline.json"
    if not path.exists():
        return 0
    try:
        tl = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return 0
    date_of: dict[str, str] = {}
    for rel in tl.get("releases", []):
        d = rel.get("date")
        if not d:
            continue
        for h in rel.get("heroes", []):
            hid = h.get("id")
            # First release wins (a hero appears once); guards stray dup ids.
            if hid and hid not in date_of:
                date_of[hid] = d
    n = 0
    for u in units.values():
        d = date_of.get(u.get("id")) or date_of.get(u.get("base_id"))
        if d:
            u["released"] = d
            n += 1
    return n


def inspect(img: Path, raw: Path, out: Path) -> None:
    """Read-only report (--inspect): staged slug counts by kind, name coverage,
    raw rig counts, and update codenames detected in path tokens. Writes
    nothing — useful before a full rebuild to spot drift."""
    site_assets = out / "assets"
    root = out.parent if out.name == "site" else Path(".")
    name_base, name_skin = load_name_db(root)
    event_labels = load_event_labels(root)

    dirs = ([d for d in sorted(site_assets.iterdir())
             if d.is_dir() and not d.name.startswith("_")
             and (d / "pose.png").exists()]
            if site_assets.exists() else [])
    by_kind: dict[str, int] = defaultdict(int)
    named = spined = combat = 0
    for d in dirs:
        slug = d.name
        by_kind[kind_of(slug)] += 1
        base_id, _, _ = split_variant(slug)
        if slug in name_skin or base_id in name_base:
            named += 1
        if (d / f"{slug}.json").exists():
            spined += 1
        if (d / "combat" / f"{slug}.json").exists():
            combat += 1
    print(f"[staged]  {len(dirs)} slugs with a baked pose")
    for k, n in sorted(by_kind.items(), key=lambda x: -x[1]):
        print(f"  {k:10s} {n}")
    print(f"[names]   {named} resolve a display name "
          f"({len(name_base)} base heroes + {len(name_skin)} skins known)")
    print(f"[spine]   {spined} with live-viewer JSON · {combat} with a combat rig")

    for sub in ("portrait", "model"):
        p = raw / sub
        if p.exists():
            n = sum(1 for f in p.iterdir() if f.suffix == ".scsp")
            print(f"[raw]     {sub}: {n} .scsp rigs")

    codes: set[str] = set()
    for p in walk(img / "banner"):
        codes |= {c.lower() for c in CODE_RE.findall(p.name.lower())}
    sb = img / "story" / "bg"
    if sb.exists():
        for p in sb.iterdir():
            codes |= {c.lower() for c in CODE_RE.findall(p.name.lower())}
    unlabeled = sorted(codes - event_labels.keys())
    print(f"[codes]   {len(codes)} codenames in banner/story tokens, "
          f"{len(codes) - len(unlabeled)} labeled"
          + (f" — unlabeled: {', '.join(unlabeled)}" if unlabeled else ""))
    print("\n(read-only — nothing written)")


def build(img: Path, raw: Path, out: Path) -> None:
    site_assets = out / "assets"
    if not site_assets.exists():
        raise SystemExit(f"no {site_assets} — run `python tools/prepare_assets.py --all` then "
                          "`node tools/render_poses.js` first")

    root = out.parent if out.name == "site" else Path(".")
    name_base, name_skin = load_name_db(root)
    event_labels = load_event_labels(root)   # codename -> human label (DB > KNOWN_UPDATES)

    # Unreleased-unit guard: slugs the game still labels "Unknown Hero" are
    # unannounced (placeholder rows in character_player.db; see
    # tools/build_names.py). They must not appear on the public site at all —
    # no listing here, and deploy.ps1 keeps their assets off R2 + Pages. The
    # flag flips to a real name a few days before release, so they surface
    # automatically once SG announces them.
    unreleased: set[str] = set()
    p_unrel = root / "data_external" / "unreleased_units.json"
    if p_unrel.exists():
        unreleased = set(json.loads(p_unrel.read_text("utf-8")).get("slugs", []))

    # Token form for art whose FILENAME references an unreleased unit but doesn't
    # resolve to a staged slug — e.g. wallpaper `img_intimacy_illust_c5069` or
    # banner `gacha_c5069_01_bg`. The unit-dir guard above never sees these, so
    # the wallpaper/emote builders below filter on this. Split on non-alphanumeric
    # because '_c5069_' has no word boundary for a `\b`-anchored regex.
    _unrel_tokens = ({u.lower() for u in unreleased}
                     | {u.split("_")[0].lower() for u in unreleased})
    def refs_unreleased(name: str) -> bool:
        return bool(set(re.split(r"[^a-z0-9]+", name.lower())) & _unrel_tokens)

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
    # Drop unreleased units (by slug OR base hero slug) before anything sees
    # them — keeps them out of units.json, extras, emote links, everything.
    n_dirs_before = len(all_dirs)
    all_dirs = [d for d in all_dirs
                if d.name not in unreleased
                and split_variant(d.name)[0] not in unreleased]
    n_hidden = n_dirs_before - len(all_dirs)
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
            # .scsp isn't locatable.
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
            # Dual-rig units (e.g. c2185_1 Rhianna & Luciella) stage a
            # combat/rigs.json manifest listing each rig + a display label; the
            # viewer renders a rig <select> from it. The primary's file is
            # always <slug>.json, so the default load path is unchanged.
            rigs_manifest = d / "combat" / "rigs.json"
            if rigs_manifest.exists():
                unit["combat_rigs"] = json.loads(rigs_manifest.read_text(encoding="utf-8"))

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
    # NOTE: only the `img_intimacy_illust_<slug>.webp` (story/bg) is the real
    # fully-rendered illustration. `img_illust_<slug>.png` (item/art) and
    # `sp_illust_<slug>_th.webp` are SELECTION THUMBNAILS, not the art — do NOT
    # treat them as the illustration (the in-game illustration is animated w/ voice;
    # its real static/animated source is still being identified, see TASKS).
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

    # Step 3b-2: animated intimacy illustrations (preferred). A few units ship the
    # intimacy art as a multi-layer Spine effect rig (output/effect/uieff_illust_*),
    # not a static webp — baked offline (composited + cropped to the picture
    # rectangle) into assets/<slug>/intimacy.webm. When that file is present it WINS
    # over the static webp; the frontend renders a looping <video> instead of an
    # <img>. Currently c1153 (Harsetti); c2181_1 (Notos) pending.
    for uid, u in units.items():
        webm = site_assets / uid / "intimacy.webm"
        if webm.exists():
            # Append a content-version query (file mtime) so a re-baked clip gets a
            # NEW URL: the filename never changes, so Cloudflare's edge would keep
            # serving the stale copy for hours after a redeploy (a redeploy does not
            # evict the edge cache). The query is part of the CF cache key, so each
            # new bake is a guaranteed cache miss → fresh fetch. units.json itself is
            # served DYNAMIC (uncached), so the new query reaches clients immediately.
            ver = int(webm.stat().st_mtime)
            u["intimacy"] = f"assets/{uid}/intimacy.webm?v={ver}"
        # Voice-triggered reaction clips (silent): intimacy_<kind>_<n>.webm, each with
        # a poster intimacy_<kind>_<n>.jpg. The frontend shows them as a clickable row
        # under the idle illustration (open in the video lightbox). Labelled from the
        # filename: enter -> "Greeting", touch -> "Touch".
        reacts = sorted((site_assets / uid).glob("intimacy_*.webm"))
        if reacts:
            LBL = {"enter": "Greeting", "touch": "Touch"}
            rlist = []
            for p in reacts:
                parts = p.stem.split("_")        # intimacy_enter_1 -> [intimacy, enter, 1]
                kind, num = (parts[1], parts[-1]) if len(parts) >= 3 else (parts[-1], "")
                poster = site_assets / uid / f"{p.stem}.jpg"
                rlist.append({
                    "webm": f"assets/{uid}/{p.name}",
                    "poster": f"assets/{uid}/{p.stem}.jpg" if poster.exists() else None,
                    "label": f"{LBL.get(kind, kind.title())} {num}".strip(),
                })
            u["intimacy_reactions"] = rlist

    # Step 4: update gallery — copy banner art + story images per KNOWN_UPDATE codename.
    updates_dir = site_assets / "_updates"
    updates_dir.mkdir(exist_ok=True)
    banners_per_code: dict[str, list[str]] = defaultdict(list)
    story_per_code:  dict[str, list[str]] = defaultdict(list)
    STORY_SKIP = re.compile(r"_th\.|_blur\.|(?:^|_)silhouette", re.I)

    for p in walk(img / "banner"):
        if p.suffix.lower() not in IMG_EXT: continue
        codes = {c.lower() for c in CODE_RE.findall(p.name.lower())} & event_labels.keys()
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
            codes = {c.lower() for c in CODE_RE.findall(p.name.lower())} & event_labels.keys()
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
            if aid in UNRELEASED_ARTIFACTS:
                # Belongs to an unreleased unit — never stage/publish it, and
                # purge any copy a prior build left behind.
                if dst.exists():
                    try: dst.unlink()
                    except OSError: pass
                continue
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
        rec = {**artifact_db.get(aid, {}), **MANUAL_ARTIFACTS.get(aid, {})}
        entry: dict = {"id": aid, "art_full": paths["full"]}
        if "lobby" in paths: entry["art_lobby"] = paths["lobby"]
        if rec.get("name"):       entry["name"]    = rec["name"]
        if rec.get("_id"):        entry["slug"]    = rec["_id"]
        if rec.get("rarity"):     entry["rarity"]  = rec["rarity"]
        if rec.get("role"):       entry["role"]    = rec["role"]
        if rec.get("_id"):
            entry["cecilia"] = f"{CECILIA_ARTIFACT}/{rec['_id']}"
        elif rec.get("name"):
            # No community kebab yet (e.g. a manually-named brand-new artifact):
            # synthesise one from the name — the same deterministic shape ceciliabot
            # uses — so the link resolves once ceciliabot adds the artifact (may 404
            # until then), mirroring the new-hero kebab fallback. NEVER point an
            # artifact at the HEROES index (the prior bug for the 3 NEW artifacts).
            entry["cecilia"] = f"{CECILIA_ARTIFACT}/{kebab(rec['name'])}"
        else:
            entry["cecilia"] = CECILIA_ARTIFACT
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
            if eid in unreleased or refs_unreleased(eid):
                # Emote art for an unreleased unit — withhold + purge a stale copy.
                dst0 = emotes_dir / p.name
                if dst0.exists():
                    try: dst0.unlink()
                    except OSError: pass
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
        if refs_unreleased(src.stem):
            # Unreleased-unit art (e.g. img_intimacy_illust_c5069) — never publish,
            # and purge any copy a prior build staged before the guard existed.
            if dst.exists():
                try: dst.unlink()
                except OSError: pass
            return
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
            if p.stem.lower() in {"black", "white"}:
                continue   # solid-colour utility screens — not real backgrounds
            add_wallpaper(p, "story")

    # Flag newly-seen units/artifacts/emotes/wallpapers (first_seen ledger) +
    # float artifacts up (units sort new-first in the frontend; emotes/wallpapers
    # float up there too).
    n_new = apply_new_flags(units, artifacts_out, emotes_list, wallpapers)
    n_mod = apply_modified_flags(units)
    n_rel = apply_released_dates(units)
    artifacts_out.sort(key=lambda a: (not a.get("new"),
                                      -(a.get("rarity") or 0), a["id"]))

    # Step 7: write outputs.
    data = out / "data"
    data.mkdir(parents=True, exist_ok=True)
    (data / "units.json").write_text(
        json.dumps(sorted(units.values(), key=lambda u: u["id"]),
                   indent=1, ensure_ascii=False), "utf-8")
    updates_out = {}
    # Only iterate over codenames that picked up any art — keeps the JSON tight
    # even though event_labels now has 100+ entries (most have no on-disk assets).
    for c in sorted(set(banners_per_code) | set(story_per_code)):
        banners = sorted(set(banners_per_code[c]))
        story   = sorted(set(story_per_code[c]))
        if not banners and not story:
            continue
        entry: dict = {"codename": c, "banners": banners}
        if story:
            entry["story"] = story
        # Year-digit at position 3 for 6-char codenames (vsu5aa -> 5 -> 2025).
        # 5-char shapes (vyunaa, vresaa, vrimaa, vreaaa, vasiaa) don't encode
        # a year — frontend falls back to alphabetical for those.
        if len(c) == 6 and c[3].isdigit():
            entry["year"] = 2020 + int(c[3])
        label = event_labels.get(c, c)   # codename itself is the last-resort heading
        updates_out[label] = entry
    (data / "updates.json").write_text(
        json.dumps(updates_out, indent=1, ensure_ascii=False), "utf-8")
    (data / "emotes.json").write_text(
        json.dumps(emotes_list, indent=1, ensure_ascii=False), "utf-8")
    (data / "wallpapers.json").write_text(
        json.dumps(wallpapers, indent=1, ensure_ascii=False), "utf-8")
    (data / "artifacts.json").write_text(
        json.dumps(artifacts_out, indent=1, ensure_ascii=False), "utf-8")

    # Step 8: SEO prerender stubs — one static page per base hero at /u/<base>,
    # plus sitemap.xml + robots.txt. The SPA routes by hash (#/u/<base>), which
    # crawlers don't index, so heroes were invisible to search; these stubs give
    # each one a crawlable URL with a real <title>/description/OG image, then
    # bounce human visitors to the hash route. Cloudflare Pages serves /u/<base>
    # from u/<base>.html natively (automatic .html resolution). Units here have
    # already passed the unreleased guard, so stubs can't leak; stale stubs for
    # pulled/renamed bases are pruned each build.
    SITE_ORIGIN = "https://e7codex.com"
    u_dir = out / "u"
    u_dir.mkdir(exist_ok=True)
    stub_bases: dict[str, list[dict]] = defaultdict(list)
    for u in units.values():
        stub_bases[u.get("base_id") or u["id"]].append(u)
    for base, group in stub_bases.items():
        rep = next((x for x in group if not x.get("variant")), group[0])
        name = rep.get("hero_name") or rep.get("name") or base
        forms = f" {len(group)} forms." if len(group) > 1 else ""
        desc = (f"{name} — Epic Seven artwork, baked poses and a live Spine "
                f"viewer on E7 Codex.{forms}")
        e = html.escape
        pose_url = f"{SITE_ORIGIN}/{rep['pose']}"
        page_url = f"{SITE_ORIGIN}/u/{base}"
        (u_dir / f"{base}.html").write_text(f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>{e(name)} — E7 Codex</title>
<meta name="description" content="{e(desc)}">
<link rel="canonical" href="{page_url}">
<meta property="og:site_name" content="E7 Codex">
<meta property="og:title" content="{e(name)} — E7 Codex">
<meta property="og:description" content="{e(desc)}">
<meta property="og:type" content="website">
<meta property="og:url" content="{page_url}">
<meta property="og:image" content="{pose_url}">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{e(name)} — E7 Codex">
<meta name="twitter:image" content="{pose_url}">
<script>location.replace("/#/u/{base}");</script>
</head>
<body>
<p><a href="/#/u/{base}">{e(name)} on E7 Codex — artwork &amp; pose archive</a></p>
</body>
</html>
""", "utf-8")
    valid_stubs = {f"{b}.html" for b in stub_bases}
    n_pruned = 0
    for p in u_dir.glob("*.html"):
        if p.name not in valid_stubs:
            p.unlink()
            n_pruned += 1
    urls = [f"{SITE_ORIGIN}/"] + [f"{SITE_ORIGIN}/u/{b}" for b in sorted(stub_bases)]
    (out / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "".join(f"  <url><loc>{u}</loc></url>\n" for u in urls)
        + "</urlset>\n", "utf-8")
    (out / "robots.txt").write_text(
        f"User-agent: *\nAllow: /\nSitemap: {SITE_ORIGIN}/sitemap.xml\n", "utf-8")

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
    if n_hidden:
        print(f"\n[hidden]  {n_hidden} unreleased unit(s) suppressed "
              f"(game flag 'Unknown Hero')")
    print(f"\n[names]   {with_name} units with display name "
          f"(from HeroDatabase.json + HeroSkins.json + names_from_db.json)")
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
          f"out of {len(event_labels)} labeled "
          f"(KNOWN_UPDATES={len(KNOWN_UPDATES)} + DB join)")
    named_arti = sum(1 for a in artifacts_out if a.get("name"))
    print(f"[arti]    {len(artifacts_out)} artifacts ({named_arti} named "
          f"from Artifacts.json + artifacts_from_db.json, "
          f"{len(artifacts_out)-named_arti} orphan)")
    print(f"[new]     {n_new} unit/artifact/emote/wallpaper flagged new "
          f"(first-seen within {NEW_WINDOW_DAYS}d; first_seen.json)")
    print(f"[upd]     {n_mod} unit(s) flagged updated "
          f"(within {MOD_WINDOW_DAYS}d; modified.json)")
    print(f"[date]    {n_rel} unit(s) stamped with release date "
          f"(timeline/timeline.json)")
    print(f"[seo]     {len(stub_bases)} prerender stubs in site/u/ + sitemap.xml"
          + (f" ({n_pruned} stale pruned)" if n_pruned else ""))
    print(f"\n-> {data / 'units.json'}\n-> {data / 'updates.json'}"
          f"\n-> {data / 'emotes.json'}\n-> {data / 'wallpapers.json'}"
          f"\n-> {data / 'artifacts.json'}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--img", required=True, help="img_output root (decoded PNGs)")
    ap.add_argument("--raw", required=True, help="output/ root (story paths for codename scan)")
    ap.add_argument("--out", default="./site")
    ap.add_argument("--inspect", action="store_true",
                    help="read-only report (no files written)")
    a = ap.parse_args()
    if a.inspect:
        inspect(Path(a.img), Path(a.raw), Path(a.out))
    else:
        build(Path(a.img), Path(a.raw), Path(a.out))
