"""Build data_external/names_from_db.json — self-sufficient hero names + metadata.

Decodes Epic Seven's local data files directly from your own game output dir
(no external API, no runtime dependency) to pull each unit's display name +
rarity + attribute + role straight from the game, so the project no longer
depends on community JSONs for that data. Joins two tables:

  text/en/text.db          -> {export_id: text}   (chrn_* -> "Ras", ...)
  db/character_player.db    -> per c-slug row; columns (fixed 98-wide schema):
                                 [0]  id (c-slug, incl. costume slugs)
                                 [3]  name key  (chrn_<base>)
                                 [4]  rarity    ("3".."6")
                                 [7]  attribute (fire/ice/wind/light/dark)
                                 [8]  role/class (warrior/knight/ranger/mage/
                                                  manauser/assassin/material)

Output (data_external/names_from_db.json), keyed by c-slug:
  { "c1001": {"name": "Ras", "rarity": 3, "attribute": "fire", "role": "knight"}, ... }

The attribute + role vocabulary matches the community DBs (the frontend aliases
manauser->soul-weaver / assassin->thief at render time), so the output is a
drop-in metadata source layered ahead of them in build_index.py. Skin DISPLAY
names are NOT in character_player.db — costume rows reuse the base hero's chrn_
key — so the community skin DB stays the source for those, as does the
ceciliabot kebab (URL slug), which isn't in the game data either.

UNRELEASED GUARD: the game ships placeholder rows for unannounced units whose
name resolves to the literal "Unknown Hero". Those names are NOT written to
names_from_db.json (so they can't clobber a real name), and the slugs are
written to data_external/unreleased_units.json instead. build_index.py uses that
list to keep unannounced units off the site entirely — the project does not
publish datamined/unreleased content. The flag flips to a real name shortly
before release, so a unit surfaces automatically once it is officially announced.

Keys + paths are local-only. Copy tools/voice_keys.example.json → voice_keys.json
(gitignored) and fill in the values from your own install: the game output dir,
the outer-XOR key file, and the default XXTEA key. DB values are cocos-XXTEA; the
outer layer is a 256-byte rolling XOR (same primitives as build_voices.py).
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

ELEMENTS = {'fire', 'ice', 'wind', 'light', 'dark'}
ROLES = {'warrior', 'knight', 'ranger', 'mage', 'manauser', 'assassin'}
UNRELEASED_NAME = 'Unknown Hero'   # game's placeholder for unannounced units

# ---- cipher primitives (same as build_voices.py) ----
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

# The playable roster is split across THREE tables, all sharing the same
# positional schema ([0]=c-slug, [3]=chrn_ name key, [4]=rarity, [7]=attribute,
# [8]=role, [20]=combat-rig name). `character_player.db` is the modern roster;
# `grade2` carries awakened/promoted forms; `grade3` carries the OLD 3-star/4-star
# units that aren't in the base table — they map to their (often generic
# class/element) battle rig via col[20]. Reading only the base table left the old
# units unmapped. Base is listed FIRST so it wins on any duplicate c-slug.
PLAYER_DBS = (
    'character_player.db',
    'character_player_grade2.db',
    'character_player_grade3.db',
)

def _decode_one_player_db(keymap, dbname):
    plain = outer_decrypt_db((OUT_DB / dbname).read_bytes())
    rows = []
    for key, val in cdbm_rows(plain):
        if len(key) != 8 or key[0] == 9: continue
        pt = decrypt_value(val, keymap)
        if not pt: continue
        # keep empty columns — schema is fixed-width and positional
        rows.append([c.decode('utf-8', 'replace') for c in pt.split(b'\x00')])
    return rows

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
            model_map[cslug] = r[20]   # col[20] = combat-rig filename

    DATA_EXTERNAL.mkdir(parents=True, exist_ok=True)
    out_path = DATA_EXTERNAL / 'names_from_db.json'
    json.dump(out, open(out_path, 'w', encoding='utf-8'), ensure_ascii=False,
              indent=0, sort_keys=True)
    unreleased.sort()
    unrel_path = DATA_EXTERNAL / 'unreleased_units.json'
    json.dump({'signal': "character_player.db name == '%s'" % UNRELEASED_NAME,
               'slugs': unreleased},
              open(unrel_path, 'w', encoding='utf-8'), ensure_ascii=False, indent=0)
    # c-slug -> combat-rig filename (col[20]); authoritative map consumed by
    # prepare_combat_assets.py. Excludes unreleased units.
    model_path = DATA_EXTERNAL / 'model_map_from_db.json'
    json.dump(model_map, open(model_path, 'w', encoding='utf-8'),
              ensure_ascii=False, indent=0, sort_keys=True)
    full = sum(1 for v in out.values()
               if {'rarity', 'attribute', 'role'} <= set(v))
    print('\nwrote %s' % out_path)
    print('  entries: %d  (with full name+rarity+attribute+role: %d)' % (len(out), full))
    print('wrote %s' % unrel_path)
    print('  unreleased (Unknown Hero) slugs: %d' % len(unreleased))
    print('wrote %s' % model_path)
    print('  c-slug -> combat model entries: %d' % len(model_map))
    for k in ('c1001', 'c1067_s01', 'c1112', 'c1137'):
        print('  %s -> %r' % (k, out.get(k)))

if __name__ == '__main__':
    main()
