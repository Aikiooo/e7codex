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
raw .scsp/.sct/.atlas  ──►  converters  ──►  staged Spine JSON  ──►  site/assets/<slug>/
   (you supply)            (this repo)        + decoded .png            │
                                                                        ▼
                          build_index.py  ──►  site/data/*.json  ◄── names from
                                                                      community DBs
                          render_poses.js ──►  pose.png thumbnails
                                                                        │
                                                                        ▼
                                              site/index.html + viewer.html
```

## Prerequisites

- Python 3.11+ (`pip install lz4 pillow texture2ddecoder`)
- Node 18+ (`npm install` — pulls puppeteer + sharp for thumbnail rendering)
- Your own extracted Epic Seven assets (see step 2)

## Setup

### 1. Cache the Spine runtime (one-shot)

spine-player is **not** redistributed here. Fetch stock 3.8 from Esoteric and
apply the one-line screenshot patch:

```powershell
curl -sSL -A "Mozilla/5.0" -o site/spine-player.js  https://esotericsoftware.com/files/spine-player/3.8/spine-player.js
curl -sSL -A "Mozilla/5.0" -o site/spine-player.css https://esotericsoftware.com/files/spine-player/3.8/spine-player.css
copy site\spine-player.js  tools\spine-player.js
copy site\spine-player.css tools\spine-player.css
```

Then, in `site/spine-player.js` (around line 11071), enable buffer readback so
the viewer's screenshot button works:

```js
// find:    var webglConfig = { alpha: config.alpha };
// change:  var webglConfig = { alpha: config.alpha, preserveDrawingBuffer: true };
```

### 2. Bring your own data

This is the step you do yourself. You need:

- **Raw rigs** — the game's `.scsp` skeleton files (+ `.sct` textures, `.atlas`)
  for portraits and combat models. Extracting these from the client is on you;
  the community tool for it is
  [EpicSevenAssetRipper](https://github.com/CeciliaBot/EpicSevenAssetRipper).
- **Names / slugs** — point the indexer at the public community databases
  (ceciliabot, epic7rtastats). See `CREDITS.md`. These are not bundled.

Drop the raw assets where the pipeline expects them and adjust the paths at the
top of `tools/prepare_assets.py` / `E7_Scsp2Json.py` to match.

### 3. Convert + stage

```powershell
python tools/prepare_assets.py --all          # portraits → site/assets/<slug>/
python tools/prepare_combat_assets.py --all    # combat rigs (optional)
```

`tools/scsp_to_json.py` auto-detects the rig version (2.1.27 vs 3.8.99) and
dispatches to the right converter.

### 4. Render pose thumbnails

```powershell
node tools/render_poses.js        # bakes site/assets/<slug>/pose.png
```

Optionally, bake tighter character-only hub thumbnails and pose-crop hints
(the site falls back to `pose.png` / no crop when these are absent):

```powershell
node tools/render_thumbs.js       # site/assets/<slug>/thumb.png (FX/backdrop stripped)
node tools/compute_trim_data.js   # site/assets/<slug>/pose_trim.json (CSS crop hints)
```

### 5. Build the data index

```powershell
python build_index.py --img <your_img_dir> --raw <your_raw_dir> --out ./site
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
