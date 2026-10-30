#!/usr/bin/env python3
"""
E7 Codex — site index builder: the entry point and the orchestration only.

The site enumerates units by **portrait ID** (c1001, npc1467, m9181, …) because
that's the unit of artwork we can reliably bake — see `render/poses.js`. For
every ID with a baked pose at site/assets/<id>/pose.png we produce a units.json
entry: kind (from ID prefix), pose path, artwork matches, skill animation
stills, update-codename tags, and — if we know a name for it — display name +
ceciliabot kebab slug.

The work itself lives in `pipeline/indexing/`, one module per step, called in
this order by `build()` below (read them in that order):

    tables      every hand-edited table — open this one on a new pack
    slugs       split_variant / kind_of / kebab
    fsutil      walk + the animated-WebP loop fix and its sweep
    sources     the data_external/*.json loaders (names, codenames, artifacts)
    unreleased  the DMCA guard: held slugs, filename tokens, the deep scan
    units       step 1: role map + unit materialization (names, spine, combat)
    artwork     steps 2/3/3b: face art, S3 stills, intimacy
    updates     step 4: banner/story art per codename
    artifacts   step 4b: artifact art + names, signature/owner links
    emotes      step 5: emote groups
    wallpapers  step 6: the four buckets + the curated picks
    flags       new / modified / released / announced badges
    write       steps 7-8: every file the build writes (JSON, stubs, sitemap)
    summary     the run report
    audit       --inspect (read-only)

Names come from four layers in `sources.load_name_db()` — HeroDatabase /
HeroSkins / the rtastats scrape, then the in-game `names_from_db.json`, which
wins. See docs/reference/units.md.

Run:
    python e7.py build          # --img/--raw/--out come from e7lib.config
    python pipeline/build_index.py --img <img_dir> --raw <raw_dir> --out ./site
"""
from __future__ import annotations
import argparse, sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

_REPO = Path(__file__).resolve().parents[1]      # repo root
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))
from e7lib.bootstrap import add_source_dirs  # noqa: E402
add_source_dirs(_REPO)

# ── the build steps, in the order build() calls them ───────────────────────
from indexing.fsutil import sweep_webp_loops  # noqa: E402
from indexing.sources import (  # noqa: E402
    load_artifact_db, load_event_labels, load_name_db,
)
from indexing.unreleased import load_guard, split_held  # noqa: E402
from indexing.tables import effective_swap_map  # noqa: E402
from indexing.units import (  # noqa: E402
    build_units, plan_roles, staged_unit_dirs, swap_alias_map,
)
from indexing.artwork import stage_faces, stage_intimacy, stage_skills  # noqa: E402
from indexing.updates import build_updates, stage_update_art  # noqa: E402
from indexing.artifacts import (  # noqa: E402
    attach_artifact_owners, attach_signature_artifacts, stage_artifact_art,
)
from indexing.emotes import build_emotes  # noqa: E402
from indexing.wallpapers import build_wallpapers  # noqa: E402
from indexing.flags import (  # noqa: E402
    apply_announced_flags, apply_modified_flags, apply_new_flags,
    apply_released_dates,
)
from indexing.write import (  # noqa: E402
    write_catalogs, write_seo, write_units, write_unreleased,
)
from indexing.summary import print_summary  # noqa: E402
from indexing.audit import inspect_site  # noqa: E402

# The old name of the --inspect report, kept for callers that import it.
inspect = inspect_site

# ── re-exported public surface ─────────────────────────────────────────────
# These names are imported from `build_index` by callers outside this file
# (and the public mirror ships this module), so their old import path keeps
# working: the tables, the slug helpers, the loaders and the badge passes.
from indexing.tables import (  # noqa: E402,F401
    ANNOUNCED, BANNER_WALLPAPERS, CECILIA_ARTIFACT, CECILIA_BASE, CECILIA_INDEX,
    CODE_RE, EXTRA_SUFFIX, EXTRA_WALLPAPERS, IMG_EXT, IMG_WALLPAPERS,
    KNOWN_UPDATES, MANUAL_ARTIFACTS, MANUAL_NAMES, MOD_WINDOW_DAYS,
    NEW_WINDOW_DAYS, PRIMARY_SWAP, PRIMARY_SWAP_EXCEPT, SANCTUARY_WALLPAPERS,
    SIGNATURE_ARTIFACTS, SLUG_PARENT, UNRELEASED_ARTIFACTS, UPDATE_EXTRA_STORY,
    VARIANT_SUFFIXES, WP_NAME,
)
from indexing.slugs import kebab, kind_of, split_variant  # noqa: E402,F401
from indexing.fsutil import force_webp_loop, walk  # noqa: E402,F401
from indexing.unreleased import (  # noqa: E402,F401
    assert_no_held_tokens, assert_no_held_units,
)


def build(img: Path, raw: Path, out: Path) -> None:
    site_assets = out / "assets"
    if not site_assets.exists():
        raise SystemExit(f"no {site_assets} — run `python pipeline/prepare_assets.py --all` then "
                          "`node render/poses.js` first")

    root = out.parent if out.name == "site" else Path(".")
    name_base, name_skin = load_name_db(root)
    event_labels = load_event_labels(root)   # codename -> human label (DB > KNOWN_UPDATES)

    # Unreleased-unit guard: slugs the game still labels "Unknown Hero" are
    # unannounced (placeholder rows in character_player.db; see
    # pipeline/names.py). They must not appear on the public site at all —
    # no listing here, and ops/deploy.ps1 keeps their assets off R2 + Pages. The
    # flag flips to a real name a few days before release, so they surface
    # automatically once SG announces them.
    guard = load_guard(root)   # held slugs + their filename tokens (indexing.unreleased)

    all_dirs = staged_unit_dirs(site_assets)
    n_hidden = sum(1 for d in all_dirs if guard.is_held(d.name))
    staged = {d.name for d in all_dirs}
    # Effective backdrop-swap map: explicit PRIMARY_SWAP entries plus any
    # auto-detected (X, X_1) pair (see effective_swap_map above).
    swap = effective_swap_map(staged)
    role = plan_roles(staged, swap)
    units = build_units(all_dirs, raw, name_base, name_skin, swap, role)
    swap_alias = swap_alias_map(swap, units)

    stage_faces(img, site_assets, units, swap_alias)
    stage_skills(img, site_assets, units, swap_alias)
    stage_intimacy(img, site_assets, units, swap_alias)

    banners_per_code, story_per_code = stage_update_art(
        img, site_assets, guard, event_labels)

    artifact_db = load_artifact_db(root)
    artifacts_out, artifacts_unrel = stage_artifact_art(img, site_assets, artifact_db)

    emotes_list = build_emotes(img, site_assets, units, name_base, guard)

    wallpapers = build_wallpapers(img, site_assets, guard)

    # Safety net: force infinite loop on EVERY staged animated WebP, whichever
    # step copied it. Newer packs ship cut-ins/emotes/etc. with loop=1 (play once
    # then freeze — first bit c5069's skill cut-in, then c5147's emote). The
    # per-step force_webp_loop() calls above only touch FRESHLY-copied files, so
    # they miss already-staged webps and any future copy path we forget to wire.
    # This unconditional, idempotent sweep is the single guarantee that no
    # animated webp ever ships play-once again. See [[project-e7-webp-loop-sweep]].
    n_loop = sweep_webp_loops(site_assets)

    # Flag newly-seen units/artifacts/emotes/wallpapers (first_seen ledger) +
    # float artifacts up (units sort new-first in the frontend; emotes/wallpapers
    # float up there too).
    n_new = apply_new_flags(units, artifacts_out, emotes_list, wallpapers)
    n_mod = apply_modified_flags(units)
    n_rel = apply_released_dates(units)
    # After NEW so we can strip `new` while still pre-banner (ANNOUNCED wins).
    n_ann = apply_announced_flags(units, artifacts_out)
    # Bidirectional owner links (after announced so pre-banner flags propagate):
    #   unit.signature_artifacts[]  → detail page strip
    #   artifact.owner_units[]      → Artifacts tab / zoom → unit page
    n_sig = attach_signature_artifacts(units, artifacts_out)
    # Held units must never surface as owner pills in PUBLIC artifacts.json
    # (name + #/u/ link would leak an unannounced hero) — pass released only.
    n_own = attach_artifact_owners(
        {s: u for s, u in units.items() if not guard.is_held(s)}, artifacts_out)
    artifacts_out.sort(key=lambda a: (not a.get("announced"), not a.get("new"),
                                      -(a.get("rarity") or 0), a["id"]))

    # Step 7: write outputs.
    data = out / "data"
    data.mkdir(parents=True, exist_ok=True)

    units, unrel_list = split_held(units, guard)
    write_units(data, units, guard)
    write_unreleased(data, unrel_list, artifacts_unrel, site_assets)
    updates_out = build_updates(banners_per_code, story_per_code, event_labels)
    write_catalogs(data, updates_out, emotes_list, wallpapers, artifacts_out)
    stub_bases, n_pruned = write_seo(units, out)

    print_summary(
        units=units, unrel_list=unrel_list, n_hidden=n_hidden,
        emotes_list=emotes_list, wallpapers=wallpapers, updates_out=updates_out,
        event_labels=event_labels, artifacts_out=artifacts_out,
        stub_bases=stub_bases, n_pruned=n_pruned, n_new=n_new, n_ann=n_ann,
        n_sig=n_sig, n_own=n_own, n_mod=n_mod, n_rel=n_rel, n_loop=n_loop,
        data=data)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--img", required=True, help="img_output root (decoded PNGs)")
    ap.add_argument("--raw", required=True, help="output/ root (story paths for codename scan)")
    ap.add_argument("--out", default="./site")
    ap.add_argument("--inspect", action="store_true",
                    help="read-only report (no files written)")
    a = ap.parse_args()
    if a.inspect:
        inspect_site(Path(a.img), Path(a.raw), Path(a.out))
    else:
        build(Path(a.img), Path(a.raw), Path(a.out))
