"""Steps 7-8: what the build writes.

Step 7 is the JSON the front end fetches, plus the two LOCAL-ONLY files the
unreleased guard splits out (units_unreleased.json, artifacts_unreleased.json).
`write_units` runs the two leak assertions immediately before the write, so a
held slug can never reach the public catalog.

Step 8 is the SEO surface: one static prerender stub per base hero at /u/<base>
(the SPA routes by hash, which crawlers don't index) plus sitemap.xml and
robots.txt. Stubs are only written for units that already passed the guard, and
stale stubs for pulled/renamed bases are pruned on every build.
"""
from __future__ import annotations

import html
import json
from collections import defaultdict
from pathlib import Path

from .artifacts import purge_unreleased_artifacts
from .unreleased import assert_no_held_tokens, assert_no_held_units

def write_units(data: Path, units: dict, guard) -> None:
    """site/data/units.json — asserted clean on the way in."""
    assert_no_held_units(units, guard)
    _units_text = json.dumps(sorted(units.values(), key=lambda u: u["id"]),
                             indent=1, ensure_ascii=False)
    assert_no_held_tokens(_units_text, guard)
    (data / "units.json").write_text(_units_text, "utf-8")


def write_unreleased(data: Path, unrel_list: list, artifacts_unrel: list,
                     site_assets: Path) -> None:
    """The LOCAL-ONLY held previews (index.html loads them only on localhost)."""
    # LOCAL-ONLY browse file (index.html loads only when E7.isLocal / ?unreleased=1
    # / ?local=1; ops/deploy.ps1 holds it + asset dirs aside so it never reaches Pages).
    unrel_path = data / "units_unreleased.json"
    unrel_list.sort(key=lambda x: x["id"])
    if unrel_list:
        unrel_path.write_text(json.dumps(unrel_list, indent=1, ensure_ascii=False), "utf-8")
        print(f"[unreleased] {len(unrel_list)} held unit(s) -> units_unreleased.json "
              f"(full build, LOCAL-ONLY; ops/deploy.ps1 holds it aside)")
    elif unrel_path.exists():
        unrel_path.unlink()   # don't let a stale file outlive the held set

    # LOCAL-ONLY held-artifact preview (same treatment as units_unreleased).
    unrel_arti_path = data / "artifacts_unreleased.json"
    if artifacts_unrel:
        unrel_arti_path.write_text(json.dumps(artifacts_unrel, indent=1, ensure_ascii=False), "utf-8")
        print(f"[unreleased] {len(artifacts_unrel)} held artifact(s) -> artifacts_unreleased.json "
              f"(LOCAL-ONLY; ops/deploy.ps1 holds it aside)")
    else:
        if unrel_arti_path.exists(): unrel_arti_path.unlink()
        purge_unreleased_artifacts(site_assets)


def write_catalogs(data: Path, updates_out: dict, emotes_list: list,
                   wallpapers: list, artifacts_out: list) -> None:
    """updates.json / emotes.json / wallpapers.json / artifacts.json."""
    (data / "updates.json").write_text(
        json.dumps(updates_out, indent=1, ensure_ascii=False), "utf-8")
    (data / "emotes.json").write_text(
        json.dumps(emotes_list, indent=1, ensure_ascii=False), "utf-8")
    (data / "wallpapers.json").write_text(
        json.dumps(wallpapers, indent=1, ensure_ascii=False), "utf-8")
    (data / "artifacts.json").write_text(
        json.dumps(artifacts_out, indent=1, ensure_ascii=False), "utf-8")


def write_seo(units: dict, out: Path) -> tuple[dict, int]:
    """Prerender stubs + sitemap + robots; returns (stub_bases, n_pruned)."""
    # Step 8: SEO prerender stubs — one static page per base hero at /u/<base>,
    # plus sitemap.xml + robots.txt. The SPA routes by hash (#/u/<base>), which
    # crawlers don't index, so heroes were invisible to search; these stubs give
    # each one a crawlable URL with a real <title>/description/OG image, then
    # bounce human visitors to the hash route. Cloudflare Pages serves /u/<base>
    # from u/<base>.html natively (automatic .html resolution). Units here have
    # already passed the unreleased guard, so stubs can't leak; stale stubs for
    # pulled/renamed bases are pruned each build.
    SITE_ORIGIN = "https://e7codex.com"
    u_dir = out / "u"
    u_dir.mkdir(exist_ok=True)
    stub_bases: dict[str, list[dict]] = defaultdict(list)
    for u in units.values():
        stub_bases[u.get("base_id") or u["id"]].append(u)
    for base, group in stub_bases.items():
        rep = next((x for x in group if not x.get("variant")), group[0])
        name = rep.get("hero_name") or rep.get("name") or base
        forms = f" {len(group)} forms." if len(group) > 1 else ""
        desc = (f"{name} — Epic Seven artwork, baked poses and a live Spine "
                f"viewer on E7 Codex.{forms}")
        e = html.escape
        pose_url = f"{SITE_ORIGIN}/{rep['pose']}"
        page_url = f"{SITE_ORIGIN}/u/{base}"
        (u_dir / f"{base}.html").write_text(f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>{e(name)} — E7 Codex</title>
<meta name="description" content="{e(desc)}">
<link rel="canonical" href="{page_url}">
<meta property="og:site_name" content="E7 Codex">
<meta property="og:title" content="{e(name)} — E7 Codex">
<meta property="og:description" content="{e(desc)}">
<meta property="og:type" content="website">
<meta property="og:url" content="{page_url}">
<meta property="og:image" content="{pose_url}">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{e(name)} — E7 Codex">
<meta name="twitter:image" content="{pose_url}">
<script>location.replace("/#/u/{base}");</script>
</head>
<body>
<p><a href="/#/u/{base}">{e(name)} on E7 Codex — artwork &amp; pose archive</a></p>
</body>
</html>
""", "utf-8")
    valid_stubs = {f"{b}.html" for b in stub_bases}
    n_pruned = 0
    for p in u_dir.glob("*.html"):
        if p.name not in valid_stubs:
            p.unlink()
            n_pruned += 1
    urls = [f"{SITE_ORIGIN}/"] + [f"{SITE_ORIGIN}/u/{b}" for b in sorted(stub_bases)]
    (out / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "".join(f"  <url><loc>{u}</loc></url>\n" for u in urls)
        + "</urlset>\n", "utf-8")
    (out / "robots.txt").write_text(
        f"User-agent: *\nAllow: /\nSitemap: {SITE_ORIGIN}/sitemap.xml\n", "utf-8")
    return stub_bases, n_pruned
