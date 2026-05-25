"""Find units.json units still lacking has_combat whose combat rig is
PROBABLY present in output/model under a different name. Matches each
unstaged rig stem to a unit by (a) exact name-kebab, (b) name token subset.
Read-only; prints candidates ranked by confidence.
"""
import json, re, sys
from pathlib import Path
THIS = Path(__file__).resolve(); sys.path.insert(0, str(THIS.parent))
import prepare_combat_assets as pca

REPO = THIS.parents[1]
units = json.loads((REPO / 'site' / 'data' / 'units.json').read_text(encoding='utf-8'))
combat_ids = {u['id'] for u in units if u.get('has_combat')}
km = pca.load_kebab_to_cslug()
staged = {p.name for p in pca.SITE.iterdir() if p.is_dir() and not p.name.startswith('_')}

# unstaged rig stems = those map_stem can't already place
stems = sorted(p.stem for p in pca.MODEL.glob('*.scsp'))
unmapped = [s for s in stems if pca.map_stem(s, km, staged) is None]

# index units by name tokens (kind==unit, no combat yet, staged dir exists)
def toks(s): return set(re.findall(r'[a-z]+', s.lower()))
unit_by_tokens = []
for u in units:
    if u.get('kind') != 'unit' or u['id'] in combat_ids: continue
    if u['id'] not in staged: continue
    nm = u.get('name', '')
    if nm: unit_by_tokens.append((u['id'], nm, toks(nm)))

# only consider bare-ish stems (no _m/_s suffix) for this collab/prefix sweep
SUF = pca.SUFFIX_PEEL
def is_bare(s): return not any(s.endswith(x) for x in SUF)

hits = []
for stem in unmapped:
    if not is_bare(stem): continue
    st = stem.replace('_', '-')
    cand = []
    for cid, nm, tk in unit_by_tokens:
        # stem token equals the unit's last name-token (e.g. winter == ae-WINTER)
        if st in tk or st.replace('-', '') in {''.join(re.findall(r'[a-z]+', t)) for t in tk}:
            cand.append((cid, nm))
    if len(cand) == 1:
        hits.append((stem, cand[0][0], cand[0][1], 'HIGH'))
    elif len(cand) > 1:
        hits.append((stem, ';'.join(c for c, _ in cand), ';'.join(n for _, n in cand), 'AMBIG'))

print(f'unmapped bare stems: {sum(1 for s in unmapped if is_bare(s))}')
print(f'matched to an unstaged unit: {len(hits)}')
for stem, cid, nm, conf in sorted(hits):
    print(f'  [{conf}] {stem:18s} -> {cid:12s} {nm}')
