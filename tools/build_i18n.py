"""Build per-language display-name overlays for the E7 Codex localization layer.

The game ships localized text in output/text/<lang>/text.db for 10 languages
(en ko ja zhs zht th de fr es pt). Every in-game term is keyed by a LANGUAGE-
INDEPENDENT export_id, so we decode each language's text.db and resolve the SAME
keys the English site already uses:

  hero names   chrn_<cslug>            (ML/seasonal forms carry their own chrn_)
  skin names   ma_<slug>_name          (costume display name, e.g. ma_c1002_s01_name)
  artifacts    <identifier>_name        (identifier from artifacts_from_db.json)
  events       codename title           (re-resolved via codename_labels source keys)
  elements     color_<token>            (fire/ice/wind/light/dark; color_wind = "Earth")
  classes      ui_hero_role_<token>     (warrior/knight/ranger/mage/manauser/assassin)

Output: site/data/lang/<lang>.json = {names, artifacts, events, elements, classes}
        (the `ui` chrome block is merged in later by the translation step).

English is the reference: a language's value is emitted ONLY when it differs from
English, so units.json stays the English source of truth and the overlays carry
just the deltas (keeps de/fr/es/pt overlays tiny — most proper nouns are identical).

Reuses tools/build_names.py cipher primitives. Run after a data pack, alongside
build_names.py / build_artifacts.py:  python tools/build_i18n.py
Dev speed: --cache <dir> reads pre-decoded {lang}.json dumps instead of text.db.
"""
from __future__ import annotations
import argparse, json, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import build_names as bn  # cipher + path primitives (load_keymap, cdbm_rows, ...)

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'site' / 'data'
DATA_EXTERNAL = ROOT / 'data_external'
TEXT_ROOT = bn.RAW_DIR / 'text'
# Hand/LLM-translated UI chrome (source of truth, checked in). One file per
# non-English language: {"ui": {key: text}, "elements"?: {...}, "classes"?: {...}}.
# build_i18n MERGES the `ui` block into each overlay so re-running it (which
# regenerates game terms from text.db) never clobbers the chrome translations.

# 10 game languages. English is the reference and gets NO overlay file (it is
# already inline in units.json/artifacts.json). Vietnamese (vi) is unofficial and
# has no game text.db — its overlay is authored entirely from the chrome source
# (ui + hand-translated elements/classes; game names fall back to English).
GAME_LANGS = ['ko', 'ja', 'zhs', 'zht', 'th', 'de', 'fr', 'es', 'pt']
UNOFFICIAL_LANGS = ['vi']
ALL_LANGS = ['en'] + GAME_LANGS

# Vietnamese: no in-game text.db (E7 has no official VI localization). Its overlay
# is hand-translated — UI chrome + closed-set terms only; hero/artifact/event
# names fall back to English. Marked "unofficial" in the switcher (shared.js).
VI = 'vi'

# Hand-authored translation source (produced by the translation step). Per lang:
#   data_external/i18n_ui/<lang>.json = {"ui": {key: text}, "elements"?: {...},
#   "classes"?: {...}}. For the 10 game langs only "ui" is used (elements/classes
#   come from the DB); for vi, "elements"/"classes" are read from here too.
UI_SRC = DATA_EXTERNAL / 'i18n_ui'

ELEMENT_TOKENS = ['fire', 'ice', 'wind', 'light', 'dark']          # color_<token>
CLASS_TOKENS = ['warrior', 'knight', 'ranger', 'mage', 'manauser', 'assassin']  # ui_hero_role_<token>


def load_ui_src(lang: str) -> dict:
    """Hand-authored translation source for a language, or {} if not yet made."""
    p = UI_SRC / f'{lang}.json'
    if p.exists():
        return json.loads(p.read_text(encoding='utf-8'))
    return {}


def decode_lang(lang: str) -> dict:
    """Decode output/text/<lang>/text.db -> {export_id: text}."""
    keymap = bn.load_keymap()
    plain = bn.outer_decrypt_textdb((TEXT_ROOT / lang / 'text.db').read_bytes())
    out = {}
    for key, val in bn.cdbm_rows(plain):
        if len(key) != 8 or key[:4] != b'\x1b\x6b\x00\x00':
            continue
        pt = bn.decrypt_value(val, keymap)
        if not pt:
            continue
        parts = [c for c in pt.split(b'\x00') if c]
        if len(parts) >= 2:
            out[parts[0].decode('utf-8', 'replace')] = parts[1].decode('utf-8', 'replace')
    return out


def load_maps(cache: Path | None) -> dict[str, dict]:
    """{lang: {export_id: text}} for every language, from text.db or a --cache dir."""
    maps = {}
    for lang in ALL_LANGS:
        t = time.time()
        if cache:
            maps[lang] = json.loads((cache / f'{lang}.json').read_text(encoding='utf-8'))
            src = 'cache'
        else:
            maps[lang] = decode_lang(lang)
            src = 'text.db'
        print(f'  {lang}: {len(maps[lang])} entries ({src}, {time.time()-t:.1f}s)', flush=True)
    return maps


def name_key(unit: dict, en: dict) -> str | None:
    """The text.db key the English site's name for this unit resolves through, or
    None when there is no game source (name then stays English in every language).
    Mirrors build_index's fallback: skins -> ma_<slug>_name; ML/base -> chrn_<slug>;
    _1 primary-swap sibling -> chrn_<slug minus _1>; else base hero's chrn_."""
    cid = unit['id']
    if unit.get('variant'):                       # skin/costume: authoritative ma_ key only
        k = f'ma_{cid}_name'
        return k if k in en else None
    if f'chrn_{cid}' in en:
        return f'chrn_{cid}'
    if cid.endswith('_1') and f'chrn_{cid[:-2]}' in en:
        return f'chrn_{cid[:-2]}'
    base = unit.get('base_id') or cid
    return f'chrn_{base}' if f'chrn_{base}' in en else None


def hero_key(base_id: str, en: dict) -> str | None:
    """Key for a base hero's display name (the variant-grouping label)."""
    if f'chrn_{base_id}' in en:
        return f'chrn_{base_id}'
    if base_id.endswith('_1') and f'chrn_{base_id[:-2]}' in en:
        return f'chrn_{base_id[:-2]}'
    return None


def delta(maps: dict, lang: str, key: str) -> str | None:
    """The language value for `key`, or None when it is absent or identical to
    English (identical -> frontend falls back to the inline English record)."""
    en_v = maps['en'].get(key)
    lv = maps[lang].get(key)
    if lv is None or lv == en_v:
        return None
    return lv


def build(cache: Path | None, out_dir: Path) -> None:
    print('decoding text.db (10 languages)...', flush=True)
    maps = load_maps(cache)
    en = maps['en']

    units = json.loads((DATA / 'units.json').read_text(encoding='utf-8'))
    artifacts_db = json.loads((DATA_EXTERNAL / 'artifacts_from_db.json').read_text(encoding='utf-8'))
    codenames = json.loads((DATA_EXTERNAL / 'codename_labels.json').read_text(encoding='utf-8'))

    # DMCA belt-and-suspenders: never localize a held/unreleased slug even if one
    # somehow reached units.json (it shouldn't — build_index splits it out first).
    try:
        unreleased = set(json.loads((DATA_EXTERNAL / 'unreleased_units.json').read_text(encoding='utf-8')))
    except FileNotFoundError:
        unreleased = set()

    def held(cid: str, base: str) -> bool:
        return cid in unreleased or base in unreleased

    # Resolve the name key ONCE per unit/base (keys are language-independent).
    unit_keys = {}      # id -> text.db key
    for u in units:
        cid, base = u['id'], (u.get('base_id') or u['id'])
        if held(cid, base):
            continue
        k = name_key(u, en)
        if k:
            unit_keys[cid] = k
        hk = hero_key(base, en)
        if hk:
            unit_keys.setdefault(base, hk)   # base label; don't clobber a unit id

    # DMCA: only localize artifacts the site actually ships. artifacts.json is
    # already unreleased-filtered by build_index (UNRELEASED_ARTIFACTS); deriving
    # the allowed id set from it keeps held artifact names out of the public
    # overlay JSON (the overlay ships to Pages, so an unrendered-but-present name
    # would still leak). Falls back to the full DB only if artifacts.json is
    # absent (dev-only; the deploy path always builds it first).
    try:
        shipped = {rec['id'] for rec in json.loads((DATA / 'artifacts.json').read_text(encoding='utf-8'))}
    except FileNotFoundError:
        shipped = None
    art_keys = {aid: f"{rec['identifier']}_name"
                for aid, rec in artifacts_db.items()
                if rec.get('identifier') and f"{rec['identifier']}_name" in en
                and (shipped is None or aid in shipped)}

    element_keys = {tok: f'color_{tok}' for tok in ELEMENT_TOKENS if f'color_{tok}' in en}
    class_keys = {tok: f'ui_hero_role_{tok}' for tok in CLASS_TOKENS if f'ui_hero_role_{tok}' in en}

    out_dir.mkdir(parents=True, exist_ok=True)
    counts = {}
    for lang in GAME_LANGS:
        names = {cid: v for cid, k in unit_keys.items()
                 if (v := delta(maps, lang, k)) is not None}
        arts = {aid: v for aid, k in art_keys.items()
                if (v := delta(maps, lang, k)) is not None}
        # events: codename_labels.json is {codename: english title}; re-resolve the
        # SAME title per language by reverse-mapping the title back to its text key.
        events = resolve_events(codenames, maps, lang)
        elements = {tok: maps[lang][k] for tok, k in element_keys.items() if maps[lang].get(k)}
        classes = {tok: maps[lang][k] for tok, k in class_keys.items() if maps[lang].get(k)}

        overlay = {'names': names, 'artifacts': arts, 'events': events,
                   'elements': elements, 'classes': classes}
        ui = load_ui_src(lang).get('ui')
        if ui:
            overlay['ui'] = ui
        (out_dir / f'{lang}.json').write_text(
            json.dumps(overlay, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
        counts[lang] = {'names': len(names), 'artifacts': len(arts), 'events': len(events)}
        print(f'  {lang}.json: names={len(names)} artifacts={len(arts)} '
              f'events={len(events)} elements={len(elements)} classes={len(classes)} '
              f'ui={len(ui or {})}', flush=True)

    # Vietnamese (unofficial): hand overlay only — ui + closed-set terms; game
    # names/artifacts/events stay English (no in-game VI text). Written only when
    # a vi translation source exists.
    vi_src = load_ui_src(VI)
    if vi_src:
        vi_overlay = {
            'names': {}, 'artifacts': {}, 'events': {},
            'elements': vi_src.get('elements', {}),
            'classes': vi_src.get('classes', {}),
            'ui': vi_src.get('ui', {}),
        }
        (out_dir / f'{VI}.json').write_text(
            json.dumps(vi_overlay, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
        print(f'  {VI}.json: ui={len(vi_overlay["ui"])} elements={len(vi_overlay["elements"])} '
              f'classes={len(vi_overlay["classes"])} (unofficial; names fall back to English)', flush=True)

    print(f'\nwrote overlays -> {out_dir}')


# codename_labels.json is built by build_codename_labels.py; its VALUES are the
# English titles. The title's text.db export_id isn't stored there, so to localize
# we reverse-map: find the English key whose value equals the title, then pull that
# key per language. Titles are unique enough that this is reliable; ambiguous or
# unfound titles simply stay English.
def resolve_events(codenames: dict, maps: dict, lang: str) -> dict:
    en = maps['en']
    # Build a reverse index once per call is wasteful across langs; cache on the fn.
    idx = getattr(resolve_events, '_idx', None)
    if idx is None:
        idx = {}
        for k, v in en.items():
            idx.setdefault(v, k)      # first key wins
        resolve_events._idx = idx
    out = {}
    for code, title in codenames.items():
        k = idx.get(title)
        if not k:
            continue
        lv = maps[lang].get(k)
        if lv and lv != title:
            out[code] = lv
    return out


def main():
    ap = argparse.ArgumentParser(description='Build per-language name overlays for E7 Codex.')
    ap.add_argument('--cache', type=Path, help='dir of pre-decoded {lang}.json dumps (dev speed)')
    ap.add_argument('--out', type=Path, default=DATA / 'lang', help='output dir (default site/data/lang)')
    args = ap.parse_args()
    build(args.cache, args.out)


if __name__ == '__main__':
    main()
