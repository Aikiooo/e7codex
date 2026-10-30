# E7 Codex — build tooling

The pipeline behind [e7codex.com](https://e7codex.com): a static, browsable
archive of Epic Seven character/artifact art with a live in-browser Spine
model viewer. This repo is the **tooling** — it turns raw, extracted game
assets into the finished static site. It ships **no game assets**; you bring
your own.

> **What's here:** the indexer, the asset-staging + pose-rendering pipeline,
> the SCSP→Spine converters (with attribution — see `CREDITS.md`), and the
> site UI.
>
> **What's NOT here (by design):** any Epic Seven assets, the cached
> spine-player runtime, and the community name databases. The steps below
> fetch or generate each of those locally.

## How it fits together

```
raw .scsp/.sct/.atlas  ──►  convert/  ──►  staged Spine JSON  ──►  site/assets/<slug>/
   (you supply)                      + decoded .png                   │
                                                                     ▼
                 pipeline/build_index.py  ──►  site/data/*.json  ◄── names from
                                                                     community DBs
                 render/poses.js          ──►  pose.png thumbnails
                                                                     │
                                                                     ▼
                                           site/index.html + viewer.html
```

`e7.py` is the entry point for all of it (`python e7.py build` / `python e7.py render`),
and `e7lib/` holds the shared plumbing every tool imports: data-root config,
`sys.path` bootstrap, the DB cipher primitives and the progress logger.

## Layout

```
e7.py                one entry point: build / render
e7lib/               shared config (reads private/keys/voice_keys.json), bootstrap,
                     db cipher primitives, logger
convert/             ssra.py (the local SSRA archive reader) + .scsp/.sct →
                     Spine JSON / PNG (2.1.27, 3.8.99, 4.2.43)
pipeline/            data builders: index, names, artifacts, voices, i18n, staging
render/              puppeteer bakes: poses, thumbs, skill-3 clips, backgrounds,
                     and illust/ (the lobby-illustration pipeline)
ops/leak_check.py    the unreleased-content gate (used by the deploy routine)
site/                the front end — HTML, the vendored encoders, 3 data configs
tests/               a few unit tests (pytest)
```


## Prerequisites

- Python 3.11+ (`pip install lz4 pillow texture2ddecoder xxhash zstandard`;
  `xxhash` + `zstandard` are only needed by `convert/ssra.py`)
- Node 18+ (`npm install` — pulls puppeteer + sharp for thumbnail rendering)
- Your own extracted Epic Seven assets (see step 2)

## Setup

### 1. Cache the Spine runtime (one-shot)

spine-player is **not** redistributed here. Fetch stock 3.8 from Esoteric and
apply the one-line screenshot patch:

```powershell
curl -sSL -A "Mozilla/5.0" -o site/spine-player.js  https://esotericsoftware.com/files/spine-player/3.8/spine-player.js
curl -sSL -A "Mozilla/5.0" -o site/spine-player.css https://esotericsoftware.com/files/spine-player/3.8/spine-player.css
# the bakes load it from render/vendor/, the illust pipeline from render/illust/
mkdir render\vendor, render\illust -Force
copy site\spine-player.js   render\vendor\spine-player.js
copy site\spine-player.css  render\vendor\spine-player.css
copy site\spine-player.js   render\illust\spine-player.js
copy site\spine-player.css  render\illust\spine-player.css
```

Then, in `site/spine-player.js` (around line 11071), enable buffer readback so
the viewer's screenshot button works:

```js
// find:    var webglConfig = { alpha: config.alpha };
// change:  var webglConfig = { alpha: config.alpha, preserveDrawingBuffer: true };
```

**Optional — Spine-2.1.x shear-free scale inheritance.** Spine 2.1.x tracked
world scale as scalars and rebuilt a clean rotation×scale matrix per bone, so a
non-uniform-scaled rotated parent never sheared its children. spine-player 3.8
composes full 2×2 matrices, which *do* accumulate shear there — exploding
long-aspect weapon meshes on some 2.1.27 combat rigs into needles. The converter
tags affected rigs with `"e7v21x": true`; a stock player ignores the flag (the
needle bug remains). To honor it, in `site/spine-player.js` find the start of
`Bone.prototype.updateWorldTransformWith` — just after `var parent = this.parent;`
(stock 3.8 follows it with `if (parent == null) {`) — and insert this gated
branch *before* that `if`:

```js
if (this.skeleton.data.e7v21x) {
    var sk = this.skeleton;
    var cosD = spine.MathUtils.cosDeg, sinD = spine.MathUtils.sinDeg;
    if (parent == null) {
        var wr = rotation, wsx = scaleX * sk.scaleX, wsy = scaleY * sk.scaleY;
        this._e7wr = wr; this._e7wsx = wsx; this._e7wsy = wsy;
        this.a = cosD(wr) * wsx; this.b = -sinD(wr) * wsy;
        this.c = sinD(wr) * wsx; this.d = cosD(wr) * wsy;
        this.worldX = x * sk.scaleX + sk.x;
        this.worldY = y * sk.scaleY + sk.y;
        return;
    }
    var pa = parent.a, pb = parent.b, pc = parent.c, pd = parent.d;
    this.worldX = pa * x + pb * y + parent.worldX;
    this.worldY = pc * x + pd * y + parent.worldY;
    var pwr = parent._e7wr || 0;
    var pwsx = parent._e7wsx != null ? parent._e7wsx : 1;
    var pwsy = parent._e7wsy != null ? parent._e7wsy : 1;
    var tm = this.data.transformMode;
    // Normal(0)/NoScale(3)/NoScaleOrReflection(4) inherit rotation;
    // Normal(0)/NoRotationOrReflection(2) inherit scale.
    var inhRot = (tm == 0 || tm == 3 || tm == 4);
    var inhScale = (tm == 0 || tm == 2);
    var wr = inhRot ? pwr + rotation : rotation;
    var wsx = inhScale ? pwsx * scaleX : scaleX;
    var wsy = inhScale ? pwsy * scaleY : scaleY;
    this._e7wr = wr; this._e7wsx = wsx; this._e7wsy = wsy;
    this.a = cosD(wr) * wsx; this.b = -sinD(wr) * wsy;
    this.c = sinD(wr) * wsx; this.d = cosD(wr) * wsy;
    return;
}
```

You also need the loader to carry the flag through: find
`skeletonData.imagesPath = skeletonMap.images;` and add
`skeletonData.e7v21x = skeletonMap.e7v21x;` after it. The branch is gated on the
flag, so 3.8.99 rigs and any bone without non-uniform scale under rotation are
untouched. Apply the same two edits to the `render/vendor/` and
`render/illust/` copies — the bakes need them too (only the readback one is
viewer-specific).

### 2. Bring your own data

This is the step you do yourself. You need:

- **Raw rigs** — the game's `.scsp` skeleton files (+ `.sct` textures, `.atlas`)
  for portraits and combat models. Since the 2026-10-29 patch the PC client no
  longer ships `data.pack`: its assets are an **SSRA archive** (`manifest.ssra`
  + `chunks/*.ssrc`, in the client's `gameres` folder). `convert/ssra.py` reads
  it locally — it never writes into the game folder and never downloads
  anything, so launch the game once first so it has installed every chunk:

  ```powershell
  python convert/ssra.py --game-dir "<EpicSeven>\gameres" --list              # what is installed
  python convert/ssra.py --game-dir "<EpicSeven>\gameres" --out <dump>\output  # extract
  python convert/ssra.py --game-dir "<EpicSeven>\gameres" --verify-only       # hash-check only
  ```

  The output tree keeps the client's folder layout (`portrait/`, `model/`,
  `effect/`, `db/`, `text/`, …); that folder is your `raw_dir`. `--groups a,b`
  limits the run to some groups (names from `--list`); missing chunks are
  listed and the run fails rather than writing a partial tree. Textures stay
  `.sct` — decode them into your `img_dir` with
  `python convert/decode_sct.py --batch <src_dir> <dst_dir>` (one folder at a
  time) or `python convert/decode_sct.py <in.sct> <out.png>`.
- **Names / slugs** — point the indexer at the public community databases
  (ceciliabot, epic7rtastats). See `CREDITS.md`. These are not bundled.
  - *Optional, self-sufficient:* if you have your own decrypted game data +
    keys set up (see the voice pipeline below — same `voice_keys.json`), run
    `python pipeline/names.py` to pull names + rarity/attribute/role
    straight from the game into `data_external/names_from_db.json`. The indexer
    layers it ahead of the community DBs. This also writes
    `unreleased_units.json` (units the game still labels "Unknown Hero"); the
    indexer drops those — the project does not publish unannounced/datamined
    units. Both files are gitignored.
  - *Artifacts (same setup):* `python pipeline/artifacts.py` decodes
    `equip_item.db` into `data_external/artifacts_from_db.json`, layered ahead
    of the community `Artifacts.json` for name/rarity/role. Gitignored.
  - *Localization (same setup):* `python pipeline/i18n.py` decodes each
    language's `text.db` into per-language display-name overlays
    (`site/data/lang/<lang>.json`) that power the site's language switcher
    (10 game languages + unofficial Vietnamese). It needs the same keys/data
    as `pipeline/names.py`, plus hand-maintained UI-chrome translations
    (`data_external/i18n_ui/<lang>.json`, not bundled). Without the overlays
    the switcher still renders and every name falls back to English.

Tell the pipeline where your data lives in **one place**: copy
`e7lib/voice_keys.example.json` to `private/keys/voice_keys.json` (gitignored —
the whole `private/` tree is) and set `raw_dir` (your extracted `output/`),
`img_dir` (decoded images), and `voice_dir` (voice scratch). `e7lib/config.py`
resolves these for every tool, so there's no code to edit; omitted keys default
under `dump_dir`.

### 3. Convert + stage

```powershell
python pipeline/prepare_assets.py --all          # portraits → site/assets/<slug>/
python pipeline/prepare_combat_assets.py --all   # combat rigs (optional)
```

To convert a single rig by hand: `python convert/scsp_to_json.py <in.scsp> <out.json>`.
`convert/scsp_to_json.py` auto-detects the rig version (2.1.27, 3.8.x, or 4.2.x)
and dispatches to the right converter — the vendored third-party ones for
2.1.27 / 3.8.x, and `convert/skel42_to_json38.py` for Spine 4.2 rigs (an
E7-wrapped stock `.skel`, converted down to 3.8-compatible JSON so the same
spine-player renders every rig).

### 4. Render pose thumbnails

```powershell
node render/poses.js        # bakes site/assets/<slug>/pose.png
```

Optionally, bake tighter character-only hub thumbnails (the site falls back to
`pose.png` when these are absent). Smart-crop is baked into the PNG at render
time:

```powershell
node render/thumbs.js       # site/assets/<slug>/thumb.png (FX/backdrop stripped, smart-cropped)
```

### 5. Build the data index

```powershell
python e7.py build                                    # uses e7lib/config.py roots
python pipeline/build_index.py --img <img_dir> --raw <raw_dir> --out ./site
```

### 6. Run locally

```powershell
cd site
python -m http.server 8765
# visit http://localhost:8765/
```

> Note: `site/index.html`, `viewer.html`, and `404.html` reference
> `favicon-16.png`, `favicon-32.png`, and `apple-touch-icon.png`, which are not
> shipped. Drop your own icons into `site/` or remove the `<link rel="icon">`
> tags — the site works either way (the browser just shows a default favicon).

## Optional: voice pipeline

The site can show per-hero voice-actor credits and a clickable catalog of voice
clips. This is an **optional** add-on with extra prerequisites, and like the rest
of the repo it ships **no game data and no keys** — you supply both.

You'll need:

- **vgmstream** — download a release build from
  [vgmstream](https://github.com/vgmstream/vgmstream/releases) and unzip it into
  `pipeline/vendor/vgmstream/` (so `pipeline/vendor/vgmstream/vgmstream-cli.exe`
  exists).
- **FFmpeg** — install it and make sure `ffmpeg` is on your `PATH`.
- **Your own keys + data** — copy `e7lib/voice_keys.example.json` to
  `private/keys/voice_keys.json` (gitignored) and fill in the values from your
  own install: `dump_dir` (+ optional `raw_dir` / `img_dir` / `voice_dir`), your
  outer-XOR key file (`outer_key_file`), and the default XXTEA key
  (`default_xxtea_key`). None of these are provided here.
- **Your own voice banks** — the FMOD `.bank` files, under
  `<voice_dir>/sound/<lang>/*.bank`. They are the `media_en` / `media_ja` /
  `media_ko` groups of the SSRA archive:

  ```powershell
  python convert/ssra.py --game-dir "<EpicSeven>\gameres" --groups media_en,media_ja,media_ko --out <tmp>
  ```

  The client only installs the voice languages you picked in its settings;
  `--list --include-media` shows which `media_*` chunks are missing.
  Then copy `<tmp>/sound/<lang>/*.bank` to `<voice_dir>/sound/<lang>/` (keep
  the file names). The three shared banks (`master.bank`,
  `master.strings.bank`, `voc.event.bank`) are in the main extraction under
  `sound/`; copy them to `<voice_dir>/sound/`.

Then:

```powershell
# Credits + a fallback line catalog from your local data files → site/data/voices.json
python pipeline/voices.py

# Decode the voice banks → OGG + a per-language catalog
python pipeline/voice_audio.py --langs en --slugs c1001     # subset / pilot
python pipeline/voice_audio.py --langs en ja ko --all       # full
```

`pipeline/voice_audio.py` reads banks from / writes OGGs to your configured
`voice_dir` (from `voice_keys.json`, default `<dump_dir>/_voice_work`); override
per-run with `--sound` / `--out` (or the `E7_VOICE_SOUND` / `E7_VOICE_OUT` env
vars). The generated audio and JSON stay local — they're gitignored and not part
of this repository.

## Deploying

`site/` is a self-contained static bundle — serve it from any static host
(GitHub Pages, Cloudflare Pages, Netlify, a plain web server, etc.). The Spine
assets under `site/assets/` are large; for production you'll likely want to
offload them to object storage and point the viewer at that host instead of
serving them inline. That wiring is left to you.

## Credits & licensing

See `CREDITS.md` for full attribution and `LICENSE` for terms. In short: the
E7 Codex code is MIT; the vendored converters keep their original authors'
terms; spine-player is Esoteric Software's; and Epic Seven assets belong to
Smilegate / Super Creative and are not part of this repository.
