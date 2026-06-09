"""Central data-dir resolution for the E7 Codex pipeline.

Every tool resolves the extracted-data roots through here, so the physical
location of the dump lives in ONE place: `tools/voice_keys.json`. Defaults
preserve the historical flat layout (`<dump>/output`, `<dump>/img_output`,
`<dump>/_voice_work`), so importing this changes nothing until you set the keys.

To relocate the data (e.g. group everything under `<dump>/extracted_data/`),
set the keys in voice_keys.json and physically move the dirs once — no tool
code changes needed:

    {
      "dump_dir":  "D:/Claude/E7",
      "raw_dir":   "D:/Claude/E7/extracted_data/output",
      "img_dir":   "D:/Claude/E7/extracted_data/img_output",
      "voice_dir": "D:/Claude/E7/extracted_data/_voice_work"
    }

voice_keys.json is gitignored (bring-your-own); the committed
voice_keys.example.json documents every key.
"""
from __future__ import annotations

import json
from pathlib import Path

_TOOLS = Path(__file__).resolve().parent
_REPO = _TOOLS.parent
# Default dump dir = the folder that contains the repo (historically D:/Claude/E7).
_DEFAULT_DUMP = _REPO.parent

_CFG_PATH = _TOOLS / "voice_keys.json"


def _load() -> dict:
    if _CFG_PATH.exists():
        try:
            return json.loads(_CFG_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


_cfg = _load()


def _resolve(key: str, default: Path) -> Path:
    v = _cfg.get(key)
    return Path(v) if v else default


DUMP_DIR: Path = _resolve("dump_dir", _DEFAULT_DUMP)
RAW_DIR: Path = _resolve("raw_dir", DUMP_DIR / "output")          # raw extracted tree
IMG_DIR: Path = _resolve("img_dir", DUMP_DIR / "img_output")      # decoded images
VOICE_DIR: Path = _resolve("voice_dir", DUMP_DIR / "_voice_work")  # voice extraction scratch
TREE_DIFF: Path = _resolve("tree_diff", DUMP_DIR / "tree_diff.txt")
