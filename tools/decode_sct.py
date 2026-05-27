"""
E7 .sct texture → PNG.

Standalone port of EpicSevenAssetRipper/app/hooks/before_write/sct.py.
Handles both formats found in the dump:
  - Legacy SCT  (signature 'SCT\\x01', LZ4 + RGBA32 or RGB565+A)
  - SCT2        (signature 'SCT\\x32', LZ4 + ASTC 4x4 / 6x6 / 8x8 or ETC2A8)

Usage:
  python decode_sct.py <input.sct> <output.png>
  python decode_sct.py --batch <src_dir> <dst_dir>   # decode every .sct in src_dir
"""
from __future__ import annotations
import argparse, struct, sys
from pathlib import Path
import lz4.block
from PIL import Image

def _decode_legacy(data: bytes) -> Image.Image:
    byte_format = data[4]
    width  = struct.unpack("<H", data[5:7])[0]
    height = struct.unpack("<H", data[7:9])[0]
    uncomp = struct.unpack("<I", data[9:13])[0]
    comp   = struct.unpack("<I", data[13:17])[0]
    raw = lz4.block.decompress(data[17:17+comp], uncompressed_size=uncomp)
    if byte_format == 2:
        return Image.frombytes("RGBA", (width, height), raw, "raw", "RGBA")
    if byte_format == 4:
        rgb = Image.frombytes("RGB", (width, height), raw, "raw", "BGR;16", 0, 1)
        rgb.putalpha(Image.frombytes("L", (width, height), raw[-width*height:]))
        return rgb
    if byte_format == 102:  # single-channel grayscale
        return Image.frombytes("L", (width, height), raw)
    raise ValueError(f"unsupported legacy SCT byte_format={byte_format}")

def _decode_sct2(data: bytes) -> Image.Image:
    import texture2ddecoder
    dataLen = struct.unpack("<I", data[4:8])[0]
    offset       = struct.unpack("<I", data[12:16])[0]
    byte_format  = struct.unpack("<I", data[20:24])[0]   # 19 ETC2A8 · 40 ASTC4x4 · 44 ASTC6x6 · 47 ASTC8x8
    width        = struct.unpack("<H", data[24:26])[0]
    height       = struct.unpack("<H", data[26:28])[0]
    uncomp = struct.unpack("<I", data[offset    :offset+ 4])[0]
    comp   = struct.unpack("<I", data[offset+ 4 :offset+ 8])[0]
    blob = data[offset+8 : offset+8+comp]
    payload = lz4.block.decompress(blob, uncompressed_size=uncomp) if comp == dataLen - 80 else blob
    if byte_format == 19:   raw = texture2ddecoder.decode_etc2a8(payload, width, height)
    elif byte_format == 40: raw = texture2ddecoder.decode_astc(payload, width, height, 4, 4)
    elif byte_format == 44: raw = texture2ddecoder.decode_astc(payload, width, height, 6, 6)
    elif byte_format == 47: raw = texture2ddecoder.decode_astc(payload, width, height, 8, 8)
    else: raise ValueError(f"unsupported SCT2 byte_format={byte_format}")
    return Image.frombytes("RGBA", (width, height), raw, "raw", "BGRA")

def decode_sct(sct_path: Path) -> Image.Image:
    data = sct_path.read_bytes()
    if data[:3] != b"SCT":
        raise ValueError(f"not an SCT file: {sct_path}")
    return _decode_sct2(data) if data[3:4] == b"\x32" else _decode_legacy(data)

def decode_one(src: Path, dst: Path) -> tuple[int, int]:
    img = decode_sct(src)
    dst.parent.mkdir(parents=True, exist_ok=True)
    img.save(dst)
    return img.size

def main():
    ap = argparse.ArgumentParser(description="decode E7 .sct → .png")
    ap.add_argument("--batch", action="store_true")
    ap.add_argument("src"); ap.add_argument("dst")
    a = ap.parse_args()
    src, dst = Path(a.src), Path(a.dst)
    if a.batch:
        n = ok = 0
        for sct in sorted(src.glob("*.sct")):
            n += 1
            try:
                decode_one(sct, dst / (sct.stem + ".png"))
                ok += 1
            except Exception as e:
                print(f"[fail] {sct.name}: {e}", file=sys.stderr)
        print(f"[batch] {ok}/{n} ok")
    else:
        w, h = decode_one(src, dst)
        print(f"[ok] {src.name} -> {dst.name} {w}x{h}")

if __name__ == "__main__":
    main()
