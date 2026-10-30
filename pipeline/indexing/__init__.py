"""The site index: hand-edited tables + one module per build step.

`pipeline/build_index.py` is the entry point (same CLI, same flags); it calls
these modules in the original order:

    tables      every hand-edited list/dict — open this on a new pack
    slugs       split_variant / kind_of / kebab
    fsutil      walk, the animated-WebP loop fix + sweep
    sources     the data_external/*.json loaders (names, codenames, artifacts)
    unreleased  the DMCA guard: held slugs, token matching, the deep scan
    units       staged dirs -> role map -> materialized units (step 1)
    artwork     face art, skill stills, intimacy (steps 2, 3, 3b)
    updates     banner/story art per codename, updates.json (step 4)
    artifacts   artifact art + names, signature/owner links (step 4b)
    emotes      emote groups (step 5)
    wallpapers  the four wallpaper buckets + the curated picks (step 6)
    flags       new / modified / released / announced badges
    write       every file the build writes (steps 7-8)
    summary     the run report
    audit       --inspect (read-only)

Everything is imported as `indexing.<name>`: `pipeline/` is itself a `sys.path`
entry (`e7lib/bootstrap.py`), so this package is reached by its top-level name
and must not collide with a `pipeline/*.py` module or the stdlib — see the
package name note in `pipeline/build_index.py`.
"""
from __future__ import annotations

import sys
from pathlib import Path

# pipeline/indexing/__init__.py -> repo root. One place for the repo-relative
# reads (data_external/, timeline/, render/illust/) the modules need.
REPO_ROOT = Path(__file__).resolve().parents[2]

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
from e7lib.bootstrap import add_source_dirs  # noqa: E402

# So every module here (and `import scsp_to_json` in units.py) works from any cwd.
add_source_dirs(REPO_ROOT)

__all__ = ["REPO_ROOT"]
