#!/usr/bin/env python3
"""One-shot scrape of c####→name mapping from epic7rtastats.com /heroes.

CeciliaBot/E7Tools HeroDatabase.json is frozen at April 2023 so any hero past
c1143 (e.g. c1171 Tori) lacks a name. Epic7RTAStats embeds a complete current
roster as escaped JSON inside the /heroes page HTML — we pull it once and cache
the parsed result alongside HeroDatabase.json. build_index.py treats it as a
fall-back layer: HeroDatabase first (better metadata), then this file for the
heroes the original snapshot misses.

Run:
    python tools/scrape_rtastats_names.py
"""
from __future__ import annotations
import json, re, sys, urllib.request
from pathlib import Path

URL = "https://www.epic7rtastats.com/heroes"
OUT = Path(__file__).resolve().parent.parent / "data_external" / "HeroNames_rtastats.json"


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="replace")


def parse(html: str) -> dict[str, dict]:
    # Records are embedded in a Next.js prop blob with escaped quotes:
    #   \"code\":\"c1171\",\"name\":\"Tori\",\"element\":\"fire\",\"class\":\"assassin\"
    pat = re.compile(
        r'\\"code\\":\\"(c\d+)\\","name\\":\\"([^"\\]+)\\","element\\":\\"(\w+)\\","class\\":\\"(\w+)\\"'
        .replace('","name', r'\\",\\"name')        # keep separators escaped
        .replace('","element', r'\\",\\"element')
        .replace('","class', r'\\",\\"class')
    )
    # Simpler approach: scan with a forgiving pattern that tolerates the escape style.
    out: dict[str, dict] = {}
    record_re = re.compile(r'\\"code\\":\\"(c\d+)\\"[^{}]{0,200}?'
                           r'\\"name\\":\\"([^"\\]+)\\"[^{}]{0,200}?'
                           r'\\"element\\":\\"(\w+)\\"[^{}]{0,80}?'
                           r'\\"class\\":\\"(\w+)\\"')
    for code, name, elem, cls in record_re.findall(html):
        if code not in out:
            out[code] = {"name": name, "attribute": elem, "role": cls}
    return out


def main() -> int:
    print(f"fetching {URL} ...")
    html = fetch(URL)
    heroes = parse(html)
    if not heroes:
        print("ERROR: no hero records parsed — page structure may have changed.")
        return 1
    payload = {"_source": URL, "_count": len(heroes), "heroes": heroes}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=1, ensure_ascii=False), "utf-8")
    print(f"wrote {OUT}  ({len(heroes)} unique c#### entries)")
    for c in ("c1019", "c1144", "c1171", "c2079"):
        print(f"  spot check: {c} -> {heroes.get(c)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
