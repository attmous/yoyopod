# Deploy Workflow

Applies to: `deploy/pi-deploy.yaml`, deployment and debugging on Raspberry Pi

## Manual Deploy

```bash
# Local: commit and push
git push

# RPi: pull and run
ssh rpi-zero "cd YoyoPod_Core && git pull origin main"
ssh rpi-zero "cd YoyoPod_Core && source .venv/bin/activate && python yoyopod.py"
```

Kill stuck processes before restarting:

```bash
ssh rpi-zero "killall -9 python"
```

## rpi-deploy Plugin

The `rpi-deploy` Claude Code plugin automates the deploy cycle with slash commands. In this repo, prefer `yoyoctl remote` as the executable implementation for these workflows and keep the skills as thin wrappers around it.

| Command | Purpose |
|---|---|
| `/yoyopod-deploy` | Git push, SSH pull, kill, restart, verify |
| `/yoyopod-sync` | Rsync dirty tree (no commit), kill, restart |
| `/yoyopod-logs [N] [--errors] [--filter <sub>]` | Tail app logs from Pi |
| `/yoyopod-restart` | Kill processes and relaunch |
| `/yoyopod-status` | Health check dashboard (connectivity, memory, processes) |
| `/yoyopod-screenshot [--readback]` | Capture display output as PNG |

Config: `deploy/pi-deploy.yaml` plus optional `deploy/pi-deploy.local.yaml` for machine-specific host/user overrides. Preferred edit flow:

```bash
yoyoctl remote config show
yoyoctl remote config edit
```

Plugin repo: https://github.com/moustafattia/rpi-deploy

## Target Hardware

- Raspberry Pi Zero 2W (416 MB RAM)
- SSH host alias: `rpi-zero` (configured in `~/.ssh/config`)
- Project dir on Pi: `/home/pi/YoyoPod_Core`
- Venv on Pi: `/home/pi/YoyoPod_Core/.venv`
