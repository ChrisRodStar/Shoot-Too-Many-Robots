# Shoot Too Many Robots

**Apple Silicon (ARM64) static-recompilation port and compatibility runtime for the Windows release of *Shoot Many Robots* (Demiurge Studios / Seoul Engine).**

This project lifts the 32-bit x86 Windows executable through Ghidra P-code into native ARM64 C, links it against a custom macOS Win32 + Direct3D 9 → Metal host runtime, and runs remaining third-party x86 middleware DLLs (`PhysXCore`, `d3dx9_43`, `fmodex`, `msvcr90`) under a transparent Unicorn fallback until shimmed or recompiled natively.

---

## Status at a Glance

| Area | Status | Notes |
| --- | --- | --- |
| **Executable Translation** | **50,203 / 50,204** functions | `46,464` primary + `3,739` secondary entries (`0x96006b` skipped for unreachable `XBEGIN`) |
| **Game Code Fallbacks** | **0 `game.exe` fallbacks** | 100% native `game.exe` execution in `--full` mode (`SMR_NATIVE_WNDPROC=1` by default) |
| **3D Rendering (D3D9 → Metal)** | **Lit, textured, color-graded** | Deferred lighting, 343 2D textures, 32×32×32 3D LUT, hardware `_sRGB`, `ff-skipped 0` |
| **Input & Windowing** | **Working** | 1280 × 720 AppKit window, keyboard/mouse forwarding, prefers secondary Dell display |
| **Audio (FMOD)** | **Not yet wired** | `fmodex.dll` queries unshimmed `DirectSoundEnumerateW` in `dsound.c` |
| **Latest Acceptance Run** | **Exit 0 · 28.9 fps** | `552` draws (`640` peak) · `34.5 ms` CPU · `3.6 ms` GPU · `217` DLL fallback roots · `0` faults/traps |

### Milestones

- [x] Boot Windows PE cleanly to title screen and advance through loading into the tutorial
- [x] Eliminate all `game.exe` Unicorn fallbacks (`0` remaining in full build)
- [x] Full deferred HDR lighting, 2D/3D texture loading, and sRGB color grading in Metal
- [x] Fast native shims for hot `msvcr90.dll` memory/string routines
- [x] Offline differential verifier (`./scripts/recomp verify`) and automated tutorial acceptance runner
- [ ] Interactive tutorial-to-combat playtesting (controls, combat physics, menus, saves)
- [ ] Audio playback via FMOD → DirectSound / CoreAudio (`DirectSoundEnumerateW` & `dsound.c`)
- [ ] Reduce remaining `217` DLL fallback roots (`PhysXCore`, `msvcr90`, `fmod_event`, `d3dx9_43`, `fmodex`) for 60 fps and faster loading

---

## Architecture

```text
ShootManyRobots.exe (x86 PE)
   └─► Ghidra headless P-code export (work/smr-fixed.jsonl)
         └─► P-code → C emitter (vendor/recompiler)
               └─► ARM64 Mach-O host (Clang + vendor/macos-runtime + src/host)
                     ├── D3D9 → Metal renderer (shaders via sm2msl, sRGB views, 3D LUT)
                     ├── Win32 / CRT / Input shims (AppKit window, src/host/msvcr90.c)
                     └── Unicorn x86 bridge for unshimmed third-party DLLs
```

### Repository Layout

Tracked source, config, and tools are strictly separated from large/generated local artifacts (`work/` and `logs/`, both git-ignored).

| Path | Role |
| --- | --- |
| [`src/host/`](src/host/) | Project-specific macOS host code (`surface.m`, `offscreen.m`, `msvcr90.c`, `pe_modules.c`, `startup.sb`) compiled alongside the vendored runtime |
| [`vendor/macos-runtime/`](vendor/macos-runtime/) | Pinned macOS Win32 + D3D9 → Metal host runtime with local fixes applied directly |
| [`vendor/recompiler/`](vendor/recompiler/) | Pinned x86 P-code exporter and C emitter (`emit.py`) |
| [`tools/recomp/`](tools/recomp/) | Python CLI backing `./scripts/recomp` (build, run, differential verify, explain, promote, doctor) |
| [`tools/ghidra/scripts/`](tools/ghidra/scripts/) | Ghidra headless analysis and P-code export scripts (`DumpPcode.java`, `FixSplitEntry.java`, etc.) |
| [`scripts/`](scripts/) | Entry points (`recomp`, `startup-probe`, `dev-setup`) and deterministic input scripts (`smr-title.script`, `smr-tutorial.script`) |
| [`config/`](config/) | Curated small inputs (`guest-manifest.json`, `entry-set.json`, `smr-extra-entries.json`, `learned-entries.txt`) |
| [`patches/`](patches/) | Reusable upstream reference deltas (`pe-image-base.patch`, `recompiler-mmx-sse.patch`) |
| [`docs/`](docs/) | Detailed engineering docs — see [`docs/RECOMP-WORKFLOW.md`](docs/RECOMP-WORKFLOW.md) for the dev loop design |
| `work/` *(ignored)* | Game binaries, DLLs, Ghidra project, generated C (`smr-generated/`, `smr-entry-generated/`), frame dumps, and run history |
| `logs/` *(ignored)* | Build and runtime logs (`window-full-startup.log`, `window-startup.log`, `native-startup.log`) |

---

## Quick Start & Dev Loop

First verify your local toolchain and game data under `work/`:

```sh
./scripts/recomp doctor
./scripts/recomp status
```

### Common Commands

| Command | Purpose |
| --- | --- |
| `./scripts/recomp run --to tutorial --full` | Incremental build + hands-free boot to tutorial + FPS/draw/fallback deltas |
| `./scripts/recomp build --full` | Rebuild the full native host only, reporting object cache hits |
| `./scripts/recomp verify --changed` | Offline native-vs-x86 differential test (Unicorn oracle) on changed TUs |
| `./scripts/recomp verify --full --sample 100` | Seeded random verification sample across all 50k functions |
| `./scripts/recomp explain <addr>` | Inspect original x86 instructions, call targets, generated C, and last verdict |
| `./scripts/recomp promote --dry-run` | Preview hot fallback promotion candidates (use `--full` for production speed) |
| `./scripts/recomp clean` | Clear rebuildable testlib/index caches without touching game data or generated C |

### Direct Launch Modes (`scripts/startup-probe`)

| Mode | Command | Notes |
| --- | --- | --- |
| Full windowed Metal | `SMR_FULL=1 SMR_WINDOW=1 ./scripts/startup-probe` | Runs all 50,203 native functions in a live window; logs to `logs/window-full-startup.log` |
| Entry-subset windowed | `SMR_WINDOW=1 ./scripts/startup-probe` | Fast-build 189-entry startup subset with Unicorn fallback |
| Offscreen first-frame | `SMR_METAL=1 ./scripts/startup-probe` | Stops after first D3D9 `Present` and saves `work/boot/frame_1.png` |
| Headless diagnostics | `./scripts/startup-probe` | No GPU/window; logs to `logs/native-startup.log` |

Useful environment flags: `SMR_BUILD_ONLY=1` (compile without launching), `SMR_TRACE=1` (Win32 API trace), `FNV_DUMP_FRAMES=1,60,300` (dump specific frame numbers), `SMR_CONTINUE=1` / `SMR_PROBE_SECONDS=60` (headless runs).

### Working with Git Worktrees

`SMR_DATA_ROOT` points to a shared read-only copy of `work/` (game files + P-code exports), so parallel worktrees don't duplicate gigabytes of assets:

```sh
git worktree add ../smr-task -b task/name
cd ../smr-task
SMR_DATA_ROOT="/path/to/main/checkout/work" ./scripts/dev-setup
./scripts/recomp doctor
```

---

## Technical Reference

<details>
<summary><strong>Key Runtime &amp; Rendering Fixes</strong></summary>

- **Startup & tagged-pointer crashes:** Re-running Ghidra with `ResolveJumpTables`, `FixNoReturn`, and `FixEntries` resolved the `0x5c88f0` window-procedure switch table (`SMR_NATIVE_WNDPROC=1`). Added `SQRTPS`/`PSHUFW` emission for `0x83f6e0`, and moved the guest heap in `gheap.c` to `0x18000000–0x40000000` so handle bit 30 (`0x40000000`, used as a tagged-index flag by `0x764a80`) never collides with heap pointers.
- **Last two `game.exe` fallback gaps:** `FixSplitEntry.java` corrected `0x626770` (split two bytes late at `0x626772`), and teaching both emitters `in`/`out`/`swi` CALLOTHERs enabled `0x7c727c` (`OUTSB`) and `0x7c7290` with Unicorn-matching no-op port semantics (`in` → `0`, `out` → no-op, `swi` → trap).
- **Deferred HDR lighting:** `copy_tokens` in `vendor/macos-runtime/upstream/recomp/host/d3d9.c` now skips `OP_COMMENT` (`0xFFFE`) blocks instead of terminating early on `0x0000FFFF` inside D3DX `PRES` preshader comments.
- **2D & 3D LUT texture loading:** `Unk_QueryInterface` rejects D3D9Ex IIDs (`IID_IDirect3DDevice9Ex`, `IID_IDirect3D9Ex`, `IID_IDirect3DSwapChain9Ex`) and cross-type texture queries so `d3dx9_43.dll` permits `D3DPOOL_MANAGED` loads (all 343 2D textures + 32×32×32 LUT). Added `IDirect3DVolumeTexture9` and `IDirect3DVolume9` (`GetLevelDesc`, `GetVolumeLevel`, `LockBox`, `UnlockBox`) with Metal `MTLTextureType3D` upload.
- **sRGB & exposure:** Implemented hardware `_sRGB` texture views (`D3DSAMP_SRGBTEXTURE`) and sRGB render-target attachment views (`D3DRS_SRGBWRITEENABLE`) in `d3d9_metal.m`, fixing double-gamma overexposure across albedo textures and the 3D color-grading LUT.
- **Performance:** Added native fast shims in `src/host/msvcr90.c` (`memset`, `memcpy`, `memmove`, `memcmp`, `strcmp`, `strncmp`, `_stricmp`, `_strnicmp`) that bypass guest `msvcr90.dll`, reducing DLL fallback roots from `251` to `217`.

</details>

<details>
<summary><strong>Required Local Inputs (<code>work/</code>) &amp; Pinned Upstreams</strong></summary>

Game assets and compiled outputs are kept out of Git under `work/`:

- `work/boot/ShootManyRobots.exe` — unpacked 32-bit Windows PE guest executable
- `work/installed/` — unpacked game content (`.sar` archives) and bundled redistributables
- `work/vc90/dlls/` — x86 Visual C++ 2008 CRT DLLs (`msvcr90.dll`, `msvcp90.dll`)
- `work/d3dx/` — June 2010 DirectX x86 DLLs (`d3dx9_43.dll`, `d3dcompiler_43.dll`)
- `work/smr-fixed.jsonl` — Ghidra P-code export (`46,464` primary functions)
- `work/smr-generated/` & `work/smr-entry-generated/` — emitted C translation units (`50,203` full / `189` entry)

Pinned upstream baselines:

- `vendor/recompiler`: [Fallout-NV-MacOS](https://github.com/thetheoryofR/Fallout-NV-MacOS) @ `ff8e0d791e3e1f0148a2245c12c7706855e66926`
- `vendor/macos-runtime`: [Fallout-ElderScrolls-macOS-Port](https://github.com/pedroh77/Fallout-ElderScrolls-macOS-Port) @ `9470dcf94dd69f37263a9f94db69957a76dbed7b`

</details>

<details>
<summary><strong>Reproducing the Ghidra P-Code Export &amp; Full C Emission</strong></summary>

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

Keep `--extra config/smr-extra-entries.json` so re-emission preserves the `3,739` recovered secondary entries.

</details>

<details>
<summary><strong>Middleware Probe (<code>PhysXLoader.dll</code>)</strong></summary>

Early validation extracted 33 leaf functions from `PhysXLoader.dll` (`0x10000000` image base, requiring [`patches/pe-image-base.patch`](patches/pe-image-base.patch)) and verified them against Unicorn (`10` pass, `15` flags-only, `8` untestable, `0` real mismatches):

```sh
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

</details>
