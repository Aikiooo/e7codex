"""Build data_external/codename_labels.json — codename -> human event label.

Resolves the cryptic version codenames the dump tokenizes (`vsu5aa`, `vfa2aa`,
`vyunaa`, `v1070a`, ...) to their in-game event titles via a single-table join:

  db/substory_main.db       -> row per side-story; col[0] = codename
  text/en/text.db           -> mission_name2_<codename> -> human label

For every distinct col[0] value in substory_main.db we look up
`mission_name2_<code>` (the proper in-game event title) and, as fallback, the
codename itself as a direct text.db key (a handful of codenames like `vfm3aa`
"Night of the Last Succession" double-resolve that way).

The mission_name2 column carries the LONG event title; mission_name1 holds a
generic "Side Story" category we deliberately ignore — the long title is what
makes the Updates view actually scannable.

Output (`data_external/codename_labels.json`), flat dict:

  { "vsu5aa": "Intense! Tropical Days!!",
    "vfa2aa": "Otherworldly Alchemist",
    "vyunaa": "Chaotic Full Moon Festival",
    "v1070a": "My Knight Would Never!", ... }

`pipeline/build_index.py` merges this on top of its built-in KNOWN_UPDATES table — DB
labels WIN on overlap (the in-game name is canonical), and any DB codename
with no prior label is added (so new events start appearing in the Updates
view automatically when their banners ship). Story-style codenames (`vNNNNa`)
are emitted for completeness even though the current Updates view filter
(`v[a-z0-9]{3}aa`) won't pick them up — future tabs (#49 Events) can use them.

Premise correction vs the original task brief: `background_main.db` is NOT
useful here — its row IDs are scene-slot names (`grassland_1`, `castle_2`,
...) describing parallax layers, not version codenames. The codename→label
join lives entirely in `substory_main.db`. `substory_main_illust.db` carries
codenames in col[2] but no label column. Single-table join is the answer.

Cipher reference: GAMEBIN_CRACK_FINDINGS.md + memory reference-e7-text-db-format.
Mirrors pipeline/names.py (same cocos-XXTEA + outer-XOR primitives inline).
Keys/paths in gitignored private/keys/voice_keys.json.

Self-sufficient ([[feedback-self-sufficient]]): all inputs are on-disk under
extracted_data/output/; no network/CDN dependency at build OR runtime.
"""
import json, sys, re
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
from e7lib.config import RAW_DIR  # noqa: E402
OUT_DB = RAW_DIR / 'db'
TEXT_DB = RAW_DIR / 'text' / 'en' / 'text.db'
DATA_EXTERNAL = Path(__file__).resolve().parents[1] / 'data_external'

# Codename patterns:
#   v + (theme letters / digits, 2-4 chars) + (digit | 'aa')
# Loose enough to catch updates-style (vsu5aa), story-style (v1070a),
# and the odd-shapes we saw (vyunaa, vresaa, vov4aa, vasiaa, vrimaa).
# 4-7 chars after the `v`, lowercase alnum, ending in 'a'.
CODENAME_RE = re.compile(r'^v[a-z0-9]{3,6}a$')

# ---- shared primitives (e7lib.dbcrypto), kept reachable under this module ----
def decode_text(keymap):
    """text.db -> {export_id: text}, from this module's TEXT_DB."""
    return dbcrypto.decode_text(keymap, TEXT_DB)

def decode_substory_main(keymap):
    """substory_main.db -> rows of decoded columns."""
    return dbcrypto.decode_db_rows(OUT_DB / 'substory_main.db', keymap)


def main():
    keymap = load_keymap()
    print('decoding text.db ...', flush=True)
    text = decode_text(keymap)
    print(f'  text.db entries: {len(text)}')

    print('decoding substory_main.db ...', flush=True)
    rows = decode_substory_main(keymap)
    print(f'  substory_main.db rows: {len(rows)}')

    # col[0] is the codename. Collect distinct ones that pass the regex.
    codenames: set[str] = set()
    for r in rows:
        if not r:
            continue
        c = r[0].strip().lower()
        if CODENAME_RE.match(c):
            codenames.add(c)
    print(f'  distinct codenames matching pattern: {len(codenames)}')

    # Resolve each: prefer mission_name2_<code>, fall back to direct text.db lookup.
    labels: dict[str, str] = {}
    no_label: list[str] = []
    for c in sorted(codenames):
        lbl = text.get(f'mission_name2_{c}') or text.get(c) or ''
        lbl = lbl.strip()
        if lbl:
            labels[c] = lbl
        else:
            no_label.append(c)

    DATA_EXTERNAL.mkdir(parents=True, exist_ok=True)
    out_path = DATA_EXTERNAL / 'codename_labels.json'
    out_path.write_text(json.dumps(labels, indent=1, ensure_ascii=False,
                                   sort_keys=True), encoding='utf-8')

    # bucket by shape for the summary
    updates_re = re.compile(r'^v[a-z0-9]{3}aa$')
    story_re   = re.compile(r'^v[0-9]{4}a$')
    updates_n = sum(1 for c in labels if updates_re.match(c))
    story_n   = sum(1 for c in labels if story_re.match(c))
    other_n   = len(labels) - updates_n - story_n

    print(f'\nwrote {out_path}')
    print(f'  codenames with labels: {len(labels)} '
          f'({updates_n} updates-style, {story_n} story-style, {other_n} other)')
    if no_label:
        print(f'  no label found: {len(no_label)} (e.g. {no_label[:6]})')
    # Spot-check a known sample so a schema drift surfaces fast.
    for k in ('vsu5aa', 'vfa2aa', 'vae2aa', 'vfr5aa', 'vyunaa', 'v1070a', 'vfm3aa'):
        v = labels.get(k, '<missing>')
        # ascii-safe print so cp1252 consoles don't blow up
        safe = v.encode('ascii', 'replace').decode('ascii')
        print(f'  {k} -> {safe!r}')

if __name__ == '__main__':
    main()
