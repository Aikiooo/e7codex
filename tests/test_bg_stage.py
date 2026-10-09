"""Regression tests for tools/bg_stage.py's pure helpers.

The background pipeline leans on three things that are easy to break silently:
the underscore-insensitive name kinship that claims a layer for its scene, the
suffix table that decides draw order, and the merge step's refusal to keep an
attachment whose region is not in the chosen atlas (spine will not load such a
skeleton at all). Run from the repo root:

    python -m pytest tests/ -q
"""
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from tools.bg_stage import (  # noqa: E402
    _lead_token,
    _norm,
    _subseq,
    layer_rank,
    merge_layers,
    parse_atlas,
    rewrite_atlas,
    static_layer,
)


# ── name kinship (assignment rule 1) ─────────────────────────────────────────

@pytest.mark.parametrize("stem, atlas", [
    # The dump separates the scene and its atlas differently; both spellings
    # have to collapse to the same key.
    ("rta006_back",    "rta_006"),
    ("rta_020_front",  "rta_020"),
    ("drptown_0",      "drp_town"),
    ("minetown_light", "minetown"),
])
def test_norm_makes_the_scene_name_see_the_atlas_name(stem, atlas):
    assert _norm(stem).startswith(_norm(atlas))


@pytest.mark.parametrize("stem, expected", [
    ("dis4_back",   "dis4"),
    ("rta006_back", "rta006"),
    # No digit run: the whole (normalized) name is the token, which makes the
    # subsequence test stricter, not looser.
    ("forest_tree", "foresttree"),
    ("back",        "back"),
])
def test_lead_token(stem, expected):
    assert _lead_token(stem) == expected


@pytest.mark.parametrize("tok, name, expected", [
    # the numbered-page case the tie-break exists for
    ("dis1", "disdimension1", True),
    ("dis1", "disdimension2", False),
    ("dis4", "disdimension4", True),
    ("dis4", "disdimension1", False),
    ("chg",  "chaosgate01",   True),
    ("clanmain", "clanmainbgdaya", True),
])
def test_subsequence_kinship(tok, name, expected):
    assert _subseq(tok, name) is expected


# ── draw order ───────────────────────────────────────────────────────────────

def test_layer_rank_orders_the_stack():
    r = lambda s: layer_rank(s, "minetown")[0]
    assert r("minetown_back")  < r("minetown_0")
    assert r("minetown_0")     < r("minetown_tree")
    assert r("minetown_tree")  < r("minetown_light")
    assert r("minetown_light") < r("minetown_fog")
    assert r("minetown_fog")   < r("minetown_front")


def test_layer_rank_numbers_sort_within_a_band():
    assert layer_rank("minetown_back", "minetown") < layer_rank("minetown_back2", "minetown")
    assert layer_rank("minetown_0", "minetown") < layer_rank("minetown_7", "minetown")


def test_unknown_suffix_lands_mid_depth():
    assert layer_rank("minetown_whatever", "minetown")[0] == 55


# ── atlas parsing / rewriting ────────────────────────────────────────────────

ATLAS = (
    "\n"
    "page.png\n"
    "size: 100, 50\n"
    "format: RGBA8888\n"
    "filter: Linear,Linear\n"
    "repeat: none\n"
    "bg_0\n"
    "  rotate: false\n"
    "  xy: 1, 2\n"
    "  size: 10, 20\n"
    "  orig: 10, 20\n"
    "  offset: 0, 0\n"
    "  index: -1\n"
)


def test_parse_atlas_reads_page_and_regions(tmp_path):
    p = tmp_path / "x.atlas"
    p.write_text(ATLAS, encoding="utf-8")
    at = parse_atlas(p)
    assert at["page"] == {"w": 100, "h": 50}
    assert at["regions"] == {"bg_0": {"rot": False, "w": 10, "h": 20}}


def test_rewrite_atlas_keeps_the_leading_blank_line(tmp_path):
    # The atlas format opens with a blank line, which these files carry as a
    # bare CRLF. Rewriting line 0 instead of the first non-blank line leaves the
    # real texture name in place and spine then asks for a .sct.
    src = tmp_path / "x.atlas"
    dst = tmp_path / "out.atlas"
    src.write_text(ATLAS, encoding="utf-8")
    rewrite_atlas(src, dst, "x.png")
    lines = dst.read_text(encoding="utf-8").split("\n")
    assert lines[0] == ""
    assert lines[1] == "x.png"
    assert "page.png" not in dst.read_text(encoding="utf-8")


# ── merge ────────────────────────────────────────────────────────────────────

def _layer(region, extra_region=None):
    atts = {region: {region: {"name": region, "path": region, "width": 10, "height": 10}}}
    if extra_region:
        atts[extra_region] = {extra_region: {"name": extra_region, "path": extra_region,
                                             "width": 4, "height": 4}}
    slots = [{"name": n, "bone": "root", "attachment": n} for n in atts]
    return {
        "bones": [{"name": "root"}],
        "slots": slots,
        "skins": [{"name": "default", "attachments": atts}],
        "animations": {},
    }


def test_merge_keeps_slot_order_and_prefixes_names():
    merged, info = merge_layers("s", [("s_back", _layer("r0")), ("s_front", _layer("r1"))],
                                {"w": 1, "h": 1}, {"r0", "r1"})
    # spine keys a skin's attachments by SLOT name, so the merge keys by the
    # layer's own slot name, prefixed to keep layers from colliding.
    assert [s["name"] for s in merged["slots"]] == ["0_r0", "1_r1"]
    assert [b["name"] for b in merged["bones"]] == ["0_root", "1_root"]
    assert set(merged["skins"][0]["attachments"]) == {"0_r0", "1_r1"}
    assert info["dropped"] == []
    assert merged["_bg"]["layers"] == ["s_back", "s_front"]


def test_merge_drops_attachments_missing_from_the_atlas():
    merged, info = merge_layers("s", [("s_back", _layer("r0", "ghost"))],
                                {"w": 1, "h": 1}, {"r0"})
    assert set(merged["skins"][0]["attachments"]) == {"0_r0"}
    assert [s["name"] for s in merged["slots"]] == ["0_r0"]


def test_merge_drops_a_layer_with_no_surviving_slot():
    # A layer placed by name kinship whose regions all live in a sibling atlas
    # contributes nothing and must not leave an empty slot behind.
    merged, info = merge_layers("s", [("s_back", _layer("r0")), ("s_x", _layer("ghost"))],
                                {"w": 1, "h": 1}, {"r0"})
    assert [s["name"] for s in merged["slots"]] == ["0_r0"]
    assert info["dropped"] == ["s_x"]
    assert merged["_bg"]["layers"] == ["s_back"]


def test_merge_always_leaves_one_animation_for_the_player():
    # render_bg.html drives spine-player through setAnimation; a skeleton with
    # no animation at all would never compute a viewport.
    merged, _ = merge_layers("s", [("s_back", _layer("r0"))], {"w": 1, "h": 1}, {"r0"})
    assert list(merged["animations"]) == ["idle"]


# ── db-driven composition ────────────────────────────────────────────────────

def test_static_layer_draws_a_region_with_no_rig():
    lay = static_layer("b0", 40, 12)
    att = lay["skins"][0]["attachments"]["b0"]["b0"]
    assert att["path"] == "b0" and att["width"] == 40 and att["height"] == 12
    assert lay["slots"][0]["attachment"] == "b0"


def test_placed_part_gets_a_container_bone():
    # background_main.db gives each static part x/y/scale; without the container
    # every `<region>.png` part would land on the origin.
    merged, _ = merge_layers("s", [("r0", _layer("r0"))], {"w": 1, "h": 1}, {"r0"},
                             [{"x": 120.0, "y": -40.0, "scale": 1.5, "rotation": 0.0}])
    c = merged["bones"][0]
    assert c["name"] == "c0" and c["x"] == 120.0 and c["y"] == -40.0
    assert c["scaleX"] == 1.5 and c["scaleY"] == 1.5
    assert merged["bones"][1]["parent"] == "c0"


def test_unplaced_part_stays_a_root():
    # A `.scsp` part's own bones are already in scene space: its row's x/y must
    # not be applied on top (arena rendered correctly that way before the table
    # was found, and breaks when the container is added).
    merged, _ = merge_layers("s", [("r0", _layer("r0"))], {"w": 1, "h": 1}, {"r0"}, [None])
    assert merged["bones"][0]["name"] == "0_root"
    assert "parent" not in merged["bones"][0]


def test_merge_restates_the_2_1_27_scale_inheritance_flag():
    # skeleton.e7v21x switches spine-player to 2.1.27 scalar scale inheritance.
    # The merged skeleton is a fresh block, so it has to be re-stated or every
    # child of a scaled bone comes out the wrong size.
    lay = _layer("r0")
    lay["skeleton"] = {"e7v21x": True}
    merged, _ = merge_layers("s", [("r0", lay)], {"w": 1, "h": 1}, {"r0"})
    assert merged["skeleton"]["e7v21x"] is True
    plain, _ = merge_layers("s", [("r0", _layer("r0"))], {"w": 1, "h": 1}, {"r0"})
    assert "e7v21x" not in plain["skeleton"]
