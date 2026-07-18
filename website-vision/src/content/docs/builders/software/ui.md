---
title: UI Engine
description: How shapes and motion reach the canvas.
---

*The UI stack from scene graph to panel, and the one-button interaction model.*

## Overview

One of the four peer engines of the software platform, alongside the
[Media Engine](/builders/software/media-engine/),
[Calling Engine](/builders/software/calling-engine/), and
[Voice & Ask Engine](/builders/software/voice-ask/).
The entire interface lives on one small canvas: a 240×280 RGB565
panel driven over SPI, controlled with a single physical button. The UI
runs as its own binary, `yoyopod-ui-host`, supervised by the runtime over
a line protocol.

Five rules govern everything drawn: three gestures on one button (press =
advance, double-press = open, long-press = Home — "hold to talk" is the
same button remapped per screen); flat chrome (fills and radius, no
borders or shadows); the **wheel** as the only menu primitive; the **arc
hero** as the only player primitive; and voice carries pre-readers —
every focus change speaks the focused label, and no flow may require
reading to complete.

## Key components

| Layer | What it is |
| --- | --- |
| Screens & scene graph | 17 screen modules declaring trees over four primitives — container, label, image, progress — plus composite widgets |
| Engine | the reconciler: diffs each new scene against the old and emits only the mutations that changed, under a hard budget of 60 live widgets |
| Animation | a custom timeline engine (keyframes, easing, presets) — deliberately not LVGL's animation system |
| Renderer | **LVGL 9.5.0, stock upstream, zero patches**, used strictly as a renderer through a hand-written C FFI — no binding crate |
| Input | one GPIO button feeding a Rust gesture state machine; LVGL never sees raw input |
| Driver | a userspace ST7789/Whisplay driver streaming SPI at 100 MHz — there is no kernel display driver at all |

## Interfaces & contracts

- **State in, intents out** — screens render runtime state snapshots and emit intents; screens never perform side effects directly. One-way data flow all the way around the loop.
- **Partial flush** — LVGL renders dirty areas into a single 240×40 draw buffer; the flush callback byte-swaps every RGB565 pixel for the panel and pastes into an in-memory shadow framebuffer; the worker pushes only what is dirty.
- **Deterministic time** — no LVGL OS layer, single-threaded: LVGL time only advances when the UI loop pumps the tick, which keeps rendering deterministic and testable.
- **The one-button grammar** is a contract every screen obeys — the family-facing version is [Using the Button](/families/using-the-button/).

## Today vs. target

- Today: the stack runs on the prototype hardware (Raspberry Pi Zero 2W + PiSugar Whisplay HAT; the ST7789 panel is a 240×280 window into a 240×320 controller).
- Honest flags carried from the as-built docs: the arc-hero progress ring ships as a bar fallback (`lv_arc` is not in the FFI yet); focused-tile scaling is emulated by resize-and-recenter; `set_opacity` is a no-op; only two of the design-system font sizes are usable from Rust today.
- The deep dive — the FFI ledger, the render loop, the tracked gaps — is the as-built UI System Guide in the engineering docs (`website/` in the repository). This page stays the map; that guide stays the territory.

## Open questions

- TODO: does a product-board display change the panel contract (resolution, color depth, refresh)?
- TODO: are the on-device screens fixed for V1, or could Setup fold into the Hub wheel?

:::note[Sources]
Condensed from the as-built docs site (`website/` in the repository): the UI System Guide's overview, LVGL layer, and custom-framework pages.
:::
