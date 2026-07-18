---
title: "The Canvas: Display & Input"
description: The small calm screen and the one physical button.
---

*The display panel and the single-button input path.*

## Overview

"The canvas" is the project's shorthand for the panel's visible window —
the surface every shape and animation lands on. The screen is small and
portrait by design: it shows state, it is not the product. Input is one
physical side button, the device's only control. Both live on the PiSugar
Whisplay HAT worn by the Raspberry Pi Zero 2W — an off-the-shelf part of
the V0 “Dawn” rig; the V1 “Daylight” board may ship its own panel and
driver ([From Prototype to Product](/builders/hardware/roadmap/)).

## Key components

The panel is driven by an **ST7789** controller over SPI:

| Property | Value |
| --- | --- |
| Visible resolution | **240 × 280**, portrait |
| Controller addressing | 240 × 320, visible window offset by 20 rows |
| Color format | RGB565 (16 bits per pixel) |
| Interface | SPI0, chip-select 0, 100 MHz, Mode 0 |
| Writes | blocking 4096-byte chunks — no DMA, no GPU |
| Rotation | in-panel via MADCTL, never in software |

The GPIO map: Data/Command on 27, Reset on 4, Backlight on 22, Button on 17
(input with pull-up). The backlight is **active-low and on/off only** —
there is no PWM dimming; any brightness above zero means "on". The power
worker turns it off after inactivity (default 60 seconds). Pins, bus, and
SPI speed are overridable through environment variables for bench setups.

## Interfaces & contracts

There is **no kernel display stack — by choice**: no `/dev/fb0`, no
DRM/KMS, no `fbtft` module. The UI host drives the panel directly from
userspace (GPIO + SPI via the `rppal` crate). One binary owns the canvas —
no kernel driver version drift, no display server, no compositor — and
startup is deterministic: the host either initializes the panel or fails
loudly. The cost: every pixel crosses the CPU, which is why the render
pipeline is aggressive about dirty-region tracking.

The renderer never touches the panel directly; it goes through a
`DisplayDevice` trait with three write paths (full frame, HUD-only region,
dirty region). The second implementation is an in-memory mock, so the full
render pipeline runs on any machine — the physical panel is the only
unmockable part, behind a one-method-swap trait. Button events on GPIO 17
are the input contract. The as-built UI System Guide (`website/` in the
repository) covers the driver in depth: init sequence, window addressing,
and the flush path.

## Today vs. target

Today: the prototype SPI panel on the Whisplay HAT, driven by the existing
userspace driver and LVGL pipeline; the 20-row controller offset is
absorbed in the driver so the rest of the stack sees a clean 240 × 280.
Target: a product board may ship its own display and driver. Fixed by
intent: small, portrait, calm, one button. Open: panel technology,
resolution, and touch.

## Open questions

- TODO: Does the product device get a touch layer, or does one button remain the entire input story?
- TODO: What resolution and panel technology does the product board target, and does 240x280 stay the design canvas?
- TODO: How much of the button-gesture grammar (tap, double-tap, hold) is frozen before more kid testing?
- TODO: Is there a hardware brightness/ambient-light story, or does the backlight stay on/off only?

:::note[Sources]
Condensed from the as-built docs site (`website/` in the repository): the
UI System Guide's hardware page ("The Canvas and the Board") and
display-driver page ("Talking to the Panel").
:::
