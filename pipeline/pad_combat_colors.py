"""Pad short RRGGBBAA hex colors on already-staged combat rig JSONs.

Does NOT re-run the converter (UV/deform post-process is not idempotent).
Only walks color/light/dark string fields.

  python pipeline/pad_combat_colors.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from e7lib.bootstrap import add_source_dirs  # noqa: E402
add_source_dirs(ROOT)
from scsp_to_json import _e7_pad_colors  # noqa: E402  (convert/)

ASSETS = ROOT / "site" / "assets"


def main() -> None:
    nfiles = 0
    nfields = 0
    for p in sorted(ASSETS.glob("*/combat/*.json")):
        if p.parent.name != "combat":
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            print("SKIP", p, e)
            continue
        n = _e7_pad_colors(data)
        if not n:
            continue
        p.write_text(
            json.dumps(data, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        nfiles += 1
        nfields += n
        print(f"{p.relative_to(ASSETS)}  {n}")
    print(f"padded {nfields} fields in {nfiles} files")


if __name__ == "__main__":
    main()
