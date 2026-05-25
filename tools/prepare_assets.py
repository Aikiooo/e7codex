"""
Stage one (or many) E7 portrait units into site/assets/<slug>/.

For each <slug>, produces:
  site/assets/<slug>/<slug>.json    Spine JSON (reused from D:\\Claude\\E7\\yes\\ if already converted, else freshly via scsp_to_json.py)
  site/assets/<slug>/<slug>.atlas   atlas with the .sct line rewritten to .png
  site/assets/<slug>/<slug>.png     decoded texture

After this runs you can point a Spine 3.8 player at site/assets/<slug>/<slug>.json
and get a renderable rig. Pair with render_poses.js to bake a static pose.png.

Usage:
  python prepare_assets.py <slug> [<slug> ...]
  python prepare_assets.py --all                # every .scsp in output/portrait
  python prepare_assets.py --from yes           # every json that already exists in yes/
"""
from __future__ import annotations
import argparse, re, shutil, sys, traceback
from pathlib import Path

THIS   = Path(__file__).resolve()
REPO   = THIS.parents[1]                       # E7 Codex
ROOT   = REPO.parent                           # D:\Claude\E7
PORT   = ROOT / "output" / "portrait"
YESDIR = ROOT / "yes"
SITE   = REPO / "site" / "assets"

sys.path.insert(0, str(THIS.parent))
from decode_sct  import decode_one as decode_sct  # type: ignore
import scsp_to_json                                # type: ignore
import find_backdrops                              # type: ignore

def normalize_slug(s: str) -> str:
    """Map bare-digit slugs to c#### form (e.g. '5033' → 'c5033').

    The E7 dump occasionally ships source files without the 'c' prefix.
    Normalizing here ensures site/assets/ always uses the canonical slug.
    """
    return "c" + s if re.match(r"^\d+$", s) else s


def stage_atlas(src_atlas: Path, dst_atlas: Path, png_name: str) -> None:
    out, swapped = [], False
    for line in src_atlas.read_text(encoding="utf-8").splitlines():
        if not swapped and line.strip().endswith(".sct"):
            out.append(png_name); swapped = True
        else:
            out.append(line)
    dst_atlas.write_text("\n".join(out) + "\n", encoding="utf-8")

def stage_one(slug: str, force: bool = False) -> tuple[bool, str]:
    """Returns (ok, note). Note is empty on full success."""
    # The dump may use a bare digit name in source files (e.g. '5033' vs 'c5033').
    # Try the normalized slug first; fall back to the bare version.
    bare = slug[1:] if (slug.startswith("c") and slug[1:].isdigit()) else slug
    candidates = [slug] if bare == slug else [slug, bare]
    src_slug = None
    for candidate in candidates:
        if all((PORT / f"{candidate}{ext}").exists() for ext in (".scsp", ".atlas", ".sct")):
            src_slug = candidate
            break
    if src_slug is None:
        return False, "missing source files in output/portrait"

    scsp  = PORT / f"{src_slug}.scsp"
    atlas = PORT / f"{src_slug}.atlas"
    sct   = PORT / f"{src_slug}.sct"

    dst_dir   = SITE / slug
    dst_json  = dst_dir / f"{slug}.json"
    dst_atlas = dst_dir / f"{slug}.atlas"
    dst_png   = dst_dir / f"{slug}.png"
    dst_dir.mkdir(parents=True, exist_ok=True)

    # JSON — prefer yes/<slug>.json, fall back to yes/<src_slug>.json if different.
    if force or not dst_json.exists():
        yes_json = YESDIR / f"{slug}.json"
        yes_src  = YESDIR / f"{src_slug}.json"
        if yes_json.exists():
            shutil.copy2(yes_json, dst_json)
        elif src_slug != slug and yes_src.exists():
            shutil.copy2(yes_src, dst_json)
        else:
            scsp_to_json.convert(scsp, dst_json)

    # texture
    if force or not dst_png.exists():
        decode_sct(sct, dst_png)

    # atlas
    if force or not dst_atlas.exists():
        stage_atlas(atlas, dst_atlas, f"{slug}.png")

    return True, ""

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("slugs", nargs="*")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--from-yes", action="store_true",
                    help="stage every slug that already has a JSON in D:\\Claude\\E7\\yes\\")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()

    slugs: list[str] = [normalize_slug(s) for s in a.slugs]
    if a.all:
        slugs += [normalize_slug(p.stem) for p in PORT.glob("*.scsp")]
    if a.from_yes:
        slugs += [normalize_slug(p.stem) for p in YESDIR.glob("*.json")]
    slugs = sorted(set(slugs))
    if not slugs:
        ap.error("no slugs given (use positional args, --all, or --from-yes)")

    ok = fail = 0
    for s in slugs:
        try:
            done, note = stage_one(s, force=a.force)
            if done:
                ok += 1; print(f"[ok]   {s}")
            else:
                fail += 1; print(f"[skip] {s}: {note}")
        except Exception as e:
            fail += 1
            print(f"[fail] {s}: {e}")
            if a.force: traceback.print_exc()
    print(f"\n[summary] {ok} prepared, {fail} skipped/failed (out of {len(slugs)})")

    print("\n--- scanning for new backdrop/character (X, X_1) pairs ---")
    try:
        find_backdrops.main([])
    except Exception as e:
        print(f"[warn] find_backdrops scan failed: {e}")

if __name__ == "__main__":
    main()
