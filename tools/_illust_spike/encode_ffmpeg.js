/**
 * Shared FFmpeg encode args for illust/lobby PNG→WebM bakes.
 *
 * Env:
 *   E7_ENCODER=vp9|av1_amf|amf   (default vp9)
 *   E7_VP9_CPU_USED=0..5         (default 2; libvpx default 0 is ~3–5× slower)
 *   E7_VP9_DEADLINE=good|realtime|best  (default good)
 *
 * VP9 remains the shipping default (browser + Pages). av1_amf is a fast AMD
 * hardware path for local previews when quality/compat tradeoffs are OK.
 */
const os = require("os");

function encodeArgs(fps, crf, inputPattern, outPath) {
  const enc = (process.env.E7_ENCODER || "vp9").toLowerCase();
  const threads = String(os.cpus().length || 4);

  if (enc === "av1_amf" || enc === "amf") {
    // AMD AMF AV1 — much faster wall time; quality ≠ libvpx CRF scale.
    // qp 20–28 is a reasonable preview range; map crf roughly.
    const qp = String(Math.min(40, Math.max(10, parseInt(crf, 10) || 20)));
    return [
      "-y",
      "-framerate",
      String(fps),
      "-i",
      inputPattern,
      "-c:v",
      "av1_amf",
      "-rc",
      "cqp",
      "-qp_i",
      qp,
      "-qp_p",
      qp,
      "-pix_fmt",
      "yuv420p",
      "-an",
      outPath,
    ];
  }

  // libvpx-vp9 (default). cpu-used 2 is the easy free win vs implicit 0.
  const cpuUsed = process.env.E7_VP9_CPU_USED || "2";
  const deadline = process.env.E7_VP9_DEADLINE || "good";
  return [
    "-y",
    "-framerate",
    String(fps),
    "-i",
    inputPattern,
    "-c:v",
    "libvpx-vp9",
    "-pix_fmt",
    "yuv420p",
    "-crf",
    String(crf),
    "-b:v",
    "0",
    "-row-mt",
    "1",
    "-tiles",
    "2x2",
    "-threads",
    threads,
    "-cpu-used",
    String(cpuUsed),
    "-deadline",
    deadline,
    "-an",
    outPath,
  ];
}

function encodeLabel() {
  const enc = (process.env.E7_ENCODER || "vp9").toLowerCase();
  if (enc === "av1_amf" || enc === "amf") return "av1_amf";
  return `libvpx-vp9 cpu-used=${process.env.E7_VP9_CPU_USED || "2"}`;
}

module.exports = { encodeArgs, encodeLabel };
