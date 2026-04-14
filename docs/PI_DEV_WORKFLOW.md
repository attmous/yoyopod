# Raspberry Pi Dev Workflow

This guide gives the day-to-day remote workflow for YoyoPod development once code is already in Git.

## What This Solves

The repo now has a clear hardware smoke path, but developers still need a quick way to:

- sync a branch onto the Raspberry Pi
- inspect remote status
- run one combined preflight before manual app startup
- run the Pi smoke checks
- launch the production app
- install and inspect the production systemd unit
- tail the structured file logs with subsystem/error filtering

Use `yoyoctl remote` for that loop.

## Setup

Make sure your dev machine can SSH into the Raspberry Pi with an alias or reachable host name.

The repo-tracked deploy contract lives in `deploy/pi-deploy.yaml`.

- keep `host` and `user` blank there
- put your real machine-specific values in `deploy/pi-deploy.local.yaml`
- create or update that file with:

```bash
yoyoctl remote config edit
```

Examples:

```bash
ssh rpi-zero
ssh tifo@192.168.1.42
```

Optional environment defaults:

```bash
export YOYOPOD_PI_HOST=rpi-zero
export YOYOPOD_PI_PROJECT_DIR=~/YoyoPod_Core
export YOYOPOD_PI_BRANCH=main
```

On Windows PowerShell:

```powershell
$env:YOYOPOD_PI_HOST="rpi-zero"
$env:YOYOPOD_PI_PROJECT_DIR="~/YoyoPod_Core"
$env:YOYOPOD_PI_BRANCH="main"
```

## Common Commands

### Check remote status

```bash
yoyoctl remote status
```

Shows:

- remote branch and commit
- dirty working tree state
- music backend process state
- tracked PID file state
- latest startup marker from the file log
- top memory processes

### Sync branch to the Raspberry Pi

```bash
yoyoctl remote sync --branch main
```

By default this will:

1. `git fetch origin`
2. `git checkout <branch>`
3. `git pull --ff-only origin <branch>`
4. `uv sync --extra dev`

Skip dependency refresh if you only need the Git update:

```bash
yoyoctl remote sync --branch main --skip-uv-sync
```

### Run smoke validation remotely

```bash
yoyoctl remote smoke
yoyoctl remote smoke --with-power --with-rtc
yoyoctl remote smoke --with-music --with-voip --with-rtc
yoyoctl remote smoke --with-lvgl-soak
```

Useful variations:

```bash
yoyoctl remote smoke --with-music --music-timeout 10
yoyoctl remote smoke --with-voip --voip-timeout 15 --verbose
```

### Run Whisplay gesture tuning remotely

```bash
yoyoctl remote whisplay
yoyoctl remote whisplay --duration-seconds 45 --double-tap-ms 240 --long-hold-ms 900
```

### Run the LVGL Whisplay soak remotely

```bash
yoyoctl remote lvgl-soak
yoyoctl remote lvgl-soak --cycles 3 --hold-seconds 0.3
```

Use this when you want a focused hardware-in-the-loop pass for:

- repeated LVGL screen transitions
- sleep/wake recovery
- Whisplay-only rendering regressions

### PiSugar RTC helpers

```bash
yoyoctl remote rtc status
yoyoctl remote rtc sync-to
```

### PiSugar power helper

```bash
yoyoctl remote power
```

Use this when you want a focused battery, charging, and watchdog snapshot without the full smoke pass.

### Production systemd service

```bash
yoyoctl remote service status
yoyoctl remote service install
yoyoctl remote service restart
yoyoctl remote service logs --lines 150
```

This installs `deploy/systemd/yoyopod@.service` onto the Pi as `yoyopod@<remote-user>.service`, enables it at boot, and keeps the app paired with the PiSugar watchdog recovery loop. `service install`, `start`, and `restart` now wait for the file-log startup marker and verify that it matches the PID file before returning success.
The install step also records the merged `project_dir` in `/etc/default/yoyopod`, so the service keeps following your configured checkout path after the repo rename.

### Structured file logs

```bash
yoyoctl remote logs --lines 200
yoyoctl remote logs --errors
yoyoctl remote logs --filter voip
yoyoctl remote logs --follow --filter ERROR
```

This tails the file sinks declared in `deploy/pi-deploy.yaml`, which is the stable Pi contract for:

- `<project-dir>/logs/yoyopod.log`
- `<project-dir>/logs/yoyopod_errors.log`
- `/tmp/yoyopod.pid`

Use this during on-device tuning when the Whisplay button feels too eager or too sluggish. The helper runs interactively over SSH, prints every semantic gesture event, and accepts temporary timing overrides without modifying the tracked config file.

Liblinphone note:

- keep `config/liblinphone_factory.conf` tracked and synced with the branch when debugging outbound-call negotiation on the Pi
- if registration works but calls fail during setup, compare the active branch's factory config before changing SIP credentials

### Run the full preflight in one command

```bash
yoyoctl remote preflight --branch main --with-music --with-voip --with-lvgl-soak
```

What it does:

1. runs local `compileall`
2. runs local `uv run pytest -q`
3. syncs the chosen branch to the Raspberry Pi
4. runs the Raspberry Pi smoke pass

Useful variations:

```bash
yoyoctl remote preflight --branch main --skip-local
yoyoctl remote preflight --branch main --skip-sync --with-voip
yoyoctl remote preflight --branch main --skip-uv-sync --with-music --with-voip
```

### Restart the production app remotely

```bash
yoyoctl remote restart
```

## Suggested Daily Loop

1. Run local checks: `uv run pytest -q`
2. Push your branch
3. Run the combined preflight:
   `yoyoctl remote preflight --branch <branch> --with-music --with-voip --with-lvgl-soak`
4. Launch the app:
   `yoyoctl remote restart`

If you are validating the production boot path rather than an interactive SSH run, use:

5. `yoyoctl remote service restart`
6. `yoyoctl remote service status`

## Release / Pre-Merge Checklist

- Local branch is green with `uv run pytest -q`
- Branch is pushed and reviewed
- `yoyoctl remote preflight --branch <branch> --with-music --with-voip --with-lvgl-soak` passes
- `yoyoctl remote restart` starts cleanly
- Manual sanity:
  - display renders correctly
  - input works on target hardware
  - music playback works
  - SIP registration succeeds
  - incoming/outgoing call flow still behaves correctly

## Notes

- `pi_remote.py run` uses an interactive SSH session so you can stop the remote app with `Ctrl+C`.
- `pi_remote.py preflight` is intentionally non-interactive. It validates but does not launch the app.
- `pi_remote.py service install` expects passwordless `sudo` or an interactive sudo policy on the Pi.
- The helper does not kill existing remote processes for you. If the Pi already has a stale YoyoPod process, stop it first.
- For deeper hardware debugging, use `docs/RPI_SMOKE_VALIDATION.md`.
