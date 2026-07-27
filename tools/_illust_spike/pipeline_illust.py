"""Automatic multi-layer illust/lobby bake pipeline (stage → alpha_key → bake).

Does NOT launch renders unless you pass an explicit action (still|bake|full).
Default is dry-run / list only so a casual invoke never starts a long bake.

Usage:
  python pipeline_illust.py list
  python pipeline_illust.py list lobby           # lobby packs only
  python pipeline_illust.py discover             # scan effect/*.cfx for illust/lobby stacks
  python pipeline_illust.py dry-run              # all packs
  python pipeline_illust.py dry-run c1153 c6005
  python pipeline_illust.py dry-run vva5aa_lobby # Tori Valentine lobby
  python pipeline_illust.py list deferred        # intro one-shots (later)
  python pipeline_illust.py resolve-order vsu6aa_lobby
  python pipeline_illust.py stage [pack…]        # scsp→json + decode + premultiply
  python pipeline_illust.py alpha-key [pack…]
  python pipeline_illust.py still [pack…]        # E7_STILL_ONLY=1 (lobby) or 1-frame dbg
  python pipeline_illust.py bake [pack…]         # full WebM  **explicit only**
  python pipeline_illust.py full [pack…]         # stage + alpha-key + bake
  python pipeline_illust.py audit-sync [pack…]   # static multi-layer duration/phase audit
  # default pack set for bake/full/stage = all non-deferred; pass ids or 'deferred' / 'all'

Env (encode speed):
  E7_ENCODER=vp9|av1_amf     default vp9
  E7_VP9_CPU_USED=2          faster than libvpx default 0
  E7_LEGACY_CROP=1           use recipes' legacy_crop (screenshot-era; not exact-data)

Framing:
  lobby  → bake_lobby_hq.js world0 + DESIGN res (rank-1)
  intimacy → bake.js slot AABB, crop 0 unless E7_LEGACY_CROP
  z-order → CFX primitive z (rank-2) via cfx_order.py

Multi-layer timing (automatic — no per-pack recipe needed for ambient pairs):
  rec.html __seek phase-locks all layers to max(duration). Near-length ambient
  (e.g. Luluca waves 6s vs body 8s) is time-warped; short particles short-loop.
  Story stacks still set recipe "anim": "story_en" so tears share one timeline.
  audit-sync / bake logs surface mismatches; bakes always go through __seek.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

SPIKE = Path(__file__).resolve().parent
REPO = SPIKE.parents[1]  # E7 Codex
sys.path.insert(0, str(SPIKE))
from cfx_order import EFFECT, merge_order  # noqa: E402

RECIPES_PATH = SPIKE / "recipes.json"


def load_recipes() -> dict:
    return json.loads(RECIPES_PATH.read_text(encoding="utf-8"))


def pack_map(data: dict) -> dict[str, dict]:
    return {p["id"]: p for p in data["packs"]}


def resolve_order(pack: dict) -> list[dict]:
    excl = set(pack.get("exclude") or [])
    return merge_order(pack["cfx"], exclude=excl)


def order_csv(pack: dict) -> str:
    return ",".join(r["source"] for r in resolve_order(pack))


def scales_csv(pack: dict) -> str:
    """Rank-2 CFX primitive scale map: stem:scale pairs for rec.html.

    EffectPlay multiplies CFX `scale` on top of scaleFactor=BASE_SCALE. world0
    framing is DESIGN/BASE_SCALE; omitting scale leaves UI illust panels small
    with dark overscan margins (letterbox). Identity (1.0) omitted from env.
    """
    parts: list[str] = []
    for r in resolve_order(pack):
        sc = r.get("scale", 1.0)
        try:
            scf = float(sc)
        except (TypeError, ValueError):
            continue
        if abs(scf - 1.0) < 1e-6:
            continue
        parts.append(f"{r['source']}:{scf:g}")
    return ",".join(parts)


def stems_of(pack: dict) -> list[str]:
    return [r["source"] for r in resolve_order(pack)]


def stage_dir(pack: dict) -> Path:
    return SPIKE / pack["stage_dir"]


def out_path(pack: dict) -> Path:
    name = pack["out_webm"]
    if pack.get("out_dir"):
        return Path(pack["out_dir"]) / name
    return SPIKE / name


def crop_for(pack: dict) -> str:
    if os.environ.get("E7_LEGACY_CROP") == "1" and pack.get("legacy_crop"):
        return pack["legacy_crop"]
    return pack.get("crop") or "0,0,0,0"


def check_cfx(pack: dict) -> list[str]:
    missing = []
    for stem in pack["cfx"]:
        p = EFFECT / f"{stem}.cfx"
        if not p.is_file():
            missing.append(str(p))
    return missing


# Must match rec.html PHASE_NEAR_RATIO — near-length ambient is time-warped
# into the master period instead of early-restart (Luluca waves vs float).
PHASE_NEAR_RATIO = 0.5


def _spine_anim_duration(anim: dict) -> float:
    """Max key time in a Spine JSON animation block (offline estimate)."""
    tmax = 0.0

    def walk(obj: object) -> None:
        nonlocal tmax
        if isinstance(obj, dict):
            t = obj.get("time")
            if t is not None:
                try:
                    tmax = max(tmax, float(t))
                except (TypeError, ValueError):
                    pass
            for v in obj.values():
                walk(v)
        elif isinstance(obj, list):
            for x in obj:
                walk(x)

    walk(anim)
    return tmax


def _pick_idle_anim(names: list[str], want: str | None = None) -> str | None:
    """Mirror rec.html pickIdleAnim (keep in sync when changing preference)."""
    if not names:
        return None
    if want and want in names:
        return want
    if "story_en" in names:
        return "story_en"
    for n in names:
        if n.startswith("story_"):
            return n
    for n in ("animation", "loop", "off_loop", "on", "idle", "normal"):
        if n in names:
            return n
    for n in names:
        if "loop" in n.lower() and not any(
            x in n.lower() for x in ("intro", "enter", "touch", "end")
        ):
            return n
    for n in names:
        low = n.lower()
        if not any(x in low for x in ("intro", "enter", "touch", "end", "delay")):
            return n
    return names[0]


def _phase_policy(dur: float, master: float) -> str:
    if master <= 0 or dur <= 0:
        return "none"
    if abs(dur - master) < 1e-3:
        return "master"
    if dur >= master * PHASE_NEAR_RATIO:
        return "near-stretch"
    return "short-loop"


def audit_pack_sync(pack: dict) -> dict:
    """Static phase/duration audit from staged Spine JSON (no browser).

    Returns a report dict; does not bake. Bakes always use rec.html __seek
    phase-lock — this only surfaces what policy will apply.
    """
    d = stage_dir(pack)
    want = pack.get("anim") or pack.get("idle_anim")
    layers: list[dict] = []
    missing: list[str] = []
    for stem in stems_of(pack):
        jp = d / f"{stem}.json"
        if not jp.is_file():
            missing.append(stem)
            continue
        try:
            data = json.loads(jp.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            missing.append(f"{stem}({e})")
            continue
        anims = data.get("animations") or {}
        names = list(anims.keys())
        pick = _pick_idle_anim(names, want)
        dur = _spine_anim_duration(anims[pick]) if pick and pick in anims else 0.0
        layers.append(
            {
                "stem": stem,
                "anim": pick,
                "dur": dur,
                "anims": names,
            }
        )
    master = max((L["dur"] for L in layers), default=0.0)
    for L in layers:
        L["policy"] = _phase_policy(L["dur"], master)
    anim_names = {L["anim"] for L in layers if L.get("anim")}
    return {
        "id": pack["id"],
        "want": want,
        "master": master,
        "layers": layers,
        "missing": missing,
        "mixed_anim_names": len(anim_names) > 1,
        "anim_names": sorted(n for n in anim_names if n),
        "needs_sync": any(
            L["policy"] in ("near-stretch", "short-loop") for L in layers
        ),
    }


def cmd_audit_sync(packs: list[dict]) -> int:
    """Report multi-layer duration mismatch + phase-lock policy for staged packs."""
    n_mixed = 0
    n_skip = 0
    n_name_mix = 0
    for p in packs:
        rep = audit_pack_sync(p)
        if rep["missing"] and not rep["layers"]:
            print(f"[{rep['id']}] SKIP not staged: {', '.join(rep['missing'][:6])}")
            n_skip += 1
            continue
        parts = [
            f"{L['stem']}={L['anim']}@{L['dur']:.2f}s:{L['policy']}"
            for L in rep["layers"]
        ]
        flag = []
        if rep["needs_sync"]:
            flag.append("AUTO-SYNC")
            n_mixed += 1
        if rep["mixed_anim_names"]:
            flag.append("NAME-MIX")
            n_name_mix += 1
        if rep["missing"]:
            flag.append(f"missing={len(rep['missing'])}")
        tag = (" " + " ".join(flag)) if flag else " uniform"
        want = f" want={rep['want']}" if rep["want"] else ""
        print(
            f"[{rep['id']}] master={rep['master']:.2f}s{want}{tag}\n"
            f"  " + "  ".join(parts)
        )
        if rep["mixed_anim_names"] and not rep["want"]:
            print(
                f"  hint: layers pick different clips {rep['anim_names']}; "
                f"set recipe anim=story_en (or shared name) if FX must share timeline"
            )
    print(
        f"\naudit-sync: {len(packs)} packs, {n_mixed} duration-mixed (phase-lock handles), "
        f"{n_name_mix} name-mixed, {n_skip} unstaged"
    )
    print(
        "Bakes use rec.html phase-lock automatically; re-bake after seek changes. "
        "Story/tears stacks still need recipe \"anim\" for a shared clip name."
    )
    return 0


def check_staged(pack: dict) -> list[str]:
    missing = []
    d = stage_dir(pack)
    for s in stems_of(pack):
        for ext in (".json", ".atlas", ".png"):
            if not (d / f"{s}{ext}").is_file():
                missing.append(f"{pack['stage_dir']}/{s}{ext}")
    return missing


def run(cmd: list[str], *, dry: bool, env: dict | None = None) -> int:
    print("$", " ".join(cmd))
    if dry:
        return 0
    e = os.environ.copy()
    if env:
        e.update({k: str(v) for k, v in env.items() if v is not None})
    r = subprocess.run(cmd, cwd=str(SPIKE), env=e)
    return r.returncode


def cmd_list(data: dict, kind_filter: str | None = None) -> int:
    print(f"{'id':<22} {'kind':<9} {'def':<4} {'label':<38} cfx stems staged")
    print("-" * 105)
    n_show = 0
    for p in data["packs"]:
        if kind_filter == "deferred":
            if not p.get("deferred"):
                continue
        elif kind_filter in ("lobby", "intimacy"):
            if p.get("kind") != kind_filter or p.get("deferred"):
                continue
        elif kind_filter == "active":
            if p.get("deferred"):
                continue
        n_show += 1
        try:
            n = len(stems_of(p))
            miss = len(check_staged(p))
            st = "OK" if miss == 0 else f"need {miss}"
        except Exception as e:
            n, st = "?", f"err:{e}"
        dflag = "yes" if p.get("deferred") else ""
        print(
            f"{p['id']:<22} {p['kind']:<9} {dflag:<4} {p.get('label','')[:38]:<38} "
            f"{len(p['cfx']):>3} {n!s:>5}  {st}"
        )
    print()
    print(f"shown {n_show} / {len(data['packs'])} catalog packs"
          + (f" (filter={kind_filter})" if kind_filter else ""))
    print("Encode defaults: E7_ENCODER=vp9  E7_VP9_CPU_USED=2")
    print("Default bake set = non-deferred. Pass 'deferred' or pack ids for intros.")
    print("Actions that bake: still | bake | full  (list/dry-run/discover never bake)")
    return 0


def cmd_discover() -> int:
    """Scan effect/*.cfx for multi-layer illust/lobby stacks not yet in recipes."""
    import plistlib
    import re

    data = load_recipes()
    known_cfx = set()
    for p in data["packs"]:
        known_cfx.update(p.get("cfx") or [])

    pat = re.compile(
        r"^(uieff_illust|illeff_|uieff_lobbypack|lobby_prequel|"
        r"eff_lobby|eff_overload_lobby)",
        re.I,
    )
    found = []
    for cfx in sorted(EFFECT.glob("*.cfx")):
        if not pat.search(cfx.stem):
            continue
        try:
            d = plistlib.loads(cfx.read_bytes())
        except Exception:
            continue
        prims = []
        for pr in d.get("primitive") or []:
            if pr.get("format") != "spine" or not pr.get("source"):
                continue
            src = pr["source"]
            z = pr.get("z", 0) or 0
            try:
                z = float(z)
            except (TypeError, ValueError):
                z = 0.0
            has = (EFFECT / f"{src}.scsp").is_file()
            prims.append((z, src, has))
        if len(prims) < 2:
            continue
        prims.sort()
        ok = sum(1 for *_, h in prims if h)
        found.append((cfx.stem, prims, ok, cfx.stem in known_cfx))

    print(f"multi-spine illust/lobby CFX under {EFFECT}:\n")
    print(f"{'cfx':<42} layers ok  in_recipes")
    print("-" * 72)
    for name, prims, ok, known in found:
        flag = "yes" if known else "NO"
        print(f"{name:<42} {len(prims):>3}/{ok:<3}  {flag}")
        if not known:
            for z, s, h in prims:
                print(f"    z={z:>7g}  {s}  {'OK' if h else 'MISSING'}")
    print()
    print(f"{sum(1 for *_,k in found if not k)} CFX stacks not yet in recipes.json")
    print("Add them under packs[] then dry-run. No bake launched.")
    return 0


def cmd_dry_run(packs: list[dict]) -> int:
    for p in packs:
        print("=" * 72)
        print(f"[{p['id']}] {p.get('label')}  kind={p['kind']}  bake={p['bake']}")
        miss = check_cfx(p)
        if miss:
            print("  CFX MISSING:", *miss, sep="\n    ")
        rows = resolve_order(p)
        print(f"  CFX order ({len(rows)} layers, back→front):")
        for r in rows:
            print(f"    z={r['z']:>7g}  {r['source']}")
        if p.get("exclude"):
            print(f"  exclude: {p['exclude']}  ({p.get('exclude_reason', '')})")
        print(f"  stage_dir: {p['stage_dir']}/")
        print(f"  order CSV: {order_csv(p)}")
        staged = check_staged(p)
        if staged:
            print(f"  staged: MISSING {len(staged)} files (run: stage {p['id']})")
        else:
            print("  staged: OK")
        print(f"  alpha_key: {p.get('alpha_key', 'auto')} on all stems")
        print(f"  framing: anchor={p.get('anchor')}  crop={crop_for(p)}", end="")
        if p.get("res"):
            print(f"  res={p['res']}", end="")
        sc = scales_csv(p)
        if sc:
            print(f"  cfx_scale={sc}", end="")
        if p.get("anim") or p.get("idle_anim"):
            print(f"  anim={p.get('anim') or p.get('idle_anim')}", end="")
        print()
        print(
            f"  bake: outH={p.get('outH')} fps={p.get('fps')} crf={p.get('crf')} "
            f"workers={p.get('workers')} max_sec={p.get('max_sec', '—')} "
            f"xfade={p.get('xfade', False)}"
        )
        print(f"  out: {out_path(p)}")
        if p.get("site_slug"):
            print(f"  site: assets/{p['site_slug']}/intimacy.webm (finalize separately)")
        if p.get("note"):
            print(f"  note: {p['note']}")
        print(f"  cmd preview:")
        _preview_bake(p)
    print("=" * 72)
    print(f"dry-run complete: {len(packs)} pack(s). No processes launched.")
    return 0


def _preview_bake(p: dict) -> None:
    order = order_csv(p)
    out = str(out_path(p))
    if p["bake"] == "lobby_hq":
        print(
            f"    node bake_lobby_hq.js {p['stage_dir']} {order} {out} "
            f"{p['outH']} {p['fps']} {p['crf']} {p['workers']} "
            f"{p['anchor']} {p.get('res', '1920x1080')}"
        )
    else:
        print(
            f"    node bake.js {p['stage_dir']} {order} {out} "
            f"{p['fps']} {p['anchor']} {p['outH']} {crop_for(p)} "
            f"{p.get('max_sec', 30)} {p['crf']} {p['workers']}"
        )


def _sync_idle_bones(p: dict, dry: bool) -> int:
    """Optional recipe.sync_idle_bones: inject char idle bones into empty FX layers."""
    cfg = p.get("sync_idle_bones")
    if not cfg:
        return 0
    driver = cfg.get("driver")
    targets = cfg.get("targets") or []
    anim = cfg.get("anim") or "animation"
    if not driver or not targets:
        print(f"[{p['id']}] sync_idle_bones missing driver/targets", file=sys.stderr)
        return 1
    return run(
        [
            sys.executable,
            str(SPIKE / "sync_fx_idle_bones.py"),
            p["stage_dir"],
            driver,
            *targets,
            "--anim",
            anim,
        ],
        dry=dry,
    )


def cmd_stage(packs: list[dict], dry: bool) -> int:
    for p in packs:
        stems = stems_of(p)
        if not stems:
            print(f"[{p['id']}] no stems from CFX", file=sys.stderr)
            return 1
        rc = run(
            [sys.executable, str(SPIKE / "stage_layers.py"), p["stage_dir"], *stems],
            dry=dry,
        )
        if rc:
            return rc
        rc = _sync_idle_bones(p, dry)
        if rc:
            return rc
    return 0


def cmd_alpha_key(packs: list[dict], dry: bool) -> int:
    for p in packs:
        stems = stems_of(p)
        # Safe on all stems: stems with no additive slots print n=0.
        rc = run(
            [sys.executable, str(SPIKE / "alpha_key.py"), p["stage_dir"], *stems],
            dry=dry,
        )
        if rc:
            return rc
    return 0


def _bake_env(p: dict, extra: dict | None = None) -> dict:
    env: dict = {}
    sc = scales_csv(p)
    if sc:
        env["E7_LAYER_SCALES"] = sc
    # Shared clip across layers (story_en etc.) — keep tears/FX on face timeline.
    anim = p.get("anim") or p.get("idle_anim")
    if anim:
        env["E7_LAYER_ANIM"] = anim
    if extra:
        env.update(extra)
    return env


def cmd_still(packs: list[dict], dry: bool) -> int:
    for p in packs:
        order = order_csv(p)
        out = str(out_path(p))
        out_path(p).parent.mkdir(parents=True, exist_ok=True)
        if p["bake"] == "lobby_hq":
            env = _bake_env(p, {"E7_STILL_ONLY": "1"})
            rc = run(
                [
                    "node",
                    "bake_lobby_hq.js",
                    p["stage_dir"],
                    order,
                    out,
                    str(p["outH"]),
                    str(p["fps"]),
                    str(p["crf"]),
                    str(p["workers"]),
                    p["anchor"],
                    p.get("res", "1920x1080"),
                ],
                dry=dry,
                env=env,
            )
        else:
            # intimacy: single composite via dbg.js at t=0.5
            still = str(out_path(p)).replace(".webm", "_still.png")
            rc = run(
                [
                    "node",
                    "dbg.js",
                    p["stage_dir"],
                    order,
                    still,
                    "0.5",
                    p["anchor"],
                    crop_for(p),
                    str(p["outH"]),
                ],
                dry=dry,
            )
        if rc:
            return rc
    return 0


def cmd_bake(packs: list[dict], dry: bool) -> int:
    for p in packs:
        order = order_csv(p)
        out = str(out_path(p))
        out_path(p).parent.mkdir(parents=True, exist_ok=True)
        keep = []
        if p.get("xfade"):
            keep = ["--keep-frames"]
        if p["bake"] == "lobby_hq":
            rc = run(
                [
                    "node",
                    "bake_lobby_hq.js",
                    p["stage_dir"],
                    order,
                    out,
                    str(p["outH"]),
                    str(p["fps"]),
                    str(p["crf"]),
                    str(p["workers"]),
                    p["anchor"],
                    p.get("res", "1920x1080"),
                    *keep,
                ],
                dry=dry,
                env=_bake_env(p),
            )
        else:
            # bake.js writes relative to SPIKE unless absolute
            rel_out = out
            if not Path(out).is_absolute():
                rel_out = Path(out).name
            rc = run(
                [
                    "node",
                    "bake.js",
                    p["stage_dir"],
                    order,
                    rel_out if not Path(out).is_absolute() else out,
                    str(p["fps"]),
                    p["anchor"],
                    str(p["outH"]),
                    crop_for(p),
                    str(p.get("max_sec", 30)),
                    str(p["crf"]),
                    str(p["workers"]),
                    *keep,
                ],
                dry=dry,
            )
            # bake.js historically joins ROOT/out — move if needed
            if not dry and Path(out).is_absolute():
                produced = SPIKE / Path(out).name
                if produced.is_file() and produced.resolve() != Path(out).resolve():
                    produced.replace(Path(out))
                    print(f"  moved {produced.name} -> {out}")

        if rc:
            return rc

        if p.get("xfade") and not dry:
            rc = _xfade(p)
            if rc:
                return rc
        if p.get("post_crop") and not dry:
            rc = _post_crop(p)
            if rc:
                return rc
    return 0


def _xfade(p: dict) -> int:
    """Bake continuation tail + xfadeloop. Requires --keep-frames body dir."""
    # bake.js / bake_lobby_hq.js: _frames_<out webm stem>
    body = SPIKE / ("_frames_" + Path(p["out_webm"]).stem)
    if not body.is_dir():
        candidates = list(SPIKE.glob("_frames_*"))
        print(f"[xfade] body frames not at {body}; candidates: {candidates}")
        return 1
    tail_n = int(p.get("xfade_tail_frames") or 30)
    order = order_csv(p)
    # tail.js: <base> <order> <outDir> <anchor> <crop> <outH> <fps> <start> <count>
    start_t = float(p.get("max_sec") or 14)
    tail_dir = SPIKE / f"_tail_{p['id']}"
    rc = run(
        [
            "node",
            "tail.js",
            p["stage_dir"],
            order,
            str(tail_dir),
            p["anchor"],
            crop_for(p),
            str(p["outH"]),
            str(p["fps"]),
            str(start_t),
            str(tail_n),
        ],
        dry=False,
    )
    if rc:
        return rc
    out = str(out_path(p))
    return run(
        [
            sys.executable,
            str(SPIKE / "xfadeloop.py"),
            str(body),
            str(tail_dir),
            out,
            str(p["fps"]),
            str(p["crf"]),
        ],
        dry=False,
    )


def _post_crop(p: dict) -> int:
    """ffmpeg crop filter e.g. 2380:1080:0:0 (rank-2 residual gap fix for c2185)."""
    spec = p["post_crop"]
    src = out_path(p)
    tmp = src.with_suffix(".precrop.webm")
    if not src.is_file():
        print(f"[post_crop] missing {src}", file=sys.stderr)
        return 1
    src.replace(tmp)
    rc = run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(tmp),
            "-vf",
            f"crop={spec}",
            "-c:v",
            "libvpx-vp9",
            "-crf",
            str(p["crf"]),
            "-b:v",
            "0",
            "-pix_fmt",
            "yuv420p",
            "-an",
            str(src),
        ],
        dry=False,
    )
    if rc == 0:
        tmp.unlink(missing_ok=True)
    return rc


def cmd_full(packs: list[dict], dry: bool) -> int:
    rc = cmd_stage(packs, dry)
    if rc:
        return rc
    rc = cmd_alpha_key(packs, dry)
    if rc:
        return rc
    return cmd_bake(packs, dry)


def main() -> int:
    # Accept --dry-run anywhere (argparse nargs=* + trailing option is flaky).
    argv = [a for a in sys.argv[1:] if a != "--dry-run"]
    dry_flag = "--dry-run" in sys.argv[1:]

    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument(
        "action",
        choices=[
            "list",
            "discover",
            "dry-run",
            "resolve-order",
            "stage",
            "alpha-key",
            "still",
            "bake",
            "full",
            "audit-sync",
        ],
        help="list/discover/dry-run/audit-sync never bake; bake/full require explicit intent",
    )
    ap.add_argument(
        "packs",
        nargs="*",
        help="pack ids (default: all), or kind filter for list (lobby|intimacy).",
    )
    args = ap.parse_args(argv)
    data = load_recipes()
    pm = pack_map(data)

    if args.action == "list":
        kind = (
            args.packs[0]
            if args.packs
            and args.packs[0] in ("lobby", "intimacy", "deferred", "active")
            else None
        )
        return cmd_list(data, kind_filter=kind)

    if args.action == "discover":
        return cmd_discover()

    # Default pack set: all non-deferred (main bake list).
    # Filters: lobby | intimacy | deferred | all | explicit ids
    ids = args.packs
    if not ids:
        packs = [p for p in data["packs"] if not p.get("deferred")]
    elif len(ids) == 1 and ids[0] in ("lobby", "intimacy"):
        packs = [
            p
            for p in data["packs"]
            if p.get("kind") == ids[0] and not p.get("deferred")
        ]
    elif len(ids) == 1 and ids[0] == "deferred":
        packs = [p for p in data["packs"] if p.get("deferred")]
    elif len(ids) == 1 and ids[0] == "all":
        packs = list(data["packs"])
    elif len(ids) == 1 and ids[0] == "active":
        packs = [p for p in data["packs"] if not p.get("deferred")]
    else:
        unknown = [i for i in ids if i not in pm]
        if unknown:
            print(f"unknown pack id(s): {unknown}", file=sys.stderr)
            print(f"known: {', '.join(pm)}", file=sys.stderr)
            return 2
        packs = [pm[i] for i in ids]
    dry = dry_flag or args.action == "dry-run"

    if args.action in ("dry-run",):
        return cmd_dry_run(packs)
    if args.action == "audit-sync":
        return cmd_audit_sync(packs)
    if args.action == "resolve-order":
        for p in packs:
            print(f"# {p['id']}")
            for r in resolve_order(p):
                print(f"{r['z']:>7g}  {r['source']}")
            print(order_csv(p))
            print()
        return 0
    if args.action == "stage":
        return cmd_stage(packs, dry)
    if args.action == "alpha-key":
        return cmd_alpha_key(packs, dry)
    if args.action == "still":
        return cmd_still(packs, dry)
    if args.action == "bake":
        if dry:
            return cmd_dry_run(packs)
        print(
            "WARNING: full bake can take a long time (many GB of frames). "
            "Starting because you asked for action=bake."
        )
        return cmd_bake(packs, dry=False)
    if args.action == "full":
        if dry:
            print("[dry-run] would stage + alpha-key + bake:")
            return cmd_dry_run(packs)
        print(
            "WARNING: full pipeline (stage+akey+bake). "
            "Starting because you asked for action=full."
        )
        return cmd_full(packs, dry=False)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
