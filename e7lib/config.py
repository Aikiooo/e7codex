"""Central data-dir resolution + the one `voice_keys.json` reader.

Moved verbatim from `e7lib/config.py` (refactor phase 2); the shim is gone as of
phase 3, so every tool imports this module directly.

Every tool resolves the extracted-data roots through here, so the physical
location of the dump lives in ONE place: `private/keys/voice_keys.json`. Defaults
preserve the historical flat layout (`<dump>/output`, `<dump>/img_output`,
`<dump>/_voice_work`), so importing this changes nothing until you set the keys.

To relocate the data (e.g. group everything under `<dump>/extracted_data/`),
set the keys in voice_keys.json and physically move the dirs once — no tool
code changes needed:

    {
      "dump_dir":  "<the folder holding your extracted data>",
      "raw_dir":   "<dump>/extracted_data/output",
      "img_dir":   "<dump>/extracted_data/img_output",
      "voice_dir": "<dump>/extracted_data/_voice_work"
    }

voice_keys.json is gitignored (bring-your-own); the committed
e7lib/voice_keys.example.json documents every key.

The reader is shared by every tool that used to parse that file itself
(`extract_pack.load_config`, `check_pack_state`, the four DB builders), with two
entry points because the tools' error behaviour genuinely differs:

  * load_keys()    — missing file yields {} (every key is optional);
  * require_keys() — missing file is fatal with the tool's own hint text.
"""
from __future__ import annotations

import json
from pathlib import Path

__all__ = [
    "REPO_ROOT", "TOOLS_DIR", "KEYS_PATH",
    "load_keys", "require_keys", "resolve_path", "outer_key_path",
    "DUMP_DIR", "RAW_DIR", "IMG_DIR", "VOICE_DIR", "TREE_DIFF",
    "CDN_WORK_DIR", "GAME_RES_DIR",
]

REPO_ROOT = Path(__file__).resolve().parents[1]
KEYS_DIR = REPO_ROOT / "private" / "keys"      # gitignored, never mirrored
TOOLS_DIR = REPO_ROOT / "tools"                # legacy location of the keys file
# Default dump dir = the folder that contains the repo (this machine keeps the
# dump in the parent directory; any other layout is a `dump_dir` key away).
_DEFAULT_DUMP = REPO_ROOT.parent

KEYS_PATH = KEYS_DIR / "voice_keys.json"


def load_keys() -> dict:
    """Read private/keys/voice_keys.json; a missing file yields {}.

    A malformed file raises json.JSONDecodeError (or OSError) unchanged, so
    callers that log-and-continue keep reporting the same message they did when
    they parsed the file themselves."""
    if not KEYS_PATH.exists():
        return {}
    return json.loads(KEYS_PATH.read_text(encoding="utf-8"))


def require_keys(hint: str) -> dict:
    """load_keys(), but a missing file is fatal. `hint` is the per-tool tail of
    the message ("copy from … setup (…)"), which is why it is a parameter."""
    if not KEYS_PATH.exists():
        raise SystemExit("missing private/keys/voice_keys.json — " + hint)
    return load_keys()


def resolve_path(keys: dict, key: str, default: Path) -> Path:
    v = keys.get(key)
    return Path(v) if v else default


def outer_key_path(keys: dict | None = None) -> Path:
    """Path of the outer-XOR key file. A relative value is relative to the keys
    directory (private/keys/), which is where the key file lives."""
    if keys is None:
        keys = load_keys()
    p = Path(keys["outer_key_file"])
    return p if p.is_absolute() else KEYS_DIR / p


try:                                    # a malformed file must not break imports
    _cfg = load_keys()
except Exception:
    _cfg = {}


DUMP_DIR: Path = resolve_path(_cfg, "dump_dir", _DEFAULT_DUMP)
RAW_DIR: Path = resolve_path(_cfg, "raw_dir", DUMP_DIR / "output")            # raw extracted tree
IMG_DIR: Path = resolve_path(_cfg, "img_dir", DUMP_DIR / "img_output")        # decoded images
VOICE_DIR: Path = resolve_path(_cfg, "voice_dir", DUMP_DIR / "_voice_work")   # voice extraction scratch
TREE_DIFF: Path = resolve_path(_cfg, "tree_diff", DUMP_DIR / "tree_diff.txt")
# CDN tooling scratch tree — the out-of-repo home of cdn_sync.py / cdn_download.py,
# their manifest + policy files, and the downloads themselves. Used by sync_pack
# Stage 1 to refresh voice banks from the CDN media policy.
CDN_WORK_DIR: Path = resolve_path(_cfg, "cdn_work_dir", DUMP_DIR / "_cdn_work")
# The installed client's SSRA store (manifest.ssra + chunks/*.ssrc + patch-meta.json),
# since the 2026-10-29 data.pack -> SSRA migration. READ-ONLY for every tool: never
# write into the game folder. Used by extract_ssra.py as a local chunk source.
# A per-machine location, so it comes from `game_res_dir` in voice_keys.json;
# unset means "no game install configured" (the tools that need it say so).
GAME_RES_DIR: Path | None = (
    Path(_cfg["game_res_dir"]).expanduser() if _cfg.get("game_res_dir") else None
)
