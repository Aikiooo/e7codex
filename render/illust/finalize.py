"""Copy the baked idle + reaction WebMs into site/assets/<slug>/ and extract a
poster JPG (mid-action frame) for each reaction. build_index picks them up:
  intimacy.webm            -> the looping idle illustration (main video)
  intimacy_<label>.webm    -> a reaction clip (poster = intimacy_<label>.jpg)
Usage: python finalize.py <slug> <idle.webm> <label>=<reaction.webm> ...
"""
import sys, shutil, subprocess, json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRATCH = Path(__file__).resolve().parent
ASSETS = REPO / "site" / "assets"


def poster(webm: Path, out_jpg: Path):
    # mid-clip frame as the poster (the neutral first frame looks like the idle)
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                "-of", "csv=p=0", str(webm)], capture_output=True, text=True).stdout.strip() or "3")
    subprocess.run(["ffmpeg", "-y", "-ss", f"{dur*0.55:.2f}", "-i", str(webm),
                    "-vframes", "1", "-q:v", "3", str(out_jpg)],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main():
    slug = sys.argv[1]
    idle = SCRATCH / sys.argv[2]
    dst = ASSETS / slug
    dst.mkdir(parents=True, exist_ok=True)
    shutil.copy(idle, dst / "intimacy.webm")
    print(f"[idle] {idle.name} -> {slug}/intimacy.webm")
    for spec in sys.argv[3:]:
        label, src = spec.split("=", 1)
        srcp = SCRATCH / src
        out = dst / f"intimacy_{label}.webm"
        shutil.copy(srcp, out)
        poster(out, dst / f"intimacy_{label}.jpg")
        print(f"[react] {src} -> {slug}/intimacy_{label}.webm (+poster)")


if __name__ == "__main__":
    main()
