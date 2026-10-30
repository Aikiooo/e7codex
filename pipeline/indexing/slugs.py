"""Slug parsing: variant suffixes, kind prefixes, ceciliabot kebabs."""
from __future__ import annotations

import re

from .tables import EXTRA_SUFFIX, VARIANT_SUFFIXES


def split_variant(slug: str) -> tuple[str, str, bool]:
    """Return (base_id, suffix, is_extra).

    If the slug ends with `_1` we peel that first and mark `is_extra=True`;
    the bare slug then goes through the regular variant match. This lets
    `c1046_s02_1` resolve to (c1046, '_s02', True) — same variant key as
    `c1046_s02` but flagged so the caller can attach it as an extra rig
    rather than a separate unit/tab.
    """
    is_extra = False
    bare = slug
    if slug.endswith(EXTRA_SUFFIX) and len(slug) > len(EXTRA_SUFFIX):
        bare = slug[:-len(EXTRA_SUFFIX)]
        is_extra = True
    for suf in VARIANT_SUFFIXES:
        if bare.endswith(suf) and len(bare) > len(suf):
            return bare[:-len(suf)], suf, is_extra
    return bare, "", is_extra


def kind_of(slug: str) -> str:
    if slug.startswith("npc"):      return "npc"
    if slug.startswith("pet"):      return "pet"
    if slug.startswith("af"):       return "artifact"
    if re.match(r"^m\d", slug):     return "monster"
    if re.match(r"^d\d", slug):     return "monster"
    if re.match(r"^s\d", slug):     return "special"
    if re.match(r"^c\d", slug):     return "unit"
    return "other"


def kebab(s: str) -> str:
    """Make a name into a ceciliabot-style URL slug: 'Lionheart Cermia' ->
    'lionheart-cermia', "A Little Queen's Huge Crown" -> 'a-little-queens-huge-crown',
    'Air-to-Surface Missile: MISHA' -> 'airtosurface-missile-misha'. Matches
    ceciliabot's convention: punctuation (apostrophes, colons, intra-word hyphens)
    is DROPPED IN PLACE, not turned into a separator — only whitespace becomes a
    hyphen. Used to synthesise a slug when the community snapshot has none yet."""
    s = s.lower()
    s = re.sub(r"[^a-z0-9\s]", "", s)    # drop punctuation in place: queen's -> queens
    return re.sub(r"\s+", "-", s.strip())
