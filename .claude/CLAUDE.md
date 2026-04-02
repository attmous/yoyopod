# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

YoyoPod is an iPod-inspired Raspberry Pi application combining SIP calling (VoIP via linphonec) and Mopidy-based music playback behind a small-screen, button-driven UI. Target hardware is Raspberry Pi Zero 2W (416 MB RAM).

Three display/input modes: Pimoroni DisplayHATMini, PiSugar Whisplay, and browser-based simulation.

## Common Commands

```bash
# Run the app
python yoyopod.py              # Production (requires Pi hardware)
python yoyopod.py --simulate   # Simulation mode (browser UI at localhost:5000)

# Tests
pytest
pytest tests/test_fsm_runtime.py
pytest -v

# Code quality
black .
ruff check .
mypy yoyopy/

# Install dev dependencies
pip install -e ".[dev]"
```

## Architecture

```text
yoyopod.py / yoyopy/main.py  (entry points)
        |
    YoyoPodApp (app.py) -- central coordinator
    |- MusicFSM + CallFSM (fsm.py) -- composed playback and call state machines
    |- CoordinatorRuntime (coordinators/runtime.py) -- derived app state
    |- AppContext (app_context.py) -- shared state
    |- MopidyClient (audio/mopidy_client.py) -- Mopidy JSON-RPC
    |- VoIPManager (connectivity/voip_manager.py) -- linphonec subprocess
    |- Display HAL (ui/display/) -- factory pattern, 3 adapters
    |- Input HAL (ui/input/) -- semantic actions, 3 adapters
    `- ScreenManager (ui/screens/manager.py) -- stack-based navigation
```

**Display HAL** (`ui/display/`): `DisplayHAL` interface -> factory -> adapters (pimoroni, whisplay, simulation). Facade via `Display` in `display_manager.py`.

**Input HAL** (`ui/input/`): Semantic actions (SELECT, BACK, UP, DOWN). Adapters: `four_button.py`, `ptt_button.py`, `keyboard.py`. Manager dispatches actions to active screen.

**Screen system** (`ui/screens/`): Base class in `base.py`, stack-based manager in `manager.py`. Feature screens organized in `navigation/`, `music/`, `voip/` subdirectories.

**State orchestration**: `MusicFSM` and `CallFSM` stay independent, while `CoordinatorRuntime` derives combined runtime states such as `PLAYING_WITH_VOIP`, `PAUSED_BY_CALL`, and `CALL_ACTIVE_MUSIC_PAUSED`. Auto-pauses music on incoming calls and auto-resumes after call ends (configurable).

**VoIP**: Wraps `linphonec` CLI subprocess. Parses stdout for call state changes. Linphone 5.x uses case-insensitive patterns, square brackets for SIP addresses (`[sip:user@domain]`), and `"CallSession"` not `"Call"`.

## Configuration

All config in `config/` directory (tracked in repo):
- `yoyopod_config.yaml` -- display hardware, Mopidy host/port, auto-resume
- `voip_config.yaml` -- SIP account, transport, STUN, HA1 hash auth
- `contacts.yaml` -- contact list and speed dial

## Code Style

- Python 3.12+, type hints required on all function definitions
- Black formatting, 100 char line length
- Logging via `loguru` (not stdlib logging)
- Build system: hatchling

## Key Patterns

- Ring tone generated via `speaker-test` subprocess (800Hz on `plughw:1`)
- Screen stack: incoming call pushes screens, `_pop_call_screens()` pops all call screens on hangup to prevent stack overflow
- VoIP monitor thread reads linphonec output continuously; callbacks fire on the coordinator thread for UI updates
- EventBus serializes typed app events on the coordinator thread

## Deploy Workflow

```bash
# Local: commit and push
git push

# RPi: pull and run
ssh rpi-zero "cd yoyo-py && git pull origin main"
ssh rpi-zero "cd yoyo-py && source .venv/bin/activate && python yoyopod.py"
```

Kill stuck processes before restarting (Python caches modules):

```bash
ssh rpi-zero "killall -9 python linphonec"
```

## Current Gaps

- Settings UI is still not implemented
- Hardware-required validation still needs real Pi coverage beyond CI and simulation
