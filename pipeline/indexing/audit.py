"""`--inspect`: a read-only report about the staged tree (nothing written).

Use it before a full rebuild to spot drift: how many slugs are staged per kind,
how many resolve a name, how many have a live-viewer / combat rig, and which
codenames in banner/story path tokens have no label yet.
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from .fsutil import walk
from .slugs import kind_of, split_variant
from .sources import load_event_labels, load_name_db
from .tables import CODE_RE


def inspect_site(img: Path, raw: Path, out: Path) -> None:
    """Read-only report (--inspect): staged slug counts by kind, name coverage,
    raw rig counts, and update codenames detected in path tokens. Writes
    nothing — useful before a full rebuild to spot drift."""
    site_assets = out / "assets"
    root = out.parent if out.name == "site" else Path(".")
    name_base, name_skin = load_name_db(root)
    event_labels = load_event_labels(root)

    dirs = ([d for d in sorted(site_assets.iterdir())
             if d.is_dir() and not d.name.startswith("_")
             and (d / "pose.png").exists()]
            if site_assets.exists() else [])
    by_kind: dict[str, int] = defaultdict(int)
    named = spined = combat = 0
    for d in dirs:
        slug = d.name
        by_kind[kind_of(slug)] += 1
        base_id, _, _ = split_variant(slug)
        if slug in name_skin or base_id in name_base:
            named += 1
        if (d / f"{slug}.json").exists():
            spined += 1
        if (d / "combat" / f"{slug}.json").exists():
            combat += 1
    print(f"[staged]  {len(dirs)} slugs with a baked pose")
    for k, n in sorted(by_kind.items(), key=lambda x: -x[1]):
        print(f"  {k:10s} {n}")
    print(f"[names]   {named} resolve a display name "
          f"({len(name_base)} base heroes + {len(name_skin)} skins known)")
    print(f"[spine]   {spined} with live-viewer JSON · {combat} with a combat rig")

    for sub in ("portrait", "model"):
        p = raw / sub
        if p.exists():
            n = sum(1 for f in p.iterdir() if f.suffix == ".scsp")
            print(f"[raw]     {sub}: {n} .scsp rigs")

    codes: set[str] = set()
    for p in walk(img / "banner"):
        codes |= {c.lower() for c in CODE_RE.findall(p.name.lower())}
    sb = img / "story" / "bg"
    if sb.exists():
        for p in sb.iterdir():
            codes |= {c.lower() for c in CODE_RE.findall(p.name.lower())}
    unlabeled = sorted(codes - event_labels.keys())
    print(f"[codes]   {len(codes)} codenames in banner/story tokens, "
          f"{len(codes) - len(unlabeled)} labeled"
          + (f" — unlabeled: {', '.join(unlabeled)}" if unlabeled else ""))
    print("\n(read-only — nothing written)")
