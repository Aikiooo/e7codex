"""Put the repo's code directories on `sys.path`.

The tools import each other by module name (`import build_index`,
`from scsp_to_json import convert`) rather than through a package path — that is
what they did when they all lived in `tools/`, and it keeps the call sites
unchanged. This puts the source directories on `sys.path` once, so any tool can
be run as a script from any working directory.

Deliberately not part of `e7lib.config`: config is imported by keyless consumers
that should not have to care how the code tree is laid out.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Source trees whose modules are imported by bare name. Keep this list short:
# every entry is a directory whose module names must stay unique.
SOURCE_DIRS = ("pipeline", "convert", "render/bg")

__all__ = ["SOURCE_DIRS", "add_source_dirs"]


def add_source_dirs(repo_root: Path | str) -> Path:
    """Insert `repo_root` and the code dirs on `sys.path` (idempotent).

    Returns the resolved repo root, so a caller can write
    `REPO = add_source_dirs(...)` in one line."""
    root = Path(repo_root).resolve()
    for d in (root, *(root / s for s in SOURCE_DIRS)):
        p = str(d)
        if p not in sys.path:
            sys.path.insert(0, p)
    return root
