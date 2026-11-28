# Roadmap

Ordered by what unlocks the most understanding per hour. Phases are not
calendar promises; each has a concrete exit test.

## Phase 0 — a complete, honest tree (done)

- [x] Read-only Ghidra export of all 46,458 `.text` functions
- [x] 250-function banks, resumable, parallel-safe
- [x] Per-function metadata: address, size, name, calls, string references
- [x] Symbol, prototype, string, and unit indexes
- [x] Query CLI (`status`, `stats`, `search`, `explain`, `callers`, `strings`, `suggest`)

Exit test: `decompile.py status` reports every function, and `explain` works
for any address without Ghidra.

## Phase 1 — names for the unnamed

- [x] Seoul Engine exports (200)
- [x] RTTI / vtable-derived class names and lifetimes
- [x] Vtable scan (608 vtables, 527 classes) and 2,850 slot labels
- [ ] Imported-API clustering: group functions by called Win32/D3D/FMOD APIs
      and name the groups (`d3d9_device_*`, `fmod_event_*`)
- [ ] String-driven names: turn the best string reference into a
      `// strings:` note and a review queue; add `GUESS` confidence markers
- [x] Virtual-call recovery: identify vtable slots and label the functions
      stored in them (`Class::vfunc_N`, guess provenance recorded)
- [ ] Replace `vfunc_N` labels with real method names from RPC tables, strings,
      and overriding relationships
- [ ] Script/console tables: find string→function-handler tables and name the
      handlers from their script names
- [ ] Static-library fingerprinting: match known Seoul Engine / RakNet /
      PhysX 2.8.4 / zlib code against public matching builds where licences
      allow names only

Exit test: every bank has a one-line subsystem guess, and the share of
`FUN_` names is below 90% with each new name marked by source and confidence.
(Current: 92.8% unnamed, 7.2% named, all names carry provenance.)

## Phase 2 — types and compilable units

- [ ] Promote the most-used inferred structs into `include/game/`
- [ ] Rebuild class layouts from RTTI and constructor/destructor call sites
- [ ] Make one bank parse as C with a normal compiler (syntax only, not match)
- [ ] Replace Ghidra vocabulary in that bank with real MSVC 2008 types
- [ ] Add `// src:` provenance markers for every non-guessed name

Exit test: one bank compiles cleanly against reconstructed headers with no
Ghidra `undefined*` types, and still decompiles consistently.

## Phase 3 — the matching loop

- [x] MSVC 2008 SP1 + RTM running under Wine/Docker (`tools/msvc/`)
- [x] `tools/match/verify.py`: compile and compare the matched registry
- [x] First matched units: 149 tail thunks + 19 accessors + 5 leaf/reloc functions (173 functions, 945 bytes)
- [ ] Relocation-aware comparison through the unit symbol map
- [ ] Per-unit flags inferred from the binary
- [ ] Exception-handling and `fold_alias` accounting
- [ ] First fully matched bank (start with small Seoul Engine exports)
- [ ] CI-style check that compares changed banks only

Exit test: a bank reports `N/N functions match`, reproduced from a clean
checkout plus the user's own image.

## Phase 4 — breadth

- [ ] Match subsystem by subsystem, tracking bytes not function counts
- [ ] Recover original translation-unit boundaries where evidence supports it
- [ ] Names/comments review pass (machine-proposed, human-accepted)
- [ ] Optional: repeat the pipeline for the shipped middleware DLLs
      (`PhysXCore`, `fmodex`, `fmod_event`, `d3dx9_43`)

## Non-goals

- Distributing the game, its assets, or bytes from the executable.
- A playable build. The parent repo's static recompilation is the playable
  artifact; this tree is a reference.
- Guessing names without recording that they are guesses.
