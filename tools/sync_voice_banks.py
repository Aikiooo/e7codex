"""Copy Epic Seven voice banks into the scratch tree.

WHY: the spoken-voice source is FMOD `.bank` files. Point `--game-sound` at any
tree holding `sound/<lang>/*.bank` — the game folder, or a complete set of banks
for all three languages obtained elsewhere — and gate on CONTENT with
`--reference <tree>/sound` when that tree is known to be current (a freshly
unpacked set keeps its archive's original old mtimes, so the mtime fallback
would call a byte-identical language stale forever).

The GAME folder only ever holds the
CURRENTLY-SELECTED Hero Audio Language — the client prunes the others when you
switch in-game. So syncing from the game means picking a language in-game,
letting it download, copying it here, and repeating per language. This script is
also what you run after a normal game update — it copies any bank whose bytes
changed.

  GAME (read-only source)                    SCRATCH (destination)
  <game>/sound/<lang>/*.audio_<lang>.bank -> _voice_work/sound/<lang>/*.bank
  <game>/sound/{master.strings,voc.event,   _voice_work/sound/  (top level)
               master}.bank

SAFETY: this NEVER writes to the game folder — it only reads from it and copies
into the scratch tree (writing into the game install risks an anti-cheat ban).
The copy direction is fixed (game -> scratch); there is no path that writes back.

Incremental: a bank is copied only when the destination is missing or its size /
mtime differs from the source, so re-running is cheap. The set of languages it
syncs is simply whichever `<lang>/` dirs currently exist in the game folder.

Downstream: after syncing, `tools/extract_voice_audio.py --langs <changed>`
decodes only the NEW clips (it skips OGGs already on disk) and rebuilds the
per-language catalog. Pass --extract here to chain that automatically for the
languages whose banks changed.

Usage:
  python tools/sync_voice_banks.py                      # sync all langs present in-game
  python tools/sync_voice_banks.py --extract            # + run extraction for changed langs
  python tools/sync_voice_banks.py --game-sound <path>  # override game sound dir
                                                        # (or any current sound/<lang> tree)
"""
import argparse, hashlib, json, os, shutil, subprocess, sys, time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# Optional override from the (gitignored) voice_keys.json; falls back to the
# default PC-client install path. --game-sound beats both.
DEFAULT_GAME_SOUND = Path('D:/Games/EpicSeven/data.unpacked/sound')
sys.path.insert(0, str(Path(__file__).parent))
from paths import VOICE_DIR  # central data-dir config
DEST = VOICE_DIR / 'sound'
SHARED_BANKS = ('master.strings.bank', 'voc.event.bank', 'master.bank')

_CFG = Path(__file__).parent / 'voice_keys.json'


def game_sound_default() -> Path:
    if _CFG.exists():
        cfg = json.loads(_CFG.read_text(encoding='utf-8'))
        if cfg.get('game_sound_dir'):
            return Path(cfg['game_sound_dir'])
    return DEFAULT_GAME_SOUND


def _newest_mtime(paths) -> float:
    return max((p.stat().st_mtime for p in paths if p.exists()), default=0.0)


def _md5(fp: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.md5()
    with open(fp, 'rb') as f:
        for b in iter(lambda: f.read(chunk), b''):
            h.update(b)
    return h.hexdigest()


def _banks_match(a: Path, b: Path) -> bool:
    """Byte-identical? Size first (cheap), then md5."""
    sa, sb = a.stat(), b.stat()
    if sa.st_size != sb.st_size:
        return False
    return _md5(a) == _md5(b)


def lang_status(dest: Path, require, reference: Path = None) -> dict:
    """Per-language freshness vs the current pack.

    The reliable test is CONTENT. When a `reference` tree is given — the staging
    tree holding a known-current set of banks — a language is `current` iff every bank there is present in the
    scratch tree byte-for-byte.

    Without a reference we fall back to mtime: the shared banks (voc.event /
    master.strings) ship with every PACK while a per-language bank changes only
    when that language's audio does, so a language whose banks predate the shared
    ones is *probably* behind. That heuristic is only a proxy, and it is wrong in
    both directions: a pack can bump `voc.event.bank` without touching any
    language's audio, and freshly unpacked banks keep their ORIGINAL (old) mtimes — so
    a byte-identical language still reads as `stale`. Prefer a reference whenever
    one is available; "missing" always means never dumped.
    """
    out = {}
    pack_mtime = _newest_mtime([dest / n for n in SHARED_BANKS])
    TOL = 5.0  # seconds — banks downloaded in the same session land ~together
    for lang in require:
        banks = list((dest / lang).glob('*.bank')) if (dest / lang).is_dir() else []
        if not banks:
            out[lang] = 'missing'
            continue
        ref_banks = list((reference / lang).glob('*.bank')) \
            if reference and (reference / lang).is_dir() else []
        if ref_banks:
            ok = True
            for rb in ref_banks:
                lb = dest / lang / rb.name
                if not lb.is_file() or not _banks_match(lb, rb):
                    ok = False
                    break
            out[lang] = 'current' if ok else 'stale'
            continue
        out[lang] = 'current' if _newest_mtime(banks) >= pack_mtime - TOL else 'stale'
    return out


def wait_until_stable(paths, settle: float = 8.0, timeout: float = 1800.0, poll: float = 2.0) -> bool:
    """Block until the source banks stop changing, so we never copy a file that's
    still downloading. A bank being written keeps changing size/mtime; we proceed
    only once nothing has been touched for `settle` seconds (and sizes held steady
    across a poll). Idle/complete files return immediately. Returns False on
    timeout (copies as-is with a warning)."""
    paths = [p for p in paths if p.exists()]
    if not paths:
        return True
    start = time.time()
    prev = None
    while True:
        cur = {p: (p.stat().st_size, p.stat().st_mtime) for p in paths if p.exists()}
        now = time.time()
        newest = max((mt for _, mt in cur.values()), default=0.0)
        idle = (now - newest) >= settle           # nothing written for `settle`s
        if cur and idle and (prev is None or cur == prev):
            return True
        if now - start > timeout:
            print(f'  WARNING: banks still changing after {int(timeout)}s — copying as-is '
                  f'(a download may be stuck).')
            return False
        if prev is None or cur != prev:
            print('  waiting for downloads to finish (banks still changing)…', flush=True)
        prev = cur
        time.sleep(poll)


def needs_copy(src: Path, dst: Path, by_content: bool = False) -> bool:
    """Should src overwrite dst?

    Default: size differs, or src is newer — the game-folder case, where mtimes
    track the client's own downloads. by_content compares bytes instead, for an
    authoritative reference tree (a freshly unpacked set), whose mtimes are
    the archive's originals and so say nothing about freshness.
    """
    if not dst.exists():
        return True
    s, d = src.stat(), dst.stat()
    if s.st_size != d.st_size:
        return True
    if by_content:
        return _md5(src) != _md5(dst)
    return s.st_mtime > d.st_mtime + 1


def copy_if_changed(src: Path, dst: Path, by_content: bool = False) -> bool:
    """Read-only on src (game); writes only to dst (scratch). Returns True if copied.

    Stamps the destination mtime to now when by_content: the scratch tree then
    reads as "verified against the current pack as of this run", which is what
    lang_status()'s mtime fallback looks at when no reference is supplied.
    """
    if not needs_copy(src, dst, by_content):
        if by_content:
            os.utime(dst, None)      # verified current — refresh the stamp
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)   # copies src -> dst; never the reverse
    if by_content:
        os.utime(dst, None)
    return True


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--game-sound', type=Path, default=None,
                    help='game sound dir (default: voice_keys.json game_sound_dir or the PC install path)')
    ap.add_argument('--dest', type=Path, default=DEST, help='scratch sound dir')
    ap.add_argument('--require-langs', nargs='+', default=['en', 'ja', 'ko'],
                    help='languages that must all be current before the pack is "ready"')
    ap.add_argument('--reference', type=Path, default=None,
                    help='authoritative bank tree to gate against (a known-current set '
                         'of banks). When set, freshness is decided by CONTENT (md5), '
                         'not mtimes — unpacked archives keep their original old mtimes, '
                         'so a byte-identical language otherwise reads as stale')
    ap.add_argument('--wait', action='store_true',
                    help='interactive: after a pack update, loop until every required '
                         'language has been swapped-to in-game + re-dumped (press Enter '
                         'after each swap; the game only keeps the selected language on disk)')
    ap.add_argument('--extract', action='store_true',
                    help='after syncing, run extract_voice_audio.py for the changed languages')
    ap.add_argument('--settle', type=float, default=8.0,
                    help='seconds the source banks must be unchanged before copying '
                         '(guards against copying a bank that is still downloading); 0 to disable')
    args = ap.parse_args()

    game_sound = args.game_sound or game_sound_default()
    if not game_sound.is_dir():
        raise SystemExit(f'game sound dir not found: {game_sound}\n'
                         f'(pass --game-sound or set game_sound_dir in voice_keys.json)')

    def sync_once():
        """Copy whatever the game folder currently holds; return changed langs."""
        # Don't copy mid-download: wait until the source banks are stable.
        if args.settle > 0:
            srcs = [game_sound / n for n in SHARED_BANKS]
            for d in game_sound.iterdir():
                if d.is_dir():
                    srcs += list(d.glob('*.bank'))
            wait_until_stable(srcs, settle=args.settle)
        shared_changed = 0
        for name in SHARED_BANKS:
            src = game_sound / name
            if src.exists() and copy_if_changed(src, args.dest / name):
                shared_changed += 1
                print(f'  [shared] {name}')
        changed = []
        lang_dirs = sorted(d for d in game_sound.iterdir() if d.is_dir())
        if not lang_dirs:
            print('  (no language subdir in the game folder — download a Hero Audio '
                  'Language in-game, or point --game-sound at a current bank tree)')
        for ld in lang_dirs:
            banks = sorted(ld.glob('*.bank'))
            if not banks:
                continue
            n = sum(copy_if_changed(b, args.dest / ld.name / b.name, bool(args.reference))
                    for b in banks)
            print(f'  [{ld.name}] {len(banks)} banks, {f"{n} changed" if n else "up to date"}')
            if n:
                changed.append(ld.name)
        return changed, shared_changed

    print(f'syncing from {game_sound}')
    changed_langs, _ = sync_once()

    # Freshness gate: every required language must be at the current pack before
    # downstream extraction runs, or we'd publish stale audio for the languages
    # not yet re-dumped after an update.
    def report_status():
        st = lang_status(args.dest, args.require_langs, args.reference)
        print('\npack language status:')
        for lang in args.require_langs:
            print(f'  {lang}: {st[lang]}')
        return st

    status = report_status()
    stale = [l for l in args.require_langs if status[l] != 'current']

    if stale and args.wait:
        print('\nThe game folder holds only the SELECTED Hero Audio Language. '
              'If you have a current set of all three languages, re-run with '
              '--game-sound <tree>/sound --reference <tree>/sound instead. '
              'To dump from the game, switch in-game to each stale/missing '
              'language, let it finish downloading, then press Enter to re-dump it.')
        while stale:
            try:
                resp = input(f'  waiting for: {", ".join(stale)}  [Enter=re-scan, q=abort] ').strip().lower()
            except EOFError:
                break
            if resp == 'q':
                print('aborted — pack still incomplete.')
                sys.exit(2)
            c, _ = sync_once()
            changed_langs += [l for l in c if l not in changed_langs]
            status = report_status()
            stale = [l for l in args.require_langs if status[l] != 'current']

    print(f'\nsynced: {", ".join(changed_langs) or "no"} language(s) changed')
    print(f'  source: {game_sound}\n  dest:   {args.dest}')

    if stale:
        print(f'\nNOT READY — stale/missing: {", ".join(stale)}. '
              f'Point --game-sound/--reference at a current bank tree, or use --wait '
              f'to dump each language from the game. Extraction skipped to avoid stale audio.')
        sys.exit(2)

    print('READY - all required languages are at the current pack.')
    if args.extract and changed_langs:
        cmd = [sys.executable, str(Path(__file__).parent / 'extract_voice_audio.py'),
               '--all', '--langs', *changed_langs]
        print(f'\n--extract: {" ".join(cmd)}')
        sys.exit(subprocess.call(cmd))
    elif changed_langs:
        print(f'\nNext: python tools/extract_voice_audio.py --all --langs {" ".join(changed_langs)}')


if __name__ == '__main__':
    main()
