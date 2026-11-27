# The recomp dev loop

This document explains the fast iteration loop added in `scripts/recomp` and
why it is shaped the way it is. The short version:

```sh
./scripts/recomp status                    # where are we?
./scripts/recomp verify --changed          # did my translation change break anything?
./scripts/recomp run --to tutorial         # does it still boot and draw?
```

No manual clicking, no full rebuild for a one-function translation change, and
no guessing whether a run was better or worse than the last one.

## The problem with "run the game every time"

Booting the tutorial costs a build, a launch, a scripted or manual trip through
the title screen, and a visual judgement at the end. It is the *integration*
test, and it has to exist. It is also a terrible inner loop:

- a wrong translation and a wrong renderer change look identical from outside;
- a run produces a log and some PNGs, not a pass/fail for one function;
- most edits only touch a handful of translated functions, but every edit pays
  for the whole pipeline;
- without a baseline, "26 fps and 516 draws" is an anecdote, not a measurement.

## What other static recompilation projects do

The pattern across mature projects is the same: verify translations against the
original binary *offline*, and keep the run-the-game loop for integration.

- **[3dsrecomp](https://github.com/fearkov/3dsrecomp)** has a `verify` command
  that "check[s] every recompiled function against Zakuro's interpreter, running
  both from the same state and comparing registers, flags and memory", and writes
  down where it still had to interpret so the next build takes it in. Its
  runtime loads the recompiled library on its own and records interpreter
  fallbacks for the next build.
- **[RecompCore](https://github.com/aharonahdoot/RecompCore)** (Dolphin + a
  static-recompiled GameCube core) reports a *lockstep* mode that reruns every
  dispatch on the interpreter and compares full CPU state; it is how their FPU
  was brought to bit-exactness, and they report 0 divergences over 37.7B
  dispatches. Unknown code transparently falls back to the interpreter.
- **[N64Recomp](https://github.com/N64Recomp/N64Recomp)** / **Zelda64Recomp**
  emphasise single-file output and a patch ELF for fast iteration, and their
  development guide calls out validating each function against a reference
  emulator from the same ROM revision before moving to the next subsystem.
- The general static-recompilation literature calls this **trace comparison**:
  there is no source-level ground truth, so the original binary is the oracle,
  and the first state divergence is the bug.

`work/macos-runtime/tools/differential/difftest.py` is already an excellent
oracle harness: it runs the recompiled C and the original x86 bytes in Unicorn
from identical randomized state and compares registers, flags, x87, XMM and
touched memory. `scripts/recomp verify` turns it into a usable inner loop.

## Commands

| Command | What it does | Typical time |
| --- | --- | --- |
| `./scripts/recomp status` | Coverage, fallbacks, last run, last verify, next action. | < 1 s |
| `./scripts/recomp verify` | Native-vs-x86 check of the default startup subset. | 5–8 s |
| `./scripts/recomp verify --changed` | Only translation units whose C changed since the last verify. | 1–6 s |
| `./scripts/recomp verify --full --sample 100` | Seeded random sample of the 46k-function build. | ~10 s after the first full testlib build |
| `./scripts/recomp verify --failures --all` | Re-run the last mismatches with full detail. | seconds |
| `./scripts/recomp explain 0x83ed3e` | Instructions, call targets, generated C, last verdict. | < 1 s |
| `./scripts/recomp promote --dry-run` | Show which fallbacks would become native. | ~15 s first time, then fast |
| `./scripts/recomp promote` | Promote, verify, rebuild, and re-run the tutorial. | ~4 min |
| `./scripts/recomp clean` | Drop rebuildable caches (testlib, indexes, reports). | < 1 s |
| `./scripts/recomp run --to tutorial` | Incremental build + boot to the tutorial + summary + deltas. | 2–3 min (entry), ~1.5 min (full) |
| `./scripts/recomp build --full` | Rebuild only, report cache hits. | varies |
| `./scripts/recomp doctor` | Check inputs, tools, SDK, caches. | < 1 s |

Addresses are accepted directly:

```sh
./scripts/recomp verify 0x83ed3e --all
./scripts/recomp verify --full --sample 100 --seed 7
```

`verify` exits non-zero on a real mismatch, so it can gate a commit or a CI job.
`verify --strict` also rejects flags-only and blocked results; `--strict-harness`
also rejects the known harness divergences described below.

## How `verify` works

1. **Build a test dylib from the exact production translation units.** It does
   not re-emit C. The same `tu_*.c`, `table.c` and `stubs.c` that the host links
   are compiled into `work/recomp-dev/testlib/<variant>/libtest.dylib`. If those
   files are the ones you ship, you are verifying what you ship.
2. **Cache objects by content.** Each translation unit gets an object keyed by a
   SHA-256 of the compiler flags, toolchain and source bytes. A rebuild after a
   one-function change compiles one object, not 190. The dispatch link is cached
   by the set of object keys.
3. **Run the upstream differential harness.** Every function gets several
   randomized machine states (GPRs, flags, x87, XMM, a pointer-rich scratch
   heap, stack, TEB, the PE image). Native C and original x86 start from the
   same state; the harness compares final state.
4. **Classify and report.** Raw difftest verdicts are mapped to categories that
   distinguish a real bug from a limitation of isolated testing.

### The whole 4 GB is mapped

The pinned harness maps only the image, a scratch heap, a stack and the TEB. The
real host maps all 4 GB (`MEM` in `rt.h`). With the partial map, any randomized
pointer outside those regions makes the original x86 fault, so a function is
reported "untestable" for a reason that cannot happen in production.

`tools/recomp/difftest_full.py` wraps the pinned harness and adds the missing
regions as lazily-zeroed anonymous mappings, leaving the import-thunk window
(`0xFEE00000..0xFEE10000`) unmapped on purpose. Windows API calls still fail
cleanly on both sides. The instruction budget is lowered from 2M to 250k
(`SMR_DIFF_BUDGET`) because a wild jump into zeroed memory would otherwise burn
the full budget before being reported invalid.

Every trial resets those gap pages on both engines (`MADV_DONTNEED`, ~2 ms for
the whole map). Without that, a function that writes into guest heap space
leaves state behind for the next function, and results depend on test order.
That bug existed briefly in this harness and produced four phantom mismatches;
fixing it turned them into passes.

## Reading the result

| Category | Meaning | Action |
| --- | --- | --- |
| `pass` | Every valid trial matched exactly. | None. |
| `flags-only` | State matched; only CF/ZF/SF/OF differed. | Usually none. The Win32 ABI does not carry flags across calls. |
| `blocked:import` | The function calls a Windows API. | Expected in isolation. Cover it with a run, or a captured-state replay (below). |
| `blocked:callee` | An indirect call reached an address that is not a native entry. | If the address is real game code, export/emit it; if it is random data, ignore. |
| `blocked:fault` / `blocked:exception` / `blocked:budget` | The original x86 faults, traps or loops on randomized inputs. | Not a translation verdict. Prefer captured real inputs. |
| `harness:cpuid` | `rt_cpuid()` deliberately reports a 2010-era SSE2 CPU; Unicorn answers the host CPU. | Known harness divergence, excluded by default. |
| `harness:order` | The mismatch disappeared when the same entry was re-run alone in a fresh process. | Harness state leaked between functions, not a translation bug. |
| `fail` | A real state mismatch or native trap that reproduces in isolation. | Investigate. `--all` shows the values. |

Before a `fail` counts, `verify` re-runs that entry alone in a fresh process with
the same seed. Real translation bugs reproduce; order-dependent harness leaks do
not. `--no-confirm` skips this step, and `--strict-harness` counts both
`harness:*` categories as failures.

`harness:cpuid` currently catches the two `__get_sse2_info`-style helpers in the
startup subset, which compare CPUID feature bits. They are not translation bugs:
the native runtime intentionally lies to the guest about the CPU.

## Deterministic runs

`./scripts/recomp run --to tutorial` uses a checked-in input script,
`scripts/smr-tutorial.script`. The host applies script events when the presented
frame counter reaches the first column; `waitsteady` pauses the script until the
draw count has been stable for N frames and re-bases later frame numbers to that
sync point. That makes the script independent of startup timing and shader
compilation hitches.

> The default `entry` build interprets the tutorial's hot path in Unicorn, so its
> fps is not the port's performance. Use `run --to tutorial --full` when the
> number matters; use the default build for fast rendering checks.

The tutorial script:

```text
0 waitsteady 20 100      # title screen (~150 draws)
60 tap 57                # Space
120 waitsteady 30 400    # tutorial scene (~500 draws)
300 dump                 # three checkpoint frames
420 dump
600 dump
720 quit
```

`run` also:

- kills the whole process tree if the script never quits (`--timeout`, default
  360 s), instead of leaving a window behind;
- parses the log into fps (min/max/last), main CPU, GPU, draws, shader compile,
  fallbacks by module, faults and captures;
- compares against `work/recomp-dev/last-run.json` and prints deltas;
- writes `work/recomp-dev/runs/<timestamp>/` with the log and a JSON summary;
- `--verify` runs `verify --changed` first and refuses to launch on a mismatch.

Input-script commands (from the host's `input.c`) are one event per line:

```text
<frame> key <dik> down|up
<frame> tap <dik>
<frame> hold <dik> <frames>
<frame> mouse <dx> <dy>
<frame> button <n> down|up
<frame> click <n>
<frame> dump
<frame> quit
<frame> waitdraws <n> [<stable>]
<frame> waitsteady <frames> [<min_draws>]
```

Frame numbers after a `waitsteady`/`waitdraws` sync are *relative* to the sync
point, which is what makes the tutorial script timing-independent. Keep the
post-sync window short: the default build interprets the tutorial's hot path, so
a long linger is wall-clock time spent in Unicorn.

The integration loop is therefore:

```sh
# edit translation or host code
./scripts/recomp verify --changed
./scripts/recomp run --to tutorial
./scripts/recomp status
```

If you change a translation, `verify` tells you whether the new C still matches
the original instructions before you ever boot the game. The run then tells you
whether the integrated result still draws the scene.

## Artifacts and caches

Everything added by this tool lives under `work/recomp-dev/` (ignored by Git):

| Path | Contents |
| --- | --- |
| `testlib/<variant>/libtest.dylib` | cached diagnostic library |
| `testlib/<variant>/obj/*.o` | content-addressed objects |
| `verify-<variant>.json` | raw difftest report from the last run |
| `verify-<variant>-last.json` | classified summary used by `--failures` and `status` |
| `tu-<variant>.json` | per-translation-unit hashes for `--changed` |
| `pcode-index.json` | cached guest-address index over `smr-fixed.jsonl` |
| `last-run.json`, `runs.jsonl`, `runs/` | run summaries and logs |

The executable, DLLs, P-code, generated C and save data stay where they were.

## Promoting hot fallbacks

`./scripts/recomp promote` closes the loop the other way: it takes the
`game.exe` addresses that fell back to Unicorn in the last run, adds them to the
default native entry set, re-emits, verifies, rebuilds and re-runs the tutorial.

```sh
./scripts/recomp promote --dry-run      # preview
./scripts/recomp promote                # do it
./scripts/recomp promote 0x5c88f0 --no-closure
```

What it changes:

- `work/smr-entrypoints.jsonl` — the P-code subset for the default build;
- `work/smr-entry-generated/` — re-emitted C (previous copy kept under
  `work/recomp-dev/backups/entry-*`);
- `work/recomp-dev/entry-set.json` — the authoritative entry-address list.

Safety gates:

1. It only promotes addresses that exist as function entries in the P-code
   export. Addresses missing from the export are reported and skipped.
2. Direct callees are added unless `--no-closure` is given, so a promoted
   function does not immediately fall back again. (For the current tutorial
   roots this adds nothing: they are leaves.)
3. `verify --changed` must pass before the host is rebuilt. On a real mismatch
   the generated C is left in place but the host is not, and the backup path is
   printed.
4. The final re-run reports `game.exe fallbacks N -> M` and the fps delta.

Promotion only affects game-exe code. Fallbacks inside `msvcr90`, `msvcp90`,
PhysX, FMOD and friends remain; those need separate analysis and emission.

## What this does not solve (yet)

- **Import-heavy functions.** About 147 of the startup functions call a
  Windows API early, so isolated randomized testing cannot judge them. The next
  step is a captured-state replay: record the real guest registers, x87/XMM and
  stack/frame/TEB pages at a function entry during a scripted run, then replay
  that exact state through native and Unicorn. The host already has
  `rt_diag_entry` (`--trace-entries`) and fallback snapshots to build on.
- **Renderer correctness.** `verify` says nothing about Metal, shaders or
  pixels. The scripted run + frame dumps are the tool for that.
- **Whole-program equivalence.** A sample of passing functions is evidence, not
  proof. `verify --full` on every function is the stronger check; use
  `--require-tested` in CI if you want to fail on untested functions.

## References

- 3dsrecomp `verify`: <https://github.com/fearkov/3dsrecomp>
- RecompCore lockstep differential mode: <https://github.com/aharonahdoot/RecompCore>
- N64Recomp (single-file output, overlays, patches): <https://github.com/N64Recomp/N64Recomp>
- Zelda64Recomp development/testing guide: <https://deepwiki.com/Zelda64Recomp/Zelda64Recomp/10.3-building-and-testing>
- Static recompilation testing and trace comparison: <https://github.com/sp00nznet/recompclass/blob/master/papers/challenges-in-static-recompilation.md>
