# Rust Static Hub UI - Design Spec

## Problem

The Rust Whisplay UI PoC already proves basic output, one-button input, Python
supervision, ARM CI build, and hardware execution. The next migration risk is
whether a real YoYoPod screen can cross the Python-to-Rust boundary without
inventing a second UI contract.

The first screen should be static Hub because it is the root screen, is small
enough to validate quickly, and already has a narrow LVGL sync surface in
Python.

## Goal

Render the Hub screen from the Rust Whisplay sidecar using the same view-model
field names that the current Python `LvglHubView.sync()` sends into the native
LVGL shim.

This creates the seed contract for the next step, where Python can send live
Hub snapshots into Rust while Python still owns the app runtime.

## Non-Goals

- Do not replace the production Python LVGL runtime.
- Do not port the screen manager.
- Do not add browser simulation.
- Do not support Pimoroni or four-button hardware.
- Do not move app state, VoIP, music, power, or network into Rust.
- Do not add live Python runtime sync in this step.

## Scope

Only the Rust Whisplay sidecar is changed. It gains one new command:

```json
{"kind":"command","type":"ui.show_hub","payload":{...}}
```

An empty payload renders a deterministic static Hub snapshot. A full payload
uses the exact current Hub sync field names:

- `icon_key`
- `title`
- `subtitle`
- `footer`
- `time_text`
- `accent`
- `selected_index`
- `total_cards`
- `voip_state`
- `battery_percent`
- `charging`
- `power_available`

The command may also carry `renderer` with `auto`, `lvgl`, or `framebuffer`.
That field is a sidecar execution option, not part of the Hub view-model.

## Architecture

```text
Python CLI / later Python runtime sync
        |
        | ui.show_hub HubSnapshot JSON
        v
Rust Whisplay sidecar
        |
        |- HubSnapshot parser with Python LVGL field names
        |- Hub renderer
        |  |- auto: use current native LVGL shim when available
        |  `- framebuffer fallback for host tests and missing shim
        |
        `- existing Whisplay full-frame flush
```

The first LVGL path may dynamically load the existing native YoYoPod LVGL shim.
That is intentionally a bridge, not the final Rust-owned LVGL architecture. It
lets the sidecar validate real LVGL Hub pixels on hardware while the Rust
contract and worker protocol are established.

## Runtime Behavior

`ui.show_hub` parses a `HubSnapshot`, renders one full frame, flushes it through
the existing Rust display device, increments the normal frame counter, and
records the last Hub renderer in `ui.health`.

Renderer handling:

- `renderer="lvgl"` requires the native LVGL shim and fails explicitly if it
  cannot be loaded.
- `renderer="framebuffer"` uses a deterministic Rust framebuffer drawing.
- `renderer="auto"` tries LVGL first and falls back to framebuffer rendering.

The fallback renderer exists to keep host tests and CI independent from native
LVGL availability. Hardware validation should force `renderer="lvgl"` once the
native shim is built on the Pi.

## Validation

Host validation:

- Rust tests cover Hub snapshot defaults and field parsing.
- Rust worker tests cover `ui.show_hub` using framebuffer rendering.
- Python tests cover the static Hub payload contract and CLI command envelope.
- Existing worker contract tests continue to pass.

Pi validation:

```bash
yoyopod pi rust-ui-poc --screen hub --hub-renderer lvgl --frames 1
```

Success criteria:

- Rust sidecar emits `ui.ready`.
- The command renders one Hub frame.
- `ui.health` reports `frames=1` and `last_hub_renderer=lvgl`.
- The app service can be restored after the sidecar releases hardware.

## Follow-Up

After this step passes on hardware, the next migration step is live Python Hub
sync: Python builds the same `HubSnapshot` from `HubScreen` and sends it to the
Rust sidecar on screen changes. The Python app runtime still owns screen state
at that point.
