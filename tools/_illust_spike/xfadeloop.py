#!/usr/bin/env python
# Build a seamless loop from a body frame-dir + a continuation tail frame-dir.
# The seam (last body frame -> first output frame) is between consecutive real
# frames, so it's continuous; the first X output frames crossfade the tail
# (continuation) into the true head. When the loop length is an exact multiple
# of the CHARACTER period, the character is identical across the blend, so only
# the non-periodic ambient layers blend (no character ghosting).
# Usage: xfadeloop.py <bodyDir> <tailDir> <out.webm> <fps> <crf> [glob]
import sys, os, glob, subprocess
import numpy as np
from PIL import Image

bodyDir, tailDir, out, fpsA, crfA = sys.argv[1:6]
fps, crf = int(fpsA), int(crfA)
body = sorted(glob.glob(os.path.join(bodyDir, "*.png")))
tail = sorted(glob.glob(os.path.join(tailDir, "*.png")))
N, X = len(body), len(tail)
od = out + "_frames"
os.makedirs(od, exist_ok=True)
print(f"body {N}  tail(crossfade) {X}")
for i in range(N):
    if i < X:
        a = i / X
        f = np.asarray(Image.open(body[i]).convert("RGB"), dtype=np.float32)
        t = np.asarray(Image.open(tail[i]).convert("RGB"), dtype=np.float32)
        Image.fromarray(((1 - a) * t + a * f).clip(0, 255).astype(np.uint8)).save(od + "/o%05d.png" % i)
    else:
        Image.open(body[i]).save(od + "/o%05d.png" % i)
print("encoding", N, "frames ->", out)
# Match bake.js defaults: VP9 with cpu-used=2 (or E7_ENCODER=av1_amf).
enc = (os.environ.get("E7_ENCODER") or "vp9").lower()
cpu_used = os.environ.get("E7_VP9_CPU_USED") or "2"
threads = str(os.cpu_count() or 8)
if enc in ("av1_amf", "amf"):
    qp = str(min(40, max(10, int(crf))))
    ff = ["ffmpeg", "-v", "error", "-y", "-framerate", str(fps), "-i", od + "/o%05d.png",
          "-c:v", "av1_amf", "-rc", "cqp", "-qp_i", qp, "-qp_p", qp,
          "-pix_fmt", "yuv420p", "-an", out]
else:
    ff = ["ffmpeg", "-v", "error", "-y", "-framerate", str(fps), "-i", od + "/o%05d.png",
          "-c:v", "libvpx-vp9", "-crf", str(crf), "-b:v", "0", "-pix_fmt", "yuv420p",
          "-row-mt", "1", "-tiles", "2x2", "-threads", threads,
          "-cpu-used", cpu_used, "-deadline", "good", "-an", out]
subprocess.run(ff, check=True)
print("wrote", out, os.path.getsize(out) // 1024, "KB")
