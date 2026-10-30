"""Badges and dates: NEW, MODIFIED, released, ANNOUNCED.

Two of the four are DERIVED from files on disk, one is auto-maintained by the
build, one is hand-declared — all three are documented in
docs/reference/updates_and_packs.md:

  apply_new_flags        maintains data_external/first_seen.json (auto, with the
                         self-bootstrapping sentinel so a namespace rollout does
                         not flood the galleries) -> `new` / `new_since`
  apply_modified_flags   reads the hand-committed data_external/modified.json
                         -> `modified` / `modified_since` / `modified_parts`
  apply_released_dates   reads ../timeline/timeline.json (one dir above the repo,
                         alongside the dump) -> `released`, the hub's sort key
  apply_announced_flags  reads tables.ANNOUNCED -> `announced` / `announce_*`
                         and strips `new` while still pre-banner
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from . import REPO_ROOT
from .tables import ANNOUNCED, MOD_WINDOW_DAYS, NEW_WINDOW_DAYS

def apply_new_flags(units: dict, artifacts: list, emotes: list, wallpapers: list) -> int:
    """Maintain data_external/first_seen.json (id -> first-seen ISO date) and flag
    units (kind=='unit'), artifacts, emote groups, and wallpapers seen within
    NEW_WINDOW_DAYS as `new` (plus `new_since`). Emote/wallpaper ledger keys are
    namespaced (`emote:` / `wp:`) so they can't collide with unit/artifact ids.

    Self-bootstrapping rollout: the first build that introduces a namespace (no
    key of that namespace is in the ledger yet) backdates its whole current batch
    to a sentinel old date, so the rollout does NOT flag every pre-existing asset
    as NEW. From then on a genuinely-new key is recorded at today's date and
    flags for the window — which also catches pre-staged unit releases that show
    as 'changed', not 'added', in the pack diff. The ledger is hand-editable:
    edit a date to extend/clear NEW, or delete an entry to re-flag it on the next
    build. Returns the count flagged."""
    import datetime
    path = REPO_ROOT / "data_external" / "first_seen.json"
    ledger: dict = {}
    if path.exists():
        try: ledger = json.loads(path.read_text(encoding="utf-8"))
        except Exception: ledger = {}
    today = datetime.date.today().isoformat()
    SEED_OLD = "2025-01-01"   # backdate sentinel, well before any NEW window

    def seed(keys: list) -> None:
        # If the ledger already knows ANY of these keys, this namespace has been
        # rolled out → an unseen key is genuinely new (today). If it knows NONE,
        # this is the first build to see them → backdate the batch so nothing
        # floods the gallery with NEW badges.
        d = today if any(k in ledger for k in keys) else SEED_OLD
        for k in keys:
            ledger.setdefault(k, d)

    unit_keys  = [u["id"] for u in units.values() if u.get("kind") == "unit"]
    arti_keys  = [a["id"] for a in artifacts]
    emote_keys = [f"emote:{g['id']}" for g in emotes]
    wp_keys    = [f"wp:{w['file']}"  for w in wallpapers]
    for batch in (unit_keys, arti_keys, emote_keys, wp_keys):
        seed(batch)

    cutoff = (datetime.date.today() - datetime.timedelta(days=NEW_WINDOW_DAYS)).isoformat()
    n = 0
    def flag(obj: dict, key: str) -> None:
        nonlocal n
        if ledger.get(key, "") >= cutoff:
            obj["new"] = True; obj["new_since"] = ledger[key]; n += 1
    for u in units.values():
        if u.get("kind") == "unit": flag(u, u["id"])
    for a in artifacts:  flag(a, a["id"])
    for g in emotes:     flag(g, f"emote:{g['id']}")
    for w in wallpapers: flag(w, f"wp:{w['file']}")
    path.write_text(json.dumps(ledger, ensure_ascii=False, indent=0, sort_keys=True),
                    encoding="utf-8")
    return n


def apply_modified_flags(units: dict) -> int:
    """Flag EXISTING units changed recently (curated, not auto-detected) with
    `modified` / `modified_since` / `modified_parts`, for MOD_WINDOW_DAYS. Source
    is the hand-maintained, COMMITTED ledger data_external/modified.json:

        { "<unit_id>": {"since": "YYYY-MM-DD", "parts": ["intimacy", ...]}, ... }

    Unlike first_seen.json (auto-derived), this is declared: when you add a
    feature to an old unit (e.g. an animated intimacy illustration), add/refresh
    its entry here. The frontend shows a MODIFIED badge on the hub card (floats it
    up, below NEW) and on each named part of the detail page (`modified_parts`).
    Entries older than the window simply stop flagging; leave or prune them.
    Returns the count flagged."""
    import datetime
    path = REPO_ROOT / "data_external" / "modified.json"
    if not path.exists():
        return 0
    try: ledger = json.loads(path.read_text(encoding="utf-8"))
    except Exception: return 0
    cutoff = (datetime.date.today() - datetime.timedelta(days=MOD_WINDOW_DAYS)).isoformat()
    n = 0
    for uid, info in ledger.items():
        u = units.get(uid)
        if not u or not isinstance(info, dict):
            continue
        since = info.get("since", "")
        if since >= cutoff:
            u["modified"] = True
            u["modified_since"] = since
            u["modified_parts"] = info.get("parts", [])
            n += 1
    return n


def apply_released_dates(units: dict) -> int:
    """Stamp each unit with `released` (ISO date) from the hand-curated release
    timeline at ../timeline/timeline.json (one dir above the repo, alongside the
    dump). The frontend hub sorts by this date in its default "Timeline" mode.

    The timeline is keyed by the in-game c-slug (`c1001`, `c2185_1`, …). We match
    a unit's own `id` first (so ML/seasonal/PRIMARY_SWAP `_1` forms get their own
    debut date), then fall back to `base_id` (so a skin like c1046_s02_1 inherits
    its base hero's date). Units with no timeline entry (NPCs, monsters, a few
    collab/test rigs) are left without `released` and the frontend sorts them
    after all dated units. Returns the count stamped."""
    path = REPO_ROOT.parent / "timeline" / "timeline.json"
    if not path.exists():
        return 0
    try:
        tl = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return 0
    date_of: dict[str, str] = {}
    for rel in tl.get("releases", []):
        d = rel.get("date")
        if not d:
            continue
        for h in rel.get("heroes", []):
            hid = h.get("id")
            # First release wins (a hero appears once); guards stray dup ids.
            if hid and hid not in date_of:
                date_of[hid] = d
    n = 0
    for u in units.values():
        d = date_of.get(u.get("id")) or date_of.get(u.get("base_id"))
        if d:
            u["released"] = d
            n += 1
    return n


def _announced_info_for(obj_id: str, base_id: str | None = None) -> dict | None:
    """Lookup ANNOUNCED by exact id, then base_id, then bare c#### peel."""
    if not ANNOUNCED:
        return None
    for key in (obj_id, base_id):
        if key and key in ANNOUNCED:
            return ANNOUNCED[key]
    if obj_id:
        m = re.match(r"^(c\d{4})", obj_id.lower())
        if m and m.group(1) in ANNOUNCED:
            return ANNOUNCED[m.group(1)]
    return None


def apply_announced_flags(units: dict, artifacts: list) -> int:
    """Mark pre-banner public units/artifacts as `announced` (not NEW).

    While today < entry['release'], clear `new` so the hub shows ANNOUNCED
    instead of NEW, and attach optional official `announce_video`. On/after
    release day the flag is omitted — first_seen NEW applies normally.

    Delete (or leave past-dated) ANNOUNCED entries once the window no longer
    matters; stale past-release rows are no-ops. Returns count flagged."""
    import datetime
    if not ANNOUNCED:
        return 0
    today = datetime.date.today().isoformat()
    n = 0

    def apply_one(obj: dict, info: dict) -> None:
        nonlocal n
        rel = (info.get("release") or "").strip()
        if rel and today >= rel:
            return  # live — let NEW badge take over
        obj["announced"] = True
        if rel:
            obj["announce_release"] = rel
        vid = (info.get("video") or "").strip()
        if vid:
            obj["announce_video"] = vid
        # Don't double-badge as NEW while still pre-banner.
        obj.pop("new", None)
        obj.pop("new_since", None)
        n += 1

    for u in units.values():
        info = _announced_info_for(u.get("id") or "", u.get("base_id"))
        # `{}` is a valid entry (announced, no extra metadata) — an empty dict is
        # falsy, so test for None or an entry with no `release` silently never fires.
        if info is not None:
            apply_one(u, info)
    for a in artifacts:
        info = _announced_info_for(a.get("id") or "", None)
        if info is not None:
            apply_one(a, info)
    return n
