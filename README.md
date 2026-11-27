# Shoot Too Many Robots

Apple Silicon compatibility research for the Windows release of *Shoot Many Robots*. Game files, upstream checkout, analysis output, and compiled probes live in the ignored `work/` directory.

## Current status

The original Windows executable reaches the first tutorial in a 1280 × 720 AppKit window on the Apple M4. Pressing Space advances past the title screen and loading screen into the tutorial (`50,203` functions emitted, including 3,739 secondary entries; `ff-skipped 0`). The full build now has **zero game.exe fallbacks**: the last acceptance run exited 0 with no faults or traps and dumped the expected frames. See the [title screen](work/boot/window-frames/title-window.png), [chapter loading screen](work/boot/window-frames/frame_2138.png), and [full-build log](work/boot/window-full-startup.log).

- **Resolved startup & tagged-pointer crashes.** Re-running Ghidra with `ResolveJumpTables`, `FixNoReturn`, and `FixEntries` resolved the `0x5c88f0` window-procedure switch table (`SMR_NATIVE_WNDPROC=1`). Added `SQRTPS`/`PSHUFW` support to fix the `0x83f6e0` trap. Moved the guest heap in `gheap.c` from `0x40000000` to `0x18000000–0x40000000` because the game's handle resolver (`0x764a80`) treats bit 30 (`0x40000000`) as a tagged-index flag, which caused the `0x5c9c86` null-call trap.
- **Scene rendering diagnosis.** Supporting depth-only (`ps=0`) draws eliminated all skipped fixed-function draws (`ff-skipped 0`), and adding a `texture3d` LUT fallback in `d3d9_metal.m` eliminated the solid magenta backbuffer. The G-buffer geometry and normals (`frame_9000.png` / `frame_9999.png`) render cleanly, and the albedo buffer (`frame_9010.png`) shows the scene geometry (tinted magenta), while the deferred directional-light HDR pass currently outputs black because its pixel shader constants (`cf0..cf2`) are all zero.
- **Input.** The window forwards keyboard input, mouse buttons, and relative mouse motion to the guest. A focused input test verified Space and left-click delivery, including button release after the window loses focus.
- **Next milestone.** Fix the zeroed pixel shader constants (`cf0..cf2`) in the deferred lighting pass and the magenta tint in the G-buffer albedo so the tutorial scene renders lit and textured; audio and DLL-fallback optimization (`~251` unique DLL roots in the latest run) come later.

## Run the startup probe

Run these commands from the project directory with the local inputs listed below in place.

| Mode | Command | Output |
| --- | --- | --- |
| Windowed Metal | `SMR_WINDOW=1 ./scripts/startup-probe` | Opens the game window and runs until it exits or the window is closed. The [startup trace](work/boot/window-startup.log) and [frame captures](work/boot/window-frames/) stay under `work/boot/`. |
| Offscreen Metal | `SMR_METAL=1 ./scripts/startup-probe` | Stops after the first successful Direct3D `Present` and saves the [Demiurge splash](work/boot/frame_1.png). |
| Headless diagnostics | `./scripts/startup-probe` | Runs startup without a GPU renderer or window and writes [the startup trace](work/boot/native-startup.log). |

Set `SMR_TRACE=1` to log individual Windows API calls. For non-windowed runs, `SMR_CONTINUE=1` removes the first-frame stop and `SMR_PROBE_SECONDS` sets the timeout, which defaults to 60 seconds. For windowed runs, `FNV_DUMP_FRAMES` selects the frames to capture.

The default ARM64 host runs recompiled startup functions and uses Unicorn for remaining x86 code. To test the full translation, run `SMR_FULL=1 SMR_WINDOW=1 ./scripts/startup-probe`. This uses a separate build, log, frame directory, and save directory. Add `SMR_BUILD_ONLY=1` to build without launching. Network access is disabled and probe output and saves stay under `work/boot/`.

The full build with `SMR_NATIVE_WNDPROC=1` runs `0x5c88f0` natively and has **0 game.exe fallbacks**; the only remaining fallbacks are 251 unique Windows DLL addresses. One packed-region function (`0x96006b`) is skipped for an unsupported `XBEGIN` and is not reached by the tutorial.

The latest acceptance run (`work/recomp-dev/runs/20261126-214349`, 575 draws last / 645 peak, `ff-skipped 0`) exited cleanly on scripted quit with 0 faults and 0 traps. Its last-window fps was 15.8 (`main_cpu_ms` 61.96, `gpu_ms` 1.52); single-run fps is noisy, so treat the earlier ~26–28 fps full runs as the performance reference, not this one. See the [full run](work/boot/window-full-startup.log) and [full-run CPU sample](work/perf/full-tutorial.sample.txt).

## Fast iteration loop

`scripts/recomp` makes the inner loop measurable without booting the game each time. See [docs/RECOMP-WORKFLOW.md](docs/RECOMP-WORKFLOW.md) for the design and the limitations.

```sh
./scripts/recomp status                    # coverage, fallbacks, last run, next action
./scripts/recomp verify --changed          # native-vs-x86 check of what you just recompiled
./scripts/recomp verify --full --sample 100 # seeded sample of all 46k functions
./scripts/recomp promote                   # make hot game.exe fallbacks native, then re-run
./scripts/recomp run --to tutorial         # hands-free build + boot + summary + deltas
```

`verify` links the exact production translation units into a cached diagnostic dylib and compares each function against the original x86 bytes in Unicorn from identical randomized state (registers, flags, x87, XMM and touched memory). It runs in seconds, needs no window, and exits non-zero on a real mismatch. Results distinguish an actual translation bug from an isolated-harness limitation such as a call into a Windows import or a deliberate CPUID divergence. Suspected mismatches are re-run alone in a fresh process, so only reproducible bugs count. `run` drives a checked-in [tutorial input script](scripts/smr-tutorial.script), enforces a timeout, parses fps/draws/fallbacks/faults and prints deltas against the previous run.

`promote` is a measured experiment, not automatic progress: it reverts itself if the tutorial gets slower by more than 1 fps or the game.exe fallback count does not drop. On this title the observed roots are thin wrappers around further Unicorn entries, so one-at-a-time promotion lost to the fallback boundary cost and was reverted. Use `run --to tutorial --full` when the frame rate matters; the full build is the performance path.

### Last two game.exe gaps (2026-11-26)

The full build no longer falls back for any game.exe address. The last two gaps were closed as follows:

- `0x626770` was a real entry that Ghidra had split two bytes late at `0x626772`. `tools/ghidra/scripts/FixSplitEntry.java` removes the bogus function, disassembles and creates `FUN_00626770`, and the P-code was re-exported. The new export differs from the old one only by adding `0x626770` and removing `0x626772`; every other function line is byte-identical.
- `0x7c727c` (`OUTSB`) and its secondary entry `0x7c7290` are emitted after teaching both emitters the `in`/`out` CALLOTHERs (the vendor emitters carry the local change directly). **Semantics:** Unicorn, the current fallback, executes `IN`/`INS` as a zero read and discards `OUT`/`OUTS` because no port device is attached. The native emitter preserves that (`in` writes 0, `out` is a no-op) instead of trapping. `swi` (`INT n`) is emitted as a non-returning trap because Unicorn raises `UC_ERR_EXCEPTION`; this lets the remaining packed/data I/O-port functions link. One function, `0x96006b`, is still skipped for `XBEGIN` and is unreachable in the tutorial.

Reproduce with the vendored emitters:

```sh
export JAVA_HOME="$(brew --prefix openjdk@25)/libexec/openjdk.jdk/Contents/Home"
headless="$(brew --prefix ghidra)/libexec/support/analyzeHeadless"
"$headless" "$PWD/work/ghidra" smr -process ShootManyRobots.exe -noanalysis \
  -scriptPath "$PWD/tools/ghidra/scripts" \
  -postScript FixSplitEntry.java 0x626770:0x626772
"$headless" "$PWD/work/ghidra" smr -process ShootManyRobots.exe -noanalysis -readOnly \
  -scriptPath "$PWD/tools/ghidra/scripts" \
  -postScript DumpPcode.java "$PWD/work/smr-fixed.jsonl" all
.venv/bin/python vendor/recompiler/recomp/emit.py work/smr-fixed.jsonl work/smr-generated \
  --extra config/smr-extra-entries.json
```

The `--extra` map is the 3,739 secondary entries recovered from the existing generated C; keep it with the P-code export so a re-emit does not drop them. Verification: `./scripts/recomp verify --full 0x626770,0x7c727c,0x7c7290` reported pass 1 / flags-only 2 with no real mismatches, and `./scripts/recomp verify --full --sample 100` also exited 0.

The executable extracted from the installer is a 32-bit Windows PE whose entry point lands in `.bind` and whose `.text` section is packed. The diagnostic uses the loose executable from Downloads, which differs from the installer executable. The Microsoft Visual C++, PhysX, DirectX, and FMOD DLLs come from the installer and its bundled redistributables.

### Project inputs

- `vendor/recompiler` contains [the P-code exporter and emitter](https://github.com/thetheoryofR/Fallout-NV-MacOS) at `ff8e0d791e3e1f0148a2245c12c7706855e66926`.
- `vendor/macos-runtime` contains [the macOS host](https://github.com/pedroh77/Fallout-ElderScrolls-macOS-Port) at `9470dcf94dd69f37263a9f94db69957a76dbed7b`, pinned with the local changes applied. Local host sources (guest-module loader, CRT shims, Metal surfaces) live in `src/host/` and are compiled alongside the vendored host; nothing is copied into `vendor/` at build time.
- Ghidra exported 46,464 primary function entries. The full emission report is `work/smr-generated/emit_report.json`; it emitted 50,203 functions (46,464 primary plus 3,739 secondary entries) and skipped one packed-region function (`0x96006b`, unsupported `XBEGIN`). The default build uses `work/smr-entry-generated/` (189 curated entries). Full mode uses `work/smr-generated/`.
- `work/installed/` contains the unpacked game and redistributables. `work/vc90/dlls/` contains the two x86 CRT DLLs from the nested Visual C++ cabinet, and `work/d3dx/` contains the two x86 DirectX DLLs from the June 2010 cabinets. `work/boot/ShootManyRobots.exe` is the guest input. The project keeps these files and generated artifacts out of Git.

### Repository layout and worktrees

Tracked source lives in `vendor/` (pinned upstream), `src/host/` (local host code), `tools/` (dev loop and Ghidra scripts), `scripts/`, `config/` (small curated inputs), `docs/`, and `patches/` (reusable upstream deltas). Everything large or generated lives under ignored `work/`.

`SMR_DATA_ROOT` points at the shared read-only guest inputs and P-code exports. It defaults to this checkout's `work/`. A fresh worktree can prepare its own scratch space with:

```sh
git worktree add ../smr-task -b task/name
cd ../smr-task
SMR_DATA_ROOT="/path/to/main/checkout/work" ./scripts/dev-setup
./scripts/recomp doctor
```

`dev-setup` links the read-only guest data, copies the generated C baselines, and creates `work/recomp-dev` without modifying the main checkout.

## Verified middleware probe

Ghidra 12.2 analyzed the packaged `PhysXLoader.dll` and exported 33 leaf functions. The Fallout recompiler translated all 33 and Clang linked an ARM64 Mach-O library. Isolated comparisons against the original x86 instructions reported 10 passes, 15 flags-only differences, and 8 untestable functions. This probe covered individual functions and did not initialize the PhysX SDK or boot the game.

The [Fallout recompiler](https://github.com/thetheoryofR/Fallout-NV-MacOS) checkout is pinned at `ff8e0d791e3e1f0148a2245c12c7706855e66926`. [The local patch](patches/pe-image-base.patch) makes its comparison harness read the PE image base instead of assuming the executable starts at `0x400000`. This DLL uses `0x10000000`.

## Reproduce the PhysX function probe

Run from the project directory. The steps assume `vendor/recompiler` contains the pinned checkout with the image-base patch applied, and `.venv` has the checkout's Python requirements installed.

```bash
set -e
work="$PWD/work"
repo="$PWD/vendor/recompiler"
installer="$HOME/Downloads/Shoot Many Robots.exe"
dll="$work/installed/app/ShootManyRobots/Binaries/PhysXLoader.dll"
python="$PWD/.venv/bin/python"

innoextract --extract --output-dir "$work/installed" "$installer"
export JAVA_HOME="$(brew --prefix openjdk@25)/libexec/openjdk.jdk/Contents/Home"
headless="$(brew --prefix ghidra)/libexec/support/analyzeHeadless"
mkdir -p "$work/ghidra"
"$headless" "$work/ghidra" middleware -import "$dll" -overwrite \
  -analysisTimeoutPerFile 120 -scriptPath "$PWD/tools/ghidra/scripts" \
  -postScript DumpPcode.java "$work/physx-leaf.jsonl" leaf

"$python" "$repo/recomp/emit.py" "$work/physx-leaf.jsonl" "$work/physx-generated"
JOBS=4 "$repo/recomp/build.sh" "$work/physx-generated" "$work/physx-build"
"$python" "$repo/recomp/difftest.py" "$dll" "$work/physx-build/librecomp.dylib" \
  "$work/physx-leaf.jsonl.regs.json" "$work/physx-difftest.json" --jobs 4
```
