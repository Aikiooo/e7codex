"""Build profile-frame catalog for the avatar + frame compositor (TASKS.md #32).

Indexes in-game profile borders (`img_output/item/border/*.png`, all 148×148)
plus extra circular rings community asked for (legacy device frames and
battle-UI hero rings), staged at a uniform 148×148 canvas.

  - `site/data/frames.json` — committed catalog (like units.json)
  - `site/assets/_frames/` — staged PNGs under the gitignored `site/assets/`
    (present on the deploy machine; wrangler uploads them with Pages)

Usage:
  python tools/build_frames.py
  python tools/build_frames.py --src D:/path/to/img_output/item/border
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from paths import IMG_DIR  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    Image = None  # type: ignore

REPO = Path(__file__).resolve().parents[1]
SITE = REPO / "site"
DATA_OUT = SITE / "data" / "frames.json"
ASSET_OUT = SITE / "assets" / "_frames"
CANVAS = 148

# Filename → UI category. Order of first match wins.
# Arena = classic / seasonal PvP ranks; RTA = World Arena (ssN_rta*).
# ui = non-profile circular rings (legacy device frames, battle hero_s rings).
_CAT_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("ui", re.compile(r"legacy_frame|hero_s_frame", re.I)),
    ("rta", re.compile(r"(?:^|_)rta|_ss\d+_rta|ss\d+_rta", re.I)),
    ("arena", re.compile(
        r"(?:^|_)pvp_|rookie_rank|rank_none|pvp_season|pvp_rookie", re.I)),
    ("tournament", re.compile(r"e7wc|e7masters|ecl\d+|clan_tournament|clan_war", re.I)),
    ("clan", re.compile(r"clan", re.I)),
    ("abyss", re.compile(r"abyss", re.I)),
    ("event", re.compile(
        r"login|days|anniversary|\d+th|huawei|donation|guide_clear|automt|"
        r"seasonpass|season_pass", re.I)),
]


def categorize(stem: str) -> str:
    s = stem
    if s.startswith("icon_border_"):
        s = s[len("icon_border_"):]
    for cat, rx in _CAT_RULES:
        if rx.search(s) or rx.search(stem):
            return cat
    return "other"


def pretty_label(stem: str) -> str:
    """Human-ish label from filename: icon_border_pvp_season27_rank_1 → PvP season 27 rank 1."""
    s = stem
    if s.startswith("icon_border_"):
        s = s[len("icon_border_"):]
    s = s.replace("_", " ")
    s = re.sub(r"\bpvp\b", "PvP", s, flags=re.I)
    s = re.sub(r"\brta\b", "RTA", s, flags=re.I)
    s = re.sub(r"\be7wc\b", "E7WC", s, flags=re.I)
    s = re.sub(r"\be7masters\b", "E7 Masters", s, flags=re.I)
    s = re.sub(r"\bhero s frame\b", "Hero S frame", s, flags=re.I)
    s = re.sub(r"\blegacy frame\b", "Legacy frame", s, flags=re.I)
    return s.strip() or stem


# In-game profile face box is 112×112 inside a 148 border; icon_border_base's
# inner hole starts ~r=51 from center. Extra UI rings must match that hole so
# the face doesn't clip the ring or float with a gap.
TARGET_HOLE_R = 51
_HOLE_ALPHA = 30


def _inner_hole_radius(im: "Image.Image") -> int | None:
    """First opaque pixel along +x from center — the clear face aperture."""
    im = im.convert("RGBA")
    w, h = im.size
    cx, cy = w // 2, h // 2
    px = im.load()
    for r in range(0, min(cx, cy)):
        if px[cx + r, cy][3] > _HOLE_ALPHA:
            return r
    return None


def normalize_to_canvas(src: Path, dst: Path, canvas: int = CANVAS) -> None:
    """Stage a non-profile ring onto canvas×canvas, matching the profile hole.

    Official item/border assets are already 148×148 (bit-exact copy). Extra UI
    rings (hero_s / legacy) ship at 88–160 with different hole sizes — fit-to-
    outer stretched them wrong (face clipped or gapped). Scale so the inner
    hole ≈ TARGET_HOLE_R, center on the canvas, clip ornaments that stick out.
    """
    if Image is None:
        shutil.copy2(src, dst)
        return
    im = Image.open(src).convert("RGBA")
    w, h = im.size
    if w == canvas and h == canvas:
        if src.resolve() != dst.resolve():
            shutil.copy2(src, dst)
        return

    hole = _inner_hole_radius(im)
    if hole and hole > 0:
        scale = TARGET_HOLE_R / hole
    else:
        # Fallback: fit outer bounds (no clear hole detected).
        scale = min(canvas / w, canvas / h)

    nw = max(1, int(round(w * scale)))
    nh = max(1, int(round(h * scale)))
    resized = im.resize((nw, nh), Image.Resampling.LANCZOS)
    out = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    # Center; if larger than canvas, paste negative origin so mid stays mid
    # (PIL clips automatically).
    out.paste(resized, ((canvas - nw) // 2, (canvas - nh) // 2), resized)
    out.save(dst, "PNG")


def collect_sources(border_src: Path) -> list[tuple[Path, str]]:
    """Return (src_path, catalog_id) pairs. Profile borders first, then extras."""
    out: list[tuple[Path, str]] = []
    seen: set[str] = set()

    def add(p: Path, catalog_id: str) -> None:
        if not p.is_file() or p.suffix.lower() != ".png":
            return
        if catalog_id in seen:
            return
        seen.add(catalog_id)
        out.append((p, catalog_id))

    if border_src.is_dir():
        for p in sorted(border_src.glob("*.png"), key=lambda x: x.name.lower()):
            add(p, p.stem)

    # Battle-UI hero rings (ally / enemy / guide / …) — community request.
    img_dir = IMG_DIR / "img"
    if img_dir.is_dir():
        for p in sorted(img_dir.glob("*hero_s_frame*.png"), key=lambda x: x.name.lower()):
            # Normalize id: _hero_s_frame_guide → hero_s_frame_guide
            add(p, p.stem.lstrip("_"))

    # Older device / legacy circular frames.
    legacy_dir = IMG_DIR / "legacy"
    if legacy_dir.is_dir():
        for p in sorted(legacy_dir.glob("legacy_frame_*.png"), key=lambda x: x.name.lower()):
            add(p, p.stem)

    return out


def stage_one(src: Path, catalog_id: str) -> tuple[Path, bool] | None:
    """Write ASSET_OUT/<id>.png. Returns (dest, wrote) or None on failure."""
    dst = ASSET_OUT / f"{catalog_id}.png"
    try:
        # Official borders that are already 148×148: bit-exact copy.
        # Everything else is hole-aligned onto the profile canvas.
        exact = False
        if Image is not None:
            with Image.open(src) as im:
                exact = im.size == (CANVAS, CANVAS) and src.parent.name == "border"
        else:
            exact = src.parent.name == "border"

        need = (
            not dst.exists()
            or dst.stat().st_mtime < src.stat().st_mtime
            or dst.stat().st_size == 0
        )
        if need:
            if exact:
                shutil.copy2(src, dst)
            else:
                normalize_to_canvas(src, dst)
        return dst, need
    except OSError as e:
        print(f"  skip {src.name}: {e}")
        return None


def build(src: Path) -> dict:
    pairs = collect_sources(src)
    if not pairs:
        raise SystemExit(f"no frame PNGs found (border src={src})")

    ASSET_OUT.mkdir(parents=True, exist_ok=True)
    frames: list[dict] = []
    wrote = 0
    for p, fid in pairs:
        staged = stage_one(p, fid)
        if staged is None:
            continue
        dst, did_write = staged
        if did_write:
            wrote += 1
        frames.append({
            "id": fid,
            "file": dst.name,
            "path": f"assets/_frames/{dst.name}",
            "label": pretty_label(fid),
            "category": categorize(fid),
        })

    DATA_OUT.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 3,
        "note": "Profile frames for the unit detail compositor (face_s + border). "
                "Includes official item/border plus UI/legacy circular rings.",
        "canvas": CANVAS,
        "face_box": 112,        # in-game profile face (_s) is typically 112×112
        "count": len(frames),
        "frames": frames,
    }
    DATA_OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n",
                        encoding="utf-8")
    cats: dict[str, int] = {}
    for f in frames:
        cats[f["category"]] = cats.get(f["category"], 0) + 1
    print(f"[frames] {len(frames)} borders → {DATA_OUT.relative_to(REPO)}")
    print(f"[frames] wrote/updated {wrote} under {ASSET_OUT.relative_to(REPO)}")
    print(f"[frames] categories: {', '.join(f'{k}={v}' for k, v in sorted(cats.items()))}")
    return payload


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--src", type=Path, default=None,
                    help="border PNG folder (default: <img_dir>/item/border)")
    args = ap.parse_args()
    src = args.src or (IMG_DIR / "item" / "border")
    build(src)


if __name__ == "__main__":
    main()
