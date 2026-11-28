# Matched source

Only functions that have been rebuilt and **verified byte-identical** against
the original image live here. The generated reference tree in `src/game/` is
never edited.

Every function in this tree must have an entry in
[`config/matched.json`](../../config/matched.json) with:

- its original address and size,
- the COFF symbol it compiles to,
- the source file and compiler flags,
- the compiler version used for verification.

Run the check:

```sh
python3 Decompile/tools/match/verify.py
```

The current first entries are deliberately trivial (`return 0`, `return 1`,
identity) — they prove the toolchain and comparator before the real work
starts. Do not add a function until `verify.py` reports `MATCH` for it.
