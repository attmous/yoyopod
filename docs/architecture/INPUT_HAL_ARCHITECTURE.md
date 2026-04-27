# YoYoPod Input HAL Architecture

**Last updated:** 2026-04-15
**Status:** Implemented

This document describes the input abstraction layer that now exists in the UI package.

## Goals

- route semantic user actions instead of raw hardware buttons
- support multiple input sources
- decouple screen navigation from specific input devices
- keep simulation and hardware modes on the same action model

## Current Files

- `yoyopod/ui/input/hal.py`: `InputAction` and `InputHAL`
- `yoyopod/ui/input/manager.py`: action dispatcher
- `yoyopod/ui/input/factory.py`: adapter selection
- `yoyopod/ui/input/adapters/four_button.py`
- `yoyopod/ui/input/adapters/ptt_button.py`
- `yoyopod/ui/input/adapters/keyboard.py`

## Core Semantic Actions

- navigation: `SELECT`, `BACK`, `UP`, `DOWN`, `LEFT`, `RIGHT`, `MENU`, `HOME`
- playback: `PLAY_PAUSE`, `NEXT_TRACK`, `PREV_TRACK`, `VOLUME_UP`, `VOLUME_DOWN`
- VoIP: `CALL_ANSWER`, `CALL_REJECT`, `CALL_HANGUP`
- PTT: `PTT_PRESS`, `PTT_RELEASE`
- voice: `VOICE_COMMAND`

## Adapter Mapping

### PTTInputAdapter

- button press and release emit `PTT_PRESS` and `PTT_RELEASE`
- optional click patterns can emit `SELECT` and `BACK`
- this is the canonical runtime path for Whisplay hardware

### FourButtonInputAdapter

- button layout emits `SELECT`, `BACK`, `UP`, and `DOWN`
- used by the Pimoroni display path when the corresponding GPIO/display helpers are available

### KeyboardInputAdapter

Used in simulation mode:

- `Enter` or `Space -> SELECT`
- `Esc` or `Backspace -> BACK`
- `Up` or `K -> UP`
- `Down` or `J -> DOWN`

Simulation also wires browser button input onto the same semantic actions.

The current product runtime keeps three input surfaces alive: Whisplay
single-button hardware, Pimoroni four-button hardware, and simulation keyboard
/ browser input.

## How ScreenManager Uses It

`ScreenManager` connects semantic actions to the current screen when screens change.

This is the current call path:

```text
input adapter -> InputManager -> ScreenManager -> current screen handler
```

## Screen Contract

Current behavior:

- `ScreenManager` registers semantic callbacks
- `Screen` defines semantic methods like `on_select()`, `on_back()`, `on_up()`, and `on_down()`
- concrete screens implement those semantic handlers directly

Legacy `on_button_*()` compatibility methods have been removed from `Screen`.

## Known Gaps

- some older demos and tests still import deleted pre-HAL input modules
- `keyboard.py` still has small naming drift between `get_supported_actions()` and the manager's `get_capabilities()` convention

## Summary

The input HAL is real and in use today. Screen input is now fully semantic end to end.
