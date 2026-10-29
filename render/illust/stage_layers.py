"""Stage intimacy effect layers into render/illust/<base>/ : .scsp->json, copy
.atlas, decode .sct->png. Usage: python stage_layers.py <base_dir> <stem1> <stem2> ...

Auto-premultiply: spine-player renders these rigs with premultipliedAlpha=true, but
E7's atlases are mixed — the character-art pages decode ALREADY premultiplied, while
the FX pages (glow/ray/bg) decode straight-alpha. A straight page rendered pma=true
shows hard square boundaries on its additive quads; premultiplying it fixes that.
Premultiplying an already-premultiplied page instead darkens the art's anti-aliased
edges (black outlines). So we DETECT each page (a premultiplied page has RGB==0
wherever alpha==0; a straight page has leftover RGB in fully-transparent pixels) and
premultiply only the straight ones. Idempotent — re-running never double-applies."""
import sys, shutil, subprocess
from pathlib import Path
from PIL import Image
from PIL import ImageChops

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from e7lib.config import RAW_DIR
EFFECT = RAW_DIR / "effect"
SCRATCH = Path(__file__).resolve().parent

def rewrite_atlas(src: Path, dst: Path) -> str:
    """Copy atlas, rewriting the texture-page line from `<name>.sct` to `<name>.png`
    (spine-player needs a decoded PNG, not the raw .sct). Returns the png page name."""
    lines = src.read_text(encoding="utf-8", errors="ignore").splitlines()
    png = None
    for i, line in enumerate(lines):
        s = line.strip()
        if s.endswith(".sct"):
            png = s[:-4] + ".png"
            lines[i] = line.replace(s, png)
            break
        if s.endswith(".png"):
            png = s
            break
    if png is None:
        png = src.stem + ".png"
    dst.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return png

def is_straight_alpha(im: Image.Image) -> bool:
    """True if the page is straight-alpha and needs premultiplying. The robust
    discriminator: a premultiplied page has RGB <= alpha for EVERY pixel (since
    RGB = origRGB*alpha <= alpha); a straight page has many pixels where a colour
    channel exceeds alpha (bright colour at low alpha — exactly the additive-glow
    quad edges that show square boundaries under pma=true). Count those pixels."""
    im = im.convert("RGBA")
    r, g, b, a = im.split()
    maxrgb = ImageChops.lighter(ImageChops.lighter(r, g), b)
    excess = ImageChops.subtract(maxrgb, a, scale=1, offset=0)  # max(0, maxrgb-alpha)
    over = excess.point(lambda v: 255 if v > 8 else 0)
    hist = over.histogram()
    n_over = hist[-1] if len(hist) >= 256 else 0
    return n_over > 0.002 * (im.width * im.height)

def premultiply(path: Path):
    im = Image.open(path).convert("RGBA")
    r, g, b, a = im.split()
    r = ImageChops.multiply(r, a); g = ImageChops.multiply(g, a); b = ImageChops.multiply(b, a)
    Image.merge("RGBA", (r, g, b, a)).save(path)

def main():
    base = sys.argv[1]
    stems = sys.argv[2:]
    out = SCRATCH / base
    out.mkdir(parents=True, exist_ok=True)
    for stem in stems:
        scsp = EFFECT / f"{stem}.scsp"
        atlas = EFFECT / f"{stem}.atlas"
        sct = EFFECT / f"{stem}.sct"
        if not scsp.exists():
            print(f"[skip] {stem}: no .scsp"); continue
        r = subprocess.run([sys.executable, str(REPO / "convert" / "scsp_to_json.py"),
                            str(scsp), str(out / f"{stem}.json")])
        if r.returncode != 0:
            print(f"[FAIL] {stem}: scsp->json failed"); continue
        pg = rewrite_atlas(atlas, out / f"{stem}.atlas")
        subprocess.run([sys.executable, str(REPO / "convert" / "decode_sct.py"),
                        str(sct), str(out / pg)])
        pngpath = out / pg
        straight = is_straight_alpha(Image.open(pngpath))
        if straight:
            premultiply(pngpath)
        print(f"[ok] {stem} (page {pg}) {'[premultiplied: straight-alpha FX]' if straight else '[left as-is: already premultiplied]'}")

if __name__ == "__main__":
    main()
