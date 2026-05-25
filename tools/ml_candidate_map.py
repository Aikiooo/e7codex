"""
Generate candidate mappings for unmapped ML/alt-form combat rigs
(<base>_m / _m2 / _a01 / _m_s01) -> a special-form units.json unit, by
name-token match. ML units are DISTINCT units (different art) sharing only
the base character's lore name, so candidates = units whose name contains
the base character's display name, excluding the base unit itself.

Confidence:
  HIGH    exactly 1 un-combat-staged special unit matches
  AMBIG   multiple matches -> needs visual disambiguation
  NOBASE  base character not resolvable from HeroDatabase
  NOCAND  no special unit found (likely the rig has no Codex unit)
Read-only; writes ml_candidate_map.txt.
"""
import json, sys, re
from pathlib import Path
THIS = Path(__file__).resolve()
sys.path.insert(0, str(THIS.parent))
import prepare_combat_assets as pca

REPO = THIS.parents[1]
hdb = json.loads((REPO / 'data_external' / 'HeroDatabase.json').read_text(encoding='utf-8'))
kebab_to_name = {k: v['name'] for k, v in hdb.items()}
units = json.loads((REPO / 'site' / 'data' / 'units.json').read_text(encoding='utf-8'))
by_id = {u['id']: u for u in units}
combat_ids = {u['id'] for u in units if u.get('has_combat')}

MODEL = pca.MODEL
SITE = pca.SITE
staged = {p.name for p in SITE.iterdir() if p.is_dir() and not p.name.startswith('_')}
kebab_map = pca.load_kebab_to_cslug()

# ML/alt suffixes to consider here (skins _s01/_s02 keep base c-slug -> handled elsewhere)
ML_SUFFIXES = ['_m_s01', '_a01', '_m2', '_m']

stems = sorted(p.stem for p in MODEL.glob('*.scsp'))

def already_mapped(stem):
    return pca.map_stem(stem, kebab_map, staged) is not None

def base_name(stem):
    for suf in ML_SUFFIXES:
        if stem.endswith(suf):
            base = stem[:-len(suf)]
            base = pca.SPELLING_ALIAS.get(base.replace('_', '-'), base.replace('_', '-'))
            return base  # kebab form
    return None

def name_tokens(name):
    return set(re.findall(r"[a-z]+", name.lower()))

rows = []
for stem in stems:
    bk = base_name(stem)
    if bk is None:
        continue  # not an ML/alt-suffixed rig
    if already_mapped(stem):
        continue  # existing logic already handles it
    disp = kebab_to_name.get(bk)
    if not disp:
        rows.append((stem, 'NOBASE', bk, []))
        continue
    base_id = kebab_map.get(bk)
    # candidate special units: name contains the base display name token,
    # not the base unit, kind==unit, not already combat-staged
    btoks = name_tokens(disp)
    cands = []
    for u in units:
        if u.get('kind') != 'unit':
            continue
        if u['id'] == base_id:
            continue
        if u['id'] in combat_ids:
            continue
        nm = u.get('name', '')
        if not nm:
            continue
        if btoks and btoks <= name_tokens(nm):  # base name fully contained
            cands.append((u['id'], nm))
    if not cands:
        rows.append((stem, 'NOCAND', disp, []))
    elif len(cands) == 1:
        rows.append((stem, 'HIGH', disp, cands))
    else:
        rows.append((stem, 'AMBIG', disp, cands))

from collections import Counter
print('unmapped ML/alt rigs examined:', len(rows))
print(dict(Counter(r[1] for r in rows)))
print()
print('=== HIGH confidence (1 candidate) ===')
for stem, conf, disp, cands in rows:
    if conf == 'HIGH':
        cid, nm = cands[0]
        print(f'  {stem:24s} -> {cid:10s} {nm}')
print()
print('=== AMBIG (multiple candidates) ===')
for stem, conf, disp, cands in rows:
    if conf == 'AMBIG':
        print(f'  {stem:24s} base={disp:14s} -> ' + '; '.join(f'{c}/{n}' for c, n in cands))

with open(REPO / 'ml_candidate_map.txt', 'w', encoding='utf-8') as w:
    for stem, conf, disp, cands in rows:
        w.write(f'{conf}\t{stem}\t{disp}\t' + '; '.join(f'{c}/{n}' for c, n in cands) + '\n')
print('\n-> ml_candidate_map.txt')
