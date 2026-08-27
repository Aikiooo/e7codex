"""Build profile-frame catalog for the avatar + frame compositor (TASKS.md #32).

Indexes in-game profile borders (`img_output/item/border/*.png`, all 148×148)
plus extra circular rings community asked for (legacy device frames and
battle-UI hero rings).

  - `site/data/frames.json` — committed catalog (like units.json)
  - `site/assets/_frames/` — staged PNGs under the gitignored `site/assets/`
    (present on the deploy machine; wrangler uploads them with Pages)

Official profile borders (item/border, 148×148):
  Bit-exact copies. Site composites with RE/game values from
  UIUtil.getUserIcon — face 112 centered on canvas 148. Never re-encode,
  never re-measure, never rescale.

UI / legacy rings (hero_s_frame*, legacy_frame_*):
  Not profile borders; no RE layout. Same layout target as official:
  **face 112 on canvas 148**. The ring (not the face) is placed by:

    1. Locate the true hole center + multi-ray p85 radius (ignores interior
       deco; handles off-center art like hero_s_frame_guide).
    2. Prefer scale so hole ≈ r51 when all paint still fits with the hole
       locked to the canvas center.
    3. Otherwise fit-scale (full flourishes visible, hole slightly smaller).
    4. Paste so the hole center lands on the canvas center.

  Canvas is always 148 — preview never jumps.

Usage:
  python tools/build_frames.py
  python tools/build_frames.py --src D:/path/to/img_output/item/border
"""
from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from paths import IMG_DIR  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    Image = None  # type: ignore

REPO = Path(__file__).resolve().parents[1]
SITE = REPO / "site"
DATA_OUT = SITE / "data" / "frames.json"
ASSET_OUT = SITE / "assets" / "_frames"
CANVAS = 148
DEFAULT_FACE_BOX = 112
# icon_border_base / UIUtil.getUserIcon: hole ~r51; face always 112 on 148.
REF_HOLE_R = 51
_HOLE_ALPHA = 30
# Tiny transparent margin so antialiased edges aren't hard-clipped at canvas.
_EDGE_PAD = 2
# Multi-ray hole: high percentile ignores interior decorations that only
# block some angles (first-opaque-from-center is wrong for those).
_HOLE_RAYS = 96
_HOLE_PERCENTILE = 85

# Per-frame UI overrides (catalog id → options). Official borders never use these.
#   src_avatar: (x, y, w, h) on the SOURCE png — ground-truth face slot
#               (e.g. guide marked #ed1d25 region = 96×96 at 32,32 on 160²)
#   target_hole / mask_r: legacy knobs (prefer src_avatar when known)
_UI_OVERRIDES: dict[str, dict] = {
    # Battle-UI guide ring — ground truth from user-painted #ed1d25 plate on
    # the 160×160 asset (D:\Downloads\_hero_s_frame_guide.png):
    #   plate center ≈ (79, 78), size 96×96. NOT profile 112/148.
    # Stage bit-exact 160; site draws face at face_center with face_box=96.
    "hero_s_frame_guide": {
        "native": True,
        "face_box": 96,
        "face_center": (79, 78),
    },
}

# Filename → UI category. Order of first match wins.
# Arena = classic / seasonal PvP ranks; RTA = World Arena (ssN_rta*).
# ui = non-profile circular rings (legacy device frames, battle hero_s rings).
_CAT_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("ui", re.compile(r"legacy_frame|hero_s_frame", re.I)),
    ("rta", re.compile(r"(?:^|_)rta|_ss\d+_rta|ss\d+_rta", re.I)),
    ("arena", re.compile(
        r"(?:^|_)pvp_|rookie_rank|rank_none|pvp_season|pvp_rookie", re.I)),
    ("tournament", re.compile(r"e7wc|e7masters|ecl\d+|clan_tournament|clan_war", re.I)),
    ("clan", re.compile(r"clan", re.I)),
    ("abyss", re.compile(r"abyss", re.I)),
    ("event", re.compile(
        r"login|days|anniversary|\d+th|huawei|donation|guide_clear|automt|"
        r"seasonpass|season_pass", re.I)),
]


def categorize(stem: str) -> str:
    s = stem
    if s.startswith("icon_border_"):
        s = s[len("icon_border_"):]
    for cat, rx in _CAT_RULES:
        if rx.search(s) or rx.search(stem):
            return cat
    return "other"


def pretty_label(stem: str) -> str:
    """Human-ish label from filename: icon_border_pvp_season27_rank_1 → PvP season 27 rank 1."""
    s = stem
    if s.startswith("icon_border_"):
        s = s[len("icon_border_"):]
    s = s.replace("_", " ")
    s = re.sub(r"\bpvp\b", "PvP", s, flags=re.I)
    s = re.sub(r"\brta\b", "RTA", s, flags=re.I)
    s = re.sub(r"\be7wc\b", "E7WC", s, flags=re.I)
    s = re.sub(r"\be7masters\b", "E7 Masters", s, flags=re.I)
    s = re.sub(r"\bhero s frame\b", "Hero S frame", s, flags=re.I)
    s = re.sub(r"\blegacy frame\b", "Legacy frame", s, flags=re.I)
    return s.strip() or stem


def _circ_frac(
    px, w: int, h: int, cx: float, cy: float, r: float,
    samples: int = 72, alpha: int = _HOLE_ALPHA,
) -> float:
    """Fraction of samples on circle (cx,cy,r) that are opaque."""
    if r <= 0.5:
        return 0.0
    n = 0
    for i in range(samples):
        ang = 2.0 * math.pi * i / samples
        x = int(round(cx + r * math.cos(ang)))
        y = int(round(cy + r * math.sin(ang)))
        if 0 <= x < w and 0 <= y < h and px[x, y][3] > alpha:
            n += 1
    return n / samples


def _ray_hits(
    px, w: int, h: int, cx: float, cy: float, alpha: int = _HOLE_ALPHA
) -> list[float]:
    """First-opaque distance along N rays from (cx, cy). Fallback only."""
    max_r = min(cx, cy, w - 1 - cx, h - 1 - cy)
    if max_r < 2:
        return []
    hits: list[float] = []
    for i in range(_HOLE_RAYS):
        ang = 2.0 * math.pi * i / _HOLE_RAYS
        dx, dy = math.cos(ang), math.sin(ang)
        r = 0.0
        while r < max_r:
            x = int(round(cx + dx * r))
            y = int(round(cy + dy * r))
            if x < 0 or y < 0 or x >= w or y >= h:
                break
            if px[x, y][3] > alpha:
                hits.append(r)
                break
            r += 0.5
    return hits


def _pct(hits: list[float], p: float) -> float:
    hits = sorted(hits)
    if not hits:
        return 0.0
    idx = int(round((p / 100.0) * (len(hits) - 1)))
    idx = max(0, min(len(hits) - 1, idx))
    return hits[idx]


def _find_hole(im: "Image.Image") -> tuple[float, float, float]:
    """Locate the main ring's center + inner hole radius for a UI frame.

    Guide art is off-center on its PNG and has outer flourishes that fool
    simple ray/variance searches. We sample the solid ring band along many
    angles and least-squares fit a circle — that center is where the face
    must sit. Hole = first radius with a mostly-opaque circumference.
    """
    im = im.convert("RGBA")
    w, h = im.size
    px = im.load()
    gcx, gcy = (w - 1) / 2.0, (h - 1) / 2.0
    max_r = int(min(w, h) / 2)
    # Expected main-ring band (skip inner deco + outer flourishes).
    band_lo = max(10, int(max_r * 0.32))
    band_hi = max(band_lo + 6, int(max_r * 0.72))

    # Midpoint of the longest opaque run in the band, per angle.
    pts_x: list[float] = []
    pts_y: list[float] = []
    n_ang = 180
    for i in range(n_ang):
        ang = 2.0 * math.pi * i / n_ang
        dx, dy = math.cos(ang), math.sin(ang)
        best_run = 0
        best_mid = 0.0
        r = band_lo
        while r <= band_hi:
            x = int(round(gcx + dx * r))
            y = int(round(gcy + dy * r))
            if not (0 <= x < w and 0 <= y < h) or px[x, y][3] <= _HOLE_ALPHA:
                r += 1
                continue
            run0 = r
            while r <= band_hi + 8:
                x = int(round(gcx + dx * r))
                y = int(round(gcy + dy * r))
                if not (0 <= x < w and 0 <= y < h) or px[x, y][3] <= _HOLE_ALPHA:
                    break
                r += 1
            run = r - run0
            if run > best_run:
                best_run = run
                best_mid = run0 + run / 2.0
            r += 1
        if best_run >= 2:
            pts_x.append(gcx + dx * best_mid)
            pts_y.append(gcy + dy * best_mid)

    cx, cy = gcx, gcy
    if len(pts_x) >= 12:
        # Algebraic least-squares circle: x²+y² + D x + E y + F = 0
        # (no numpy dependency — small N, pure Python normal equations)
        n = len(pts_x)
        s_x = s_y = s_xx = s_yy = s_xy = s_xz = s_yz = s_z = 0.0
        for x, y in zip(pts_x, pts_y):
            z = x * x + y * y
            s_x += x
            s_y += y
            s_xx += x * x
            s_yy += y * y
            s_xy += x * y
            s_xz += x * z
            s_yz += y * z
            s_z += z
        # Solve 3x3 for D,E,F via Cramer's rule on the normal matrix.
        # [s_xx s_xy s_x] [D]   [-s_xz]
        # [s_xy s_yy s_y] [E] = [-s_yz]
        # [s_x  s_y  n  ] [F]   [-s_z ]
        a11, a12, a13 = s_xx, s_xy, s_x
        a21, a22, a23 = s_xy, s_yy, s_y
        a31, a32, a33 = s_x, s_y, float(n)
        b1, b2, b3 = -s_xz, -s_yz, -s_z

        def det3(m11, m12, m13, m21, m22, m23, m31, m32, m33):
            return (
                m11 * (m22 * m33 - m23 * m32)
                - m12 * (m21 * m33 - m23 * m31)
                + m13 * (m21 * m32 - m22 * m31)
            )

        det_a = det3(a11, a12, a13, a21, a22, a23, a31, a32, a33)
        if abs(det_a) > 1e-9:
            d = det3(b1, a12, a13, b2, a22, a23, b3, a32, a33) / det_a
            e = det3(a11, b1, a13, a21, b2, a23, a31, b3, a33) / det_a
            f = det3(a11, a12, b1, a21, a22, b2, a31, a32, b3) / det_a
            cx = -d / 2.0
            cy = -e / 2.0
            # Sanity: center must stay near the image middle.
            if abs(cx - gcx) > max_r * 0.35 or abs(cy - gcy) > max_r * 0.35:
                cx, cy = gcx, gcy

    # Hole = first r where circumference is mostly opaque (main ring starts).
    limit = int(min(cx, cy, w - 1 - cx, h - 1 - cy))
    hole = float(max(8, int(max_r * 0.35)))
    for r in range(4, max(5, limit - 2)):
        if _circ_frac(px, w, h, cx, cy, r) >= 0.50:
            hole = float(r)
            break
    else:
        hits = _ray_hits(px, w, h, cx, cy)
        if hits:
            hole = max(1.0, _pct(hits, _HOLE_PERCENTILE))

    return float(cx), float(cy), max(1.0, hole)


def _ring_inner_radius(im: "Image.Image") -> int | None:
    """Hole radius about the detected (or geometric) center — for reporting."""
    _cx, _cy, r = _find_hole(im)
    return max(1, int(round(r)))


def _opaque_extents(
    im: "Image.Image", hcx: float, hcy: float, alpha: int = _HOLE_ALPHA
) -> tuple[float, float]:
    """Max |Δx|, |Δy| of opaque pixels from hole center (for fit scale)."""
    im = im.convert("RGBA")
    w, h = im.size
    px = im.load()
    max_dx = 1.0
    max_dy = 1.0
    for y in range(h):
        for x in range(w):
            if px[x, y][3] > alpha:
                max_dx = max(max_dx, abs(x - hcx))
                max_dy = max(max_dy, abs(y - hcy))
    return max_dx, max_dy


def stage_ui_ring(
    src: Path, dst: Path, canvas: int = CANVAS, catalog_id: str | None = None
) -> dict:
    """Place a UI ring on the standard 148 canvas.

    Default path (no override): detect ring center/hole, scale so hole≈r51
    when ornaments fit, else contain; paste hole-centered. Face stays 112.

    With `src_avatar` override (guide): ground-truth face plate on the source
    PNG. Scale the whole asset onto 148 and record the mapped face_box so the
    site draws the avatar into that plate (not the profile 112 box).
    """
    if Image is None:
        shutil.copy2(src, dst)
        return {"mode": "copy", "hole": REF_HOLE_R, "canvas": canvas,
                "w": canvas, "h": canvas}

    im = Image.open(src).convert("RGBA")
    w, h = im.size
    if w < 1 or h < 1:
        shutil.copy2(src, dst)
        return {"mode": "copy", "hole": REF_HOLE_R, "canvas": canvas,
                "w": canvas, "h": canvas}

    ov = _UI_OVERRIDES.get(catalog_id or "", {})

    # --- Ground-truth plate: keep native pixels, record face rect in source --
    if ov.get("native") or ov.get("face_center"):
        # Bit-exact copy so red-plate coordinates stay valid.
        if src.suffix.lower() == ".png":
            shutil.copy2(src, dst)
        else:
            im.save(dst, "PNG")
        with Image.open(dst) as staged:
            sw, sh = staged.size
        fcx, fcy = ov.get("face_center") or (sw / 2.0, sh / 2.0)
        face_box = int(ov.get("face_box") or DEFAULT_FACE_BOX)
        info = {
            "mode": "native_plate",
            "hole": max(1, face_box // 2),
            "scale": 1.0,
            "canvas": max(sw, sh),
            "w": sw,
            "h": sh,
            "face_box": face_box,
            "face_cx": float(fcx),
            "face_cy": float(fcy),
        }
        return info

    if ov.get("src_avatar"):
        ax, ay, aw, ah = (int(v) for v in ov["src_avatar"])
        usable = canvas - 2 * _EDGE_PAD
        scale = min(usable / w, usable / h)
        nw = max(1, int(round(w * scale)))
        nh = max(1, int(round(h * scale)))
        resized = im.resize((nw, nh), Image.Resampling.LANCZOS)
        acx = ax + aw / 2.0
        acy = ay + ah / 2.0
        sh_acx = acx * (nw / w)
        sh_acy = acy * (nh / h)
        out = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
        paste_x = int(round(canvas / 2.0 - sh_acx))
        paste_y = int(round(canvas / 2.0 - sh_acy))
        out.paste(resized, (paste_x, paste_y), resized)
        out.save(dst, "PNG")
        face_box = int(round(min(aw, ah) * scale))
        info = {
            "mode": "src_avatar",
            "hole": max(1, face_box // 2),
            "scale": round(scale, 4),
            "canvas": canvas,
            "w": canvas,
            "h": canvas,
            "face_box": face_box,
            "face_cx": float(canvas) / 2.0,
            "face_cy": float(canvas) / 2.0,
            "src_avatar": (ax, ay, aw, ah),
        }
        return info

    # --- Default: detect hole + scale to profile face layout ---------------
    hcx, hcy, hole0 = _find_hole(im)
    half = (canvas - 2 * _EDGE_PAD) / 2.0
    max_dx, max_dy = _opaque_extents(im, hcx, hcy)
    s_fit = min(half / max_dx, half / max_dy)
    s_fit = max(s_fit, 1e-6)

    target_hole = float(ov.get("target_hole", REF_HOLE_R))
    mode = "contain"
    scale = s_fit
    if hole0 > 0:
        s_hole = target_hole / hole0
        if ov.get("target_hole") is not None or s_hole <= s_fit + 1e-6:
            scale = s_hole
            mode = "hole" if ov.get("target_hole") is None else "hole_forced"

    nw = max(1, int(round(w * scale)))
    nh = max(1, int(round(h * scale)))
    resized = im.resize((nw, nh), Image.Resampling.LANCZOS)
    shcx = hcx * (nw / w)
    shcy = hcy * (nh / h)

    target = canvas / 2.0
    out = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    paste_x = int(round(target - shcx))
    paste_y = int(round(target - shcy))
    out.paste(resized, (paste_x, paste_y), resized)
    out.save(dst, "PNG")

    rcx, rcy, hole = _find_hole(out)
    info = {
        "mode": mode,
        "hole": int(round(hole)),
        "scale": round(scale, 4),
        "canvas": canvas,
        "w": canvas,
        "h": canvas,
        "src_hole_xy": (round(hcx, 1), round(hcy, 1)),
        "out_hole_xy": (round(rcx, 1), round(rcy, 1)),
        "face_box": DEFAULT_FACE_BOX,  # profile layout
    }
    if "mask_r" in ov:
        info["mask_r"] = int(ov["mask_r"])
    return info


def collect_sources(border_src: Path) -> list[tuple[Path, str]]:
    """Return (src_path, catalog_id) pairs. Profile borders first, then extras."""
    out: list[tuple[Path, str]] = []
    seen: set[str] = set()

    def add(p: Path, catalog_id: str) -> None:
        if not p.is_file() or p.suffix.lower() != ".png":
            return
        if catalog_id in seen:
            return
        seen.add(catalog_id)
        out.append((p, catalog_id))

    if border_src.is_dir():
        for p in sorted(border_src.glob("*.png"), key=lambda x: x.name.lower()):
            add(p, p.stem)

    # Battle-UI hero rings (ally / enemy / guide / …) — community request.
    img_dir = IMG_DIR / "img"
    if img_dir.is_dir():
        for p in sorted(img_dir.glob("*hero_s_frame*.png"), key=lambda x: x.name.lower()):
            add(p, p.stem.lstrip("_"))

    # Older device / legacy circular frames.
    legacy_dir = IMG_DIR / "legacy"
    if legacy_dir.is_dir():
        for p in sorted(legacy_dir.glob("legacy_frame_*.png"), key=lambda x: x.name.lower()):
            add(p, p.stem)

    return out


def is_official_border(src: Path) -> bool:
    """True only for the game's 148×148 item/border profile frames."""
    if src.parent.name != "border":
        return False
    if Image is None:
        return True
    with Image.open(src) as im:
        return im.size == (CANVAS, CANVAS)


def stage_one(src: Path, catalog_id: str, force: bool = False) -> tuple[Path, bool, dict] | None:
    """Write ASSET_OUT/<id>.png. Returns (dest, wrote, info) or None."""
    dst = ASSET_OUT / f"{catalog_id}.png"
    try:
        official = is_official_border(src)
        need = (
            force
            or not dst.exists()
            or dst.stat().st_mtime < src.stat().st_mtime
            or dst.stat().st_size == 0
        )
        info: dict = {"mode": "official", "hole": REF_HOLE_R, "canvas": CANVAS,
                      "w": CANVAS, "h": CANVAS}
        if need:
            if official:
                # Bit-exact — never re-encode official profile borders.
                shutil.copy2(src, dst)
            else:
                info = stage_ui_ring(src, dst, catalog_id=catalog_id)
        elif not official and Image is not None and dst.exists():
            with Image.open(dst) as im:
                h = _ring_inner_radius(im)
                info = {
                    "mode": "cached",
                    "hole": h or REF_HOLE_R,
                    "canvas": max(im.size),
                    "w": im.size[0],
                    "h": im.size[1],
                    "face_box": DEFAULT_FACE_BOX,
                }
                ov = _UI_OVERRIDES.get(catalog_id, {})
                if "mask_r" in ov:
                    info["mask_r"] = int(ov["mask_r"])
                if ov.get("native") or ov.get("face_center"):
                    info["mode"] = "cached_native"
                    info["face_box"] = int(ov.get("face_box") or DEFAULT_FACE_BOX)
                    info["hole"] = max(1, info["face_box"] // 2)
                    info["w"], info["h"] = im.size
                    info["canvas"] = max(im.size)
                    fcx, fcy = ov.get("face_center") or (im.size[0] / 2, im.size[1] / 2)
                    info["face_cx"] = float(fcx)
                    info["face_cy"] = float(fcy)
                elif ov.get("src_avatar") and src.is_file():
                    with Image.open(src) as sim:
                        sw, sh = sim.size
                    ax, ay, aw, ah = (int(v) for v in ov["src_avatar"])
                    usable = CANVAS - 2 * _EDGE_PAD
                    sc = min(usable / sw, usable / sh) if sw and sh else 1.0
                    info["face_box"] = int(round(min(aw, ah) * sc))
                    info["hole"] = max(1, info["face_box"] // 2)
                    info["mode"] = "cached_src_avatar"
                    info["face_cx"] = float(CANVAS) / 2.0
                    info["face_cy"] = float(CANVAS) / 2.0
        return dst, need, info
    except OSError as e:
        print(f"  skip {src.name}: {e}")
        return None


def build(src: Path, force_ui: bool = True) -> dict:
    pairs = collect_sources(src)
    if not pairs:
        raise SystemExit(f"no frame PNGs found (border src={src})")

    ASSET_OUT.mkdir(parents=True, exist_ok=True)
    frames: list[dict] = []
    wrote = 0
    ui_report: list[str] = []
    for p, fid in pairs:
        # Re-stage UI/legacy when the normalizer changes; never force-touch
        # official borders (mtime copy only when source is newer).
        official = is_official_border(p)
        force = force_ui and not official
        staged = stage_one(p, fid, force=force)
        if staged is None:
            continue
        dst, did_write, info = staged
        if did_write:
            wrote += 1
        cat = categorize(fid)
        entry: dict = {
            "id": fid,
            "file": dst.name,
            "path": f"assets/_frames/{dst.name}",
            "label": pretty_label(fid),
            "category": cat,
        }
        # UI-only extras for the compositor.
        if cat == "ui":
            entry["fit"] = "ui"
            entry["hole"] = int(info.get("hole") or REF_HOLE_R)
            fb = info.get("face_box")
            if fb is not None and int(fb) != DEFAULT_FACE_BOX:
                entry["face_box"] = int(fb)
            # Non-square / off-center plates (guide is 160 with face at 79,78).
            if info.get("w") and int(info["w"]) != CANVAS:
                entry["size"] = int(info["w"])
            if info.get("face_cx") is not None:
                entry["face_cx"] = float(info["face_cx"])
            if info.get("face_cy") is not None:
                entry["face_cy"] = float(info["face_cy"])
            if info.get("mask_r") is not None:
                entry["mask_r"] = int(info["mask_r"])
        frames.append(entry)
        if cat == "ui":
            ui_report.append(
                f"  ui {fid:28} mode={info.get('mode')} "
                f"face_box={info.get('face_box')} size={info.get('w')} "
                f"face_c=({info.get('face_cx')},{info.get('face_cy')})"
            )

    DATA_OUT.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 15,
        "note": "Official: 148/112 RE layout, bit-exact. UI rings on 148 except "
                "guide: native 160 + face_box=96 at painted plate center (79,78). "
                "Site circle-masks UI faces.",
        "canvas": CANVAS,
        "face_box": DEFAULT_FACE_BOX,
        "ref_hole": REF_HOLE_R,
        "count": len(frames),
        "frames": frames,
    }
    DATA_OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n",
                        encoding="utf-8")
    cats: dict[str, int] = {}
    for f in frames:
        cats[f["category"]] = cats.get(f["category"], 0) + 1
    print(f"[frames] {len(frames)} borders → {DATA_OUT.relative_to(REPO)}")
    print(f"[frames] wrote/updated {wrote} under {ASSET_OUT.relative_to(REPO)}")
    print(f"[frames] categories: {', '.join(f'{k}={v}' for k, v in sorted(cats.items()))}")
    for line in ui_report:
        print(line)
    return payload


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--src", type=Path, default=None,
                    help="border PNG folder (default: <img_dir>/item/border)")
    ap.add_argument("--no-force-ui", action="store_true",
                    help="skip forced re-stage of UI/legacy rings")
    args = ap.parse_args()
    src = args.src or (IMG_DIR / "item" / "border")
    build(src, force_ui=not args.no_force_ui)


if __name__ == "__main__":
    main()
