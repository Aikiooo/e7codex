"""Local SSRA archive reader — `manifest.ssra` + `chunks/*.ssrc` → raw asset tree.

Since 2026-10-29 the PC client ships its assets as an **SSRA** archive instead of
`data.pack`: one `manifest.ssra` (index) plus `chunks/*.ssrc` (payload bundles).
This tool rebuilds the raw asset tree from that archive with the **same layout as
the historical `output/`**, so `private/ingest/extract_pack.py --from-tree <dir>` takes
over unchanged. Correctness is checked by hashes and sizes, never by eye.

This module is the **local reader and nothing else**: it opens a manifest and the
chunk files already on disk. It carries NO network code — no HTTP client, no URL,
no downloader and no download flag. A chunk missing locally is a hard stop: the
missing names are listed and the tool exits non-zero (fail closed). Run the game
client once so it has installed every group you need. **Keep it that way: no
network code in this file, ever.**

What it does:

  1. Parses `manifest.ssra` and sanity-checks EVERY table entry: magic/version,
     tables inside the file, the asset table ending exactly at the string table,
     every path offset landing on a string start, and every path's xxh64 matching
     its record. Any mismatch aborts with exit 1 (fail closed).
  2. Resolves every chunk from the local read-only sources it is given (by
     default the installed client's `chunks/`), verifying size + trailer + xxh64
     of each chunk it reads.
  3. Extracts chunk by chunk: one chunk is read into memory and verified once,
     then its assets are written in offset order. No other chunk is held.
  4. Writes `<out>.report.json` NEXT TO the tree (not inside it — the tree is
     renamed to `output/` by the swap), carrying manifest identity, per-group
     counts, chunk provenance and any failures.

Format (verified against client build 12 — all integers little-endian):

  header       'SSRA' | u32 version=4 | u32 build | u32 chunk count
               | u32 asset count | u32 (unknown) | u64 string-table off SB
               | u64 string-table len | u64 chunk-table off | u64 asset-table off
  chunk table  32 B: u32 index | u16 group | u16 one | u64 payload_size
               | u64 stored_size | u64 xxh64(payload)
               names: the first `chunk count` NUL-terminated strings at SB, in order
  chunk file   payload | b'SSRC' + u32 chunk index + u64 xxh64(payload)
               (the u32 is the record's own `index` field, not a constant: every
               one of the 109 locally available chunks carries its index here)
  asset table  40 B: u64 xxh64(path) | u64 offset in the GROUP stream
               | u32 stored | u32 raw | u32 0 | u32 path off (relative to SB)
               | u16 flag (1 = zstd, 0 = raw) | u16 group | u32 0
  group stream all chunks of the group concatenated in chunk-index order; no asset
               straddles two chunks (a straddle is an error, not a guess)

Group name = chunk name minus the `_bNN_N.ssrc` suffix (`cat_effect_b03_0.ssrc`
-> `cat_effect`). Hash-suffixed `cat_sound_large_<hash>.ssrc` chunks take the name
of their group's other chunks; if the group holds none, `cat_sound_large`.

The default selection reproduces the historical `output/` tree: every group
except `media_*` (localized voice banks — another route), `cinema_zl`,
`cinema_zl_ja` and `pub_zl`. `--include-media` adds the voice banks;
`--groups a,b` overrides the selection completely.

Chunk presence is decided by size + trailer (cheap, no full read); the xxh64 of
every chunk is verified when the chunk is read, and `--verify-only` hashes all
chunks and decodes every asset before anything is written.

Config: the game dir defaults to `GAME_RES_DIR` from e7lib/config.py (the
installed client: READ-ONLY, never written, never created into); nothing else is
needed from the keys file — `--game-dir` alone is enough.

Usage:
  python convert/ssra.py --game-dir <dir> --list          # per-group inventory, no writes
  python convert/ssra.py --game-dir <dir>                 # full default extraction
  python convert/ssra.py --game-dir <dir> --verify-only   # hash/decode everything, write nothing
  python convert/ssra.py --game-dir <dir> --include-media # add the media_* voice banks
  python convert/ssra.py --game-dir <dir> --groups cat_db,base  # explicit group set
  python convert/ssra.py --game-dir <dir> --force         # replace a non-empty --out

The archive, its chunks and the extracted tree stay LOCAL. Like
private/ingest/extract_pack.py, this tool handles game content and must not be
used to redistribute it: the chunks are the heaviest DMCA surface of the
pipeline. The tool itself is public; the data never is.
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import shutil
import struct
import sys
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

import xxhash
import zstandard

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

THIS = Path(__file__).resolve()
PACKAGE = THIS.parent                      # convert/
REPO = THIS.parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))          # repo root: makes e7lib importable

# The configured scratch dir: only the default --out lives under it.
from e7lib.config import CDN_WORK_DIR as WORK_DIR, GAME_RES_DIR as _GAME_RES_DIR  # noqa: E402
from e7lib.log import log  # noqa: E402  shared [HH:MM:SS] progress line

MANIFEST_MAGIC = b"SSRA"
MANIFEST_VERSION = 4
TRAILER_MAGIC = b"SSRC"
HEADER = struct.Struct("<4sIIIIIQQQQ")     # 0x00..0x37, 56 bytes
CHUNK_REC = struct.Struct("<IHHQQQ")       # 32 bytes
ASSET_REC = struct.Struct("<QQIIIIHHI")    # 40 bytes
TRAILER = struct.Struct("<4sIQ")           # 16 bytes
READ_BLOCK = 1 << 20                       # streaming verification block

# Historical output/ = every group but these (localized voice banks, legacy
# Chinese cinema/pub bundles). Verified against the 67 top-level dirs of the tree.
EXCLUDE_GROUPS = ("cinema_zl", "cinema_zl_ja", "pub_zl")
MEDIA_PREFIX = "media_"

_GROUP_SUFFIX = re.compile(r"_b\d+_\d+$")
_HASH_SUFFIX = re.compile(r"_[0-9a-f]{8}$")
_DRIVE = re.compile(r"^[A-Za-z]:")


class SsraError(Exception):
    """A format or configuration violation — always fatal, never papered over."""


# --------------------------------------------------------------------------- model
@dataclass
class Chunk:
    index: int
    group: int
    payload_size: int
    stored_size: int
    xxh64: int
    name: str = ""
    pos: int = -1         # position in the chunk table (unique key)


@dataclass
class Asset:
    path: str
    chunk: int
    offset: int           # offset inside that chunk's payload
    stored: int
    raw: int
    zstd: bool
    gid: int


@dataclass
class Manifest:
    path: Path
    size: int
    xxh64: int
    version: int
    build: int
    string_off: int
    string_len: int
    chunks: list
    assets: list
    groups: dict = field(default_factory=dict)        # group id -> group name
    group_chunks: dict = field(default_factory=dict)  # group name -> [table positions]


# --------------------------------------------------------------------------- manifest
def _read_cstr(buf: bytes, off: int, limit: int) -> str:
    if off < 0 or off >= limit:
        raise SsraError(f"string offset {off:,} outside the file (limit {limit:,})")
    end = buf.find(b"\0", off, limit)
    if end < 0:
        raise SsraError(f"unterminated string at offset {off:,}")
    try:
        return buf[off:end].decode("utf-8")
    except UnicodeDecodeError as e:
        raise SsraError(f"non-UTF-8 string at offset {off:,} ({e})") from e


def _chunk_base(name: str) -> str | None:
    """`cat_effect_b03_0.ssrc` -> `cat_effect`; None for a hash-suffixed name."""
    stem = name[:-5]
    m = _GROUP_SUFFIX.search(stem)
    return stem[:m.start()] if m else None


def _check_asset_path(path: str) -> None:
    if not path:
        raise SsraError("empty asset path")
    if "\\" in path:
        raise SsraError(f"asset path uses a backslash: {path!r}")
    if path.startswith("/") or _DRIVE.match(path) or path.startswith("//"):
        raise SsraError(f"asset path is absolute: {path!r}")
    for part in path.split("/"):
        if part in ("", ".", ".."):
            raise SsraError(f"asset path has an unsafe part {part!r}: {path!r}")


def parse_manifest(path: Path) -> Manifest:
    """Parse + fully validate the manifest. Every mismatch raises SsraError."""
    try:
        buf = path.read_bytes()
    except OSError as e:
        raise SsraError(f"cannot read manifest {path}: {e}") from e
    size = len(buf)
    if size < HEADER.size:
        raise SsraError(f"manifest is {size} bytes, smaller than its header")

    (magic, version, build, n_chunks, n_assets, _unknown,
     sb, slen, chunk_off, asset_off) = HEADER.unpack_from(buf, 0)

    if magic != MANIFEST_MAGIC:
        raise SsraError(f"bad magic {magic!r}, expected {MANIFEST_MAGIC!r}")
    if version != MANIFEST_VERSION:
        raise SsraError(f"unsupported manifest version {version} "
                        f"(this tool knows {MANIFEST_VERSION})")

    if n_chunks == 0 or n_assets == 0:
        raise SsraError(f"empty tables (chunks={n_chunks}, assets={n_assets})")
    if chunk_off < HEADER.size or chunk_off + n_chunks * CHUNK_REC.size > size:
        raise SsraError(f"chunk table ({chunk_off:,} + {n_chunks:,}x32) is outside the file")
    if asset_off < HEADER.size or asset_off >= sb:
        raise SsraError(f"asset table offset {asset_off:,} is not before the strings at {sb:,}")
    end_assets = asset_off + n_assets * ASSET_REC.size
    if end_assets != sb:
        raise SsraError(f"asset table ends at {end_assets:,}, "
                        f"expected the string table at {sb:,}")
    if sb + slen > size:
        raise SsraError(f"string table {sb:,}+{slen:,} runs past the file ({size:,})")

    log(f"manifest: {path} — build {build}, version {version}, {n_chunks:,} chunks, "
        f"{n_assets:,} assets, {size:,} B")

    # --- chunk table + names ----------------------------------------------
    chunks = []
    for i in range(n_chunks):
        index, group, one, payload, stored, digest = CHUNK_REC.unpack_from(
            buf, chunk_off + i * CHUNK_REC.size)
        if one != 1:
            raise SsraError(f"chunk {i} flag is {one}, expected 1")
        if stored != payload + TRAILER.size:
            raise SsraError(f"chunk {i}: stored {stored:,} != payload {payload:,} + 16")
        chunks.append(Chunk(index, group, payload, stored, digest, "", i))

    pos = sb
    for i in range(n_chunks):
        name = _read_cstr(buf, pos, size)
        if "/" in name or "\\" in name or not name.endswith(".ssrc"):
            raise SsraError(f"chunk {i} has an unexpected name {name!r}")
        chunks[i].name = name
        pos += len(name.encode("utf-8")) + 1
    names = [c.name for c in chunks]
    if len(set(names)) != len(names):
        dupes = sorted({n for n in names if names.count(n) > 1})
        raise SsraError(f"duplicate chunk names: {dupes[:5]}")

    # --- group ids -> names -----------------------------------------------
    # The per-record index is the chunk's position INSIDE its group (0..n-1,
    # contiguous), not a global table index — validate that and sort by it.
    by_group: dict[int, list[int]] = {}
    for i, c in enumerate(chunks):
        by_group.setdefault(c.group, []).append(i)
    for gid, idxs in by_group.items():
        got = sorted(chunks[i].index for i in idxs)
        if got != list(range(len(idxs))):
            raise SsraError(f"group {gid} ({names[idxs[0]]}): chunk indices {got} "
                            f"are not 0..{len(idxs) - 1}")
    groups: dict[int, str] = {}
    for gid, idxs in by_group.items():
        bases = [b for b in (_chunk_base(names[i]) for i in idxs) if b]
        if bases:
            groups[gid] = collections.Counter(bases).most_common(1)[0][0]
        else:
            stem = names[idxs[0]][:-5]
            m = _HASH_SUFFIX.search(stem)
            groups[gid] = stem[:m.start()] if m else stem
    if len(set(groups.values())) != len(groups):
        vals = list(groups.values())
        dupes = sorted({n for n in vals if vals.count(n) > 1})
        raise SsraError(f"two group ids resolve to the same name: {dupes}")

    by_index = {gid: sorted(idxs, key=lambda i: chunks[i].index)
                for gid, idxs in by_group.items()}
    group_chunks = {groups[gid]: idxs for gid, idxs in by_index.items()}

    # --- string starts (every path offset must land on one) ---------------
    starts = set()
    p = sb
    while p < size:
        end = buf.find(b"\0", p)
        if end < 0:
            break
        starts.add(p - sb)
        p = end + 1

    # --- asset table -------------------------------------------------------
    assets = []
    seen: dict[str, str] = {}
    for i in range(n_assets):
        (digest, off, stored, raw, zero1, path_off, flag, gid, zero2) = \
            ASSET_REC.unpack_from(buf, asset_off + i * ASSET_REC.size)
        if zero1 or zero2:
            raise SsraError(f"asset {i}: reserved field is not zero ({zero1}, {zero2})")
        if path_off not in starts:
            raise SsraError(f"asset {i}: path offset {path_off:,} is not a string start")
        path_str = _read_cstr(buf, sb + path_off, size)
        if xxhash.xxh64(path_str.encode("utf-8")).intdigest() != digest:
            raise SsraError(f"asset {i}: path hash mismatch for {path_str!r}")
        if gid not in groups:
            raise SsraError(f"asset {i} ({path_str!r}): unknown group id {gid}")
        if flag not in (0, 1):
            raise SsraError(f"asset {i} ({path_str!r}): unknown flag {flag}")
        if flag == 1 and stored == raw:
            raise SsraError(f"asset {i} ({path_str!r}): zstd flag but stored == raw")
        if flag == 0 and stored != raw:
            raise SsraError(f"asset {i} ({path_str!r}): raw flag but stored "
                            f"{stored:,} != raw {raw:,}")
        if raw > 0 and stored == 0:
            raise SsraError(f"asset {i} ({path_str!r}): no stored bytes for {raw:,}")
        _check_asset_path(path_str)
        low = path_str.lower()
        if low in seen:
            raise SsraError(f"duplicate asset path (case-insensitive): "
                            f"{path_str!r} / {seen[low]!r}")
        seen[low] = path_str
        assets.append(Asset(path_str, -1, off, stored, raw, flag == 1, gid))

    # --- locate every asset in its group stream ---------------------------
    spans: dict[int, list[tuple[int, int]]] = {}
    totals: dict[int, int] = {}
    for gid, idxs in by_index.items():
        acc = 0
        entries = []
        for ci in idxs:
            entries.append((ci, acc))
            acc += chunks[ci].payload_size
        spans[gid] = entries
        totals[gid] = acc

    for a in assets:
        want = a.offset
        placed = False
        for ci, acc in spans[a.gid]:
            hi = acc + chunks[ci].payload_size
            if want < hi or (a.stored == 0 and want <= hi):
                if want + a.stored > hi:
                    raise SsraError(f"asset {a.path!r} straddles chunks "
                                    f"(offset {want:,}, {a.stored:,} B, chunk ends {hi:,})")
                a.chunk = ci
                a.offset = want - acc
                placed = True
                break
        if not placed:
            raise SsraError(f"asset {a.path!r}: offset {want:,} + {a.stored:,} B is past "
                            f"the group stream end ({totals[a.gid]:,})")

    mf = Manifest(path=path, size=size,
                  xxh64=xxhash.xxh64(buf).intdigest(),
                  version=version, build=build,
                  string_off=sb, string_len=slen,
                  chunks=chunks, assets=assets,
                  groups=groups, group_chunks=group_chunks)
    log(f"manifest OK: {len(groups)} groups, every path hash verified")
    return mf


# --------------------------------------------------------------------------- selection
def select_groups(mf: Manifest, groups_arg: str | None, include_media: bool) -> list[str]:
    all_names = sorted(mf.group_chunks)
    if groups_arg:
        wanted = []
        for raw in groups_arg.split(","):
            name = raw.strip()
            if name and name not in wanted:
                wanted.append(name)
        unknown = [n for n in wanted if n not in mf.group_chunks]
        if unknown:
            raise SsraError(f"unknown group(s): {', '.join(unknown)}\n"
                            f"known: {', '.join(all_names)}")
        if not wanted:
            raise SsraError("--groups selected nothing")
        return wanted
    sel = [n for n in all_names
           if n not in EXCLUDE_GROUPS and not n.startswith(MEDIA_PREFIX)]
    if include_media:
        sel += [n for n in all_names if n.startswith(MEDIA_PREFIX)]
    return sel


# --------------------------------------------------------------------------- chunk io
def probe_chunk(path: Path, c: Chunk) -> str | None:
    """Cheap presence check: size + trailer. None when it looks usable."""
    try:
        if not path.is_file():
            return "not a file"
        size = path.stat().st_size
    except OSError as e:
        return f"unreadable ({e})"
    if size != c.stored_size:
        return f"size {size:,} != {c.stored_size:,}"
    try:
        with open(path, "rb") as f:
            f.seek(c.payload_size)
            raw = f.read(TRAILER.size)
    except OSError as e:
        return f"unreadable ({e})"
    if len(raw) != TRAILER.size:
        return "truncated trailer"
    magic, version, digest = TRAILER.unpack(raw)
    if magic != TRAILER_MAGIC:
        return f"trailer magic {magic!r}"
    if version != c.index:
        return f"trailer index {version} != chunk index {c.index}"
    if digest != c.xxh64:
        return f"trailer hash {digest:016x} != table {c.xxh64:016x}"
    return None


def verify_chunk_file(path: Path, c: Chunk) -> None:
    """Full verification (size + payload xxh64 + trailer), streaming."""
    try:
        size = path.stat().st_size
    except OSError as e:
        raise SsraError(f"chunk {c.name}: cannot stat {path}: {e}") from e
    if size != c.stored_size:
        raise SsraError(f"chunk {c.name}: size {size:,} != stored_size {c.stored_size:,}")
    h = xxhash.xxh64()
    with open(path, "rb") as f:
        left = c.payload_size
        while left:
            b = f.read(min(READ_BLOCK, left))
            if not b:
                raise SsraError(f"chunk {c.name}: truncated payload")
            h.update(b)
            left -= len(b)
        raw = f.read(TRAILER.size)
    if len(raw) != TRAILER.size:
        raise SsraError(f"chunk {c.name}: truncated trailer")
    magic, version, digest = TRAILER.unpack(raw)
    if magic != TRAILER_MAGIC or version != c.index:
        raise SsraError(f"chunk {c.name}: bad trailer {magic!r}/{version} "
                        f"(expected {TRAILER_MAGIC!r}/{c.index})")
    got = h.intdigest()
    if got != c.xxh64:
        raise SsraError(f"chunk {c.name}: payload xxh64 {got:016x} != table {c.xxh64:016x}")
    if digest != c.xxh64:
        raise SsraError(f"chunk {c.name}: trailer xxh64 {digest:016x} != table {c.xxh64:016x}")


def load_chunk(path: Path, c: Chunk) -> bytes:
    """Read a whole chunk and verify size + payload hash + trailer, once."""
    data = path.read_bytes()
    if len(data) != c.stored_size:
        raise SsraError(f"chunk {c.name}: {len(data):,} B on disk, expected {c.stored_size:,}")
    payload = data[:c.payload_size]
    got = xxhash.xxh64(payload).intdigest()
    if got != c.xxh64:
        raise SsraError(f"chunk {c.name}: payload xxh64 {got:016x} != table {c.xxh64:016x}")
    magic, version, digest = TRAILER.unpack_from(data, c.payload_size)
    if magic != TRAILER_MAGIC or version != c.index:
        raise SsraError(f"chunk {c.name}: bad trailer {magic!r}/{version} "
                        f"(expected {TRAILER_MAGIC!r}/{c.index})")
    if digest != c.xxh64:
        raise SsraError(f"chunk {c.name}: trailer xxh64 {digest:016x} != table {c.xxh64:016x}")
    return payload


# --------------------------------------------------------------------------- plan
def locate_all(mf: Manifest, selected: list[str] | None):
    """Return (selected group names, {chunk index: [assets]}, chunks_needed)."""
    if selected is None:
        selected = sorted(mf.group_chunks)
    wanted = set(selected)
    per_chunk: dict[int, list[Asset]] = {}
    group_of_chunk = {c.pos: mf.groups[c.group] for c in mf.chunks}
    for a in mf.assets:
        if group_of_chunk[a.chunk] in wanted:
            per_chunk.setdefault(a.chunk, []).append(a)
    chunks_needed = sorted(per_chunk)
    for lst in per_chunk.values():
        lst.sort(key=lambda x: x.offset)
    return selected, per_chunk, chunks_needed


def inventory(mf: Manifest, selected: list[str]) -> dict:
    group_of_chunk = {c.pos: mf.groups[c.group] for c in mf.chunks}
    inv = {name: {"files": 0, "bytes": 0, "chunks": 0, "missing": []}
           for name in selected}
    for name in selected:
        inv[name]["chunks"] = len(mf.group_chunks[name])
    for a in mf.assets:
        gname = group_of_chunk[a.chunk]
        if gname in inv:
            inv[gname]["files"] += 1
            inv[gname]["bytes"] += a.raw
    return inv


# --------------------------------------------------------------------------- output guard
def check_out(out: Path, game_dir: Path) -> Path:
    """Reject an --out that would delete/replace the client, the repo or the cache."""
    out = out.resolve()
    guarded = [game_dir.resolve(), REPO.resolve(), WORK_DIR.resolve(), PACKAGE.resolve()]
    for g in guarded:
        if out == g or out in g.parents:
            raise SsraError(f"refusing to write the tree to {out}: it contains {g}")
    # Inside the repo only the local-only trees are allowed (data/ is the dump,
    # gitignored); never the client, the site, the tools or the staged externals.
    forbidden = [game_dir.resolve(), REPO.resolve() / ".git", REPO.resolve() / "site",
                 REPO.resolve() / "pipeline", REPO.resolve() / "convert",
                 REPO.resolve() / "render", REPO.resolve() / "ops",
                 REPO.resolve() / "private", REPO.resolve() / "data_external"]
    for g in forbidden:
        if g == out or g in out.parents:
            raise SsraError(f"refusing to write the tree inside {g}")
    return out


def prepare_out(out: Path, force: bool, game_dir: Path) -> Path:
    out = check_out(out, game_dir)
    if out.exists():
        if not out.is_dir():
            raise SsraError(f"--out {out} exists and is not a directory")
        if any(out.iterdir()):
            if not force:
                raise SsraError(f"--out {out} is not empty; pass --force to replace it")
            log(f"removing existing {out}")
            shutil.rmtree(out)
    return out


# --------------------------------------------------------------------------- cli
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Extract a local SSRA archive (manifest.ssra + chunks/*.ssrc) "
                    "into the raw asset tree layout consumed by "
                    "extract_pack.py --from-tree. Reads local files only.")
    p.add_argument("--game-dir", type=Path, default=None,
                   help="installed client dir holding manifest.ssra + chunks/ "
                        "(default: game_res_dir from e7lib/config.py)")
    p.add_argument("--manifest", type=Path, default=None,
                   help="manifest.ssra path (default: <game-dir>/manifest.ssra)")
    p.add_argument("--out", type=Path, default=WORK_DIR / "_staging_assets_ssra",
                   help="output tree (default: <configured work dir>/_staging_assets_ssra)")
    p.add_argument("--groups", default=None,
                   help="comma-separated group names; overrides the default selection")
    p.add_argument("--include-media", action="store_true",
                   help="also extract the media_* localized voice banks")
    p.add_argument("--list", action="store_true",
                   help="print the per-group inventory and exit without extracting")
    p.add_argument("--verify-only", action="store_true",
                   help="verify every chunk and decode every asset; write nothing to --out")
    p.add_argument("--force", action="store_true",
                   help="replace a non-empty --out (only that directory is deleted)")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    t0 = time.time()
    try:
        return run(args, t0)
    except SsraError as e:
        log(f"ERROR: {e}")
        return 1
    except KeyboardInterrupt:
        log("interrupted")
        return 130
    except Exception:
        log("ERROR: unexpected failure")
        traceback.print_exc()
        return 1


def resolve_manifest(args) -> tuple[Path, str]:
    """(path, origin) from --manifest, else the game dir. Local files only."""
    if args.manifest:
        p = Path(args.manifest)
        if not p.is_file():
            raise SsraError(f"--manifest {p} does not exist")
        return p, "cli"
    game_dir = resolve_game_dir(args)
    p = game_dir / "manifest.ssra"
    if not p.is_file():
        raise SsraError(f"no manifest: pass --manifest or provide {p}")
    return p, "game"


def resolve_game_dir(args) -> Path:
    """--game-dir, else GAME_RES_DIR from e7lib/config.py, else a clear error."""
    raw = getattr(args, "game_dir", None)
    if raw:
        return Path(raw)
    if _GAME_RES_DIR:
        return Path(_GAME_RES_DIR)
    raise SsraError("no game dir: pass --game-dir <dir holding manifest.ssra + chunks/>")


def run(args, t0: float, *,
        game_dir: Path | None = None,
        manifest_source: tuple[Path, str] | None = None,
        chunk_dirs: Iterable[tuple[Path, str]] | None = None,
        fill_missing: Callable[[Manifest, list[Chunk], dict], None] | None = None,
        missing_hint: str = "",
        recover_hint: str = "",
        report_tool: str = "ssra",
        report_context: str | None = None,
        report_manifest_extra: dict | None = None) -> int:
    """The whole extraction, local-only.

    Hooks exist so the private network wrapper can drive this same code without
    this file knowing anything about the network:

      game_dir       the READ-ONLY client dir to guard (default: resolved from args)
      manifest_source  pre-resolved (path, origin); default: args/game dir
      chunk_dirs     [(dir, kind)] local chunk sources, first hit wins; the `kind`
                     string is what the report counts. Default: <game_dir>/chunks.
      fill_missing   called with (manifest, missing, source) when chunks are absent;
                     it must add `source[pos] = (path, kind)` or raise. Default: fail.
      missing_hint   appended to the missing-chunks message.
      recover_hint   the caller's command for re-obtaining a chunk (the local
                     reader has none).
      report_tool / report_context / report_manifest_extra
                     report identity, so the wrapper's report keeps its fields.
    """
    if game_dir is None:
        game_dir = resolve_game_dir(args)
    game_dir = Path(game_dir)
    if chunk_dirs is None:
        chunk_dirs = [(game_dir / "chunks", "local")]
    chunk_dirs = list(chunk_dirs)

    # --- manifest ---------------------------------------------------------
    if manifest_source is None:
        manifest_path, origin = resolve_manifest(args)
    else:
        manifest_path, origin = manifest_source
    mf = parse_manifest(manifest_path)
    log(f"manifest origin: {origin}")

    selected = select_groups(mf, args.groups, args.include_media)
    sel, per_chunk, chunks_needed = locate_all(mf, selected)
    group_of_chunk = {c.pos: mf.groups[c.group] for c in mf.chunks}
    inv = inventory(mf, sel)

    total_files = sum(g["files"] for g in inv.values())
    total_bytes = sum(g["bytes"] for g in inv.values())
    log(f"selection: {len(sel)}/{len(mf.group_chunks)} groups, "
        f"{total_files:,} assets, {total_bytes:,} B raw, "
        f"{len(chunks_needed)} chunks")

    # --- chunk resolution --------------------------------------------------
    source: dict[int, tuple[Path, str]] = {}
    missing: list[Chunk] = []
    for ci in chunks_needed:
        c = mf.chunks[ci]
        for directory, kind in chunk_dirs:
            cand = Path(directory) / c.name
            if cand.is_file():
                reason = probe_chunk(cand, c)
                if reason is None:
                    source[ci] = (cand, kind)
                    break
                log(f"  WARN {c.name}: {kind} copy unusable ({reason})")
        else:
            missing.append(c)

    for c in missing:
        inv[group_of_chunk[c.pos]]["missing"].append(c.name)

    if args.list:
        print_inventory(sel, inv, missing, chunks_needed)
        return 0

    if missing and fill_missing is None:
        raise_missing(missing, missing_hint)

    if not args.verify_only:
        early = check_out(args.out, game_dir)
        if early.exists() and any(early.iterdir()) and not args.force:
            raise SsraError(f"--out {early} is not empty; pass --force to replace it")

    # --- the caller's hook supplies what is absent locally ----------------
    if missing:
        fill_missing(mf, missing, source)

    # --- verify-only: hash every chunk, decode every asset, write nothing --
    if args.verify_only:
        return do_verify_only(mf, sel, per_chunk, chunks_needed, source, inv,
                              total_files, total_bytes, t0, manifest_path, args.out,
                              report_tool, report_context, report_manifest_extra)

    # --- output tree -------------------------------------------------------
    out = prepare_out(args.out, args.force, game_dir)
    out.mkdir(parents=True, exist_ok=True)
    log(f"extracting into {out}")

    dctx = zstandard.ZstdDecompressor()
    failures: list[dict] = []
    written = 0
    written_bytes = 0

    for n, ci in enumerate(chunks_needed, 1):
        c = mf.chunks[ci]
        path, kind = source[ci]
        try:
            payload = load_chunk(path, c)
        except SsraError as e:
            raise SsraError(f"{e}{_recovery_hint(path, recover_hint)}") from e
        gname = group_of_chunk[ci]
        n_ok = 0
        for a in per_chunk[ci]:
            try:
                data = payload[a.offset:a.offset + a.stored]
                if a.zstd:
                    data = dctx.decompress(data, max_output_size=a.raw)
                if len(data) != a.raw:
                    raise SsraError(f"{a.path!r}: decoded {len(data):,} B, expected {a.raw:,}")
                dst = out.joinpath(*a.path.split("/"))
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_bytes(data)
                written += 1
                written_bytes += len(data)
                n_ok += 1
            except SsraError as e:
                failures.append({"path": a.path, "chunk": c.name, "error": str(e)})
            except Exception as e:
                failures.append({"path": a.path, "chunk": c.name,
                                 "error": f"{type(e).__name__}: {e}"})
        del payload
        if n % 10 == 0 or n == len(chunks_needed):
            log(f"  [{n}/{len(chunks_needed)}] {gname}/{c.name}: {n_ok} files, "
                f"{written:,} total")

    counts: dict[str, int] = {kind: 0 for _dir, kind in chunk_dirs}
    counts.update({"downloaded": 0})
    for ci in chunks_needed:
        counts[source[ci][1]] += 1
    used_bytes = sum(mf.chunks[ci].stored_size for ci in chunks_needed)

    log(f"wrote {written:,} files, {written_bytes:,} B in {time.time() - t0:.1f}s")
    if failures:
        log(f"FAILURES: {len(failures)} (first: {failures[0]})")

    report = {
        "tool": report_tool,
        "mode": "extract",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "duration_s": round(time.time() - t0, 1),
        "out": str(out),
    }
    if report_context is not None:
        report["context"] = report_context
    report["manifest"] = {
        "path": str(manifest_path),
        "origin": origin,
        "size": mf.size,
        "xxh64": f"{mf.xxh64:016x}",
        "version": mf.version,
        "build": mf.build,
        "chunks": len(mf.chunks),
        "assets": len(mf.assets),
        **(report_manifest_extra or {}),
    }
    report["selection"] = {"groups": sel, "count": len(sel)}
    report["groups"] = {name: {"files": inv[name]["files"], "bytes": inv[name]["bytes"],
                               "chunks": len(mf.group_chunks[name])} for name in sel}
    report["chunks"] = {
        "used": len(chunks_needed),
        "local": counts.get("local", 0),
        "cache": counts.get("cache", 0),
        "downloaded": counts.get("downloaded", 0),
        "stored_bytes": used_bytes,
    }
    report["totals"] = {"files": written, "bytes": written_bytes}
    report["failures"] = failures
    write_report(out, report)
    return 1 if failures else 0


def _recovery_hint(path: Path, recover: str) -> str:
    """Tail for a chunk that was present but failed its hash on read."""
    if recover:
        return f" — delete {path} and re-run with {recover}"
    return f" — {path} is corrupt or stale; get a good copy and re-run"


def raise_missing(missing: list[Chunk], hint: str = "") -> None:
    total = sum(c.stored_size for c in missing)
    log(f"MISSING {len(missing)} chunk(s), {total / 1e6:.1f} MB "
        f"— nothing was written.{hint}")
    for c in missing:
        log(f"  {c.name:<40} {c.stored_size:>13,} B")
    raise SystemExit(2)


def print_inventory(sel: list[str], inv: dict, missing: list[Chunk],
                    chunks_needed: list[int]) -> None:
    print()
    print(f"{'group':<24}{'files':>8}{'bytes':>16}{'chunks':>8}  missing")
    print("-" * 78)
    for name in sel:
        g = inv[name]
        miss = ",".join(g["missing"]) if g["missing"] else "-"
        print(f"{name:<24}{g['files']:>8,}{g['bytes']:>16,}{g['chunks']:>8}  {miss}")
    print("-" * 78)
    tf = sum(g["files"] for g in inv.values())
    tb = sum(g["bytes"] for g in inv.values())
    nch = sum(g["chunks"] for g in inv.values())
    print(f"{'TOTAL':<24}{tf:>8,}{tb:>16,}{nch:>8}")
    print()
    if missing:
        total = sum(c.stored_size for c in missing)
        print(f"{len(missing)} of {len(chunks_needed)} chunk(s) missing locally: "
              f"{total:,} B ({total / 1e6:.1f} MB)")
        for c in missing:
            print(f"  {c.name:<40} {c.stored_size:>13,} B")
    else:
        print(f"all {len(chunks_needed)} chunks present")


def do_verify_only(mf, sel, per_chunk, chunks_needed, source, inv,
                   total_files, total_bytes, t0, manifest_path, out: Path,
                   report_tool: str, report_context: str | None,
                   report_manifest_extra: dict | None) -> int:
    log(f"verify-only: hashing {len(chunks_needed)} chunks and decoding "
        f"{total_files:,} assets (nothing written)")
    dctx = zstandard.ZstdDecompressor()
    failures: list[dict] = []
    decoded = 0
    for n, ci in enumerate(chunks_needed, 1):
        c = mf.chunks[ci]
        path, _kind = source[ci]
        verify_chunk_file(path, c)
        payload = load_chunk(path, c)
        for a in per_chunk[ci]:
            try:
                data = payload[a.offset:a.offset + a.stored]
                if a.zstd:
                    data = dctx.decompress(data, max_output_size=a.raw)
                if len(data) != a.raw:
                    raise SsraError(f"{a.path!r}: decoded {len(data):,} B, "
                                    f"expected {a.raw:,}")
                decoded += 1
            except Exception as e:
                failures.append({"path": a.path, "chunk": c.name, "error": str(e)})
        del payload
        if n % 10 == 0 or n == len(chunks_needed):
            log(f"  [{n}/{len(chunks_needed)}] verified {decoded:,} assets")
    counts: dict[str, int] = {"local": 0, "cache": 0, "downloaded": 0}
    for ci in chunks_needed:
        counts[source[ci][1]] = counts.get(source[ci][1], 0) + 1
    log(f"verify-only: {len(chunks_needed)} chunks OK, {decoded:,} assets decoded, "
        f"{len(failures)} failure(s)")
    report = {
        "tool": report_tool,
        "mode": "verify-only",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "duration_s": round(time.time() - t0, 1),
        "out": None,
    }
    if report_context is not None:
        report["context"] = report_context
    report["manifest"] = {
        "path": str(manifest_path),
        "size": mf.size,
        "xxh64": f"{mf.xxh64:016x}",
        "version": mf.version,
        "build": mf.build,
        "chunks": len(mf.chunks),
        "assets": len(mf.assets),
        **(report_manifest_extra or {}),
    }
    report["selection"] = {"groups": sel, "count": len(sel)}
    report["groups"] = {name: {"files": inv[name]["files"], "bytes": inv[name]["bytes"],
                               "chunks": len(mf.group_chunks[name])} for name in sel}
    report["chunks"] = {"used": len(chunks_needed), **counts}
    report["totals"] = {"files": decoded, "bytes": total_bytes}
    report["failures"] = failures
    write_report(out, report)
    return 1 if failures else 0


def write_report(out: Path, report: dict) -> None:
    """`<out>.report.json`, next to the tree (the tree itself becomes output/)."""
    path = out.with_name(out.name + ".report.json")
    tmp = path.with_name(path.name + ".tmp")
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    log(f"report: {path}")


if __name__ == "__main__":
    sys.exit(main())
