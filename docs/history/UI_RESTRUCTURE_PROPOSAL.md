# YoYoPod UI Refactor Status

**Last updated:** 2026-04-02
**Status:** Historical implementation record, mostly implemented

> Current note: this file records the UI refactor milestone and what it accomplished. It is useful for historical context and remaining cleanup notes, but it is not the top-level source of truth for the current runtime shape. For current behavior, trust `docs/architecture/SYSTEM_ARCHITECTURE.md`, UI subsystem docs, and the current code under `yoyopod/ui/`.

This document replaces the old proposal-only version and records what the refactor actually accomplished.

## Refactor Goals

- split the monolithic UI package into focused modules
- introduce display and input HALs
- move screen navigation logic into the screens package
- reduce the cost of working on one screen or adapter at a time

## Current Structure

```text
yoyopod/ui/
  __init__.py
  web_server.py
  display/
    __init__.py
    hal.py
    factory.py
    manager.py
    adapters/
      pimoroni.py
      simulation.py
      whisplay.py
  input/
    __init__.py
    hal.py
    factory.py
    manager.py
    adapters/
      four_button.py
      keyboard.py
      ptt_button.py
  screens/
    __init__.py
    base.py
    manager.py
    navigation/
    music/
    voip/
```

## Phase Status

### Phase 1: Display module restructure

Status: done

- display code moved under `yoyopod/ui/display/`
- facade, factory, and adapters are separate files

### Phase 2: Screen split

Status: done

- `screens.py` was split by feature area
- `screen_manager.py` became `yoyopod/ui/screens/manager.py`

### Phase 3: Semantic input migration

Status: partial

- semantic input infrastructure exists
- `ScreenManager` dispatches semantic actions
- concrete screens still mostly implement legacy `on_button_*()` methods

### Phase 4: Cleanup and documentation

Status: partial

- obsolete core files were removed
- docs, demos, and tests were not fully updated at the same time

## What Still Needs Cleanup

- migrate concrete screens from `on_button_*()` to semantic handlers
- update demos to use `yoyopod.ui.input` and `yoyopod.ui.screens.manager`
- update tests that still target removed modules
- remove small compatibility leftovers after migration is complete

## Why The Refactor Was Worth It

- display and input are no longer hardwired into the rest of the app
- screens are easier to navigate and maintain
- simulation mode can share the same screen code and action model
- adding a new adapter no longer requires editing a monolithic UI file
