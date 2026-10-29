"""One-shot audit: list slugs whose pose render output will change under the
new default+normal+<expression> rule. A slug is "broken-by-design" — and so
benefits from the expression layer — when it has a generic face slot
(face/eye/eyeA/head/mouth/lip/brow/eyebrow/nose/normal/normal) whose setup-
pose attachment is also a generic face name (face/eye/eyeA/head/.../1) but
that attachment is NOT provided by either the `default` or `normal` skin.
The expression skins (smile/angry/panic/sad/special) carry it instead.

For rigs whose `default + normal` already supplies the face features, the
layer is a no-op visually but adds an unwanted expression overlay — we
must NOT trigger then.

Prints a newline-separated list of affected slugs to stdout."""

import json
import re
import sys
from pathlib import Path

ASSETS = Path(__file__).resolve().parent.parent / "site" / "assets"

# Critical SLOT names: generic face-piece identifiers that should be
# visible in a "neutral" pose. eye[A-Z]? covers c3011's eyeA/eyeB pattern.
CRIT_SLOT = re.compile(
    r"^(face|head|head2|eye[A-Z]?|mouth|lip|brow|eyebrow|nose"
    r"|normal|normal/normal|face/face|head/head)$"
)
# Critical setup-pose ATTACHMENT names: same generic identifiers plus '1'
# (the bare-numeric attachment name used on normal/normal slots) and any
# single digit (npc1366's `normal` slot has setup `3`). This second check
# rejects expression-suffixed setup names like 'angry/angry_face' that
# exist on slots which match CRIT_SLOT but are meant to be invisible by
# default.
CRIT_SETUP = re.compile(r"^(face|head|head2|eye[A-Z]?|mouth|lip|brow|eyebrow|nose|normal|1|\d)$")

# Per-slug overrides for rigs whose missing-face slot does NOT match the
# generic regex above. Adding the slug here forces the expression layer
# regardless of slot/attachment naming.
#   npc1366: missing eye lives in slot `bone4` (setup attachment `bone4`),
#            provided only by expression skins. See docs/TASKS.md Task #17.
#   npc1038/npc1160: face slot `normal/face3` (setup `1`) lives only in
#            expressions — the "no mouth" pattern. Widening CRIT_SLOT to
#            cover `normal/face\d+` would false-trigger on working rigs
#            like c1003_s01/c1046_s01 that use the same structure for
#            optional features. See docs/TASKS.md Task #22.
#   npc1152: face slot `normal/normal5` (setup `1`) lives only in
#            expressions. Same widening risk on c1003_s01/c2046_s01.
#   npc1235/npc1277: face slot `normal5`/`normal4` (setup `normal5`/
#            `normal4`) lives only in expressions. Same widening risk
#            on c4052/c5070/c1117/c1123 — structurally identical but
#            those slots are intentionally hidden in their resting pose.
# Cleared 2026-07-18: these entries were workarounds for E7_Scsp2Json
# special_process stripping shared face slots from the "normal" skin
# (mouth / normal1..5 / etc.). With special_process disabled, default+normal
# already carries the resting face — forcing smile would bake an unwanted
# expression onto pose/thumb. Re-add a slug only if default+normal is still
# genuinely mouthless after a fresh convert.
EXPRESSION_FORCE = set()

# Second heuristic: rigs that lack a neutral face anywhere in default+normal,
# while expression skins provide one. The face-piece regex is broader than
# CRIT_SLOT (allows expression-shape suffixes like `_ag`/`_sm`, plus path
# prefixes like `normal/face_nm`) — but deliberately omits bare `normal`,
# which in minimalist NPC rigs is the body slot (e.g. npc1175), not the face.
# Caught: npc1136 (default=body), npc1138 (default=`15`), npc1175 (default=`normal` slot).
FACE_PIECE = re.compile(
    r"^(?:[a-z]+/)?(face|head|eye|mouth|lip|brow|eyebrow|nose|cheek)"
    r"(?:[A-Z\d]|[_/]\w+)?$",
    re.IGNORECASE,
)
EXPR_SKINS = frozenset({"smile", "angry", "panic", "sad", "special", "special2", "special3"})


def _has_face_piece(attachments) -> bool:
    return any(FACE_PIECE.match(n) for n in attachments)


def _needs_layer_no_neutral_face(d) -> bool:
    skins = {sk["name"]: sk.get("attachments", {}) for sk in d.get("skins", []) if isinstance(sk, dict)}
    if _has_face_piece(skins.get("default", {})) or _has_face_piece(skins.get("normal", {})):
        return False
    for name, atts in skins.items():
        if name in EXPR_SKINS and _has_face_piece(atts):
            return True
    return False


def slug_is_affected(json_path: Path) -> bool:
    if json_path.parent.name in EXPRESSION_FORCE:
        return True
    try:
        d = json.loads(json_path.read_text(encoding="utf-8"))
    except Exception:
        return False
    if _needs_layer_no_neutral_face(d):
        return True
    skins = {sk["name"]: sk.get("attachments", {}) for sk in d.get("skins", []) if isinstance(sk, dict)}
    defs = skins.get("default", {})
    norm = skins.get("normal", {})
    for s in d.get("slots", []):
        name = s.get("name", "")
        setup = s.get("attachment")
        if not setup:
            continue
        if not CRIT_SLOT.match(name):
            continue
        if not CRIT_SETUP.match(setup):
            continue
        if name in defs and setup in defs[name]:
            continue
        if name in norm and setup in norm[name]:
            continue
        return True
    return False


def main() -> int:
    if not ASSETS.is_dir():
        print(f"missing {ASSETS}", file=sys.stderr)
        return 2
    affected = []
    for slug_dir in sorted(ASSETS.iterdir()):
        if not slug_dir.is_dir():
            continue
        json_path = slug_dir / f"{slug_dir.name}.json"
        if not json_path.is_file():
            continue
        if slug_is_affected(json_path):
            affected.append(slug_dir.name)
    for s in affected:
        print(s)
    print(f"\n[{len(affected)} slugs affected]", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
