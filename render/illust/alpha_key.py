"""Alpha-key the additive-blend FX sprites of a staged layer: set alpha = perceptual
luminance over each additive slot's atlas region, so the opaque-black background of
an "additive on black" flare/glow texture becomes transparent. Without this, those
sprites render their black square boundary (spine-player isn't applying pure additive
blend here). NORMAL-blend regions (the orb body `fx_b`, petals, character art) are
left untouched. Idempotent-ish (re-keying a keyed region is a no-op).

Usage: python alpha_key.py <base> <stem1> <stem2> ...
"""
import sys, json, re
from pathlib import Path
from PIL import Image

SCRATCH = Path(__file__).resolve().parent


def parse_atlas(path: Path):
    """-> {region_name: {xy:(x,y), size:(w,h), rotate:bool}}"""
    regions, name, cur = {}, None, None
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if not line.strip():
            continue
        if line.endswith(".png") or line.startswith("size:") or line.startswith("format:") \
                or line.startswith("filter:") or line.startswith("repeat:") or line.startswith("pma:"):
            continue
        if not line.startswith(" ") and ":" not in line:
            name = line.strip(); cur = {}; regions[name] = cur
        elif ":" in line and cur is not None:
            k, v = line.split(":", 1)
            cur[k.strip()] = v.strip()
    out = {}
    for n, r in regions.items():
        if "xy" not in r or "size" not in r:
            continue
        x, y = [int(t) for t in r["xy"].split(",")]
        w, h = [int(t) for t in r["size"].split(",")]
        rot = r.get("rotate", "false") == "true"
        out[n] = {"x": x, "y": y, "w": w, "h": h, "rot": rot}
    return out


def alpha_key_region(im: Image.Image, x, y, w, h):
    box = (x, y, x + w, y + h)
    crop = im.crop(box).convert("RGBA")
    px = crop.load()
    cw, ch = crop.size
    for j in range(ch):
        for i in range(cw):
            r, g, b, a = px[i, j]
            lum = int(0.299 * r + 0.587 * g + 0.114 * b)
            if lum < a:                      # only ever reduce alpha (black -> transparent)
                px[i, j] = (r, g, b, lum)
    im.paste(crop, box)


def main():
    base = sys.argv[1]
    stems = sys.argv[2:]
    d = SCRATCH / base
    for stem in stems:
        jf = d / f"{stem}.json"
        af = d / f"{stem}.atlas"
        pf = d / f"{stem}.png"
        if not jf.exists():
            print(f"[skip] {stem}: not staged"); continue
        data = json.loads(jf.read_text(encoding="utf-8"))
        additive_slots = {s["name"] for s in data.get("slots", []) if s.get("blend") == "additive"}
        # Resolve the atlas REGIONS those additive slots actually draw: each slot's
        # attachments live in the skin and reference a region via `path` (falling
        # back to the attachment name). Keying by slot name alone misses most.
        skins = data.get("skins", [])
        skl = ({s["name"]: s.get("attachments", {}) for s in skins}
               if isinstance(skins, list) else skins)
        additive = set()
        for atts in skl.values():
            for slot, attmap in atts.items():
                if slot in additive_slots:
                    for attname, att in attmap.items():
                        additive.add(att.get("path", attname))
        regions = parse_atlas(af)
        im = Image.open(pf).convert("RGBA")
        n = 0
        for rname, r in regions.items():
            if rname not in additive:
                continue
            pw, ph = (r["h"], r["w"]) if r["rot"] else (r["w"], r["h"])   # stored rect
            alpha_key_region(im, r["x"], r["y"], pw, ph)
            n += 1
        im.save(pf)
        print(f"[ok] {stem}: alpha-keyed {n} additive regions")


if __name__ == "__main__":
    main()
