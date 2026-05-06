# YoYoPod Display HAL Architecture

**Last updated:** 2026-04-22
**Status:** Current implementation

This document describes the live Rust-owned display path used by the LVGL-only
runtime.

## Goals

- keep screen code hardware-agnostic
- use one render contract for both hardware and simulation
- avoid duplicate preview-only layout engines

## Current Files

- `device/ui/src/main.rs`: Rust UI host entrypoint
- `device/ui/src/worker.rs`: worker protocol loop
- `device/ui/src/render/`: framebuffer and LVGL render path
- `device/ui/src/lvgl/`: native LVGL scene backend and screen controllers
- `device/ui/native/lvgl/`: C LVGL shim used by the Rust build

## Architecture

```text
yoyopod-runtime
  -> yoyopod-ui-host worker
     -> Rust scene state
        -> native LVGL scene backend
        -> hardware flush path or preview/readback support
```

## Supported Runtime Surfaces

### Whisplay hardware

- `240x280`
- portrait
- PiSugar Whisplay HAT
- LVGL-only production path

### Pimoroni / ST7789 hardware

- `320x240`
- landscape
- LVGL-backed adapter over ST7789 SPI plus GPIO control

### Preview

The Rust UI host can run in mock hardware mode for protocol and render smoke
checks. The production hardware path remains Whisplay-focused.

## Production Contract

- Non-simulated Whisplay runs require `display.whisplay_renderer=lvgl`.
- If the Whisplay driver, board init, or LVGL backend is unavailable, startup fails loudly.
- There is no supported PIL renderer or alternate production display backend in the current runtime.

## Summary

The display HAL is implemented and frozen around LVGL-backed Whisplay, Pimoroni,
and simulation adapter surfaces.
