# YoYoPod Whisplay / Simulation Parity Contract

**Last Updated:** 2026-04-22
**Status:** Implemented contract

## Problem Statement

`python yoyopod.py --simulate` is the software-only preview of the current
Whisplay product UI. That preview is only useful if it renders the same layout
contract as hardware instead of drifting behind a second renderer.

## Current Contract

The supported portrait UI has one visual source of truth:

- Whisplay hardware: `240x280`, portrait, LVGL-only
- Simulation: `240x280`, portrait, browser preview of the same Whisplay render path

The browser is transport, not a second layout engine.

That also means simulation requires the native LVGL shim. If the shim is not
available, startup should fail loudly instead of silently reviving a second
renderer. The supported fix is to build the shim first with
`yoyopod build simulation` (or `yoyopod build ensure-native`).

## Implemented Direction

Simulation now reuses the same render contract as hardware:

1. LVGL scenes still own the object tree and layout behavior.
2. The Whisplay adapter mirrors RGB565 flushes into a framebuffer.
3. Browser preview reuses that mirrored framebuffer instead of maintaining a
   second simulation-specific renderer.

This means simulation is its own adapter surface backed by the same LVGL output
contract, not a second renderer.

## Goals

- keep simulation as the primary software-only preview of the current Whisplay UI
- treat Whisplay as the visual source of truth for the product
- remove duplicate layout behavior that can drift between hardware and browser preview
- preserve fast local and Pi-hosted browser preview for development
- keep simulation input ergonomic for developers while matching Whisplay output geometry

## Non-Goals

- emulate SPI timing, LCD refresh artifacts, or backlight latency
- reproduce panel color calibration exactly
- maintain a second renderer just for simulation

## Required Parity Surface

The following remain parity-sensitive for simulation:

- status bar height and icon placement
- hero-card position, size, radius, and padding
- footer copy position
- list item spacing and focus treatment
- Whisplay portrait safe-area assumptions

The first required screen set is still:

- main menu / hub
- Listen
- Talk
- Ask
- Setup
- Voice Commands
- Talk Contact
- Now Playing

## Verification Contract

Parity must be enforced with artifacts, not visual memory.

Required verification layers:

- unit or integration tests for shared geometry/profile values
- screenshot and adapter tests around the RGB565 framebuffer + browser preview path
- Pi-hosted validation using Whisplay screenshots from the live LVGL path

Small anti-aliasing or color differences can be tolerated. Geometry drift should not be.

## File Ownership

- `yoyopod/ui/display/factory.py`
  - owns adapter selection and preview startup
- `yoyopod/ui/display/adapters/whisplay.py`
  - owns Whisplay output behavior
- `yoyopod/ui/display/adapters/simulation.py`
  - owns the simulation adapter surface while reusing the shared LVGL contract
- `yoyopod/ui/display/rgb565.py`
  - owns the framebuffer and PNG encoding helpers used by the adapter
- `yoyopod/ui/display/adapters/simulation_web/server.py`
  - owns browser preview transport only
- `yoyopod/ui/lvgl_binding/`
  - owns the LVGL scene/backend path
- `tests/ui/test_display.py`
- `tests/ui/test_whisplay_adapter.py`

## Acceptance Criteria

- `python yoyopod.py --simulate` shows the same layout geometry as the current
  Whisplay UI for the required parity screens when the native LVGL shim has been built
- simulation no longer relies on a second drifting copy of Whisplay-first
  layout behavior
- the browser preview remains usable both locally and from the Pi IP
- output parity is preserved while simulation input stays developer-friendly
- UI work can use simulation as a trustworthy preview of Whisplay instead of a rough approximation
