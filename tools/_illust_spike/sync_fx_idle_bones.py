"""Copy idle bone timelines from a driver char layer into FX layers with empty animation.

Some multi-layer illust stacks (e.g. Salome epma_04) put outfit FX (twinkles/stars)
on a separate eff skeleton parented to body bones, but author only those bones on
the character layers' short `animation` clip. The FX layer's `animation` is empty,
so ambient idle leaves stars frozen at setup while the body bobs → desync.

story_* clips often key both skeletons and look fine, but they are VO/dialogue
timelines (blood, long holds) — wrong for a looping wallpaper.

This script injects missing bone keyframes from the driver stem into each target
stem for a named animation (default `animation`). Idempotent: skips bones that
already have keys. Backs up each target once to <stem>.json.bak_pre_inject.

Usage:
  python sync_fx_idle_bones.py epma_04 illeff_epma_04_a_f eff_epma_04
  python sync_fx_idle_bones.py epma_04 illeff_epma_04_a_f eff_epma_04 --anim animation
"""
from __future__ import annotations

import argparse
import json
import sys
from copy import deepcopy
from pathlib import Path

SPIKE = Path(__file__).resolve().parent


def anim_tmax(anim: dict) -> float:
    m = 0.0

    def walk(o: object) -> None:
        nonlocal m
        if isinstance(o, dict):
            if "time" in o:
                try:
                    m = max(m, float(o["time"]))
                except (TypeError, ValueError):
                    pass
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for x in o:
                walk(x)

    walk(anim)
    return m


def inject(driver: dict, target: dict, anim_name: str) -> tuple[int, int, float]:
    src = (driver.get("animations") or {}).get(anim_name) or {}
    src_bones = src.get("bones") or {}
    if not src_bones:
        return 0, 0, 0.0
    anims = target.setdefault("animations", {})
    dst = anims.setdefault(anim_name, {})
    dst_bones = dst.setdefault("bones", {})
    tgt_names = {b["name"] for b in (target.get("bones") or []) if b.get("name")}
    copied = skipped = 0
    for bn, ch in src_bones.items():
        if bn not in tgt_names:
            skipped += 1
            continue
        if bn in dst_bones and dst_bones[bn]:
            skipped += 1
            continue
        dst_bones[bn] = deepcopy(ch)
        copied += 1
    return copied, skipped, anim_tmax(dst)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("stage_dir", help="pack stage folder under tools/_illust_spike/")
    ap.add_argument("driver", help="stem with full idle bone keys (char layer)")
    ap.add_argument("targets", nargs="+", help="FX stems with empty/thin idle")
    ap.add_argument("--anim", default="animation", help="animation name (default animation)")
    args = ap.parse_args()

    d = SPIKE / args.stage_dir
    if not d.is_dir():
        print(f"missing stage dir {d}", file=sys.stderr)
        return 1
    dp = d / f"{args.driver}.json"
    if not dp.is_file():
        print(f"missing driver {dp}", file=sys.stderr)
        return 1
    driver = json.loads(dp.read_text(encoding="utf-8"))
    if args.anim not in (driver.get("animations") or {}):
        print(f"driver has no anim {args.anim}", file=sys.stderr)
        return 1

    for stem in args.targets:
        tp = d / f"{stem}.json"
        if not tp.is_file():
            print(f"skip missing {tp}")
            continue
        bak = d / f"{stem}.json.bak_pre_inject"
        if not bak.is_file():
            bak.write_bytes(tp.read_bytes())
            print(f"backup {bak.name}")
        target = json.loads(tp.read_text(encoding="utf-8"))
        copied, skipped, dur = inject(driver, target, args.anim)
        tp.write_text(
            json.dumps(target, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        print(f"{stem}: injected {copied} bones (skipped {skipped}) anim={args.anim} ~{dur:.3f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
