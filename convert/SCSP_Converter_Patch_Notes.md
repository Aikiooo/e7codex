# Patch Notes: SCSP to JSON Converter (`_epic7_scsp2json_v2_1_27.py`)

## Overview
During asset processing via `prepare_assets.py`, the Spine 2.1.27 converter (`_epic7_scsp2json_v2_1_27.py`) was encountering fatal errors (`IndexError` and intentional `sys.exit()` calls) when handling certain portrait `.scsp` files (specifically `c1035`, `c1088`, `c1092`, `c1097`, `c2002`, `c2053`, and `c4041`). These files contained malformed, non-standard, or corrupted animation data. 

To ensure the batch processing pipeline runs continuously without completely halting on corrupted files, several defensive programming patches were applied to the converter.

## Modified Files
* `convert/vendor/epic7_scsp2json_v1_0/_epic7_scsp2json_v2_1_27.py`

## Detailed Changes

### 1. Bounds Checking for Bones and Slots
* **Issue:** Malformed files referenced `animation_slot` indices that exceeded the length of the parsed `bones` and `slots` arrays, resulting in an `IndexError` (around lines 941 and 958).
* **Fix:** Added validation checks before array indexing. If an index is out of bounds, the script now gracefully skips the invalid slot/bone assignment rather than throwing a python exception.

### 2. Handled Invalid Animation Modes
* **Issue:** Corrupted files provided invalid `animation_mode` values (e.g., `>= 65534` or `0x00000000`), which originally triggered an abrupt script termination (`sys.exit(1)`).
* **Fix:** Replaced hard exits with a warning print statement and a `continue` / `pass` instruction to skip the corrupted animation sequence and move on to the next.

### 3. Sanity Checks for Item Counts
* **Issue:** Data corruption (or shifted bytes) caused `anim_items_count` to evaluate to unreasonably large numbers (e.g., `> 100,000,000`), leading to memory/processing errors and cascading failures.
* **Fix:** Implemented a threshold validation check. If `anim_items_count` exceeds a realistic upper bound (e.g., `> 1,000,000`), it is treated as a corruption flag, and the item processing is safely bypassed.

### 4. Bypassing Hard Exits on Unknown Curve Types (Patch 1 — partial)
* **Issue:** Unknown animation curve modes triggered legacy debugging exits (`print("WTF?! animation_mode_curve")` followed by `sys.exit(1)`).
* **Fix (partial):** Only the first occurrence was patched in the initial pass, leaving 4 duplicate `sys.exit(1)` calls across the scale / rotate / translate / color / FFD curve-reading loops.

### 5. Remaining `sys.exit` calls removed (Patch 2 — 2026-05-20)
* **Issue:** The 4 remaining `WTF?! animation_mode_curve` + `sys.exit(1)` blocks in the scale, rotate, translate, color, and FFD sections were still live, causing `c2053` to crash after the Patch 1 fix.
* **Fix:** All 5 occurrences replaced with `print(f"!!! Unknown curve type {animation_mode_curve}; continuing")` + no exit.
* **Also fixed:** Unknown `skin_mode` at line ~568, previously also a hard `sys.exit(1)`, replaced with `print` + `continue`.

## Current Status (2026-05-20)
| Slug   | Status |
|--------|--------|
| c1035  | ✅ Fixed — converter succeeds |
| c1088  | ✅ Fixed — converter succeeds (re-run needed after Patch 1) |
| c1092  | ✅ Fixed — converter succeeds |
| c1097  | ✅ Fixed — converter succeeds |
| c2002  | ✅ Fixed — converter succeeds |
| c2053  | ❌ Still failing — parser loses byte-stream sync after unknown animation modes (deep corruption; `struct.unpack` buffer underflow). See TASKS.md. |
| c4041  | ✅ Fixed — converter succeeds (re-run needed after Patch 1) |

## Impact
The batch converter now survives malformed portrait inputs for 6 of the 7 originally failing files. `c2053` remains unresolvable with the current parser — the file's animation section contains unknown mode values that make the parser lose its byte-stream position, causing a `struct.error` on the next read.

---

## Patch 6 (2026-05-22): Combat-rig support — header detect, BBOX, events block, mode 9/10 byte-alignment

* **Issue:** Combat rigs in `output/model/` use a "new format" 2.1.27 binary with a different header layout, BBOX skin attachments, an explicit events block, and previously-unseen animation modes 9 and 10. The portrait-format parser couldn't read any of these.
* **Fix:**
  - `detect_version()` upgraded from 64KB head-scan to full-body scan (combat rigs carry the marker 2-9 MB deep).
  - New-format header detect via `b"scsp"` magic at `[8:12]`; bones start at offset 116 instead of 88; counts read at `[44:72]`.
  - BBOX attachment handler added (mode 1 in skin block): `skin_item_path_link2ref` is repurposed as vertex-count-in-floats, followed by N floats (no color/width/height/padding).
  - Events block parser: `count_events × 16-byte records` of `(sentinel, name_ref, intValue, floatValue)`.
  - Mode 9 and 10 animation records consumed for byte-alignment: `idx(4) + sub_type(4) + raw_count(4) + (raw_count/2)*8` bytes per record. Data discarded — see Patch 8 for the open work.
  - Per-anim trailer scan-forward via `_scsp_findNextAnimHeader` (trailer carries drawOrder/event timelines; not modelled in JSON output yet).

## Patch 7 (2026-05-23 morning): Refstring sentinel + skin dedup + empty timeline prune

Three independent combat-rig converter bugs found and fixed. Closed the shadow-only render bug.

1. **Refstring null sentinel (lines 426 + 980).** Converter used `if ref < 65535` to mean "null/empty name". Combat rigs ship 100-200 KB refstring tables; legitimate offsets routinely exceed 65535 and were silently nulled. Real sentinel is uint32 `0xFFFFFFFF`. After fix: attachment names resolve correctly and empty-name keyframes emit JSON `null` (the proper Spine 3.8 hidden-slot marker).
2. **Skin sub-record dedup (line 612).** Inner skin loop did `skins[name][slot] = {}` on every sub-record, wiping prior attachments. Combat rigs ship 2-10 attachments per slot for mesh-swaps; Charlotte's 162 sub-records collapsed to 94. Fixed to `setdefault`-style init.
3. **Empty timeline arrays (`convert/scsp_to_json.py:post_process_2_1_27`).** Some rigs (c3143 weapon2) shipped 0-length bone timelines, crashing spine-player with `frameCount must be > 0`. Post-process now prunes empty `bones.*.<kind>` and `slots.*.<kind>` arrays.

Visually verified after this patch: c1144, c1009, c3143, c1067 render full body + accessories in idle/skill1/skill2.

## Patch 8 (OPEN — 2026-05-23 evening diagnostic): Mode 9/10 emission + post-events block decode

* **Issue:** After Patch 7, head/hand/elbow artefacts remain on every 2.1.27 combat rig (visible on c1112_s01 + c3143 most obviously, subtle on c1144). Diagnostic session proved:
  - Setup pose renders correctly (stripped-animations test on c3143 → clean standing pose).
  - Mode 9/10 records are constraint-MIX timelines (values are 0.0/1.0 in idle; ramp counts increase in skill anims).
  - `idx` field is a bone index; targeted bones for abigail include `1_head` directly — matches user's reported symptoms exactly.
  - The post-events block (~1 MB between events-end and first-animation in abigail) is E7's homegrown per-bone constraint declaration table (no canonical Spine 2.1.27 analogue — confirmed via canonical source review).
* **Fix:** **Not yet shipped.** Requires reverse-engineering the post-events block to extract constraint declarations (target bone, offset, type), emitting them as Spine 3.8 transform constraints at JSON root, and wiring mode 9/10 records as their mix timelines. Three search avenues (canonical Spine source, e7herder dump, other community converters) confirmed no public corpus exists to diff against — manual RE required.
* See `docs/TASKS.md` → "Combat rig live viewer" for the proven-root-cause narrative and concrete next-session steps. Memory pointers: `[[project-e7-2127-combat-constraints-next]]` and `[[reference-spine-2127-format-sources]]`.

## Current Status (2026-05-23 evening)
| Slug   | Status |
|--------|--------|
| c1035, c1088, c1092, c1097, c2002, c4041 | ✅ Fixed by Patches 1-5 |
| c2053  | ❌ Still failing (deep portrait-rig corruption; see above) |
| Combat rigs — body | ✅ Render correctly (Patch 7) |
| Combat rigs — bone constraints (head/hand/elbow) | ❌ Open (Patch 8 pending; post-events block decode required) |
| 9 combat-rig parse-drift failures (achates_s01, aither_s01, bernard, byblis, chloe, karin_s01, pavel, rimuru, suthan) | ❌ Per-rig deferred — same scan-forward / mode-handler treatment as abigail RE took ~one session per rig |
