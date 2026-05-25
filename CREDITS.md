# Credits & third-party components

E7 Codex stands on community work that came before it. The components below
were authored by others and are vendored or fetched as-is; E7 Codex's own
patches to them are committed separately (see git history) so the diff is
auditable.

## SCSP → Spine JSON converters

- **`epic7_scsp2json_v1_0/`** — Epic7 scsp2json v1.0 (handles the 2.1.27 `.scsp`
  format). Community converter from the e7herder ecosystem
  (https://github.com/zklm/e7herder-issues). Vendored verbatim, then patched
  in-tree for combat-rig support and spine-player 3.8 compatibility.
- **`E7_Scsp2Json.py`** — Epic Seven 3.8.99 `.scsp` → JSON converter by
  **Twistzz**. Source: https://live2dhub.com/t/topic/5799 ·
  https://github.com/violet-wdream/.Scripts (`Games/Yuna/E7/E7_Scsp2Json.py`).
  Vendored verbatim, then patched in-tree.

## Data sources (not bundled — fetch your own)

- **ceciliabot.github.io** — hero, skin, and artifact databases. Names, kebab
  slugs, and the deep links throughout the site come from these public datasets.
- **epic7rtastats.com** — hero metadata fallback for the most recent releases.
- **EpicSevenAssetRipper** (https://github.com/CeciliaBot/EpicSevenAssetRipper)
  — raw asset extraction from the game client. `tools/decode_sct.py` is a
  standalone port of its `.sct` texture decoder and follows that project's terms.

## Runtime

- **spine-player** 3.8 by **Esoteric Software** (https://esotericsoftware.com/spine-player)
  — drives the live viewer. Not redistributed here; the setup step fetches it
  from Esoteric and applies a one-line `preserveDrawingBuffer` patch.

## Copyright

Epic Seven and all related artwork, characters, names, and logos are the
intellectual property of Smilegate Holdings, Inc. and Super Creative. This
project ships no game assets; it is tooling that processes assets you supply.
