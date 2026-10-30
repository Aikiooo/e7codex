"""Filesystem helpers shared by the build steps."""
from __future__ import annotations

import os
from pathlib import Path


def walk(root: Path):
    if not root.exists(): return
    for dp, _, fs in os.walk(root):
        for f in fs:
            yield Path(dp) / f


def force_webp_loop(path: Path) -> bool:
    """Set an animated WebP's ANIM loop count to 0 (infinite). Newer packs
    ship cut-ins/emotes with loop=1 (first seen: c5069 skill cut-in,
    2026-06-11; c5147 emote, 2026-07-03) which play once and freeze in the
    gallery; every older animation loops. Walks the top-level RIFF chunks
    (no naive byte search — 'ANIM' can occur in compressed payloads).
    Returns True if it rewrote the file; False (no-op) for static or
    already-looping files. Idempotent — safe to re-run on staged files."""
    try:
        b = bytearray(path.read_bytes())
    except OSError:
        return False
    if len(b) < 12 or b[0:4] != b"RIFF" or b[8:12] != b"WEBP":
        return False
    pos = 12
    while pos + 8 <= len(b):
        fourcc = bytes(b[pos:pos + 4])
        size = int.from_bytes(b[pos + 4:pos + 8], "little")
        if fourcc == b"ANIM" and size >= 6:
            loop_at = pos + 8 + 4          # payload: u32 bg color, u16 loop
            if b[loop_at:loop_at + 2] != b"\x00\x00":
                b[loop_at:loop_at + 2] = b"\x00\x00"
                try:
                    path.write_bytes(b)
                    return True
                except OSError:
                    return False
            return False
        pos += 8 + size + (size & 1)       # chunks are 2-byte aligned
    return False


def sweep_webp_loops(site_assets: Path) -> int:
    """Force an infinite loop on EVERY staged animated WebP; returns how many
    files were rewritten. Unconditional and idempotent, so a copy path nobody
    wired to force_webp_loop() still cannot ship a play-once animation."""
    return sum(force_webp_loop(p) for p in site_assets.rglob("*.webp"))
