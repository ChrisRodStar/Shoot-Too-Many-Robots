# Status snapshot

Generated from `Decompile/build/game/functions.jsonl` and the RTTI scan on
2026-11-28. Re-run `python3 Decompile/tools/decompile.py stats` after a new
export.

## Coverage

| Metric | Value |
| --- | --- |
| Functions in `.text` | **46,458** |
| Ghidra decompile failures | **4** (listed below) |
| Code bytes (Ghidra bodies) | **5,601,322** |
| Generated C | **34.2 MB** across 186 banks |
| Named functions | **3,363 (7.2%)** |
| — from PE exports + Ghidra RTTI | 513 |
| — from vtable-slot recovery (guess) | 2,850 |
| Unnamed (`FUN_`/`thunk_`) | **43,095 (92.8%)** |
| Functions with string references | **4,314** |
| Call edges recorded | **81,390** |
| Medium/high name suggestions | **4,026** |
| Steam `.bind` packer stubs excluded | 6 |

## Recovered structure

| RTTI / vtable scan | Count |
| --- | --- |
| Type descriptors with names | 706 |
| Complete object locators | 657 |
| Vtables | **608** |
| Distinct classes | **527** |
| Virtual slots | **7,715** |
| Distinct virtual function targets | 2,888 |
| Unnamed targets promoted by vtable | 2,850 |

Largest class families by virtual targets: `SteamSession`, the robot family
(`Robot`, `GroundRobot`, `StationaryRobot`, `AerialPatrolRobot`), `BrownTown`,
`Player`, `Character`, `HazardComponent`, `FxFactory`, `D3D9VertexFormat`,
`PCSession`, `SessionInterface`.

## Decompiler failures

These are real `.text` functions where Ghidra could not produce C. They are
kept in the tree with an explicit `decompile failed` comment rather than
silently dropped.

| Address | Size | Note |
| --- | --- | --- |
| `0x00530000` | 42 | overlapping/ambiguous instruction flow |
| `0x0059d145` | 109 | overlapping/ambiguous instruction flow |
| `0x008416a1` | 94 | overlapping/ambiguous instruction flow |
| `0x0096006b` | 412 | unreachable `XBEGIN` entry, also skipped by the recompiler |

## Named subsystems visible today

`Player`, `Character`, `Robot` behaviours (`Blimp`, `Gorilla`, `Charger`),
`BrownTown`, `Weapon`/`WorldWeaponComponent`, `HazardComponent`,
`SomervilleGameApp`, `SomervilleMatchmaker*`, `SteamSession`,
`SteamProfiles`, `SteamLeaderboard*`, `GUIScreen*`, `D3D9Device`,
`D3D9VertexFormat`, `FxFactory`, `GSys*`/`G*` Seoul engine classes, FMOD and
PhysX imports.

## What a reader can trust

- Addresses, sizes, callees, and string references are extracted from Ghidra.
- 513 names are sourced (PE exports, RTTI/vtables).
- 2,850 names are class/slot labels and are **guesses** (`name_source:
  vtable:RTTI` in `functions.jsonl`, `names_applied.csv`).
- Function bodies are Ghidra's reconstruction. They are readable, not the
  original source and not guaranteed to compile.
- `Class::vfunc_N` is a **locator**, not a source method name. Secondary base
  vtables and shared thunks mean 98 names repeat across 405 records (C++
  overloads account for some of that too).
- No function has been shown to rebuild to the original bytes.

## Immediate next work

1. Locate the RakNet RPC registration tables and turn the 142
   `Class::Method` strings into sourced names.
2. Use the 4,026 string suggestions to name the UI and gameplay functions,
   recording `GUESS` confidence.
3. Split the most coherent banks (engine exports, UI, gameplay) into real
   translation units.
4. Stand up MSVC 2008 + Wine and start the first matched bank
   ([MATCHING.md](MATCHING.md)).
