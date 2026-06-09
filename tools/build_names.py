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
build + deploy pipeline uses that list to keep them off the public site
entirely (no listing, no rendered art served). The flag flips to a real name a
few days before release, so a unit surfaces automatically once SG announces it.
See docs/TASKS.md #42 and the conversation log for the DMCA rationale.

Cipher reference: GAMEBIN_CRACK_FINDINGS.md + memory reference-e7-text-db-format.
Mirrors tools/build_voices.py (same cocos-XXTEA + outer-XOR primitives). Keys
and dump path are local-only via tools/voice_keys.json (gitignored).
"""
import struct, json, sys
from pathlib import Path

_CFG_PATH = Path(__file__).parent / 'voice_keys.json'
if not _CFG_PATH.exists():
    raise SystemExit('missing tools/voice_keys.json — copy from build_voices.py setup '
                     '(dump_dir, outer_key_file, default_xxtea_key)')
_CFG = json.loads(_CFG_PATH.read_text(encoding='utf-8'))

DUMP = Path(_CFG['dump_dir'])
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
# Manually-suppressed units that are ANNOUNCED (so they already carry a real name
# and the 'Unknown Hero' auto-signal misses them) but NOT YET RELEASED. Hosting
# pre-release art is the highest DMCA risk (see CLAUDE.md "Unreleased-unit guard"),
# so we hide these by hand until launch, then DELETE the entry here. Use base slugs
# — build_index drops by slug OR base, so a base covers its skins/variants/_1 sibling.
MANUAL_UNRELEASED = {
    'c5069',   # added 2026-05-30 — announced, not yet released
    # c2185 Rhianna & Luciella released 2026-06-04 — blockage dropped
}

# ---- cipher primitives (verbatim from build_voices.py) ----
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
    # text.db's outer-XOR offset is NOT fixed: it was 0, but the 2026-06-04
    # update shifted it to 180. Brute the offset against the PLPcK magic, the
    # same way outer_decrypt_db does for the other db files.
    for off in range(256):
        if bytes(cipher[i] ^ _PRE[(off + i) % 256] for i in range(5)) == b'PLPcK':
            return bytes(cipher[i] ^ _PRE[(off + i) % 256] for i in range(len(cipher)))
    raise SystemExit('could not find text.db outer-XOR offset (no PLPcK magic)')

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
            model_map[cslug] = r[20]

    # Fold in the manual override list (announced-but-unreleased units the auto
    # 'Unknown Hero' signal misses). Drop any emitted name/model for them too so
    # nothing downstream can surface them.
    n_manual = 0
    for s in MANUAL_UNRELEASED:
        out.pop(s, None)
        model_map.pop(s, None)
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
