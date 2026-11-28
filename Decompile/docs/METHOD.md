# Method

This document records how the tree is produced, so the output can be audited
and regenerated rather than trusted.

## Inputs

| Input | Where | Notes |
| --- | --- | --- |
| Original image | `work/inputs/exe/ShootManyRobots.exe` | PE32, i386, image base `0x00400000`, SHA-256 in `config/project.json` |
| Ghidra project | `work/ghidra/game` (`smr`) | Built by the static-recompilation pipeline in the parent repo; analyzed with jump tables resolved and split entries fixed |
| Ghidra | 12.2 from Homebrew | `brew install ghidra`; requires OpenJDK 25 |
| Decompiler | Ghidra `DecompInterface`, default simplification | One function at a time, 120 s timeout |

The Ghidra project is opened **read-only**. Decompilation never mutates the
analysis used by the recompiler.

## Pipeline

```text
work/ghidra/game (analyzed program)
        │
        ├─ ExportTree.java     function bodies -> src/game/bank_NNNN.c
        │                      metadata       -> build/game/meta/bank_NNNN.jsonl
        ├─ ExportData.java     data symbols   -> build/game/data_symbols.csv
        ├─ ExportTypes.java    structs/enums  -> include/game/smr_types.h
        │
        └─ merge (final 0/1 pass)
               build/game/functions.jsonl   46,458 records
               build/game/symbols.csv
               build/game/prototypes.h
               build/game/strings.tsv
               build/game/banks.txt
```

### Banks

Functions are sorted by entry address and grouped 250 at a time. A bank is the
unit of work and the unit of the eventual matching build:

- one deterministic address range per bank;
- each bank is written atomically (`.c` then `.jsonl`);
- an existing non-empty bank file is skipped, so an interrupted export resumes;
- `shardK/shardN` lets several Ghidra processes work on disjoint banks.

Bank grouping is deliberately mechanical. Inventing source files from
heuristics would hide how little is actually known; a bank is an honest unit.
Once functions are named and typed, banks can be split into real translation
units and `build/units.json` updated.

### Vtable pass

`tools/analyze_vtables.py` scans `.rdata`/`.data` for MSVC RTTI:

```text
vtable[-1] -> CompleteObjectLocator
  +0 signature, +12 TypeDescriptor, +16 ClassHierarchy, +20 self
TypeDescriptor +8 -> ".?AVClass@Namespace@@"
```

A locator is accepted only when its type descriptor agrees and its self pointer
is zero or exact. A vtable is accepted only when the word before it is that
locator and its slots point into `.text`. The result is `vtables.csv`,
`vtable_slots.csv`, and `vtable_names.csv`. `tools/apply_names.py` then renames
only functions that are still `FUN_`/`thunk_`, records `name_source:
vtable:RTTI` plus the placeholder in `functions.jsonl`, and rewrites the source,
metadata, prototypes, and string index in place.

This is a *labelling* pass, not proof: slot 4 of a class vtable is not
necessarily the fourth virtual function in the original source, and a shared
thunk can appear in several classes. Treat `Class::vfunc_N` as a locator.

### Per-function record

Every function has a JSON record (`build/game/functions.jsonl`):

```json
{"addr":"00401000","name":"FUN_00401000","size":27,"bank":"bank_0000",
 "source":"","decompiled":true,"signature":"float10 FUN_00401000(void);",
 "calls":["ext:rand"],"strings":[]}
```

- `addr`, `size` come from the Ghidra function body.
- `name` is fully qualified (`Class::method` when a namespace exists).
- `source` is filled only when a `Source:` plate comment exists. Only a handful
  of RakNet/PhysX source strings survive in the retail image; the game's own
  source paths do not.
- `calls` are callee addresses, or `ext:<name>` for imports.
- `strings` are the highest-signal string references in the body, used for
  search and as a first hint when naming a function.
- `placeholder`/`name_source` appear after a naming pass, so a guessed name can
  be audited and reverted.

### What is not recovered

- **No PDB.** The image retains the PDB *path* but no symbol table. 43,095 of
  46,458 functions still have no name after vtable naming.
- **200 exports.** The image exports the Seoul Engine API surface; those names
  are real and are already applied by Ghidra.
- **RTTI/vtables.** Ghidra's MSVC RTTI analysis names classes, vtables and some
  constructors/destructors (313 additional named functions). A separate Python
  scan of the image's `RTTICompleteObjectLocator` records finds **608 vtables
  across 527 classes** and **7,715 slots**; 2,850 unnamed slot targets are
  labelled `Class::vfunc_N` as recorded guesses.
- **No original types.** Struct layouts are inferred by the decompiler and are
  not yet promoted into shared headers.

## Reproducing

```sh
brew install ghidra openjdk@25
./Decompile/tools/export.sh game 4        # ~5 min on a 10-core Apple silicon Mac
python3 Decompile/tools/decompile.py units
python3 Decompile/tools/analyze_vtables.py
python3 Decompile/tools/apply_names.py
python3 Decompile/tools/decompile.py units
```

The exporter refuses to guess: if the Ghidra project or image is missing it
stops. It does not download the game or any tool that contains game code. Only
functions in the `.text` block are exported; the Steam packer's `.bind` stubs
are excluded (`SMR_CODE_BLOCK=*` overrides this).

## Improving output

1. **Names.** Work outward from the 200 exports and RTTI classes. Strings are
   indexed per function (`strings.tsv`) and make subsystem triage practical.
2. **Types.** `ExportTypes.java` writes the current Ghidra data types. These are
   decompiler-inferred, not original; promote one struct at a time when call
   sites agree.
3. **Call graph.** `decompile.py callers` is the fastest way to understand a
   function's contract; callers constrain prototypes.
4. **Matching.** See [MATCHING.md](MATCHING.md). A bank only graduates from
   "reference" to "matched" when MSVC 2008 reproduces its bytes.
