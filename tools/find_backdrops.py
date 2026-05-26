#!/usr/bin/env python3
"""
Scan staged (X, X_1) pairs not already in PRIMARY_SWAP and report
likely backdrop/character splits for manual review.

Heuristic: if >= THRESHOLD fraction of the bare slug's Spine slot names
match known background/scene patterns, the pair is flagged as a candidate.
Supporting signals: pose_trim.json being null (transparent render) and
the _1 sibling having character expression slots.

Usage:
    python tools/find_backdrops.py [--threshold 0.6]

After verifying visually (open both slugs in viewer.html), add confirmed
entries to PRIMARY_SWAP in build_index.py:
    "c<id>": {"label": "backdrop"},
"""
from __future__ import annotations
import argparse, json, re, sys
from pathlib import Path

THIS = Path(__file__).resolve()
REPO = THIS.parents[1]
SITE = REPO / "site" / "assets"

sys.path.insert(0, str(REPO))
import build_index  # type: ignore  # gives us PRIMARY_SWAP, EXTRA_SUFFIX

# Backdrop slot-name patterns: covers all confirmed conventions across the 8
# known PRIMARY_SWAP entries plus the eff_back_* pattern seen in c2112_s01.
#   ^bg       → bg1, bg_*, bgmang*, bg_d_*      (c1180, c2076, c2181, c2185)
#   ^back     → back_01, back_02                 (c1183)
#   ^cloud    → scene clouds
#   ^d_       → d_bg_*, d_1, d_2, …             (c2076, c2184)
#   ^b_       → b_1, b_10, … (scene layer bones)(c6024)
#   ^fx[/_]   → fx/flare*, fx_f_*               (c1180, c2181)
#   ^eff_back → eff_back_*                       (c2112_s01)
#   ^sky      → sky layers
#   ^stage    → stage objects
#   ^\d+_chick → 1_chick_*, 2_chick_* props     (c1183)
BACKDROP_RE = re.compile(
    r"^(bg|back|cloud|d_|b_|fx[/_]|eff_back|sky|stage|\d+_chick)",
    re.I,
)

# Expression/body slots that strongly indicate a character rig.
CHAR_RE = re.compile(
    r"^(normal|angry|panic|smile|special|sad|main_head|main_body|hair|face|eye|mouth)",
    re.I,
)


def slot_names(slug: str) -> list[str]:
    p = SITE / slug / f"{slug}.json"
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return [s["name"] for s in data.get("slots", [])]
    except Exception:
        return []


def pose_trim_is_null(slug: str) -> bool:
    p = SITE / slug / "pose_trim.json"
    if not p.exists():
        return False
    return p.read_text(encoding="utf-8").strip() == "null"


def backdrop_score(slots: list[str]) -> tuple[float, int, int]:
    """Return (ratio, backdrop_count, char_count)."""
    if not slots:
        return 0.0, 0, 0
    bd = sum(1 for s in slots if BACKDROP_RE.match(s))
    ch = sum(1 for s in slots if CHAR_RE.match(s))
    return bd / len(slots), bd, ch


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--threshold", type=float, default=0.6,
                    help="min backdrop-slot fraction to flag as candidate (default: 0.60)")
    args = ap.parse_args(argv)

    known_swap: set[str] = set(build_index.PRIMARY_SWAP.keys())
    extra_suffix: str = build_index.EXTRA_SUFFIX  # "_1"

    staged = {
        d.name for d in SITE.iterdir()
        if d.is_dir() and d.name != "_updates" and (d / f"{d.name}.json").exists()
    }

    # Find (bare, bare+_1) pairs where bare is not already in PRIMARY_SWAP.
    pairs: list[tuple[str, str]] = []
    for slug in sorted(staged):
        if not slug.endswith(extra_suffix):
            continue
        bare = slug[: -len(extra_suffix)]
        if bare not in staged:
            continue
        if bare in known_swap:
            continue
        pairs.append((bare, slug))

    if not pairs:
        print("No unhandled (X, X_1) pairs found — PRIMARY_SWAP may be complete.")
        return

    print(f"Checking {len(pairs)} unhandled (X, X_1) pair(s)...\n")

    results = []
    for bare, x1 in pairs:
        bare_slots = slot_names(bare)
        x1_slots   = slot_names(x1)
        ratio, bd, ch = backdrop_score(bare_slots)
        _, _, x1_char = backdrop_score(x1_slots)
        results.append({
            "bare": bare, "x1": x1,
            "ratio": ratio, "bd": bd, "ch": ch,
            "total": len(bare_slots),
            "x1_char": x1_char,
            "trim_null": pose_trim_is_null(bare),
        })

    above = [r for r in results if r["ratio"] >= args.threshold]
    below = [r for r in results if r["ratio"] < args.threshold]

    if above:
        print(f"=== CANDIDATES  (backdrop ratio >= {args.threshold:.0%}) ===")
        for r in above:
            print(f"\n  {r['bare']}  +  {r['x1']}")
            pct = f"{r['bd']}/{r['total']} ({r['ratio']:.0%})"
            print(f"    backdrop slots : {pct}")
            if r["ch"]:
                print(f"    char slots in bare  : {r['ch']}  (unusual, verify)")
            if r["x1_char"]:
                print(f"    char slots in _1    : {r['x1_char']}  (supports swap)")
            if r["trim_null"]:
                print(f"    pose_trim is null   (bare slug rendered transparent)")
            print(f"    >> add to PRIMARY_SWAP in build_index.py:")
            print(f'        "{r["bare"]}": {{"label": "backdrop"}},')
    else:
        print(f"No candidates above {args.threshold:.0%} threshold.")

    if below:
        print(f"\n=== LOW CONFIDENCE  (backdrop ratio < {args.threshold:.0%}) ===")
        for r in below:
            pct = f"{r['bd']}/{r['total']} ({r['ratio']:.0%})"
            print(f"  {r['bare']} + {r['x1']}: {pct} backdrop slots")
        print("  Review these manually in viewer.html before deciding.")


if __name__ == "__main__":
    main()
