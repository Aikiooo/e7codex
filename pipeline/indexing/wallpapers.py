"""Step 6: the Wallpapers gallery — four scanned buckets + curated picks.

Buckets: `bgpack/` (lobby), `item/art/lp_*` (event splashes), `episode/`
(chapter art), `story/bg/` (filtered to drop the silhouette / `_th` / `_blur`
alt-moods and the solid black/white utility screens). `banner/` and `img/` are
deliberately NOT scanned — they are promo/UI chrome — so their wallpaper-worthy
full-bleeds are hand-picked in `tables.py` (BANNER_WALLPAPERS / IMG_WALLPAPERS /
SANCTUARY_WALLPAPERS, plus EXTRA_WALLPAPERS for the lobby-bake masters).

`add_wallpaper` also withholds anything that tokens an unreleased slug and
purges a copy a prior build may have staged.
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

from . import REPO_ROOT
from .tables import (BANNER_WALLPAPERS, EXTRA_WALLPAPERS, IMG_EXT,
                     IMG_WALLPAPERS, SANCTUARY_WALLPAPERS, WP_NAME)


def build_wallpapers(img: Path, site_assets: Path, guard) -> list[dict]:
    """Copy every wallpaper into site/assets/_wallpapers/<category>/ and return
    the wallpaper entries in scan order."""
    # Step 6: wallpaper gallery. Pulls four buckets and tags them by category:
    #   lobby   img_output/bgpack/*.{png,webp}           5 files  (~4 MB)
    #   event   img_output/item/art/lp_*.png             23 files (event splashes,
    #                                                              ML rerun, collab themes)
    #   episode img_output/episode/{_cm,cimg,img}_*.*    129 files (chapter art)
    #   story   img_output/story/bg/*.{png,webp}         filtered to skip the
    #                                                    _silhouette_ / _th /
    #                                                    blur variants that are
    #                                                    just low-res or alt-mood
    #                                                    versions of the same art
    # storytool_data is intentionally skipped: it's a folder of *prop* sheets
    # (clouds, tile cuts) the dev tooling assembles into scenes, not standalone
    # wallpapers.
    wp_dir = site_assets / "_wallpapers"
    wp_dir.mkdir(exist_ok=True)
    wallpapers: list[dict] = []
    seen_dst: set[str] = set()
    STORY_BG_SKIP = re.compile(r"(?:^|/|_)(?:silhouette|blur|_th)|_th\.|_blur\.", re.I)

    def humanise(stem: str, category: str) -> str:
        # Strip the dump-side prefixes that aren't part of the human name.
        s = stem
        if category == "event":
            s = re.sub(r"^lp_", "", s, flags=re.I)
            # banner/ picks are named <thing>_bg(_N) — drop the _bg marker
            s = re.sub(r"_bg(?:_\d+)?$", "", s, flags=re.I)
        elif category == "episode":
            s = re.sub(r"^(?:_cm_|cimg_|img_)", "", s, flags=re.I)
        elif category == "story":
            s = re.sub(r"^bg_", "", s, flags=re.I)
        # Insert space between digits and letters so 2023summer -> 2023 summer.
        s = re.sub(r"(\d)([A-Za-z])", r"\1 \2", s)
        s = re.sub(r"([A-Za-z])(\d)", r"\1 \2", s)
        return s.replace("_", " ").strip().title()

    def add_wallpaper(src: Path, category: str, sub: str | None = None) -> None:
        # Copy under _wallpapers/<category>/[<sub>/]<file>. Skip duplicates by
        # destination path so a rebuild is idempotent.
        rel = Path(category)
        if sub: rel = rel / sub
        dst = wp_dir / rel / src.name
        rel_str = f"assets/_wallpapers/{rel.as_posix()}/{src.name}"
        if guard.refs(src.stem):
            # Unreleased-unit art (e.g. img_intimacy_illust_c5069) — never publish,
            # and purge any copy a prior build staged before the guard existed.
            if dst.exists():
                try: dst.unlink()
                except OSError: pass
            return
        if rel_str in seen_dst:
            return
        seen_dst.add(rel_str)
        dst.parent.mkdir(parents=True, exist_ok=True)
        if not dst.exists():
            try: shutil.copy2(src, dst)
            except OSError: return
        wallpapers.append({
            "file":     rel_str,
            "name":     WP_NAME.get(src.stem, humanise(src.stem, category)),
            "stem":     src.stem,
            "category": category,
        })

    for p in sorted((img / "bgpack").iterdir() if (img / "bgpack").exists() else []):
        if p.suffix.lower() not in IMG_EXT: continue
        add_wallpaper(p, "lobby")

    art_dir = img / "item" / "art"
    if art_dir.exists():
        for p in sorted(art_dir.iterdir()):
            if p.suffix.lower() not in IMG_EXT: continue
            if not p.name.lower().startswith("lp_"): continue
            add_wallpaper(p, "event")

    ep_dir = img / "episode"
    if ep_dir.exists():
        for p in sorted(ep_dir.iterdir()):
            if p.suffix.lower() not in IMG_EXT: continue
            # Skip dev/test placeholders.
            if p.stem.lower().startswith("test"): continue
            add_wallpaper(p, "episode")

    story_bg = img / "story" / "bg"
    if story_bg.exists():
        for p in sorted(story_bg.iterdir()):
            if p.suffix.lower() not in IMG_EXT: continue
            if STORY_BG_SKIP.search(p.name):
                continue
            if p.stem.lower() in {"black", "white"}:
                continue   # solid-colour utility screens — not real backgrounds
            add_wallpaper(p, "story")

    # Curated banner backgrounds. banner/ is ~1,450 promo/UI images (gacha CGs,
    # shop screens, season passes, info-bar strips), so it is deliberately NOT a
    # scanned bucket — only full-bleed backgrounds hand-checked as wallpaper-
    # worthy go here. Add new picks after a visual check (see BANNER_WALLPAPERS).
    banner_dir = img / "banner"
    if banner_dir.exists():
        for name in BANNER_WALLPAPERS:
            p = banner_dir / name
            if p.is_file() and p.suffix.lower() in IMG_EXT:
                add_wallpaper(p, "event")

    img_dir = img / "img"
    if img_dir.exists():
        for name in IMG_WALLPAPERS:
            p = img_dir / name
            if p.is_file() and p.suffix.lower() in IMG_EXT:
                add_wallpaper(p, "event")

    for src, cat in EXTRA_WALLPAPERS:
        if src.is_file() and src.suffix.lower() in IMG_EXT:
            add_wallpaper(src, cat)

    # Sanctuary facility hub stills (category "lobby"). Not shipped flat by the
    # game: they are the 4K stills of the exact eff_sanc_* CFX bakes
    # (render/illust recipes sanc_*, `pipeline_illust.py still`), copied
    # under these names into render/illust/sanctuary_stills/ (gitignored,
    # like the Epic Dash stills above).
    sanctuary_dir = REPO_ROOT / "render" / "illust" / "sanctuary_stills"
    if sanctuary_dir.exists():
        for name in SANCTUARY_WALLPAPERS:
            p = sanctuary_dir / name
            if p.is_file() and p.suffix.lower() in IMG_EXT:
                add_wallpaper(p, "lobby")

    return wallpapers
