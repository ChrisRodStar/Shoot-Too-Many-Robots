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

Current contents: 149 tail-call thunks (`engine/tail_thunks.c`), 19 field
accessors (`engine/field_getters.c`), `bank_0088` C++ methods
(`engine/bank_0088_methods.cpp`), misc C (`engine/bank_0088_misc.c`), one real
relocation-heavy function (`engine/rand_scale.c`), and four leaf sanity checks
(`engine/simple.c`). Do not add a function until
`verify.py` reports `MATCH` for it.
