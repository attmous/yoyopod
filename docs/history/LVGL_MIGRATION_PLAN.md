# LVGL CPython Migration Plan

**Last Updated:** 2026-04-05
**Scope:** Whisplay-first LVGL migration for the CPython YoYoPod runtime
**Status:** Historical migration record, partly completed

> Current note: the supported runtime is now LVGL-only for Whisplay hardware, Pimoroni/ST7789 hardware, and simulation. References below to PIL, mixed-renderer migration stages, or old target splits are historical context, not the current product contract. For current implementation details, trust `AGENTS.md`, `docs/architecture/SYSTEM_ARCHITECTURE.md`, and the code under `yoyopod/ui/lvgl_binding/`.

> Read this as migration history plus remaining rationale, not as proof that every phase item below is still pending.

---

## Summary

- Keep the current CPython app, `EventBus`, FSMs, coordinators, router, and input grammar.
- Target Whisplay first. Pimoroni and the current simulator stay on the PIL path during migration.
- Pin LVGL `v9.5.0`.
- Use a small native C shim between CPython and LVGL, then bind that shim from Python with `cffi`.
- Do a fast cutover at the screen level, but preserve current screen class names and routes by turning each screen into a controller that delegates to a backend-specific view.

---

## Key Implementation Changes

### Prep

- Save this plan in-repo and keep `AGENTS.md` pointing here.
- Add a new config switch:
  - `display.whisplay_renderer: pil | lvgl`
  - default: `pil`

### Phase 0: Whisplay LVGL Proof

- Build LVGL `v9.5.0` on the Pi as a shared library for the proof only.
- Create a minimal native bridge under `yoyopod/ui/lvgl_binding/native/` that links to LVGL and exposes a narrow ABI:
  - init/shutdown
  - display registration
  - input registration
  - tick/timer pumping
  - basic probe-scene helpers
- Write a standalone probe script with no app dependency that renders:
  - one card
  - one list
  - one footer
- Flush to Whisplay through the existing `draw_image(x, y, width, height, pixel_data)` path using partial RGB565 area flushes.
- Start with a partial draw buffer sized `240x40` pixels.

### Phase 1: Production Backend Integration

- Stop using `/usr/local` as the production contract after the proof; production must build from repo-pinned sources.
- Add `LvglDisplayBackend` plus a Python binding layer under `yoyopod/ui/lvgl_binding/`.
- Python binds to the shim header, not to all LVGL headers.
- Keep `Display` as the app entrypoint, but add backend-aware accessors:
  - `backend_kind`
  - `get_ui_backend()`
  - hard reset/clear on backend handoff
- Keep PIL for non-Whisplay targets.

### Phase 2: Main Loop and Input Bridge

- Do not let LVGL own the loop.
- In `YoyoPodApp.run()`, the coordinator thread becomes the only place that calls:
  - `lv_tick_inc(delta_ms)`
  - queued LVGL input processing
  - `lv_timer_handler()`
- Keep `PTTInputAdapter` unchanged.
- Add `LvglInputBridge` that maps:
  - `ADVANCE -> LV_KEY_RIGHT`
  - `SELECT -> LV_KEY_ENTER`
  - `BACK -> LV_KEY_ESC`
- Use LVGL groups/encoder navigation for one-button focus order.
- No LVGL calls from polling threads or background callbacks.

### Phase 3: Screen Migration

- Keep current screen classes and route names.
- Each migrated screen becomes a controller with a backend-specific view lifecycle:
  - `build()`
  - `sync()`
  - `destroy()`
- Screen classes do not import raw `lvgl`; only LVGL view classes do.
- Do not build a perfect shared widget API first.
- Migrate in this order:
  1. `HubScreen`
  2. `ListenScreen`
  3. `AskScreen`
  4. `ContactListScreen`
  5. `PlaylistScreen`
  6. `NowPlayingScreen`
  7. `IncomingCallScreen`
  8. `OutgoingCallScreen`
  9. `InCallScreen`
  10. `CallScreen`
  11. `PowerScreen`
- Use LVGL image widgets for the current PNG icons; do not introduce an icon-font system during migration.

### Phase 4: Cutover

- When all Whisplay-target screens are stable, flip `display.whisplay_renderer` default to `lvgl`.
- Remove Whisplay-specific PIL rendering/theme code that is no longer needed.
- Keep Pimoroni and simulation on PIL until a separate follow-up plan.

---

## Public Interfaces / Types

- `display.whisplay_renderer: Literal["pil", "lvgl"]`
- `Display.backend_kind`
- `Display.get_ui_backend()`
- `LvglDisplayBackend`
- `LvglInputBridge`
- `ScreenView` protocol with `build()`, `sync()`, `destroy()`
- Native shim ABI functions for:
  - LVGL init/shutdown
  - display registration + flush callback glue
  - encoder/key indev registration
  - tick/timer pump

---

## Test Plan

- Phase 0 probe on real Whisplay:
  - renders correctly
  - partial flush works
  - survives repeated redraws for 10 minutes
- Binding/bridge tests:
  - init/shutdown
  - partial flush area correctness
  - backend reset on PIL <-> LVGL handoff
- Input tests:
  - `ADVANCE/SELECT/BACK` map correctly to LVGL encoder/key events
  - focus wrap works on one-button screens
- Screen migration tests:
  - `Hub -> Listen -> Playlist -> NowPlaying`
  - incoming call push/pop flow
  - Setup paging
  - in-call live updates
- Hardware acceptance:
  - boots under systemd with LVGL enabled on Whisplay
  - no corruption after 100 transitions
  - no visible missed taps
  - no sustained memory growth during 10 minutes of navigation/call/music activity

---

## Assumptions And Defaults

- CPython remains the app runtime.
- Whisplay is the only LVGL target in this migration.
- The native shim is accepted as part of the product build/deploy story.
- Raw LVGL is treated as a display-layer implementation detail, not a screen-layer dependency.
- No feature work runs in parallel with this migration.
- Current architecture stays intact above the display/UI backend boundary.

---

## References

- LVGL latest release as of 2026-04-05: `v9.5.0`
  - https://github.com/lvgl/lvgl/releases/tag/v9.5.0
- LVGL display flush model
  - https://docs.lvgl.io/9.4/details/main-modules/display/overview.html
- LVGL display setup
  - https://docs.lvgl.io/9.3/details/main-modules/display/setup.html
- LVGL encoder/groups input model
  - https://docs.lvgl.io/master/details/main-modules/indev/encoder.html
  - https://docs.lvgl.io/latest/en/html/details/main-modules/indev/groups.html
- Official MicroPython binding repo
  - https://github.com/lvgl/lv_micropython
