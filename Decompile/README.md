# Shoot Many Robots — decompilation

A work-in-progress, function-by-function decompilation of the 2012 Windows
release of **Shoot Many Robots** (Demiurge Studios, Seoul Engine), modelled on
the [Fallout: New Vegas](https://github.com/momusdigital/fnv_decomp) and Fallout 3
decompilation projects.

This is the *readable source* half of the project. The parent repo contains a
separate static-recompilation port that runs the game; nothing here is needed
to play it, and nothing here is playable.

> **Status: reference decompilation, not a matching build yet.**
> All 46,458 functions in the game's `.text` block have been exported as C by
> Ghidra 12.2; 4 of them fail the decompiler and are marked in place. 3,363
> functions carry names: 513 from the executable's 200 Seoul Engine exports
> plus Ghidra RTTI, and 2,850 recovered from **608 RTTI vtables across 527
> classes** (class/slot labels, recorded as guesses). The other 43,095 are
> `FUN_` placeholders. The 6 Steam-packer stubs in `.bind` are deliberately
> excluded. Zero functions have been rebuilt to byte-identical machine code so
> far. See [docs/STATUS.md](docs/STATUS.md) and [docs/FINDINGS.md](docs/FINDINGS.md).

---

## Layout

| Path | What it holds |
| --- | --- |
| `src/game/bank_NNNN.c` | Generated C, 250 functions per bank, address order (186 banks) |
| `build/game/functions.jsonl` | One record per function: address, size, name, strings, calls |
| `build/game/symbols.csv` | Flat symbol table |
| `build/game/prototypes.h` | Signatures recovered by the decompiler |
| `build/game/strings.tsv` | String references per function (the best naming lead) |
| `build/game/units.json` | Build recipe: bank → functions, for the matching harness |
| `build/game/vtables.csv` | 608 RTTI vtables, class names and slot counts |
| `build/game/vtable_slots.csv` | Every virtual slot and its target function |
| `build/game/vtable_names.csv` | Remaining `Class::vfunc_N` proposals (empty once applied) |
| `build/game/names_applied.csv` | Audit log of every applied name and its provenance |
| `build/game/suggested_names.csv` | 4,026 string-derived name suggestions |
| `include/smr_ghidra_types.h` | Ghidra type vocabulary (`undefined4`, `float10`, …) |
| `include/game/` | Exported/inferred type headers |
| `tools/export.sh` | Headless Ghidra driver (parallel, resumable) |
| `tools/decompile.py` | Search / explain / callers / stats / suggest front-end |
| `tools/analyze_vtables.py` | MSVC RTTI + vtable scanner |
| `tools/apply_names.py` | Apply a rename map to the tree, with provenance |
| `tools/ghidra/` | Export scripts |
| `tools/match/` | PE + COFF readers and the byte-exact comparison harness |
| `config/project.json` | Image fingerprint, PE facts, toolchain |
| `docs/` | [Method](docs/METHOD.md), [status](docs/STATUS.md), [findings](docs/FINDINGS.md), [matching](docs/MATCHING.md), [roadmap](docs/ROADMAP.md) |

Generated output is intentionally kept out of Git: `src/`, `build/`,
`include/game/` and `share/` are ignored. The tracked part is the pipeline, the
small config and the docs; anyone with the game can regenerate the tree.

---

## Quick start

Requires the game's unpacked executable at `work/inputs/exe/ShootManyRobots.exe`
(the parent repo's `./scripts/recomp doctor` prepares it), Ghidra 12.2 and
OpenJDK 25.

```sh
brew install ghidra openjdk@25

# decompile everything (~5 min on a 10-core Mac; resumable)
./Decompile/tools/export.sh game 4

# recover RTTI vtables and label unnamed virtual functions
python3 Decompile/tools/analyze_vtables.py
python3 Decompile/tools/apply_names.py
python3 Decompile/tools/decompile.py units

python3 Decompile/tools/decompile.py status
python3 Decompile/tools/decompile.py stats
python3 Decompile/tools/decompile.py explain 0x5d5f80
python3 Decompile/tools/decompile.py callers 0x5d5f80
python3 Decompile/tools/decompile.py strings weapon --limit 20
python3 Decompile/tools/decompile.py suggest --limit 20
python3 Decompile/tools/decompile.py search lobby --field strings
```

`explain` prints the metadata and the C body without opening Ghidra:

```text
address   005d5f80  size 288
name      GWaitable::Wait
...
```

---

## How it works

1. The parent project's Ghidra analysis (`work/ghidra/game`, program `smr`) is
   opened **read-only**.
2. `ExportTree.java` decompiles each function and writes it to an address-range
   bank, together with a JSON record of callees and referenced strings.
3. A final single pass merges the per-bank records into the indexes and
   regenerates `units.json`.
4. `decompile.py` answers questions from the index; source stays in plain `.c`
   files that any editor or `rg` can read.

Banks are mechanical on purpose. The retail image has no PDB and almost no
game source paths, so inventing source files or module names would hide how
much is actually unknown. See [docs/METHOD.md](docs/METHOD.md).

### What is known

- **200 exports** name the Seoul Engine API surface (`GSystem`, `GMatrix3D`,
  `GSysFile`, `GThread`, `GImage`, …). These are real names.
- **RTTI and vtables** contribute constructors, destructors, class scopes and
  **2,850 class/slot virtual-function labels** across 608 vtables
  (`GSysAlloc::vfunc_04`, `Player::vfunc_01`). These are labelled guesses,
  not original names.
- **UI/script keys** such as `lobby_quickmatch_searching` are indexed per
  function and are the best lead for the remaining 43,095 placeholders.
- **RPC method strings** such as `SomervilleGameApp::ClientLevelStarted`
  describe the multiplayer protocol, but this pool is unreferenced in the
  image; mapping it to handlers needs the RPC dispatch table.
- **No PDB, no MAP, no debug symbols.** The PDB path survives in the image;
  the file does not. The 6 `.bind` functions are Steam DRM/packer stubs and are
  out of scope.
- Whether a `vfunc_N` slot is a real override, a shared thunk, or a secondary
  base vtable entry; the label identifies the class and slot, not the source
  method name.

### What is not known

- Original function names for 92.8% of the code.
- Original struct layouts, enums, and class hierarchies beyond RTTI basics.
- Original source file boundaries and compiler flags.
- Whether a given Ghidra body compiles to the original bytes (none tested yet).

---

## Matching

`tools/match/` is the beginning of the Fallout-style byte-exact loop:

```sh
# validate the readers against the known image
python3 Decompile/tools/match/compare.py --selftest

# compare a COFF object with the original functions
python3 Decompile/tools/match/compare.py \
    --object build/obj/bank_0000.obj --bank bank_0000
```

It understands PE32 sections, i386 COFF symbols/relocations, and reports
matches, mismatches, missing symbols, and which relocation bytes were skipped.
A tiny example already works as a warning: clang encodes `xor eax,eax` as
`31 c0`, the game's MSVC 2008 build as `33 c0`, so only the original compiler
can be the authority. See [docs/MATCHING.md](docs/MATCHING.md).

---

## Legal

This repository contains **no game assets, no game executable and no bytes
copied from the game**. It contains decompiled source text derived from the
user's own copy, addresses/sizes, and our tooling. You need a legally owned
copy of *Shoot Many Robots* to use any of it; it is not a way around buying the
game, and it is not playable.

The contributors' own work in `Decompile/` (tooling, docs, names, comments) is
dedicated to the public domain under CC0 1.0. That grant does not cover the
game, its code, its data, its assets, or any trademark. *Shoot Many Robots* is
© Demiurge Studios; Seoul Engine is © Demiurge Studios; DirectX, FMOD, PhysX
and other middleware belong to their respective owners. This project is not
affiliated with or endorsed by any of them.
