"""Regression tests for build_index.py's pure helpers and data-layering rules.

These cover the invariants that have historically been easy to break silently:
variant-suffix ordering, the `_1` extra peeling, name-source precedence, and
the codename matcher. Run from the repo root:

    python -m pytest tests/ -q
"""
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from build_index import (  # noqa: E402
    CODE_RE,
    kebab,
    kind_of,
    load_artifact_db,
    load_event_labels,
    load_name_db,
    split_variant,
    KNOWN_UPDATES,
)


# ── split_variant ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("slug, expected", [
    # plain base slug
    ("c1019",        ("c1019", "", False)),
    # simple variant suffixes
    ("c1019_s01",    ("c1019", "_s01", False)),
    ("c1019_s02",    ("c1019", "_s02", False)),
    ("c1019_m",      ("c1019", "_m", False)),
    ("c1019_m2",     ("c1019", "_m2", False)),
    # longest-first ordering: _m_s01 must NOT be parsed as base "c1019_m" + ???
    ("c1019_m_s01",  ("c1019", "_m_s01", False)),
    # `_1` extra-asset marker peels FIRST, then the variant matches
    ("c1046_s02_1",  ("c1046", "_s02", True)),
    ("c1183_1",      ("c1183", "", True)),
    # extra marker on a moonlight form
    ("c1100_m_1",    ("c1100", "_m", True)),
    # non-variant underscore content stays in the base
    ("npc1467",      ("npc1467", "", False)),
])
def test_split_variant(slug, expected):
    assert split_variant(slug) == expected


def test_split_variant_never_empties_base():
    # A slug that IS a suffix must not produce an empty base.
    base, suf, extra = split_variant("_s01")
    assert base == "_s01" and suf == "" and not extra


# ── kind_of ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("slug, kind", [
    ("c1019",   "unit"),
    ("npc1467", "npc"),
    ("pet0001", "pet"),
    ("af0401",  "artifact"),
    ("m9181",   "monster"),
    ("d0001",   "monster"),
    ("s0001",   "special"),
    ("xyz",     "other"),
])
def test_kind_of(slug, kind):
    assert kind_of(slug) == kind


# ── kebab ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("name, slug", [
    ("Lionheart Cermia",  "lionheart-cermia"),
    ("Rhianna & Luciella", "rhianna-luciella"),
    ("Ainos 2.0",          "ainos-2-0"),
])
def test_kebab(name, slug):
    assert kebab(name) == slug


# ── codename matcher ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("text, codes", [
    ("banner_vsu5aa_01.png",       ["vsu5aa"]),
    ("story_tm_vsu5aa_1/bg.png",   ["vsu5aa"]),
    # must not match inside a longer token
    ("xvsu5aab.png",               []),
    # multiple codenames in one path
    ("vch3aa_and_vva5aa.png",      ["vch3aa", "vva5aa"]),
])
def test_code_re(text, codes):
    assert [c.lower() for c in CODE_RE.findall(text.lower())] == codes


# ── name-source layering (load_name_db) ───────────────────────────────────────

def _write(root: Path, rel: str, obj) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj), encoding="utf-8")


def test_load_name_db_layering(tmp_path):
    # HeroDatabase: canonical kebab _id; rtastats fills gaps but never
    # overrides; names_from_db wins on name/rarity/attribute/role LAST.
    _write(tmp_path, "data_external/HeroDatabase.json", {
        "k1": {"id": "c1019", "_id": "ravi", "name": "Ravi (old)", "rarity": 4},
    })
    _write(tmp_path, "data_external/HeroSkins.json", {
        "ravi": [{"id": "c1019_s01", "name": "Bikini Ravi"}],
    })
    _write(tmp_path, "data_external/HeroNames_rtastats.json", {"heroes": {
        "c1019": {"name": "Ravi RTA"},          # overlap → ignored
        "c2200": {"name": "New Hero", "attribute": "fire"},  # gap → filled
    }})
    _write(tmp_path, "data_external/names_from_db.json", {
        "c1019": {"name": "Ravi", "rarity": 5, "attribute": "dark", "role": "warrior"},
        "c3000": {"name": "DB Only Hero"},
    })

    base, skin = load_name_db(tmp_path)

    # HeroDatabase kept the kebab, names_from_db overwrote name + stats.
    assert base["c1019"]["_id"] == "ravi"
    assert base["c1019"]["name"] == "Ravi"
    assert base["c1019"]["rarity"] == 5
    assert base["c1019"]["attribute"] == "dark"
    # rtastats filled a hero HeroDatabase missed, with a synthesized kebab.
    assert base["c2200"]["name"] == "New Hero"
    assert base["c2200"]["_id"] == "new-hero"
    # db-only hero exists with a synthesized kebab.
    assert base["c3000"]["_id"] == "db-only-hero"
    # skins keyed by full skin id.
    assert skin["c1019_s01"]["name"] == "Bikini Ravi"
    assert skin["c1019_s01"]["_hero_key"] == "ravi"


def test_load_name_db_missing_files(tmp_path):
    base, skin = load_name_db(tmp_path)
    assert base == {} and skin == {}


# ── event labels (load_event_labels) ──────────────────────────────────────────

def test_load_event_labels_db_wins(tmp_path):
    _write(tmp_path, "data_external/codename_labels.json", {
        "vsu5aa": "Intense! Tropical Days!!",
        "vxx9aa": "",                       # empty label → fallback kept/absent
    })
    labels = load_event_labels(tmp_path)
    assert labels["vsu5aa"] == "Intense! Tropical Days!!"   # DB beat KNOWN_UPDATES
    assert "vxx9aa" not in labels                            # empty never lands
    # KNOWN_UPDATES fallback survives for codenames the DB lacks.
    for code, lbl in KNOWN_UPDATES.items():
        if code != "vsu5aa":
            assert labels[code] == lbl


# ── artifact catalog layering (load_artifact_db) ──────────────────────────────

def test_load_artifact_db_layering(tmp_path):
    _write(tmp_path, "data_external/Artifacts.json", {
        "k": {"id": "art0100", "_id": "old-slug", "name": "Community Name", "rarity": 4},
    })
    _write(tmp_path, "data_external/artifacts_from_db.json", {
        "art0100": {"name": "In-Game Name", "rarity": 5, "role": "mage"},
        "art0200": {"name": "DB Only", "rarity": 3},
    })
    db = load_artifact_db(tmp_path)
    # in-game source wins on name/rarity/role; community keeps the kebab.
    assert db["art0100"]["name"] == "In-Game Name"
    assert db["art0100"]["rarity"] == 5
    assert db["art0100"]["role"] == "mage"
    assert db["art0100"]["_id"] == "old-slug"
    # db-only artifact exists without a kebab.
    assert db["art0200"]["name"] == "DB Only"
    assert "_id" not in db["art0200"]


# ── leak-gate slug matching (tools/sync_pack.py) ──────────────────────────────

def test_is_unreleased_matches_costumes():
    # sync_pack.py is not part of the public mirror — skip there.
    sys.path.insert(0, str(REPO / "tools"))
    sync_pack = pytest.importorskip("sync_pack")
    is_unreleased = sync_pack.is_unreleased
    unrel = {"c6023"}
    assert is_unreleased("c6023", unrel)
    assert is_unreleased("c6023_s01", unrel)   # costume of a flagged base
    assert is_unreleased("c6023_1", unrel)     # extra rig of a flagged base
    assert not is_unreleased("c60230", unrel)  # different slug, shared prefix
    assert not is_unreleased("c1019", unrel)
