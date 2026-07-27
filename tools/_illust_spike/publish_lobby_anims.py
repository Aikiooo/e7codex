"""Stage lobby anim posters/local videos + optional R2 upload for large WebMs.

  python publish_lobby_anims.py              # hardlink masters → site/assets/_illust/videos/
  python publish_lobby_anims.py --upload    # rclone copy WebMs → r2:e7codex-spine/illust/

Does NOT run deploy.ps1.
  - Posters: site/assets/_illust/posters/  (Pages OK, ~100–200 KB)
  - Local Play: site/assets/_illust/videos/*.webm hardlinks (gitignored; held off Pages)
  - Prod: R2 https://assets.e7codex.com/illust/<id>.webm  (Pages 25 MiB limit)

Catalog: site/data/lobby_anims.json
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

SPIKE = Path(__file__).resolve().parent
REPO = SPIKE.parents[1]  # E7 Codex
SITE = REPO / "site"
DATA = SITE / "data" / "lobby_anims.json"
POSTER_DIR = SITE / "assets" / "_illust" / "posters"
VIDEO_DIR = SITE / "assets" / "_illust" / "videos"
SCRATCH = REPO.parent / "_scratch"

# id → local master WebM (scratch)
WEBMS: dict[str, Path] = {
    "vsu6aa_lobby": SCRATCH / "lobby_aube" / "aube_lobby_idle_hq.webm",
    "vva5aa_lobby": SCRATCH / "lobby_vva5aa" / "tori_vva5aa_lobby_idle.webm",
    "vsu5aa_1": SCRATCH / "lobby_events" / "vsu5aa_1_lobby.webm",
    "vsu5aa_2_lobby": SCRATCH / "lobby_events" / "vsu5aa_2_lobby.webm",
    "vsu4aa1": SCRATCH / "lobby_events" / "vsu4aa1_lobby.webm",
    "vsu4aa2": SCRATCH / "lobby_events" / "vsu4aa2_lobby.webm",
    "vsu3aa1": SCRATCH / "lobby_events" / "vsu3aa1_lobby.webm",
    "vsu3aa2": SCRATCH / "lobby_events" / "vsu3aa2_lobby.webm",
    "vae2aa1": SCRATCH / "lobby_events" / "vae2aa1_lobby.webm",
    "vt41aa_1": SCRATCH / "lobby_events" / "vt41aa_1_lobby.webm",
    "vms03c_1": SCRATCH / "lobby_events" / "vms03c_1_lobby.webm",
    "epma_04": SCRATCH / "lobby_events" / "epma_04_lobby.webm",
    "epma_04_story": SCRATCH / "lobby_events" / "epma_04_story_lobby.webm",
    "imgsa_1_1": SCRATCH / "lobby_events" / "imgsa_1_1_lobby.webm",
    "vfr5aa_3": SCRATCH / "lobby_events" / "vfr5aa_3_lobby.webm",
    "lobby_prequel_1": SCRATCH / "lobby_events" / "lobby_prequel_1.webm",
    "lobby_prequel_2": SCRATCH / "lobby_events" / "lobby_prequel_2.webm",
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--upload",
        action="store_true",
        help="rclone copy each master WebM to r2:e7codex-spine/illust/<id>.webm",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="with --upload, only print rclone commands",
    )
    args = ap.parse_args()

    if not DATA.is_file():
        print(f"missing {DATA}", file=sys.stderr)
        return 1
    catalog = json.loads(DATA.read_text(encoding="utf-8"))
    print(f"catalog: {len(catalog)} entries")
    print(f"posters: {POSTER_DIR} ({sum(1 for _ in POSTER_DIR.glob('*.jpg')) if POSTER_DIR.is_dir() else 0} files)")

    # Local hardlinks so localhost Play works without R2.
    VIDEO_DIR.mkdir(parents=True, exist_ok=True)
    gi = VIDEO_DIR / ".gitignore"
    if not gi.is_file():
        gi.write_text("*\n!.gitignore\n", encoding="utf-8")

    def video_stems(entry: dict) -> list[str]:
        """Pack id and/or each variants[].video stem (epma_04 + epma_04_story)."""
        stems: list[str] = []
        for v in entry.get("variants") or []:
            vid = (v.get("video") or "").replace("\\", "/")
            name = Path(vid).stem
            if name and name not in stems:
                stems.append(name)
        if not stems and entry.get("id"):
            stems.append(entry["id"])
        # Always include top-level video stem if present
        top = Path((entry.get("video") or "").replace("\\", "/")).stem
        if top and top not in stems:
            stems.insert(0, top)
        return stems

    missing = []
    for e in catalog:
        poster = SITE / e["poster"]
        if not poster.is_file():
            print(f"  [poster MISSING] {e['poster']}")
        for stem in video_stems(e):
            src = WEBMS.get(stem)
            if not src or not src.is_file():
                # Fallback: out_dir style name
                alt = SCRATCH / "lobby_events" / f"{stem}_lobby.webm"
                src = alt if alt.is_file() else src
            if not src or not src.is_file():
                missing.append(stem)
                print(f"  [webm MISSING] {stem}")
                continue
            mb = src.stat().st_size / (1024 * 1024)
            local = VIDEO_DIR / f"{stem}.webm"
            try:
                if local.exists() or local.is_symlink():
                    local.unlink()
                os.link(src, local)
                link = "hardlink"
            except OSError:
                shutil.copy2(src, local)
                link = "copy"
            print(
                f"  {stem:20s}  {mb:7.1f} MB  local={link}  →  assets.e7codex.com/illust/{stem}.webm"
            )

    if missing:
        print(f"\n{len(missing)} WebM(s) missing from scratch — bake first.")
        if args.upload:
            print("  Continuing upload for the masters that are present.")

    if not args.upload:
        print(
            "\nLocal Play: site/assets/_illust/videos/ (hardlinks; not on Pages).\n"
            "To publish prod videos (R2):\n"
            "  python tools/_illust_spike/publish_lobby_anims.py --upload\n"
            "Posters ship with Pages. Videos: R2 only."
        )
        return 0

    # Stage into a temp folder with CDN object names, then one rclone copy.
    stage = SPIKE / "_r2_illust_stage"
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)
    for e in catalog:
        for stem in video_stems(e):
            src = WEBMS.get(stem)
            if not src or not src.is_file():
                alt = SCRATCH / "lobby_events" / f"{stem}_lobby.webm"
                src = alt if alt.is_file() else None
            if not src or not src.is_file():
                continue
            name = f"{stem}.webm"
            shutil.copy2(src, stage / name)
            print(f"  staged {name}")

    cmd = [
        "rclone",
        "copy",
        str(stage),
        "r2:e7codex-spine/illust/",
        "--progress",
        "--transfers",
        "2",
    ]
    print("$", " ".join(cmd))
    if args.dry_run:
        return 0
    r = subprocess.run(cmd)
    if r.returncode == 0:
        print("OK → https://assets.e7codex.com/illust/")
        shutil.rmtree(stage, ignore_errors=True)
    return r.returncode


if __name__ == "__main__":
    raise SystemExit(main())
