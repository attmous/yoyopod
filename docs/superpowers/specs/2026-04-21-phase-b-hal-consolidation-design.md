# Phase B — HAL Consolidation — Design

**Date:** 2026-04-21
**Owner:** Moustafa
**Status:** Awaiting review
**Follows:** Phase A (`docs/superpowers/specs/2026-04-21-phase-a-spine-rewrite-design.md`)
**Note:** Renumbered from Phase C; the original Phase B (runtime services cleanup) was absorbed into Phase A.

---

## 1. Goals

After Phase A, the `src/yoyopod/core/` + `integrations/` + `backends/` architecture is in place. Display and input hardware is still reached through the pre-Phase-A HAL:

- `src/yoyopod/ui/display/` — facade + factory + adapters (Pimoroni, Whisplay/LVGL, Simulation)
- `src/yoyopod/ui/input/` — manager + factory + adapters (FourButton, PTT, Keyboard)
- `src/yoyopod/ui/lvgl_binding/` — native LVGL C shim + cffi binding + backend bridge + input bridge

These HALs predate the Phase A pattern and exhibit three maintainability smells:

1. **Four-to-five-level abstraction stack per HAL.** Display: facade → factory → adapter → (optional LVGL bridge → LVGL backend → C shim). Reading "how does a pixel end up on screen" requires tracing five files. Same magnitude for input.
2. **Abstraction mismatch.** The facade interface is tuned for Pimoroni-style PIL rendering; the Whisplay adapter is forced to translate PIL calls into LVGL which is designed around its own retained-mode widget tree. The translation happens inside the adapter and leaks across the abstraction.
3. **Hardware-adjacent services are scattered.** Display, input, power (Phase A kept it as an integration), network (same), audio-device routing live in separate packages with their own patterns. No single consistent "this is how hardware is wired" story.

Phase B reshapes display and input HALs to the Phase A pattern — backends under `src/yoyopod/backends/`, thin integrations under `src/yoyopod/integrations/` — and evaluates whether the OVOS-style PHAL consolidation (all hardware behind one `hardware` service) is worth adopting.

**Success criteria:**

- Display pipeline traceable top-to-bottom in ≤3 hops on both PIL and LVGL paths.
- Input pipeline traceable top-to-bottom in ≤3 hops.
- LVGL binding confined to one adapter — other code never `import`s raw LVGL types.
- Display + input backend swap still controlled by the same `YOYOPOD_DISPLAY` / `YOYOPOD_WHISPLAY_DRIVER` env vars as today (no user-visible regression).
- No `ui/display/factory.py` or `ui/input/factory.py` indirection — backends constructed inside each integration's `setup()`.
- Consolidation decision made: either adopt a single `hardware` integration (OVOS PHAL-style) or keep per-device integrations (display + input as separate integrations).

---

## 2. Scope

**In scope:**

- Restructure `src/yoyopod/ui/display/` into:
  - `src/yoyopod/backends/display/` — adapter implementations (Pimoroni, Whisplay/LVGL, Simulation).
  - `src/yoyopod/integrations/display/` — `setup(app)` that picks the right adapter based on config/env, exposes display primitives to screens via `app.display` handle.
- Restructure `src/yoyopod/ui/input/` into:
  - `src/yoyopod/backends/input/` — adapter implementations (FourButton, PTT, Keyboard).
  - `src/yoyopod/integrations/input/` — `setup(app)` that constructs the right adapter, publishes `UserActivityEvent` + typed domain events for each input.
- Evaluate and implement (or explicitly skip) the OVOS PHAL-style `hardware` integration that consolidates display + input (+ optionally some backends from Phase A integrations) behind a single unified API.
- Decide whether `src/yoyopod/ui/lvgl_binding/` should stay as-is, be relocated, or be absorbed into `backends/display/whisplay/`. Target: LVGL raw types appear in only one file.
- Rewrite the display facade interface to match how LVGL actually wants to be used (retained widget tree + dirty-region invalidation), with the PIL adapters implementing the same API via an internal PIL→widget-tree translator.
- Update all 17 screens to consume the new display API in one sweep (or confirm compatibility if the API stays similar).
- Delete stale code: `ui/display/factory.py`, `ui/input/factory.py`, and any facade/factory/adapter boilerplate that no longer pays for itself.

**Out of scope:**

- Changing the rendering output (screens look the same on both Pimoroni and Whisplay).
- New display adapters or new input modes.
- Rewriting Phase A integrations beyond wiring adjustments.

---

## 3. Current state analysis

(Brief — full detail in the audit that led to Phase A spec §1.)

**Display HAL layers:**
1. `src/yoyopod/ui/display/__init__.py` — public surface
2. `src/yoyopod/ui/display/facade.py` — `Display` class that screens hold
3. `src/yoyopod/ui/display/factory.py` — selects adapter based on env/config
4. `src/yoyopod/ui/display/contracts.py` — abstract interface
5. `src/yoyopod/ui/display/adapters/pimoroni.py` / `whisplay.py` / `simulation.py`
6. (For Whisplay) `src/yoyopod/ui/lvgl_binding/backend.py` + `binding.py` + native shim

**Input HAL layers:**
1. `src/yoyopod/ui/input/manager.py` — InputManager
2. `src/yoyopod/ui/input/factory.py` — selects adapter
3. `src/yoyopod/ui/input/contracts.py` — abstract interface
4. `src/yoyopod/ui/input/adapters/four_button.py` / `ptt.py` / `keyboard.py`

**Smells captured in §1.** Most egregious is the LVGL cross-cutting: `ui/lvgl_binding/` holds LVGL types, but `ui/display/adapters/whisplay.py` calls into it, and `app.py` historically also poked at the LVGL backend directly (`_pump_lvgl_backend`). In the Phase A rewrite, that pump logic moves into the display integration's ui_tick callback.

---

## 4. Target architecture

### 4.1 Display integration + backends

```
src/yoyopod/
├── backends/display/
│   ├── __init__.py
│   ├── pimoroni.py       # Display-HAT-Mini adapter (PIL rendering)
│   ├── whisplay.py       # Whisplay adapter (LVGL retained-mode widget tree)
│   ├── simulation.py     # pygame-backed preview for dev
│   └── lvgl/
│       ├── __init__.py
│       ├── binding.py    # cffi binding to the native shim (moved from ui/lvgl_binding/)
│       └── native_shim/  # C source (moved)
└── integrations/display/
    ├── __init__.py       # setup(app): pick adapter by env, bind app.display, register ui_tick
    ├── commands.py       # RefreshCommand, CaptureScreenshotCommand, SetBrightnessOverrideCommand
    └── api.py            # Common display API all screens use (DrawContext-like)
```

- Screens hold `self.app` and call into `app.display.render(canvas)` / `app.display.capture_screenshot()` / `app.display.invalidate_region(rect)`.
- `app.display` is an object with the canonical API — its implementation is the backend adapter.
- The display integration's `ui_tick_callback` (registered in `core/app_shell.YoyoPodApp._ui_tick_callback`) calls the backend's `tick()` — PIL adapters do nothing here; LVGL adapter pumps the native LVGL loop.

### 4.2 Input integration + backends

```
src/yoyopod/
├── backends/input/
│   ├── __init__.py
│   ├── four_button.py    # Pimoroni 4-button GPIO reader
│   ├── ptt.py            # Whisplay push-to-talk single button
│   └── keyboard.py       # Dev-mode keyboard input
└── integrations/input/
    ├── __init__.py       # setup(app): pick adapter by env, register reader thread, bind
    ├── events.py         # ButtonPressedEvent, ButtonLongPressEvent, PttHeldEvent, PttReleasedEvent
    └── commands.py       # (few — maybe SimulateButtonCommand for tests)
```

- Input adapter runs a reader thread; on events, `scheduler.run_on_main(lambda: app.bus.publish(…))`.
- Every input also triggers `app.bus.publish(UserActivityEvent(action_name=…))` for the screen integration.

### 4.3 LVGL isolation

LVGL types (from cffi binding) appear only inside `backends/display/lvgl/` and `backends/display/whisplay.py`. No other file imports LVGL directly. Screens never know LVGL exists.

### 4.4 OVOS PHAL-style `hardware` integration — DECIDED: DO NOT ADOPT

Evaluated during this plan's brainstorming. Conclusion: consolidating display + input + (possibly) power + network behind a single `hardware` service adds a layer without removing any. OVOS's PHAL wins come from their message-bus transport between processes; YoyoPod is single-process so the benefit evaporates.

Keep display and input as separate integrations. The consistency comes from using the Phase A pattern (backend + integration + setup), not from jamming everything behind one API.

---

## 5. Fate of existing classes

| Class / module | Fate |
|---|---|
| `src/yoyopod/ui/display/facade.py` `Display` class | Rewritten as the adapter-common API (in `backends/display/api.py` or similar) |
| `src/yoyopod/ui/display/factory.py` | **Delete.** Adapter selection moves into `integrations/display/__init__.py`'s `setup()` |
| `src/yoyopod/ui/display/contracts.py` | Fold into the common API definition |
| `src/yoyopod/ui/display/adapters/pimoroni.py` | Move to `backends/display/pimoroni.py` |
| `src/yoyopod/ui/display/adapters/whisplay.py` | Move to `backends/display/whisplay.py`, simplified now that LVGL imports are local |
| `src/yoyopod/ui/display/adapters/simulation.py` | Move to `backends/display/simulation.py` |
| `src/yoyopod/ui/lvgl_binding/*` | Move under `backends/display/lvgl/` |
| `src/yoyopod/ui/input/manager.py` `InputManager` | Logic absorbed into `integrations/input/__init__.py` |
| `src/yoyopod/ui/input/factory.py` | **Delete.** Adapter selection in `integrations/input/__init__.py` |
| `src/yoyopod/ui/input/contracts.py` | Fold into the common API definition |
| `src/yoyopod/ui/input/adapters/*` | Move to `backends/input/*` |
| `app._pump_lvgl_backend` / `app._tick_ui` hook | Wired via the display integration's `setup()` that sets `app._ui_tick_callback` |

Net result: `src/yoyopod/ui/` holds only `screens/` — the rendering/input HAL moves entirely to `backends/` + `integrations/`.

---

## 6. Migration strategy

Two or three plans — M-BigBang on `arch/phase-b-hal-consolidation` branch.

1. **Plan B1: Display migration.** Move adapters + LVGL binding. Create `integrations/display/`. Update screens to consume `app.display`. Delete old `ui/display/`.
2. **Plan B2: Input migration.** Move adapters. Create `integrations/input/`. Update screen event wiring. Delete old `ui/input/`.
3. **Plan B3 (optional): LVGL adapter internal cleanup.** If Plan B1 reveals the Whisplay adapter needs further splitting, do it here. Often unnecessary.

Each plan lands on the Phase-B branch; one merge to main when all green.

---

## 7. Testing strategy

- Unit tests for each adapter in isolation (mock hardware where possible).
- Integration tests for display integration (ensures `app.display` is wired up, `ui_tick` is called, backend receives the canvas, etc.).
- Integration tests for input (simulate GPIO events, assert `ButtonPressedEvent` on the bus).
- End-to-end on Pi:
  - Whisplay: `yoyopod pi validate smoke` on real hardware.
  - Simulation: `python yoyopod.py --simulate` launches and renders home screen.
- Visual regression: `yoyopod pi screenshot` captures output; compare against a small baseline set of reference PNGs.

TDD cadence is kept throughout.

---

## 8. Pre-merge gate

Same structure as Phase A:

- `uv run python scripts/quality.py ci` green.
- `yoyopod pi validate deploy` green.
- `yoyopod pi validate smoke` green.
- `yoyopod pi validate lvgl-soak` green.
- Manual on-Pi: home screen renders correctly on Whisplay; all button events register; simulation mode renders in a browser.
- No raw LVGL imports outside `backends/display/lvgl/` and `backends/display/whisplay.py`.

---

## 9. Risks

1. **LVGL native shim portability.** Moving the native source under `backends/display/lvgl/native_shim/` may require updating the build script (`yoyopod build lvgl`). Mitigation: Plan B1 Task 1 validates the build works from the new location before moving on.
2. **Whisplay driver specifics.** The Whisplay adapter embeds hardware knowledge (screen size, rotation, backlight control). Ensure these don't leak into the common display API; keep them inside the Whisplay backend.
3. **Input timing during migration.** The reader thread model must remain (button debouncing, long-press detection). Moving it into `backends/input/*` doesn't change the threading, but assertions about event ordering need re-testing.

---

## 10. Definition of done

- `src/yoyopod/backends/display/`, `src/yoyopod/backends/input/` populated.
- `src/yoyopod/integrations/display/`, `src/yoyopod/integrations/input/` populated and registered in `src/yoyopod/app.py`'s integration list.
- `src/yoyopod/ui/display/` and `src/yoyopod/ui/input/` deleted.
- `src/yoyopod/ui/lvgl_binding/` absorbed under `backends/display/lvgl/`.
- All screens still render correctly on all three display adapters.
- Pre-merge gate green on Pi.
- This spec marked `Status: Implemented`.

---

*End of design spec.*
