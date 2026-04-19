# YoyoPod - Agent Instructions

Last Updated: 2026-04-19
Target Hardware: Raspberry Pi Zero 2W
Project: iPod-inspired VoIP + local music device with small-screen button UI

Purpose
- Keep this file small. It is the always-loaded agent brief, not a dump of the whole codebase.
- For detail, read the referenced docs instead of stuffing more into this file.

Guidance order
1. Current code in `src/yoyopod/`
2. `README.md` and `docs/README.md`
3. `rules/` for constraints and style
4. This file for quick operating context
5. `skills/` for deploy/debug playbooks
6. `.claude/` and `.agents/` as tool-facing mirrors

Read these rules first
- `rules/project.md`
- `rules/architecture.md`
- `rules/code-style.md`
- `rules/design-fidelity.md`
- `rules/voip.md`
- `rules/lvgl.md`
- `rules/logging.md`
- `rules/deploy.md`

Canonical deploy/debug skills
- `skills/yoyopod-deploy/SKILL.md`
- `skills/yoyopod-sync/SKILL.md`
- `skills/yoyopod-logs/SKILL.md`
- `skills/yoyopod-restart/SKILL.md`
- `skills/yoyopod-status/SKILL.md`
- `skills/yoyopod-screenshot/SKILL.md`

Current runtime summary
- Entrypoint: `yoyopod.py` -> `yoyopy.main` -> `YoyoPodApp`
- Main packages: `yoyopy/audio/`, `voip/`, `power/`, `ui/`, `coordinators/`
- Runtime structure: split `MusicFSM` + `CallFSM`, typed `EventBus`, coordinator-driven app state
- Production audio: mpv backend under `yoyopy/audio/music/`
- Production VoIP: Liblinphone under `yoyopy/voip/liblinphone_binding/`
- Production LVGL path: `yoyopy/ui/lvgl_binding/`
- Production service templates: `deploy/systemd/`

Source-of-truth files
- `yoyopy/app.py`
- `yoyopy/fsm.py`
- `yoyopy/event_bus.py`
- `yoyopy/events.py`
- `yoyopy/coordinators/runtime.py`
- `README.md`
- `docs/SYSTEM_ARCHITECTURE.md`
- `docs/POWER_MODULE.md`
- `docs/LVGL_MIGRATION_PLAN.md`
- `docs/LOCAL_FIRST_MUSIC_PLAN.md`

High-value commands
- Install/test env: `uv sync --extra dev`
- Tests: `uv run pytest -q`
- Pi smoke: `yoyoctl pi smoke`
- Remote operations: `yoyoctl remote ...`

Hardware modes
- Pimoroni Display HAT Mini: landscape + four buttons
- PiSugar Whisplay: portrait + single button
- Simulation: browser-rendered display + keyboard/web input

Guardrails
- Prefer narrow, reviewable changes.
- Keep raw LVGL confined to `yoyopy/ui/lvgl_binding/` and display-layer code.
- Prefer `yoyoctl remote` over ad-hoc SSH sequences.
- Current code and runtime docs beat old plan docs when they disagree.
- `docs/archive/` is history, not truth.

If you need more than this file gives you, read the referenced rules/docs instead of expanding this file again.
