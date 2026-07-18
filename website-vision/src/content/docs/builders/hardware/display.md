---
title: "The Glass: Display & Input"
description: The small calm screen and the one physical button.
---

*The display panel and the single-button input path.*

:::caution[Vision stub]
Placeholder in the vision docs — the structure is decided, the content is
not written yet. As-built engineering docs live in the main docs site
(`website/` in the repository).
:::

## Overview

- Why the screen is deliberately small and calm: it shows state, it is not the product
- The one-button philosophy: tap, double-tap, hold — and hold doubling as push-to-talk
- What the glass shows: the four on-device screens (Hub, Listen, Talk, Setup) and nothing more
- What the glass will never be: a scrolling feed, a browser, an app grid

## Key components

- Prototype panel: roughly 240x280 portrait SPI display on the PiSugar Whisplay HAT
- The single physical side button: the only input path on the device
- Backlight and brightness behavior (product-board control scheme TBD)
- Touch: whether the product screen is touch-capable at all (TBD)

## Interfaces & contracts

- How the panel reaches software: SPI in the prototype; the as-built UI System Guide (in `website/` in the repository) covers the display driver in depth
- The custom LVGL-based UI that renders to the glass — see [UI](/builders/software/ui/)
- Button events as the input contract: tap / double-tap / hold, debounced and interpreted in one place
- What contract a replacement product panel must satisfy so the UI stack survives the swap (TBD)

## Today vs. target

- Today: prototype SPI panel on the Whisplay HAT, driven by the existing LVGL pipeline
- Target: a product board that may ship its own display and its own driver
- Fixed by intent: small, portrait, calm, one button; open: panel technology, resolution, touch (TBD)
- What changes for the UI stack if resolution or aspect ratio shifts (TBD)

## Open questions

- TODO: Does the product device get a touch layer, or does one button remain the entire input story?
- TODO: What resolution and panel technology does the product board target, and does 240x280 stay the design canvas?
- TODO: How much of the button-gesture grammar (tap, double-tap, hold) is frozen before more kid testing?
- TODO: Is there a hardware brightness/ambient-light story, or is brightness purely software-managed?
