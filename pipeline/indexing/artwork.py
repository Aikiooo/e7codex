"""Steps 2, 3, 3b: unit artwork — face PNGs, S3 stills, intimacy illustrations.

Every step copies into the unit's own `site/assets/<primary>/` dir and records
the relative path on the unit, routed through `swap_alias` so files named after
a backdrop bare slug land on the promoted `_1` primary.
"""
from __future__ import annotations

import hashlib
import re
import shutil
from collections import defaultdict
from pathlib import Path

from .fsutil import force_webp_loop, walk
from .tables import IMG_EXT


def stage_faces(img: Path, site_assets: Path, units: dict, swap_alias: dict) -> None:
    """Count every img_output file whose name/parent references a unit, and copy
    the face/* PNGs into the site bundle (with content-hash dedupe)."""
    # Step 2: artwork matching — count every img_output file whose name/parent
    # references the unit ID, but only COPY the face/* PNGs into the site bundle.
    # Include swap_alias keys so bare-slug face images land on the primary unit.
    # Content-hash dedupe: the dump sometimes ships identical base + `_t`
    # faces (e.g. Notos c2181 / c2181_t) that both match the same primary —
    # keep the first path only so the detail gallery doesn't show twin tiles.
    all_match_slugs = sorted(set(units) | set(swap_alias), key=len, reverse=True)
    slug_re = {s: re.compile(rf"(?:^|[^a-z0-9]){re.escape(s)}(?:[^a-z0-9]|$)", re.I)
               for s in all_match_slugs}
    counts: dict[str, int] = defaultdict(int)
    face_hashes: dict[str, set[str]] = defaultdict(set)
    n_face_dedup = 0

    for p in walk(img):
        if p.suffix.lower() not in IMG_EXT: continue
        # Skip categories we'll handle separately below.
        rel_parent = p.parent.name.lower()
        if rel_parent in {"cut", "fhd"}:  # handled in skills step
            continue
        haystack = f"{p.stem} {p.parent.name}"
        is_face = (rel_parent == "face")
        for s in all_match_slugs:
            if slug_re[s].search(haystack):
                primary = swap_alias.get(s, s)
                counts[primary] += 1
                if is_face:
                    try:
                        blob = p.read_bytes()
                    except OSError:
                        break
                    digest = hashlib.md5(blob).hexdigest()
                    if digest in face_hashes[primary]:
                        n_face_dedup += 1
                        # Drop a prior-build copy if one still sits on disk.
                        orphan = site_assets / primary / f"face_{p.name}"
                        if orphan.exists():
                            try: orphan.unlink()
                            except OSError: pass
                        break
                    face_hashes[primary].add(digest)
                    dst = site_assets / primary / f"face_{p.name}"
                    if not dst.exists():
                        try:    shutil.copy2(p, dst)
                        except OSError: break
                    rel = f"assets/{primary}/{dst.name}"
                    if rel not in units[primary]["artworks"]:
                        units[primary]["artworks"].append(rel)
                break
    for s, n in counts.items():
        if s in units:
            units[s]["artworks_count"] = n
    if n_face_dedup:
        print(f"[artwork] skipped {n_face_dedup} content-identical face PNG(s)")


def stage_skills(img: Path, site_assets: Path, units: dict, swap_alias: dict) -> None:
    """Copy the S3 still (cut/fhd/sk_<id>_3*) next to the pose."""
    # Step 3: skill animations from img_output/cut/fhd/sk_<id>_3*.webp
    # The third skill (S3) is the one E7 dumps as a still; we copy it next to
    # the pose so the detail page can render it without a second fetch path.
    # swap_alias resolves bare-slug skill files to the correct primary unit.
    fhd = img / "cut" / "fhd"
    if fhd.exists():
        sk_re = re.compile(r"^sk_(.+?)_3(?:_\d+)?\.(?:webp|png|jpg)$", re.I)
        for p in fhd.iterdir():
            m = sk_re.match(p.name)
            if not m: continue
            slug = m.group(1)
            primary = swap_alias.get(slug, slug)
            if primary not in units: continue
            dst = site_assets / primary / f"skill_{p.name}"
            if not dst.exists():
                try: shutil.copy2(p, dst)
                except OSError: continue
                if dst.suffix.lower() == ".webp":
                    force_webp_loop(dst)
            units[primary]["skills"].append(f"assets/{primary}/{dst.name}")


def stage_intimacy(img: Path, site_assets: Path, units: dict, swap_alias: dict) -> None:
    """Static intimacy webp (step 3b), then the animated webm override and the
    voice-triggered reaction clips (step 3b-2)."""
    # Step 3b: intimacy illustrations — story/bg/img_intimacy_illust_c<id>.webp (skip _th).
    # NOTE: only the `img_intimacy_illust_<slug>.webp` (story/bg) is the real
    # fully-rendered illustration. `img_illust_<slug>.png` (item/art) and
    # `sp_illust_<slug>_th.webp` are SELECTION THUMBNAILS, not the art — do NOT
    # treat them as the illustration (the in-game illustration is animated w/ voice;
    # its real static/animated source is still being identified, see TASKS).
    intimacy_re = re.compile(r"^img_intimacy_illust_(c\d+)\.webp$", re.I)
    _intimacy_dir = img / "story" / "bg"
    if _intimacy_dir.exists():
        for p in _intimacy_dir.iterdir():
            m = intimacy_re.match(p.name)
            if not m:
                continue
            slug = m.group(1)
            primary = swap_alias.get(slug, slug)
            if primary not in units:
                continue
            dst = site_assets / primary / "intimacy.webp"
            if not dst.exists():
                try:    shutil.copy2(p, dst)
                except OSError: continue
                force_webp_loop(dst)
            units[primary]["intimacy"] = f"assets/{primary}/intimacy.webp"

    # Step 3b-2: animated intimacy illustrations (preferred). A few units ship the
    # intimacy art as a multi-layer Spine effect rig (output/effect/uieff_illust_*),
    # not a static webp — baked offline (composited + cropped to the picture
    # rectangle) into assets/<slug>/intimacy.webm. When that file is present it WINS
    # over the static webp; the frontend renders a looping <video> instead of an
    # <img>. Currently c1153 (Harsetti); c2181_1 (Notos) pending.
    for uid, u in units.items():
        webm = site_assets / uid / "intimacy.webm"
        if webm.exists():
            # Append a content-version query (file mtime) so a re-baked clip gets a
            # NEW URL: the filename never changes, so Cloudflare's edge would keep
            # serving the stale copy for hours after a redeploy (a redeploy does not
            # evict the edge cache). The query is part of the CF cache key, so each
            # new bake is a guaranteed cache miss → fresh fetch. units.json itself is
            # served DYNAMIC (uncached), so the new query reaches clients immediately.
            ver = int(webm.stat().st_mtime)
            u["intimacy"] = f"assets/{uid}/intimacy.webm?v={ver}"
        # Voice-triggered reaction clips (silent): intimacy_<kind>_<n>.webm, each with
        # a poster intimacy_<kind>_<n>.jpg. The frontend shows them as a clickable row
        # under the idle illustration (open in the video lightbox). Labelled from the
        # filename: enter -> "Greeting", touch -> "Touch".
        reacts = sorted((site_assets / uid).glob("intimacy_*.webm"))
        if reacts:
            LBL = {"enter": "Greeting", "touch": "Touch"}
            rlist = []
            for p in reacts:
                parts = p.stem.split("_")        # intimacy_enter_1 -> [intimacy, enter, 1]
                kind, num = (parts[1], parts[-1]) if len(parts) >= 3 else (parts[-1], "")
                poster = site_assets / uid / f"{p.stem}.jpg"
                rlist.append({
                    "webm": f"assets/{uid}/{p.name}",
                    "poster": f"assets/{uid}/{p.stem}.jpg" if poster.exists() else None,
                    "label": f"{LBL.get(kind, kind.title())} {num}".strip(),
                })
            u["intimacy_reactions"] = rlist
