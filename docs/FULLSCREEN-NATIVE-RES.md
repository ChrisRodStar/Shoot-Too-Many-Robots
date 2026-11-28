# Full screen at native resolution — research notes

Status: research + validated prototype (uncommitted). Default behavior is unchanged apart from a
Retina pixel→point sizing fix; the new display/fullscreen paths are opt-in with
`SMR_NATIVE_RES=1` and `SMR_AUTO_FULLSCREEN=1`.

Target machine used for measurements: Apple M4, two 2560×1440 displays
(AW2725DM @144 Hz main, DELL S2722DC @75 Hz), macOS 26.

---

## 1. What the game does today

### 1.1 The guest never renders at more than 1280×720

The D3D9 device is created from `IDirect3D9::CreateDevice`, and the guest fills
`D3DPRESENT_PARAMETERS` with **`BackBufferWidth = 0`, `BackBufferHeight = 0`** and
`Windowed = TRUE` (verified in the emitted C for `FUN_005d05a0`,
`work/smr-generated/tu_000ba.c`, stores at `0x5d075e`…`0x5d07ae`). In windowed mode Direct3D
ignores those fields, so the effective size is whatever the host reports as the desktop mode.

`vendor/macos-runtime/upstream/recomp/host/d3d9.c:1013` then does:

```c
g_d3d.width  = G32(pp)     ? G32(pp)     : fnv_display_width();
g_d3d.height = G32(pp + 4) ? G32(pp + 4) : fnv_display_height();
```

`fnv_display_width/height` are never configured by this port. They keep the hard-coded default
from `vendor/macos-runtime/macos/FNVDisplay.c:5`:

```c
static unsigned width = 1280, height = 720, ...
```

That single default is why every log line says `CreateDevice 1280x720` even when the game's
`smrconfig.ini` asks for 800×600, 3024×1964, etc. The windowed window also starts at that size
(`[smr-window] opened 1280 x 720 points`).

The 1024×768 `Reset` mentioned in `tools/recomp/check_frame_fill.py` is a later tutorial reset,
not the boot mode.

### 1.2 The game's own fullscreen toggle is thrown away

`Shoot Many Robots` does not call `ChangeDisplaySettings`. Its fullscreen path is
`FUN_005ce1a0` (`work/smr-generated/tu_000b9.c`), which:

1. `SetWindowLongA(hwnd, GWL_STYLE, 0x80000000)` — `WS_POPUP`
2. `SetWindowPos(hwnd, HWND_NOTOPMOST, 0, 0, width, height, SWP_NOCOPYBITS)`
3. `SetWindowPos(hwnd, HWND_NOTOPMOST, 0, 0, 0, 0, SWP_NOSIZE|SWP_NOMOVE|SWP_NOZORDER|SWP_NOACTIVATE|SWP_FRAMECHANGED|SWP_SHOWWINDOW)`
4. a device `Reset` with `Windowed = FALSE`

The shims are stubs:

- `shims_win.c:83` `SetWindowPos` → `RET(c, 1, 7)` (does nothing)
- `shims_win.c:78` `ShowWindow` → `RET(c, 1, 2)` (does nothing)
- `SetWindowLongA` records `window_style` but nothing consumes it

So the guest believes it is fullscreen while the AppKit window keeps its title bar and its
original size. That is also why the saved `smrconfig.ini` can say `Fullscreen=True` while the
game still runs in a window.

A windowed run with `SMR_TRACE_WINDOW=1` shows the exact split:

```
Fullscreen=True                          Fullscreen=False
CreateDevice 1280x720 windowed=1         CreateDevice 1280x720 windowed=1
SetWindowPos(0,0,1280,720)               SetWindowPos(0,0,1280,720)
SetWindowLongA(-16, 0x80000000)          SetWindowLongA(-16, 0x00ca0000)
SetWindowPos(0,0,1280,720)               SetWindowPos(0,0,1280,720)
SetWindowPos(0,0,0,0, 0x67)              SetWindowPos(0,0,0,0, 0x67)
Reset 1280x720 windowed=0                Reset 1280x720 windowed=1
```

Two useful conclusions:

- `Windowed = FALSE` in the `Reset` is the authoritative fullscreen signal.
- The game uses a **borderless-window** fullscreen model, not an exclusive display mode, so the
  host never needs `CGDisplaySetDisplayMode`.

### 1.3 The only working fullscreen path is the host's Cmd+F

`src/host/surface.m` already maps Cmd+F / Ctrl+Cmd+F / Option+Return to
`toggleFullScreen:`. That enters a real macOS fullscreen Space, but it only **upscales** the
1280×720 backbuffer to the 2560×1440 drawable with MetalFX/bilinear. It does not change the
render resolution.

### 1.4 Retina sizing is wrong even before fullscreen

`fnv_surface(device, size)` receives a **pixel** size from the renderer but treats it as
**points** (`surface.m:313`), and `smr_fitted_content_size` clamps it to 95 % of
`visibleFrame`. On a 2× display the current 1280×720 backbuffer therefore asks for a 1280×720
*point* window (2560×1440 px drawable): the image is still 1:1 at 720p, but the window is
physically twice as large as intended. A native 2560×1440 backbuffer would ask for a 2560×1440
point window, get clamped to the visible frame, and end up with a ~2872×1866 px drawable — an
upscale. This needs an explicit pixel→point conversion.

---

## 2. What "native resolution" requires

There are only three levers:

1. **Publish the panel size as the D3D9 desktop mode** — `fnv_display_configure(w, h)`.
   Because the guest's backbuffer is 0×0, this alone changes the render resolution.
2. **Size the AppKit window/drawable in pixels** — convert to points with
   `backingScaleFactor`, and do not clamp in fullscreen.
3. **Map the guest's fullscreen state onto the NSWindow** — `WS_POPUP` / `Windowed=FALSE`
   → `toggleFullScreen:`.

The renderer already contains everything else: `fnv_display_configure_scaled` (render scale),
`fnv_output_width/height`, MetalFX Spatial, sRGB, and the aspect-fit presenter
(`d3d9_metal.m:1960`). The port simply never calls the display configuration.

---

## 3. Prototype (validated)

The prototype adds:

| File | Change |
| --- | --- |
| `src/host/surface.m` | `smr_screen_pixels` / `smr_configure_display` (native size + refresh + optional `SMR_RENDER_SCALE`), pixel→point conversion in `fnv_surface`/`fnv_resize_surface`, `fnv_set_fullscreen`, transition bookkeeping/logging |
| `vendor/macos-runtime/macos/FNVDisplay.h` | declare `fnv_display_configure_scaled`, `fnv_display_set_refresh`, `fnv_output_width/height` |
| `vendor/macos-runtime/macos/FNVSurface.h` | declare `fnv_set_fullscreen` |
| `shims_win.c` | weak `fnv_set_fullscreen`; on `SetWindowLongA(GWL_STYLE)` call it with `WS_POPUP` state when `SMR_AUTO_FULLSCREEN` is set; opt-in window trace (`SMR_TRACE_WINDOW`) |
| `d3d9.c` | `Reset` log now prints the `Windowed` flag (diagnostic only) |

Enable:

```sh
SMR_NATIVE_RES=1 SMR_AUTO_FULLSCREEN=1 ./scripts/recomp run --to tutorial --full
# or directly
SMR_NATIVE_RES=1 SMR_AUTO_FULLSCREEN=1 SMR_WINDOW=1 ./scripts/startup-probe
```

`SMR_RENDER_SCALE=50..100` renders below native and lets the existing MetalFX path upscale to the
panel (useful if a scene is GPU-bound).

### 3.1 Measured result

Headless full-build runs, deterministic tutorial script, same machine:

| | 1280×720 (today) | 2560×1440 (prototype) |
| --- | --- | --- |
| Guest device / backbuffer | 1280×720 | **2560×1440** |
| Fullscreen `Reset` | `windowed=0` | `windowed=0` |
| GPU average / max | 2.87 / 3.76 ms | **7.80 / 10.81 ms** |
| CPU average / max | 15.31 / 30.28 ms | 16.05 / 29.37 ms |
| Footprint | 1,371 MiB | 1,512 MiB |
| Tutorial FPS | 59–60 | **56–60** |
| Presenter upscale | MetalFX 720p→1440p | **none, 1:1 blit** |

The FPS row is from offscreen runs (the host's `pace_60fps` path). On a real 144 Hz windowed
surface the presenter cadence caps at ~48 fps for a 60 fps guest — see §3.2; that limit is the
same at 720p and 1440p.

With `SMR_RENDER_SCALE=75` the guest renders 1920×1080 into a 2560×1440 output
(`[metalfx] spatial scaler 1920x1080 -> 2560x1440`), GPU average drops to **6.04 ms**
(max 8.18 ms), CPU 14.76 ms.

Windowed fullscreen run (`SMR_WINDOW=1`, no `FNV_HEADLESS`):

```
[smr-window] display 2560x1440 px, render 2560x1440 (100%), 144 Hz
[d3d9] CreateDevice 2560x1440 ...
[smr-window] opened 2229 x 1254 points, drawable 2229 x 1254 px
[d3d9] Reset 2560x1440 windowed=0
[smr-window] full screen request enter
[smr-window] entered full screen, drawable 2560 x 1440 px
```

The drawable matches the backbuffer exactly, and no `[metalfx] spatial scaler` line is emitted
(1:1 path).

### 3.2 A separate 144 Hz problem

The same run reports:

```
[perf] interval_ms=20.89 ... present_ms=19.71 drawable_wait_ms=19.69 gpu_ms=7.80 main_cpu_ms=1.19
```

That is 47.9 fps, not 60, and the title screen only needs 1.19 ms of CPU. The cause is the
presenter's fixed cap in `d3d9_metal.m:2001`:

```objc
if (!getenv("FNV_NOVSYNC") && fnv_display_refresh() > 62)
    [cmd presentDrawable:drawable afterMinimumDuration:1.0 / 60.5];
```

On a 144 Hz panel a 60 fps frame cannot land on a vsync boundary: the next available refresh is
3 × 6.94 ms = 20.83 ms → 48 fps. (A 60 Hz panel gives exactly 60; 120 Hz also works because
60 = 2 refreshes.) Options:

- request a 120 Hz mode (60 = 2 refreshes) while fullscreen;
- run the display at 60 Hz in fullscreen;
- `FNV_NOVSYNC=1` + the existing `pace_60fps()` (tearing possible);
- accept 48 fps on 144 Hz.

This is independent of the resolution change but matters for "actually play".

---

## 4. Recommended implementation

### Phase 1 — native render size (low risk)

1. At host start, before the guest thread:
   - `fnv_display_configure_scaled(panelW, panelH, renderScale)`
   - `fnv_display_set_refresh(screen.maximumFramesPerSecond)`
   - panel size from `CGDisplayCopyDisplayMode` → `CGDisplayModeGetPixelWidth/Height`
     (this is the size the fullscreen drawable will have; on scaled Retina modes it is the
     backing size, not the physical panel).
2. Fix `fnv_surface` / `fnv_resize_surface` to treat their argument as pixels
   (`points = px / backingScaleFactor`).
3. Log the chosen display/render sizes (already in the prototype).

This alone gives native resolution in the existing Cmd+F fullscreen.

### Phase 2 — make the game's fullscreen work

1. Keep the weak `fnv_set_fullscreen` hook.
2. In `SetWindowLongA(GWL_STYLE)` map `WS_POPUP` → enter/leave native fullscreen.
   (`Reset`'s `Windowed` flag is a redundant, equally valid trigger; don't use both without
   deduplication.)
3. Guard with a transition flag (already done) because `toggleFullScreen:` is asynchronous and
   `windowDidEnter/ExitFullScreen` arrive later.
4. On exit, restore the window's saved frame; on multi-monitor setups use the screen that owns
   the window (`game_window.screen`), not always `mainScreen`.

### Phase 3 — polish / correctness

- **Mode list:** `D3D_EnumAdapterModes` currently returns a fixed list that includes
  3840×2160 on a 2560×1440 panel (`d3d9.c:928`). Filter it to modes ≤ panel size and put the
  panel mode first, so the in-game resolution picker cannot select an impossible mode.
- **Aspect:** with 16:9 panels this is a no-op. On 16:10 panels the game would render 16:10
  natively; the camera is driven by the backbuffer aspect and the UI is anchored, but the
  cutscene letterbox and HUD should be checked.
- **Notch:** if a MacBook panel is used, either use the full panel (content under the notch) or
  reserve the top inset as the upstream `FNVApp.m` does. The current `smr_sync_drawable` uses the
  whole view; no notch handling exists.
- **Transitions:** during the macOS fullscreen animation the drawable size changes every frame,
  which recreates MetalFX/bilinear intermediates (visible as a cascade of `[metalfx] spatial
  scaler 1280x720 -> NxM` lines). Skip upscaling while `fullscreen_transition` is set, or just
  blit 1:1, to avoid the hitch.
- **Persistence:** the game writes `Fullscreen` and `WindowWidth/Height` to
  `…/Demiurge Studios/Shoot Many Robots/Player/smrconfig.ini`. It also has
  `Resolution Width` / `Resolution Height` keys (strings at `0x5ecc74`/`0x5ecc88`), which are
  absent from the current file. Verify what the in-game resolution picker writes before adding
  host-side persistence.
- **Refresh:** decide the 144 Hz policy above; optionally set a 120 Hz display mode only while
  fullscreen.

### Phase 4 — test matrix

- 1280×720 vs 2560×1440 vs `SMR_RENDER_SCALE=75`; windowed → Cmd+F → in-game toggle → Cmd+F.
- 16:9 (both monitors here) and a 16:10 MacBook panel.
- Two displays: launch on the secondary, toggle, drag between screens.
- Save/load, cutscenes (the 1024×768 `Reset`), and the tutorial's frame-fill check
  (`tools/recomp/check_frame_fill.py`).
- Alt-tab / Mission Control / display sleep while fullscreen.
- FPS at 60/75/120/144 Hz.

---

## 5. Risks

- **GPU cost:** 4× pixels. Measured 2.9 → 7.8 ms average on an M4; a heavier combat scene could
  approach the 16.7 ms budget. `SMR_RENDER_SCALE` is the escape hatch.
- **Memory:** +~140 MiB in the tutorial; deferred G-buffers scale with resolution.
- **Window state:** the guest sets `WS_POPUP` *without* `WS_VISIBLE`; don't mirror the raw style,
  just the fullscreen intent.
- **Race at startup:** the game restyles the window immediately after device creation; the
  window must exist first (it does — `fnv_surface` is called from `d3d_backend_init` before the
  style call).
- **Uncommitted prototype:** `work/research/fullscreen-native-res.patch` contains the exact diff
  if the in-tree changes need to be moved to a branch/commit.

---

## 6. Files worth reading

- `src/host/surface.m` — window, drawable, fullscreen, menu.
- `vendor/macos-runtime/macos/FNVDisplay.c` — the 1280×720 default and render-scale config.
- `vendor/macos-runtime/upstream/recomp/host/d3d9.c:1009` — `CreateDevice` fallback.
- `vendor/macos-runtime/upstream/recomp/host/d3d9.c:661` — `Reset`.
- `vendor/macos-runtime/upstream/recomp/host/d3d9_metal.m:1960` — aspect-fit present and
  MetalFX.
- `vendor/macos-runtime/upstream/recomp/host/shims_win.c:117` — `SetWindowLongA`.
- `work/smr-generated/tu_000b9.c` (`FUN_005ce1a0`) — the guest's fullscreen toggle.
- `work/smr-generated/tu_000ba.c` (`FUN_005d05a0`) — device creation with a 0×0 backbuffer.
