"""Sequential full bake of all non-deferred catalog packs. Logs to batch_bake.log.

  python run_batch_bake.py              # stage+akey+bake active set
  python run_batch_bake.py --skip-stage # bake only (assets already staged)
  python run_batch_bake.py c1153 c6005  # subset
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
import time
from pathlib import Path

SPIKE = Path(__file__).resolve().parent
LOG = SPIKE / "batch_bake.log"
RECIPES = SPIKE / "recipes.json"


def log(msg: str) -> None:
    line = f"[{dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("packs", nargs="*", help="pack ids (default: all non-deferred)")
    ap.add_argument("--skip-stage", action="store_true")
    args = ap.parse_args()

    data = json.loads(RECIPES.read_text(encoding="utf-8"))
    if args.packs:
        want = set(args.packs)
        packs = [p for p in data["packs"] if p["id"] in want]
    else:
        packs = [p for p in data["packs"] if not p.get("deferred")]

    log(f"=== batch start: {len(packs)} packs ===")
    log("ids: " + ", ".join(p["id"] for p in packs))
    results: list[tuple[str, int, float]] = []

    for i, p in enumerate(packs, 1):
        pid = p["id"]
        log(f"--- [{i}/{len(packs)}] {pid} ({p.get('kind')}) ---")
        t0 = time.time()
        cmd = [
            sys.executable,
            str(SPIKE / "pipeline_illust.py"),
            "bake" if args.skip_stage else "full",
            pid,
        ]
        log("$ " + " ".join(cmd))
        r = subprocess.run(cmd, cwd=str(SPIKE))
        elapsed = time.time() - t0
        results.append((pid, r.returncode, elapsed))
        log(f"--- [{i}/{len(packs)}] {pid} exit={r.returncode} in {elapsed/60:.1f} min ---")
        if r.returncode != 0:
            log(f"WARN: {pid} failed; continuing")

    log("=== batch summary ===")
    ok = sum(1 for _, c, _ in results if c == 0)
    for pid, code, el in results:
        log(f"  {'OK' if code==0 else 'FAIL':<4} {pid:<22} {el/60:6.1f} min  exit={code}")
    log(f"done: {ok}/{len(results)} ok")
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
