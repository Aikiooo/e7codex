"""Publish the community-requests list to its own Pages project.

  python tools/publish_requests.py --dry-run   # validate + build dist-requests/
  python tools/publish_requests.py             # validate + build + deploy

Why a separate project: the list is edited far more often than the site is
rebuilt, so it gets its own deploy target that holds ONLY requests.json +
_headers + 404.html. Editing a row never requires a full site deploy, and the
main e7codex Pages project cannot be affected. Mirrors the mtcoe-news pattern.

The list lives in two places by design:
  - site/data/community_requests.json — source of truth, committed, and bundled
    with the main site as the same-origin fallback when this project is
    unreachable (or not yet created).
  - the e7codex-requests Pages project — what this script publishes.

One-time project setup (needs Cloudflare auth):
  npx wrangler pages project create e7codex-requests --production-branch main

Deploying is a publish, not a release: nothing here ships without the usual
explicit OK, and every entry must pass the unreleased-content guard first.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "site" / "data" / "community_requests.json"
DIST = ROOT / "dist-requests"
PROJECT = "e7codex-requests"
BRANCH = "main"

STATUSES = {"shipped", "planned", "wip"}
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,60}$")
FIELDS = {"id", "title", "status", "requested", "shipped", "link", "note"}


def fail(msg: str) -> None:
    print(f"ABORT: {msg}", file=sys.stderr)
    sys.exit(1)


def validate(items) -> None:
    if not isinstance(items, list):
        fail("top level must be a JSON array")
    if not items:
        fail("list is empty — nothing to publish")

    seen = set()
    for i, r in enumerate(items):
        where = f"entry {i + 1}"
        if not isinstance(r, dict):
            fail(f"{where}: not an object")

        unknown = set(r) - FIELDS
        if unknown:
            fail(f"{where}: unknown field(s) {sorted(unknown)}")

        rid = r.get("id")
        if not isinstance(rid, str) or not ID_RE.match(rid):
            fail(f"{where}: id must be a lowercase slug (a-z, 0-9, -)")
        if rid in seen:
            fail(f"{where}: duplicate id '{rid}'")
        seen.add(rid)
        where = f"{rid}"

        if not isinstance(r.get("title"), str) or not r["title"].strip():
            fail(f"{where}: title is required")
        if r.get("status") not in STATUSES:
            fail(f"{where}: status must be one of {sorted(STATUSES)}")

        req = r.get("requested")
        if not isinstance(req, str) or not DATE_RE.match(req):
            fail(f"{where}: requested must be YYYY-MM-DD")
        ship = r.get("shipped")
        if r["status"] == "shipped":
            if not isinstance(ship, str) or not DATE_RE.match(ship):
                fail(f"{where}: status 'shipped' needs a shipped date (YYYY-MM-DD)")
            if ship < req:
                fail(f"{where}: shipped {ship} is before requested {req}")
        elif ship is not None:
            fail(f"{where}: status '{r['status']}' must not carry a shipped date")

        link = r.get("link")
        if link is not None:
            if not isinstance(link, str) or not link.strip():
                fail(f"{where}: link must be a non-empty string or omitted")
            if "://" in link or link.startswith("//") or link.startswith(".."):
                fail(f"{where}: link must be a site-relative path")

        note = r.get("note")
        if note is not None and (not isinstance(note, str) or not note.strip()):
            fail(f"{where}: note must be a non-empty string or omitted")


def build(items) -> None:
    shutil.rmtree(DIST, ignore_errors=True)
    DIST.mkdir(parents=True)
    (DIST / "requests.json").write_text(
        json.dumps(items, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    (DIST / "_headers").write_text(
        "/*\n  Access-Control-Allow-Origin: *\n  Cache-Control: public, max-age=300\n",
        encoding="utf-8",
    )
    (DIST / "404.html").write_text(
        '<!DOCTYPE html><html><head><meta charset="utf-8"><title>404</title></head>'
        "<body>Not found</body></html>",
        encoding="utf-8",
    )


def leak_gate() -> None:
    """Same deep gate the site deploy runs: this is the only other public path."""
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "leak_check.py")], cwd=ROOT)
    if r.returncode != 0:
        fail("leak_check failed — nothing published (see output above)")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true", help="validate + build only")
    args = p.parse_args()

    items = json.loads(SRC.read_text(encoding="utf-8"))
    validate(items)
    leak_gate()
    build(items)

    shipped = sum(1 for r in items if r["status"] == "shipped")
    wip = sum(1 for r in items if r["status"] == "wip")
    planned = len(items) - shipped - wip
    print(f"{len(items)} entr{'y' if len(items) == 1 else 'ies'} "
          f"({shipped} shipped, {wip} wip, {planned} planned) -> {DIST}")

    if args.dry_run:
        print("dry run — not deployed")
        return

    r = subprocess.run(
        ["npx", "wrangler", "pages", "deploy", str(DIST),
         "--project-name", PROJECT, "--branch", BRANCH],
        cwd=ROOT,
        shell=True,
    )
    if r.returncode != 0:
        fail(f"wrangler deploy failed (exit {r.returncode}) — if the project does "
             f"not exist yet: npx wrangler pages project create {PROJECT} "
             f"--production-branch {BRANCH}")
    print(f"deployed -> https://{PROJECT}.pages.dev/requests.json")


if __name__ == "__main__":
    main()
