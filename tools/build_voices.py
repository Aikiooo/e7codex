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
local-only (tools/voice_keys.json, gitignored): the default XXTEA key, the
per-collection keymap (output/pass/public.pass), and the outer-XOR key file.
See TASKS.md #45 (enabler) / #43 (this).
"""
import struct, json, os, sys
from pathlib import Path

try:  # JP/KR actor names in debug prints crash on a cp1252 console (Windows)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# Local-only secrets + paths. Copy tools/voice_keys.example.json → voice_keys.json
# (gitignored) and fill in the values from your own install.
_CFG_PATH = Path(__file__).parent / 'voice_keys.json'
if not _CFG_PATH.exists():
    raise SystemExit('missing tools/voice_keys.json — copy voice_keys.example.json '
                     'and fill in your local paths + key')
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

M = 0xFFFFFFFF; DELTA = 0x9E3779B9
DEFAULT_KEY = tuple(int(str(x), 16) for x in _CFG['default_xxtea_key'])

# ---- cipher primitives ----
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

# ---- outer XOR ----
_PRE = OUTER_KEY.read_bytes()
_BASE = _PRE[256 - 51:] + _PRE[:256 - 51]   # un-rotated base key

def outer_decrypt_textdb(cipher):
    # text.db's outer-XOR offset is NOT fixed: it was 0, but the 2026-06-04
    # update shifted it to 180. Brute the offset against the PLPcK magic, the
    # same way outer_decrypt_db does for the other db files.
    for off in range(256):
        if bytes(cipher[i] ^ _PRE[(off + i) % 256] for i in range(5)) == b'PLPcK':
            return bytes(cipher[i] ^ _PRE[(off + i) % 256] for i in range(len(cipher)))
    raise SystemExit('could not find text.db outer-XOR offset (no PLPcK magic)')

def outer_decrypt_db(cipher):
    # other db files: brute the rotation offset until first 5 bytes == "PLPcK"
    for off in range(256):
        if bytes(cipher[i] ^ _BASE[(off + i) % 256] for i in range(5)) == b'PLPcK':
            return bytes(cipher[i] ^ _BASE[(off + i) % 256] for i in range(len(cipher)))
    raise SystemExit('could not find outer-XOR offset (no PLPcK magic)')

def cdbm_rows(plain):
    nb = struct.unpack_from('<I', plain, 0x15)[0]
    return walk_cdbm(plain, 38 + nb * 5 + 5)

# ---- decode each table ----
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

def decode_db_rows(fname, keymap):
    plain = outer_decrypt_db((OUT_DB / fname).read_bytes())
    rows = []
    for key, val in cdbm_rows(plain):
        if len(key) != 8 or key[0] == 9: continue
        pt = decrypt_value(val, keymap)
        if not pt: continue
        rows.append([c.decode('utf-8', 'replace') for c in pt.split(b'\x00')])
    return rows

def clean_actor(text):
    if text is None: return None
    t = text.strip()
    for pre in ('CV: ', 'CV:', 'CV：'):
        if t.startswith(pre): return t[len(pre):].strip()
    return t

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
