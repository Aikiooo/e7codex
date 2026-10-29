"""Build site/data/voices.json — per-hero voice metadata.

Self-contained: decodes Epic Seven's encrypted DBs directly from `output/`
(no external API, no runtime dep). Joins three decrypted tables:

  text/en/text.db              -> {export_id: text}  (label/actor-name lookup)
  db/character_voice.db        -> per c-slug voice ACTOR credit keys (kr/ja/en/zhs)
  db/character_intimacy_voice.db -> per-event voice LINE catalog (sound path + label)

Output (site/data/voices.json), keyed by c-slug:
  { "c1001": {
      "actors": {"en":"Griffin Burns","ja":"広瀬裕也","kr":"이경태","zhs":"kinsen"},
      "lines":  [{"event":"c1001_battle_01","category":"battle",
                  "label":"Sound when Attacked","sound":"voc/character/ras/ani/attacked"}, ...]
  }, ... }

Cipher reference: GAMEBIN_CRACK_FINDINGS.md + memory reference-e7-text-db-format.
DB values are cocos-XXTEA; outer layer is a 256-byte rolling XOR. Keys/paths are
local-only (private/keys/voice_keys.json, gitignored): the default XXTEA key, the
per-collection keymap (output/pass/public.pass), and the outer-XOR key file.
See TASKS.md #45 (enabler) / #43 (this).
"""
import re
import json, os, sys
from pathlib import Path

try:  # JP/KR actor names in debug prints crash on a cp1252 console (Windows)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# Local-only keys. Copy e7lib/voice_keys.example.json → voice_keys.json
# (gitignored) and fill in the values from your own install.
_REPO = Path(__file__).resolve().parents[1]   # repo root: makes e7lib importable
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import e7lib.config as config  # noqa: E402
from e7lib import dbcrypto  # noqa: E402
from e7lib.dbcrypto import (  # noqa: E402  re-exported: these were defined here
    M, DELTA, xxtea_dec, load_keymap, decrypt_value, walk_cdbm,
    outer_decrypt_textdb, outer_decrypt_db, cdbm_rows)

config.require_keys('copy voice_keys.example.json and fill in your local '
                    'paths + key')

sys.path.insert(0, str(Path(__file__).parent))
from e7lib.config import RAW_DIR  # noqa: E402  central data-dir config
OUT_DB = RAW_DIR / 'db'
TEXT_DB = RAW_DIR / 'text' / 'en' / 'text.db'
SITE_DATA = Path(__file__).resolve().parents[1] / 'site' / 'data'
DATA_EXTERNAL = Path(__file__).resolve().parents[1] / 'data_external'

# Unreleased-unit guard (mirrors sync_pack.leak_gate): drop voice data for any
# announced-but-unreleased c-slug so it never ships in voices.json. See CLAUDE.md
# "Unreleased-unit guard" + MANUAL_UNRELEASED in build_names.py.
def load_unreleased() -> set[str]:
    p = DATA_EXTERNAL / 'unreleased_units.json'
    if not p.exists():
        return set()
    return set(json.loads(p.read_text(encoding='utf-8')).get('slugs', []))

def is_unreleased(slug: str, unrel: set[str]) -> bool:
    return any(slug == u or slug.startswith(u + '_') for u in unrel)

# ---- shared primitives (e7lib.dbcrypto), kept reachable under this module ----
def decode_text(keymap):
    """text.db -> {export_id: text}, from this module's TEXT_DB.

    A wrapper, not a bare re-export: build_story retargets the table by assigning
    TEXT_DB (ko) around the call."""
    return dbcrypto.decode_text(keymap, TEXT_DB)

def decode_db_rows(fname, keymap):
    """table name under OUT_DB -> rows of decoded columns."""
    return dbcrypto.decode_db_rows(OUT_DB / fname, keymap)

def clean_actor(text):
    if text is None: return None
    t = text.strip()
    # credit prefixes the game writes before the name: "CV: …" (JP/KR), "VA: …" (EN)
    m = re.match(r'^(?:CV|VA)\s*[:：]\s*', t)
    return t[m.end():].strip() if m else t

def main():
    keymap = load_keymap()
    print('decoding text.db ...'); sys.stdout.flush()
    text = decode_text(keymap)
    print('  text.db entries:', len(text))

    voices = {}

    # character_voice.db: id, export_id, kr, ja, en, zhs  (actor credit keys)
    print('decoding character_voice.db ...'); sys.stdout.flush()
    for r in decode_db_rows('character_voice.db', keymap):
        if len(r) < 6: continue
        cslug = r[0]
        actors = {}
        for lang, col in (('kr', r[2]), ('ja', r[3]), ('en', r[4]), ('zhs', r[5])):
            if col and col in text:
                name = clean_actor(text[col])
                if name: actors[lang] = name
        if cslug and actors:
            voices.setdefault(cslug, {})['actors'] = actors

    # character_intimacy_voice.db: id, export_id, sound_id, channel_id, name
    print('decoding character_intimacy_voice.db ...'); sys.stdout.flush()
    for r in decode_db_rows('character_intimacy_voice.db', keymap):
        if len(r) < 5: continue
        event, sound, namekey = r[0], r[2], r[4]
        if not event or '_' not in event: continue
        # event = <slug>_<category>_<NN>; slug may carry a skin suffix (c1067_s01)
        toks = event.split('_')
        if len(toks) >= 3 and toks[-1].isdigit() and not toks[-2].isdigit():
            cslug = '_'.join(toks[:-2]); category = toks[-2]
        else:
            cslug = toks[0]; category = 'misc'
        label = text.get(namekey, namekey)
        line = {'event': event, 'category': category, 'label': label, 'sound': sound}
        voices.setdefault(cslug, {}).setdefault('lines', []).append(line)

    # Drop unreleased units before writing (DMCA guard).
    unrel = load_unreleased()
    if unrel:
        dropped = [s for s in voices if is_unreleased(s, unrel)]
        for s in dropped:
            del voices[s]
        if dropped:
            print('  dropped %d unreleased slug(s): %s' % (len(dropped), ', '.join(sorted(dropped))))

    with_actors = sum(1 for v in voices.values() if v.get('actors'))
    with_lines = sum(1 for v in voices.values() if v.get('lines'))
    total_lines = sum(len(v.get('lines', [])) for v in voices.values())
    SITE_DATA.mkdir(parents=True, exist_ok=True)
    out_path = SITE_DATA / 'voices.json'
    json.dump(voices, open(out_path, 'w', encoding='utf-8'), ensure_ascii=False,
              separators=(',', ':'), sort_keys=True)
    print('\nwrote %s' % out_path)
    print('  characters: %d  (with actors: %d, with lines: %d)' % (len(voices), with_actors, with_lines))
    print('  total voice lines: %d' % total_lines)
    ex = voices.get('c1001', {})
    print('  c1001 actors:', ex.get('actors'))
    print('  c1001 first 3 lines:', ex.get('lines', [])[:3])

if __name__ == '__main__':
    main()
