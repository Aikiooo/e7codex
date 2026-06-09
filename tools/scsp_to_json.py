"""
E7 .scsp → Spine .json (auto-detects 2.1.27 vs 3.8.99).

Delegates to the two third-party converters that already work for each format:
  - 2.1.27.scsp -> epic7_scsp2json_v1_0/epic7_scsp2json.py
  - 3.8.99.scsp -> E7_Scsp2Json.py   (top-level Chinese-language fork)

This script wraps both with a unified CLI and decides which to call by
peeking at the first decompressed-bytes string table for a "spine: VERSION"
literal. If neither matches, we fall back to running the 2.1.27 converter
first (it self-aborts with "New format?" on non-2.1.27 input), then the 3.8.99
one as a fallback.

Usage:
    python scsp_to_json.py <input.scsp> <output.json>
"""
from __future__ import annotations
import argparse, struct, subprocess, sys, tempfile, shutil
from pathlib import Path
import lz4.block

REPO = Path(__file__).resolve().parents[1]
CONV_2_1   = REPO / "epic7_scsp2json_v1_0" / "epic7_scsp2json.py"
CONV_3_8   = REPO / "E7_Scsp2Json.py"   # Chinese-language tool; CWD-sensitive INPUT/OUTPUT paths

def detect_version(scsp: Path) -> str | None:
    """Scan the lz4-decompressed scsp for a Spine version marker.

    Combat rigs in output/model/ carry the marker 2-9 MB into the body
    (after large mesh/animation tables), so a 64KB head-peek misses them.
    Scan the full body; tail-first when the file is large, since the
    skeleton metadata typically sits near the end of the binary.
    """
    data = scsp.read_bytes()
    if len(data) < 8:
        return None
    dec_len = struct.unpack("<I", data[0:4])[0]
    cmp_len = struct.unpack("<I", data[4:8])[0]
    try:
        body = lz4.block.decompress(data[8:8+cmp_len], uncompressed_size=dec_len)
    except Exception:
        return None
    if b"2.1.27.scsp" in body: return "2.1.27"
    if b"3.8.99"      in body: return "3.8.99"
    return None

def convert_2_1(scsp: Path, out_json: Path) -> bool:
    r = subprocess.run([sys.executable, str(CONV_2_1.name), str(scsp.resolve()), str(out_json.resolve())],
                       cwd=str(CONV_2_1.parent), capture_output=True, text=True)
    if r.returncode != 0 or "halted" in r.stdout.lower():
        sys.stderr.write(r.stdout); sys.stderr.write(r.stderr); return False
    return out_json.exists()

def convert_3_8(scsp: Path, out_json: Path) -> bool:
    """E7_Scsp2Json.py reads INPUT_PATH from a constant. Stage the file in a tempdir
    and rewrite the constants for this one run."""
    src = CONV_3_8.read_text(encoding="utf-8")
    with tempfile.TemporaryDirectory() as td:
        td_in  = Path(td) / "in"
        td_out = Path(td) / "out"
        td_in.mkdir(); td_out.mkdir()
        # E7_Scsp2Json reads .scsp + .atlas + .sct together; only .scsp is required
        # for JSON output. Copy whatever sibling files exist.
        for ext in (".scsp", ".atlas", ".sct"):
            sib = scsp.with_suffix(ext)
            if sib.exists(): shutil.copy2(sib, td_in / sib.name)
        # patch the two path constants
        patched = (src
                   .replace('INPUT_PATH = r"D:\\Claude\\E7\\output\\portrait"',
                            f'INPUT_PATH = r"{td_in}"')
                   .replace('OUTPUT_PATH = r"D:\\Claude\\E7\\yes"',
                            f'OUTPUT_PATH = r"{td_out}"'))
        patched_script = Path(td) / "_run.py"
        patched_script.write_text(patched, encoding="utf-8")
        r = subprocess.run([sys.executable, str(patched_script)], capture_output=True, text=True)
        produced = td_out / (scsp.stem + ".json")
        if not produced.exists():
            sys.stderr.write(r.stdout); sys.stderr.write(r.stderr); return False
        out_json.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(produced, out_json)
        return True

def post_process_2_1_27(out_json: Path) -> None:
    """Patch 2.1.27 converter output for spine-player 3.8.99 compatibility.

    Two structural differences make spine-player silently skip all skins:
      1. skeleton.spine = "2.1.27.scsp"  →  must be "3.8.99"
      2. skins block is a dict {name: attachments}  →  must be a list [{name, attachments}]
    Drops residual flipX/flipY fields, and translates Spine 2.x inherit
    booleans (`inheritRotation`/`inheritScale`) to the 3.8 `transform` enum
    so rigs authored with non-default inheritance render correctly.
    """
    import json as _json
    data = _json.loads(out_json.read_text(encoding="utf-8"))

    skel = data.get("skeleton", {})
    if skel.get("spine") == "2.1.27.scsp":
        skel["spine"] = "3.8.99"
    # Flag this rig for the patched spine-player's Spine-2.1.x scalar (shear-free)
    # scale-inheritance path. 2.1.x tracked worldScaleX/Y as SCALARS and rebuilt a
    # clean rotation*scale matrix, so non-uniform parent scale never produced shear.
    # spine-player 3.8 composes full matrices, which accumulate shear from a
    # counter-scaled rotated parent (e.g. c3002 onehanded_ice's b_idle left-arm
    # squash) and explode long-aspect weapon meshes into needles. A no-op for any
    # bone without non-uniform scale under rotation. (2026-06-02 mesh-residual fix.)
    skel["e7v21x"] = True
    data["skeleton"] = skel

    skins = data.get("skins")
    if isinstance(skins, dict):
        data["skins"] = [{"name": k, "attachments": v} for k, v in skins.items()]

    # Translate 2.1.27 inherit booleans to Spine 3.8 `transform` enum. The 3.8
    # runtime ignores `inheritRotation`/`inheritScale`, so all bones authored to
    # NOT inherit their parent's rotation or scale silently revert to "normal"
    # — visible as upside-down heads, broken sword/weapon multi-bone setups,
    # mis-rotated hair strands. The converter only emits the booleans when False
    # (defaults are inheritScale=true, inheritRotation=true), so presence == false.
    for bone in data.get("bones", []):
        bone.pop("flipX", None)
        bone.pop("flipY", None)
        ir_false = bone.pop("inheritRotation", True) is False
        is_false = bone.pop("inheritScale", True) is False
        if ir_false and is_false:
            bone["transform"] = "onlyTranslation"
        elif ir_false:
            bone["transform"] = "noRotationOrReflection"
        elif is_false:
            bone["transform"] = "noScale"

    for anim in data.get("animations", {}).values():
        for bone_anim in anim.get("bones", {}).values():
            bone_anim.pop("flipX", None)
            bone_anim.pop("flipY", None)

    # Mesh fix-ups:
    #  - 2.1.27 stores UVs doubled (part1+part2), so len(uvs)=2*len(vertices). spine-player
    #    treats the mismatch as a weighted mesh and uses vertex coords as bone indices →
    #    JS crash. Truncate uvs to the first half.
    #  - 2.1.27 emits `type:"skinnedmesh"` with separate `bones`/`weights` arrays.
    #    spine-player 3.8 silently returns null for that type. Convert to `type:"mesh"`
    #    with the 3.8 weighted vertex format: vertices = [count, idx,x,y,w, ..., count, ...].
    for skin in data.get("skins", []):
        if not isinstance(skin, dict):
            continue
        for slot_atts in skin.get("attachments", {}).values():
            for att in slot_atts.values():
                t = att.get("type")
                if t == "mesh":
                    verts = att.get("vertices")
                    uvs = att.get("uvs")
                    if isinstance(verts, list) and isinstance(uvs, list) and len(uvs) == 2 * len(verts):
                        att["uvs"] = uvs[:len(verts)]
                elif t == "skinnedmesh":
                    bones = att.get("bones"); weights = att.get("weights")
                    if not (isinstance(bones, list) and isinstance(weights, list)):
                        continue
                    num_verts = 0; bp = 0
                    while bp < len(bones):
                        num_verts += 1
                        bp += 1 + bones[bp]
                    vertices = []; bp = 0; wp = 0
                    while bp < len(bones):
                        cnt = bones[bp]
                        vertices.append(cnt)
                        for k in range(cnt):
                            bi = bones[bp + 1 + k]
                            vertices.extend([bi, weights[wp], weights[wp + 1], weights[wp + 2]])
                            wp += 3
                        bp += 1 + cnt
                    att["type"] = "mesh"
                    att["vertices"] = vertices
                    att.pop("bones", None); att.pop("weights", None)
                    uvs = att.get("uvs")
                    if isinstance(uvs, list) and len(uvs) == 4 * num_verts:
                        att["uvs"] = uvs[:2 * num_verts]

    # Convert bezier curves from the modern array form `curve:[cx1,cy1,cx2,cy2]`
    # to the legacy 4-field form `curve:cx1, c2:cy1, c3:cx2, c4:cy2` — that's what
    # the cached spine-player.js 3.8 build reads. Passing an array as cx1 produces
    # NaN bone transforms → NaN bounds → transparent render.
    def _fix_frames(frames):
        if not isinstance(frames, list): return
        for f in frames:
            if not isinstance(f, dict): continue
            c = f.get("curve")
            if isinstance(c, list) and len(c) == 4:
                f["curve"] = c[0]; f["c2"] = c[1]; f["c3"] = c[2]; f["c4"] = c[3]

    # Build {skin_name: {slot_name: {att_name: att_dict}}} for fast lookup
    # during the deform absolute-to-delta conversion below.
    _e7_skin_index: dict = {}
    for _skin in data.get("skins", []):
        if not isinstance(_skin, dict):
            continue
        _e7_skin_index[_skin.get("name", "")] = _skin.get("attachments", {})

    for anim in data.get("animations", {}).values():
        for tls in anim.get("bones", {}).values():
            for frames in tls.values(): _fix_frames(frames)
        for tls in anim.get("slots", {}).values():
            for frames in tls.values(): _fix_frames(frames)
        for key in ("ik", "transform", "paths"):
            for tls in anim.get(key, {}).values():
                if isinstance(tls, list): _fix_frames(tls)
                elif isinstance(tls, dict):
                    for frames in tls.values(): _fix_frames(frames)
        for key in ("deform", "ffd"):
            for skin_atts in anim.get(key, {}).values():
                for slot_atts in skin_atts.values():
                    for frames in slot_atts.values(): _fix_frames(frames)
        # Rename Spine 2.x `ffd` (free-form deformation) → Spine 3.8 `deform`.
        # Plus: for UNWEIGHTED meshes, convert absolute vertex positions to
        # deltas-from-setup (the 2.1.27 binary stores absolutes here; Spine
        # 3.8 expects deltas and adds setup back at runtime). For WEIGHTED
        # meshes, the per-bone-pair bone-local format is already what
        # spine-player 3.8 expects — leave untouched.
        #
        # Diagnostic that nailed this: c1018's head1 mesh (4-vert quad,
        # verts_len=8) had `ffd` entries identical to its setup vertices at
        # EVERY keyframe of `run` and `b_idle`. If those were already deltas
        # they would be zero (no animation); the fact that they exactly
        # reproduced setup means the binary stored absolutes. spine-player
        # adds setup at line 6157-6160 (skeleton-json.ts readAnimation
        # unweighted-mesh branch), so without subtraction the mesh renders
        # at 2× and collapses (user-reported "face tiny, hair huge halo,
        # hands as pointy stubs" symptom).
        if "ffd" in anim and "deform" not in anim:
            anim["deform"] = anim.pop("ffd")
        if "deform" in anim:
            for skin_name, slot_atts in anim["deform"].items():
                skin_lookup = _e7_skin_index.get(skin_name, {})
                for slot_name, atts in slot_atts.items():
                    slot_lookup = skin_lookup.get(slot_name, {})
                    for att_name, frames in atts.items():
                        att = slot_lookup.get(att_name)
                        if not att:
                            continue
                        setup_verts = att.get("vertices")
                        uvs = att.get("uvs")
                        if not isinstance(setup_verts, list) or not isinstance(uvs, list):
                            continue
                        # Unweighted detector (post UV-truncation): vertex
                        # array is 2 floats per vertex, uvs is 2 floats per
                        # vertex, so equal length means unweighted.
                        if len(setup_verts) != len(uvs):
                            continue
                        for f in frames:
                            v = f.get("vertices")
                            if v is None or len(v) != len(setup_verts):
                                continue
                            delta = [round(v[i] - setup_verts[i], 6) for i in range(len(v))]
                            # 5e-6 absorbs the float64→decimal→subtract noise
                            # (round-to-6 yields literal `1e-06` for values
                            # whose absolutes differed by float-precision LSB).
                            if all(abs(x) < 5e-6 for x in delta):
                                f.pop("vertices", None)  # all-zero delta → omit, spine-player uses setup
                            else:
                                f["vertices"] = delta
        _fix_frames(anim.get("drawOrder"))
        _fix_frames(anim.get("events"))

    # Drop empty timeline arrays. spine-player 3.8's SkeletonJson asserts
    # `frameCount > 0` on every timeline it constructs; a stray empty
    # `bones.<name>.scale: []` (seen on c3143 weapon2.root) crashes load with
    # "frameCount must be > 0". The 2.1.27 converter occasionally emits these
    # when the source ships a zero-length timeline block; pruning here keeps
    # the runtime contract that an entry, if present, has at least one frame.
    def _prune_empty_bone_timelines(anim):
        bones = anim.get("bones")
        if not isinstance(bones, dict):
            return
        for bn in list(bones.keys()):
            tls = bones[bn]
            if not isinstance(tls, dict):
                continue
            for key in list(tls.keys()):
                if isinstance(tls[key], list) and not tls[key]:
                    del tls[key]
            if not tls:
                del bones[bn]
        if not bones:
            anim.pop("bones", None)

    def _prune_empty_slot_timelines(anim):
        slots = anim.get("slots")
        if not isinstance(slots, dict):
            return
        for sn in list(slots.keys()):
            tls = slots[sn]
            if not isinstance(tls, dict):
                continue
            for key in list(tls.keys()):
                if isinstance(tls[key], list) and not tls[key]:
                    del tls[key]
            if not tls:
                del slots[sn]
        if not slots:
            anim.pop("slots", None)

    # Apply E7 mode 9/10 bone-mix-to-setup records (combat rigs only — portrait
    # rigs never trigger this). Each record carries a per-frame mix in [0,1]
    # that blends a specific bone from animation pose (mix=0) toward setup
    # pose (mix=1). Spine 3.8 has no native equivalent for "setup mix"
    # (transform constraints would need a target bone we don't have a
    # declaration for), so we bake the mix directly into the bone's rotate/
    # translate/scale timeline values:
    #   new_value(t) = (1 - mix(t)) * animation_value(t) + mix(t) * setup_value
    # setup_value is 0 for rotate/translate (which store deltas) and 1 for
    # scale (which stores absolute ratios with default 1.0). When the mix
    # timeline keyframes don't align with the bone-timeline keyframes, the
    # mix is linear-interpolated at the bone keyframe times. The bone's
    # curve metadata is preserved unchanged. Verified visually on c1144
    # idle 2026-05-23: head/center/leg bones with mode 9 mix=1 reverted from
    # animated deltas to setup pose, fixing the user-reported "head offset"
    # and splayed-leg symptoms.
    bone_names_e7 = [b.get("name", "") for b in data.get("bones", [])]

    def _e7_mix_at(frames, t):
        if not frames:
            return 0.0
        if t <= frames[0]["time"]:
            return frames[0]["mix"]
        if t >= frames[-1]["time"]:
            return frames[-1]["mix"]
        for i in range(len(frames) - 1):
            f0, f1 = frames[i], frames[i + 1]
            if f0["time"] <= t <= f1["time"]:
                span = f1["time"] - f0["time"]
                if span <= 0:
                    return f0["mix"]
                w = (t - f0["time"]) / span
                return f0["mix"] * (1 - w) + f1["mix"] * w
        return frames[-1]["mix"]

    def _e7_apply_mix_to_bone(timelines, frames):
        for tl_kind in ("rotate", "translate", "scale"):
            tl = timelines.get(tl_kind)
            if not isinstance(tl, list) or not tl:
                continue
            setup = 1.0 if tl_kind == "scale" else 0.0
            for entry in tl:
                t = entry.get("time", 0)
                mix = _e7_mix_at(frames, t)
                if mix <= 0.0001:
                    continue
                if tl_kind == "rotate":
                    a = entry.get("angle", 0)
                    new = (1 - mix) * a + mix * setup
                    if abs(new) < 1e-4:
                        entry.pop("angle", None)
                    else:
                        entry["angle"] = round(new, 4)
                else:
                    for axis in ("x", "y"):
                        v = entry.get(axis, setup)
                        new = (1 - mix) * v + mix * setup
                        if abs(new - setup) < 1e-4:
                            entry.pop(axis, None)
                        else:
                            entry[axis] = round(new, 4)

    # Re-enabled 2026-05-24: the byte-layout sanity check via
    # tools/_dump_mode9_subtype.py confirmed converter's idx(4)+sub_type(4)+
    # count(4)+frames(time,mix) interpretation is correct (every idx resolves
    # to a real bone, sub_type is a constant per-mode flag = 1 for mode 9 and
    # 0 for mode 10). The Ghidra-derived "two float arrays" hypothesis from
    # the late+2 disable is contradicted by that data. c1018 specifically has
    # 17 mode-9 records targeting arm bones (l_shoulder0, l_arm2, l_hend,
    # r_arm0/2, r_hend) with mix=1 keyframes — without the bake, the arms
    # animate freely where the binary says "clamp to setup", producing the
    # "left arm rotates wrong direction" symptom. The late+1 mix-bake-ship
    # saw c1018 still broken, but at that point ffd→deform hadn't shipped
    # yet (late+5), so cloth/skirt/cape artefacts likely masked the arm fix.
    for anim in data.get("animations", {}).values():
        recs = anim.pop("_e7_mix_records", None) or []
        if not recs:
            continue
        bones_tls = anim.get("bones")
        if not isinstance(bones_tls, dict):
            continue
        for rec in recs:
            idx = rec.get("idx", -1)
            if not (0 <= idx < len(bone_names_e7)):
                continue
            bname = bone_names_e7[idx]
            tls = bones_tls.get(bname)
            if not isinstance(tls, dict):
                continue
            _e7_apply_mix_to_bone(tls, rec.get("frames", []))

    # Per-animation drawOrder timeline (2026-05-25, mode-6 revision).
    #
    # The 2.1.27 reader now decodes timeline mode 6 as the DrawOrder timeline.
    # It was previously mislabeled FLIPY and skipped, which BOTH lost the
    # drawOrder data and desynced the item stream (the source of the old
    # "phantom trailer" hack and the ~13 trailer-skip converter crashes). The
    # reader stores, per animation:
    #   _e7_draworder = {"slotCount": N,
    #                    "frames": [{"time": t, "order": [perm of 0..N-1] | None}]}
    # `order` is the full target draw order for that keyframe (None when the
    # frame's flag byte is 0 = setup/identity order). The per-frame times come
    # straight from the file — no more even-distribution guessing, which is
    # what fixes the residual mid-skill drawOrder clip (e.g. Ravi skill1 ~0.5).
    #
    # Spine 3.8 drawOrder is sparse: listed slots get explicit (slot, offset),
    # the rest fill remaining positions in setup index order. The minimal
    # explicit-mover set is the complement of the longest increasing
    # subsequence of `order`. Offsets MUST be sorted by setup slot index
    # ascending or spine-player 3.8 (which walks originalIndex monotonically)
    # throws "RangeError: Invalid array length".
    _E7_EMIT_DRAW_ORDER = True
    import bisect as _bis
    slots_top = data.get("slots", [])
    n_slots_top = len(slots_top)
    setup_slot_names = [s.get("name", "") for s in slots_top]

    def _draworder_offsets(new_order):
        # Sparse (slot, offset) movers = the complement of the longest
        # increasing subsequence of new_order, sorted by setup slot index
        # ascending. Returns [] for an identity order. Patience-sort LIS with
        # parent pointers to recover the actual position set (not just length).
        n_new = len(new_order)
        tails: list[int] = []
        tail_idx: list[int] = []
        parent = [-1] * n_new
        for lis_pos, v in enumerate(new_order):
            k = _bis.bisect_left(tails, v)
            if k == len(tails):
                tails.append(v); tail_idx.append(lis_pos)
            else:
                tails[k] = v; tail_idx[k] = lis_pos
            if k > 0:
                parent[lis_pos] = tail_idx[k - 1]
        lis_positions = set()
        cur = tail_idx[-1] if tail_idx else -1
        while cur != -1:
            lis_positions.add(cur)
            cur = parent[cur]
        movers = []
        for new_pos in range(n_new):
            if new_pos in lis_positions:
                continue
            slot_idx = new_order[new_pos]
            delta = new_pos - slot_idx
            # Emit an offset for EVERY non-LIS slot — including delta==0. A slot
            # whose target position equals its setup index but which is NOT part
            # of the longest increasing subsequence must still be pinned with an
            # explicit (offset 0) entry: otherwise spine-player treats it as
            # "unchanged" and its `unchanged`-fill places it at the wrong spot,
            # cascading every slot after it. That cascade is what pushed Ravi's
            # (c1019) back skirt panel behind her rear-skin slots at t≈0.4-0.5
            # (the reported skill1 clip). Skipping delta==0 is only safe for LIS
            # slots, which are already `continue`d above. With this, the emitted
            # offsets resolve byte-for-byte back to the source permutation on
            # every frame. (2026-06-02 drawOrder roundtrip fix.)
            movers.append((slot_idx, delta))
        movers.sort(key=lambda x: x[0])
        return [{"slot": setup_slot_names[s], "offset": d} for s, d in movers]

    for anim_name, anim in data.get("animations", {}).items():
        anim.pop("_e7_trailer_b64", None)  # legacy capture, superseded by _e7_draworder
        do_rec = anim.pop("_e7_draworder", None)
        if not _E7_EMIT_DRAW_ORDER or not do_rec or n_slots_top < 2:
            continue
        frames = do_rec.get("frames") or []
        if not frames:
            continue
        do_frames = []
        for fr in frames:
            t = fr.get("time", 0)
            order = fr.get("order")
            frame = {"time": t} if t != 0 else {}
            # order is a full permutation of 0..n_slots_top-1 (or None when the
            # frame's flag byte was 0 = setup/identity order at that time).
            if (isinstance(order, list) and len(order) == n_slots_top
                    and sorted(order) == list(range(n_slots_top))):
                offsets = _draworder_offsets(order)
                if offsets:
                    frame["offsets"] = offsets
            do_frames.append(frame)
        # Emit only when something actually reorders. An all-identity drawOrder
        # is a no-op; identity frames are still kept inside do_frames so they
        # reset the order at their timestamp when interleaved with real moves.
        if any("offsets" in f for f in do_frames):
            anim["drawOrder"] = do_frames

    for anim in data.get("animations", {}).values():
        _prune_empty_bone_timelines(anim)
        _prune_empty_slot_timelines(anim)

    out_json.write_text(_json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def convert(scsp: Path, out_json: Path) -> str:
    """Returns the version that was used, or raises."""
    ver = detect_version(scsp)
    order = ("2.1.27", "3.8.99") if ver != "3.8.99" else ("3.8.99", "2.1.27")
    for v in order:
        ok = convert_2_1(scsp, out_json) if v == "2.1.27" else convert_3_8(scsp, out_json)
        if ok:
            if v == "2.1.27":
                post_process_2_1_27(out_json)
            return v
    raise RuntimeError(f"both converters failed for {scsp}")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("scsp"); ap.add_argument("json")
    a = ap.parse_args()
    v = convert(Path(a.scsp), Path(a.json))
    print(f"[ok] {Path(a.scsp).name} -> {Path(a.json).name} (spine {v})")

if __name__ == "__main__":
    main()
