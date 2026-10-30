#!/usr/bin/env python3
"""E7 Codex — one entry point for the tooling.

    python e7.py sync   [args…]   # the change-driven export pipeline
    python e7.py build  [args…]   # just the site index (units/updates/…)
    python e7.py render [target] [args…]   # puppeteer bakes
    python e7.py deploy [args…]   # ops/deploy.ps1 through pwsh
    python e7.py mirror [args…]   # sync the public mirror (never pushes)
    python e7.py check            # golden snapshot + the leak gate

Each subcommand forwards its remaining arguments to the script it names, so

    python e7.py sync --skip-voice --skip-assets
    python e7.py build --inspect
    python e7.py deploy -SkipR2 -SkipPages

behave exactly like the underlying tool. Exit codes are propagated unchanged.

`sync` shells out to `private/ingest/sync.py` rather than importing its stages:
the orchestrator is designed around subprocess calls that each start a fresh
Python (a stage can die without taking the run with it), and turning them into
imports is phase 6 of docs/history/PLAN_refactor.md, not this file's job.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))

from e7lib.config import IMG_DIR, RAW_DIR  # noqa: E402

# Commands, in the order the help message lists them.
USAGE = __doc__.split("Each subcommand")[0].rstrip()

# `render` targets: name -> (script, extra leading args).
RENDER_TARGETS: dict[str, str] = {
    "poses": "render/poses.js",
    "thumbs": "render/thumbs.js",
    "skill3": "render/skill3.js",
    "audit": "render/audit_skins.py",
    "bg": "render/bg/render_backgrounds.js",
    "bgfield": "render/bg/render_bgfield.js",
    "bgreport": "render/bg/bg_report.js",
    "bgconvert": "render/bg/bg_convert_layers.py",
    "bgstage": "render/bg/bg_stage.py",
    "bgfieldtools": "render/bg/bg_field.py",
    "bgpacks": "render/bg/bg_packs.py",
    "illust": "render/illust/pipeline_illust.py",
}
# No target = the pair the pipeline re-renders after staging a rig.
RENDER_DEFAULT = ("poses", "thumbs")

# pwsh 7, not Windows PowerShell 5: deploy.ps1 is BOM-less UTF-8 and 5.1 decodes
# it as cp1252 (see the header of that script). A store/MSI install is not always
# on PATH, so fall back to the conventional location under %ProgramFiles% rather
# than spelling out a machine-specific path.
def _pwsh() -> str | None:
    found = shutil.which("pwsh")
    if found:
        return found
    for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramW6432")):
        if base:
            p = Path(base) / "PowerShell" / "7" / "pwsh.exe"
            if p.is_file():
                return str(p)
    return None


PWSH = _pwsh()


def _run(cmd: list[str]) -> int:
    print(f"$ {' '.join(str(c) for c in cmd)}", flush=True)
    return subprocess.call([str(c) for c in cmd], cwd=str(REPO))


def _missing(script: str) -> bool:
    # The public mirror ships only part of the tree (no private/, ops/ or tests/golden/).
    if (REPO / script).is_file():
        return False
    print(f"{script} is not part of this checkout "
          "(that command is not available in this repository)", file=sys.stderr)
    return True


def _node(script: str, *args: str) -> int:
    if _missing(script):
        return 2
    return _run(["node", str(REPO / script), *args])


def _py(script: str, *args: str) -> int:
    if _missing(script):
        return 2
    return _run([sys.executable, str(REPO / script), *args])


def cmd_sync(args: list[str]) -> int:
    return _py("private/ingest/sync.py", *args)


def cmd_build(args: list[str]) -> int:
    # The usual roots come from e7lib.config; anything the caller passes later
    # wins, because argparse keeps the last value of a repeated option.
    return _py("pipeline/build_index.py",
               "--img", str(IMG_DIR), "--raw", str(RAW_DIR), "--out", str(REPO / "site"),
               *args)


def cmd_render(args: list[str]) -> int:
    if args and args[0] in RENDER_TARGETS:
        target, rest = args[0], args[1:]
    elif args and args[0] in ("-h", "--help"):
        print("render targets: " + ", ".join(sorted(RENDER_TARGETS))
              + f"\n(no target = {' then '.join(RENDER_DEFAULT)})")
        return 0
    elif args:
        print(f"unknown render target {args[0]!r}\n" + USAGE, file=sys.stderr)
        return 2
    else:
        target, rest = None, []

    if target is not None:
        script = RENDER_TARGETS[target]
        return _node(script, *rest) if script.endswith(".js") else _py(script, *rest)

    for t in RENDER_DEFAULT:
        script = RENDER_TARGETS[t]
        rc = _node(script, *rest) if script.endswith(".js") else _py(script, *rest)
        if rc:
            return rc
    return 0


def cmd_deploy(args: list[str]) -> int:
    script = REPO / "ops" / "deploy.ps1"
    if not script.is_file():
        print("ops/deploy.ps1 is not part of this checkout "
              "(the deploy routine is not published)", file=sys.stderr)
        return 2
    if not PWSH:
        print("pwsh 7 not found — install PowerShell 7 or add pwsh to PATH",
              file=sys.stderr)
        return 2
    return _run([PWSH, "-NoProfile", "-File", str(script), *args])


def cmd_check(args: list[str]) -> int:
    if args:
        print("check takes no arguments", file=sys.stderr)
        return 2
    rc = _py("tests/golden/snapshot.py", "--check")
    if rc:
        return rc
    return _py("private/ingest/sync.py", "--verify-only")


def cmd_mirror(args: list[str]) -> int:
    return _py("ops/mirror.py", *args)


COMMANDS = {
    "sync": cmd_sync,
    "build": cmd_build,
    "render": cmd_render,
    "deploy": cmd_deploy,
    "mirror": cmd_mirror,
    "check": cmd_check,
}


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(USAGE)
        return 0 if argv else 2
    name, rest = argv[0], argv[1:]
    if name not in COMMANDS:
        print(f"unknown command {name!r}\n\n{USAGE}", file=sys.stderr)
        return 2
    try:
        return COMMANDS[name](rest)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
