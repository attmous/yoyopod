# LVGL Display Pipeline

Applies to: `yoyopod/ui/lvgl_binding/**`, `yoyopod/ui/display/adapters/whisplay.py`

## Overview

LVGL 9.5.0 is the standard rendering layer for all hardware displays. The architecture is display-hardware-agnostic -- LVGL renders to its internal buffer, then flush callbacks route pixels to whatever SPI display is connected.

For the Figma-to-Whisplay implementation workflow, screen extraction order, and hardware validation loop, also follow `rules/design-fidelity.md`.

## Production Contract

- Non-simulated Whisplay runs are a production LVGL path.
- `display.whisplay_renderer: lvgl` is the only supported production setting for Whisplay hardware.
- If the Whisplay driver, hardware init, or LVGL shim/backend is unavailable, startup must fail loudly instead of silently degrading to another renderer.
- The Rust runtime software preview reuses the Whisplay LVGL render contract and browser preview transport; it is not a separate PIL renderer.
- Simulation also requires the native LVGL shim. If the shim is missing, the correct fix is to build it, not to fall back to PIL.

## Rendering Pipeline

```
LVGL object tree
  -> partial render (40-line draw buffer)
  -> flush callback (RGB565_SWAPPED)
  -> LvglDisplayBackend._flush_callback() [Python]
  -> Rgb565FlushTarget.draw_rgb565_region() [adapter]
  -> hardware SPI + RGB565 framebuffer/browser preview
```

## C Shim (`native/lvgl_shim.c`)

The C shim bridges Python (via cffi) and the LVGL C library:
- `yoyopod_lvgl_init/shutdown` -- lifecycle
- `yoyopod_lvgl_register_display` -- sets up flush callback, RGB565_SWAPPED format
- Scene functions (`hub_build/sync/destroy`, `listen_*`, `playlist_*`, etc.) -- each screen type
- `yoyopod_lvgl_snapshot` -- captures active screen via `lv_snapshot_take()`
- `yoyopod_lvgl_force_refresh` -- invalidates and redraws immediately

## Python Binding (`binding.py`)

cffi ABI-mode wrapper. Mirrors the C shim API 1:1. Key patterns:
- Strings encoded to `char[]` via `ffi.new()`
- Colors packed as `(r, g, b)` tuples -> 24-bit RGB via `_pack_rgb()`
- `to_bytes()` converts cffi pixel buffers to Python bytes

## lv_conf.h

Minimal config enabling only what YoYoPod uses:
- `LV_COLOR_DEPTH 16` (RGB565)
- `LV_USE_SNAPSHOT 1` (for screenshot readback)
- Montserrat fonts 12-40
- Flex layout, list, label, button, image widgets

## Building

```bash
yoyopod build simulation   # prepares the LVGL shim used by the Rust runtime preview
yoyopod build lvgl         # clones LVGL 9.5.0, compiles shim
yoyopod build ensure-native
```

Must rebuild on Pi after changing `lv_conf.h` or `lvgl_shim.c`.

## Screenshot Support

- `yoyopod remote screenshot` defaults to the shadow-first path via `SIGUSR2`.
- `yoyopod remote screenshot --readback` requests LVGL readback via `SIGUSR1`.
- The remote helper now clears the previous remote PNG before capture and waits for a fresh file.
- Both screenshot signals also append freeze diagnostics to `logs/yoyopod_errors.log`:
  - an all-thread traceback dump from `faulthandler`
  - a structured runtime snapshot logged before the screenshot is queued
- To confirm which path actually succeeded, check the app log:
  - `Saved screenshot via LVGL readback` means native LVGL snapshotting succeeded.
  - `Saved screenshot via shadow buffer` means the RGB565 framebuffer path was used instead.
