"""The unreleased-unit guard (DMCA): held slugs, their art tokens, the deep scan.

The game marks unannounced units with the name "Unknown Hero"; announced-but-not-
released ones must be hand-listed in `pipeline/names.py:MANUAL_UNRELEASED`. Both
feed `data_external/unreleased_units.json`, which this module reads.

Held units are MATERIALIZED the same as released ones (full face/skill/
swap_alias/name path) so local / tunnel preview pages are complete. They are only
SPLIT OUT at write time into units_unreleased.json — never units.json, never SEO
stubs, never deploy (ops/deploy.ps1 holds assets + the unreleased JSON aside).
Token guards on wallpapers/emotes/updates withhold public cross-refs to held slugs.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .slugs import split_variant


class Guard:
    """Held unit slugs + the filename-token form of the same set.

    One instance per build, created by `load_guard()`. It replaces the
    `unreleased` / `_unrel_tokens` / `refs_unreleased()` / `_is_unreleased()`
    closures that used to live inside `build()`: identical lifetime, but passed
    explicitly instead of being captured, and no module-level mutable state.
    """

    def __init__(self, slugs: set[str]) -> None:
        self.slugs = slugs
        # Token form for art whose FILENAME references an unreleased unit but doesn't
        # resolve to a staged slug — e.g. wallpaper `img_intimacy_illust_c5069` or
        # banner `gacha_c5069_01_bg`. The unit-dir guard never sees these, so
        # the wallpaper/emote builders filter on this. Split on non-alphanumeric
        # because '_c5069_' has no word boundary for a `\b`-anchored regex.
        self.tokens = ({u.lower() for u in slugs}
                       | {u.split("_")[0].lower() for u in slugs})

    def refs(self, name: str) -> bool:
        """Does this filename/stem reference a held slug by token?"""
        return bool(set(re.split(r"[^a-z0-9]+", name.lower())) & self.tokens)

    def is_held(self, name: str) -> bool:
        """Is this staged slug (or its base slug) held back?"""
        return name in self.slugs or split_variant(name)[0] in self.slugs


def load_guard(root: Path) -> Guard:
    """Read the held set (built by `pipeline/names.py`). Missing file = empty."""
    p = root / "data_external" / "unreleased_units.json"
    slugs: set[str] = set()
    if p.exists():
        slugs = set(json.loads(p.read_text("utf-8")).get("slugs", []))
    return Guard(slugs)


def split_held(units: dict, guard: Guard) -> tuple[dict, list[dict]]:
    """Split held units out of the public catalog: (public_units, held list).

    Same full materialization as released; only the write targets differ. Strip
    cecilia — CB pages usually don't exist yet and we don't want a public
    deep-link temptation if the JSON ever escaped the local gate."""
    unrel_list: list[dict] = []
    public_units: dict[str, dict] = {}
    for slug, unit in units.items():
        if guard.is_held(slug):
            held = dict(unit)
            held["unreleased"] = True
            held.pop("cecilia", None)
            unrel_list.append(held)
        else:
            public_units[slug] = unit
    return public_units, unrel_list


def assert_no_held_units(units: dict, guard: Guard) -> None:
    """Defense-in-depth: units.json must never carry an unreleased slug (the other
    guard is sync_pack Stage 8). Cheap, and it turns any future refactor slip
    into a hard build failure instead of a silent public leak."""
    leaked = [s for s in units if guard.is_held(s)]
    if leaked:
        raise SystemExit(f"FATAL: unreleased slug(s) reached units.json: {leaked}")


def assert_no_held_tokens(units_text: str, guard: Guard) -> None:
    """Deep belt: assert_no_held_units only sees TOP-LEVEL slugs — a held slug
    nested as an extras[] entry under a released primary would pass it.
    Token-scan the serialized text instead (consecutive-sequence match, so a held
    `_1` variant never false-flags its released base)."""
    held_seqs = [tuple(p for p in re.split(r"[^a-z0-9]+", u.lower()) if p)
                 for u in guard.slugs]
    toks = [t for t in re.split(r"[^a-z0-9]+", units_text.lower()) if t]
    deep = sorted({"_".join(seq) for seq in held_seqs
                   for i, t in enumerate(toks) if t == seq[0]
                   and tuple(toks[i:i + len(seq)]) == seq})
    if deep:
        raise SystemExit(f"FATAL: held slug token(s) inside units.json "
                         f"(nested extras[]?): {deep}")
