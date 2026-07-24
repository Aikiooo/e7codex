"""Build profile-frame catalog for the avatar + frame compositor (TASKS.md #32).

Indexes in-game profile borders (`img_output/item/border/*.png`, all 148×148)
and stages them for the site's per-unit "Frame" tool.

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

REPO = Path(__file__).resolve().parents[1]
SITE = REPO / "site"
DATA_OUT = SITE / "data" / "frames.json"
ASSET_OUT = SITE / "assets" / "_frames"

# Filename → UI category. Order of first match wins.
# Arena = classic / seasonal PvP ranks; RTA = World Arena (ssN_rta*).
_CAT_RULES: list[tuple[str, re.Pattern[str]]] = [
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
    return s.strip() or stem


def build(src: Path) -> dict:
    if not src.is_dir():
        raise SystemExit(f"border source not found: {src}")

    pngs = sorted(src.glob("*.png"), key=lambda p: p.name.lower())
    if not pngs:
        raise SystemExit(f"no .png borders in {src}")

    ASSET_OUT.mkdir(parents=True, exist_ok=True)
    frames: list[dict] = []
    copied = 0
    for p in pngs:
        stem = p.stem
        dst = ASSET_OUT / p.name
        try:
            if not dst.exists() or dst.stat().st_mtime < p.stat().st_mtime:
                shutil.copy2(p, dst)
                copied += 1
        except OSError as e:
            print(f"  skip {p.name}: {e}")
            continue
        frames.append({
            "id": stem,
            "file": p.name,
            "path": f"assets/_frames/{p.name}",
            "label": pretty_label(stem),
            "category": categorize(stem),
        })

    DATA_OUT.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 2,
        "note": "Profile frames for the unit detail compositor (face_s + border).",
        "canvas": 148,          # all borders are 148×148
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
    print(f"[frames] staged {copied} new/updated under {ASSET_OUT.relative_to(REPO)}")
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
