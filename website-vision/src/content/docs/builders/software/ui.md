---
title: UI System
description: How shapes and motion reach the glass.
---

*The UI stack from scene graph to panel, and the one-button interaction model.*

:::caution[Vision stub]
Placeholder in the vision docs — the structure is decided, the content is
not written yet. As-built engineering docs live in the main docs site
(`website/` in the repository).
:::

## Overview

- One small calm screen — "the glass", roughly 240x280 portrait — and everything drawn on it
- The stack in one breath: scene graph down to panel, on a custom LVGL-based stack
- The four on-device screens: Hub (the home wheel), Listen, Talk, Setup
- One physical side button as the entire input surface

## Key components

- Scene graph and renderer on the custom LVGL-based stack
- Router between the four screens
- Animation layer: how motion is described and reaches the glass
- Input layer: tap, double-tap, hold — with hold doubling as push-to-talk

## Interfaces & contracts

- How screens receive state from the runtime workers (outline; detail TBD)
- The one-button grammar as a contract every screen must obey — the family-facing version is [Using the Button](/families/using-the-button/)
- What the panel contract promises the stack: resolution, orientation, refresh (TBD for a product board)
- Where screen definitions end and shared runtime state begins (TBD)

## Today vs. target

- Today: the custom LVGL-based stack runs on the prototype hardware (Raspberry Pi Zero 2W + PiSugar Whisplay HAT)
- The deep dive is the as-built UI System Guide in the engineering docs (`website/` in the repository)
- Target: the same stack on a product board with its own display (TBD)
- This page stays the map; the as-built guide stays the territory

## Open questions

- TODO: does a product-board display change the panel contract (resolution, color depth, refresh)?
- TODO: how much scene-graph internals belong here vs. in the as-built guide?
- TODO: are the four screens fixed for V1, or could Setup fold into the Hub wheel?
