# Setup and System Dependency Contract

This document defines the baseline repo-owned setup and verification contract for YoyoPod Core.

Issue [`#87`](https://github.com/moustafattia/YoyoPod_Core/issues/87) is the work that turned this from wishful docs into executable commands. This file documents the contract those commands implement.

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

Current repo-owned bootstrap baseline:

```bash
uv run yoyoctl setup host
```

This is the executable baseline, not full setup ownership. It does not provision
non-apt assets like Vosk models or cover every board-specific edge.

Current repo-owned validation baseline:

```bash
uv run yoyoctl setup verify-host
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

Current repo-owned bootstrap baseline:

```bash
uv run yoyoctl setup pi
```

This bootstraps the baseline package/build contract only. It does not yet solve
Vosk model provisioning, board/modem permissions, or non-Debian portability.

Feature extras are opt-in:

- `yoyoctl setup pi --with-voice`
- `yoyoctl setup pi --with-network`
- `yoyoctl setup pi --with-pisugar`

Current repo-owned verification baseline:

```bash
uv run yoyoctl setup verify-pi
```

This verifies presence and basic build state. It does not perform deeper
artifact health checks for every native/runtime dependency.

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

### Local developer bringup baseline

```bash
uv run yoyoctl setup host
uv run yoyoctl setup verify-host
python yoyopod.py --simulate
uv run pytest -q
```

This is the minimum executable contract for contributors. Feature assets and
hardware-specific extras still need follow-through when the feature requires them.

### Target Pi bringup baseline

```bash
uv run yoyoctl setup pi
uv run yoyoctl setup verify-pi
yoyoctl pi validate deploy
yoyoctl pi validate smoke
yoyoctl pi validate smoke --with-power --with-rtc
uv run python yoyopod.py
```

This does not yet provision non-apt assets such as Vosk models or encode every
board/modem-specific permission step.

### Remote Pi workflow baseline

```bash
yoyoctl remote config show
uv run yoyoctl remote setup
uv run yoyoctl remote verify-setup
yoyoctl remote status
yoyoctl remote sync --branch main
yoyoctl remote smoke --with-music --with-voip
yoyoctl remote service status
```

These remote helpers mirror the same baseline contract. They still rely on
feature-specific follow-up for assets and unusual hardware bringup.

## Verification before blaming product code

Before treating a failure as an app bug, verify the setup layer first.

Checklist:

- local bootstrap completes with `uv run yoyoctl setup host`
- local verification passes with `uv run yoyoctl setup verify-host`
- tracked config files are present under `config/`
- required system packages are verified with `uv run yoyoctl setup verify-pi`
- native shims have been built when the feature requires them
- `yoyoctl pi validate smoke` passes for the requested hardware path
- remote config values come from `deploy/pi-deploy.yaml` plus local overrides, not tribal knowledge

## Current gaps

This repo is still missing some setup hardening that a foundation-grade repo should have:

- provisioning of non-apt assets such as Vosk model downloads under `models/`
- board- and modem-specific device-permission setup for every bringup variant
- portability beyond the current Debian-based Raspberry Pi package flow

The contract is now executable, but those remaining edges are still real.
