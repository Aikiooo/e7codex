#!/usr/bin/env python3
"""
Audit staged (X, X_1) pairs under the auto backdrop-swap rule.

Second-rig releases are treated as a backdrop/character split by default:
indexing.tables.effective_swap_map() flips every staged (X, X_1) pair so the
bare slug is the scene (backdrop) and X_1 is the character. This tool lists
every pair and flags the ones worth a second look:

  - bare rigs with CHARACTER-like slots (normal_*/angry_*/hair_*/face_* …)
    — those are likely char+char pairs, NOT scene+char, and should be added
    to PRIMARY_SWAP_EXCEPT in pipeline/indexing/tables.py;
  - bare rigs with no obvious backdrop slots at all (0% match) — usually
    still a scene with exotic slot names (c5190 reef, c2113_s01), but check.

Usage:
    python pipeline/find_backdrops.py
"""
from __future__ import annotations
import json, re, sys
from pathlib import Path

THIS = Path(__file__).resolve()
REPO = THIS.parents[1]
SITE = REPO / "site" / "assets"

sys.path.insert(0, str(THIS.parent))
sys.path.insert(0, str(REPO))
from e7lib.bootstrap import add_source_dirs  # noqa: E402
add_source_dirs(REPO)
from indexing.tables import EXTRA_SUFFIX, PRIMARY_SWAP_EXCEPT  # noqa: E402

# Backdrop slot-name patterns: covers all confirmed conventions across the
# known backdrop-swap entries plus the eff_back_* pattern seen in c2112_s01.
#   ^bg       → bg1, bg_*, bgmang*, bg_d_*      (c1180, c2076, c2181, c2185)
#   ^back     → back_01, back_02                 (c1183)
#   ^cloud    → scene clouds                     (from TASKS.md)
#   ^d_       → d_bg_*, d_1, d_2, …             (c2076, c2184)
#   ^b_       → b_1, b_10, … (scene layer bones)(c6024)
#   ^fx[/_]   → fx/flare*, fx_f_*               (c1180, c2181)
#   ^eff_back → eff_back_*                       (c2112_s01)
#   ^sky      → sky layers                       (from TASKS.md)
#   ^stage    → stage objects                    (from TASKS.md)
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


def backdrop_score(slots: list[str]) -> tuple[float, int, int]:
    """Return (ratio, backdrop_count, char_count)."""
    if not slots:
        return 0.0, 0, 0
    bd = sum(1 for s in slots if BACKDROP_RE.match(s))
    ch = sum(1 for s in slots if CHAR_RE.match(s))
    return bd / len(slots), bd, ch


def main() -> None:
    staged = {
        d.name for d in SITE.iterdir()
        if d.is_dir() and d.name != "_updates" and (d / f"{d.name}.json").exists()
    }
    extra_suffix = EXTRA_SUFFIX  # "_1"

    pairs: list[tuple[str, str]] = []
    for slug in sorted(staged):
        if not slug.endswith(extra_suffix):
            continue
        bare = slug[: -len(extra_suffix)]
        if bare not in staged:
            continue
        pairs.append((bare, slug))

    if not pairs:
        print("No (X, X_1) pairs staged.")
        return

    print(f"{len(pairs)} second-rig pair(s) staged — all auto-swapped "
          f"(bare = backdrop, X_1 = character) per effective_swap_map().\n")

    flagged = 0
    for bare, x1 in pairs:
        exempt = bare in PRIMARY_SWAP_EXCEPT
        ratio, bd, ch = backdrop_score(slot_names(bare))
        _, _, x1_char = backdrop_score(slot_names(x1))
        line = f"  {bare:14s} + {x1}"
        if exempt:
            print(f"{line}  [EXEMPT from swap — manual override]")
            continue
        flags = []
        if ch:
            flags.append(f"{ch} char-like slots in bare (possible char+char pair)")
        if bd == 0:
            flags.append("0% backdrop-slot match (scene with exotic names?)")
        if x1_char == 0:
            flags.append("no char slots in _1 (verify it's a character)")
        if flags:
            flagged += 1
            print(f"{line}  FLAG: " + " | ".join(flags))
        else:
            print(f"{line}  ok ({bd} backdrop slots, {x1_char} char slots in _1)")

    if flagged:
        print(f"\n{flagged} pair(s) flagged — review in viewer.html. If a bare rig "
              f"is actually a character (not a scene), add it to "
              f"PRIMARY_SWAP_EXCEPT in pipeline/indexing/tables.py.")
    else:
        print("\nNo anomalies — auto-swap looks right across the board.")


if __name__ == "__main__":
    main()
