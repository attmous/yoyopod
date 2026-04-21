# YoyoPod Core

YoyoPod is an iPod-inspired Raspberry Pi application that combines SIP calling, local-first music playback, and a small-screen button UI.

Current product surface:
- `Listen` - local music with `Playlists`, `Recent`, and `Shuffle`, including dashboard-imported device-local tracks
- `Talk` - contact-first calls and voice notes
- `Ask` - staged shell for future safe AI interactions
- `Setup` - power, care, and device status

Approved contacts are now backend-synced policy data:

- the Pi stores mutable people data in `data/people/contacts.yaml`
- backend config sync can merge household-approved contacts into that file
- contacts may carry both `sip_address` and `phone_number`
- calling is currently SIP-first; GSM numbers are stored for later enablement
- a claimed device may bootstrap prestored local contacts to the backend once
  when the backend household contact list is still empty

Supported display/input modes:
- Pimoroni Display HAT Mini: `320x240` landscape with four buttons
- PiSugar Whisplay HAT: `240x280` portrait with a single PTT-style button
- Simulation mode: browser display with keyboard and web-button input

## Call And Music Contract

- Incoming and outgoing call setup both pause local music once when playback is actively running.
- Missed, rejected, failed, cancelled, and completed call teardown only auto-resume music when YoyoPod paused it for that call and `auto_resume_after_call` is enabled.
- Calls that start while music is already paused or idle leave playback unchanged.
- Playback FSM state only flips after the pause or resume command succeeds, so navigation after the call keeps the visible playback truth aligned with the backend.

## Quick Start

Local-only contributor path:

```bash
uv run yoyopod setup host
uv run yoyopod setup verify-host
python yoyopod.py --simulate
uv run python scripts/quality.py ci
```

If you plan to validate on a Raspberry Pi or use GitHub CLI helpers, verify those host prerequisites explicitly before you need them:

```bash
uv run yoyopod setup verify-host --with-remote-tools
uv run yoyopod setup verify-host --with-github
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
- [Canonical Structure](docs/CANONICAL_STRUCTURE.md)
- [Cloud Provisioning And Backend Integration](docs/CLOUD_PROVISIONING_AND_BACKEND.md)

Setup and operations:
- [Setup Contract](docs/SETUP_CONTRACT.md)
- [Quality Gates](docs/QUALITY_GATES.md)
- [Pi Dev Workflow](docs/PI_DEV_WORKFLOW.md)
- [Pi Smoke Validation](docs/RPI_SMOKE_VALIDATION.md)
- [Deployed Pi Dependencies](docs/DEPLOYED_PI_DEPENDENCIES.md)

Subsystem docs:
- [Power Module](docs/POWER_MODULE.md)
- [Audio Stack](docs/AUDIO_STACK.md)
- [Remote Playback](docs/REMOTE_PLAYBACK.md)
- [Local-First Music Plan](docs/LOCAL_FIRST_MUSIC_PLAN.md)
- [mpv Dependencies](docs/MPV_DEPENDENCIES.md)
- [Cloud Provisioning And Backend Integration](docs/CLOUD_PROVISIONING_AND_BACKEND.md)

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
