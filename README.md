# Shoot Too Many Robots

Apple Silicon compatibility research for the Windows release of *Shoot Many Robots*. Game files, upstream checkout, analysis output, and compiled probes live in the ignored `work/` directory.

## Current status

The original Windows executable reaches the first tutorial in a 1280 × 720 AppKit window on the Apple M4. Pressing Space advances past the title screen. Metal displays the chapter loading artwork and the tutorial prompt, while the scene area remains magenta. See the [title screen](work/boot/window-frames/title-window.png), [chapter loading screen](work/boot/window-frames/frame_2138.png), and [windowed log](work/boot/window-startup.log).

- **Resolved startup crash.** The old x86 fallback appeared to stop at `0x40000c`. An executable-range guard traced the failure to a null call after `SteamApps()` returned no object in offline mode. The guest requests `ISteamApps004`. Its offline proxy provides the startup language and reports the observed app query as unavailable. The [diagnostic trace](work/boot/steam-null-startup.log) records the original failure.
- **Resolved follow-up stop.** The game now runs past the missing dedicated-server callback pump. The offline host has no server callback queue, so the pump has no events to deliver. The [follow-up trace](work/boot/steam-callback-startup.log) records the earlier stop.
- **Input.** The window forwards keyboard input, mouse buttons, and relative mouse motion to the guest. A focused input test verified Space and left-click delivery, including button release after the window loses focus.
- **Next milestone.** Render the tutorial scene and verify gameplay and sound in the windowed run.

## Run the startup probe

Run these commands from the project directory with the local inputs listed below in place.

| Mode | Command | Output |
| --- | --- | --- |
| Windowed Metal | `SMR_WINDOW=1 ./scripts/startup-probe` | Opens the game window and runs until it exits or the window is closed. The [startup trace](work/boot/window-startup.log) and [frame captures](work/boot/window-frames/) stay under `work/boot/`. |
| Offscreen Metal | `SMR_METAL=1 ./scripts/startup-probe` | Stops after the first successful Direct3D `Present` and saves the [Demiurge splash](work/boot/frame_1.png). |
| Headless diagnostics | `./scripts/startup-probe` | Runs startup without a GPU renderer or window and writes [the startup trace](work/boot/native-startup.log). |

Set `SMR_TRACE=1` to log individual Windows API calls. For non-windowed runs, `SMR_CONTINUE=1` removes the first-frame stop and `SMR_PROBE_SECONDS` sets the timeout, which defaults to 60 seconds. For windowed runs, `FNV_DUMP_FRAMES` selects the frames to capture.

The default ARM64 host runs recompiled startup functions and uses Unicorn for remaining x86 code. To test the full translation, run `SMR_FULL=1 SMR_WINDOW=1 ./scripts/startup-probe`. This uses a separate build, log, frame directory, and save directory. Add `SMR_BUILD_ONLY=1` to build without launching. Network access is disabled and probe output and saves stay under `work/boot/`.

The full build runs one entry at `0x5c88f0` in Unicorn after its translated version failed during startup. Windows DLL code also still runs in Unicorn. A fallback root in the log identifies a distinct entry address and does not measure CPU time spent there.

The full build reaches the opening scene. Across the first ten two-second intervals with at least 500 draws per frame and no shader compilation, the median rose from 13.3 to 16.2 FPS while main-thread CPU time fell from 68 to 53 ms per frame. GPU time stayed near 1.5 ms. The scene still renders magenta. See the [focused run](work/tutorial-test/original-window.log), [full run](work/boot/window-full-startup.log), and [full-run CPU sample](work/perf/full-tutorial.sample.txt).

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
