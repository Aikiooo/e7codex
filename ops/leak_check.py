#!/usr/bin/env python3
"""Deep unreleased-content leak scan — the last gate before anything publishes.

Shape-agnostic by design: instead of checking known JSON fields (which drift —
nested extras[], owner_units, items chips, db_banner stems, and path-only patch
rows all slipped past the structured checks at least once), this tokenizes the
text of every publishable file and matches held slugs as token sequences. A new
data shape added tomorrow is covered automatically.

Scanned surfaces (red-teamed 2026-07-18; every bullet closes a proven bypass):
  1. site/data/**/*.json — BOTH the raw text AND the decoded JSON strings
     (keys + values), so \\uXXXX-escaped slug chars can't smuggle a reference
     the browser would happily reconstruct.
  2. Held units' real in-game names — exact string-value match inside JSON
     (never substring, so French prose "aube" can't false-flag a held Aube).
  3. site/u/*.html prerender stubs, sitemap.xml, robots.txt, and the top-level
     site HTML/JS — these deploy to Pages with no hold, and a stub carries the
     held slug in its URLs and the held NAME in its <title>.
  4. Loose-art paths (dirs deploy does NOT move aside: _patches/_wallpapers/
     _emotes/_artifacts/_updates/_cinema) — full relative path, not basename.

Token matching splits on [^a-z0-9]+ (NEVER \\b — `_c5069_` has no word
boundary) and matches a slug as a CONSECUTIVE token sequence, so a held
variant like c2185_1 ("c2185","1") does not flag a released base c2185.
Single-part slugs additionally match as a token PREFIX (`ss_c6023a0_bi`
tokenizes to one fused token 'c6023a0' — startswith catches it).

FAIL-CLOSED: a missing unreleased_units.json, or an empty slugs list (the
2026-06-04 text.db outer-offset shift rebuilt it empty and silently degraded
the guard), exits 1. The ~168 reserved "Unknown Hero" slots mean the real list
is never legitimately empty; if that ever changes, pass --allow-empty.

Exit 0 = clean, exit 1 = leaks/config error listed on stdout. Wired into
sync_pack Stage 8 and ops/deploy.ps1 Step 2b; also runnable standalone:

  python ops/leak_check.py             # scan the real site/
  python ops/leak_check.py --selftest  # verify every known escape shape
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Public-data exclusions: local-only files ops/deploy.ps1 holds aside (never
# published), so held slugs are EXPECTED inside them.
LOCAL_ONLY = {"units_unreleased.json", "story_index.json"}
LOCAL_ONLY_DIRS = {"story"}

# Shared art dirs that deploy does NOT move aside — the loose-token leak
# surface (the c5069 wallpaper and c5190 _patches leaks shipped this way).
LOOSE_ART_DIRS = ("_patches", "_wallpapers", "_emotes", "_artifacts",
                  "_updates", "_cinema")

# Pages-published text files outside site/data — prerender stubs carry the
# held slug in URLs and the held name in <title>; none are held aside.
SITE_TEXT_GLOBS = ("u/*.html", "*.html", "*.js", "sitemap.xml", "robots.txt")

# Escape hatch for confirmed false positives: exact leak lines reviewed by a
# human. Keep empty unless a hit was verified harmless.
ALLOW: set[str] = set()

TOKEN_RE = re.compile(r"[^a-z0-9]+")


def slug_parts(slug: str) -> tuple[str, ...]:
    return tuple(p for p in TOKEN_RE.split(slug.lower()) if p)


def tokenize(text: str) -> list[str]:
    return [t for t in TOKEN_RE.split(text.lower()) if t]


def ngram_hits(tokens: list[str], seqs: dict[str, tuple[str, ...]]) -> set[str]:
    """Keys of seqs whose token sequence appears consecutively in tokens.
    Single-token sequences also match as a PREFIX of a fused token."""
    hits = set()
    for key, parts in seqs.items():
        if not parts:
            continue
        if len(parts) == 1:
            p = parts[0]
            if any(t == p or t.startswith(p) for t in tokens):
                hits.add(key)
            continue
        for i, t in enumerate(tokens):
            if t == parts[0] and tuple(tokens[i:i + len(parts)]) == parts:
                hits.add(key)
                break
    return hits


def iter_strings(node):
    """Every string in a parsed JSON tree — keys AND values."""
    if isinstance(node, dict):
        for k, v in node.items():
            if isinstance(k, str):
                yield k
            yield from iter_strings(v)
    elif isinstance(node, list):
        for v in node:
            yield from iter_strings(v)
    elif isinstance(node, str):
        yield node


def scan(site: Path, unreleased_path: Path, names_path: Path,
         allow_empty: bool = False) -> list[str] | None:
    """None = configuration failure (fail closed); list = leak lines."""
    if not unreleased_path.exists():
        print(f"CONFIG ERROR: {unreleased_path} missing — the holdback list is "
              "the gate's ground truth; refusing to pass.")
        return None
    held = json.loads(unreleased_path.read_text(encoding="utf-8")).get("slugs", [])
    slugs = {s.lower(): slug_parts(s) for s in held if s and slug_parts(s)}
    if not slugs:
        if allow_empty:
            print("   (empty holdback list — nothing to gate, --allow-empty set)")
            return []
        print("CONFIG ERROR: unreleased_units.json has 0 slugs. The reserved "
              "'Unknown Hero' slots mean this is never legitimately empty — "
              "likely the text.db decode failed (outer-XOR offset shift, "
              "2026-06-04 mode). Re-run build_names.py; or --allow-empty.")
        return None

    # Real in-game names of held units (build_names keeps them for local
    # browse; they must never appear in public output). Only borrow the base
    # slug's name when the base itself is held — otherwise a held c6024_1
    # would adopt released Iseria's name and false-flag every legit mention.
    held_names: dict[str, str] = {}
    if names_path.exists():
        names_db = json.loads(names_path.read_text(encoding="utf-8"))
        for s in slugs:
            rec = names_db.get(s)
            base = s.split("_")[0]
            if rec is None and base != s and base in slugs:
                rec = names_db.get(base)
            name = (rec or {}).get("name")
            if name:
                held_names[name.lower()] = s
    name_seqs = {n: slug_parts(n) for n in held_names}

    leaks: list[str] = []

    def hit(rel: str, what: str):
        leaks.append(f"{rel}: {what}")

    # 1+2: public data JSONs — raw text, decoded strings, exact name values.
    data_dir = site / "data"
    for p in sorted(data_dir.rglob("*.json")) if data_dir.is_dir() else []:
        if p.name in LOCAL_ONLY or any(
                d in LOCAL_ONLY_DIRS for d in p.relative_to(data_dir).parts[:-1]):
            continue
        text = p.read_text(encoding="utf-8")
        rel = p.relative_to(site).as_posix()
        parsed = json.loads(text)
        decoded = "\n".join(iter_strings(parsed))
        tokens = tokenize(text) + tokenize(decoded)
        for slug in sorted(ngram_hits(tokens, slugs)):
            hit(rel, f"slug token '{slug}'")
        for val in iter_strings(parsed):
            s = held_names.get(val.strip().lower())
            if s:
                hit(rel, f"held unit NAME '{val}' ({s})")

    # 3: Pages-published text outside site/data (prerender stubs, sitemap, …).
    seen: set[Path] = set()
    for pat in SITE_TEXT_GLOBS:
        for p in sorted(site.glob(pat)):
            if not p.is_file() or p in seen:
                continue
            seen.add(p)
            rel = p.relative_to(site).as_posix()
            tokens = tokenize(p.read_text(encoding="utf-8", errors="replace"))
            for slug in sorted(ngram_hits(tokens, slugs)):
                hit(rel, f"slug token '{slug}'")
            for name in sorted(ngram_hits(tokens, name_seqs)):
                hit(rel, f"held unit NAME '{name}' ({held_names[name.lower()]})")

    # 4: loose-art paths (full relative path — a slug-named parent dir with a
    # generic basename like preview.png must still flag).
    for sub in LOOSE_ART_DIRS:
        d = site / "assets" / sub
        if not d.is_dir():
            continue
        for f in sorted(d.rglob("*")):
            if not f.is_file():
                continue
            tokens = tokenize(f.relative_to(d).as_posix())
            for slug in sorted(ngram_hits(tokens, slugs)):
                hit(f"assets/{sub}/{f.relative_to(d).as_posix()}",
                    f"slug token '{slug}'")

    return [x for x in leaks if x not in ALLOW]


def selftest() -> int:
    """Plant one leak per known escape shape (incl. every red-teamed bypass,
    2026-07-18); assert each is caught and clean shapes pass."""
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "data" / "lang").mkdir(parents=True)
        (root / "u").mkdir()
        (root / "assets" / "_wallpapers").mkdir(parents=True)
        (root / "assets" / "_patches" / "c9998_pack").mkdir(parents=True)
        unrel = root / "unreleased_units.json"
        unrel.write_text(json.dumps({"slugs": ["c9998", "c2185_1", "c6024_1"]}), "utf-8")
        names = root / "names_from_db.json"
        names.write_text(json.dumps({"c9998": {"name": "Testina Vera"},
                                     "c6024": {"name": "Iseria"}}), "utf-8")

        cases = {  # data-file name -> (raw text, expected hit count)
            # held slug nested as an extras[] entry (not top-level)
            "units.json": (json.dumps(
                [{"id": "c1000", "extras": [{"id": "c9998_1"}],
                  # released base's name must NOT false-flag via held c6024_1
                  "name": "Iseria"}]), 1),
            # held owner leaked via owner_units name + href
            "artifacts.json": (json.dumps(
                [{"id": "art9", "owner_units": [
                    {"id": "c9998", "name": "Testina Vera", "href": "#/u/c9998"}]}]), 2),
            # items chip token
            "updates.json": (json.dumps(
                {"Ev": {"items": ["ma_emo_c9998_drink_001"]}}), 1),
            # FUSED token: slug glued to a trailing id (ss_c9998a0_bi)
            "voices.json": (json.dumps({"x": "ss_c9998a0_bi"}), 1),
            # unicode-escape smuggling: c 9998 decodes to c9998
            "lang/ja.json": ('{"x": "assets/_\\u00639998_bg/pose.png"}', 1),
            # held VARIANT must not flag the released base
            "wallpapers.json": (json.dumps([{"file": "gacha_c2185_01_bg.png"}]), 0),
            "emotes.json": (json.dumps([{"file": "emo_c2185_1_smile.png"}]), 1),
        }
        for fname, (content, _) in cases.items():
            (root / "data" / fname).write_text(content, "utf-8")
        # prerender stub + sitemap (published to Pages, no hold)
        (root / "u" / "c9998.html").write_text(
            "<title>Testina Vera</title><a href='/#/u/c9998'>x</a>", "utf-8")
        (root / "sitemap.xml").write_text(
            "<urlset><url><loc>https://x/u/c9998</loc></url></urlset>", "utf-8")
        # loose art: slug only in the parent DIR, generic basename
        (root / "assets" / "_patches" / "c9998_pack" / "preview.png").write_text("x")
        (root / "assets" / "_wallpapers" / "img_intimacy_illust_c9998.webp").write_text("x")

        leaks = scan(root, unrel, names)
        failures = []
        if leaks is None:
            failures.append("scan() reported config error on a valid fixture")
            leaks = []
        for fname, (_, expected) in cases.items():
            got = sum(1 for l in leaks if l.startswith(f"data/{fname}:"))
            if got != expected:
                failures.append(f"data/{fname}: expected {expected} hit(s), got {got}")
        for prefix, label in (("u/c9998.html:", "prerender stub"),
                              ("sitemap.xml:", "sitemap"),
                              ("assets/_patches/c9998_pack/", "dir-named loose art"),
                              ("assets/_wallpapers/", "loose wallpaper")):
            if not any(l.startswith(prefix) for l in leaks):
                failures.append(f"{label} leak missed ({prefix})")
        if any("Iseria" in l for l in leaks):
            failures.append("released base name 'Iseria' false-flagged via held c6024_1")

        # fail-closed config checks
        if scan(root, root / "missing.json", names) is not None:
            failures.append("missing holdback list did not fail closed")
        empty = root / "empty.json"
        empty.write_text(json.dumps({"slugs": []}), "utf-8")
        if scan(root, empty, names) is not None:
            failures.append("empty holdback list did not fail closed")
        if scan(root, empty, names, allow_empty=True) != []:
            failures.append("--allow-empty did not permit an empty list")

        if failures:
            print("SELFTEST FAILED:")
            for f in failures:
                print(f"  {f}")
            print("leaks found:")
            for l in leaks:
                print(f"  {l}")
            return 1
        print(f"selftest OK — {len(leaks)} planted leaks caught, "
              "clean shapes + fail-closed checks passed")
        return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--site", default=str(ROOT / "site"))
    ap.add_argument("--unreleased", default=str(ROOT / "data_external" / "unreleased_units.json"))
    ap.add_argument("--names", default=str(ROOT / "data_external" / "names_from_db.json"))
    ap.add_argument("--allow-empty", action="store_true",
                    help="permit an empty holdback list (normally fail-closed)")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    leaks = scan(Path(a.site), Path(a.unreleased), Path(a.names), a.allow_empty)
    if leaks is None:
        return 1
    if leaks:
        print("LEAKING unreleased references:")
        for x in leaks[:40]:
            print(f"  {x}")
        print(f"ABORT: {len(leaks)} unreleased reference(s) in publishable data.")
        return 1
    print("leak_check OK — no held slug tokens or names in publishable data/art/html")
    return 0


if __name__ == "__main__":
    sys.exit(main())
