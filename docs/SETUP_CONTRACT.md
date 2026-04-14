# Setup and System Dependency Contract

This document defines what setup is supposed to be repo-owned in YoyoPod Core.

Issue [`#87`](https://github.com/moustafattia/YoyoPod_Core/issues/87) tracks turning this into a fully scripted setup flow. Until then, this file is the source of truth for what must be documented, tracked, and eventually automated.

## Why this exists

The repo already owns a lot of runtime behavior, but setup still has too much implicit machine knowledge.

That is a foundation risk.

For this repo to be the real base of the system, a contributor should be able to answer these questions from the repo itself:

- what Python and system dependencies are required
- which dependencies are core vs feature-gated
- which files are repo-owned vs machine-local
- how to bring up a dev machine
- how to bring up a target Pi
- how to verify the setup before debugging product code

## Setup ownership rules

The repo should own:

- the Python dependency graph in `pyproject.toml`
- the shared Pi deploy contract in `deploy/pi-deploy.yaml`
- the tracked app config in `config/`
- the documented system dependency list in this file
- the validation commands in `docs/DEVELOPMENT_GUIDE.md` and `docs/RPI_SMOKE_VALIDATION.md`
- the remote workflow exposed through `yoyoctl remote`

Machine-local values should stay out of tracked files.

Examples of machine-local state:

- Pi hostname or SSH alias
- Pi username
- machine-specific overrides in `deploy/pi-deploy.local.yaml`
- secrets and account credentials
- local audio paths or removable-media contents

## Supported setup surfaces

### 1. CI-safe developer machine

Minimum expectation:

- Python `3.12+`
- `uv`
- Git

Current repo-owned bootstrap:

```bash
uv sync --extra dev
```

Current repo-owned validation baseline:

```bash
uv run pytest -q
```

Optional but expected for Pi workflows:

- `ssh`
- `rsync`

Optional but useful for repo operations:

- `gh`

### 2. Target Raspberry Pi runtime

Current core system packages and services expected by the active stack:

- `mpv`
- `ffmpeg`
- `liblinphone-dev`
- `pkg-config`
- `cmake`
- `alsa-utils`
- `i2c-tools`
- `pisugar-server` running on PiSugar-based targets

Current manual install shape:

```bash
sudo apt install -y mpv ffmpeg liblinphone-dev pkg-config cmake alsa-utils i2c-tools
```

For PiSugar-based hardware, make sure `pisugar-server` is installed and running as a system service.

Then build the native pieces the repo expects:

```bash
yoyoctl build liblinphone
yoyoctl build lvgl
```

### 3. Feature-gated or hardware-specific extras

These are not universal for every contributor machine, but the repo should still name them explicitly when a feature depends on them.

#### Voice path

- `espeak-ng` for the current TTS backend
- Vosk model files under `models/`

#### Cellular / GPS path

- `ppp` for the modem PPP data path
- board- and modem-specific serial/device access

#### Board bringup variants

See:

- `docs/CUBIE_A7Z_BRINGUP.md`
- `docs/CUBIE_A7Z_PIMORONI_SETUP.md`

## Repo-owned configuration contract

Tracked config lives in:

- `config/yoyopod_config.yaml`
- `config/voip_config.yaml`
- `config/liblinphone_factory.conf`
- `config/contacts.yaml`
- `deploy/pi-deploy.yaml`

Gitignored local overrides belong in:

- `deploy/pi-deploy.local.yaml`

The tracked deploy contract must stay generic:

- no personal hostnames
- no personal usernames
- no secrets
- no machine-specific absolute paths unless they are intended defaults

## Current bringup contract

### Local developer bringup

```bash
uv sync --extra dev
python yoyopod.py --simulate
uv run pytest -q
```

### Target Pi bringup

```bash
sudo apt install -y mpv ffmpeg liblinphone-dev pkg-config cmake alsa-utils i2c-tools
uv sync --extra dev
yoyoctl build liblinphone
yoyoctl build lvgl
yoyoctl pi smoke
yoyoctl pi smoke --with-power --with-rtc
uv run python yoyopod.py
```

### Remote Pi workflow

```bash
yoyoctl remote config show
yoyoctl remote status
yoyoctl remote sync --branch main
yoyoctl remote smoke --with-music --with-voip
yoyoctl remote service status
```

## Verification before blaming product code

Before treating a failure as an app bug, verify the setup layer first.

Checklist:

- Python deps install cleanly with `uv sync --extra dev`
- tracked config files are present under `config/`
- required system packages are installed on the target Pi
- native shims have been built when the feature requires them
- `yoyoctl pi smoke` passes for the requested hardware path
- remote config values come from `deploy/pi-deploy.yaml` plus local overrides, not tribal knowledge

## Current gaps

This repo is still missing some setup hardening that a foundation-grade repo should have:

- one canonical bootstrap command for host setup
- one canonical bootstrap command for target Pi setup
- an executable verifier for required system packages and native artifacts
- CI enforcement for the broader quality commands the team expects locally
- a cleaner split between core-required and optional feature packages in executable setup flows

That is the remaining work in issue `#87`.

This document is here so the contract is explicit before the scripts are finished.
