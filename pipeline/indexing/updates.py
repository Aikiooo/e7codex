"""Step 4: the Updates gallery — banner/story art per event codename.

Which art belongs to which codename is decided by a TOKEN in the filename
(`vsu5aa_...`), not by folder, so the scan is heuristic: it walks banner/ and
story/bg/, keeps the codenames `load_event_labels()` knows about, skips the
low-res/alt-mood variants, and never stages art that tokens an unreleased slug.
`UPDATE_EXTRA_STORY` covers the event stills whose filename carries no token.
"""
from __future__ import annotations

import re
import shutil
from collections import defaultdict
from pathlib import Path

from .fsutil import walk
from .tables import CODE_RE, IMG_EXT, UPDATE_EXTRA_STORY


def stage_update_art(img: Path, site_assets: Path, guard, event_labels: dict,
                     ) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """Copy the per-codename banner/story art into site/assets/_updates/<code>/.

    Returns (banners_per_code, story_per_code) — codename -> staged rel paths."""
    # Step 4: update gallery — copy banner art + story images per KNOWN_UPDATE codename.
    updates_dir = site_assets / "_updates"
    updates_dir.mkdir(exist_ok=True)
    banners_per_code: dict[str, list[str]] = defaultdict(list)
    story_per_code:  dict[str, list[str]] = defaultdict(list)
    # panic_stage = Panic minigame roster portraits (already shown as Stage cast);
    # keep them out of the event story / art gallery.
    STORY_SKIP = re.compile(
        r"_th\.|_blur\.|(?:^|_)silhouette|panic_stage", re.I
    )

    for p in walk(img / "banner"):
        if p.suffix.lower() not in IMG_EXT: continue
        codes = {c.lower() for c in CODE_RE.findall(p.name.lower())} & event_labels.keys()
        if guard.refs(p.name):
            # Unreleased-unit promo art (gacha/update banner, e.g.
            # vsu6aa_..._c5190_play) reaches _updates by CODENAME, not a staged
            # unit dir — the unit-dir hold-back misses it. Never stage/reference
            # it, and purge any copy a prior build left. (Same guard as wallpapers.)
            for c in codes:
                stale = updates_dir / c / p.name
                if stale.exists():
                    try: stale.unlink()
                    except OSError: pass
            continue
        for c in codes:
            dst = updates_dir / c / p.name
            dst.parent.mkdir(exist_ok=True)
            if not dst.exists():
                try: shutil.copy2(p, dst)
                except OSError: continue
            banners_per_code[c].append(f"assets/_updates/{c}/{p.name}")

    story_bg = img / "story" / "bg"
    if story_bg.exists():
        for p in sorted(story_bg.iterdir()):
            if p.suffix.lower() not in IMG_EXT: continue
            if STORY_SKIP.search(p.name): continue
            codes = {c.lower() for c in CODE_RE.findall(p.name.lower())} & event_labels.keys()
            if guard.refs(p.name):
                for c in codes:
                    stale = updates_dir / c / p.name
                    if stale.exists():
                        try: stale.unlink()
                        except OSError: pass
                continue
            for c in codes:
                dst = updates_dir / c / p.name
                dst.parent.mkdir(exist_ok=True)
                if not dst.exists():
                    try: shutil.copy2(p, dst)
                    except OSError: continue
                story_per_code[c].append(f"assets/_updates/{c}/{p.name}")

    for code, rels in UPDATE_EXTRA_STORY.items():
        if code not in event_labels:
            continue
        for rel in rels:
            src = img / rel.replace("\\", "/")
            if not src.is_file() or src.suffix.lower() not in IMG_EXT:
                continue
            if guard.refs(src.name):
                continue
            dst = updates_dir / code / src.name
            dst.parent.mkdir(exist_ok=True)
            if not dst.exists():
                try:
                    shutil.copy2(src, dst)
                except OSError:
                    continue
            rec = f"assets/_updates/{code}/{src.name}"
            if rec not in story_per_code[code]:
                story_per_code[code].append(rec)

    return banners_per_code, story_per_code


def build_updates(banners_per_code: dict, story_per_code: dict,
                  event_labels: dict) -> dict:
    """Codename-keyed Updates JSON: label -> {codename, banners, story?, year?}."""
    updates_out = {}
    # Only iterate over codenames that picked up any art — keeps the JSON tight
    # even though event_labels now has 100+ entries (most have no on-disk assets).
    for c in sorted(set(banners_per_code) | set(story_per_code)):
        banners = sorted(set(banners_per_code[c]))
        story   = sorted(set(story_per_code[c]))
        if not banners and not story:
            continue
        entry: dict = {"codename": c, "banners": banners}
        if story:
            entry["story"] = story
        # Year-digit at position 3 for 6-char codenames (vsu5aa -> 5 -> 2025).
        # 5-char shapes (vyunaa, vresaa, vrimaa, vreaaa, vasiaa) don't encode
        # a year — frontend falls back to alphabetical for those.
        if len(c) == 6 and c[3].isdigit():
            entry["year"] = 2020 + int(c[3])
        label = event_labels.get(c, c)   # codename itself is the last-resort heading
        updates_out[label] = entry
    return updates_out
