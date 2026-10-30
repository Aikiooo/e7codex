"""Step 5: the Emotes gallery — per-character emote groups.

Two folders feed it: `emoticon/` (animated webp) and `emoticon_chat/` (static
chat sticker png). The filename grammar is `<id>_<theme>_<NNN>`, where `<id>` is
usually a c#### but sometimes a multi-token hero slug (`alki_glasses_001`), so
groups are keyed on everything before the trailing `_<theme>_<NNN>`.
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path


def build_emotes(img: Path, site_assets: Path, units: dict, name_base: dict,
                 guard) -> list[dict]:
    """Copy every emote/sticker into site/assets/_emotes/ and group by character,
    deep-linking each group to a unit where one resolves."""
    # Step 5: emote gallery — img_output/emoticon/<id>_<theme>_001.webp (animated)
    # and img_output/emoticon_chat/<id>_<theme>_001.png (static chat sticker).
    # Filename grammar: <id> is usually c#### but sometimes a hero slug
    # (e.g. alki_glasses_001.png) where the slug part is multi-token. We group
    # entries by everything up to the trailing `_<theme>_<NNN>` segment.
    emotes_dir = site_assets / "_emotes"
    emotes_dir.mkdir(exist_ok=True)
    emote_re = re.compile(r"^(?P<id>.+?)_(?P<theme>[a-z]+)_(?P<n>\d+)\.(?:webp|png)$", re.I)
    emote_groups: dict[str, dict] = {}
    for sub, animated in (("emoticon", True), ("emoticon_chat", False)):
        d = img / sub
        if not d.exists(): continue
        for p in sorted(d.iterdir()):
            m = emote_re.match(p.name)
            if not m: continue
            eid   = m.group("id").lower()
            # Skip icon_c#### duplicates — chat-sticker pngs that mirror the
            # animated c#### emote under a separate id. Always duplicates of
            # an existing bare-id entry; would otherwise appear as a second
            # group for the same character in the gallery.
            if eid.startswith("icon_"):
                continue
            if eid in guard.slugs or guard.refs(eid):
                # Emote art for an unreleased unit — withhold + purge a stale copy.
                dst0 = emotes_dir / p.name
                if dst0.exists():
                    try: dst0.unlink()
                    except OSError: pass
                continue
            theme = m.group("theme").lower()
            dst = emotes_dir / p.name
            if not dst.exists():
                try: shutil.copy2(p, dst)
                except OSError: continue
            rec = emote_groups.setdefault(eid, {"id": eid, "emotes": []})
            rec["emotes"].append({
                "file":     f"assets/_emotes/{p.name}",
                "theme":    theme,
                "animated": animated,
            })
    # Link each group to a known unit if possible (so the gallery can deep-link
    # to the detail page). The character ID in the emote filename is usually
    # c#### but sometimes a hero slug (alki_glasses_001.png). Resolution
    # order: staged unit (links to /#/u/<base>) -> HeroDatabase by id ->
    # HeroDatabase by kebab slug. Name comes from whichever resolves first.
    name_base_by_slug = {v["_id"]: v for v in name_base.values()}
    emotes_list = []
    for eid, rec in sorted(emote_groups.items()):
        lookup = eid
        unit = units.get(lookup) or next(
            (units[s] for s in units if units[s].get("base_id") == lookup), None)
        if unit:
            rec["base_id"]   = unit.get("base_id", unit["id"])
            rec["hero_name"] = unit.get("hero_name") or unit.get("name") or ""
            rec["slug"]      = unit.get("slug") or ""
        elif lookup in name_base:                    # c#### in HeroDatabase
            rec["hero_name"] = name_base[lookup]["name"]
            rec["slug"]      = name_base[lookup]["_id"]
        elif lookup in name_base_by_slug:            # filename uses kebab slug
            rec["hero_name"] = name_base_by_slug[lookup]["name"]
            rec["slug"]      = lookup
        emotes_list.append(rec)
    return emotes_list
