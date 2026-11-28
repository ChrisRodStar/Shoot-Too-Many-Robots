# Matching

A Fallout-style decompilation has two products: readable source, and source
that compiles back to the original bytes. This project has the first; this
document defines the second and the distance to it.

## What counts as a match

For every function in `build/game/units.json`:

1. the function's machine code is compiled by the **original toolchain**
   (Microsoft Visual C++ 2008, `cl 15.00.xxxxx`) with the unit's flags;
2. its bytes are identical to the bytes at the original virtual address,
   same length, same instructions and immediates;
3. every relocation resolves to the same original address: relative `call` /
   `jmp` displacements and absolute data references are compared through the
   symbol map, not just as four bytes;
4. exception-handling data (x86 SEH) and `fold_aliases` (identical code folded
   by the linker) are accounted for.

A function that differs only in a relocation currently reports as a mismatch
with `--strict-relocs`; without it, relocation spans are ignored and counted,
so the report never silently calls unchecked bytes a match.

## Why the compiler is not optional

The image was built with Visual C++ 2008 (VC9): it imports `MSVCR90.dll` /
`MSVCP90.dll`, and its code shape (prologue patterns, `ret n` stdcall cleanup,
x87 usage) matches VC9. Compiler identity is not cosmetic. A concrete example
already in the harness:

| Function | Original (MSVC 2008) | clang 21 `--target=i686-pc-windows-msvc` |
| --- | --- | --- |
| `FUN_00401050` | `33 c0 c2 10 00` | `31 c0 c2 10 00` |

Both are `xor eax,eax; ret 16`, but the encoding differs in the first byte, so
only MSVC can be the oracle. This is also why "it compiles and looks right" is
not progress.

## Toolchain

Needed to move from reference to matched:

- **Visual C++ 2008 SP1** (`cl 15.00.30729.01`) for most units.
- Optionally the **original 2008 release** (`cl 15.00.21022.08`): different
  optimisation results in some units, and FNV needed both.
- A 32-bit Windows environment, or Wine with a 32-bit prefix. On Apple silicon
  this generally means an x86_64 Linux VM/container with Wine, not native
  macOS Wine.
- The headers/libraries the translation unit needs. The image links the CRT
  dynamically, so most CRT prototypes can come from the VC9 headers; engine
  and game types must be rebuilt from the decompilation.

The harness takes any `cl.exe` path:

```sh
export SMR_MSVC9_ROOT=/path/to/vc9      # contains VC/bin/cl.exe and SDK/
# SMR_CL=/path/to/cl.exe wine ...       # explicit override
```

## Units

`build/game/units.json` is generated from the bank index. Each unit is a
250-function address range with a stable source path:

```json
{
 "name": "bank_0000",
 "source": "src/game/bank_0000.c",
 "functions": [
   {"address": "0x00401000", "size": 27, "name": "FUN_00401000"}
 ]
}
```

Banks are the *starting* recipe, not a claim about the original translation
units. As functions are named and typed, split them into real units and keep
the per-function address list; the comparator uses addresses, not file order.

## Loop

```sh
# 1. pick a bank and find its boundaries
python3 Decompile/tools/decompile.py unit 0

# 2. rewrite one function in src/matched/bank_0000.c (new file; generated
#    banks are never edited in place)

# 3. compile the unit with the original compiler, then compare
python3 Decompile/tools/match/compare.py \
    --object build/obj/bank_0000.obj --bank bank_0000 --verbose
```

Until `compare.py` reports `MATCH`, the function is still reference-only, no
matter how convincing the C looks.

## What the harness does today

- `--selftest` verifies the PE fingerprint, the 200 exports, a known 5-byte
  function, and parses a clang-built COFF object.
- `compare.py` parses PE32 sections and i386 COFF symbols/relocations, matches
  object functions by name (with C decoration removal), compares bytes, reports
  the first difference, and masks/report relocation spans.
- No compiler driver yet: compiling remains an explicit step, so a wrong
  `cl.exe` can never be mistaken for a match.

## Next steps

1. **Compiler driver.** `tools/match/build.py`: resolve `cl.exe` (native or
   under Wine), verify its version, compile a unit with per-unit flags, and
   refuse on mismatch.
2. **Relocation comparison.** Resolve `REL32`/`DIR32` targets through
   `units.json` and compare target addresses, not zeroed bytes.
3. **First matched bank.** Pick a bank dominated by small, self-contained
   functions (the Seoul Engine exports are ideal) and get it to 100% match.
4. **Type promotion.** Move inferred structs into `include/game/` as call sites
   agree; each promotion must keep the bank matching.
5. **Naming.** `// src: GUESS 0x... (confidence: ...)` markers, as FNV does,
   so guessed names can be audited and replaced.
