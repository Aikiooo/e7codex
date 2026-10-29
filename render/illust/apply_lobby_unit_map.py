"""Merge unit slugs from LOBBY_ANIM_UNIT_MAP.md JSON block or a sidecar JSON
into site/data/lobby_anims.json.

  # Edit LOBBY_ANIM_UNIT_MAP.md quick-paste JSON, then:
  python apply_lobby_unit_map.py

  # Or pass a JSON file:
  python apply_lobby_unit_map.py --map my_map.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SPIKE = Path(__file__).resolve().parent
CATALOG = SPIKE.parents[1] / "site" / "data" / "lobby_anims.json"
MAP_MD = SPIKE / "LOBBY_ANIM_UNIT_MAP.md"


def extract_json_from_md(text: str) -> dict:
    """Prefer the first fenced ```json block that looks like a pack→units map."""
    blocks = re.findall(r"```json\s*(\{.*?\})\s*```", text, flags=re.S)
    for b in blocks:
        try:
            data = json.loads(b)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and data and all(isinstance(v, list) for v in data.values()):
            # Skip the "already linked" block if both exist: merge all valid maps.
            return data
    # Merge ALL valid maps in the file
    merged: dict = {}
    for b in blocks:
        try:
            data = json.loads(b)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and all(isinstance(v, list) for v in data.values()):
            merged.update(data)
    return merged


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--map", type=Path, help="JSON object { pack_id: [slugs] }")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if args.map:
        mapping = json.loads(args.map.read_text(encoding="utf-8"))
    else:
        if not MAP_MD.is_file():
            print(f"missing {MAP_MD}", file=sys.stderr)
            return 1
        mapping = extract_json_from_md(MAP_MD.read_text(encoding="utf-8"))
        # Merge every json block (done + todo)
        blocks = re.findall(r"```json\s*(\{.*?\})\s*```", MAP_MD.read_text(encoding="utf-8"), flags=re.S)
        mapping = {}
        for b in blocks:
            try:
                data = json.loads(b)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict) and all(isinstance(v, list) for v in data.values()):
                mapping.update(data)

    if not mapping:
        print("no pack→units map found", file=sys.stderr)
        return 1

    cat = json.loads(CATALOG.read_text(encoding="utf-8"))
    by_id = {e["id"]: e for e in cat}
    n = 0
    for pid, units in mapping.items():
        if pid not in by_id:
            print(f"  skip unknown pack: {pid}")
            continue
        units = [str(u).strip() for u in units if str(u).strip()]
        old = by_id[pid].get("units") or []
        if old == units:
            continue
        print(f"  {pid}: {old} → {units}")
        by_id[pid]["units"] = units
        n += 1

    if args.dry_run:
        print(f"dry-run: would update {n} entries")
        return 0
    CATALOG.write_text(json.dumps(cat, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"updated {n} entries → {CATALOG}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
