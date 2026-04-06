# CLAUDE.md

Follow all instructions in the `rules/` directory at the repo root:
- `rules/project.md` -- project overview, commands, configuration
- `rules/architecture.md` -- system architecture, HAL layers, state machines
- `rules/code-style.md` -- Python 3.12+, black, ruff, type hints
- `rules/voip.md` -- linphonec integration, SIP patterns
- `rules/lvgl.md` -- LVGL display pipeline, C shim, screenshot support
- `rules/logging.md` -- loguru contract, subsystem tags, PID file
- `rules/deploy.md` -- Pi deploy workflow, rpi-deploy plugin commands

## Claude Code Specific

- Use Bash tool for SSH/SCP commands to the Pi
- Use Read tool to display PNG screenshots (multimodal)
- The rpi-deploy plugin provides `/deploy`, `/sync`, `/logs`, `/restart`, `/pi-status`, `/screenshot` commands
