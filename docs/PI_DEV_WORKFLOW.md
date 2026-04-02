# Raspberry Pi Dev Workflow

This guide gives the day-to-day remote workflow for YoyoPod development once code is already in Git.

## What This Solves

The repo now has a clear hardware smoke path, but developers still need a quick way to:

- sync a branch onto the Raspberry Pi
- inspect remote status
- run the Pi smoke checks
- launch the production app

Use `scripts/pi_remote.py` for that loop.

## Setup

Make sure your dev machine can SSH into the Raspberry Pi with an alias or reachable host name.

Examples:

```bash
ssh rpi-zero
ssh tifo@192.168.1.42
```

Optional environment defaults:

```bash
export YOYOPOD_PI_HOST=rpi-zero
export YOYOPOD_PI_PROJECT_DIR=~/yoyo-py
export YOYOPOD_PI_BRANCH=main
```

On Windows PowerShell:

```powershell
$env:YOYOPOD_PI_HOST="rpi-zero"
$env:YOYOPOD_PI_PROJECT_DIR="~/yoyo-py"
$env:YOYOPOD_PI_BRANCH="main"
```

## Common Commands

### Check remote status

```bash
uv run python scripts/pi_remote.py status
```

Shows:

- remote branch and commit
- dirty working tree state
- Mopidy user-service state
- top memory processes

### Sync branch to the Raspberry Pi

```bash
uv run python scripts/pi_remote.py sync --branch main
```

By default this will:

1. `git fetch origin`
2. `git checkout <branch>`
3. `git pull --ff-only origin <branch>`
4. `uv sync --extra dev`

Skip dependency refresh if you only need the Git update:

```bash
uv run python scripts/pi_remote.py sync --branch main --skip-uv-sync
```

### Run smoke validation remotely

```bash
uv run python scripts/pi_remote.py smoke
uv run python scripts/pi_remote.py smoke --with-mopidy --with-voip
```

Useful variations:

```bash
uv run python scripts/pi_remote.py smoke --with-mopidy --mopidy-timeout 10
uv run python scripts/pi_remote.py smoke --with-voip --voip-timeout 15 --verbose
```

### Launch the production app remotely

```bash
uv run python scripts/pi_remote.py run
```

Pass extra args through when needed:

```bash
uv run python scripts/pi_remote.py run --simulate
uv run python scripts/pi_remote.py run --app-arg=--your-extra-flag
```

## Suggested Daily Loop

1. Run local checks: `uv run pytest -q`
2. Push your branch
3. Sync the target branch to the Raspberry Pi:
   `uv run python scripts/pi_remote.py sync --branch <branch>`
4. Run the hardware smoke pass:
   `uv run python scripts/pi_remote.py smoke --with-mopidy --with-voip`
5. Launch the app:
   `uv run python scripts/pi_remote.py run`

## Release / Pre-Merge Checklist

- Local branch is green with `uv run pytest -q`
- Branch is pushed and reviewed
- Raspberry Pi has the intended branch checked out
- `uv run python scripts/pi_remote.py smoke` passes
- `uv run python scripts/pi_remote.py smoke --with-mopidy --with-voip` passes when services are expected
- `uv run python scripts/pi_remote.py run` starts cleanly
- Manual sanity:
  - display renders correctly
  - input works on target hardware
  - music playback works
  - SIP registration succeeds
  - incoming/outgoing call flow still behaves correctly

## Notes

- `pi_remote.py run` uses an interactive SSH session so you can stop the remote app with `Ctrl+C`.
- The helper does not kill existing remote processes for you. If the Pi already has a stale YoyoPod or `linphonec` process, stop it first.
- For deeper hardware debugging, use `docs/RPI_SMOKE_VALIDATION.md`.
