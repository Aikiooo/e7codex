"""
Minimal E7 SCSP header parser.
Extracts LZ4-compressed Spine binary from E7's custom .scsp format.

Input: .scsp file
Output: Decompressed Spine binary (ready for Spine library)
"""

import os
import sys
import struct
import mmap
import platform
import lz4.block


def decompress_scsp(scsp_file_path):
    """
    Decompress an E7 .scsp file.
    
    E7 .scsp format:
    - 4 bytes: decompressed size (little-endian uint32)
    - 4 bytes: compressed size (little-endian uint32)
    - N bytes: LZ4-compressed data
    
    Returns:
    - bytes: Decompressed Spine binary data
    """
    file_size = os.path.getsize(scsp_file_path)
    
    # Open file with memory mapping
    if platform.system() == 'Windows':
        mfd = os.open(scsp_file_path, os.O_RDONLY | os.O_BINARY)
        mfile = mmap.mmap(mfd, 0, access=mmap.ACCESS_READ)
    else:
        mfd = os.open(scsp_file_path, os.O_RDONLY)
        mfile = mmap.mmap(mfd, 0, prot=mmap.PROT_READ)
    
    try:
        # Read header
        header = mfile.read(8)
        if len(header) < 8:
            raise ValueError(f"Invalid SCSP file: header too short ({len(header)} bytes)")
        
        decompressed_length = struct.unpack("@I", header[0:4])[0]
        compressed_length = struct.unpack("@I", header[4:8])[0]
        
        print(f"[SCSP] Decompressed size: {decompressed_length} bytes")
        print(f"[SCSP] Compressed size: {compressed_length} bytes")
        
        # Read compressed data
        compressed_data = mfile.read(compressed_length)
        if len(compressed_data) < compressed_length:
            raise ValueError(f"Incomplete compressed data: expected {compressed_length}, got {len(compressed_data)}")
        
        # Decompress using LZ4
        print(f"[SCSP] Decompressing LZ4 data...")
        decompressed_data = lz4.block.decompress(
            compressed_data,
            uncompressed_size=decompressed_length
        )
        
        print(f"[SCSP] Successfully decompressed {len(decompressed_data)} bytes")
        return decompressed_data
        
    finally:
        mfile.close()
        os.close(mfd)


def extract_spine_binary(scsp_file_path, output_file_path=None):
    """
    Extract Spine binary from .scsp and save to file.
    
    Args:
        scsp_file_path: Path to .scsp file
        output_file_path: Where to save decompressed binary (optional)
                         If None, uses <scsp_name>.spine
    
    Returns:
        bytes: Decompressed Spine binary
    """
    print(f"\n[Parser] Reading: {scsp_file_path}")
    
    # Decompress
    spine_binary = decompress_scsp(scsp_file_path)
    
    # Determine output path
    if output_file_path is None:
        output_file_path = scsp_file_path + ".spine"
    
    # Save binary
    with open(output_file_path, 'wb') as f:
        f.write(spine_binary)
    
    print(f"[Parser] Written: {output_file_path}")
    return spine_binary


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python e7_scsp_parser.py <.scsp file> [output file]")
        print("Example: python e7_scsp_parser.py c1113.scsp c1113.spine")
        sys.exit(1)
    
    scsp_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else None
    
    try:
        extract_spine_binary(scsp_file, output_file)
    except Exception as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)
