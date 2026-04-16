# Development Guide

This guide holds the operational detail that does not belong on the repo landing page.

If you are new here, read these first:

1. [`../README.md`](../README.md)
2. [`README.md`](README.md)
3. [`CONTRIBUTOR_WORKFLOW.md`](CONTRIBUTOR_WORKFLOW.md)
4. [`SYSTEM_ARCHITECTURE.md`](SYSTEM_ARCHITECTURE.md)

## Source of truth

For current behavior, trust:
- current code in `src/yoyopod/`
- this guide for setup and workflow
- [`SYSTEM_ARCHITECTURE.md`](SYSTEM_ARCHITECTURE.md) for runtime topology
- [`../AGENTS.md`](../AGENTS.md) and `rules/` for repo guidance

Treat plan docs and checklists as supporting context unless they explicitly state they are current.

## Python Environment

```bash
uv run yoyoctl setup host
uv run yoyoctl setup verify-host
```

These commands define the baseline executable setup contract. They do not yet
cover non-apt assets like Vosk models or every board/modem-specific setup edge.

## System Dependencies

The current repo-owned setup contract lives in [`SETUP_CONTRACT.md`](SETUP_CONTRACT.md).

Short version:

Core Raspberry Pi packages and services expected by the active stack:

- `mpv`
- `ffmpeg`
- `liblinphone-dev`
- `pkg-config`
- `cmake`
- `alsa-utils`
- `i2c-tools`
- `pisugar-server` on PiSugar-based targets

Feature-gated extras are documented there too, including:

- `espeak-ng` for the current TTS path
- `ppp` for the modem PPP path
- Vosk model files under `models/`

Example:

```bash
uv run yoyoctl setup pi
uv run yoyoctl setup verify-pi
```

Treat those commands as the baseline package/build verifier, not proof that all
feature assets and hardware-specific setup are complete.

For PiSugar-based hardware, make sure `pisugar-server` is installed and running too.

## Configuration

Tracked config files live under `config/`:

- `config/yoyopod_config.yaml`
- `config/voip_config.yaml`
- `config/liblinphone_factory.conf`
- `config/contacts.yaml`

Key settings:

- `config/yoyopod_config.yaml`
  - `display.*` hardware and renderer selection
  - `audio.music_dir`
  - `audio.mpv_socket`
  - `audio.mpv_binary`
  - `audio.alsa_device`
  - `audio.default_volume`
  - `input.whisplay_*_ms`
  - `power.*`
  - `logging.*`
- `config/voip_config.yaml`
  - SIP account, transport, STUN, Liblinphone messaging and media config
- `config/contacts.yaml`
  - contact list and speed-dial style entries

## Running

Production app:

```bash
python yoyopod.py
```

Simulation:

```bash
python yoyopod.py --simulate
```

Installed console entrypoint:

```bash
yoyopod
```

Useful demos:

```bash
python demos/demo_voip.py --simulate
python demos/demo_playlists.py
python demos/demo_runtime_state.py --simulate
```

## Validation

Local validation:

```bash
uv run python scripts/quality.py ci
```

Optional extra syntax/import smoke for broad tree changes:

```bash
python -m compileall yoyopod tests demos scripts
```

Full quality audit of the current repo debt:

```bash
uv run python scripts/quality.py audit
```

The staged gate contract and exact target set live in [`QUALITY_GATES.md`](QUALITY_GATES.md).

Target-side validation suite:

```bash
yoyoctl pi validate deploy
yoyoctl pi validate smoke
yoyoctl pi validate smoke --with-power --with-rtc
yoyoctl pi validate music
yoyoctl pi validate voip
yoyoctl pi validate stability
```

## Raspberry Pi Workflow

Preferred remote helper:

```bash
yoyoctl remote config show
uv run yoyoctl remote setup
uv run yoyoctl remote verify-setup
yoyoctl remote status
git branch --show-current
git rev-parse HEAD
yoyoctl remote validate --branch <branch> --sha <commit> --with-music --with-voip --with-lvgl-soak
yoyoctl remote preflight --branch <branch> --with-music --with-voip --with-lvgl-soak
yoyoctl remote service status
yoyoctl remote logs --lines 200
```

That remote flow mirrors the same baseline contract. You still need feature-specific
follow-through for assets like Vosk models and for unusual board/modem bringup.

The detailed deploy and validation flows live in:

- `docs/PI_DEV_WORKFLOW.md`
- `docs/RPI_SMOKE_VALIDATION.md`
- `rules/deploy.md`

## Logging

The app writes:

- `logs/yoyopod.log`
- `logs/yoyopod_errors.log`

Pi deploy defaults live in:

- `deploy/pi-deploy.yaml`
- `deploy/pi-deploy.local.yaml` for gitignored machine-local overrides

Useful remote log commands:

```bash
yoyoctl remote logs --lines 200
yoyoctl remote logs --errors
yoyoctl remote logs --filter voip
yoyoctl remote logs --follow --filter ERROR
```

## Package Layout

```text
src/yoyopod/
  app.py
  main.py
  fsm.py
  app_context.py
  coordinators/
  runtime/
    boot.py
    loop.py
    recovery.py
    screen_power.py
    shutdown.py
    models.py
  cli/
    setup.py
    remote/
      setup.py
      ops.py
      infra.py
      lvgl.py
  audio/
    history.py
    local_service.py
    volume.py
    music/
      backend.py
      ipc.py
      models.py
      process.py
  config/
    manager.py
    models.py
  voip/
    backend.py
    history.py
    manager.py
    models.py
  ui/
    display/
    input/
    lvgl_binding/
    screens/
    web_server.py
scripts/
  quality.py
sitecustomize.py
```

## Current Active Docs

Start with [`README.md`](README.md) for the full docs map.

Current contributor, runtime, and setup docs:
- `docs/CONTRIBUTOR_WORKFLOW.md`
- `docs/QUALITY_GATES.md`
- `docs/SETUP_CONTRACT.md`
- `docs/SYSTEM_ARCHITECTURE.md`
- `docs/POWER_MODULE.md`
- `docs/LOCAL_FIRST_MUSIC_PLAN.md`
- `docs/MPV_DEPENDENCIES.md`
- `docs/PI_DEV_WORKFLOW.md`
- `docs/RPI_SMOKE_VALIDATION.md`

Plan and migration docs can still be useful, but they are not automatically the source of truth.

Historical milestone notes are archived under `docs/archive/`.
