# Cross-Screen Overlay Contract

**Last updated:** 2026-04-25  
**Status:** active design contract for runtime overlay refactors

## Problem

YoYoPod has multiple UI concerns that can appear regardless of the current route
(power alerts, call state, future HUD/toast flows), but runtime ownership has
historically been split across:

- ad-hoc `ScreenManager` helper methods
- route-stack push/pop side effects
- one-off rendering hooks in the coordinator loop

That coupling makes cross-screen behavior hard to extend and forces new concerns
to either duplicate rendering in many screens or add more bespoke manager APIs.

## Overlay Runtime Contract

Cross-screen concerns should implement one shared contract:

1. Long-lived instance: created once at boot by its owning subsystem.
2. Pure activation check: `is_active(now: float) -> bool` decides visibility
   without mutating overlay-owned state.
3. Rendering hook: `render(now: float) -> None`.
4. Deactivation hook: `on_deactivate(now: float) -> None` owns idempotent
   cleanup that may run while an overlay is not the active winner.
5. Ordering: each overlay provides `priority: int`; higher values render first.
6. Runtime ownership: overlays are registered in a shared overlay runtime that
   evaluates overlays once per coordinator tick, stops at the first active
   overlay, and renders only that winner.

## Loop Placement

Overlay evaluation/rendering runs during LVGL pump in `RuntimeLoopService`,
between deferred navigation refresh and `backend.pump(delta_ms)`.

This keeps overlay rendering in the same frame pipeline as screen refreshes and
avoids standalone special-cases in the outer coordinator iteration.

## Lifecycle Expectations

- Overlay owners subscribe to bus/domain events as needed and update their own
  internal state.
- Overlays must be self-deactivating: once the condition is gone,
  `is_active()` returns `False` and the runtime naturally stops rendering it.
- Inactive cleanup belongs in `on_deactivate()`, not in `is_active()`.

## Current Migration Plan

1. Phase 1 (this change): power overlay moved to the shared overlay contract
   while preserving behavior.
2. Phase 2: move call-presenter UI concerns to overlay implementations and
   remove call-specific `ScreenManager` helpers.
3. Phase 3: onboard new cross-screen concerns (volume HUD, voice feedback,
   network degradation indicator) onto the same contract.
