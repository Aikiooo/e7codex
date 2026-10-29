"""Build data_external/artifacts_from_db.json — self-sufficient artifact catalog.

Mirror of `build_names.py` for artifacts: decodes the game's own equipment table
to replace the community Artifacts.json dependency. Joins two decrypted tables:

  text/en/text.db       -> {export_id: text}   (`<identifier>_name` -> display name)
  db/equip_item.db      -> row per equip piece; filter `type == 'artifact'`.
                           Fixed 55-col schema; columns we use:
                             [ 0] id            = artifact identifier (e.g. 'efw21')
                             [ 7] name          = key in text.db (e.g. 'efw21_name')
                             [ 8] type          = 'artifact' / 'weapon' / 'helm' / ...
                             [24] role          = warrior|knight|ranger|mage|manauser|assassin
                             [29] artifact_grade = '1'..'5' (the displayed rarity)
                             [40] image         = '<art####>_fu' (full-art file stem)
                             [41] thumbnail     = '<art####>_l'  (lobby cut file stem)

Output (`data_external/artifacts_from_db.json`), keyed by the `art####` art id
that `pipeline/build_index.py` Step 4b already uses as the primary artifact key:

  { "art0105": {"identifier":"efw21","name":"A Little Queen's Huge Crown",
                "rarity":5,"role":"warrior"}, ... }

`pipeline/build_index.py` layers this LAST in `load_artifact_db()` and WINS on the
overlapping fields, parallel to how `names_from_db.json` wins for heroes.
The ceciliabot kebab (`_id`) and `tags` stay sourced from the community
snapshot — they are not in the game data.

ROLE FALLBACK. The role column is populated only for the 5★ class-specific
artifacts (the efw##/efk##/efr##/efm##/efh##/efa## identifier families).
Lower-grade artifacts and the generic ef### family (e.g. 'A Symbol of Unity')
ship with role empty in-game — those genuinely have no class restriction.
For the populated rows we additionally derive role from the identifier letter
to confirm the column (w→warrior, k→knight, r→ranger, m→mage, h→manauser,
a→assassin); mismatches would surface a schema drift.

Cipher reference: GAMEBIN_CRACK_FINDINGS.md + memory reference-e7-text-db-format.
Self-contained, mirrors build_voices.py/build_names.py (same primitives inline).
Keys/paths in gitignored private/keys/voice_keys.json.
"""
import json, sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]   # repo root: makes e7lib importable
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import e7lib.config as config  # noqa: E402
from e7lib import dbcrypto  # noqa: E402
from e7lib.dbcrypto import (  # noqa: E402  re-exported: these were defined here
    M, DELTA, xxtea_dec, load_keymap, decrypt_value, walk_cdbm,
    outer_decrypt_textdb, outer_decrypt_db, cdbm_rows)

# A build step, not a library: without local keys nothing can be decoded.
config.require_keys('copy from build_voices.py setup '
                    '(dump_dir, outer_key_file, default_xxtea_key)')

sys.path.insert(0, str(Path(__file__).parent))
from e7lib.config import RAW_DIR  # noqa: E402  central data-dir config
OUT_DB = RAW_DIR / 'db'
TEXT_DB = RAW_DIR / 'text' / 'en' / 'text.db'
DATA_EXTERNAL = Path(__file__).resolve().parents[1] / 'data_external'

# Role map for identifier-letter inference (efw##/efk##/efr##/efm##/efh##/efa##).
# Matches HeroDatabase.json vocab (the frontend already aliases
# manauser->soul-weaver, assassin->thief at render time).
ROLE_BY_LETTER = {
    'w': 'warrior', 'k': 'knight', 'r': 'ranger',
    'm': 'mage',    'h': 'manauser', 'a': 'assassin',
}

# ---- shared primitives (e7lib.dbcrypto), kept reachable under this module ----
def decode_text(keymap):
    """text.db -> {export_id: text}, from this module's TEXT_DB."""
    return dbcrypto.decode_text(keymap, TEXT_DB)

def decode_equip_rows(keymap):
    """equip_item.db -> rows of decoded columns."""
    return dbcrypto.decode_db_rows(OUT_DB / 'equip_item.db', keymap)

# Column indices in equip_item.db (positional schema). id/name/type are stable
# anchors; the artifact-data block (role/grade/image/thumbnail) DRIFTS when the
# game inserts a column — the 2026-06-25 pack added one, pushing the block +1
# (role 24->25, grade 29->30, image 40->41, thumb 41->42). These are the
# DOCUMENTED baseline indices; main() detects the live shift at runtime by
# locating the `art####_fu` image cell and offsets the whole block, so a future
# insert self-heals (same philosophy as the text.db outer-offset brute-force).
COL_ID, COL_NAME, COL_TYPE = 0, 7, 8
BASE_ROLE, BASE_GRADE, BASE_IMAGE, BASE_THUMB = 24, 29, 40, 41
import re as _re
_FU_RE = _re.compile(r'^art\d+_fu$')

def detect_col_shift(rows):
    """Index delta of the artifact-data block vs the documented baseline, found by
    locating the `art####_fu` image cell in a sample artifact row. 0 if absent."""
    for r in rows:
        if len(r) > COL_TYPE and r[COL_TYPE] == 'artifact':
            for i, c in enumerate(r):
                if isinstance(c, str) and _FU_RE.match(c):
                    return i - BASE_IMAGE
    return 0

def derive_role(ident: str, row_role: str) -> str | None:
    """Trust the row's role column when set; else infer from identifier prefix.
    For non-ef-prefix identifiers or unknown letters, return None (community
    fallback keeps whatever it had)."""
    if row_role:
        return row_role
    if len(ident) >= 3 and ident.startswith('ef') and ident[2].isalpha():
        return ROLE_BY_LETTER.get(ident[2])
    return None

def main():
    keymap = load_keymap()
    print('decoding text.db ...'); sys.stdout.flush()
    text = decode_text(keymap)
    print('  text.db entries:', len(text))

    print('decoding equip_item.db ...'); sys.stdout.flush()
    rows = decode_equip_rows(keymap)
    print('  equip_item.db rows:', len(rows))

    shift = detect_col_shift(rows)
    COL_ROLE, COL_GRADE = BASE_ROLE + shift, BASE_GRADE + shift
    COL_IMAGE, COL_THUMB = BASE_IMAGE + shift, BASE_THUMB + shift
    if shift:
        print('  schema shift detected: artifact-data block +%d (image col -> %d)' % (shift, COL_IMAGE))

    out = {}
    skipped_no_image = 0
    skipped_no_name = 0
    for r in rows:
        if len(r) <= COL_THUMB:
            continue
        if r[COL_TYPE] != 'artifact':
            continue
        ident = r[COL_ID]
        image = r[COL_IMAGE]            # e.g. 'art0121_fu' — bridge to existing art_id key
        if not image.endswith('_fu'):
            skipped_no_image += 1
            continue
        art_id = image[:-3]              # 'art0121'
        name = text.get(r[COL_NAME])
        if not name:
            skipped_no_name += 1
            continue
        rec: dict = {'identifier': ident, 'name': name}
        if r[COL_GRADE].isdigit():
            rec['rarity'] = int(r[COL_GRADE])
        role = derive_role(ident, r[COL_ROLE])
        if role:
            rec['role'] = role
        out[art_id] = rec

    DATA_EXTERNAL.mkdir(parents=True, exist_ok=True)
    out_path = DATA_EXTERNAL / 'artifacts_from_db.json'
    json.dump(out, open(out_path, 'w', encoding='utf-8'),
              ensure_ascii=False, indent=0, sort_keys=True)

    with_role = sum(1 for v in out.values() if 'role' in v)
    with_rarity = sum(1 for v in out.values() if 'rarity' in v)
    print('\nwrote %s' % out_path)
    print('  artifacts: %d  (with role: %d, with rarity: %d)' % (len(out), with_role, with_rarity))
    if skipped_no_image:
        print('  skipped %d rows with no _fu image (likely retired/stub)' % skipped_no_image)
    if skipped_no_name:
        print('  skipped %d rows whose name key did not resolve in text.db' % skipped_no_name)
    # spot-check 4 known artifacts
    for k in ('art0105', 'art0121', 'art0193', 'art0007'):
        print('  %s -> %r' % (k, out.get(k)))

if __name__ == '__main__':
    main()
