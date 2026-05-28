"""Build data_external/artifacts_from_db.json — self-sufficient artifact catalog.

Decodes the game's own equipment table to replace the community Artifacts.json
dependency for artifact name + rarity + role. Joins two tables:

  text/en/text.db       -> {export_id: text}   (`<identifier>_name` -> display name)
  db/equip_item.db      -> row per equip piece; filter `type == 'artifact'`.
                           Fixed 97-col schema; columns we use:
                             [ 0] id            = artifact identifier (e.g. 'efw21')
                             [ 7] name          = key in text.db (e.g. 'efw21_name')
                             [ 8] type          = 'artifact' / 'weapon' / 'helm' / ...
                             [24] role          = warrior|knight|ranger|mage|manauser|assassin
                             [29] artifact_grade = '1'..'5' (the displayed rarity)
                             [40] image         = '<art####>_fu' (full-art file stem)
                             [41] thumbnail     = '<art####>_l'  (lobby cut file stem)

Output (`data_external/artifacts_from_db.json`), keyed by the `art####` art id
that `build_index.py` Step 4b already uses as the primary artifact key:

  { "art0105": {"identifier": "efw21", "name": "A Little Queen's Huge Crown",
                "rarity": 5, "role": "warrior"}, ... }

`build_index.py` layers this LAST in `load_artifact_db()` and WINS on the
overlapping fields, parallel to how `names_from_db.json` wins for heroes. The
ceciliabot kebab (`_id`) and `tags` stay sourced from the community snapshot —
they are not in the game data.

ROLE FALLBACK. The role column is populated only for the 5★ class-specific
artifacts (the efw##/efk##/efr##/efm##/efh##/efa## identifier families). The
generic ef### family and lower-grade artifacts ship with role empty in-game —
those genuinely have no class restriction. For the populated rows we
additionally derive role from the identifier letter to confirm the column
(w→warrior, k→knight, r→ranger, m→mage, h→manauser, a→assassin); mismatches
would surface a schema drift.

Mirrors build_names.py / build_voices.py (same cipher primitives inline; DB
values are cocos-XXTEA, outer layer is a 256-byte rolling XOR). Keys + paths
live in gitignored tools/voice_keys.json — copy voice_keys.example.json to
voice_keys.json and fill in the values from your own install.
"""
import struct, json, sys
from pathlib import Path

_CFG_PATH = Path(__file__).parent / 'voice_keys.json'
if not _CFG_PATH.exists():
    raise SystemExit('missing tools/voice_keys.json — copy voice_keys.example.json '
                     'and fill in your local paths + key')
_CFG = json.loads(_CFG_PATH.read_text(encoding='utf-8'))

sys.path.insert(0, str(Path(__file__).parent))
from paths import RAW_DIR  # central data-dir config
OUT_DB = RAW_DIR / 'db'
TEXT_DB = RAW_DIR / 'text' / 'en' / 'text.db'
PASS = RAW_DIR / 'pass' / 'public.pass'
OUTER_KEY = Path(_CFG['outer_key_file'])
if not OUTER_KEY.is_absolute():
    OUTER_KEY = Path(__file__).parent / OUTER_KEY
DATA_EXTERNAL = Path(__file__).resolve().parents[1] / 'data_external'

M = 0xFFFFFFFF; DELTA = 0x9E3779B9
DEFAULT_KEY = tuple(int(str(x), 16) for x in _CFG['default_xxtea_key'])

# Role map for identifier-letter inference (efw##/efk##/efr##/efm##/efh##/efa##).
# Matches HeroDatabase.json vocab (the frontend already aliases
# manauser->soul-weaver, assassin->thief at render time).
ROLE_BY_LETTER = {
    'w': 'warrior', 'k': 'knight', 'r': 'ranger',
    'm': 'mage',    'h': 'manauser', 'a': 'assassin',
}

# ---- cipher primitives (same as build_names.py / build_voices.py) ----
def xxtea_dec(v, k):
    v = list(v); n = len(v)
    if n < 2: return v
    total = ((6 + 52 // n) * DELTA) & M
    while total != 0:
        e = (total >> 2) & 3; y = v[0]
        for p in range(n - 1, 0, -1):
            z = v[p - 1]
            mx = ((((z >> 5) ^ ((y << 2) & M)) + ((y >> 3) ^ ((z << 4) & M))) & M) ^ (((total ^ y) + (k[(p & 3) ^ e] ^ z)) & M)
            v[p] = y = (v[p] - mx) & M
        z = v[n - 1]
        mx = ((((z >> 5) ^ ((y << 2) & M)) + ((y >> 3) ^ ((z << 4) & M))) & M) ^ (((total ^ y) + (k[e] ^ z)) & M)
        v[0] = y = (v[0] - mx) & M
        total = (total - DELTA) & M
    return v

def load_keymap():
    pk = PASS.read_bytes()
    return {struct.unpack_from('<I', pk, i)[0]: struct.unpack_from('<4I', pk, i + 4)
            for i in range(0, len(pk), 20)}

def decrypt_value(V, keymap):
    L = len(V)
    if L < 16: return None
    D = V[4:]; ld = len(D); nbytes = L - 8; n = nbytes // 4
    if n < 2 or ld < n * 4: return None
    idv = (struct.unpack_from('<I', D, 0)[0]
           ^ struct.unpack_from('<I', D, ld - 8)[0]
           ^ struct.unpack_from('<I', D, ld - 4)[0] ^ 0xd12dfd15) & M
    key = DEFAULT_KEY if idv == 0 else keymap.get(idv)
    if key is None: return None
    dec = xxtea_dec(list(struct.unpack_from('<%dI' % n, D, 0)), key)
    last = dec[-1]
    if not (nbytes - 7 <= last <= nbytes - 4): return None
    return struct.pack('<%dI' % n, *dec)[:last]

def walk_cdbm(d, data_start):
    N = len(d); p = data_start
    while p + 15 < N:
        keylen = d[p + 5]; valsize = struct.unpack_from('<I', d, p + 6)[0]
        if keylen == 0 or keylen > 64 or valsize < 1 or valsize > 1000000: break
        ks = p + 15; vs = ks + keylen
        if vs + valsize > N: break
        yield (d[ks:ks + keylen], d[vs:vs + valsize])
        p = vs + valsize

_PRE = OUTER_KEY.read_bytes()
_BASE = _PRE[256 - 51:] + _PRE[:256 - 51]

def outer_decrypt_textdb(cipher):
    return bytes(cipher[i] ^ _PRE[i % 256] for i in range(len(cipher)))

def outer_decrypt_db(cipher):
    for off in range(256):
        if bytes(cipher[i] ^ _BASE[(off + i) % 256] for i in range(5)) == b'PLPcK':
            return bytes(cipher[i] ^ _BASE[(off + i) % 256] for i in range(len(cipher)))
    raise SystemExit('could not find outer-XOR offset (no PLPcK magic)')

def cdbm_rows(plain):
    nb = struct.unpack_from('<I', plain, 0x15)[0]
    return walk_cdbm(plain, 38 + nb * 5 + 5)

# ---- decode tables ----
def decode_text(keymap):
    plain = outer_decrypt_textdb(TEXT_DB.read_bytes())
    out = {}
    for key, val in cdbm_rows(plain):
        if len(key) != 8 or key[:4] != b'\x1b\x6b\x00\x00': continue
        pt = decrypt_value(val, keymap)
        if not pt: continue
        parts = [c for c in pt.split(b'\x00') if c]
        if len(parts) >= 2:
            out[parts[0].decode('utf-8', 'replace')] = parts[1].decode('utf-8', 'replace')
    return out

def decode_equip_rows(keymap):
    plain = outer_decrypt_db((OUT_DB / 'equip_item.db').read_bytes())
    rows = []
    for key, val in cdbm_rows(plain):
        if len(key) != 8 or key[0] == 9: continue
        pt = decrypt_value(val, keymap)
        if not pt: continue
        rows.append([c.decode('utf-8', 'replace') for c in pt.split(b'\x00')])
    return rows

# Column indices in equip_item.db (97-col schema; positional).
COL_ID, COL_NAME, COL_TYPE = 0, 7, 8
COL_ROLE, COL_GRADE = 24, 29
COL_IMAGE, COL_THUMB = 40, 41

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
    for k in ('art0105', 'art0121', 'art0193', 'art0007'):
        print('  %s -> %r' % (k, out.get(k)))

if __name__ == '__main__':
    main()
