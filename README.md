# Shoot Too Many Robots

Apple Silicon compatibility research for the Windows release of *Shoot Many Robots*. Game files, upstream checkout, analysis output, and compiled probes live in the ignored `work/` directory.

## Current status

The original Windows executable reaches the first tutorial in a 1280 × 720 AppKit window on the Apple M4. Pressing Space advances past the title screen and loading screen into the tutorial (`50,195` functions emitted; `~26–28 fps` in the 500+ draw/frame tutorial with `ff-skipped 0`). See the [title screen](work/boot/window-frames/title-window.png), [chapter loading screen](work/boot/window-frames/frame_2138.png), and [full-build log](work/boot/window-full-startup.log).

- **Resolved startup & tagged-pointer crashes.** Re-running Ghidra with `ResolveJumpTables`, `FixNoReturn`, and `FixEntries` resolved the `0x5c88f0` window-procedure switch table (`SMR_NATIVE_WNDPROC=1`). Added `SQRTPS`/`PSHUFW` support to fix the `0x83f6e0` trap. Moved the guest heap in `gheap.c` from `0x40000000` to `0x18000000–0x40000000` because the game's handle resolver (`0x764a80`) treats bit 30 (`0x40000000`) as a tagged-index flag, which caused the `0x5c9c86` null-call trap.
- **Scene rendering diagnosis.** Supporting depth-only (`ps=0`) draws eliminated all skipped fixed-function draws (`ff-skipped 0`), and adding a `texture3d` LUT fallback in `d3d9_metal.m` eliminated the solid magenta backbuffer. The G-buffer geometry and normals (`frame_9000.png` / `frame_9999.png`) render cleanly, and the albedo buffer (`frame_9010.png`) shows the scene geometry (tinted magenta), while the deferred directional-light HDR pass currently outputs black because its pixel shader constants (`cf0..cf2`) are all zero.
- **Input.** The window forwards keyboard input, mouse buttons, and relative mouse motion to the guest. A focused input test verified Space and left-click delivery, including button release after the window loses focus.
- **Next milestone.** Fix the zeroed pixel shader constants (`cf0..cf2`) in the deferred lighting pass and the magenta tint in the G-buffer albedo so the tutorial scene renders lit and textured; audio and DLL-fallback optimization (`~198` DLL roots) come later.

## Run the startup probe

Run these commands from the project directory with the local inputs listed below in place.

| Mode | Command | Output |
| --- | --- | --- |
| Windowed Metal | `SMR_WINDOW=1 ./scripts/startup-probe` | Opens the game window and runs until it exits or the window is closed. The [startup trace](work/boot/window-startup.log) and [frame captures](work/boot/window-frames/) stay under `work/boot/`. |
| Offscreen Metal | `SMR_METAL=1 ./scripts/startup-probe` | Stops after the first successful Direct3D `Present` and saves the [Demiurge splash](work/boot/frame_1.png). |
| Headless diagnostics | `./scripts/startup-probe` | Runs startup without a GPU renderer or window and writes [the startup trace](work/boot/native-startup.log). |

Set `SMR_TRACE=1` to log individual Windows API calls. For non-windowed runs, `SMR_CONTINUE=1` removes the first-frame stop and `SMR_PROBE_SECONDS` sets the timeout, which defaults to 60 seconds. For windowed runs, `FNV_DUMP_FRAMES` selects the frames to capture.

The default ARM64 host runs recompiled startup functions and uses Unicorn for remaining x86 code. To test the full translation, run `SMR_FULL=1 SMR_WINDOW=1 ./scripts/startup-probe`. This uses a separate build, log, frame directory, and save directory. Add `SMR_BUILD_ONLY=1` to build without launching. Network access is disabled and probe output and saves stay under `work/boot/`.

The full build with `SMR_NATIVE_WNDPROC=1` runs `0x5c88f0` natively; only 1 game-exe address (`0x626770`) and ~198 Windows DLL addresses still fall back to Unicorn.

Across the latest run (`run11`, 516 draws/frame, `ff-skipped 0`), the tutorial runs at **~26–28 fps** (`main_cpu_ms` ~34–35 ms, `gpu_ms` ~1.4 ms) and exits cleanly on scripted quit. See the [full run](work/boot/window-full-startup.log) and [full-run CPU sample](work/perf/full-tutorial.sample.txt).

## Fast iteration loop

`scripts/recomp` makes the inner loop measurable without booting the game each time. See [docs/RECOMP-WORKFLOW.md](docs/RECOMP-WORKFLOW.md) for the design and the limitations.

```sh
./scripts/recomp status                    # coverage, fallbacks, last run, next action
./scripts/recomp verify --changed          # native-vs-x86 check of what you just recompiled
./scripts/recomp verify --full --sample 100 # seeded sample of all 46k functions
./scripts/recomp promote                   # make hot game.exe fallbacks native, then re-run
./scripts/recomp run --to tutorial         # hands-free build + boot + summary + deltas
```

`verify` links the exact production translation units into a cached diagnostic dylib and compares each function against the original x86 bytes in Unicorn from identical randomized state (registers, flags, x87, XMM and touched memory). It runs in seconds, needs no window, and exits non-zero on a real mismatch. Results distinguish an actual translation bug from an isolated-harness limitation such as a call into a Windows import or a deliberate CPUID divergence. `run` drives a checked-in [tutorial input script](scripts/smr-tutorial.script), enforces a timeout, parses fps/draws/fallbacks/faults and prints deltas against the previous run.

The executable extracted from the installer is a 32-bit Windows PE whose entry point lands in `.bind` and whose `.text` section is packed. The diagnostic uses the loose executable from Downloads, which differs from the installer executable. The Microsoft Visual C++, PhysX, DirectX, and FMOD DLLs come from the installer and its bundled redistributables.

### Project inputs

- `work/recompiler` contains [the P-code exporter and emitter](https://github.com/thetheoryofR/Fallout-NV-MacOS) at `ff8e0d791e3e1f0148a2245c12c7706855e66926`.
- `work/macos-runtime` contains [the macOS host](https://github.com/pedroh77/Fallout-ElderScrolls-macOS-Port) at `9470dcf94dd69f37263a9f94db69957a76dbed7b`. The startup script applies `patches/macos-startup-host.patch` and adds the local guest-module loader and CRT shims.
- Ghidra analyzed 21,111 entries. The full emission report is `work/smr-generated/emit_report.json`. It emitted 21,108 functions and skipped three functions with unsupported P-code operations. The default build uses `work/smr-entry-generated/`. Full mode uses `work/smr-generated/`.
- `work/installed/` contains the unpacked game and redistributables. `work/vc90/dlls/` contains the two x86 CRT DLLs from the nested Visual C++ cabinet, and `work/d3dx/` contains the two x86 DirectX DLLs from the June 2010 cabinets. `work/boot/ShootManyRobots.exe` is the guest input. The project keeps these files and generated artifacts out of Git.

## Verified middleware probe

Ghidra 12.2 analyzed the packaged `PhysXLoader.dll` and exported 33 leaf functions. The Fallout recompiler translated all 33 and Clang linked an ARM64 Mach-O library. Isolated comparisons against the original x86 instructions reported 10 passes, 15 flags-only differences, and 8 untestable functions. This probe covered individual functions and did not initialize the PhysX SDK or boot the game.

The [Fallout recompiler](https://github.com/thetheoryofR/Fallout-NV-MacOS) checkout is pinned at `ff8e0d791e3e1f0148a2245c12c7706855e66926`. [The local patch](patches/pe-image-base.patch) makes its comparison harness read the PE image base instead of assuming the executable starts at `0x400000`. This DLL uses `0x10000000`.

## Reproduce the PhysX function probe

Run from the project directory. The steps assume `work/recompiler` contains the pinned checkout with the image-base patch applied, and `.venv` has the checkout's Python requirements installed.

```bash
set -e
work="$PWD/work"
repo="$work/recompiler"
installer="$HOME/Downloads/Shoot Many Robots.exe"
dll="$work/installed/app/ShootManyRobots/Binaries/PhysXLoader.dll"
python="$PWD/.venv/bin/python"

innoextract --extract --output-dir "$work/installed" "$installer"
export JAVA_HOME="$(brew --prefix openjdk@25)/libexec/openjdk.jdk/Contents/Home"
headless="$(brew --prefix ghidra)/libexec/support/analyzeHeadless"
mkdir -p "$work/ghidra"
"$headless" "$work/ghidra" middleware -import "$dll" -overwrite \
  -analysisTimeoutPerFile 120 -scriptPath "$repo/ghidra_scripts" \
  -postScript DumpPcode.java "$work/physx-leaf.jsonl" leaf

"$python" "$repo/recomp/emit.py" "$work/physx-leaf.jsonl" "$work/physx-generated"
JOBS=4 "$repo/recomp/build.sh" "$work/physx-generated" "$work/physx-build"
"$python" "$repo/recomp/difftest.py" "$dll" "$work/physx-build/librecomp.dylib" \
  "$work/physx-leaf.jsonl.regs.json" "$work/physx-difftest.json" --jobs 4
```
