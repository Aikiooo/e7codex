"""Step 4b: artifacts — art staging, names, and the two-way owner links.

The catalog itself comes from `sources.load_artifact_db()` (community snapshot +
the in-game `equip_item.db` join); the two manual overrides in `tables.py` are
for art that ships ahead of that data.

`attach_signature_artifacts` stamps `unit.signature_artifacts[]` for the detail
page and `attach_artifact_owners` stamps `artifact.owner_units[]` for the
Artifacts tab; both read ONE owner map (`data_external/artifact_owners.json`
plus `SIGNATURE_ARTIFACTS`) and drop cross-class pairs.
"""
from __future__ import annotations

import json
import re
import shutil
from collections import defaultdict
from pathlib import Path

from . import REPO_ROOT
from .slugs import kebab
from .tables import CECILIA_ARTIFACT, MANUAL_ARTIFACTS, SIGNATURE_ARTIFACTS, \
    UNRELEASED_ARTIFACTS

# LOCAL-ONLY staging dir for an unreleased unit's artifact art (mirrors
# units_unreleased.json). Held aside by ops/deploy.ps1 and gated behind E7.isLocal.
UNRELEASED_ART_DIR = "_artifacts_unreleased"


def purge_unreleased_artifacts(site_assets: Path) -> None:
    """Drop the local-only held-artifact dir (nothing held this build)."""
    d = site_assets / UNRELEASED_ART_DIR
    if d.exists():
        shutil.rmtree(d, ignore_errors=True)


def stage_artifact_art(img: Path, site_assets: Path, artifact_db: dict,
                       ) -> tuple[list[dict], list[dict]]:
    """Copy art####_fu.png / art####_l.jpg into site/assets/_artifacts/, and the
    held ones into the LOCAL-ONLY _artifacts_unreleased/.

    Orphans (art with no catalog record) get slug-only labels so they still
    appear in the grid — the dump occasionally retains retired art. Returns
    (artifacts_out, artifacts_unrel), both sorted rarity-first."""
    # Step 4b: copy art####_fu.png (portrait full art) + matching art####_l.jpg
    # (horizontal lobby cut); name/rarity/role come from the catalog.
    arti_dir = site_assets / "_artifacts"
    arti_dir.mkdir(exist_ok=True)
    ARTI_ID_RE = re.compile(r"^(art\d+(?:_\d+)?)_(fu\.png|l\.jpg)$", re.I)
    arti_files: dict[str, dict[str, str]] = defaultdict(dict)
    arti_unrel_files: dict[str, dict[str, str]] = defaultdict(dict)
    arti_src = img / "item_arti"
    # LOCAL-ONLY preview dir for held (unreleased-unit) artifacts — mirrors the
    # units_unreleased path. Rebuilt fresh each run so a since-released artifact's
    # art can't linger. Held aside by ops/deploy.ps1 + gated behind E7.isLocal, so it
    # never reaches Pages/R2. (The Step-2b loose token scan doesn't cover it.)
    arti_unrel_dir = site_assets / UNRELEASED_ART_DIR
    if arti_unrel_dir.exists():
        shutil.rmtree(arti_unrel_dir, ignore_errors=True)
    if arti_src.exists():
        for p in sorted(arti_src.iterdir()):
            m = ARTI_ID_RE.match(p.name)
            if not m:
                continue
            aid = m.group(1).lower()
            suf = m.group(2).lower()
            key = "full" if suf.startswith("fu") else "lobby"
            dst = arti_dir / p.name
            if aid in UNRELEASED_ARTIFACTS:
                # Never PUBLISH it: purge any copy in the public dir, but keep a
                # local-only copy so it can be previewed on localhost.
                if dst.exists():
                    try: dst.unlink()
                    except OSError: pass
                arti_unrel_dir.mkdir(exist_ok=True)
                udst = arti_unrel_dir / p.name
                try: shutil.copy2(p, udst)
                except OSError: continue
                arti_unrel_files[aid][key] = f"assets/_artifacts_unreleased/{p.name}"
                continue
            if not dst.exists():
                try: shutil.copy2(p, dst)
                except OSError: continue
            arti_files[aid][key] = f"assets/_artifacts/{p.name}"

    def _arti_entry(aid: str, paths: dict[str, str]) -> dict:
        rec = {**artifact_db.get(aid, {}), **MANUAL_ARTIFACTS.get(aid, {})}
        entry: dict = {"id": aid, "art_full": paths["full"]}
        if "lobby" in paths: entry["art_lobby"] = paths["lobby"]
        if rec.get("name"):       entry["name"]    = rec["name"]
        if rec.get("_id"):        entry["slug"]    = rec["_id"]
        if rec.get("rarity"):     entry["rarity"]  = rec["rarity"]
        if rec.get("role"):       entry["role"]    = rec["role"]
        if rec.get("_id"):
            entry["cecilia"] = f"{CECILIA_ARTIFACT}/{rec['_id']}"
        elif rec.get("name"):
            # No community kebab yet (e.g. a manually-named brand-new artifact):
            # synthesise one from the name — the same deterministic shape ceciliabot
            # uses — so the link resolves once ceciliabot adds the artifact (may 404
            # until then), mirroring the new-hero kebab fallback. NEVER point an
            # artifact at the HEROES index (the prior bug for the 3 NEW artifacts).
            entry["cecilia"] = f"{CECILIA_ARTIFACT}/{kebab(rec['name'])}"
        else:
            entry["cecilia"] = CECILIA_ARTIFACT
        return entry

    artifacts_out: list[dict] = [
        _arti_entry(aid, paths) for aid, paths in arti_files.items()
        if "full" in paths                    # no portrait → not card-worthy
    ]
    artifacts_out.sort(key=lambda a: (-(a.get("rarity") or 0), a["id"]))
    artifacts_unrel: list[dict] = [
        {**_arti_entry(aid, paths), "unreleased": True}
        for aid, paths in arti_unrel_files.items() if "full" in paths
    ]
    artifacts_unrel.sort(key=lambda a: (-(a.get("rarity") or 0), a["id"]))

    return artifacts_out, artifacts_unrel


# Class aliases so unit.role and artifact.role line up when validating links.
_ROLE_NORM = {
    "soul-weaver": "manauser", "manauser": "manauser",
    "thief": "assassin", "assassin": "assassin",
    "warrior": "warrior", "knight": "knight",
    "ranger": "ranger", "mage": "mage",
}


def _norm_role(r: str | None) -> str | None:
    if not r:
        return None
    return _ROLE_NORM.get(str(r).lower(), str(r).lower())


def _load_unit_to_arts() -> dict[str, list[str]]:
    """unit base → art#### list: owners file + SIGNATURE_ARTIFACTS (manual first).

    When a unit has a manual SIGNATURE_ARTIFACTS entry, those arts *replace*
    the owners-file list for that unit (so a fixed exclusive is not polluted
    by a stale wrong link like Kayron→Celestine).
    """
    unit_to_arts: dict[str, list[str]] = {}
    owners_path = REPO_ROOT / "data_external" / "artifact_owners.json"
    if owners_path.exists():
        try:
            owners = json.loads(owners_path.read_text(encoding="utf-8"))
            for cid, aids in (owners.get("unit_to_arts") or {}).items():
                if isinstance(aids, list) and aids:
                    unit_to_arts[cid.lower()] = [str(a).lower() for a in aids]
        except Exception:
            pass
    for cid, aids in SIGNATURE_ARTIFACTS.items():
        key = cid.lower()
        # Manual replaces owners for this unit (authoritative exclusive).
        unit_to_arts[key] = list(dict.fromkeys(str(a).lower() for a in aids))
    return unit_to_arts


def attach_signature_artifacts(units: dict, artifacts: list) -> int:
    """Stamp units with `signature_artifacts[]` from the owner map + manuals.

    Only arts present in the public `artifacts` list with a portrait are linked
    (UNRELEASED_ARTIFACTS never appear). Cross-class pairs are dropped when both
    sides have a known role (exclusive arts match the hero's class). Cards are
    slim copies for the detail page UI. Returns units stamped."""
    by_art = {a["id"]: a for a in artifacts if a.get("id") and a.get("art_full")}
    unit_to_arts = _load_unit_to_arts()

    def art_ids_for(unit: dict) -> list[str]:
        keys: list[str] = []
        for k in (unit.get("id"), unit.get("base_id")):
            if not k:
                continue
            kl = k.lower()
            keys.append(kl)
            m = re.match(r"^(c\d{4})", kl)
            if m:
                keys.append(m.group(1))
        u_role = _norm_role(unit.get("role"))
        out: list[str] = []
        seen: set[str] = set()
        for k in keys:
            for aid in unit_to_arts.get(k) or []:
                if aid in seen or aid in UNRELEASED_ARTIFACTS:
                    continue
                rec = by_art.get(aid)
                if not rec:
                    continue
                a_role = _norm_role(rec.get("role"))
                # Refuse known class clashes (Kayron/assassin ≠ Celestine/manauser).
                if u_role and a_role and u_role != a_role:
                    continue
                seen.add(aid)
                out.append(aid)
        return out

    def slim_art(rec: dict) -> dict:
        card: dict = {
            "id": rec["id"],
            "kind": "artifact",
            "name": rec.get("name") or rec["id"],
            "art_full": rec["art_full"],
        }
        for k in ("art_lobby", "rarity", "role", "slug", "cecilia",
                  "announced", "announce_video", "announce_release", "new"):
            if rec.get(k) is not None and rec.get(k) is not False:
                card[k] = rec[k]
        return card

    n = 0
    for u in units.values():
        if u.get("kind") != "unit":
            continue
        cards = []
        for aid in art_ids_for(u):
            rec = by_art.get(aid)
            if rec:
                cards.append(slim_art(rec))
        if cards:
            u["signature_artifacts"] = cards
            n += 1
    return n


def attach_artifact_owners(units: dict, artifacts: list) -> int:
    """Stamp artifacts with `owner_units[]` (reverse of signature map).

    Links the Artifacts tab / zoom UI to the unit detail page (#/u/<base>).
    Prefer a public primary unit for each base (not unreleased-only). Returns
    artifacts stamped."""
    unit_to_arts = _load_unit_to_arts()
    # art → unit bases
    art_to_bases: dict[str, list[str]] = {}
    for cid, aids in unit_to_arts.items():
        for aid in aids:
            if aid in UNRELEASED_ARTIFACTS:
                continue
            art_to_bases.setdefault(aid, [])
            if cid not in art_to_bases[aid]:
                art_to_bases[aid].append(cid)

    # Prefer one public representative per base_id (PRIMARY_SWAP primary, etc.)
    by_base: dict[str, dict] = {}
    for u in units.values():
        if u.get("kind") != "unit":
            continue
        base = (u.get("base_id") or u.get("id") or "").lower()
        if not base:
            continue
        m = re.match(r"^(c\d{4})", base)
        bare = m.group(1) if m else base
        # Prefer exact base match, then any; keep first stable
        for key in (base, bare):
            if key not in by_base:
                by_base[key] = u
            elif not (u.get("variant") or "") and (by_base[key].get("variant") or ""):
                by_base[key] = u  # prefer unskinned form as rep

    def slim_unit(u: dict) -> dict:
        base = u.get("base_id") or u["id"]
        card: dict = {
            "id": u["id"],
            "base_id": base,
            "name": u.get("hero_name") or u.get("name") or base,
            "href": f"#/u/{base}",
        }
        if u.get("thumb"):
            card["thumb"] = u["thumb"]
        elif u.get("pose"):
            card["pose"] = u["pose"]
        for k in ("rarity", "attribute", "role", "announced", "new"):
            if u.get(k) is not None and u.get(k) is not False:
                card[k] = u[k]
        return card

    a_role = None  # set per artifact below
    n = 0
    for a in artifacts:
        aid = (a.get("id") or "").lower()
        bases = art_to_bases.get(aid) or []
        a_role = _norm_role(a.get("role"))
        owners = []
        seen: set[str] = set()
        for b in bases:
            u = by_base.get(b) or by_base.get(
                re.match(r"^(c\d{4})", b).group(1)
                if re.match(r"^(c\d{4})", b) else ""
            )
            if not u:
                continue
            u_role = _norm_role(u.get("role"))
            # Drop cross-class reverse links (same rule as signature attach).
            if a_role and u_role and a_role != u_role:
                continue
            key = (u.get("base_id") or u["id"]).lower()
            if key in seen:
                continue
            seen.add(key)
            owners.append(slim_unit(u))
        if owners:
            a["owner_units"] = owners
            n += 1
    return n
