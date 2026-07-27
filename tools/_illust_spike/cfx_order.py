"""Resolve Spine layer z-order from Epic Seven .cfx plists (rank-2 data).

CFX files under extracted_data/output/effect/ list primitives with optional `z`
(string or int). Lower z draws first (back). Missing z → 0.

Usage:
  python cfx_order.py <cfx_stem> [<cfx_stem> ...]
  python cfx_order.py --json illeff_vsu6aa_01 illeff_vsu6aa_01_bg_b illeff_vsu6aa_01_bg_f

Merges all listed CFX roots, keeps spine primitives only, sorts by z ascending,
then by source name for stable ties. Dedupes by source (first wins).
"""
from __future__ import annotations

import argparse
import json
import plistlib
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
try:
    import paths

    EFFECT = Path(paths.RAW_DIR) / "effect"
except Exception:
    # Fallback when tools/paths.py is unavailable: sibling extracted_data layout.
    EFFECT = REPO.parent / "extracted_data" / "output" / "effect"


def _z_of(prim: dict) -> float:
    z = prim.get("z", 0)
    if z is None or z == "":
        return 0.0
    try:
        return float(z)
    except (TypeError, ValueError):
        return 0.0


def load_cfx_primitives(stem: str) -> list[dict]:
    """Load spine primitives from effect/<stem>.cfx (with or without .cfx suffix)."""
    name = stem if stem.endswith(".cfx") else f"{stem}.cfx"
    path = EFFECT / name
    if not path.is_file():
        return []
    try:
        data = plistlib.loads(path.read_bytes())
    except Exception as e:
        print(f"[warn] {path.name}: unparseable ({e})", file=sys.stderr)
        return []
    out = []
    for p in data.get("primitive") or []:
        if p.get("format") != "spine":
            continue
        src = (p.get("source") or "").strip()
        if not src:
            continue
        out.append(
            {
                "source": src,
                "z": _z_of(p),
                "scale": float(p["scale"]) if p.get("scale") not in (None, "") else 1.0,
                "cfx": path.stem,
            }
        )
    return out


def merge_order(
    cfx_stems: list[str],
    *,
    exclude: set[str] | None = None,
    only: set[str] | None = None,
) -> list[dict]:
    """Merge primitives from one or more CFX files → back-to-front order."""
    exclude = exclude or set()
    seen: set[str] = set()
    rows: list[dict] = []
    for stem in cfx_stems:
        for p in load_cfx_primitives(stem):
            src = p["source"]
            if src in seen or src in exclude:
                continue
            if only is not None and src not in only:
                continue
            seen.add(src)
            rows.append(p)
    rows.sort(key=lambda r: (r["z"], r["source"]))
    return rows


def order_csv(cfx_stems: list[str], **kw) -> str:
    return ",".join(r["source"] for r in merge_order(cfx_stems, **kw))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("cfx", nargs="+", help="CFX stem(s) to merge")
    ap.add_argument("--json", action="store_true", help="JSON rows instead of CSV")
    ap.add_argument(
        "--exclude",
        default="",
        help="comma-separated source stems to drop (e.g. washout layers)",
    )
    args = ap.parse_args()
    excl = {s.strip() for s in args.exclude.split(",") if s.strip()}
    rows = merge_order(args.cfx, exclude=excl)
    if not rows:
        print("no spine primitives found", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(rows, indent=2))
    else:
        for r in rows:
            sc = r.get("scale", 1.0)
            sc_s = f"  scale={sc:g}" if abs(float(sc) - 1.0) > 1e-6 else ""
            print(f"{r['z']:>7g}  {r['source']}{sc_s}")
        print("---")
        print(",".join(r["source"] for r in rows))
        scales = [
            f"{r['source']}:{float(r['scale']):g}"
            for r in rows
            if abs(float(r.get("scale", 1.0)) - 1.0) > 1e-6
        ]
        if scales:
            print("scales:", ",".join(scales))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
