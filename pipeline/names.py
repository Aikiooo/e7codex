"""Build data_external/names_from_db.json — self-sufficient hero names + metadata.

Pulls display name + rarity + attribute + role straight from the game's own
encrypted tables, replacing the community-JSON dependency for that data
(see docs/TASKS.md #42 / #45). Joins two decrypted tables:

  text/en/text.db            -> {export_id: text}   (chrn_* -> "Ras", ...)
  db/character_player.db     -> per c-slug row; cols (fixed 98-wide schema):
                                  [0]  id (c-slug, incl. costume slugs)
                                  [3]  name key  (chrn_<base>)
                                  [4]  rarity    ("3".."6")
                                  [7]  attribute (fire/ice/wind/light/dark)
                                  [8]  role/class (warrior/knight/ranger/mage/
                                                   manauser/assassin/material)
                                  [20] combat model name (output/model/<name>.scsp)

Output (data_external/names_from_db.json), keyed by c-slug:
  { "c1001": {"name":"Ras","rarity":3,"attribute":"fire","role":"knight"}, ... }

Also emits data_external/model_map_from_db.json — { c-slug: model_name } from
col[20]. This is the AUTHORITATIVE c-slug -> combat-rig-filename map (handles
romanizations, ML/seasonal forms, and internal codenames that the ceciliabot
kebab can't), consumed by prepare_combat_assets.py to map output/model/*.scsp
rigs to their unit without hand-maintained alias/override tables. Unreleased
slugs are excluded here too (never stage an unannounced unit's rig).

The attribute + role vocabulary is identical to HeroDatabase.json (the frontend
aliases manauser->soul-weaver / assassin->thief at render time), so the output
is a drop-in metadata source. Skin DISPLAY names (sn_* keys, e.g. "Arbiter
Vildred") are NOT in character_player.db — costume rows reuse the base hero's
chrn_ key — so HeroSkins.json stays the source for those. The ceciliabot kebab
(URL slug) likewise isn't in the game data and still comes from HeroDatabase.

UNRELEASED GUARD: the game ships placeholder rows for unannounced units whose
name key resolves to the literal "Unknown Hero" (~168 reserved future slots).
Those names are NOT written to names_from_db.json — both to avoid clobbering a
real community name (e.g. c6023 leaked as "Acolyte of the End Kayron") and
because the label is the game's own authoritative "not yet announced" signal.
Their c-slugs are emitted to data_external/unreleased_units.json instead; the
build + deploy pipeline uses that list to keep them off the **public** site
(no units.json / R2 / Pages). Local builds still materialize full character
pages into units_unreleased.json for localhost / tunnel preview.

MANUAL_UNRELEASED covers announced-but-not-yet-released heroes (real name already
in the DB, so the Unknown-Hero signal misses them). They stay ON the hold list
but KEEP their name/rarity/model_map so local pages are complete — only publish
is blocked. DELETE the manual entry once the unit launches.

Cipher reference: GAMEBIN_CRACK_FINDINGS.md + memory reference-e7-text-db-format.
The cocos-XXTEA + outer-XOR + CDBM primitives live in e7lib.dbcrypto (they used
to be copied into this file and three other builders) and are re-exported below,
so `import build_names; build_names.cdbm_rows(...)` still works. Keys and dump
path are local-only via private/keys/voice_keys.json (gitignored).
"""
import json, sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]   # repo root: makes e7lib importable
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import e7lib.config as config  # noqa: E402
from e7lib import dbcrypto  # noqa: E402
from e7lib.dbcrypto import (  # noqa: E402  re-exported for existing importers
    M, DELTA, xxtea_dec, load_keymap, decrypt_value, walk_cdbm,
    outer_decrypt_textdb, outer_decrypt_db, cdbm_rows, decode_db_rows)

# A build step, not a library: without local keys nothing can be decoded, so say
# so at import time.
_CFG = config.require_keys('copy from build_voices.py setup '
                           '(dump_dir, outer_key_file, default_xxtea_key)')
sys.path.insert(0, str(Path(__file__).parent))
from e7lib.config import RAW_DIR  # noqa: E402  central data-dir config
OUT_DB = RAW_DIR / 'db'
TEXT_DB = RAW_DIR / 'text' / 'en' / 'text.db'
DATA_EXTERNAL = Path(__file__).resolve().parents[1] / 'data_external'

ELEMENTS = {'fire', 'ice', 'wind', 'light', 'dark'}
ROLES = {'warrior', 'knight', 'ranger', 'mage', 'manauser', 'assassin'}
UNRELEASED_NAME = 'Unknown Hero'   # game's placeholder for unannounced units
# Manually-suppressed units that are ANNOUNCED (so they already carry a real name
# and the 'Unknown Hero' auto-signal misses them) but NOT YET RELEASED. Hosting
# pre-release art is the highest DMCA risk (see CLAUDE.md "Unreleased-unit guard"),
# so we hide these by hand until launch, then DELETE the entry here. Use base slugs
# — build_index drops by slug OR base, so a base covers its skins/variants/_1 sibling.
MANUAL_UNRELEASED = {
    # c5069 Aubade Ludwig released 2026-06-11 — blockage dropped
    # c2185 Rhianna & Luciella released 2026-06-04 — blockage dropped
    # c5190 Aube + art0245 unheld 2026-07-18 — official skill preview live;
    #      public as ANNOUNCED (see build_index.ANNOUNCED) until limited banner.
    # c2113_s01 (Empyrean Ilynav's new skin) RELEASED 2026-06-25: visible in-game
    # though not yet obtainable -> surfaced (auto-NEW, first-seen today, groups under
    # the public c2113 card). Kept out of the hold list intentionally.
    # c5112 Uncharted Pioneer Politis + art0249 unheld 2026-09-02, released
    #      2026-09-03 — blockage dropped (NEW).
    # c6023 Acolyte of the End Kayron — HELD (owner, 2026-09-10). Announced form
    #      whose base still reads 'Unknown Hero', so it was held ONLY by token
    #      inheritance; the auto signal would drop the moment the DB names c6023
    #      and c6023_1 (real name, the c5069/c2185 trap) would leak. Pin it here.
    #      DELETE this entry when Kayron launches.
    'c6023',
    # c5002 Bunny Girl Maid Cecilia — briefly held 2026-10-29 (no player-DB row),
    #      unheld the same day: officially shown in the global trailer "Secret
    #      Rabbit Hole, Come Party With Us". Public as ANNOUNCED (build_index).
}

# ---- shared primitives (e7lib.dbcrypto), kept reachable under this module ----
def decode_text(keymap):
    """text.db -> {export_id: text}, from this module's TEXT_DB.

    Kept as a wrapper rather than a bare re-export so callers can retarget the
    table by assigning TEXT_DB (the pattern build_story uses on build_voices)."""
    return dbcrypto.decode_text(keymap, TEXT_DB)

# The playable roster is split across THREE tables, all sharing the same
# positional schema ([0]=c-slug, [3]=chrn_ name key, [4]=rarity, [7]=attribute,
# [8]=role, [20]=combat-rig name). `character_player.db` is the modern roster;
# `grade2` carries awakened/promoted forms; `grade3` carries the OLD 3★/4★ units
# (Kluri, Adlay, the elemental Adins, …) that aren't in the base table — they map
# to their (often generic class/element) battle rig via col[20]. Reading only the
# base table left ~86 old units unmapped. Base is listed FIRST so it wins on any
# duplicate c-slug (modern data is the most authoritative).
PLAYER_DBS = (
    'character_player.db',
    'character_player_grade2.db',
    'character_player_grade3.db',
)

def _decode_one_player_db(keymap, dbname):
    # empty columns are kept: the player schema is fixed-width and positional
    return decode_db_rows(OUT_DB / dbname, keymap)

def decode_player_rows(keymap):
    """Rows from all three player tables, base first. A c-slug seen in an earlier
    table is not overwritten by a later one (base wins)."""
    rows, seen = [], set()
    for dbname in PLAYER_DBS:
        try:
            db_rows = _decode_one_player_db(keymap, dbname)
        except FileNotFoundError:
            print('  (skip missing %s)' % dbname); continue
        kept = 0
        for r in db_rows:
            if not r or not r[0] or r[0] in seen:
                continue
            seen.add(r[0]); rows.append(r); kept += 1
        print('  %s rows: %d (%d new)' % (dbname, len(db_rows), kept))
    return rows

def main():
    keymap = load_keymap()
    print('decoding text.db ...'); sys.stdout.flush()
    text = decode_text(keymap)
    print('  text.db entries:', len(text))

    print('decoding player tables (base + grade2 + grade3) ...'); sys.stdout.flush()
    rows = decode_player_rows(keymap)
    print('  total player rows (deduped, base wins):', len(rows))

    out = {}
    model_map = {}
    unreleased = []
    for r in rows:
        if len(r) < 9:
            continue
        cslug = r[0]
        name = text.get(r[3])
        if not name:
            continue
        if name == UNRELEASED_NAME:
            # Game flags this slot as not-yet-announced. Don't emit the name
            # (would clobber any real community name); record it for the gate.
            unreleased.append(cslug)
            continue
        rec = {'name': name}
        if r[4].isdigit():
            rec['rarity'] = int(r[4])
        if r[7] in ELEMENTS:
            rec['attribute'] = r[7]
        if r[8] in ROLES:
            rec['role'] = r[8]
        out[cslug] = rec
        if len(r) > 20 and r[20]:
            model_map[cslug] = r[20]

    # Fold in the manual override list (announced-but-unreleased units the auto
    # 'Unknown Hero' signal misses). KEEP name + model_map so local unreleased
    # pages build fully (pose/name/rarity/combat map); publish still holds them
    # via unreleased_units.json + ops/deploy.ps1 (never units.json / R2 / Pages).
    n_manual = 0
    for s in MANUAL_UNRELEASED:
        if s not in unreleased:
            unreleased.append(s)
            n_manual += 1

    DATA_EXTERNAL.mkdir(parents=True, exist_ok=True)
    out_path = DATA_EXTERNAL / 'names_from_db.json'
    json.dump(out, open(out_path, 'w', encoding='utf-8'), ensure_ascii=False,
              indent=0, sort_keys=True)
    unreleased.sort()
    unrel_path = DATA_EXTERNAL / 'unreleased_units.json'
    json.dump({'signal': "character_player.db name == '%s' + MANUAL_UNRELEASED" % UNRELEASED_NAME,
               'manual': sorted(MANUAL_UNRELEASED),
               'slugs': unreleased},
              open(unrel_path, 'w', encoding='utf-8'), ensure_ascii=False, indent=0)
    model_path = DATA_EXTERNAL / 'model_map_from_db.json'
    json.dump(model_map, open(model_path, 'w', encoding='utf-8'),
              ensure_ascii=False, indent=0, sort_keys=True)
    full = sum(1 for v in out.values()
               if {'rarity', 'attribute', 'role'} <= set(v))
    print('\nwrote %s' % out_path)
    print('  entries: %d  (with full name+rarity+attribute+role: %d)' % (len(out), full))
    print('wrote %s' % unrel_path)
    print('  unreleased slugs: %d  (Unknown Hero auto: %d, manual override: %d)'
          % (len(unreleased), len(unreleased) - n_manual, n_manual))
    print('wrote %s' % model_path)
    print('  c-slug -> combat model entries: %d' % len(model_map))
    for k in ('c1001', 'c1067_s01', 'c1112', 'c1137'):
        print('  %s -> %r' % (k, out.get(k)))

if __name__ == '__main__':
    main()
