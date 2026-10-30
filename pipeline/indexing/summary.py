"""The end-of-build report: one block per view, printed to stdout."""
from __future__ import annotations

from collections import defaultdict

from .tables import KNOWN_UPDATES, MOD_WINDOW_DAYS, NEW_WINDOW_DAYS


def print_summary(*, units, unrel_list, n_hidden, emotes_list,
                  wallpapers, updates_out, event_labels, artifacts_out,
                  stub_bases, n_pruned, n_new, n_ann,
                  n_sig, n_own, n_mod, n_rel,
                  n_loop, data) -> None:
    """Print the run summary — counts only, nothing written."""
    by_kind: dict[str, int] = defaultdict(int)
    with_art = with_spine = with_name = with_skill = with_intimacy = 0
    for u in units.values():
        by_kind[u["kind"]] += 1
        if u["artworks"]: with_art += 1
        if u.get("spine"): with_spine += 1
        if u.get("name"): with_name += 1
        if u["skills"]: with_skill += 1
        if u.get("intimacy"): with_intimacy += 1
    print(f"\n[units] {len(units)} total")
    for k, n in sorted(by_kind.items(), key=lambda x: -x[1]):
        print(f"  {k:10s} {n}")
    if n_hidden or unrel_list:
        print(f"\n[hidden]  {len(unrel_list)} unreleased unit(s) built fully → "
              f"units_unreleased.json only (not units.json / not deploy)")
    print(f"\n[names]   {with_name} units with display name "
          f"(from HeroDatabase.json + HeroSkins.json + names_from_db.json)")
    print(f"[artwork] {with_art} units with at least one face PNG bundled")
    print(f"[skills]  {with_skill} units with S3 skill animation")
    print(f"[spine]   {with_spine} units with live-viewer JSON")
    print(f"[intim]   {with_intimacy} units with intimacy illustration")
    print(f"[emotes]  {len(emotes_list)} character emote groups "
          f"({sum(len(g['emotes']) for g in emotes_list)} files; "
          f"{sum(1 for g in emotes_list if g.get('base_id'))} linked to a unit)")
    print(f"[wallpr]  {len(wallpapers)} wallpapers")
    print(f"[updates] {len(updates_out)} codenames with banner art "
          f"({sum(len(v['banners']) for v in updates_out.values())} banners total) "
          f"out of {len(event_labels)} labeled "
          f"(KNOWN_UPDATES={len(KNOWN_UPDATES)} + DB join)")
    named_arti = sum(1 for a in artifacts_out if a.get("name"))
    print(f"[arti]    {len(artifacts_out)} artifacts ({named_arti} named "
          f"from Artifacts.json + artifacts_from_db.json, "
          f"{len(artifacts_out)-named_arti} orphan)")
    print(f"[new]     {n_new} unit/artifact/emote/wallpaper flagged new "
          f"(first-seen within {NEW_WINDOW_DAYS}d; first_seen.json)")
    print(f"[ann]     {n_ann} unit/artifact flagged announced "
          f"(pre-banner; ANNOUNCED ledger — becomes NEW after release date)")
    print(f"[sig]     {n_sig} unit(s) with signature_artifacts[] "
          f"(owners map + SIGNATURE_ARTIFACTS)")
    print(f"[own]     {n_own} artifact(s) with owner_units[] "
          f"(reverse map → unit detail links)")
    print(f"[upd]     {n_mod} unit(s) flagged updated "
          f"(within {MOD_WINDOW_DAYS}d; modified.json)")
    print(f"[date]    {n_rel} unit(s) stamped with release date "
          f"(timeline/timeline.json)")
    print(f"[loop]    {n_loop} animated webp(s) forced to infinite loop "
          f"(play-once fix; emotes/skills/intimacy/…)")
    print(f"[seo]     {len(stub_bases)} prerender stubs in site/u/ + sitemap.xml"
          + (f" ({n_pruned} stale pruned)" if n_pruned else ""))
    print(f"\n-> {data / 'units.json'}\n-> {data / 'updates.json'}"
          f"\n-> {data / 'emotes.json'}\n-> {data / 'wallpapers.json'}"
          f"\n-> {data / 'artifacts.json'}")
