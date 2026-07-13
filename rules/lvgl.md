# LVGL Display Pipeline

Applies to: `device/ui/**`

## Overview

LVGL 9.5.0 is the rendering layer for the Whisplay display. The UI host
renders into LVGL's internal buffer, then flush callbacks push RGB565
pixels to the Whisplay SPI ST7789-backed panel.

For the Figma-to-Whisplay implementation workflow, screen extraction
order, and hardware validation loop, also follow
`rules/design-fidelity.md`.

## Production Contract

- Whisplay hardware uses LVGL as the only app UI renderer; there is no
  renderer selection knob.
- If the Whisplay driver, hardware init, or LVGL backend is
  unavailable, startup must fail loudly instead of silently degrading.

## Rendering Pipeline

```
LVGL object tree
  -> partial render (40-line draw buffer)
  -> flush callback (RGB565_SWAPPED)
  -> Rust display bridge in `device/ui/src/renderer/lvgl/`
  -> Whisplay SPI + RGB565 framebuffer
```

## Native Boundary

Rust owns the scene controllers and calls upstream LVGL directly through
`device/ui/src/renderer/lvgl/ffi.rs`. The only C dependency in this path is
upstream LVGL itself, built from the pinned 9.5.0 source using
`device/ui/native/lvgl`.

## lv_conf.h

Minimal config enabling only what YoYoPod uses:
- `LV_COLOR_DEPTH 16` (RGB565)
- `LV_USE_SNAPSHOT 1` (for screenshot readback)
- Montserrat fonts 12-40
- Flex layout, list, label, button, image widgets

## Building

LVGL native build commands moved out of the CLI in the Round 0 rebuild
and have not yet been ported back. For normal dev/prod validation, rely
on the CI-built Rust artifact for the exact commit under test:
`yoyopod target deploy` fetches the `yoyopod-rust-device-arm64-<sha>`
bundle which already contains the linked LVGL.

If you ever need to rebuild LVGL locally (e.g. while iterating on
`lv_conf.h`), invoke cmake directly:

```bash
cmake -S device/ui/native/lvgl -B device/ui/native/lvgl/build \
    -DCMAKE_BUILD_TYPE=Release \
    -DLVGL_SOURCE_DIR=.cache/lvgl/lvgl-9.5.0 \
    -DCONFIG_LV_BUILD_EXAMPLES=OFF -DCONFIG_LV_BUILD_DEMOS=OFF
cmake --build device/ui/native/lvgl/build --parallel 2
```

Do not rebuild LVGL on the Pi.

## Screenshot Support

- `yoyopod target screenshot` defaults to the shadow-first path via `SIGUSR2`.
- `yoyopod target screenshot --readback` requests LVGL readback via `SIGUSR1`.
- The CLI clears the previous remote PNG before capture and waits for a fresh file.
- The runtime (`device/runtime/src/cli.rs`) registers both signals next to its
  SIGINT handler and forwards a `ui.screenshot` command to the UI worker, which
  captures via `lv_snapshot_take` (readback) or the RGB565 shadow framebuffer,
  falls back to the other path on failure, and writes the PNG atomically
  (temp file + rename) to `/tmp/yoyopod_screenshot.png`.
- The runtime appends `Screenshot capture requested (…)` to the app log when a
  signal arrives. The Python-era freeze diagnostics (all-thread backtrace dump
  to `logs/yoyopod_errors.log`) were not ported to the Rust runtime.
- To confirm which path actually succeeded, check the app log:
  - `Saved screenshot via LVGL readback` means native LVGL snapshotting succeeded.
  - `Saved screenshot via shadow buffer` means the RGB565 framebuffer path was used instead.
