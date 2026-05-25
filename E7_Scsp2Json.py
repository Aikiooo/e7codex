#!/usr/bin/env python3
# Reference: https://github.com/EsotericSoftware/spine-runtimes/tree/3.8/spine-csharp/src
# 第七史诗 EpicSeven Convert skel 3.8.99 to json
# 半成品: 目前有些模型切换到 normal 这个 skin 的时候会有表情重叠
from __future__ import annotations

import base64
import json
import os
import struct
from pathlib import Path
import lz4.block
from dataclasses import dataclass, field
from collections import defaultdict
from enum import IntEnum
from typing import Any, Dict, List, Optional, Tuple, Set

# ==============================
# Config
# ==============================
INPUT_PATH = r"D:\Games\GameUnpackAssets\mymodel\Spine\EpicSeven\portrait"
OUTPUT_PATH = r"D:\Games\GameUnpackAssets\mymodel\Spine\EpicSeven\TestScsp"


IS_COMPRESS_JSON = True
ENDIAN = "<"
# ==============================
# Enums & helpers
# ==============================
class ScspVersion(IntEnum):
    V2 = 1 #2.1.27
    V3 = 30001 #3.8.99

class Inherit(IntEnum):
    Normal = 0
    OnlyTranslation = 1
    NoRotationOrReflection = 2
    NoScale = 3
    NoScaleOrReflection = 4

class BlendMode(IntEnum):
    Normal = 0
    Additive = 1
    Multiply = 2
    Screen = 3

class PositionMode(IntEnum):
    Fixed = 0
    Percent = 1


class SpacingMode(IntEnum):
    Length = 0
    Fixed = 1
    Percent = 2
    Proportional = 3


class RotateMode(IntEnum):
    Tangent = 0
    Chain = 1
    ChainScale = 2


class CurveType(IntEnum):
    LINEAR = 0
    STEPPED = 1
    BEZIER = 2


class AttachmentType(IntEnum):
    Region = 0
    Boundingbox = 1
    Mesh = 2
    Linkedmesh = 3
    Path = 4
    Point = 5
    Clipping = 6


class TimelineType(IntEnum):
    # bones
    Rotate = 0
    Translate = 1
    Scale = 2
    Shear = 3
    # slots
    Attachment = 4
    Color = 5
    TwoColor = 14
    # deform
    Deform = 6
    # events
    Event = 7
    # drawOrder
    DrawOrder = 8
    # ik
    IkConstraint = 9
    # transform
    TransformConstraint = 10
    # path
    PathConstraintPosition = 11
    PathConstraintSpacing = 12
    PathConstraintMix = 13


@dataclass
class Color:
    r: int = 0xFF
    g: int = 0xFF
    b: int = 0xFF
    a: int = 0xFF

def color_to_string(color: Color, has_alpha: bool = True) -> str:
    if has_alpha:
        return f"{color.r:02X}{color.g:02X}{color.b:02X}{color.a:02X}"
    return f"{color.r:02X}{color.g:02X}{color.b:02X}"


def uint64_to_base64(v: int) -> str:
    return base64.b64encode(struct.pack("<Q", v)).decode("ascii").rstrip("=")

def base64_to_uint64(s: str) -> int:
    # pad to valid length
    padding = "=" * ((4 - len(s) % 4) % 4)
    data = base64.b64decode(s + padding)
    return int.from_bytes(data, byteorder="little", signed=False)


# ==============================
# Data classes
# ==============================
@dataclass
class Attachment:
    name: Optional[str] = None
    path: Optional[str] = None
    type: AttachmentType = AttachmentType.Region

@dataclass
class VertexAttachment(Attachment):
    vertexCount: int = 0
    isWeighted: bool = False
    vertices: List[float] = field(default_factory=list)

@dataclass
class RegionAttachment(Attachment): 
    x: float = 0.0
    y: float = 0.0
    rotation: float = 0.0
    scaleX: float = 1.0
    scaleY: float = 1.0
    width: float = 0.0
    height: float = 0.0
    color: Optional[Color] = None

@dataclass
class MeshAttachment(VertexAttachment): 
    uvs: List[float] = field(default_factory=list)
    triangles: List[int] = field(default_factory=list)

    hullLength: int = 0
    color: Optional[Color] = None

    # Nonessential.
    edges: List[int] = field(default_factory=list)
    width: float = 0.0
    height: float = 0.0

    # 和 Attachment 中的 path 并不相同，这里的 path 是 atlas region 的名称
    # 默认值为 attachment name，如果和 attachment name 不同，则在 attachment 这一层会额外记录一个 path 字段
    path: Optional[str] = None

@dataclass
class LinkedMeshAttachment(VertexAttachment):
    skinIndex: int = 0
    parentMesh: Optional[str] = None
    deform: bool = True

    width: float = 0.0
    height: float = 0.0
    color: Optional[Color] = None


@dataclass
class BoundingBoxAttachment(VertexAttachment): 
    color: Optional[Color] = None


@dataclass
class PathAttachment(VertexAttachment): 
    color: Optional[Color] = None

    closed: bool = False
    constantSpeed: bool = False
    lengths: List[float] = field(default_factory=list)


@dataclass
class PointAttachment(Attachment): 
    rotation: float = 0.0
    x: float = 0.0
    y: float = 0.0
    color: Optional[Color] = None


@dataclass
class ClippingAttachment(VertexAttachment): 
    color: Optional[Color] = None
    endSlot: Optional[str] = None




@dataclass
class BoneData:
    name: Optional[str] = None
    parent: Optional[str] = None
    # order may be different from index in list
    rotation: float = 0.0
    x: float = 0.0
    y: float = 0.0
    scaleX: float = 1.0
    scaleY: float = 1.0
    shearX: float = 0.0
    shearY: float = 0.0
    length: float = 0.0

    inherit: Inherit = Inherit.Normal
    skinRequired: bool = False
    # optional
    color: Optional[Color] = None


@dataclass
class SlotData:
    name: Optional[str] = None
    bone: Optional[str] = None
    color: Optional[Color] = None
    darkColor: Optional[Color] = None
    attachmentName: Optional[str] = None
    blendMode: BlendMode = BlendMode.Normal


@dataclass
class IKConstraintData:
    name: Optional[str] = None
    order: int = 0
    skinRequired: bool = False
    bones: List[str] = field(default_factory=list)
    target: Optional[str] = None
    mix: float = 1.0
    softness: float = 0.0
    bendPositive: bool = True
    compress: bool = False
    stretch: bool = False
    uniform: bool = False


@dataclass
class TransformConstraintData:
    name: Optional[str] = None
    order: int = 0
    skinRequired: bool = False

    bones: List[str] = field(default_factory=list)
    target: Optional[str] = None

    local: bool = False
    relative: bool = False

    offsetRotation: float = 0.0
    offsetX: float = 0.0
    offsetY: float = 0.0
    offsetScaleX: float = 0.0
    offsetScaleY: float = 0.0
    offsetShearY: float = 0.0

    rotateMix: float = 1.0
    translateMix: float = 1.0
    scaleMix: float = 1.0
    shearMix: float = 1.0


@dataclass
class PathConstraintData:
    name: Optional[str] = None
    order: int = 0
    skinRequired: bool = False
    bones: List[str] = field(default_factory=list)
    targetSlot: Optional[str] = None
    positionMode: PositionMode = PositionMode.Percent
    spacingMode: SpacingMode = SpacingMode.Length
    rotateMode: RotateMode = RotateMode.Tangent

    offsetRotation: float = 0.0
    position: float = 0.0
    spacing: float = 0.0
    
    rotateMix: float = 1.0
    translateMix: float = 1.0


@dataclass
class SkinData:
    name: Optional[str] = None
    # slot_name -> attachment_name -> Attachment
    attachments: Dict[str, Dict[str, Attachment]] = field(default_factory=dict) 

    bones: List[str] = field(default_factory=list)
    ik: List[str] = field(default_factory=list)
    transform: List[str] = field(default_factory=list)
    paths: List[str] = field(default_factory=list)


@dataclass
class EventData:
    name: Optional[str] = None
    intValue: int = 0
    floatValue: float = 0.0
    stringValue: Optional[str] = None
    audioPath: Optional[str] = None
    volume: float = 1.0
    balance: float = 0.0


@dataclass
class TimelineData:
    type: TimelineType = TimelineType.Rotate

    # 不同 type 的frames 结构不太一样
    # https://github.com/EsotericSoftware/spine-runtimes/blob/3.8/spine-csharp/src/Animation.cs
    # 搜索 // time, 下面的注释是不同 type 的 frames 结构
    # 0 rotate: [time, angle, ...]
    # 1 translate: [time, x, y, ...]
    # 2 scale: [time, x, y, ...] 其中x, y 是 scaleX, scaleY 但是用 x y 字段表示
    # 3 shear: [time, x, y, ...] 其中x, y 是 shearX, shearY 但是用 x y 字段表示
    # 4 attachment: [time, ...]
    # 5 color : [time, r, g, b, a, ...]
    # 6 deform : [time, ...]
    # 7 event : [time, ...]
    # 8 drawOrder : [time, ...] 
    # 9 ik : [time, mix, softness, bend_direction (int), compress (bool), stretch (bool)]
    # 10 transform : [time, rotateMix, translateMix, scaleMix, shearMix, ...]
    # 11 position: [time, position, ...] 
    # 12 spacing: [time, spacing, ...] 
    # 13 mix: [time, rotateMix, translateMix, ...]
    # 14 twoColor : [time, r1, g1, b1, a1, r2, g2, b2, a2, ...]
    frames: List[float] = field(default_factory=list)

    # curves : [curveType, 9 * (x, y), ...], curveType = 0 linear, 1 stepped, 2 bezier, 前两个类型 后面的坐标都是0 可以忽略
    # attachment event drawOrder 没有 curves
    curves: List[float] = field(default_factory=list) # curves size = frame count - 1

    times: List[float] = field(default_factory=list) # 仅用于方便查询，实际数据在 frames 中

@dataclass
class RotateTimeline(TimelineData): # 0 time angle curve
    bone_index: int = 0
    angles: List[float] = field(default_factory=list)
@dataclass
class TranslateTimeline(TimelineData): # 1 time x y curve
    bone_index: int = 0
    xs: List[float] = field(default_factory=list)
    ys: List[float] = field(default_factory=list)
@dataclass
class ScaleTimeline(TimelineData): # 2 time x y curve
    bone_index: int = 0
    xs: List[float] = field(default_factory=list)
    ys: List[float] = field(default_factory=list)
@dataclass
class ShearTimeline(TimelineData): # 3 time x y curve
    bone_index: int = 0
    xs: List[float] = field(default_factory=list)
    ys: List[float] = field(default_factory=list)
@dataclass
class AttachmentTimeline(TimelineData): # 4 time name
    slot_index: int = 0
    names: List[Optional[str]] = field(default_factory=list)
@dataclass
class ColorTimeline(TimelineData): # 5 time color(string) curve
    slot_index: int = 0
    colors: List[Color] = field(default_factory=list) # r g b a 连在一起存储
@dataclass
class DeformTimeline(TimelineData): # 6 time vertices (offset) curve
    skin: Optional[str] = None
    slot_index: int = 0
    attachment: Optional[str] = None
    offsets: List[List[float]] = field(default_factory=list)
    vertices: List[List[float]] = field(default_factory=list)
@dataclass
class EventTimeline(TimelineData): # 7 time name 
    names: List[str] = field(default_factory=list)
@dataclass
class DrawOrderTimeline(TimelineData): # 8 time order
    orders: List[List[int]] = field(default_factory=list) # [SlotIndex, ... ]
@dataclass
class IKTimeline(TimelineData): # 9 time mix softness bend_direction compress stretch curve
    ik_index:int = 0
    mixs: List[float] = field(default_factory=list)
    softness: List[float] = field(default_factory=list)
    bend_directions: List[int] = field(default_factory=list)
    compresses: List[bool] = field(default_factory=list)
    stretches: List[bool] = field(default_factory=list)
@dataclass
class TransformTimeline(TimelineData): # 10 time rotateMix translateMix scaleMix shearMix curve
    transform_index: int = 0
    rotateMixs: List[float] = field(default_factory=list)
    translateMixs: List[float] = field(default_factory=list)
    scaleMixs: List[float] = field(default_factory=list)
    shearMixs: List[float] = field(default_factory=list)
@dataclass
class PathPositionTimeline(TimelineData): # 11 time position curve
    path_index: int = 0
    positions: List[float] = field(default_factory=list)
@dataclass
class PathSpacingTimeline(TimelineData): # 12 time spacing curve
    path_index: int = 0
    spacings: List[float] = field(default_factory=list)
@dataclass
class PathMixTimeline(TimelineData): # 13 time rotateMix translateMix curve
    path_index: int = 0
    rotateMixs: List[float] = field(default_factory=list)
    translateMixs: List[float] = field(default_factory=list)
@dataclass
class TwoColorTimeline(TimelineData): # 14 time light(string) dark(string)
    slot_index: int = 0
    colorLights: List[Color] = field(default_factory=list)
    colorDarks: List[Color] = field(default_factory=list)


@dataclass
class AnimationData: # animation_name -> type
    name: Optional[str] = None
    duration: float = 0.0
    timelines: List[TimelineData] = field(default_factory=list)
    # type
    slots: Dict[str, Dict[str, List[Any]]] = field(default_factory=dict) # slot_name -> timeline_type -> timeline_data
    bones: Dict[str, Dict[str, List[Any]]] = field(default_factory=dict) # bone_name -> timeline_type -> timeline_data
    ik: Dict[str, List[Any]] = field(default_factory=dict) # ik_name -> timeline_data
    transform: Dict[str, List[Any]] = field(default_factory=dict) # transform_name -> timeline_data
    path: Dict[str, Dict[str,List[Any]]] = field(default_factory=dict) # path_name -> timeline_data
    deform: Dict[str, Dict[str, Dict[str, List[Any]]]] = field(default_factory=dict) # skin_name -> slot_name ->attachment_name -> timeline_data
    drawOrder: List[Any] = field(default_factory=list) # timeline_data
    events: List[Any] = field(default_factory=list) # timeline_data


@dataclass
class SkeletonData:
    scspVersion: ScspVersion = ScspVersion.V3
    stringPool: bytes = b""

    hash: int = 0
    hashString: Optional[str] = None
    version: Optional[str] = None
    x: float = 0.0
    y: float = 0.0
    width: float = 0.0
    height: float = 0.0
    nonessential: bool = True
    fps: float = 30.0
    imagesPath: Optional[str] = None
    audioPath: Optional[str] = None
    strings: List[str] = field(default_factory=list)

    bones: List[BoneData] = field(default_factory=list)
    slots: List[SlotData] = field(default_factory=list)
    ikConstraints: List[IKConstraintData] = field(default_factory=list)
    transformConstraints: List[TransformConstraintData] = field(default_factory=list)
    pathConstraints: List[PathConstraintData] = field(default_factory=list)
    skins: List[SkinData] = field(default_factory=list)
    events: List[EventData] = field(default_factory=list)
    animations: List[AnimationData] = field(default_factory=list)


# ==============================
# Binary Reader (Spine 3.8)
# ==============================

# Basic binary reader for Spine 3.8 binary format,
# with methods to read various data types and structures.
class SpineBinaryReader:
    def __init__(self, data: bytes, endian: str = ENDIAN):
        self.data = data
        self.pos = 0
        self.endian = endian

    def _read(self, size: int) -> bytes:
        if self.pos + size > len(self.data):
            raise EOFError("Unexpected end of file")
        chunk = self.data[self.pos : self.pos + size]
        self.pos += size
        return chunk

    def reset_data(self, data: bytes, offset: int = 0) -> None:
        self.data = data
        self.pos = offset


    def reset_pos(self, pos: int = 0) -> None:
        self.pos = pos

    def read_byte(self) -> int:
        return self._read(1)[0]

    def read_bytes(self, n: int) -> bytes:
        return self._read(n)
    def read_sbyte(self) -> int:
        return struct.unpack(f"{self.endian}b", self._read(1))[0]

    def read_boolean(self) -> bool:
        return self.read_byte() != 0

    def read_u8(self) -> int:
        return struct.unpack(f"{self.endian}B", self._read(1))[0]

    def read_i16(self) -> int:
        return struct.unpack(f"{self.endian}h", self._read(2))[0]

    def read_u16(self) -> int:
        return struct.unpack(f"{self.endian}H", self._read(2))[0]

    def read_i32(self) -> int:
        return struct.unpack(f"{self.endian}i", self._read(4))[0]

    def read_u32(self) -> int:
        return struct.unpack(f"{self.endian}I", self._read(4))[0]

    def read_f32(self) -> float:
        return struct.unpack(f"{self.endian}f", self._read(4))[0]

    def read_color(self, has_alpha: bool = True) -> Color:
        r = self.read_byte()
        g = self.read_byte()
        b = self.read_byte()
        a = self.read_byte() if has_alpha else 0xFF
        return Color(r, g, b, a)
    
    def read_varint(self, optimize_positive: bool) -> int:
        result = 0
        shift = 0
        while True:
            b = self.read_byte()
            result |= (b & 0x7F) << shift
            if (b & 0x80) == 0:
                break
            shift += 7
        if not optimize_positive:
            result = (result >> 1) ^ -(result & 1)
        return result

    def read_string(self, strings: Optional[List[str]] = None) -> Optional[str]:
        length = self.read_varint(True)
        if length == 0:
            return None
        if length == 1:
            return ""
        length -= 1
        raw = self._read(length)
        s = raw.decode("utf-8", errors="replace")
        if strings is not None:
            strings.append(s)
        return s

    def read_string_ref(self, strings: List[str]) -> Optional[str]:
        index = self.read_varint(True)
        if index == 0:
            return None
        index -= 1
        if index >= len(strings):
            strings.append(self.read_string())
        return strings[index]

# ==============================
# Main reading functions
# ==============================
def get_pool_string(offset: int, sk: SkeletonData) -> Optional[str]:
    """从字符串池按偏移取 null-terminated UTF-8 字符串; 0xFFFFFFFF 表示 None"""
    string_pool = sk.stringPool
    if offset == 0xFFFFFFFF:
        return None
    if offset >= len(string_pool):
        return f'<OOB:{offset:#x}>'
    try:
        end = string_pool.index(b'\x00', offset)
    except ValueError:
        end = len(string_pool)
    return string_pool[offset:end].decode('utf-8', errors='replace')

def read_f32_array(reader: SpineBinaryReader, n: int) -> List[float]:
    return [reader.read_f32() for _ in range(n)]

def read_u8_array(reader: SpineBinaryReader, n: int) -> List[int]:
    return [reader.read_u8() for _ in range(n)]

def read_i16_array(reader: SpineBinaryReader, n: int) -> List[int]:
    return [reader.read_i16() for _ in range(n)]

def read_u16_array(reader: SpineBinaryReader, n: int) -> List[int]:
    return [reader.read_u16() for _ in range(n)]

def read_i32_array(reader: SpineBinaryReader, n: int) -> List[int]:
    return [reader.read_i32() for _ in range(n)]

def read_u32_array(reader: SpineBinaryReader, n: int) -> List[int]:
    return [reader.read_u32() for _ in range(n)]

def can_merge_weighted_vertices(vertices: List[float], bones: List[int]) -> bool:
    bpos = 0
    required_vertex_values = 0

    while bpos < len(bones):
        bone_count = bones[bpos]
        bpos += 1

        # bone_count 必须合法
        if bone_count <= 0:
            return False

        # bones 中必须有足够 bone index
        if bpos + bone_count > len(bones):
            return False

        bpos += bone_count

        # 每个 bone 对应 3 个 float (x,y,weight)
        required_vertex_values += bone_count * 3

    return required_vertex_values == len(vertices)

def merge_weighted_vertices(vertices: List[float], bones: List[int]) -> List[float]:
    """
    Merge Spine weighted vertex data.

    non-weighted vertices format:
        [x, y, x, y, ...]

    bones format:
        [boneCount, boneIndex, boneIndex, ..., boneCount, ...]

    weighted vertices format: (no bones)
        [x, y, weight, x, y, weight, ...]

    weighted versions (merged bones)
        [boneCount, boneIndex, x, y, weight, boneIndex, x, y, weight, ...]
    """
    if not can_merge_weighted_vertices(vertices, bones):
        raise ValueError("Cannot merge weighted vertices: invalid format")

    merged: List[float] = []
    bpos = 0
    vpos = 0

    while bpos < len(bones):
        bone_count = bones[bpos]
        bpos += 1

        merged.append(float(bone_count))

        for _ in range(bone_count):
            bone_index = bones[bpos]
            bpos += 1

            x = vertices[vpos]
            y = vertices[vpos + 1]
            w = vertices[vpos + 2]
            vpos += 3

            merged.extend([float(bone_index), x, y, w])

    if vpos != len(vertices):
        raise ValueError("Vertex data not fully consumed")

    return merged



#uncompressed_size 4B | compressed_size 4B|
#LZ4 compressed data:
    # data_size(uint32) 4B | string_size(uint32) 4B |
    # binary_data | (data_size) B
        # SCSP Magic 4B | Version(uint32) 4B |
        # Spine_Data (data_size - 8) B
    # string_pool | (string_size) B
def lz4_decompress(reader: SpineBinaryReader) -> None:
    uncompressed_size = reader.read_u32()
    compressed_size = reader.read_u32()

    compressed_data = reader.read_bytes(compressed_size)
    decompressed_data = lz4.block.decompress(
        compressed_data,
        uncompressed_size=uncompressed_size
    )
    reader.reset_data(decompressed_data)

def custom_data_preprocess (reader: SpineBinaryReader, skeleton: SkeletonData) -> None:
    lz4_decompress(reader)

    data_size = reader.read_u32()
    string_pool_size = reader.read_u32()

    data_start_pos = reader.pos
    magic = reader.read_bytes(4)
    version = reader.read_u32()

    if magic != b"scsp":
        raise ValueError(f"Invalid magic: {magic}")

    reader.reset_pos(data_start_pos)
    spine_data = reader.read_bytes(data_size)
    string_pool = reader.read_bytes(string_pool_size)

    reader.reset_data(spine_data)

    if version > 2:
        # print(f"Scsp Version : V3.8.99") #30001
        scsp_version = ScspVersion.V3
    else:
        # print(f"Scsp Version : V2.1.27") #1
        scsp_version = ScspVersion.V2

    skeleton.scspVersion = scsp_version
    skeleton.stringPool = string_pool

def read_skeleton_info(reader: SpineBinaryReader, skeleton: SkeletonData) -> None:
    custom_data_preprocess(reader, skeleton)

    # 枚举前 8-73 的 f32 数据 得到疑似偏移量14 width  18 height  38 fps
    # for i in range(8, 74):
    #     var = read_f32(skel_data, i)[0]
    #     print(f"  offset {i:02} = {var:.3f}")
    skeleton.x = 0.0
    skeleton.y = 0.0

    reader.reset_pos(14)
    skeleton.width = reader.read_f32()  # 14
    skeleton.height = reader.read_f32()  # 18

    reader.reset_pos(38)
    skeleton.fps = reader.read_f32()  # 38

    reader.reset_pos(74)
    hash_offset = reader.read_u32()  # 74
    ver_offset = reader.read_u32()  # 78
    skeleton.hashString = get_pool_string(hash_offset, skeleton)
    # if skeleton.hashString:
    #     skeleton.hash = base64_to_uint64(skeleton.hashString)
    skeleton.version = get_pool_string(ver_offset, skeleton)[:6] #3.8.99.scsp 取前 6 位

    reader.reset_pos(86)
    images_offset = reader.read_u32()  # 86
    audio_offset = reader.read_u32()  # 90
    skeleton.imagesPath = get_pool_string(images_offset, skeleton)
    skeleton.audioPath = get_pool_string(audio_offset, skeleton)

    reader.reset_pos(98)


def read_bones(reader: SpineBinaryReader, skeleton: SkeletonData) -> None:
    bones: List[BoneData] = []
    bone_count = reader.read_u16()
    for i in range(bone_count):
        bone = BoneData()
        index = reader.read_i16() # 存入骨骼列表的顺序就是骨骼索引
        name_offset = reader.read_u32()
        parent_index = reader.read_i16()
        floats = read_f32_array(reader, 8) #length x y rotation scaleX scaleY shearX shearY
        inherit = Inherit(reader.read_i16())
        skin_required = reader.read_boolean()

        bone.name = get_pool_string(name_offset, skeleton)
        if len(bones) > parent_index >= 0:
            bone.parent = bones[parent_index].name
        elif parent_index == -1 and index != 0:
            bone.parent = "root"
        bone.length = floats[0]
        bone.x = floats[1]
        bone.y = floats[2]
        bone.rotation = floats[3]
        bone.scaleX = floats[4]
        bone.scaleY = floats[5]
        bone.shearX = floats[6]
        bone.shearY = floats[7]
        bone.inherit = Inherit(inherit)
        bone.skinRequired = skin_required
        # if nonessential:
        #     color = r.read_color()
        #     if color != Color(0x9B, 0x9B, 0x9B, 0xFF):
        #         bone.color = color
        bones.append(bone)

    skeleton.bones = bones
    # print(f"Read {bone_count} bones")
    # print(bones)

def read_iks(reader: SpineBinaryReader, skeleton: SkeletonData) -> None:
    iks: List[IKConstraintData] = []
    ik_count = reader.read_u16()

    for _ in range(ik_count):
        ik = IKConstraintData()
        name_offset = reader.read_u32()
        order = reader.read_u32()
        skin_required = reader.read_boolean()
        bend_direction = reader.read_i32()
        compress = reader.read_boolean()
        mix = reader.read_f32()
        softness = reader.read_f32()
        stretch = reader.read_boolean()
        uniform = reader.read_boolean()
        target_index = reader.read_i16()
        bone_count = reader.read_u16()
        bone_indexes = read_i16_array(reader, bone_count)

        ik.name = get_pool_string(name_offset, skeleton)
        ik.order = order
        ik.skinRequired = skin_required
        ik.bendPositive = bend_direction > 0
        ik.compress = compress
        ik.mix = mix
        ik.softness = softness
        ik.stretch = stretch
        ik.uniform = uniform
        ik.target = skeleton.bones[target_index].name if len(skeleton.bones) > target_index >= 0 else None
        for bone_index in bone_indexes:
            if len(skeleton.bones) > bone_index >= 0:
                ik.bones.append(skeleton.bones[bone_index].name)
        iks.append(ik)

    skeleton.ikConstraints = iks
    # print(f"Read {ik_count} IK constraints")

def read_slots(reader: SpineBinaryReader, skeleton: SkeletonData) -> None:
    slots: List[SlotData] = []
    slot_count = reader.read_u16()

    for _ in range(slot_count):
        slot = SlotData()
        _index = reader.read_u16() # 存入插槽列表的顺序就是插槽索引
        name_offset = reader.read_u32()
        bone_index = reader.read_u16()
        (r, g, b, a) = read_f32_array(reader, 4)
        (dr, dg, db, da) = read_f32_array(reader, 4)
        has_dark_color = reader.read_boolean()
        attachment_name_offset = reader.read_u32()
        blend_mode = reader.read_u16()

        slot.name = get_pool_string(name_offset, skeleton)
        slot.bone = skeleton.bones[bone_index].name if len(skeleton.bones) > bone_index >= 0 else None
        slot.color = Color(int(r * 255), int(g * 255), int(b * 255), int(a * 255))
        slot.darkColor = Color(int(dr * 255), int(dg * 255), int(db * 255), int(da * 255)) if has_dark_color else None
        slot.attachmentName = get_pool_string(attachment_name_offset, skeleton)
        slot.blendMode = BlendMode(blend_mode)
        slots.append(slot)
    
    skeleton.slots = slots
    # print(f"Read {slot_count} slots")
    
def read_transform_constraints(reader: SpineBinaryReader, skeleton: SkeletonData) -> None:
    tcs: List[TransformConstraintData] = []
    tc_count = reader.read_u16()
    
    for _ in range(tc_count):
        tf = TransformConstraintData()
        name_offset = reader.read_u32()
        order = reader.read_u32()
        skin_required = reader.read_boolean()
        rotate_mix = reader.read_f32()
        translate_mix = reader.read_f32()
        scale_mix = reader.read_f32()
        shear_mix = reader.read_f32()

        offset_rotation = reader.read_f32()
        offset_x = reader.read_f32()
        offset_y = reader.read_f32()
        offset_scale_x = reader.read_f32()
        offset_scale_y = reader.read_f32()
        offset_shear_y = reader.read_f32()

        # TODO: 这里的 local 和 relative 不确定先后顺序，可能需要调整
        local = reader.read_boolean()
        relative = reader.read_boolean()

        target_index = reader.read_i16()
        bone_count = reader.read_u16()
        bone_indexes = read_i16_array(reader, bone_count)



        tf.name = get_pool_string(name_offset, skeleton)
        tf.order = order
        tf.skinRequired = skin_required
        tf.rotateMix = rotate_mix
        tf.translateMix = translate_mix
        tf.scaleMix = scale_mix
        tf.shearMix = shear_mix
        tf.offsetRotation = offset_rotation
        tf.offsetX = offset_x
        tf.offsetY = offset_y
        tf.offsetScaleX = offset_scale_x
        tf.offsetScaleY = offset_scale_y
        tf.offsetShearY = offset_shear_y
        tf.target = skeleton.bones[target_index].name if len(skeleton.bones) > target_index >= 0 else None
        for bone_index in bone_indexes:
            if len(skeleton.bones) > bone_index >= 0:
                tf.bones.append(skeleton.bones[bone_index].name)
        tf.local = local
        tf.relative = relative

        tcs.append(tf)

    skeleton.transformConstraints = tcs
    # print(f"Read {tc_count} transform constraints")


def read_path_constraints(reader: SpineBinaryReader, skeleton: SkeletonData) -> None:
    pcs: List[PathConstraintData] = []
    tc_count = reader.read_u16()

    for _ in range(tc_count):
        path = PathConstraintData()

        name_offset = reader.read_u32()
        order = reader.read_u32()
        skin_required = reader.read_boolean()

        positive_mode = reader.read_i16()
        spacing_mode = reader.read_i16()
        rotate_mode = reader.read_i16()

        offset_rotation = reader.read_f32()
        position_value = reader.read_f32()
        spacing_value = reader.read_f32()
        rotate_mix = reader.read_f32()
        translate_mix = reader.read_f32()
        # _ = reader.read_u32() # 可能还有一个 translate mix，暂时不确定
        target_slot_index = reader.read_i16()
        bone_count = reader.read_u16()
        bone_indexes = read_i16_array(reader, bone_count)


        path.name = get_pool_string(name_offset, skeleton)
        path.order = order
        path.skinRequired = skin_required
        path.positionMode = PositionMode(positive_mode)
        path.spacingMode = SpacingMode(spacing_mode)
        path.rotateMode = RotateMode(rotate_mode)

        path.offsetRotation = offset_rotation
        path.position = position_value
        path.spacing = spacing_value
        path.rotateMix = rotate_mix
        path.translateMix = translate_mix
        path.targetSlot = skeleton.slots[target_slot_index].name if len(skeleton.slots) > target_slot_index >= 0 else None
        for bone_index in bone_indexes:
            if len(skeleton.bones) > bone_index >= 0:
                path.bones.append(skeleton.bones[bone_index].name)

        pcs.append(path)

    skeleton.pathConstraints = pcs
    # print(f"Read {tc_count} path constraints")
    # print(pcs)


def read_vertices(reader: SpineBinaryReader) -> Tuple[List[float], List[int], int]:
    bones_count = reader.read_u16()
    bones = read_u16_array(reader, bones_count)
    vertices_length = reader.read_u16()
    vertices = read_f32_array(reader, vertices_length)

    world_vertices_length = reader.read_u32() # maybe world_vertices_length ?

    # if bones_count == 0: #non-weighted
    #     print("non-weighted vertices")
    #     print("vertices count: ", count, "world vertices length: ", _length )
    # if bones_count != 0:
    #     print("weighted vertices")
    #     print("vertices count: ", count, "world vertices length: ", _length, "bones count: ", bones_count)

    _name_offset = reader.read_u32()
    # _name = get_pool_string(_name_offset, skeleton) # whose name ?

    is_weighted = bones_count > 0
    vertex_count = world_vertices_length // 2

    if is_weighted:
        weighted_vertices = merge_weighted_vertices(vertices, bones)

        return weighted_vertices, bones, vertex_count

    return vertices, bones, vertex_count

def read_attachment(reader: SpineBinaryReader, skeleton: SkeletonData) -> Attachment:
    attachment: Attachment = Attachment()
    attachment_name_offset = reader.read_u32()
    attachment_type = AttachmentType(reader.read_u16())
    attachment_path_offset = reader.read_u32()

    if attachment_type == AttachmentType.Region:  # 0
        region_data = RegionAttachment()
        floats = read_f32_array(reader, 13)

        # [0:6] x y rotation scaleX scaleY width height
        # [7:13] regionOffsetX, regionOffsetY, regionWidth, regionHeight, regionOriginalWidth, regionOriginalHeight

        _uv_count = reader.read_u16()
        _uvs = read_f32_array(reader, _uv_count)
        _vertex_count = reader.read_u16()
        _vertices = read_f32_array(reader, _vertex_count)

        _region_name_offset = reader.read_u32()
        clr = read_f32_array(reader, 4)

        region_data.x = floats[0]
        region_data.y = floats[1]
        region_data.rotation = floats[2]
        region_data.scaleX = floats[3]
        region_data.scaleY = floats[4]
        region_data.width = floats[5]
        region_data.height = floats[6]
        region_data.color = Color(int(clr[0] * 255), int(clr[1] * 255), int(clr[2] * 255), int(clr[3] * 255))

        region_name = get_pool_string(_region_name_offset, skeleton)
        region_data.name = get_pool_string(attachment_name_offset, skeleton)
        region_data.path = region_name
        
        attachment = region_data
    # TODO: 暂时没有检测到这个类型，无法验证读取逻辑是否正确
    elif attachment_type == AttachmentType.Boundingbox:  # 1
        bounding_box_data = BoundingBoxAttachment()
        vertices, bones, vertex_count = read_vertices(reader)
        
        bounding_box_data.vertices = vertices
        bounding_box_data.isWeighted = len(bones) > 0
        bounding_box_data.vertexCount = vertex_count
        attachment = bounding_box_data
    elif attachment_type == AttachmentType.Mesh or attachment_type == AttachmentType.Linkedmesh:  # 2, 3
        mesh_data = MeshAttachment()
        linked_mesh_data = LinkedMeshAttachment()

        vertices, bones, vertex_count = read_vertices(reader)

        # [0.0, 0.0, 664.0, 232.0, 664.0, 232.0] 实测应该是 x y width height originalWidth originalHeight
        floats6 = read_f32_array(reader, 6)

        # region-space 顶点 应该是e7预算的，可以忽略
        count1 = reader.read_u16()
        _floats1 = read_f32_array(reader, count1)

        #uvs
        uv_count = reader.read_u16()
        uvs = read_f32_array(reader, uv_count)

        tris_count = reader.read_u16()
        triangles = read_u16_array(reader, tris_count)

        edges_count = reader.read_u16()
        edges = read_u16_array(reader, edges_count)

        path_offset = reader.read_u32()  # atlas region name offset
        # TODO 不太清楚具体数据，推测后面四个是 r g b a , 实测确实如此
        # [0.39341846108436584, 0.8822937607765198, 0.7195481061935425, 0.998993992805481,
        # 32.0, 32.0, 1.0, 1.0, 1.0, 1.0]
        floats10 = read_f32_array(reader, 10)

        # TODO 不知道是什么 maybe hull_length
        hull_length = reader.read_u32() # maybe hull length
        # 0 flag
        _flag = reader.read_boolean()
        # if flag : 90 else: 0
        _flag_data = reader.read_u32()

        parent_mesh_name_offset = reader.read_u32()
        _parent_slot_index = reader.read_i16()

        skin_index = 0
        if skeleton.scspVersion == ScspVersion.V3:
            skin_index = reader.read_i16()  # always 0
            # TODO 这里可能会越界, 因为如果需要的皮肤在当前皮肤后面
            # skin = skeleton.skins[skin_index].name if 0 <= skin_index < len(skeleton.skins) else "default"
        else:  # V2
            skin_name_offset = reader.read_u32()  # only in v2
            _skin = get_pool_string(skin_name_offset, skeleton) if skin_name_offset != 0xFFFFFFFF else "default"

        deform = reader.read_boolean()

        mesh_data.vertexCount = vertex_count
        mesh_data.isWeighted = len(bones) > 0
        mesh_data.vertices = vertices
        mesh_data.uvs = uvs
        mesh_data.triangles = triangles
        mesh_data.edges = edges
        mesh_data.hullLength = hull_length

        r = int(floats10[6] * 255)
        g = int(floats10[7] * 255)
        b = int(floats10[8] * 255)
        a = int(floats10[9] * 255)
        mesh_data.path = get_pool_string(path_offset, skeleton)
        mesh_data.color = Color(r, g, b, a)
        mesh_data.width = floats6[2]
        mesh_data.height = floats6[3]


        linked_mesh_data.parentMesh = get_pool_string(parent_mesh_name_offset, skeleton)
        linked_mesh_data.skinIndex = skin_index
        linked_mesh_data.deform = deform
        linked_mesh_data.color = Color(r, g, b, a)
        linked_mesh_data.width = floats6[2]
        linked_mesh_data.height = floats6[3]

        attachment = mesh_data if attachment_type == AttachmentType.Mesh else linked_mesh_data

    elif attachment_type == AttachmentType.Path:  # 4
        path_data = PathAttachment()
        vertices, bones, vertices_count = read_vertices(reader)
        length_count = reader.read_u16()
        lengths = read_f32_array(reader, length_count)
        closed_value = reader.read_boolean()
        constant_speed_value = reader.read_boolean()

        path_data.vertices = vertices
        path_data.isWeighted = len(bones) > 0
        path_data.vertexCount = vertices_count
        path_data.lengths = lengths
        path_data.closed = closed_value
        path_data.constantSpeed = constant_speed_value

        attachment = path_data

    elif attachment_type == AttachmentType.Point:  # 5
        point_data = PointAttachment()

        point_floats = read_f32_array(reader, 3)
        point_data.x = point_floats[0]
        point_data.y = point_floats[1]
        point_data.rotation = point_floats[2]

        attachment = point_data

    elif attachment_type == AttachmentType.Clipping:  # 6
        clipping_data = ClippingAttachment()
        vertices, bones, vertex_count = read_vertices(reader)
        end_slot_index = reader.read_i16()

        clipping_data.vertexCount = vertex_count
        clipping_data.isWeighted = len(bones) > 0
        clipping_data.vertices = vertices
        clipping_data.endSlot = skeleton.slots[end_slot_index].name if 0 <= end_slot_index < len(
            skeleton.slots) else None
        attachment = clipping_data
    
    if attachment.name is None:
        attachment.name = get_pool_string(attachment_name_offset, skeleton)
    if attachment.path is None:
        attachment.path = get_pool_string(attachment_path_offset, skeleton)
    attachment.type = attachment_type

    return attachment


def read_skins(reader: SpineBinaryReader, skeleton: SkeletonData) -> None:
    skins: List[SkinData] = []

    skin_count = reader.read_u16()

    for _ in range(skin_count):
        skin = SkinData()
        skin_name_offset = reader.read_u32()

        bone_count = reader.read_u16()
        bone_indexes = read_u16_array(reader, bone_count)

        path_count = reader.read_u16()
        path_constraint_name_offsets = read_u32_array(reader, path_count)

        slot_attachment_count = reader.read_u16()
        attachments: Dict[str, Dict[str, Attachment]] = defaultdict(dict)

        for _ in range(slot_attachment_count):
            slot_index = reader.read_i16()
            slot_name = skeleton.slots[slot_index].name if 0 <= slot_index < len(skeleton.slots) else None
            attachment = read_attachment(reader, skeleton)
            attachments[slot_name][attachment.name] = attachment

        skin.name = get_pool_string(skin_name_offset, skeleton)
        skin.bones = [skeleton.bones[i].name for i in bone_indexes]
        skin.paths = [get_pool_string(offset, skeleton) for offset in path_constraint_name_offsets]
        skin.attachments = attachments
        skins.append(skin)

    skeleton.skins = skins
    # print(f"Read {skin_count} skins")


# TODO Check
def read_events(reader: SpineBinaryReader, skeleton: SkeletonData) -> None:
    events: List[EventData] = []
    event_count = reader.read_u16()

    for _ in range(event_count):
        event = EventData()
        event_name_offset = reader.read_u32()
        int_value = reader.read_i32()
        float_value = reader.read_f32()
        string_offset = reader.read_u32()
        audio_path_offset = reader.read_u32()
        volume = reader.read_f32()
        balance = reader.read_f32()

        event.name = get_pool_string(event_name_offset, skeleton)
        event.intValue = int_value
        event.floatValue = float_value
        event.stringValue = get_pool_string(string_offset, skeleton)
        event.audioPath = get_pool_string(audio_path_offset, skeleton)
        if event.audioPath and len(event.audioPath) > 0:
            event.volume = volume
            event.balance = balance
        events.append(event)

    skeleton.events = events
    # print(f"Read {event_count} events")


def read_animations(reader: SpineBinaryReader, skeleton: SkeletonData) -> None:
    animation_count = reader.read_u16()
    animations: List[AnimationData] = []

    for _ in range(animation_count):
        anim = AnimationData()
        anim_name_offset = reader.read_u32()
        duration = reader.read_f32()
        timeline_count = reader.read_u16()

        timelines: List[TimelineData] = []
        for _ in range(timeline_count):
            timeline_data = TimelineData()
            time_line_type = TimelineType(reader.read_u16())
            # 公共模式
            if time_line_type in (0, 1, 2, 3, 5, 9, 10, 11, 12, 13, 14):
                index = reader.read_i16()
                frame_count = reader.read_u16()
                frames = read_f32_array(reader, frame_count)
                curve_count = reader.read_u16()
                curves = read_f32_array(reader, curve_count)
                match time_line_type:
                    case TimelineType.Rotate:
                        timeline_data = RotateTimeline()
                        timeline_data.bone_index = index
                        for i in range(0, frame_count, 2):
                            if i + 1 < frame_count:
                                timeline_data.times.append(frames[i])
                                timeline_data.angles.append(frames[i + 1])

                    case TimelineType.Translate:
                        timeline_data = TranslateTimeline()
                        timeline_data.bone_index = index
                        for i in range(0, frame_count, 3):
                            if i + 2 < frame_count:
                                timeline_data.times.append(frames[i])
                                timeline_data.xs.append(frames[i + 1])
                                timeline_data.ys.append(frames[i + 2])
                    case TimelineType.Scale:
                        timeline_data = ScaleTimeline()
                        timeline_data.bone_index = index
                        for i in range(0, frame_count, 3):
                            if i + 2 < frame_count:
                                timeline_data.times.append(frames[i])
                                timeline_data.xs.append(frames[i + 1])
                                timeline_data.ys.append(frames[i + 2])
                    case TimelineType.Shear:
                        timeline_data = ShearTimeline()
                        timeline_data.bone_index = index
                        for i in range(0, frame_count, 3):
                            if i + 2 < frame_count:
                                timeline_data.times.append(frames[i])
                                timeline_data.xs.append(frames[i + 1])
                                timeline_data.ys.append(frames[i + 2])
                    case TimelineType.Color:
                        timeline_data = ColorTimeline()
                        timeline_data.slot_index = index
                        for i in range(0, frame_count, 5):
                            if i + 4 < frame_count:
                                timeline_data.times.append(frames[i])
                                r = int(frames[i + 1] * 255)
                                g = int(frames[i + 2] * 255)
                                b = int(frames[i + 3] * 255)
                                a = int(frames[i + 4] * 255)
                                timeline_data.colors.append(Color(r, g, b, a))
                    case TimelineType.IkConstraint:
                        timeline_data = IKTimeline()
                        timeline_data.ik_index = index
                        for i in range(0, frame_count, 6):
                            if i + 5 < frame_count:
                                timeline_data.times.append(frames[i])
                                timeline_data.mixs.append(frames[i + 1])
                                timeline_data.softness.append(frames[i + 2])
                                timeline_data.bend_directions.append(int(frames[i + 3]))
                                timeline_data.compresses.append(frames[i + 4] > 0)
                                timeline_data.stretches.append(frames[i + 5] > 0)
                    case TimelineType.TransformConstraint:
                        timeline_data = TransformTimeline()
                        timeline_data.transform_index = index
                        for i in range(0, frame_count, 5):
                            if i + 4 < frame_count:
                                timeline_data.times.append(frames[i])
                                timeline_data.rotateMixs.append(frames[i + 1])
                                timeline_data.translateMixs.append(frames[i + 2])
                                timeline_data.scaleMixs.append(frames[i + 3])
                                timeline_data.shearMixs.append(frames[i + 4])
                    case TimelineType.PathConstraintPosition:
                        timeline_data = PathPositionTimeline()
                        timeline_data.path_index = index
                        for i in range(0, frame_count, 2):
                            if i + 1 < frame_count:
                                timeline_data.times.append(frames[i])
                                timeline_data.positions.append(frames[i + 1])
                    case TimelineType.PathConstraintSpacing:
                        timeline_data = PathSpacingTimeline()
                        timeline_data.path_index = index
                        for i in range(0, frame_count, 2):
                            if i + 1 < frame_count:
                                timeline_data.times.append(frames[i])
                                timeline_data.spacings.append(frames[i + 1])
                    case TimelineType.PathConstraintMix:
                        timeline_data = PathMixTimeline()
                        timeline_data.path_index = index
                        for i in range(0, frame_count, 3):
                            if i + 2 < frame_count:
                                timeline_data.times.append(frames[i])
                                timeline_data.rotateMixs.append(frames[i + 1])
                                timeline_data.translateMixs.append(frames[i + 2])
                    case TimelineType.TwoColor:
                        timeline_data = TwoColorTimeline()
                        timeline_data.slot_index = index
                        for i in range(0, frame_count, 9):
                            if i + 8 < frame_count:
                                timeline_data.times.append(frames[i])
                                r1 = int(frames[i + 1] * 255)
                                g1 = int(frames[i + 2] * 255)
                                b1 = int(frames[i + 3] * 255)
                                a1 = int(frames[i + 4] * 255)
                                r2 = int(frames[i + 5] * 255)
                                g2 = int(frames[i + 6] * 255)
                                b2 = int(frames[i + 7] * 255)
                                a2 = int(frames[i + 8] * 255)
                                timeline_data.colorLights.append(Color(r1, g1, b1, a1))
                                timeline_data.colorDarks.append(Color(r2, g2, b2, a2))
                
                timeline_data.type = time_line_type
                timeline_data.frames = frames
                timeline_data.curves = curves
                # TODO
            elif time_line_type == TimelineType.Attachment:  # 4
                index = reader.read_i16()
                frames_count = reader.read_u16()
                frames = read_f32_array(reader, frames_count)
                attachment_count = reader.read_u16()
                attachment_name_offsets = read_u32_array(reader, attachment_count)

                timeline_data = AttachmentTimeline()
                timeline_data.times = frames
                timeline_data.names = [get_pool_string(offset, skeleton) for offset in attachment_name_offsets]
                
                timeline_data.type = time_line_type
                timeline_data.slot_index = index
                timeline_data.frames = frames
                # attachment timeline 没有曲线数据
            # TODO Check
            elif time_line_type == TimelineType.Deform:  # 6
                slot_index = reader.read_i16()

                frame_count = reader.read_u16()
                frames = read_f32_array(reader, frame_count)

                curve_count = reader.read_u16()
                curves = read_f32_array(reader, curve_count)

                deform_count = reader.read_u16()
                deform_vertices: List[List[float]] = []
                for _ in range(deform_count):
                    vertex_count = reader.read_u16()
                    vertices = read_f32_array(reader, vertex_count)
                    deform_vertices.append(vertices)
                attachment_name_offset = reader.read_u32()

                skin_index = 0
                if skeleton.scspVersion == ScspVersion.V3:
                    skin_index = reader.read_i16()  # always 0

                # Vertex positions for an unweighted VertexAttachment, or deform offsets if it has weights.
                slot_name = skeleton.slots[slot_index].name if 0 <= slot_index < len(skeleton.slots) else None
                attachment_name = get_pool_string(attachment_name_offset, skeleton)
                attachment = skeleton.skins[skin_index].attachments.get(slot_name, {}).get(attachment_name)
                is_weighted = False
                setup_vertices: List[float] = []
                offsets: List[List[float]] = []
                if isinstance(attachment, VertexAttachment):
                    is_weighted = attachment.isWeighted
                    setup_vertices = attachment.vertices
                        
                if not is_weighted and setup_vertices: # non-weighted
                    for dv in deform_vertices:
                        frame_offsets: List[float] = []
                        count = min(len(dv), len(setup_vertices))
                        for i in range(count):
                            frame_offsets.append(dv[i] - setup_vertices[i])
                        if len(dv) < len(setup_vertices): # 补0
                            frame_offsets.extend([0.0] * (len(setup_vertices) - len(dv)))
                        offsets.append(frame_offsets)

                else: # weighted
                    offsets = deform_vertices

                timeline_data = DeformTimeline()
                timeline_data.times = frames
                timeline_data.vertices = offsets
                timeline_data.skin = skeleton.skins[skin_index].name if 0 <= skin_index < len(skeleton.skins) else None
                timeline_data.attachment = attachment_name

                timeline_data.type = time_line_type                
                timeline_data.slot_index = slot_index
                timeline_data.frames = frames
                timeline_data.curves = curves
            # TODO 结构不确定
            elif time_line_type == TimelineType.Event:  # 7
                frames_count = reader.read_u16()
                frames = read_f32_array(reader, frames_count)
                event_count = reader.read_u16()
                event_name_offsets = read_u32_array(reader, event_count)

                timeline_data = EventTimeline()
                timeline_data.times = frames
                timeline_data.names = [get_pool_string(offset, skeleton) for offset in event_name_offsets]
                
                timeline_data.type = time_line_type
                timeline_data.frames = frames
                # event timeline 没有曲线数据
            elif time_line_type == TimelineType.DrawOrder:  # 8
                frames_count = reader.read_u16()
                frames = read_f32_array(reader, frames_count)
                order_count = reader.read_u16()
                orders: List[List[int]] = []
                for _ in range(order_count):
                    slot_count = reader.read_u16()
                    slot_indexes = read_i32_array(reader, slot_count)
                    orders.append(slot_indexes)

                timeline_data = DrawOrderTimeline()
                timeline_data.times = frames
                timeline_data.orders = orders
                
                timeline_data.frames = frames
                # drawOrder timeline 没有曲线数据
            timelines.append(timeline_data)

        anim.name = get_pool_string(anim_name_offset, skeleton)
        anim.duration = duration
        anim.timelines = timelines
        animations.append(anim)

    skeleton.animations = animations
    # print(f"Read {animation_count} animations")


def read_scsp_v3(r: SpineBinaryReader, sk: SkeletonData) -> None:
    read_bones(r, sk)
    read_iks(r, sk)
    read_slots(r, sk)
    read_transform_constraints(r, sk)
    read_path_constraints(r, sk)
    read_skins(r, sk)
    read_events(r, sk)
    read_animations(r, sk)

def read_scsp_v2(r: SpineBinaryReader, sk: SkeletonData) -> None:
    pass

def read_binary_skeleton(data: bytes) -> Tuple[SkeletonData, bool]:
    r = SpineBinaryReader(data)
    sk = SkeletonData()
    
    read_skeleton_info(r, sk)

    if sk.scspVersion == ScspVersion.V2:
        # print(f"SCSP version 2 NOT IMPLEMENTED, Next.")
        read_scsp_v2(r, sk)
        return sk, False
    else:# V3
        read_scsp_v3(r, sk)
    
    return sk, True


# ==============================
# JSON Writer (Spine 3.8)
# ==============================

def write_curve(curves: List[float], frame_index: int) -> Dict[str, Any]:
    item: Dict[str, Any] = defaultdict(dict)
    curve_index = frame_index * 19
    curve_type = int(curves[curve_index]) # type + 18 floats, 每个帧的曲线数据占 19 个 float

    if curve_type == CurveType.LINEAR:
        return item
    elif curve_type == CurveType.STEPPED:
        item["curve"] = "stepped"
    elif curve_type == CurveType.BEZIER:
        if curves:
            item["curve"] = curves[curve_index + 1]
            if curves[curve_index + 2] != 0.0:
                item["c2"] = curves[curve_index + 2]
            if curves[curve_index + 3] != 1.0:
                item["c3"] = curves[curve_index + 3]
            if curves[curve_index + 4] != 1.0:
                item["c4"] = curves[curve_index + 4]
    return item


def write_timeline_data(timeline: TimelineData, sk: SkeletonData) -> List[Dict[str, Any]]:
    arr: List[Dict[str, Any]] = []
    frame_count = len(timeline.times)

    match timeline:
        case RotateTimeline() as t:
            for i in range(frame_count):
                item: Dict[str, Any] = defaultdict(dict)
                if t.times[i] != 0.0:
                    item["time"] = t.times[i]
                item["angle"] = t.angles[i]
                if t.curves and i < frame_count - 1:
                    item.update(write_curve(t.curves, i))
                arr.append(item)

        case TranslateTimeline() as t:
            for i in range(frame_count):
                item: Dict[str, Any] = defaultdict(dict)
                if t.times[i] != 0.0:
                    item["time"] = t.times[i]
                if t.xs[i] != 0.0:
                    item["x"] = t.xs[i]
                if t.ys[i] != 0.0:
                    item["y"] = t.ys[i]
                if t.curves and i < frame_count - 1:
                    item.update(write_curve(t.curves, i))
                arr.append(item)
        case ScaleTimeline() as t:
            for i in range(frame_count):
                item: Dict[str, Any] = defaultdict(dict)
                if t.times[i] != 0.0:
                    item["time"] = t.times[i]
                if t.xs[i] != 1.0:
                    item["x"] = t.xs[i]
                if t.ys[i] != 1.0:
                    item["y"] = t.ys[i]
                if t.curves and i < frame_count - 1:
                    item.update(write_curve(t.curves, i))
                arr.append(item)
        case ShearTimeline() as t:
            for i in range(frame_count):
                item: Dict[str, Any] = defaultdict(dict)
                if t.times[i] != 0.0:
                    item["time"] = t.times[i]
                if t.xs[i] != 0.0:
                    item["x"] = t.xs[i]
                if t.ys[i] != 0.0:
                    item["y"] = t.ys[i]
                if t.curves and i < frame_count - 1:
                    item.update(write_curve(t.curves, i))
                arr.append(item)
        case AttachmentTimeline() as t:
            for i in range(frame_count):
                item: Dict[str, Any] = defaultdict(dict)
                if t.times[i] != 0.0:
                    item["time"] = t.times[i]
                if i < len(t.names) and t.names[i]:
                    item["name"] = t.names[i]
                else:
                    item["name"] = None
                # attachment timeline 没有曲线数据
                arr.append(item)
        case ColorTimeline() as t:
            for i in range(frame_count):
                # print("frame_count: ", frame_count)
                item: Dict[str, Any] = defaultdict(dict)
                if t.times[i] != 0.0:
                    item["time"] = t.times[i]
                color = t.colors[i]
                if color:
                    item["color"] = color_to_string(color, True)
                if t.curves and i < frame_count - 1:
                    # print(f"ColorTimeline frame {i} has curve data")
                    item.update(write_curve(t.curves, i))
                arr.append(item)
        case DeformTimeline() as t:
            for i in range(frame_count):
                item: Dict[str, Any] = defaultdict(dict)
                if t.times[i] != 0.0:
                    item["time"] = t.times[i]
                if t.offsets and i < len(t.offsets):
                    item["offset"] = t.offsets[i]
                if t.vertices and i < len(t.vertices):
                    item["vertices"] = t.vertices[i]
                    
                if t.curves and i < frame_count - 1:
                    item.update(write_curve(t.curves, i))
                arr.append(item)
        case EventTimeline() as t:
            for i in range(frame_count):
                item: Dict[str, Any] = defaultdict(dict)
                if t.times[i] != 0.0:
                    item["time"] = t.times[i]
                if i < len(t.names) and t.names[i]:
                    item["name"] = t.names[i]
                else:
                    item["name"] = None
                # event timeline 没有曲线数据
                arr.append(item)
            pass
        case DrawOrderTimeline() as t:
            for i in range(frame_count):
                item: Dict[str, Any] = defaultdict(dict)
                if t.times[i] != 0.0:
                    item["time"] = t.times[i]
                # item["order"] = t.orders[i]
                if i < len(t.orders) and t.orders[i]:
                    # 格式: [slotIndex, ...]
                    order = t.orders[i]
                    pairs = []

                    for new_index, slot_index in enumerate(order):
                        if new_index != slot_index:
                            pairs.append((slot_index, new_index))

                    pairs.sort(key=lambda x: x[0])  # 按 slotIndex 排序

                    offsets = []

                    for slot_index, new_index in pairs:
                        offsets.append({
                            "slot": sk.slots[slot_index].name,
                            "offset": new_index - slot_index
                        })

                    if offsets:
                        item["offsets"] = offsets
                # draw order timeline 没有曲线数据  
                arr.append(item)
        case IKTimeline() as t:
            for i in range(frame_count):
                item: Dict[str, Any] = defaultdict(dict)
                if t.times[i] != 0.0:
                    item["time"] = t.times[i]
                if t.mixs and i < len(t.mixs) and t.mixs[i] != 1.0:
                    item["mix"] = t.mixs[i]
                if t.softness and i < len(t.softness) and t.softness[i] != 0.0:
                    item["softness"] = t.softness[i]
                if t.bend_directions and i < len(t.bend_directions):
                    item["bendPositive"] = t.bend_directions[i] >= 0
                if t.compresses and i < len(t.compresses) and t.compresses[i]:
                    item["compress"] = True
                if t.stretches and i < len(t.stretches) and t.stretches[i]:
                    item["stretch"] = True
                if t.curves and i < frame_count - 1:
                    item.update(write_curve(t.curves, i))
                arr.append(item)
        case TransformTimeline() as t:
            for i in range(frame_count):
                item: Dict[str, Any] = defaultdict(dict)
                if t.times[i] != 0.0:
                    item["time"] = t.times[i]
                if t.rotateMixs and i < len(t.rotateMixs) and t.rotateMixs[i] != 1.0:
                    item["rotateMix"] = t.rotateMixs[i]
                if t.translateMixs and i < len(t.translateMixs) and t.translateMixs[i] != 1.0:
                    item["translateMix"] = t.translateMixs[i]
                if t.scaleMixs and i < len(t.scaleMixs) and t.scaleMixs[i] != 1.0:
                    item["scaleMix"] = t.scaleMixs[i]
                if t.shearMixs and i < len(t.shearMixs) and t.shearMixs[i] != 1.0:
                    item["shearMix"] = t.shearMixs[i]
                if t.curves and i < frame_count - 1:
                    item.update(write_curve(t.curves, i))
                arr.append(item)
        case PathPositionTimeline() as t:
            for i in range(frame_count):
                item: Dict[str, Any] = defaultdict(dict)
                if t.times[i] != 0.0:
                    item["time"] = t.times[i]
                if t.positions and i < len(t.positions) and t.positions[i] != 0.0:
                    item["position"] = t.positions[i]
                if t.curves and i < frame_count - 1:
                    item.update(write_curve(t.curves, i))
                arr.append(item)
        case PathSpacingTimeline() as t:
            for i in range(frame_count):
                item: Dict[str, Any] = defaultdict(dict)
                if t.times[i] != 0.0:
                    item["time"] = t.times[i]
                if t.spacings and i < len(t.spacings) and t.spacings[i] != 0.0:
                    item["spacing"] = t.spacings[i]
                if t.curves and i < frame_count - 1:
                    item.update(write_curve(t.curves, i))
                arr.append(item)
        case PathMixTimeline() as t:
            for i in range(frame_count):
                item: Dict[str, Any] = defaultdict(dict)
                if t.times[i] != 0.0:
                    item["time"] = t.times[i]
                if t.rotateMixs and i < len(t.rotateMixs) and t.rotateMixs[i] != 1.0:
                    item["rotateMix"] = t.rotateMixs[i]
                if t.translateMixs and i < len(t.translateMixs) and t.translateMixs[i] != 1.0:
                    item["translateMix"] = t.translateMixs[i]
                if t.curves and i < frame_count - 1:
                    item.update(write_curve(t.curves, i))
                arr.append(item)
        case TwoColorTimeline() as t:
            for i in range(frame_count):
                item: Dict[str, Any] = defaultdict(dict)
                if t.times[i] != 0.0:
                    item["time"] = t.times[i]
                light = t.colorLights[i]
                dark = t.colorDarks[i]
                if light:
                    item["light"] = color_to_string(light, True)
                if dark:
                    item["dark"] = color_to_string(dark, False)
                if t.curves and i < frame_count - 1:
                    item.update(write_curve(t.curves, i))
                arr.append(item)

    return arr


def build_animation_json(anim: AnimationData, sk: SkeletonData) -> None:
    for timeline in anim.timelines:
        obj = write_timeline_data(timeline, sk)
        if obj:
            match timeline:
                case RotateTimeline() | TranslateTimeline() | ScaleTimeline() | ShearTimeline() as t:
                    # bones
                    bone_name = sk.bones[t.bone_index].name if 0 <= t.bone_index < len(sk.bones) else ""
                    if bone_name not in anim.bones:
                        anim.bones[bone_name] = {}
                    type_key = {
                        TimelineType.Rotate: "rotate",
                        TimelineType.Translate: "translate",
                        TimelineType.Scale: "scale",
                        TimelineType.Shear: "shear",
                    }[t.type]
                    anim.bones[bone_name][type_key] = obj
                case AttachmentTimeline() | ColorTimeline() | TwoColorTimeline() as t:
                    # slots
                    slot_name = sk.slots[t.slot_index].name if 0 <= t.slot_index < len(sk.slots) else ""
                    if slot_name not in anim.slots:
                        anim.slots[slot_name] = {}
                    type_key = {
                        TimelineType.Attachment: "attachment",
                        TimelineType.Color: "color",
                        TimelineType.TwoColor: "twoColor",
                    }[t.type]
                    anim.slots[slot_name][type_key] = obj
                case DeformTimeline() as t:
                    # deform
                    skin_name = t.skin if t.skin else "default"
                    slot_name = sk.slots[t.slot_index].name if 0 <= t.slot_index < len(sk.slots) else ""
                    attachment_name = t.attachment
                    if skin_name not in anim.deform:
                        anim.deform[skin_name] = {}
                    if slot_name not in anim.deform[skin_name]:
                        anim.deform[skin_name][slot_name] = {}
                    anim.deform[skin_name][slot_name][attachment_name] = obj
                case EventTimeline():
                    # events
                    anim.events = obj
                case DrawOrderTimeline():
                    # drawOrder
                    anim.drawOrder = obj
                case IKTimeline() as t:
                    # ik
                    ik_name = sk.ikConstraints[t.ik_index].name if 0 <= t.ik_index < len(sk.ikConstraints) else ""
                    anim.ik[ik_name] = obj
                case TransformTimeline() as t:
                    # transform
                    transform_name = sk.transformConstraints[t.transform_index].name if 0 <= t.transform_index < len(sk.transformConstraints) else ""
                    anim.transform[transform_name] = obj
                case PathPositionTimeline() | PathSpacingTimeline() | PathMixTimeline() as t:
                    # path
                    path_name = sk.pathConstraints[t.path_index].name if 0 <= t.path_index < len(sk.pathConstraints) else ""
                    if path_name not in anim.path:
                        anim.path[path_name] = {}
                    type_key = {
                        TimelineType.PathConstraintPosition: "position",
                        TimelineType.PathConstraintSpacing: "spacing",
                        TimelineType.PathConstraintMix: "mix",
                    }[t.type]
                    anim.path[path_name][type_key] = obj
    
           
    


def write_json_data(sk: SkeletonData) -> Dict[str, Any]:
    j: Dict[str, Any] = {
        "skeleton": {},
        "bones": [],
        "slots": [],
        "ik": [],
        "transform": [],
        "path": [],
        "skins": [],
        "events": {},
        "animations": {}
    }

    skeleton = {
        "x": sk.x,
        "y": sk.y,
        "width": sk.width,
        "height": sk.height,
    }
    if sk.hashString:
        skeleton["hash"] = sk.hashString
    elif sk.hash != 0:
        skeleton["hash"] = uint64_to_base64(sk.hash)
    if sk.version:
        skeleton["spine"] = sk.version
    if sk.nonessential:
        if sk.fps != 30.0:
            skeleton["fps"] = sk.fps
        if sk.imagesPath:
            skeleton["images"] = sk.imagesPath
        if sk.audioPath:
            skeleton["audio"] = sk.audioPath
    j["skeleton"] = skeleton

    # bones
    for b in sk.bones:
        obj: Dict[str, Any] = {}
        if b.name is not None:
            obj["name"] = b.name
        if b.parent is not None:
            obj["parent"] = b.parent
        if b.length != 0.0:
            obj["length"] = b.length
        if b.x != 0.0:
            obj["x"] = b.x
        if b.y != 0.0:
            obj["y"] = b.y
        if b.rotation != 0.0:
            obj["rotation"] = b.rotation
        if b.scaleX != 1.0:
            obj["scaleX"] = b.scaleX
        if b.scaleY != 1.0:
            obj["scaleY"] = b.scaleY
        if b.shearX != 0.0:
            obj["shearX"] = b.shearX
        if b.shearY != 0.0:
            obj["shearY"] = b.shearY
        if b.inherit != Inherit.Normal:
            obj["transform"] = {
                Inherit.Normal: "normal",
                Inherit.OnlyTranslation: "onlyTranslation",
                Inherit.NoRotationOrReflection: "noRotationOrReflection",
                Inherit.NoScale: "noScale",
                Inherit.NoScaleOrReflection: "noScaleOrReflection",
            }[b.inherit]
        if b.skinRequired:
            obj["skin"] = True
        if b.color:
            obj["color"] = color_to_string(b.color, True)
        j["bones"].append(obj)

    # slots
    for s in sk.slots:
        obj: Dict[str, Any] = defaultdict(dict)
        if s.name:
            obj["name"] = s.name
        if s.bone:
            obj["bone"] = s.bone
        if s.color:
            obj["color"] = color_to_string(s.color, True)
        if s.darkColor:
            obj["dark"] = color_to_string(s.darkColor, False)
        if s.attachmentName is not None:
            obj["attachment"] = s.attachmentName
        if s.blendMode != BlendMode.Normal:
            obj["blend"] = {
                BlendMode.Normal: "normal",
                BlendMode.Additive: "additive",
                BlendMode.Multiply: "multiply",
                BlendMode.Screen: "screen",
            }[s.blendMode]
        j["slots"].append(obj)

    # ik
    for ik in sk.ikConstraints:
        obj: Dict[str, Any] = defaultdict(dict)
        if ik.name:
            obj["name"] = ik.name
        if ik.order != 0:
            obj["order"] = ik.order
        if ik.skinRequired:
            obj["skin"] = True
        if ik.bones:
            obj["bones"] = ik.bones
        if ik.target:
            obj["target"] = ik.target
        if ik.mix != 1.0:
            obj["mix"] = ik.mix
        if ik.softness != 0.0:
            obj["softness"] = ik.softness
        if not ik.bendPositive:
            obj["bendPositive"] = False
        if ik.compress:
            obj["compress"] = True
        if ik.stretch:
            obj["stretch"] = True
        if ik.uniform:
            obj["uniform"] = True
        j["ik"].append(obj)

    # transform
    for tf in sk.transformConstraints:
        obj: Dict[str, Any] = defaultdict(dict)
        if tf.name:
            obj["name"] = tf.name
        if tf.order != 0:
            obj["order"] = tf.order
        if tf.skinRequired:
            obj["skin"] = True
        if tf.bones:
            obj["bones"] = tf.bones
        if tf.target:
            obj["target"] = tf.target
        if tf.rotateMix != 1.0:
            obj["rotateMix"] = tf.rotateMix
        if tf.translateMix != 1.0:
            obj["translateMix"] = tf.translateMix
        if tf.scaleMix != 1.0:
            obj["scaleMix"] = tf.scaleMix
        if tf.shearMix != 1.0:
            obj["shearMix"] = tf.shearMix
        if tf.offsetRotation != 0.0:
            obj["rotation"] = tf.offsetRotation
        if tf.offsetX != 0.0:
            obj["x"] = tf.offsetX
        if tf.offsetY != 0.0:
            obj["y"] = tf.offsetY
        if tf.offsetScaleX != 0.0:
            obj["scaleX"] = tf.offsetScaleX
        if tf.offsetScaleY != 0.0:
            obj["scaleY"] = tf.offsetScaleY
        if tf.offsetShearY != 0.0:
            obj["shearY"] = tf.offsetShearY
        if tf.relative:
            obj["relative"] = True
        if tf.local:
            obj["local"] = True
        j["transform"].append(obj)

    # path constraints
    for p in sk.pathConstraints:
        obj: Dict[str, Any] = defaultdict(dict)
        if p.name:
            obj["name"] = p.name
        if p.order != 0:
            obj["order"] = p.order
        if p.skinRequired:
            obj["skin"] = True
        if p.bones:
            obj["bones"] = p.bones
        if p.targetSlot:
            obj["target"] = p.targetSlot
        if p.positionMode != PositionMode.Percent:
            obj["positionMode"] = {PositionMode.Fixed: "fixed", PositionMode.Percent: "percent"}[p.positionMode]
        if p.spacingMode != SpacingMode.Length:
            obj["spacingMode"] = {
                SpacingMode.Length: "length",
                SpacingMode.Fixed: "fixed",
                SpacingMode.Percent: "percent",
                SpacingMode.Proportional: "proportional",
            }[p.spacingMode]
        if p.rotateMode != RotateMode.Tangent:
            obj["rotateMode"] = {
                RotateMode.Tangent: "tangent",
                RotateMode.Chain: "chain",
                RotateMode.ChainScale: "chainScale",
            }[p.rotateMode]
        if p.offsetRotation != 0.0:
            obj["rotation"] = p.offsetRotation
        if p.position != 0.0:
            obj["position"] = p.position
        if p.spacing != 0.0:
            obj["spacing"] = p.spacing
        if p.rotateMix != 1.0:
            obj["rotateMix"] = p.rotateMix
        if p.translateMix != 1.0:
            obj["translateMix"] = p.translateMix
        j["path"].append(obj)

    # skins
    for skin in sk.skins:
        s_obj: Dict[str, Any] = defaultdict(dict)
        s_obj["name"] = skin.name
        if skin.bones:
            s_obj["bones"] = skin.bones
        if skin.ik:
            s_obj["ik"] = skin.ik
        if skin.transform:
            s_obj["transform"] = skin.transform
        if skin.paths:
            s_obj["path"] = skin.paths
        for slot_name, slot_map in skin.attachments.items():
            for att_name, att in slot_map.items():
                a_obj: Dict[str, Any] = defaultdict(dict)
                if att.name != att_name:
                    a_obj["name"] = att.name
                if att.type not in (AttachmentType.Mesh, AttachmentType.Linkedmesh):
                    if att.path and att.path != att_name:
                        a_obj["path"] = att.path
                if att.type != AttachmentType.Region:
                    a_obj["type"] = {
                        AttachmentType.Region: "region", # 占位
                        AttachmentType.Boundingbox: "boundingbox",
                        AttachmentType.Mesh: "mesh",
                        AttachmentType.Linkedmesh: "linkedmesh",
                        AttachmentType.Path: "path",
                        AttachmentType.Point: "point",
                        AttachmentType.Clipping: "clipping",
                    }[att.type]
                match att:
                    case RegionAttachment() as region:
                        if region.x != 0.0:
                            a_obj["x"] = region.x
                        if region.y != 0.0:
                            a_obj["y"] = region.y
                        if region.rotation != 0.0:
                            a_obj["rotation"] = region.rotation
                        if region.scaleX != 1.0:
                            a_obj["scaleX"] = region.scaleX
                        if region.scaleY != 1.0:
                            a_obj["scaleY"] = region.scaleY
                        a_obj["width"] = region.width
                        a_obj["height"] = region.height
                        if region.color:
                            a_obj["color"] = color_to_string(region.color, True)
                    case BoundingBoxAttachment() as box:
                        if box.color:
                            a_obj["color"] = color_to_string(box.color, True)
                        if box.vertices:
                            a_obj["vertexCount"] = box.vertexCount
                            a_obj["vertices"] = box.vertices
                    case MeshAttachment() as mesh:
                        a_obj["width"] = mesh.width
                        a_obj["height"] = mesh.height

                        effective_path = mesh.path or att.path
                        if effective_path and effective_path != att_name:
                            a_obj["path"] = effective_path
                        if mesh.color:
                            a_obj["color"] = color_to_string(mesh.color, True)
                        if mesh.hullLength != 0:
                            a_obj["hull"] = mesh.hullLength
                        if mesh.triangles:
                            a_obj["triangles"] = mesh.triangles
                        if mesh.edges:
                            a_obj["edges"] = mesh.edges
                        if mesh.uvs:
                            a_obj["uvs"] = mesh.uvs
                        if mesh.vertices:
                            a_obj["vertexCount"] = mesh.vertexCount
                            a_obj["vertices"] = mesh.vertices
                    case LinkedMeshAttachment() as lmesh:
                        a_obj["width"] = lmesh.width
                        a_obj["height"] = lmesh.height
                        if lmesh.color:
                            a_obj["color"] = color_to_string(lmesh.color, True)
                        a_obj["parent"] = lmesh.parentMesh
                        # TODO ?
                        if not lmesh.deform:
                            a_obj["deform"] = False
                        a_obj["skin"] = sk.skins[lmesh.skinIndex].name if 0 <= lmesh.skinIndex < len(sk.skins) else None

                    case PathAttachment() as path_att:
                        if path_att.closed:
                            a_obj["closed"] = True
                        if not path_att.constantSpeed:
                            a_obj["constantSpeed"] = path_att.constantSpeed
                        if path_att.color:
                            a_obj["color"] = color_to_string(path_att.color, True)
                        if path_att.vertices:
                            a_obj["vertexCount"] = path_att.vertexCount
                            a_obj["vertices"] = path_att.vertices
                        if path_att.lengths:
                            a_obj["lengths"] = path_att.lengths
                    case PointAttachment() as point:
                        if point.x != 0.0:
                            a_obj["x"] = point.x
                        if point.y != 0.0:
                            a_obj["y"] = point.y
                        if point.rotation != 0.0:
                            a_obj["rotation"] = point.rotation
                        if point.color:
                            a_obj["color"] = color_to_string(point.color, True)
                    case ClippingAttachment() as clip:
                        if clip.endSlot:
                            a_obj["end"] = clip.endSlot
                        if clip.color:
                            a_obj["color"] = color_to_string(clip.color, True)
                        if clip.vertices:
                            a_obj["vertexCount"] = clip.vertexCount
                            a_obj["vertices"] = clip.vertices

                s_obj.setdefault("attachments", {}).setdefault(slot_name, {})[att_name] = a_obj
        j["skins"].append(s_obj)

    # events
    ev_obj: Dict[str, Any] = defaultdict(dict)
    for e in sk.events:
        item: Dict[str, Any] = defaultdict(dict)
        if e.intValue != 0:
            item["int"] = e.intValue
        if e.floatValue != 0.0:
            item["float"] = e.floatValue
        if e.stringValue is not None:
            item["string"] = e.stringValue
        if e.audioPath:
            item["audio"] = e.audioPath
            if e.volume != 1.0:
                item["volume"] = e.volume
            if e.balance != 0.0:
                item["balance"] = e.balance

        ev_obj[e.name] = item
    j["events"] = ev_obj

    # animations

    if sk.animations:
        anims: Dict[str, Any] = defaultdict(dict)
        for anim in sk.animations:
            build_animation_json(anim, sk)

            a_obj: Dict[str, Any] = defaultdict(dict)
            if anim.slots:
                a_obj["slots"] = anim.slots
            if anim.bones:
                a_obj["bones"] = anim.bones
            if anim.ik:
                a_obj["ik"] = anim.ik
            if anim.transform:
                a_obj["transform"] = anim.transform
            if anim.path:
                a_obj["path"] = anim.path
            if anim.deform:
                a_obj["deform"] = anim.deform
            if anim.drawOrder:
                a_obj["drawOrder"] = anim.drawOrder
            if anim.events:
                a_obj["events"] = anim.events

            anims[anim.name] = a_obj

        j["animations"] = anims

    return j


# ==============================
# Converter
# ==============================
def compress_json(json_str: str) -> str:
    data = json.loads(json_str)
    return json.dumps(data,separators=(",",":"))

def special_process(json_str: str) -> str:
    # 删除 normal 中的重合部分
    # 读取json中的 skin键 对应的值, 也就是一个字典列表, 对于列表中的每一个字典 都会有一个键 "name", 找到这个键对应的值为 “normal” 的字典 normal,
    # 对其做以下处理: 找到其余字典中 "attachments" 键下的所有键, 进行交集运算, 会得到一个交集键列表, 将 normal 字典中 "attachments" 键下的交集键对应的值删除
    # 如果deform 存在某些交集键, 则这些键不进行删除
    data = json.loads(json_str)
    skins = data.get("skins", [])
    if not isinstance(skins, list):
        return json_str
    normal_skin = None
    default_skin = None
    other_skins = []
    for skin in skins:
        if skin.get("name") == "normal":
            normal_skin = skin
        elif skin.get("name") == "default":
            default_skin = skin
        else:
            other_skins.append(skin)
    if normal_skin is None or default_skin is None or not other_skins:
        return json_str
    normal_attachments: Dict = normal_skin.get("attachments", {})
    default_attachments: Dict = default_skin.get("attachments", {})
    if not normal_attachments:
        return json_str

    key_sets: list[Set[str]] = []
    for skin in other_skins:
        attachments = skin.get("attachments", {})
        key_sets.append(set(attachments.keys()))
    if not key_sets:
        return json_str
    common_keys = set.intersection(*key_sets)

    protected_keys: Set[str] = set()
    animations = data.get("animations", {})
    if isinstance(animations, dict):
        for anim in animations.values():
            deform = anim.get("deform")
            if isinstance(deform, dict):
                normal_deform = deform.get("normal", {})
                if isinstance(normal_deform, dict):
                    protected_keys.update(normal_deform.keys())

    keys_to_delete = common_keys - protected_keys

    if len(keys_to_delete) > 1:
        return  json_str

    for key in keys_to_delete:
        if key in normal_attachments and key not in default_attachments:
            del normal_attachments[key]

    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))

# noinspection PyTypeChecker
def convert_scsp_to_json(input_path: str, output_path: str) -> bool:
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    with open(input_path, "rb") as f:
        data = f.read()

    skeleton, is_converted = read_binary_skeleton(data)
    if not is_converted:
        print(f"{input_path} is v2.1.27 scsp, not implemented yet.")
        return False

    root = write_json_data(skeleton)
    json_str = json.dumps(root, ensure_ascii=False)
    json_str = special_process(json_str) # 临时的处理, 但是并不是完全可靠的

    if IS_COMPRESS_JSON:
        json_str = compress_json(json_str)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(json_str)

    return True

# ==============================
# Batch
# ==============================

def batch_convert(input_dir: str, output_dir: str):
    input_path = Path(input_dir)
    output_path = Path(output_dir)

    total = 0
    success = 0

    for file in input_path.rglob("*.scsp"):
        total += 1
        relative_path = file.relative_to(input_path)
        out_file = output_path / relative_path.with_suffix(".json")

        try:
            if convert_scsp_to_json(str(file), str(out_file)):
                success += 1

        except Exception as e:
            print(f"[ERROR] {file}: {e}")

    print(f"\nDone: {success}/{total} files converted.")

# ==============================
# Entry
# ==============================


if __name__ == "__main__":
    batch_convert(INPUT_PATH, OUTPUT_PATH)