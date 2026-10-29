# Lobby / event anim → unit profile map

**Status:** applied to `site/data/lobby_anims.json` (2026-07-27).

| pack id | title | units | notes |
|---------|-------|-------|-------|
| `vsu6aa_lobby` | Aube — summer lobby | **c5190_1** | |
| `vva5aa_lobby` | Sweet Chocolate Scandal! | **c1171** | Tori |
| `vsu5aa_1` | Tropical Days illust 1 | **c5175** | Aram |
| `vsu5aa_2_lobby` | Tropical Days story 2 | **c5175** | |
| `vsu4aa1` | Summer 2024 illust 1 | **c5111** | |
| `vsu4aa2` | Summer 2024 illust 2 | **c5111, c1163, c1101, c3121** | c1101/c3121 are in the art but unit page skins may not match |
| `vsu3aa1` | Summer 2023 illust 1 | **c5082** | |
| `vsu3aa2` | Summer 2023 illust 2 | **c5149** | |
| `vae2aa1` | aespa collab | — | no unit link; candidate to drop from index |
| `vt41aa_1` | vt41aa EN | **c1162, c1100** | |
| `vms03c_1` | vms03c stack | **c2072, c2070** | hologram identity TBD |
| `epma_04` | Episode main (Salome) | **c2184_1** | variants: Idle + Story (one card) |
| `imgsa_1_1` | 5th anniv group | **c2076_1** | Shepherd of the Dark Diene (c2076 → c2076_1) |
| `vfr5aa_3` | Frieren illust 3 | — | multi cast / no link |
| `lobby_prequel_1` | Prequel lobby 1 | **c1166** | Victorika |
| `lobby_prequel_2` | Prequel lobby 2 | **c1166** | |

## Canonical JSON (re-apply with `apply_lobby_unit_map.py --map`)

```json
{
  "vsu6aa_lobby": ["c5190_1"],
  "vva5aa_lobby": ["c1171"],
  "vsu5aa_1": ["c5175"],
  "vsu5aa_2_lobby": ["c5175"],
  "vsu4aa1": ["c5111"],
  "vsu4aa2": ["c5111", "c1163", "c1101", "c3121"],
  "vsu3aa1": ["c5082"],
  "vsu3aa2": ["c5149"],
  "vae2aa1": [],
  "vt41aa_1": ["c1162", "c1100"],
  "vms03c_1": ["c2072", "c2070"],
  "epma_04": ["c2184_1"],
  "epma_04_story": ["c2184_1"],
  "imgsa_1_1": ["c2076_1"],
  "vfr5aa_3": [],
  "lobby_prequel_1": ["c1166"],
  "lobby_prequel_2": ["c1166"]
}
```

Open questions (your notes):
- **vae2aa1** — drop from catalog entirely?
- **vsu4aa2** — keep c1101/c3121 despite skin mismatch?
- **vms03c_1** — add hologram unit when identified?
