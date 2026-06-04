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

`build_index.py` merges this on top of its built-in KNOWN_UPDATES table — DB
labels WIN on overlap (the in-game name is canonical), and any DB codename
with no prior label is added (so new events start appearing in the Updates
view automatically when their banners ship). Story-style codenames (`vNNNNa`)
are emitted for completeness even though the current Updates view filter
(`v[a-z0-9]{3}aa`) won't pick them up — future tabs could use them.

Note on related tables: `background_main.db` is NOT a codename → label
source — its row IDs are scene-slot names (`grassland_1`, `castle_2`, ...)
describing parallax layers, not version codenames. `background.db` won't
outer-decrypt at all (no PLPcK magic — different on-disk format).
`substory_main_illust.db` carries codenames in col[2] but no label column.
Single-table join on `substory_main.db` is sufficient.

Mirrors build_names.py / build_artifacts.py / build_voices.py (same cipher
primitives inline; DB values are cocos-XXTEA, outer layer is a 256-byte
rolling XOR). Keys + paths live in gitignored tools/voice_keys.json — copy
voice_keys.example.json to voice_keys.json and fill in the values from your
own install.
"""
import struct, json, sys, re
from pathlib import Path

_CFG_PATH = Path(__file__).parent / 'voice_keys.json'
if not _CFG_PATH.exists():
    raise SystemExit('missing tools/voice_keys.json — copy voice_keys.example.json '
                     'and fill in your local paths + key')
_CFG = json.loads(_CFG_PATH.read_text(encoding='utf-8'))

sys.path.insert(0, str(Path(__file__).parent))
from paths import RAW_DIR
OUT_DB = RAW_DIR / 'db'
TEXT_DB = RAW_DIR / 'text' / 'en' / 'text.db'
PASS = RAW_DIR / 'pass' / 'public.pass'
OUTER_KEY = Path(_CFG['outer_key_file'])
if not OUTER_KEY.is_absolute():
    OUTER_KEY = Path(__file__).parent / OUTER_KEY
DATA_EXTERNAL = Path(__file__).resolve().parents[1] / 'data_external'

M = 0xFFFFFFFF; DELTA = 0x9E3779B9
DEFAULT_KEY = tuple(int(str(x), 16) for x in _CFG['default_xxtea_key'])

# Codename patterns:
#   v + (theme letters / digits, 2-4 chars) + (digit | 'aa')
# Loose enough to catch updates-style (vsu5aa), story-style (v1070a),
# and the odd-shapes we saw (vyunaa, vresaa, vov4aa, vasiaa, vrimaa).
# 4-7 chars after the `v`, lowercase alnum, ending in 'a'.
CODENAME_RE = re.compile(r'^v[a-z0-9]{3,6}a$')

# ---- cipher primitives (verbatim from build_names.py / build_artifacts.py) ----
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
    # text.db's outer-XOR offset is NOT fixed: it was 0, but a later update
    # shifted it to 180. Brute the offset against the PLPcK magic, the same
    # way outer_decrypt_db does for the other db files.
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

def decode_substory_main(keymap):
    plain = outer_decrypt_db((OUT_DB / 'substory_main.db').read_bytes())
    rows = []
    for key, val in cdbm_rows(plain):
        if len(key) != 8 or key[0] == 9: continue
        pt = decrypt_value(val, keymap)
        if not pt: continue
        rows.append([c.decode('utf-8', 'replace') for c in pt.split(b'\x00')])
    return rows


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
