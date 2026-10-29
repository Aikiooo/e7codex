"""Emit the in-game Hero View "Background Pack" list to site/data/bg_packs.json.

This is the feature a visitor asked for: in Epic Seven's Hero View you can pick a
background from a Background Pack and it is drawn behind the hero (the game's
own note: "applied only to the selected Hero when viewing from Vertical View
mode"). The list lives in `db/item_material_bgpack.db`, and the display names in
`text.db` — both decoded with the shared YUNA/CDBM primitives in
`e7lib/dbcrypto.py`.

Columns of db/item_material_bgpack.db (15, 136 rows):

    [0]  pack id           ma_bg_epi1_5
    [2]  scene             forest2, or a legacy flat sheet like bgpack/lobby_bg1.png
    [3]  scale             1.35 … 2.2      (relative to the scene's battle framing)
    [4]  offset            "x,y,z"         (y is DOWN, like background_main.db)
    [5]  scale (b)   [6]  offset (b)       a second framing, present on 19 rows
    [7]  scale (c)   [8]  offset (c)       a third, present on 76/87 rows
    [9]  scale (d)   [10] offset (d)       a fourth, present on 83/92 rows
    [11] tint              FFD3D0         (92 rows)
    [13] alternate asset   (8 rows)

Which of the four (scale, offset) pairs applies to which view mode is NOT
settled: pair (a) is present on every usable row and is the one emitted here.
The scale is confirmed against a capture of the feature (a scene's union framed
at its pack scale matches the game); the offset's units are not — a scene whose
offset x is 3600 renders centred, so it is not a plain scene-space pan.

Usage:
    python render/bg/bg_packs.py                 # write site/data/bg_packs.json
    python render/bg/bg_packs.py --raw           # dump the table instead
"""
from __future__ import annotations

import argparse, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]   # repo root
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))          # repo root: makes e7lib importable
from e7lib.bootstrap import add_source_dirs  # noqa: E402
add_source_dirs(ROOT)
from e7lib.config import RAW_DIR  # noqa: E402
from e7lib.dbcrypto import (  # noqa: E402  YUNA/CDBM + text.db primitives
    cdbm_rows, decode_text, load_keymap, outer_decrypt_db)

DB = RAW_DIR / "db"
OUT = ROOT / "site" / "data" / "bg_packs.json"


def read_rows(dbname: str) -> list[list[str]]:
    plain = outer_decrypt_db((DB / dbname).read_bytes())
    rows = []
    for key, val in cdbm_rows(plain):
        if key.startswith(b"\t"):        # container metadata rows
            continue
        cols = [c.decode("utf-8", "replace") for c in val.split(b"\x00")]
        if any(cols):
            rows.append(cols)
    return rows


def name_map() -> dict[str, str]:
    return decode_text(load_keymap())


def pack_name(text: dict[str, str], pid: str) -> str:
    for cand in (f"lobby_bgpack_{pid}", f"bgpack_{pid}", pid, f"item_{pid}"):
        if cand in text:
            return text[cand]
    for k, v in text.items():
        if pid in k and v:
            return v
    return ""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", action="store_true")
    a = ap.parse_args()

    rows = read_rows("item_material_bgpack.db")
    if a.raw:
        for r in rows:
            print([c for c in r[:14]])
        return

    text = name_map()
    entries = []
    for r in rows:
        pid = r[0] if r else ""
        scene = (r[2] if len(r) > 2 else "") or ""
        if not pid or not scene:
            continue                      # ma_bg_base has no scene: it IS the lobby
        try:
            scale = float(r[3]) if r[3] else 1.0
        except ValueError:
            scale = 1.0
        off = [0.0, 0.0, 0.0]
        if r[4]:
            parts = r[4].split(",")
            for i in range(min(3, len(parts))):
                try:
                    off[i] = float(parts[i])
                except ValueError:
                    pass
        entries.append({
            "id": pid,
            "name": pack_name(text, pid),
            "scene": scene[:-4] if scene.endswith(".png") else scene,
            "flat": scene.endswith(".png"),      # legacy single-sheet background
            "scale": scale,
            "offset": off,
            "tint": (r[11] if len(r) > 11 else "") or "",
        })

    OUT.write_text(json.dumps(entries, indent=1, ensure_ascii=False), encoding="utf-8")
    named = sum(1 for e in entries if e["name"])
    print(f"wrote {OUT.relative_to(ROOT)}: {len(entries)} pack entries, {named} with a display name, "
          f"{len({e['scene'] for e in entries})} distinct scenes")

    # The viewer's picker needs one background image per pack entry. The gallery
    # already bakes a correct 16:9 plate per scene (render/bg/render_backgrounds.js),
    # so point at those rather than baking a second set at the pack's own
    # framing: the pack's `scale` belongs in the viewer as a live zoom, and its
    # `offset` is still unresolved (applying it panned scenes off their content).
    bg = ROOT / "site" / "data" / "backgrounds.json"
    usable = []
    if bg.exists():
        have = {d["name"]: d for d in json.loads(bg.read_text(encoding="utf-8"))}
        for e in entries:
            d = have.get(e["scene"])
            if not d:
                continue
            usable.append({**e, "file": d["file"], "thumb": d["thumb"],
                           "w": d["w"], "h": d["h"]})
    (ROOT / "site" / "data" / "bg_frames.json").write_text(
        json.dumps(usable, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"wrote site/data/bg_frames.json: {len(usable)} of {len(entries)} pack entries "
          f"have a baked background")


if __name__ == "__main__":
    main()
