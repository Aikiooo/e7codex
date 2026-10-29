"""Decoders for Epic Seven's encrypted databases (`output/db/*.db`, `text.db`).

Everything here was moved verbatim out of `pipeline/names.py`, where the same
primitives had been copied into four builders (`build_names`, `build_voices`,
`build_artifacts`, `build_codename_labels`) — the copies were byte-identical, so
there is now one implementation. `build_names.py` re-exports these names, so any
importer that has not been migrated still works.

Pipeline, per file (`[[reference-e7-text-db-format]]`):

  1. outermost XOR with a 256-byte key file, at a rotation offset that is brute
     forced against the `PLPcK` magic (the offset is NOT fixed — text.db's moved
     from 0 to 180 in the 2026-06-04 pack);
  2. the plaintext is a CDBM container: rows of (key, value) walking from a data
     start whose position depends on a column-name table;
  3. rows prefixed with ``\\x1b\\x6b\\x00\\x00`` are still cocos-XXTEA encrypted
     (legacy schema, per-collection key from `output/pass/public.pass`); every
     row on the res_4109+ schema is plaintext columns;
  4. a value decodes to NUL-separated UTF-8 columns.

KEY HANDLING. e7lib is published keyless, so importing this module must not need
a local `voice_keys.json` or key file: both are read lazily, on first decode.
Until then `load_keymap()` returns {} and nothing touches the disk. The failure
modes are unchanged — a bad/absent key still raises, just at the first decode
instead of at import.
"""
from __future__ import annotations

import struct
from pathlib import Path

from e7lib import config

__all__ = [
    "M", "DELTA",
    "default_key", "load_keymap", "decrypt_value", "walk_cdbm",
    "outer_decrypt_textdb", "outer_decrypt_db", "cdbm_rows",
    "decode_text", "decode_db_rows",
]

M = 0xFFFFFFFF
DELTA = 0x9E3779B9

_outer_cache: bytes | None = None
_default_key_cache: tuple | None = None


def _pass_path() -> Path:
    """`output/pass/public.pass` — the per-collection XXTEA keymap."""
    return config.RAW_DIR / "pass" / "public.pass"


def _text_db_path() -> Path:
    """English `text.db`, the default source for `decode_text`."""
    return config.RAW_DIR / "text" / "en" / "text.db"


def _pre() -> bytes:
    """The 256-byte outer-XOR key, read once."""
    global _outer_cache
    if _outer_cache is None:
        _outer_cache = config.outer_key_path().read_bytes()
    return _outer_cache


def _base() -> bytes:
    """The un-rotated outer-XOR key (`_PRE` rotated by 51 bytes)."""
    pre = _pre()
    return pre[256 - 51:] + pre[:256 - 51]


def default_key() -> tuple:
    """The default 4-word cocos-XXTEA key, from voice_keys.json."""
    global _default_key_cache
    if _default_key_cache is None:
        _default_key_cache = tuple(int(str(x), 16)
                                   for x in config.load_keys()["default_xxtea_key"])
    return _default_key_cache


# ---- cocos-XXTEA ----
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


def load_keymap(pass_path: Path | None = None):
    """Per-collection XXTEA keymap (output/pass/public.pass).

    res_4178 (2026-09-10) dropped the `pass` archive from the res policy: every DB
    row is plaintext on the res_4109+ schema, so the map is neither shipped nor
    consulted any more. An empty map is therefore correct — decrypt_value still
    fails CLOSED if an encrypted row ever reappears."""
    p = Path(pass_path) if pass_path is not None else _pass_path()
    if not p.exists():
        return {}
    pk = p.read_bytes()
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
    key = default_key() if idv == 0 else keymap.get(idv)
    if key is None:
        if idv != 0 and not keymap:
            raise SystemExit('%s is absent, but this pack still carries '
                             'XXTEA-encrypted rows — re-fetch the `pass` archive '
                             'before building' % _pass_path())
        return None
    dec = xxtea_dec(list(struct.unpack_from('<%dI' % n, D, 0)), key)
    last = dec[-1]
    if not (nbytes - 7 <= last <= nbytes - 4): return None
    return struct.pack('<%dI' % n, *dec)[:last]


# ---- outer XOR ----
def outer_decrypt_textdb(cipher):
    # text.db's outer-XOR offset is NOT fixed: it was 0, but the 2026-06-04
    # update shifted it to 180. Brute the offset against the PLPcK magic, the
    # same way outer_decrypt_db does for the other db files.
    pre = _pre()
    for off in range(256):
        if bytes(cipher[i] ^ pre[(off + i) % 256] for i in range(5)) == b'PLPcK':
            return bytes(cipher[i] ^ pre[(off + i) % 256] for i in range(len(cipher)))
    raise SystemExit('could not find text.db outer-XOR offset (no PLPcK magic)')


def outer_decrypt_db(cipher):
    base = _base()
    for off in range(256):
        if bytes(cipher[i] ^ base[(off + i) % 256] for i in range(5)) == b'PLPcK':
            return bytes(cipher[i] ^ base[(off + i) % 256] for i in range(len(cipher)))
    raise SystemExit('could not find outer-XOR offset (no PLPcK magic)')


# ---- CDBM container ----
def walk_cdbm(d, data_start):
    N = len(d); p = data_start
    while p + 15 < N:
        keylen = d[p + 5]; valsize = struct.unpack_from('<I', d, p + 6)[0]
        if keylen == 0 or keylen > 64 or valsize < 1 or valsize > 1000000: break
        ks = p + 15; vs = ks + keylen
        if vs + valsize > N: break
        yield (d[ks:ks + keylen], d[vs:vs + valsize])
        p = vs + valsize


def cdbm_rows(plain):
    nb = struct.unpack_from('<I', plain, 0x15)[0]
    return walk_cdbm(plain, 38 + nb * 5 + 5)


# ---- table decode ----
def decode_text(keymap, path: Path | None = None):
    """`text.db` -> {export_id: text} (first two columns of each row)."""
    p = Path(path) if path is not None else _text_db_path()
    plain = outer_decrypt_textdb(p.read_bytes())
    out = {}
    for key, val in cdbm_rows(plain):
        if key.startswith(b'\t'): continue          # container metadata rows
        if key[:4] == b'\x1b\x6b\x00\x00':          # legacy XXTEA row
            pt = decrypt_value(val, keymap)
        else:                                       # res_4109+: plaintext columns
            pt = val
        if not pt: continue
        parts = [c for c in pt.split(b'\x00') if c]
        if len(parts) >= 2:
            out[parts[0].decode('utf-8', 'replace')] = parts[1].decode('utf-8', 'replace')
    return out


def decode_db_rows(path: Path, keymap):
    """Any YUNA db -> rows of decoded columns (fixed-width, positional).

    Empty columns are kept: the schemas read by the builders are positional."""
    plain = outer_decrypt_db(Path(path).read_bytes())
    rows = []
    for key, val in cdbm_rows(plain):
        if key.startswith(b'\t'): continue          # container metadata rows
        if key[:4] == b'\x1b\x6b\x00\x00':          # legacy XXTEA row
            pt = decrypt_value(val, keymap)
        else:                                       # res_4109+: plaintext columns
            pt = val
        if not pt: continue
        rows.append([c.decode('utf-8', 'replace') for c in pt.split(b'\x00')])
    return rows
