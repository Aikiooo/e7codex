"""Extract Epic Seven voice clips from FMOD banks → per-clip OGG + a catalog.

Pipeline (self-contained once vgmstream + ffmpeg are installed — see README):
  FMOD .bank  --vgmstream-cli-->  WAV (subsong)  --ffmpeg-->  OGG

Source banks live under <sound_dir>/<lang>/*.bank — point --sound at your own
copy (default: <repo>/_voice_work/sound). Each bank is a concatenation of FSB5
sub-banks; each FSB5 sample carries a name like voc_<cslug>_<action>_<take>
(e.g. voc_c1001_attacked_1, voc_c1022_s01_win_2). vgmstream enumerates them as
subsongs in the SAME order as the FSB5 name tables, so subsong index ↔ name.

Output:
  <out_dir>/<lang>/voc_<cslug>_<action>_<take>.ogg
  <out_dir>/voice_catalog.json  ->  {cslug: {action: {label, takes:{lang:[...]}}}}

Usage:
  python tools/extract_voice_audio.py --langs en --slugs c1001 c1017   # subset
  python tools/extract_voice_audio.py --langs en ja ko --all           # full
"""
import struct, glob, os, re, json, subprocess, argparse, sys, tempfile
from pathlib import Path
from collections import defaultdict

REPO = Path(__file__).resolve().parents[1]
VGM = REPO / 'tools' / 'vendor' / 'vgmstream' / 'vgmstream-cli.exe'
sys.path.insert(0, str(Path(__file__).parent))
from paths import VOICE_DIR  # central data-dir config
# Defaults resolve via voice_keys.json (voice_dir, else <dump>/_voice_work);
# override with --sound / --out (or the E7_VOICE_SOUND / E7_VOICE_OUT env vars).
# Bring your own bank files.
SOUND = Path(os.environ.get('E7_VOICE_SOUND', VOICE_DIR / 'sound'))
OUTROOT = Path(os.environ.get('E7_VOICE_OUT', VOICE_DIR / 'out'))

SAMPLE_RX = re.compile(r'^voc_(c\d+(?:_s\d+)?|af\d+|npc\d+|pet_[a-z0-9]+)_(.+?)(?:_(\d+))?$')

# action token -> friendly label. Covers the modern + legacy (Ras-era) vocab.
ACTION_LABELS = {
    'attacked': 'When Attacked', 'dmg': 'When Attacked',
    'idle': 'Idle', 'idle_s': 'Idle (skin)', 'standby': 'Standby',
    'skill1': 'Skill 1', 'sk1': 'Skill 1', 'shout': 'Skill 1',
    'skill2': 'Skill 2', 'sk2': 'Skill 2', 'skill2_s': 'Skill 2 (skin)',
    'skill3': 'Skill 3', 'sk3': 'Skill 3',
    'skill3_1': 'Skill 3 (1)', 'skill3_2': 'Skill 3 (2)', 'skill3_3': 'Skill 3 (3)', 'skill3_4': 'Skill 3 (4)',
    'sk3_1': 'Skill 3 (1)', 'sk3_2': 'Skill 3 (2)', 'sk3_3': 'Skill 3 (3)', 'sk3_4': 'Skill 3 (4)',
    'skill3_s_1': 'Skill 3 skin (1)', 'skill3_s_2': 'Skill 3 skin (2)', 'skill3_s_3': 'Skill 3 skin (3)', 'skill3_s_4': 'Skill 3 skin (4)',
    'skill2_1': 'Skill 2 (1)', 'skill2_2': 'Skill 2 (2)', 'skill2_3': 'Skill 2 (3)',
    'answer': 'Dual Attack (respond)', 'call': 'Dual Attack (request)',
    'dead': 'Death', 'defeat': 'Defeat', 'lose': 'Defeat',
    'win': 'Victory', 'lvup': 'Level Up', 'lv': 'Level Up', 'get': 'Summon',
    'utterance': 'Camp Story', 'camping': 'Camp', 'emotion': 'Emotion',
    'touch': 'Touch', 'enter': 'Enter', 'close': 'Close', 'standby': 'Standby',
    'hopeless': 'Hopeless', 'proper': 'Confident',
    'story': 'Story', 'story_a': 'Story A', 'story_b': 'Story B', 'story_d': 'Story D',
}
def label_for(action):
    if action in ACTION_LABELS: return ACTION_LABELS[action]
    return action.replace('_', ' ').title()

def fsb5_names(path):
    """Yield sample names in subsong order across all FSB5 blocks in a bank."""
    d = open(path, 'rb').read(); i = 0
    while True:
        o = d.find(b'FSB5', i)
        if o < 0: break
        try: ver, ns, shs, nts, ds, mode = struct.unpack_from('<6I', d, o + 4)
        except struct.error: break
        if ver == 1 and 0 < ns < 100000 and nts > 0 and shs < 10**8:
            nt = o + 0x3c + shs
            try:
                offs = struct.unpack_from('<%dI' % ns, d, nt)
                for k in range(ns):
                    s = nt + offs[k]; e = d.find(b'\x00', s)
                    yield d[s:e].decode('latin1').split('(')[0] if 0 < e - s < 120 else ''
            except struct.error: pass
            i = o + 0x3c + shs + nts + ds
        else:
            i = o + 4

def build_index(lang):
    """{(slug,action,take): (bank_path, subsong_index)} for one language."""
    idx = {}
    banks = sorted(glob.glob(str(SOUND / lang / '*.bank')))
    for bank in banks:
        for sub, name in enumerate(fsb5_names(bank), start=1):  # vgmstream is 1-based
            m = SAMPLE_RX.match(name)
            if not m: continue
            slug, action, take = m.group(1), m.group(2), m.group(3) or '1'
            idx[(slug, action, take)] = (bank, sub)
    return idx

def decode_one(bank, sub, out_ogg):
    with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tf:
        wav = tf.name
    try:
        r = subprocess.run([str(VGM), '-s', str(sub), '-o', wav, bank],
                           capture_output=True, text=True)
        if r.returncode != 0 or not os.path.getsize(wav):
            return False, r.stderr.strip()[:120]
        out_ogg.parent.mkdir(parents=True, exist_ok=True)
        r2 = subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-i', wav,
                             '-c:a', 'libvorbis', '-q:a', '2', '-ar', '24000', '-ac', '1',
                             str(out_ogg)], capture_output=True, text=True)
        return r2.returncode == 0 and out_ogg.exists(), r2.stderr.strip()[:120]
    finally:
        try: os.unlink(wav)
        except OSError: pass

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--langs', nargs='+', default=['en'])
    ap.add_argument('--slugs', nargs='*', help='c-slugs to extract (e.g. c1001)')
    ap.add_argument('--all', action='store_true')
    ap.add_argument('--jobs', type=int, default=8, help='parallel decode workers')
    ap.add_argument('--sound', help='dir of <lang>/*.bank files (default: <repo>/_voice_work/sound)')
    ap.add_argument('--out', help='output dir for OGGs + catalog (default: <repo>/_voice_work/out)')
    args = ap.parse_args()
    global SOUND, OUTROOT
    if args.sound: SOUND = Path(args.sound)
    if args.out: OUTROOT = Path(args.out)
    assert VGM.exists(), (f'missing {VGM} — download vgmstream into '
                          f'tools/vendor/vgmstream/ (see README, "Voice pipeline")')
    from concurrent.futures import ThreadPoolExecutor

    for lang in args.langs:
        idx = build_index(lang)
        slugs = sorted({k[0] for k in idx}) if args.all else (args.slugs or [])
        want = [(k, v) for k, v in idx.items() if k[0] in set(slugs)]
        print(f'[{lang}] index={len(idx)} clips; extracting {len(want)} for {len(set(slugs))} slugs', flush=True)
        ok = fail = 0
        def work(item):
            (slug, action, take), (bank, sub) = item
            out = OUTROOT / lang / f'voc_{slug}_{action}_{take}.ogg'
            if out.exists(): return True, None
            return decode_one(bank, sub, out)
        with ThreadPoolExecutor(max_workers=args.jobs) as ex:
            for i, (good, err) in enumerate(ex.map(work, want)):
                if good: ok += 1
                else:
                    fail += 1
                    if fail <= 5: print(f'  FAIL: {err}', flush=True)
                if (i + 1) % 2000 == 0: print(f'  [{lang}] {i+1}/{len(want)} (ok={ok} fail={fail})', flush=True)
        print(f'[{lang}] ok={ok} fail={fail}', flush=True)

    rebuild_catalog(args.langs)

# Catalog is GROUND TRUTH of OGGs actually on disk, with per-language take
# availability — so the frontend only ever shows a button whose file exists for
# the selected language (a take present in JA but missing in EN won't 404).
def rebuild_catalog(langs):
    name_rx = re.compile(r'^voc_(.+?)_(.+?)_(\d+)$')
    catalog = {}  # slug -> action -> {label, takes:{lang:[...]}}
    for lang in langs:
        for f in glob.glob(str(OUTROOT / lang / 'voc_*.ogg')):
            stem = Path(f).stem
            m = SAMPLE_RX.match(stem)
            if not m: continue
            slug, action, take = m.group(1), m.group(2), int(m.group(3) or 1)
            e = catalog.setdefault(slug, {}).setdefault(action, {'label': label_for(action), 'takes': {}})
            e['takes'].setdefault(lang, [])
            if take not in e['takes'][lang]: e['takes'][lang].append(take)
    for slug in catalog:
        for action in catalog[slug]:
            for lang in catalog[slug][action]['takes']:
                catalog[slug][action]['takes'][lang].sort()
    OUTROOT.mkdir(parents=True, exist_ok=True)
    json.dump(catalog, open(OUTROOT / 'voice_catalog.json', 'w', encoding='utf-8'),
              ensure_ascii=False, indent=0, sort_keys=True)
    print(f'\nwrote {OUTROOT/"voice_catalog.json"} ({len(catalog)} slugs, langs={langs})')

if __name__ == '__main__':
    main()
