"""Loaders for the data_external/*.json the index merges (later layer wins)."""
from __future__ import annotations

import json
from pathlib import Path

from .slugs import kebab
from .tables import KNOWN_UPDATES, MANUAL_NAMES


def load_name_db(root: Path) -> tuple[dict, dict]:
    """Load HeroDatabase + HeroSkins, layer in the rtastats scrape, then
    overlay the in-game names_from_db.json.

    HeroDatabase carries the canonical kebab `_id` used by ceciliabot's URL
    routing (not present in the game data), so it remains the source for that.
    The rtastats fallback fills heroes the snapshot misses (c1144+).

    `names_from_db.json` (built by pipeline/names.py from the game's own
    character_player.db + text.db) is applied LAST and WINS on name / rarity /
    attribute / role — it covers ~700 c-slugs vs HeroDatabase's ~380 and is
    fully self-sufficient (see docs/TASKS.md #42). For c-slugs only the DB
    knows, we synthesise a kebab from the name so a ceciliabot link still has
    the right shape (may 404 on ceciliabot itself). Skin DISPLAY names stay
    with HeroSkins — the DB only carries the base hero's name per costume.
    """
    base: dict[str, dict] = {}
    skin: dict[str, dict] = {}
    p1 = root / "data_external" / "HeroDatabase.json"
    p2 = root / "data_external" / "HeroSkins.json"
    p3 = root / "data_external" / "HeroNames_rtastats.json"
    p4 = root / "data_external" / "names_from_db.json"
    if p1.exists():
        for v in json.loads(p1.read_text("utf-8")).values():
            base[v["id"]] = v
    if p2.exists():
        for hero_key, skin_list in json.loads(p2.read_text("utf-8")).items():
            for s in skin_list:
                skin[s["id"]] = {**s, "_hero_key": hero_key}
    if p3.exists():
        payload = json.loads(p3.read_text("utf-8"))
        for code, rec in payload.get("heroes", {}).items():
            if code in base:
                continue                          # HeroDatabase wins on overlap
            base[code] = {
                "id":   code,
                "_id":  kebab(rec["name"]),
                "name": rec["name"],
                **{k: rec[k] for k in ("attribute", "role") if k in rec},
            }
    if p4.exists():
        for code, rec in json.loads(p4.read_text("utf-8")).items():
            entry = base.get(code)
            if entry is None:
                entry = {"id": code, "_id": kebab(rec["name"])}
                base[code] = entry
            entry["name"] = rec["name"]           # in-game name wins
            for k in ("rarity", "attribute", "role"):
                if k in rec:
                    entry[k] = rec[k]
    for code, rec in MANUAL_NAMES.items():
        if code not in base:
            base[code] = {"id": code, "_id": kebab(rec["name"]), **rec}
    return base, skin


def load_event_labels(root: Path) -> dict[str, str]:
    """Codename -> human event label, merged from the in-game DB and the
    legacy KNOWN_UPDATES fallback.

    `data_external/codename_labels.json` (built by pipeline/codenames.py
    from substory_main.db joined through text.db) carries the proper in-game
    event title for each codename (e.g. vsu5aa -> "Intense! Tropical Days!!").
    KNOWN_UPDATES is kept as the fallback for codenames the DB hasn't picked up
    yet — they still need a heading the user can read.

    Only updates-style codenames (v + 3 chars + 'aa', matching CODE_RE) flow
    into the Updates view. The DB also resolves story-style codenames
    (v1070a -> "My Knight Would Never!") and a handful of irregular shapes;
    those are returned too so future tabs can use them, but the path-token
    matcher in Step 4 deliberately narrows to updates-style.
    """
    labels: dict[str, str] = dict(KNOWN_UPDATES)
    p = root / "data_external" / "codename_labels.json"
    if p.exists():
        for code, lbl in json.loads(p.read_text("utf-8")).items():
            if lbl:
                labels[code] = lbl              # DB WINS on overlap
    return labels


def load_artifact_db(root: Path) -> dict[str, dict]:
    """Load the artifact catalog keyed by in-game id (`art####`).

    Two layers, applied in order; later wins on overlapping fields:

    1. `data_external/Artifacts.json` — community snapshot from ceciliabot
       (`https://ceciliabot.github.io/data/artifacts.json` cached locally).
       Source of `_id` (kebab url slug) and `tags`; neither is in the game data.
    2. `data_external/artifacts_from_db.json` — built by `pipeline/artifacts.py`
       from the game's own `equip_item.db` joined through `text.db`. Source of
       `name`, `rarity`, `role`, and `identifier`. Self-sufficient
       (`[[feedback-self-sufficient]]`) and a few entries ahead of the community
       snapshot when new artifacts ship.
    """
    by_id: dict[str, dict] = {}
    p = root / "data_external" / "Artifacts.json"
    if p.exists():
        for v in json.loads(p.read_text("utf-8")).values():
            gid = v.get("id")
            if isinstance(gid, str) and gid.startswith("art"):
                by_id[gid] = dict(v)   # copy so we can mutate
    # Layer the in-game source LAST: WINS on name/rarity/role + adds identifier.
    p_db = root / "data_external" / "artifacts_from_db.json"
    if p_db.exists():
        for aid, rec in json.loads(p_db.read_text("utf-8")).items():
            cur = by_id.setdefault(aid, {"id": aid})
            for k in ("name", "rarity", "role", "identifier"):
                v = rec.get(k)
                if v not in (None, "", 0):
                    cur[k] = v
    return by_id
