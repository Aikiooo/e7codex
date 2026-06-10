"""
Spine 4.2.43 binary .skel -> spine-player-3.8-compatible JSON.

Accepts either a stock Spine 4.2 `.skel` or an E7 `.scsp` (lz4 container whose
decompressed body is a 16-byte E7 header followed by a stock `.skel`).

The binary read logic is a line-faithful port of the official spine-runtimes
`SkeletonBinary` for editor build 4.2.43 (the `@esotericsoftware/spine-core`
4.2.43 npm release is the format ground truth — Spine binary layout changes
per editor build). Output is Spine 3.8 JSON shaped for spine-player 3.8
(list-of-skins, legacy 4-field curves `curve/c2/c3/c4`, deform deltas).

Down-conversion notes (4.2 -> 3.8):
  - Timeline VALUE semantics are identical (rotate/translate/shear are deltas
    from setup, scale is a setup multiplier), so values copy straight across.
  - 4.2 beziers store ABSOLUTE control points per component; 3.8 wants ONE
    normalized curve per frame. We normalize the component with the largest
    value span (the visually dominant one) — exact when components share a
    curve, an approximation otherwise (warned).
  - 4.2 single-axis timelines (translatex/y, scalex/y, shearx/y) and the
    alpha/rgb slot timelines have no 3.8 equivalent; they are merged into the
    combined 3.8 timeline by sampling the missing components (bezier-exact at
    keyframes, curve approximated on split segments; warned).
  - Physics constraints/timelines, inherit timelines, sequences and sequence
    timelines have no 3.8 representation: parsed (to keep the stream aligned)
    and dropped with a warning.

Usage:
    python skel42_to_json38.py <input.skel|input.scsp> <output.json>
"""
from __future__ import annotations
import json
import struct
import sys
from pathlib import Path

# ---------------------------------------------------------------- bin reader

class Bin:
    """Big-endian reader mirroring spine-core 4.2 BinaryInput."""
    def __init__(self, data: bytes):
        self.d = data
        self.i = 0
        self.strings: list[str] = []

    def byte(self) -> int:  # signed
        v = self.d[self.i]; self.i += 1
        return v - 256 if v >= 128 else v

    def ubyte(self) -> int:
        v = self.d[self.i]; self.i += 1
        return v

    def bool_(self) -> bool:
        return self.ubyte() != 0

    def int32(self) -> int:
        v = struct.unpack_from(">i", self.d, self.i)[0]; self.i += 4
        return v

    def float_(self) -> float:
        v = struct.unpack_from(">f", self.d, self.i)[0]; self.i += 4
        return v

    def varint(self, optimize_positive: bool = True) -> int:
        b = self.ubyte()
        result = b & 0x7F
        if b & 0x80:
            b = self.ubyte(); result |= (b & 0x7F) << 7
            if b & 0x80:
                b = self.ubyte(); result |= (b & 0x7F) << 14
                if b & 0x80:
                    b = self.ubyte(); result |= (b & 0x7F) << 21
                    if b & 0x80:
                        b = self.ubyte(); result |= (b & 0x7F) << 28
        result &= 0xFFFFFFFF
        if optimize_positive:
            return result
        return (result >> 1) ^ -(result & 1)

    def string(self) -> str | None:
        n = self.varint(True)
        if n == 0:
            return None
        if n == 1:
            return ""
        n -= 1
        s = self.d[self.i:self.i + n].decode("utf-8")
        self.i += n
        return s

    def string_ref(self) -> str | None:
        idx = self.varint(True)
        return None if idx == 0 else self.strings[idx - 1]

    def float_array(self, n: int) -> list[float]:
        out = list(struct.unpack_from(f">{n}f", self.d, self.i))
        self.i += 4 * n
        return out

    def varint_array(self, n: int) -> list[int]:
        return [self.varint(True) for _ in range(n)]


# ----------------------------------------------------------------- constants

BONE_ROTATE, BONE_TRANSLATE, BONE_TRANSLATEX, BONE_TRANSLATEY = 0, 1, 2, 3
BONE_SCALE, BONE_SCALEX, BONE_SCALEY = 4, 5, 6
BONE_SHEAR, BONE_SHEARX, BONE_SHEARY, BONE_INHERIT = 7, 8, 9, 10
SLOT_ATTACHMENT, SLOT_RGBA, SLOT_RGB, SLOT_RGBA2, SLOT_RGB2, SLOT_ALPHA = range(6)
ATTACHMENT_DEFORM, ATTACHMENT_SEQUENCE = 0, 1
PATH_POSITION, PATH_SPACING, PATH_MIX = 0, 1, 2
PHYSICS_RESET = 8
CURVE_LINEAR, CURVE_STEPPED, CURVE_BEZIER = 0, 1, 2

INHERIT = ["normal", "onlyTranslation", "noRotationOrReflection",
           "noScale", "noScaleOrReflection"]
BLEND = ["normal", "additive", "multiply", "screen"]
POSITION_MODE = ["fixed", "percent"]
SPACING_MODE = ["length", "fixed", "percent", "proportional"]
ROTATE_MODE = ["tangent", "chain", "chainScale"]

def _hex8(rgba8888: int) -> str:
    return format(rgba8888 & 0xFFFFFFFF, "08x")

def _hex6(rgb888: int) -> str:
    return format(rgb888 & 0xFFFFFF, "06x")

def _r(v: float, p: int = 5) -> float:
    """Round, collapsing -0.0 and float32 noise for compact output."""
    v = round(v, p)
    return 0.0 if v == 0 else v


# -------------------------------------------------------------------- curves
# A segment curve is None (linear), 'stepped', or a list of per-component
# (cx1, cy1, cx2, cy2) absolute control points.

def _read_bezier(b: Bin) -> tuple[float, float, float, float]:
    return (b.float_(), b.float_(), b.float_(), b.float_())

def _bezier_y_at(t, t1, v1, t2, v2, cx1, cy1, cx2, cy2):
    """Evaluate the cubic bezier ((t1,v1),(cx1,cy1),(cx2,cy2),(t2,v2)) at time t."""
    lo, hi = 0.0, 1.0
    for _ in range(40):
        u = (lo + hi) / 2
        w = 1 - u
        x = w*w*w*t1 + 3*w*w*u*cx1 + 3*w*u*u*cx2 + u*u*u*t2
        if x < t:
            lo = u
        else:
            hi = u
    u = (lo + hi) / 2
    w = 1 - u
    return w*w*w*v1 + 3*w*w*u*cy1 + 3*w*u*u*cy2 + u*u*u*v2

def _norm_curve(frame: dict, comps: list[tuple[float, float, tuple]],
                t1: float, t2: float) -> None:
    """Attach the legacy 4-field 3.8 curve to `frame`, normalized from the
    dominant component. comps = [(v1, v2, (cx1,cy1,cx2,cy2)), ...]."""
    if not comps:
        return
    v1, v2, (cx1, cy1, cx2, cy2) = max(comps, key=lambda c: abs(c[1] - c[0]))
    dt = t2 - t1
    dv = v2 - v1
    nx1 = (cx1 - t1) / dt if dt else 0.0
    nx2 = (cx2 - t1) / dt if dt else 0.0
    if dv:
        ny1 = (cy1 - v1) / dv
        ny2 = (cy2 - v1) / dv
    else:
        ny1, ny2 = nx1, nx2  # flat segment: any curve is visually identical
    frame["curve"] = _r(min(max(nx1, 0.0), 1.0), 4)
    frame["c2"] = _r(ny1, 4)
    frame["c3"] = _r(min(max(nx2, 0.0), 1.0), 4)
    frame["c4"] = _r(ny2, 4)


# --------------------------------------------------- generic timeline frames
# Parsed timelines are (frames, curves): frames = [(time, [v0, v1, ...])],
# curves[i] applies between frames[i] and frames[i+1].

def _read_timeline(b: Bin, frame_count: int, dim: int):
    frames, curves = [], []
    t = b.float_()
    vals = [b.float_() for _ in range(dim)]
    for f in range(frame_count):
        frames.append((t, vals))
        if f == frame_count - 1:
            break
        t2 = b.float_()
        vals2 = [b.float_() for _ in range(dim)]
        ct = b.byte()
        if ct == CURVE_STEPPED:
            curves.append("stepped")
        elif ct == CURVE_BEZIER:
            curves.append([_read_bezier(b) for _ in range(dim)])
        else:
            curves.append(None)
        t, vals = t2, vals2
    return frames, curves


def _sample(frames, curves, comp: int, t: float) -> float:
    """Value of component `comp` at time t (bezier-exact inside segments)."""
    if not frames:
        return 0.0
    if t <= frames[0][0]:
        return frames[0][1][comp]
    if t >= frames[-1][0]:
        return frames[-1][1][comp]
    for i in range(len(frames) - 1):
        t1, v1s = frames[i]
        t2, v2s = frames[i + 1]
        if t1 <= t <= t2:
            if t == t1:
                return v1s[comp]
            if t == t2:
                return v2s[comp]
            c = curves[i] if i < len(curves) else None
            if c == "stepped":
                return v1s[comp]
            if isinstance(c, list):
                cx1, cy1, cx2, cy2 = c[comp]
                return _bezier_y_at(t, t1, v1s[comp], t2, v2s[comp],
                                    cx1, cy1, cx2, cy2)
            if t2 == t1:
                return v1s[comp]
            w = (t - t1) / (t2 - t1)
            return v1s[comp] * (1 - w) + v2s[comp] * w
    return frames[-1][1][comp]


def _merge_groups(groups, out_dim: int, defaults, warn, label: str):
    """Merge component-group timelines into one out_dim-component timeline.

    groups = [(comp_indices, frames, curves), ...]; components not covered by
    any group stay at their default. Returns (frames, curves).
    """
    if len(groups) == 1 and len(groups[0][0]) == out_dim:
        return groups[0][1], groups[0][2]
    times = sorted({t for _, fr, _ in groups for t, _ in fr})
    covered = {c: (idx, fr, cu) for idx, fr, cu in groups for c in idx}
    out_frames = []
    for t in times:
        vals = list(defaults)
        for c in range(out_dim):
            g = covered.get(c)
            if g is not None:
                idx, fr, cu = g
                vals[c] = _sample(fr, cu, idx.index(c), t)
        out_frames.append((t, vals))
    # Per-segment curve: only when every covering group has the segment's two
    # boundary times as adjacent keyframes; otherwise linear (approximation).
    out_curves = []
    approx = False
    for i in range(len(times) - 1):
        t1, t2 = times[i], times[i + 1]
        seg_curve = None
        exact = True
        comps = []
        stepped = False
        for idx, fr, cu in groups:
            ftimes = [ft for ft, _ in fr]
            if t1 in ftimes:
                j = ftimes.index(t1)
                if j + 1 < len(ftimes) and ftimes[j + 1] == t2:
                    c = cu[j] if j < len(cu) else None
                    if c == "stepped":
                        stepped = True
                    elif isinstance(c, list):
                        for k, comp in enumerate(idx):
                            comps.append((comp, fr[j][1][k], fr[j + 1][1][k], c[k]))
                    continue
            if any(t1 < ft < t2 for ft in ftimes) or (ftimes and ftimes[0] < t2 and ftimes[-1] > t1):
                exact = False
        if stepped:
            seg_curve = "stepped"
        elif comps and exact:
            seg_curve = [(v1, v2, bez) for _, v1, v2, bez in comps]
            seg_curve = ("picked", seg_curve)
        elif comps:
            approx = True
        out_curves.append(seg_curve)
    if approx:
        warn(f"{label}: non-aligned single-axis keyframes; some segment curves "
             f"approximated as linear")
    return out_frames, out_curves


def _emit_frames(frames, curves, build_fields) -> list[dict]:
    """Assemble 3.8 JSON frames. build_fields(vals) -> dict of value fields."""
    out = []
    for i, (t, vals) in enumerate(frames):
        f = {"time": _r(t)} if t else {}
        f.update(build_fields(vals))
        c = curves[i] if i < len(curves) else None
        if c == "stepped":
            f["curve"] = "stepped"
        elif isinstance(c, tuple) and c[0] == "picked":
            t2 = frames[i + 1][0]
            _norm_curve(f, c[1], t, t2)
        elif isinstance(c, list):
            t2 = frames[i + 1][0]
            comps = [(vals[k], frames[i + 1][1][k], c[k]) for k in range(len(vals))]
            _norm_curve(f, comps, t, t2)
        out.append(f)
    return out


# ----------------------------------------------------------------- converter

class Skel42Converter:
    def __init__(self, data: bytes):
        self.b = Bin(data)
        self.warnings: list[str] = []
        self.out: dict = {}
        self.bones: list[dict] = []
        self.slots: list[dict] = []
        self.slot_setup_color: list[str] = []
        self.ik_names: list[str] = []
        self.tc_names: list[str] = []
        self.pc_names: list[str] = []
        self.pc_modes: list[tuple[str, str]] = []
        self.phys_names: list[str] = []
        self.skin_names: list[str] = []
        self.skins_json: list[dict] = []
        self.linked_fixups: list[tuple[dict, int]] = []
        self.nonessential = False

    def warn(self, msg: str):
        self.warnings.append(msg)
        sys.stderr.write(f"[skel42] WARN {msg}\n")

    # ---- top level ----------------------------------------------------
    def convert(self) -> dict:
        b = self.b
        low = b.int32(); high = b.int32()
        version = b.string() or ""
        skel = {
            "hash": format(high & 0xFFFFFFFF, "x") + format(low & 0xFFFFFFFF, "x")
                    if (low or high) else "",
            "spine": "3.8.99",  # what the cached 3.8 player expects
            "x": _r(b.float_()), "y": _r(b.float_()),
            "width": _r(b.float_()), "height": _r(b.float_()),
        }
        b.float_()  # referenceScale — no 3.8 equivalent
        self.nonessential = b.bool_()
        if self.nonessential:
            skel["fps"] = _r(b.float_())
            skel["images"] = b.string() or ""
            skel["audio"] = b.string() or ""
        self.out["skeleton"] = skel
        self.out["_e7_spine42_source"] = version  # provenance marker
        if not version.startswith("4.2"):
            self.warn(f"source version is {version!r}, expected 4.2.x — "
                      f"format may not match")

        for _ in range(b.varint()):
            s = b.string()
            if s is None:
                raise ValueError("null string in string table")
            b.strings.append(s)

        self._read_bones()
        self._read_slots()
        self._read_ik()
        self._read_transform_constraints()
        self._read_path_constraints()
        self._read_physics_constraints()

        default_skin = self._read_skin(default=True)
        if default_skin:
            self.skins_json.append(default_skin)
            self.skin_names.append("default")
        for _ in range(b.varint()):
            skin = self._read_skin(default=False)
            self.skins_json.append(skin)
            self.skin_names.append(skin["name"])
        for att, skin_idx in self.linked_fixups:
            att["skin"] = self.skin_names[skin_idx]
        self.out["skins"] = self.skins_json

        self._read_events()
        anims = {}
        for _ in range(b.varint()):
            name = b.string()
            anims[name] = self._read_animation()
        self.out["animations"] = anims
        if self.warnings:
            self.out["_e7_spine42_warnings"] = self.warnings
        return self.out

    # ---- skeleton blocks ----------------------------------------------
    def _read_bones(self):
        b = self.b
        for i in range(b.varint()):
            name = b.string()
            parent = None if i == 0 else self.bones[b.varint()]["name"]
            d: dict = {"name": name}
            if parent is not None:
                d["parent"] = parent
            rotation = b.float_(); x = b.float_(); y = b.float_()
            sx = b.float_(); sy = b.float_(); shx = b.float_(); shy = b.float_()
            length = b.float_()
            inherit = b.ubyte()
            skin_req = b.bool_()
            if rotation: d["rotation"] = _r(rotation)
            if x: d["x"] = _r(x)
            if y: d["y"] = _r(y)
            if sx != 1: d["scaleX"] = _r(sx)
            if sy != 1: d["scaleY"] = _r(sy)
            if shx: d["shearX"] = _r(shx)
            if shy: d["shearY"] = _r(shy)
            if length: d["length"] = _r(length)
            if inherit: d["transform"] = INHERIT[inherit]
            if skin_req: d["skin"] = True
            if self.nonessential:
                b.int32()        # color
                b.string()       # icon
                b.bool_()        # visible
            self.bones.append(d)
        self.out["bones"] = self.bones

    def _read_slots(self):
        b = self.b
        for _ in range(b.varint()):
            name = b.string()
            bone = self.bones[b.varint()]["name"]
            d: dict = {"name": name, "bone": bone}
            color = _hex8(b.int32())
            if color != "ffffffff":
                d["color"] = color
            self.slot_setup_color.append(color)
            dark = b.int32()
            if dark != -1:
                d["dark"] = _hex6(dark)
            att = b.string_ref()
            if att:
                d["attachment"] = att
            blend = b.varint()
            if blend:
                d["blend"] = BLEND[blend]
            if self.nonessential:
                b.bool_()  # visible
            self.slots.append(d)
        self.out["slots"] = self.slots

    def _read_ik(self):
        b = self.b
        out = []
        for _ in range(b.varint()):
            name = b.string()
            d: dict = {"name": name, "order": b.varint()}
            d["bones"] = [self.bones[b.varint()]["name"] for _ in range(b.varint())]
            d["target"] = self.bones[b.varint()]["name"]
            flags = b.ubyte()
            if flags & 1: d["skin"] = True
            if not (flags & 2): d["bendPositive"] = False
            if flags & 4: d["compress"] = True
            if flags & 8: d["stretch"] = True
            if flags & 16: d["uniform"] = True
            mix = 1.0
            if flags & 32:
                mix = b.float_() if (flags & 64) else 1.0
            else:
                mix = 0.0
            if mix != 1: d["mix"] = _r(mix)
            if flags & 128:
                d["softness"] = _r(b.float_())
            out.append(d)
            self.ik_names.append(name)
        if out:
            self.out["ik"] = out

    def _read_transform_constraints(self):
        b = self.b
        out = []
        for _ in range(b.varint()):
            name = b.string()
            d: dict = {"name": name, "order": b.varint()}
            d["bones"] = [self.bones[b.varint()]["name"] for _ in range(b.varint())]
            d["target"] = self.bones[b.varint()]["name"]
            flags = b.ubyte()
            if flags & 1: d["skin"] = True
            if flags & 2: d["local"] = True
            if flags & 4: d["relative"] = True
            if flags & 8: d["rotation"] = _r(b.float_())
            if flags & 16: d["x"] = _r(b.float_())
            if flags & 32: d["y"] = _r(b.float_())
            if flags & 64: d["scaleX"] = _r(b.float_())
            if flags & 128: d["scaleY"] = _r(b.float_())
            flags = b.ubyte()
            if flags & 1: d["shearY"] = _r(b.float_())
            mix_rotate = b.float_() if flags & 2 else 0.0
            mix_x = b.float_() if flags & 4 else 0.0
            mix_y = b.float_() if flags & 8 else mix_x
            mix_scale_x = b.float_() if flags & 16 else 0.0
            b.float_() if flags & 32 else None   # mixScaleY (no 3.8 field)
            mix_shear_y = b.float_() if flags & 64 else 0.0
            if mix_y != mix_x:
                self.warn(f"transform constraint {name!r}: mixX {mix_x} != "
                          f"mixY {mix_y}; 3.8 has one translateMix (using mixX)")
            if mix_rotate != 1: d["rotateMix"] = _r(mix_rotate)
            if mix_x != 1: d["translateMix"] = _r(mix_x)
            if mix_scale_x != 1: d["scaleMix"] = _r(mix_scale_x)
            if mix_shear_y != 1: d["shearMix"] = _r(mix_shear_y)
            out.append(d)
            self.tc_names.append(name)
        if out:
            self.out["transform"] = out

    def _read_path_constraints(self):
        b = self.b
        out = []
        for _ in range(b.varint()):
            name = b.string()
            d: dict = {"name": name, "order": b.varint(),
                       "skin": b.bool_()}
            if not d["skin"]:
                del d["skin"]
            d["bones"] = [self.bones[b.varint()]["name"] for _ in range(b.varint())]
            d["target"] = self.slots[b.varint()]["name"]
            flags = b.ubyte()
            pos_mode = POSITION_MODE[flags & 1]
            spacing_mode = SPACING_MODE[(flags >> 1) & 3]
            rotate_mode = ROTATE_MODE[(flags >> 3) & 3]
            if spacing_mode == "proportional":
                self.warn(f"path constraint {name!r}: spacingMode "
                          f"'proportional' (4.x-only) mapped to 'percent'")
                spacing_mode = "percent"
            if pos_mode != "percent": d["positionMode"] = pos_mode
            if spacing_mode != "length": d["spacingMode"] = spacing_mode
            if rotate_mode != "tangent": d["rotateMode"] = rotate_mode
            if flags & 128:
                d["rotation"] = _r(b.float_())
            pos = b.float_(); spacing = b.float_()
            if pos: d["position"] = _r(pos)
            if spacing: d["spacing"] = _r(spacing)
            mr = b.float_(); mx = b.float_(); my = b.float_()
            if my != mx:
                self.warn(f"path constraint {name!r}: mixX {mx} != mixY {my}; "
                          f"3.8 has one translateMix (using mixX)")
            if mr != 1: d["rotateMix"] = _r(mr)
            if mx != 1: d["translateMix"] = _r(mx)
            out.append(d)
            self.pc_names.append(name)
            self.pc_modes.append((pos_mode, spacing_mode))
        if out:
            self.out["path"] = out

    def _read_physics_constraints(self):
        b = self.b
        n = b.varint()
        for _ in range(n):
            name = b.string()
            b.varint()  # order
            b.varint()  # bone
            flags = b.ubyte()
            if flags & 2: b.float_()
            if flags & 4: b.float_()
            if flags & 8: b.float_()
            if flags & 16: b.float_()
            if flags & 32: b.float_()
            if flags & 64: b.float_()
            b.ubyte()                      # step
            b.float_(); b.float_(); b.float_()  # inertia, strength, damping
            if flags & 128: b.float_()     # massInverse
            b.float_(); b.float_()         # wind, gravity
            flags = b.ubyte()
            if flags & 128: b.float_()     # mix
            self.phys_names.append(name)
        if n:
            self.warn(f"{n} physics constraint(s) dropped (no 3.8 equivalent): "
                      f"{', '.join(self.phys_names)}")

    # ---- skins ---------------------------------------------------------
    def _read_skin(self, default: bool) -> dict | None:
        b = self.b
        skin: dict = {}
        if default:
            slot_count = b.varint()
            if slot_count == 0:
                return None
            skin["name"] = "default"
        else:
            skin["name"] = b.string()
            if self.nonessential:
                b.int32()  # color
            bones = [self.bones[b.varint()]["name"] for _ in range(b.varint())]
            if bones:
                skin["bones"] = bones
            ik = [self.ik_names[b.varint()] for _ in range(b.varint())]
            if ik:
                skin["ik"] = ik
            tc = [self.tc_names[b.varint()] for _ in range(b.varint())]
            if tc:
                skin["transform"] = tc
            pc = [self.pc_names[b.varint()] for _ in range(b.varint())]
            if pc:
                skin["path"] = pc
            phys = [self.phys_names[b.varint()] for _ in range(b.varint())]
            if phys:
                self.warn(f"skin {skin['name']!r}: physics constraint refs "
                          f"dropped: {', '.join(phys)}")
            slot_count = b.varint()
        attachments: dict = {}
        for _ in range(slot_count):
            slot_name = self.slots[b.varint()]["name"]
            slot_atts: dict = {}
            for _ in range(b.varint()):
                att_key = b.string_ref()
                att = self._read_attachment(att_key)
                if att is not None:
                    slot_atts[att_key] = att
            attachments[slot_name] = slot_atts
        skin["attachments"] = attachments
        return skin

    def _read_vertices_json(self, weighted: bool):
        """Returns (vertexCount, vertices-as-3.8-JSON)."""
        b = self.b
        vertex_count = b.varint()
        if not weighted:
            return vertex_count, [_r(v) for v in b.float_array(vertex_count * 2)]
        verts: list = []
        for _ in range(vertex_count):
            bone_count = b.varint()
            verts.append(bone_count)
            for _ in range(bone_count):
                bi = b.varint()
                x = b.float_(); y = b.float_(); w = b.float_()
                verts.extend((bi, _r(x), _r(y), _r(w)))
        return vertex_count, verts

    def _read_attachment(self, attachment_key: str) -> dict | None:
        b = self.b
        flags = b.ubyte()
        name = b.string_ref() if (flags & 8) else attachment_key
        atype = flags & 0b111
        d: dict = {}
        if name != attachment_key:
            d["name"] = name
        if atype == 0:  # Region
            path = b.string_ref() if (flags & 16) else None
            color = _hex8(b.int32()) if (flags & 32) else "ffffffff"
            if flags & 64:
                self._skip_sequence(f"region {name!r}")
            rotation = b.float_() if (flags & 128) else 0.0
            x = b.float_(); y = b.float_(); sx = b.float_(); sy = b.float_()
            w = b.float_(); h = b.float_()
            if path and path != name: d["path"] = path
            if x: d["x"] = _r(x)
            if y: d["y"] = _r(y)
            if sx != 1: d["scaleX"] = _r(sx)
            if sy != 1: d["scaleY"] = _r(sy)
            if rotation: d["rotation"] = _r(rotation)
            d["width"] = _r(w); d["height"] = _r(h)
            if color != "ffffffff": d["color"] = color
            return d
        if atype == 1:  # BoundingBox
            count, verts = self._read_vertices_json(bool(flags & 16))
            if self.nonessential:
                b.int32()
            d["type"] = "boundingbox"
            d["vertexCount"] = count
            d["vertices"] = verts
            return d
        if atype == 2:  # Mesh
            path = b.string_ref() if (flags & 16) else name
            color = _hex8(b.int32()) if (flags & 32) else "ffffffff"
            if flags & 64:
                self._skip_sequence(f"mesh {name!r}")
            hull = b.varint()
            count, verts = self._read_vertices_json(bool(flags & 128))
            uvs = [_r(v) for v in b.float_array(count * 2)]
            # 4.2 derives the index count from the vertex ARRAY length
            # (2*vertexCount), not the vertex count: (len - hull - 2) * 3.
            triangles = b.varint_array((count * 2 - hull - 2) * 3)
            d["type"] = "mesh"
            if path and path != name: d["path"] = path
            if color != "ffffffff": d["color"] = color
            d["uvs"] = uvs
            d["triangles"] = triangles
            d["vertices"] = verts
            d["hull"] = hull
            if self.nonessential:
                edges = b.varint_array(b.varint())
                w = b.float_(); h = b.float_()
                d["edges"] = edges
                d["width"] = _r(w); d["height"] = _r(h)
            return d
        if atype == 3:  # LinkedMesh
            path = b.string_ref() if (flags & 16) else name
            color = _hex8(b.int32()) if (flags & 32) else "ffffffff"
            if flags & 64:
                self._skip_sequence(f"linkedmesh {name!r}")
            inherit_timelines = bool(flags & 128)
            skin_index = b.varint()
            parent = b.string_ref()
            if self.nonessential:
                b.float_(); b.float_()
            d["type"] = "linkedmesh"
            if path and path != name: d["path"] = path
            if color != "ffffffff": d["color"] = color
            d["parent"] = parent
            if not inherit_timelines:
                d["deform"] = False
            self.linked_fixups.append((d, skin_index))
            return d
        if atype == 4:  # Path
            closed = bool(flags & 16)
            constant_speed = bool(flags & 32)
            count, verts = self._read_vertices_json(bool(flags & 64))
            lengths = [_r(b.float_()) for _ in range(count * 2 // 6)]
            if self.nonessential:
                b.int32()
            d["type"] = "path"
            if closed: d["closed"] = True
            if not constant_speed: d["constantSpeed"] = False
            d["lengths"] = lengths
            d["vertexCount"] = count
            d["vertices"] = verts
            return d
        if atype == 5:  # Point
            rotation = b.float_(); x = b.float_(); y = b.float_()
            if self.nonessential:
                b.int32()
            d["type"] = "point"
            if x: d["x"] = _r(x)
            if y: d["y"] = _r(y)
            if rotation: d["rotation"] = _r(rotation)
            return d
        if atype == 6:  # Clipping
            end_slot = self.slots[b.varint()]["name"]
            count, verts = self._read_vertices_json(bool(flags & 16))
            if self.nonessential:
                b.int32()
            d["type"] = "clipping"
            d["end"] = end_slot
            d["vertexCount"] = count
            d["vertices"] = verts
            return d
        self.warn(f"unknown attachment type {atype} for {name!r}; dropped — "
                  f"stream is likely desynced")
        return None

    def _skip_sequence(self, what: str):
        b = self.b
        b.varint(); b.varint(); b.varint(); b.varint()
        self.warn(f"{what}: sequence dropped (no 3.8 equivalent; first frame "
                  f"renders statically)")

    # ---- events ---------------------------------------------------------
    def _read_events(self):
        b = self.b
        out = {}
        self.event_names: list[str] = []
        self.event_data: list[dict] = []
        for _ in range(b.varint()):
            name = b.string()
            d: dict = {}
            iv = b.varint(False); fv = b.float_(); sv = b.string()
            audio = b.string()
            if iv: d["int"] = iv
            if fv: d["float"] = _r(fv)
            if sv: d["string"] = sv
            if audio:
                d["audio"] = audio
                d["volume"] = _r(b.float_())
                d["balance"] = _r(b.float_())
            out[name] = d
            self.event_names.append(name)
            self.event_data.append({"audio": bool(audio), "string": sv})
        if out:
            self.out["events"] = out

    # ---- animation -------------------------------------------------------
    def _read_animation(self) -> dict:
        b = self.b
        anim: dict = {}
        b.varint()  # timeline count (unused)

        # Slot timelines.
        slots_out: dict = {}
        for _ in range(b.varint()):
            slot_idx = b.varint()
            slot_name = self.slots[slot_idx]["name"]
            tls = slots_out.setdefault(slot_name, {})
            color_groups: list = tls.setdefault("_color_groups", [])
            for _ in range(b.varint()):
                ttype = b.byte()
                frame_count = b.varint()
                if ttype == SLOT_ATTACHMENT:
                    frames = []
                    for _ in range(frame_count):
                        t = b.float_()
                        n = b.string_ref()
                        f = {"time": _r(t)} if t else {}
                        f["name"] = n
                        frames.append(f)
                    tls["attachment"] = frames
                elif ttype in (SLOT_RGBA, SLOT_RGB, SLOT_ALPHA):
                    b.varint()  # bezier count
                    dim = {SLOT_RGBA: 4, SLOT_RGB: 3, SLOT_ALPHA: 1}[ttype]
                    comp_idx = {SLOT_RGBA: [0, 1, 2, 3], SLOT_RGB: [0, 1, 2],
                                SLOT_ALPHA: [3]}[ttype]
                    frames, curves = self._read_color_timeline(frame_count, dim)
                    color_groups.append((comp_idx, frames, curves))
                elif ttype in (SLOT_RGBA2, SLOT_RGB2):
                    b.varint()  # bezier count
                    dim = 7 if ttype == SLOT_RGBA2 else 6
                    has_alpha = ttype == SLOT_RGBA2
                    frames, curves = self._read_color_timeline(frame_count, dim)
                    setup_a = int(self.slot_setup_color[slot_idx][6:8], 16) / 255
                    out_frames = []
                    for i, (t, v) in enumerate(frames):
                        if has_alpha:
                            r, g, bl, a, r2, g2, b2 = v
                        else:
                            r, g, bl, r2, g2, b2 = v
                            a = setup_a
                        f = {"time": _r(t)} if t else {}
                        f["light"] = "".join(format(int(round(c * 255)), "02x")
                                             for c in (r, g, bl, a))
                        f["dark"] = "".join(format(int(round(c * 255)), "02x")
                                            for c in (r2, g2, b2))
                        c = curves[i] if i < len(curves) else None
                        if c == "stepped":
                            f["curve"] = "stepped"
                        elif isinstance(c, list):
                            t2 = frames[i + 1][0]
                            comps = [(v[k], frames[i + 1][1][k], c[k])
                                     for k in range(dim)]
                            _norm_curve(f, comps, t, t2)
                        out_frames.append(f)
                    tls["twoColor"] = out_frames
                else:
                    raise ValueError(f"unknown slot timeline type {ttype}")
        # Merge color channel groups per slot.
        for slot_name, tls in slots_out.items():
            groups = tls.pop("_color_groups", [])
            if not groups:
                continue
            slot_idx = next(i for i, s in enumerate(self.slots)
                            if s["name"] == slot_name)
            setup = self.slot_setup_color[slot_idx]
            defaults = [int(setup[k:k + 2], 16) / 255 for k in (0, 2, 4, 6)]
            frames, curves = _merge_groups(groups, 4, defaults, self.warn,
                                           f"slot {slot_name!r} color")
            def color_fields(vals):
                return {"color": "".join(
                    format(min(255, max(0, int(round(c * 255)))), "02x")
                    for c in vals)}
            tls["color"] = _emit_frames(frames, curves, color_fields)
        slots_out = {k: v for k, v in slots_out.items() if v}
        if slots_out:
            anim["slots"] = slots_out

        # Bone timelines.
        bones_out: dict = {}
        for _ in range(b.varint()):
            bone_name = self.bones[b.varint()]["name"]
            groups: dict = {"translate": [], "scale": [], "shear": []}
            tls: dict = {}
            for _ in range(b.varint()):
                ttype = b.byte()
                frame_count = b.varint()
                if ttype == BONE_INHERIT:
                    for _ in range(frame_count):
                        b.float_(); b.byte()
                    self.warn(f"bone {bone_name!r}: inherit timeline dropped "
                              f"(no 3.8 equivalent)")
                    continue
                b.varint()  # bezier count
                dim = 2 if ttype in (BONE_TRANSLATE, BONE_SCALE, BONE_SHEAR) else 1
                frames, curves = _read_timeline(b, frame_count, dim)
                if ttype == BONE_ROTATE:
                    tls["rotate"] = _emit_frames(
                        frames, curves, lambda v: {"angle": _r(v[0])})
                elif ttype in (BONE_TRANSLATE, BONE_TRANSLATEX, BONE_TRANSLATEY):
                    idx = {BONE_TRANSLATE: [0, 1], BONE_TRANSLATEX: [0],
                           BONE_TRANSLATEY: [1]}[ttype]
                    groups["translate"].append((idx, frames, curves))
                elif ttype in (BONE_SCALE, BONE_SCALEX, BONE_SCALEY):
                    idx = {BONE_SCALE: [0, 1], BONE_SCALEX: [0],
                           BONE_SCALEY: [1]}[ttype]
                    groups["scale"].append((idx, frames, curves))
                elif ttype in (BONE_SHEAR, BONE_SHEARX, BONE_SHEARY):
                    idx = {BONE_SHEAR: [0, 1], BONE_SHEARX: [0],
                           BONE_SHEARY: [1]}[ttype]
                    groups["shear"].append((idx, frames, curves))
                else:
                    raise ValueError(f"unknown bone timeline type {ttype}")
            for kind, defaults in (("translate", [0.0, 0.0]),
                                   ("scale", [1.0, 1.0]),
                                   ("shear", [0.0, 0.0])):
                if not groups[kind]:
                    continue
                frames, curves = _merge_groups(
                    groups[kind], 2, defaults, self.warn,
                    f"bone {bone_name!r} {kind}")
                def xy_fields(vals, _k=kind):
                    d = {}
                    dx, dy = (1.0, 1.0) if _k == "scale" else (0.0, 0.0)
                    if vals[0] != dx: d["x"] = _r(vals[0])
                    if vals[1] != dy: d["y"] = _r(vals[1])
                    return d
                tls[kind] = _emit_frames(frames, curves, xy_fields)
            if tls:
                bones_out[bone_name] = tls
        if bones_out:
            anim["bones"] = bones_out

        # IK constraint timelines.
        ik_out: dict = {}
        for _ in range(b.varint()):
            index = b.varint(); frame_count = b.varint()
            b.varint()  # bezier count
            frames = []
            flags = b.ubyte()
            t = b.float_()
            mix = (b.float_() if (flags & 2) else 1.0) if (flags & 1) else 0.0
            softness = b.float_() if (flags & 4) else 0.0
            for fidx in range(frame_count):
                f = {"time": _r(t)} if t else {}
                if mix != 1: f["mix"] = _r(mix)
                if softness: f["softness"] = _r(softness)
                if not (flags & 8): f["bendPositive"] = False
                if flags & 16: f["compress"] = True
                if flags & 32: f["stretch"] = True
                if fidx == frame_count - 1:
                    frames.append(f)
                    break
                flags = b.ubyte()
                t2 = b.float_()
                mix2 = (b.float_() if (flags & 2) else 1.0) if (flags & 1) else 0.0
                softness2 = b.float_() if (flags & 4) else 0.0
                if flags & 64:
                    f["curve"] = "stepped"
                elif flags & 128:
                    bez_mix = _read_bezier(b)
                    bez_soft = _read_bezier(b)
                    _norm_curve(f, [(mix, mix2, bez_mix),
                                    (softness, softness2, bez_soft)], t, t2)
                frames.append(f)
                t, mix, softness = t2, mix2, softness2
            ik_out[self.ik_names[index]] = frames
        if ik_out:
            anim["ik"] = ik_out

        # Transform constraint timelines.
        tc_out: dict = {}
        for _ in range(b.varint()):
            index = b.varint(); frame_count = b.varint()
            b.varint()  # bezier count
            frames, curves = _read_timeline(b, frame_count, 6)
            name = self.tc_names[index]
            mismatched = any(f[1][1] != f[1][2] for f in frames)
            if mismatched:
                self.warn(f"transform timeline {name!r}: animated mixX != mixY; "
                          f"3.8 translateMix uses mixX")
            def tc_fields(v):
                d = {}
                if v[0] != 1: d["rotateMix"] = _r(v[0])
                if v[1] != 1: d["translateMix"] = _r(v[1])
                if v[3] != 1: d["scaleMix"] = _r(v[3])
                if v[5] != 1: d["shearMix"] = _r(v[5])
                return d
            tc_out[name] = _emit_frames(frames, curves, tc_fields)
        if tc_out:
            anim["transform"] = tc_out

        # Path constraint timelines.
        path_out: dict = {}
        for _ in range(b.varint()):
            index = b.varint()
            name = self.pc_names[index]
            entry = path_out.setdefault(name, {})
            for _ in range(b.varint()):
                ttype = b.byte(); frame_count = b.varint()
                b.varint()  # bezier count
                if ttype == PATH_POSITION:
                    frames, curves = _read_timeline(b, frame_count, 1)
                    entry["position"] = _emit_frames(
                        frames, curves, lambda v: {"position": _r(v[0])})
                elif ttype == PATH_SPACING:
                    frames, curves = _read_timeline(b, frame_count, 1)
                    entry["spacing"] = _emit_frames(
                        frames, curves, lambda v: {"spacing": _r(v[0])})
                elif ttype == PATH_MIX:
                    frames, curves = _read_timeline(b, frame_count, 3)
                    if any(f[1][1] != f[1][2] for f in frames):
                        self.warn(f"path mix timeline {name!r}: mixX != mixY; "
                                  f"3.8 translateMix uses mixX")
                    def mix_fields(v):
                        d = {}
                        if v[0] != 1: d["rotateMix"] = _r(v[0])
                        if v[1] != 1: d["translateMix"] = _r(v[1])
                        return d
                    entry["mix"] = _emit_frames(frames, curves, mix_fields)
        if path_out:
            anim["paths"] = path_out

        # Physics timelines (parse + drop).
        n_phys = b.varint()
        for _ in range(n_phys):
            b.varint()  # index (-1 based)
            for _ in range(b.varint()):
                ttype = b.byte(); frame_count = b.varint()
                if ttype == PHYSICS_RESET:
                    for _ in range(frame_count):
                        b.float_()
                    continue
                b.varint()  # bezier count
                _read_timeline(b, frame_count, 1)
        if n_phys:
            self.warn(f"{n_phys} physics timeline group(s) dropped "
                      f"(no 3.8 equivalent)")

        # Deform (attachment) timelines.
        deform_out: dict = {}
        for _ in range(b.varint()):
            skin_name = self.skin_names[b.varint()]
            skin_entry = deform_out.setdefault(skin_name, {})
            for _ in range(b.varint()):
                slot_name = self.slots[b.varint()]["name"]
                slot_entry = skin_entry.setdefault(slot_name, {})
                for _ in range(b.varint()):
                    att_name = b.string_ref()
                    ttype = b.byte()
                    frame_count = b.varint()
                    if ttype == ATTACHMENT_SEQUENCE:
                        for _ in range(frame_count):
                            b.float_(); b.int32(); b.float_()
                        self.warn(f"sequence timeline on {slot_name}/"
                                  f"{att_name} dropped (no 3.8 equivalent)")
                        continue
                    b.varint()  # bezier count
                    frames = []
                    raw = []
                    t = b.float_()
                    fidx = 0
                    while True:
                        end = b.varint()
                        if end == 0:
                            offset, deform = 0, []
                        else:
                            start = b.varint()
                            offset = start
                            deform = [_r(b.float_()) for _ in range(end)]
                        f = {"time": _r(t)} if t else {}
                        if deform:
                            if offset:
                                f["offset"] = offset
                            f["vertices"] = deform
                        if fidx == frame_count - 1:
                            frames.append(f)
                            break
                        t2 = b.float_()
                        ct = b.byte()
                        if ct == CURVE_STEPPED:
                            f["curve"] = "stepped"
                        elif ct == CURVE_BEZIER:
                            bez = _read_bezier(b)
                            _norm_curve(f, [(0.0, 1.0, bez)], t, t2)
                        frames.append(f)
                        t = t2
                        fidx += 1
                    slot_entry[att_name] = frames
        deform_out = {k: v for k, v in deform_out.items() if any(v.values())}
        if deform_out:
            anim["deform"] = deform_out

        # Draw order timeline.
        n_do = b.varint()
        if n_do:
            do_frames = []
            for _ in range(n_do):
                t = b.float_()
                f = {"time": _r(t)} if t else {}
                offsets = []
                for _ in range(b.varint()):
                    slot_name = self.slots[b.varint()]["name"]
                    offsets.append({"slot": slot_name, "offset": b.varint()})
                if offsets:
                    f["offsets"] = offsets
                do_frames.append(f)
            anim["drawOrder"] = do_frames

        # Event timeline.
        n_ev = b.varint()
        if n_ev:
            ev_frames = []
            for _ in range(n_ev):
                t = b.float_()
                edata_idx = b.varint()
                name = self.event_names[edata_idx]
                f = {"time": _r(t)} if t else {}
                f["name"] = name
                iv = b.varint(False); fv = b.float_(); sv = b.string()
                if iv: f["int"] = iv
                if fv: f["float"] = _r(fv)
                if sv is not None: f["string"] = sv
                if self.event_data[edata_idx]["audio"]:
                    f["volume"] = _r(b.float_())
                    f["balance"] = _r(b.float_())
                ev_frames.append(f)
            anim["events"] = ev_frames
        return anim

    def _read_color_timeline(self, frame_count: int, dim: int):
        """RGBA-family timelines: bytes-per-channel values, shared curve byte,
        per-channel beziers."""
        b = self.b
        frames, curves = [], []
        t = b.float_()
        vals = [b.ubyte() / 255.0 for _ in range(dim)]
        for f in range(frame_count):
            frames.append((t, vals))
            if f == frame_count - 1:
                break
            t2 = b.float_()
            vals2 = [b.ubyte() / 255.0 for _ in range(dim)]
            ct = b.byte()
            if ct == CURVE_STEPPED:
                curves.append("stepped")
            elif ct == CURVE_BEZIER:
                curves.append([_read_bezier(b) for _ in range(dim)])
            else:
                curves.append(None)
            t, vals = t2, vals2
        return frames, curves


# ------------------------------------------------------------------- atlas

def convert_atlas42(text: str) -> str:
    """Spine 4.x atlas text -> 3.8 atlas text.

    4.x:  page name + `key:value` lines (size/filter/pma/scale/repeat), then
          regions as name + `bounds:x,y,w,h` [+ offsets/rotate/index].
    3.8:  page name + size/format/filter/repeat lines, then regions as name +
          rotate/xy/size/orig/offset/index lines. Both formats store the
          ORIGINAL region size with 90-degree packing rotation, so the
          mapping is direct.
    """
    out: list[str] = []
    lines = [ln.rstrip("\n") for ln in text.splitlines()]
    i = 0
    page_open = False

    def flush_region(name, attrs):
        x, y, w, h = (int(v) for v in attrs["bounds"].split(","))
        rot = attrs.get("rotate", "false").strip()
        if rot not in ("false", "true", "90", "0"):
            sys.stderr.write(f"[skel42] WARN atlas region {name!r}: rotate "
                             f"{rot!r} not representable in 3.8 (only 90)\n")
        rotate = "true" if rot in ("true", "90") else "false"
        if "offsets" in attrs:
            ox, oy, ow, oh = (int(v) for v in attrs["offsets"].split(","))
        else:
            ox, oy, ow, oh = 0, 0, w, h
        index = attrs.get("index", "-1")
        out.append(name)
        out.append(f"  rotate: {rotate}")
        out.append(f"  xy: {x}, {y}")
        out.append(f"  size: {w}, {h}")
        out.append(f"  orig: {ow}, {oh}")
        out.append(f"  offset: {ox}, {oy}")
        out.append(f"  index: {index}")

    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue
        if ":" in line:  # stray key:value (shouldn't happen at top level)
            i += 1
            continue
        # collect key:value attrs following this name line
        attrs = {}
        j = i + 1
        while j < len(lines):
            ln = lines[j].strip()
            if not ln or ":" not in ln:
                break
            k, _, v = ln.partition(":")
            attrs[k.strip()] = v.strip()
            j += 1
        if "bounds" in attrs:  # region
            flush_region(line, attrs)
        else:  # page
            size = attrs.get("size", "0,0").replace(",", ", ")
            filt = attrs.get("filter", "Linear,Linear").replace(",", ", ")
            rep = attrs.get("repeat", "none")
            if page_open:
                out.append("")
            out.append(line)
            out.append(f"size: {size}")
            out.append("format: RGBA8888")
            out.append(f"filter: {filt}")
            out.append(f"repeat: {rep}")
            page_open = True
        i = j
    return "\n".join(out) + "\n"


# --------------------------------------------------------------------- entry

def find_skel_payload(data: bytes) -> bytes:
    """Accept a stock .skel, an lz4 .scsp container, or a decompressed body
    with the 16-byte E7 header; return the stock .skel bytes."""
    import re
    # lz4 .scsp container? [u32 dec_len][u32 cmp_len][lz4 body]
    if len(data) >= 8:
        dec_len, cmp_len = struct.unpack("<II", data[:8])
        if cmp_len <= len(data) - 8 and 0 < dec_len < 1 << 30:
            try:
                import lz4.block
                data = lz4.block.decompress(data[8:8 + cmp_len],
                                            uncompressed_size=dec_len)
            except Exception:
                pass  # not lz4 — treat as raw
    m = re.search(rb"4\.\d+\.\d+", data[:256])
    if not m:
        raise ValueError("no Spine 4.x version string near the file head — "
                         "not a 4.x skel/scsp?")
    # version string is preceded by a 1-byte varint length; the 8-byte hash
    # precedes that. (E7 .scsp bodies put a 16-byte header before the skel.)
    start = m.start() - 1 - 8
    if start < 0:
        raise ValueError("version string too close to file head")
    return data[start:]


def convert_skel42(data: bytes) -> dict:
    return Skel42Converter(find_skel_payload(data)).convert()


def main():
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("input", help=".skel or .scsp")
    ap.add_argument("output", help="output .json")
    ap.add_argument("--atlas", nargs=2, metavar=("IN", "OUT"),
                    help="also convert a 4.x .atlas to 3.8 format")
    a = ap.parse_args()
    if a.atlas:
        src, dst = a.atlas
        Path(dst).write_text(convert_atlas42(Path(src).read_text(encoding="utf-8")),
                             encoding="utf-8")
        print(f"[ok] atlas {Path(src).name} -> {Path(dst).name}")
    out = convert_skel42(Path(a.input).read_bytes())
    Path(a.output).parent.mkdir(parents=True, exist_ok=True)
    Path(a.output).write_text(
        json.dumps(out, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8")
    n_anim = len(out.get("animations", {}))
    n_warn = len(out.get("_e7_spine42_warnings", []))
    print(f"[ok] {Path(a.input).name} -> {Path(a.output).name} "
          f"({len(out.get('bones', []))} bones, {len(out.get('slots', []))} slots, "
          f"{n_anim} animations, {n_warn} warnings)")


if __name__ == "__main__":
    main()
