"""Hand-edited tables for the site index — the file to open on a new pack.

Everything here is maintained BY HAND; the build only reads it. Which one to
touch when:

  a unit ships art ahead of the name data ............... MANUAL_NAMES
  a unit is announced but not yet in gacha .............. ANNOUNCED (+ `video`)
  a new unit's artifact ships before its name .......... MANUAL_ARTIFACTS
  an unreleased unit's artifact must be withheld ........ UNRELEASED_ARTIFACTS
  a backdrop/character `_1` pair is spotted ............ PRIMARY_SWAP, or
                                                         PRIMARY_SWAP_EXCEPT when
                                                         X_1 is an alternate rig
                                                         of the SAME character
  one character ships under two unrelated ids .......... SLUG_PARENT
  a unit's signature artifact is missing ............... SIGNATURE_ARTIFACTS
  an event still has no v####aa token in its filename .. UPDATE_EXTRA_STORY
  an event codename has no DB label yet ................ KNOWN_UPDATES
  a wallpaper-worthy background must be picked by hand . BANNER_WALLPAPERS /
                                                         IMG_WALLPAPERS /
                                                         SANCTUARY_WALLPAPERS
  a badge window should change ......................... NEW_WINDOW_DAYS /
                                                         MOD_WINDOW_DAYS

Everything derived from these (slug parsing, merge order, the auto backdrop
rule) lives in the sibling modules.
"""
from __future__ import annotations

import re

from . import REPO_ROOT

# Codename pattern: v + 2-letter theme + (year-2020) digit + 'aa'.
# This map is a FALLBACK only — the in-game event titles come from
# data_external/codename_labels.json (built by pipeline/codenames.py
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

# Manual unit names for officially announced units whose art ships ahead of any
# character_player*.db row (so names_from_db has nothing). Applied only when no other
# layer names the slug, so the in-game name takes over by itself once the DB has it.
# Name = the official announcement's title card, nothing else (no guessed rarity/
# element/class). DELETE an entry once names_from_db carries the slug.
MANUAL_NAMES: dict[str, dict] = {
    # Official global trailer "Secret Rabbit Hole, Come Party With Us" (owner, 2026-10-29).
    "c5002": {"name": "Bunny Girl Maid Cecilia"},
}

# Manual artifact names for art that ships ahead of the name data. New units'
# signature artifacts often arrive in img_output/item_arti before equip_item.db /
# text.db / the ceciliabot snapshot carry the name, so they'd otherwise render as
# nameless "ARTxxxx" orphans. Keyed by art_id; wins on name/rarity/role. DELETE an
# entry once the in-game DB or community snapshot supplies the name on its own.
MANUAL_ARTIFACTS: dict[str, dict] = {
    "art0244": {"name": "Butterfly's Baptism", "rarity": 5, "role": "thief"},  # Rhianna & Luciella (c2185), released 2026-06-04
    "art0243": {"name": "Aubade Orb", "rarity": 5, "role": "ranger"},  # Aubade Ludwig (c5069), released 2026-06-11
    "art0241": {"name": "Refracted Desire", "rarity": 5, "role": "mage"},  # Eye of the Abyss Fumyr (c5147), released 2026-06-25
    # art0247 (efa34) — Mei Lin (c1191), released 2026-10-08. text.db carries no
    # efa34_name in ANY language this pack, so the name comes from the ceciliabot
    # snapshot; the role comes from the game's own row (equip_item.db role column
    # = 'assassin'), which overrides that snapshot's stale "warrior". DELETE once
    # the game (or the community snapshot) supplies the name itself.
    "art0247": {"name": "Flame Dragon's Jewel", "rarity": 5, "role": "assassin"},
}

# Artifacts to withhold from the public site because they belong to an unreleased
# unit (the unreleased-unit guard covers units/voices/patches but NOT artifacts —
# they carry no unit link in the game data). Their _fu/_l images are dropped from
# site/assets/_artifacts so the deploy can't publish them. DELETE once the unit
# releases (then the artifact surfaces automatically).
# (Nothing held as of 2026-10-08.) art0247 efa34 — Mei Lin's (c1191) 5★ assassin
# exclusive — was unheld on owner confirmation; its name key efa34_name is absent
# from EVERY language's text.db in this pack, so the display name comes from
# MANUAL_ARTIFACTS below until the game or the community snapshot carries it.
# History: art0243 "Aubade Orb" released 2026-06-11 (c5069); art0245 "Intoxicating
# Indulgence" released 2026-07-23 (c5190); art0249 "Light and Darkness" released
# 2026-09-03 (c5112).
UNRELEASED_ARTIFACTS: set[str] = set()

# Officially announced but not yet in gacha / fully live. Public on the site
# with an ANNOUNCED badge (not NEW). When today >= `release` (ISO date), the
# announced flag clears and the normal first_seen NEW window applies.
# Match keys: unit base/id (c5190 covers c5190_1) and/or artifact art####.
# Optional `video` = official kit/preview URL (shown on detail + artifact zoom).
ANNOUNCED: dict[str, dict] = {
    # (Empty as of 2026-10-08.) History: c5190 Aube + art0245 released 2026-07-23;
    # c5112 Uncharted Pioneer Politis + art0249 released 2026-09-03; Haru (c1192)
    # released 2026-09-17; Renoa (c1193) released 2026-09-23 — her art0248 "Sorrow
    # of the Rose" shipped WITH her (owner-confirmed 2026-10-08), so it is no longer
    # announced; Mei Lin (c1191) released 2026-10-08 (gacha_c1191 banner + meilin.timeline).
    # c7016_1 Bunny Girl Mafia Yufine — announced (owner, 2026-10-29; rig shipped in
    # SSRA pack 12). STOVE notice: preview video event 11/5 03:00 – 11/26 02:59 UTC,
    # release expected with it -> NEW from 2026-11-05.
    "c7016_1": {
        "release": "2026-11-05",
        "video": "https://www.youtube.com/watch?v=nnn3L8gc3w0",
    },
    # c5002 Bunny Girl Maid Cecilia — shown (name, animations, illustration) in the
    # official global trailer "Secret Rabbit Hole, Come Party With Us" (owner,
    # 2026-10-29). Not in any player DB yet; no release date announced.
    "c5002": {
        "video": "https://www.youtube.com/watch?v=5R6fVVEmy3I",
    },
}

# Manual unit base → signature art#### (keep in sync with
# pipeline/enrich_updates.py SIGNATURE_ARTIFACTS). Prepends over
# data_external/artifact_owners.json for detail-page + Updates Featured.
# Owners file is the long-term bulk map; this covers brand-new EE gaps.
SIGNATURE_ARTIFACTS: dict[str, list[str]] = {
    "c5147": ["art0241"],  # Eye of the Abyss Fumyr — Refracted Desire
    "c5069": ["art0243"],  # Aubade Ludwig — Aubade Orb
    "c2185": ["art0244"],  # Rhianna & Luciella — Butterfly's Baptism
    "c5190": ["art0245"],  # Aube — Intoxicating Indulgence
    "c5112": ["art0249"],  # Uncharted Pioneer Politis — Light and Darkness
    "c1193": ["art0248"],  # Renoa — Sorrow of the Rose (unique new ranger ↔ art0248)
    "c1192": ["art0246"],  # Haru — Custom-Made Power Anchor
    "c1191": ["art0247"],  # Mei Lin — Flame Dragon's Jewel (efa34 5★ assassin exclusive)
    # Early covenant timeline mispairs (see pipeline/artifact_owners_repair.py):
    "c1023": ["art0109"],  # Kayron — Shepherd of the Hollow (NOT Celestine)
    "c1076": ["art0032"],  # Diene — Celestine (NOT Noble Oath)
}

# Event-gallery stills whose filenames do NOT contain the v####aa token, so the
# banner/story path scan never attaches them. Paths relative to img_output.
UPDATE_EXTRA_STORY: dict[str, list[str]] = {
    "vsu4aa": [  # Summer 2024 — Epic Dash Solitaria/Eda track
        "img/bg_epicdash_main.png",
        "story/bg/img_epicdash_2024.webp",
    ],
    "vsu5aa": [  # Summer 2025 — Epic Dash Aram/Hwayoung/Adin
        "story/bg/img_event_epicdash.webp",
        "story/bg/img_epicdash_2025.webp",
    ],
    "vsu6aa": [  # Summer 2026 — Epic Dash Fumyr/Aube underwater
        "img/bg_epicdash_main_1.png",
        "img/bg_epicdash_main_2.png",
        "img/bg_epicdash_moonlight.png",
    ],
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
    "c5069":     {"label": "backdrop"},   # Aubade Ludwig — bare rig is bg/sky+clouds+moon
    "c6024":     {"label": "backdrop"},
    # 2026-06-25 release (find_backdrops.py: bare rig is the scene, _1 is the char):
    "c5147":     {"label": "backdrop"},   # Eye of the Abyss Fumyr — 80% backdrop slots
    "c2148":     {"label": "backdrop"},   # 98% backdrop slots
    "c5190":     {"label": "backdrop"},   # underwater coral scene; detector false-negative
                                          # (0% — its slot names don't match BACKDROP_RE),
                                          # confirmed visually: bare=reef, _1=character.
    "c2113_s01": {"label": "backdrop"},   # Empyrean Ilynav skin; bare rig renders blank/
                                          # near-empty, _1 carries the character (detector
                                          # 1% — false-negative). All 4 of this release's
                                          # new units ship scene-bare + character-_1.
    "c1126_s01": {"label": "backdrop"},   # Lua skin (2026-08 release) — bare rig is the
                                          # snow/temple scene, _1 is the character.
    "c5112":     {"label": "backdrop"},   # Uncharted Pioneer Politis — bare is scene.
}

# Second-rig releases: a (X, X_1) pair where BOTH dirs are staged is treated
# as a backdrop/character split by default — the bare slug ships the scene
# (table, curtains, sound stage, sky, snowfield) and X_1 carries the character.
# Every pair staged so far is exactly that split (c1046_s02, c1180, c1183,
# c2076, c2112_s01, c2113_s01, c2148, c2181, c2184, c2185, c5069, c5147,
# c5190, c6024, c1126_s01, c5112). Add to PRIMARY_SWAP_EXCEPT only for the rare rig
# where X_1 is an alternate rig of the SAME character rather than a scene
# split — the auto rule is a default, not a law.
PRIMARY_SWAP_EXCEPT: set[str] = set()

def effective_swap_map(staged: set[str]) -> dict[str, dict]:
    """Full backdrop-swap map for a staging set: explicit PRIMARY_SWAP entries
    plus auto-detected (X, X_1) pairs. Auto entries default to the "backdrop"
    label; explicit entries win for label overrides. Single source of truth —
    also used by pipeline/find_backdrops.py (audit) and
    pipeline/prepare_combat_assets.py (combat-rig routing) so the tools can't
    drift from the site build."""
    out: dict[str, dict] = {}
    for slug in staged:
        if slug.endswith(EXTRA_SUFFIX) and len(slug) > len(EXTRA_SUFFIX):
            bare = slug[: -len(EXTRA_SUFFIX)]
            if bare in staged and bare not in PRIMARY_SWAP_EXCEPT:
                out.setdefault(bare, {"label": "backdrop"})
    for bare, meta in PRIMARY_SWAP.items():
        out[bare] = meta
    return out

# Arbitrary slug → parent mappings that don't follow the _1 suffix convention.
# Each entry is attached as an extra rig on the parent's detail page (no hub
# card of its own). Use when the same character ships under two unrelated IDs
# (e.g. an older lobby-only rig alongside the full battle rig released later,
# or a non-playable story/event alias that reuses the playable hero's name).
SLUG_PARENT: dict[str, dict] = {
    "c1084":  {"parent": "c1142", "label": "lobby rig"},          # Eligos legacy 2.1.27 sprite
    "c1007t": {"parent": "c1007", "label": "non-playable alias"},  # Vildred story/event instance
}

# ── curated wallpaper picks (hand-checked; the scans are next door) ──────────

# Hand-picked banner/ backgrounds promoted into the wallpaper gallery
# (category "event"). banner/ is not auto-scanned — see wallpapers.py.
BANNER_WALLPAPERS = [
    "ai_match_event_bg_1.png",     # AI Match event (2026-08)
    "ai_match_event_bg_2.png",
    # gacha_cg_260813_bg.png NOT included: same art as the existing
    # full-res story wallpaper windcloud_beach (2370x1080) at 1600x720.
    # event_8th_bg.png NOT included: same art as story/bg/img_2026_8th_event.webp
    # (2400x1080) at 1600x720.
    "gacha_c5112_01_bg.png",  # Uncharted Pioneer Politis gacha BG (released 2026-09-03)
    "promo_pvp_chaos_bg.png",                 # Call of Chaos key art (2026-08-27)
    "promo_e7wc_2026_preliminary_bg.png",     # E7WC 2026 prelim key art
    "event_2026e7wc_cheering.png",            # E7WC 2026 ice-cave plate
    "evert_8yr_bg.png",                       # 8th-anniversary lantern bokeh
]
# img/ is UI chrome by default; only full-bleed backgrounds go here.
IMG_WALLPAPERS = [
    "bg_monolith_main.png",          # Call of Chaos / chess-hall
    "event_payback_enhance_bg.png",  # Charm Payback forge
    # Epic Dash UI panoramas (img/ is not auto-scanned). Distinct from the
    # 16:9 story/bg artbook crops (img_epicdash_2024/2025, img_event_epicdash).
    "bg_epicdash_main.png",          # 2024 track: Solitaria + Eda, 2440x720
    "bg_epicdash_main_1.png",        # 2026 underwater: Fumyr + Aube swim, 2580x720
    "bg_epicdash_main_2.png",        # 2026 underwater: Fumyr + Aube sit, 2580x720
    "bg_epicdash_moonlight.png",     # dash moonlight stage BG, 1600x720
]
# Full stills that live outside img_output (lobby-bake masters).
EXTRA_WALLPAPERS = [
    (
        REPO_ROOT / "render" / "illust" / "bgeff_epic_dash_2026_still.png",
        "event",
    ),
    (
        REPO_ROOT / "render" / "illust" / "bgeff_epic_dash_2026_still_sun.png",
        "event",
    ),
]
WP_NAME = {
    "bgeff_epic_dash_2026_still": "Epic Dash 2026",
    "bgeff_epic_dash_2026_still_sun": "Epic Dash 2026 (sun)",
}

# Sanctuary hub backgrounds (img_output/sanctuary/). The folder also ships
# 330x270 building-slot thumbnails (aurora/craft/forest/orbis/subtask) and
# the raw sprite-sheet textures (sanctuary_day/night.png — atlas layouts,
# NOT composed scenes; do NOT ship those). The wallpapers below are the
# BAKED facility scenes (eff_sanc_* CFX composites, rank-1/2 rig data,
# union-AABB framing + computed art crops — see recipes.json sanc_* packs).
SANCTUARY_WALLPAPERS = [
    "sanctuary_orbis_day.png",      # Orbis (World Tree), day
    "sanctuary_orbis_night.png",    # Orbis (World Tree), night
    "sanctuary_forest_day.png",     # Forest of Souls, day
    "sanctuary_forest_night.png",   # Forest of Souls, night
    "sanctuary_alchemy_day.png",    # Archemist (Aurora) workshop, day
    "sanctuary_alchemy_night.png",  # Archemist (Aurora) workshop, night
]
