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

## Toolchain (working)

Two VC9 compilers run under Wine 8 in a 32-bit Debian container:

| Flavor | Version | Path |
| --- | --- | --- |
| SP1 (default) | `15.00.30729.01` | `work/toolchains/msvc9/sp1/VC/bin/cl.exe` |
| Original release | `15.00.21022.08` | `work/toolchains/msvc9/rtm/VC/bin/cl.exe` |

The container is `smr-msvc9` (Debian bookworm i386 + Wine + Windows SDK
v6.0A), running through OrbStack's `linux/386` support. Setup is one command:

```sh
./Decompile/tools/msvc/setup.sh
```

It downloads Microsoft's official VS2008 Express SP1 and original ISOs,
builds the image, extracts `VC/` and `SDK/`, and leaves the compilers under
`work/toolchains/msvc9/`. Nothing is redistributed.

```sh
# compiler version
Decompile/tools/msvc/cl.sh

# original release instead of SP1
SMR_MSVC_FLAVOR=rtm Decompile/tools/msvc/cl.sh
```

`cl.exe` is console-only and runs headless. Do **not** wrap it in `xvfb-run`:
in this environment that wrapper hangs while starting Xvfb. See
[MSVC2008.md](MSVC2008.md) for the full setup and troubleshooting notes.

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

# 2. rewrite one function in src/matched/... (the generated banks are never
#    edited in place), then register it in config/matched.json

# 3. compile every registered function and compare it byte for byte
python3 Decompile/tools/match/verify.py

# or compare a single already-built object
python3 Decompile/tools/match/compare.py \
    --object work/match/obj/simple.obj --addr 0x401050:5 \
    --symbol-map my-symbols.json --verbose
```

Until `compare.py` reports `MATCH`, the function is still reference-only, no
matter how convincing the C looks.

## What the harness does today

- `--selftest` verifies the PE fingerprint, the 200 exports, a known 5-byte
  function, and parses a clang-built COFF object.
- `compare.py` parses PE32 sections and i386 COFF symbols/relocations, matches
  object functions by name (with C decoration removal), compares bytes, reports
  the first difference, and masks/report relocation spans.
- `tools/msvc/cl.sh`: runs the selected `cl.exe` under Wine with the SDK
  `INCLUDE`/`LIB` paths.
- `tools/match/verify.py`: compiles every entry in `config/matched.json`,
  compares it at its original address, and reports functions and bytes.
- The current registry has **4/4 functions matched (19 bytes)** — deliberately
  trivial leaf functions that prove the compiler and comparator first.

## Next steps

1. **Relocation comparison.** Resolve `REL32`/`DIR32` targets through
   `units.json` and compare target addresses, not zeroed bytes.
2. **First matched bank.** Pick a bank dominated by small, self-contained
   functions (the Seoul Engine exports are ideal) and get it to 100% match.
3. **Per-unit flags.** Determine the optimisation/SEH flags from function
   prologues and the linker map, not by guessing.
4. **Type promotion.** Move inferred structs into `include/game/` as call sites
   agree; each promotion must keep the bank matching.
5. **Naming.** `// src: GUESS 0x... (confidence: ...)` markers, as FNV does,
   so guessed names can be audited and replaced.
