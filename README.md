# Shoot Too Many Robots

**Apple Silicon (ARM64) static-recompilation port and compatibility runtime for the Windows release of *Shoot Many Robots* (Demiurge Studios / Seoul Engine).**

This project lifts the 32-bit x86 Windows executable through Ghidra P-code into native ARM64 C, links it against a custom macOS Win32 + Direct3D 9 → Metal host runtime, statically recompiles the D3DX9 and FMOD audio middleware, and runs the remaining third-party x86 DLLs (`PhysXCore`, `msvcr90`) under a transparent Unicorn fallback until shimmed or recompiled natively.

> **Decompilation:** [`Decompile/`](Decompile/) is a separate, readable decompilation of the game (Ghidra C, RTTI/vtable recovery, searchable indexes, and the start of a Fallout-style byte-exact matching harness). It is not needed to run the game. See [`Decompile/README.md`](Decompile/README.md).

---

## Status at a Glance

| Area | Status | Notes |
| --- | --- | --- |
| **Executable Translation** | **50,203 / 50,204** functions | `46,464` primary + `3,739` secondary entries (`0x96006b` skipped for unreachable `XBEGIN`) |
| **Game Code Fallbacks** | **0 `game.exe` fallbacks** | 100% native `game.exe` execution in `--full` mode (`SMR_NATIVE_WNDPROC=1` by default) |
| **3D Rendering (D3D9 → Metal)** | **Lit, textured, color-graded** | Deferred lighting, 343 2D textures, 32×32×32 3D LUT, hardware `_sRGB`, `ff-skipped 0` |
| **Input & Windowing** | **Working** | 1280 × 720 AppKit window, keyboard/mouse forwarding, prefers secondary Dell display |
| **Audio (FMOD)** | **Streaming** | `fmodex.dll` + `fmod_event.dll` statically recompiled; DirectSound shim → CoreAudio `FNVAudioMixer` PCM voices |
| **Latest Acceptance Run** | **Exit 0 · 59.4 fps** | `487` draws (`646` peak) · `16.8 ms` CPU · `2.2 ms` GPU · `163` DLL fallback roots · `0` faults/traps |

### Milestones

- [x] Boot Windows PE cleanly to title screen and advance through loading into the tutorial
- [x] Eliminate all `game.exe` Unicorn fallbacks (`0` remaining in full build)
- [x] Full deferred HDR lighting, 2D/3D texture loading, and sRGB color grading in Metal
- [x] Fast native shims for hot `msvcr90.dll` memory/string routines
- [x] Offline differential verifier (`./scripts/recomp verify`) and automated tutorial acceptance runner
- [ ] Interactive tutorial-to-combat playtesting (controls, combat physics, menus, saves)
- [x] Audio playback via FMOD → DirectSound / CoreAudio (`DirectSoundEnumerateW` & `dsound.c`)
- [ ] Reduce remaining `163` DLL fallback roots (`PhysXCore`, `msvcr90`, `msvcp90`, `d3dcompiler_43`) for 60 fps and faster loading

---

## Architecture

```text
ShootManyRobots.exe (x86 PE)
   └─► Ghidra headless P-code export (work/pcode/smr-fixed.jsonl)
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
| [`tools/assets/`](tools/assets/) | SAR v3 extractor and local Next.js asset viewer |
| [`tools/ghidra/scripts/`](tools/ghidra/scripts/) | Ghidra headless analysis and P-code export scripts (`DumpPcode.java`, `FixSplitEntry.java`, etc.) |
| [`scripts/`](scripts/) | Entry points (`recomp`, `startup-probe`, `dev-setup`) and deterministic input scripts (`smr-title.script`, `smr-tutorial.script`) |
| [`config/`](config/) | Curated small inputs (`guest-manifest.json`, `entry-set.json`, `smr-extra-entries.json`, `learned-entries.txt`) |
| [`patches/`](patches/) | Reusable upstream reference deltas (`pe-image-base.patch`, `recompiler-mmx-sse.patch`) |
| [`docs/`](docs/) | Detailed engineering docs — see [`docs/RECOMP-WORKFLOW.md`](docs/RECOMP-WORKFLOW.md) for the dev loop design |
| `work/` *(ignored)* | Local 7 GB workspace — guest inputs, P-code, Ghidra projects, generated C, builds, reports, runtime scratch, extracted assets, and packaged app. See [the work layout](#work-directory-layout) |
| `logs/` *(ignored)* | Build and runtime logs (`window-full-startup.log`, `window-startup.log`, `native-startup.log`) |

### Work Directory Layout

`work/` is organized by lifecycle, so each top-level directory answers one question: what it is, whether it can be rebuilt, and whether it is safe to delete.

```text
work/
├── inputs/        guest inputs, treated as read-only
│   ├── exe/       prepared ShootManyRobots.exe (patched by the installer)
│   ├── installed/ unpacked game (.sar archives, Binaries, redist payloads)
│   ├── vc90/      x86 VC++ 2008 CRT DLLs
│   └── d3dx/      June 2010 DirectX DLLs
├── pcode/         Ghidra P-code exports (smr-fixed.jsonl, physx-leaf.jsonl)
├── ghidra/        analysis projects, one directory per module
│   ├── game/      the smr + middleware projects
│   └── physxcore/, d3dx9/, fmodex/, ... (project + DLL + functions.jsonl)
├── generated/     emitted C, one directory per module
│   ├── game/      full 50,203-function translation
│   ├── game-entry/ 189-entry startup subset
│   └── physxcore/, d3dx9/, ... (with lifted-dll markers)
├── build/         host binaries and object caches (window-host*, startup*cache)
├── reports/       differential-test fixtures and reports (*-diff.json)
├── run/           runtime scratch: frame dumps (frames/) and per-flavor user dirs
├── assets/        extracted SAR content (extracted/) and upgrade experiments
├── dev/           recomp dev state: verify cache, run history, promotion backups
├── scratch/       perf samples, one-off patches, stale experiments, old dumps
└── dist/          packaged "Shoot Too Many Robots.app"
```

Only `inputs/`, `pcode/`, and `ghidra/` are expensive to recreate. `generated/` is re-emitted from `pcode/`; `build/` and `dev/` are caches; `reports/`, `run/`, and `scratch/` are safe to delete; `assets/` and `dist/` are regenerable from `inputs/`.

---

## Quick Start & Dev Loop

### Browse Extracted Assets

From the project root, install the viewer and start it with Node.js 20.9 or later. If `work/assets/extracted/manifest.json` is missing, run `python3 tools/assets/extract_sar.py` first.

```sh
npm ci --prefix tools/assets/viewer
npm --prefix tools/assets/viewer run dev
```

Open [the local asset viewer](http://127.0.0.1:3060). It reads the SHA-256 manifest in `work/assets/extracted/`, where originals retain their archive-relative paths. Categories follow the assets' role, with separate filters for file type and group. For example, choose **Environment → Image / texture** for environment textures or **Interface → HUD** for the HUD files. **Save original** returns the extracted file. The [standalone viewer](tools/assets/viewer.html) is also available for browsing an ad hoc folder from the browser.

With Pillow installed, `python3 tools/assets/extract_sar.py --previews-only` refreshes the PNG previews and adds original dimensions and encoding to the manifest. The previews fit within 512 × 512 pixels. For image work, decode a full-resolution master from the original DDS or SIF.

### Plan Image Upgrades

Start with a small 2× pilot using a recognizable interface icon, a tiled ground texture, a character color map, and a translucent effect. Compare the full-resolution decode, a conventional resize, and a Real-ESRGAN candidate at actual display size. Check readability, repeated tile seams, alpha edges, and in-game appearance before expanding the batch. [Real-ESRGAN](https://github.com/xinntao/Real-ESRGAN)

| Asset type | Approach |
| --- | --- |
| Interface icons, fonts, and HUD | For assets with editable masters, export from those at the target resolution. For new replacements, use editable vectors or type. Check any sprite bounds, padding, and other layout data referenced by the interface movie. |
| Character, weapon, and environment color textures | Start with a 2× comparison for visible, low-resolution textures. Preserve the UV layout and check seams and bleed at lower mip levels. |
| Normal maps, channel-packed masks, LUTs, and FX | Identify the role and channel mapping first. Resample channels according to their data, renormalize normals, and preserve LUT dimensions unless the shader is updated too. Check translucent effects over light and dark backgrounds. |
| Meshes and animation | Prioritize only assets whose shapes or movement need work. New meshes or animations require a separate authoring and import workflow. |

Use a separate ignored location such as `work/assets/upgrades/` for experiments. Keep candidate files keyed by the original asset path. Before testing a replacement in the runtime, check texture encoding, alpha handling, and mipmaps against the original. The extraction contains DXT1 and DXT5 textures, so use a compatible legacy format when testing DDS output. Treat SIF repacking and interface layout integration as separate checks. [DirectXTex texture processing](https://github.com/microsoft/DirectXTex/wiki/texconv)

### Run the 2× Color Texture Pilot

Use Python 3 with Pillow 11.3+ and the [Real-ESRGAN macOS portable release](https://github.com/xinntao/Real-ESRGAN/releases/tag/v0.2.5.0). The script looks for the executable and its adjacent `models/` folder under `work/assets/upgrades/tools/realesrgan/`. Use `--upscaler` if the executable is elsewhere.

```sh
python3 tools/assets/upscale_textures.py --pack-from work/inputs/installed/app/ShootManyRobots/Data/PC_ContentPC.sar
```

The default pilot contains the Overlord diffuse map and one Farmland dirt texture. It writes PNG previews, DDS-backed SIF replacements, and the optional test archive under `work/assets/upgrades/texture-pilot/`. The test archive preserves the other entries from the original. The script checks dimensions and compression and regenerates the mip chain.

In the asset viewer, choose **Upscaled only** and select a texture to open its before-and-after view. **Slider** stacks the upscale over the original so you can drag the divider to reveal either one; **Side by side**, **Before**, and **After** are also available. Click to zoom, drag to pan, and press Escape to return to the gallery. While the viewer tab is visible, it picks up completed images from batch folders directly under `work/assets/upgrades/` about every five seconds.

Use `--list` with repeated `--match` globs to review a larger batch before running it. For example, `--match 'Environment/Farmland/Ground_Tiles/Dirt_0?.SIF'` selects the three Farmland dirt variants. Texture names alone cannot establish channel usage, so select known color maps and use a separate `--output` directory for each batch.

### Run the Full 2× Art Batch

```sh
python3 tools/assets/upscale_all_art.py
```

The full pass reuses completed character and ground textures. It uses Real-ESRGAN for world and character color maps and interpolates UI and effect images to preserve their shapes and transparency. It keeps identified data maps, weather cubemaps, and images above the input limit at their original size. The batch records every decision in `work/assets/upgrades/all-art-2x/inventory.tsv` and writes rebuilt archives beside it.

Use `--ui-base` with an existing patched `PC_UI.sar` to carry its title-screen upgrade into the batch. The viewer picks up before-and-after PNGs as each texture completes. The rebuilt UI keeps the original Scaleform layout definitions, so check sprite alignment and clipping when reviewing it in-game.

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
| Offscreen first-frame | `SMR_METAL=1 ./scripts/startup-probe` | Stops after first D3D9 `Present` and saves `work/run/frames/frame_1.png` |
| Headless diagnostics | `./scripts/startup-probe` | No GPU/window; logs to `logs/native-startup.log` |

Useful environment flags: `SMR_BUILD_ONLY=1` (compile without launching), `SMR_TRACE=1` (Win32 API trace), `FNV_DUMP_FRAMES=1,60,300` (dump specific frame numbers), `SMR_CONTINUE=1` / `SMR_PROBE_SECONDS=60` (headless runs).

### Working with Git Worktrees

`SMR_DATA_ROOT` points at a shared read-only copy of `work/`'s inputs (`inputs/`, `pcode/`, and `ghidra/`), so parallel worktrees don't duplicate gigabytes of assets. `dev-setup` links those three directories, copies `generated/` (so a worktree can re-emit safely), and copies the warm `build/startup-full-cache`:

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

- **Startup & tagged-pointer crashes:** Re-running Ghidra with `ResolveJumpTables`, `FixNoReturn`, and `FixEntries` resolved the `0x5c88f0` window-procedure switch table (`SMR_NATIVE_WNDPROC=1`). Added `SQRTPS`/`PSHUFW` emission for `0x83f6e0`, and gave the guest heap a tag-safe two-window layout in `gheap.c` (`0x14000000–0x40000000` plus `0x80000000–0xC0000000`, skipping the `0x40000000–0x7FFFFFFF` tagged band) so handle bit 30 (`0x40000000`, used as a tagged-index flag by `0x764a80`) never collides with heap pointers.
- **Last two `game.exe` fallback gaps:** `FixSplitEntry.java` corrected `0x626770` (split two bytes late at `0x626772`), and teaching both emitters `in`/`out`/`swi` CALLOTHERs enabled `0x7c727c` (`OUTSB`) and `0x7c7290` with Unicorn-matching no-op port semantics (`in` → `0`, `out` → no-op, `swi` → trap).
- **Deferred HDR lighting:** `copy_tokens` in `vendor/macos-runtime/upstream/recomp/host/d3d9.c` now skips `OP_COMMENT` (`0xFFFE`) blocks instead of terminating early on `0x0000FFFF` inside D3DX `PRES` preshader comments.
- **2D & 3D LUT texture loading:** `Unk_QueryInterface` rejects D3D9Ex IIDs (`IID_IDirect3DDevice9Ex`, `IID_IDirect3D9Ex`, `IID_IDirect3DSwapChain9Ex`) and cross-type texture queries so `d3dx9_43.dll` permits `D3DPOOL_MANAGED` loads (all 343 2D textures + 32×32×32 LUT). Added `IDirect3DVolumeTexture9` and `IDirect3DVolume9` (`GetLevelDesc`, `GetVolumeLevel`, `LockBox`, `UnlockBox`) with Metal `MTLTextureType3D` upload.
- **sRGB & exposure:** Implemented hardware `_sRGB` texture views (`D3DSAMP_SRGBTEXTURE`) and sRGB render-target attachment views (`D3DRS_SRGBWRITEENABLE`) in `d3d9_metal.m`, fixing double-gamma overexposure across albedo textures and the 3D color-grading LUT.
- **Performance:** Added native fast shims in `src/host/msvcr90.c` (`memset`, `memcpy`, `memmove`, `memcmp`, `strcmp`, `strncmp`, `_stricmp`, `_strnicmp`) that bypass guest `msvcr90.dll`, reducing DLL fallback roots from `251` to `217`.

</details>

<details>
<summary><strong>Required Local Inputs (<code>work/</code>) &amp; Pinned Upstreams</strong></summary>

Game assets and compiled outputs are kept out of Git under `work/`:

- `work/inputs/exe/ShootManyRobots.exe` — unpacked 32-bit Windows PE guest executable
- `work/inputs/installed/` — unpacked game content (`.sar` archives) and bundled redistributables
- `work/inputs/vc90/dlls/` — x86 Visual C++ 2008 CRT DLLs (`msvcr90.dll`, `msvcp90.dll`)
- `work/inputs/d3dx/` — June 2010 DirectX x86 DLLs (`d3dx9_43.dll`, `d3dcompiler_43.dll`)
- `work/pcode/smr-fixed.jsonl` — Ghidra P-code export (`46,464` primary functions)
- `work/generated/game/` & `work/generated/game-entry/` — emitted C translation units (`50,203` full / `189` entry)

Pinned upstream baselines:

- `vendor/recompiler`: [Fallout-NV-MacOS](https://github.com/thetheoryofR/Fallout-NV-MacOS) @ `ff8e0d791e3e1f0148a2245c12c7706855e66926`
- `vendor/macos-runtime`: [Fallout-ElderScrolls-macOS-Port](https://github.com/pedroh77/Fallout-ElderScrolls-macOS-Port) @ `9470dcf94dd69f37263a9f94db69957a76dbed7b`

</details>

<details>
<summary><strong>Reproducing the Ghidra P-Code Export &amp; Full C Emission</strong></summary>

```sh
export JAVA_HOME="$(brew --prefix openjdk@25)/libexec/openjdk.jdk/Contents/Home"
headless="$(brew --prefix ghidra)/libexec/support/analyzeHeadless"

"$headless" "$PWD/work/ghidra/game" smr -process ShootManyRobots.exe -noanalysis \
  -scriptPath "$PWD/tools/ghidra/scripts" \
  -postScript FixSplitEntry.java 0x626770:0x626772

"$headless" "$PWD/work/ghidra/game" smr -process ShootManyRobots.exe -noanalysis -readOnly \
  -scriptPath "$PWD/tools/ghidra/scripts" \
  -postScript DumpPcode.java "$PWD/work/pcode/smr-fixed.jsonl" all

.venv/bin/python vendor/recompiler/recomp/emit.py work/pcode/smr-fixed.jsonl work/generated/game \
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
dll="$work/inputs/installed/app/ShootManyRobots/Binaries/PhysXLoader.dll"
python="$PWD/.venv/bin/python"

innoextract --extract --output-dir "$work/inputs/installed" "$installer"
export JAVA_HOME="$(brew --prefix openjdk@25)/libexec/openjdk.jdk/Contents/Home"
headless="$(brew --prefix ghidra)/libexec/support/analyzeHeadless"
mkdir -p "$work/ghidra/middleware"
"$headless" "$work/ghidra/middleware" middleware -import "$dll" -overwrite \
  -analysisTimeoutPerFile 120 -scriptPath "$PWD/tools/ghidra/scripts" \
  -postScript DumpPcode.java "$work/pcode/physx-leaf.jsonl" leaf

"$python" "$repo/recomp/emit.py" "$work/pcode/physx-leaf.jsonl" "$work/generated/physx"
JOBS=4 "$repo/recomp/build.sh" "$work/generated/physx" "$work/scratch/physx-build"
"$python" "$repo/recomp/difftest.py" "$dll" "$work/scratch/physx-build/librecomp.dylib" \
  "$work/pcode/physx-leaf.jsonl.regs.json" "$work/reports/physx-difftest.json" --jobs 4
```

</details>
