# YoyoPod Core

YoyoPod is an iPod-inspired Raspberry Pi application that combines SIP calling, local-first music playback, and a small-screen button UI.

Current product surface:
- `Listen` - local-only music with `Playlists`, `Recent`, and `Shuffle`
- `Talk` - contact-first calls and voice notes
- `Ask` - staged shell for future safe AI interactions
- `Setup` - power, care, and device status

Supported display/input modes:
- Pimoroni Display HAT Mini: `320x240` landscape with four buttons
- PiSugar Whisplay HAT: `240x280` portrait with a single PTT-style button
- Simulation mode: browser display with keyboard and web-button input

## Quick Start

```bash
uv run yoyoctl setup host
uv run yoyoctl setup verify-host
python yoyopod.py --simulate
uv run python scripts/quality.py ci
yoyoctl pi validate smoke
```

For the full setup, validation, and Pi workflow, start with:
- [`docs/README.md`](docs/README.md)
- [`docs/CONTRIBUTOR_WORKFLOW.md`](docs/CONTRIBUTOR_WORKFLOW.md)
- [`docs/DEVELOPMENT_GUIDE.md`](docs/DEVELOPMENT_GUIDE.md)
- [`docs/SETUP_CONTRACT.md`](docs/SETUP_CONTRACT.md)

The current setup commands define a baseline executable contract, not a fully
solved setup story. Non-apt assets like Vosk models and board/modem-specific
bringup still need explicit follow-through.

Run on hardware:

```bash
python yoyopod.py
```

Board-specific hardware defaults can live in `config/boards/<board>/`.
Known boards currently include `rpi-zero-2w` and `radxa-cubie-a7z`, and
the app auto-selects those on matching hardware. You can also force one:

```bash
YOYOPOD_CONFIG_BOARD=radxa-cubie-a7z python yoyopod.py
YOYOPOD_CONFIG_BOARD=rpi-zero-2w python yoyopod.py
```

## Docs

Start here:
- [Documentation Guide](docs/README.md)
- [Contributor Workflow](docs/CONTRIBUTOR_WORKFLOW.md)
- [Development Guide](docs/DEVELOPMENT_GUIDE.md)
- [System Architecture](docs/SYSTEM_ARCHITECTURE.md)

Setup and operations:
- [Setup Contract](docs/SETUP_CONTRACT.md)
- [Quality Gates](docs/QUALITY_GATES.md)
- [Pi Dev Workflow](docs/PI_DEV_WORKFLOW.md)
- [Pi Smoke Validation](docs/RPI_SMOKE_VALIDATION.md)
- [Deployed Pi Dependencies](docs/DEPLOYED_PI_DEPENDENCIES.md)

Subsystem docs:
- [Power Module](docs/POWER_MODULE.md)
- [Audio Stack](docs/AUDIO_STACK.md)
- [Local-First Music Plan](docs/LOCAL_FIRST_MUSIC_PLAN.md)
- [mpv Dependencies](docs/MPV_DEPENDENCIES.md)

Design and migration notes:
- [LVGL Migration Plan](docs/LVGL_MIGRATION_PLAN.md)

Historical milestone notes are kept under [docs/archive](docs/archive). See [docs/README.md](docs/README.md) for the full docs map and source-of-truth guidance.

## Rules

- [Project](rules/project.md)
- [Architecture](rules/architecture.md)
- [Deploy](rules/deploy.md)
- [Logging](rules/logging.md)
- [LVGL](rules/lvgl.md)
- [VoIP](rules/voip.md)
- [Code Style](rules/code-style.md)
