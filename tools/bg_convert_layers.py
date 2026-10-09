"""Bulk-convert every bg/ .scsp layer to Spine 3.8 JSON for the background tools.

bg_stage.py and bg_field.py read converted layers from bg_stage.LAYER_CACHE and
skip any layer missing there, so run this first (and again after a pack adds
background layers).

Reads  RAW_DIR/bg/*.scsp            (tools/paths.py)
Writes LAYER_CACHE/<layer>.json     (one per layer, name preserved)
       LAYER_CACHE/_failures.json   (layers the converter rejected, e.g. 3.4.02)
Idempotent: skips layers whose .json already exists and is non-empty.
"""
from __future__ import annotations
import json, sys, time
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS.parent))
sys.path.insert(0, str(TOOLS))
from tools.scsp_to_json import convert  # noqa: E402
from tools.bg_stage import RAW_BG, LAYER_CACHE  # noqa: E402


def main() -> int:
    LAYER_CACHE.mkdir(parents=True, exist_ok=True)
    layers = sorted(p for p in RAW_BG.iterdir() if p.suffix == ".scsp")
    print(f"layers: {len(layers)}  ->  {LAYER_CACHE}", flush=True)
    ok = skip = fail = 0
    fails = []
    t0 = time.time()
    for i, p in enumerate(layers):
        dst = LAYER_CACHE / (p.stem + ".json")
        if dst.exists() and dst.stat().st_size > 0:
            skip += 1
            continue
        try:
            convert(p, dst)
            ok += 1
        except Exception as e:
            fail += 1
            fails.append((p.name, str(e)[:200]))
        if (i + 1) % 250 == 0:
            print(f"  {i+1}/{len(layers)} ok={ok} skip={skip} fail={fail} "
                  f"({time.time()-t0:.0f}s)", flush=True)
    (LAYER_CACHE / "_failures.json").write_text(json.dumps(fails, indent=1), encoding="utf-8")
    print(f"DONE ok={ok} skip={skip} fail={fail} in {time.time()-t0:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
