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
pytest                                        # All tests
pytest tests/test_phase1_state_machine.py     # Single test file
pytest -v                                     # Verbose

# Code quality
black .                  # Format (100 char line length)
ruff check .             # Lint
mypy yoyopy/             # Type check (strict: disallow_untyped_defs)

# Install dev dependencies
pip install -e ".[dev]"
```

## Architecture

```
yoyopod.py / yoyopy/main.py  (entry points)
        |
    YoyoPodApp (app.py) -- central coordinator
    ├── StateMachine (state_machine.py) -- 16 states, 48 transitions for music+call flows
    ├── AppContext (app_context.py) -- shared state
    ├── MopidyClient (audio/mopidy_client.py) -- Mopidy JSON-RPC
    ├── VoIPManager (connectivity/voip_manager.py) -- linphonec subprocess
    ├── Display HAL (ui/display/) -- factory pattern, 3 adapters
    ├── Input HAL (ui/input/) -- semantic actions, 3 adapters
    └── ScreenManager (ui/screens/manager.py) -- stack-based navigation
```

**Display HAL** (`ui/display/`): `DisplayHAL` interface -> factory -> adapters (pimoroni, whisplay, simulation). Facade via `Display` in `display_manager.py`.

**Input HAL** (`ui/input/`): Semantic actions (SELECT, BACK, UP, DOWN). Adapters: `four_button.py`, `ptt_button.py`, `keyboard.py`. Manager dispatches actions to active screen.

**Screen system** (`ui/screens/`): Base class in `base.py`, stack-based manager in `manager.py`. Feature screens organized in `navigation/`, `music/`, `voip/` subdirectories.

**State machine**: Manages combined music+VoIP states. Key combined states: `PLAYING_WITH_VOIP`, `PAUSED_BY_CALL`, `CALL_ACTIVE_MUSIC_PAUSED`. Auto-pauses music on incoming calls, auto-resumes after call ends (configurable).

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
- VoIP monitor thread reads linphonec output continuously; callbacks fire on main thread for UI updates

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

- Some demos/tests still import removed pre-refactor UI modules
- Screen code partly uses legacy `on_button_*` handlers via compatibility bridge
- Hardware paths (Whisplay driver, audio device) are not fully configurable
