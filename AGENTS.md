# YoYoPod - Agent Instructions

Last Updated: 2026-04-22
Target Hardware: Raspberry Pi Zero 2W
Project: iPod-inspired VoIP + local music device with small-screen button UI

Purpose
- Keep this file small. It is the always-loaded agent brief, not a dump of the whole codebase.
- For detail, read the referenced docs instead of stuffing more into this file.

Guidance order
1. Current code in `yoyopod/`
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
- `docs/SLOT_DEPLOY.md` (slot-deploy + OTA-ready flow; coexists with the legacy skills above)

Current runtime summary
- Entrypoint: `yoyopod.py` -> `yoyopod.main` -> `YoyoPodApp`
- Main packages: `yoyopod/core/`, `yoyopod/integrations/`, `yoyopod/backends/`, `yoyopod/ui/`, `yoyopod/config/`
- Runtime structure: canonical `YoyoPodApp` in `yoyopod/core/application.py`, boot in `yoyopod/core/bootstrap/`, loop in `yoyopod/core/loop.py`, and the shared `scheduler -> bus -> ui` runtime seam under `yoyopod/core/`
- Production audio: mpv backend under `yoyopod/backends/music/`
- Production VoIP: Liblinphone under `yoyopod/backends/voip/`
- Production LVGL path: `yoyopod/ui/lvgl_binding/`
- Production service templates: `deploy/systemd/`
- CLI package: `yoyopod_cli/` (flat, single `yoyopod` entry point)

Source-of-truth files
- `yoyopod/core/application.py`
- `yoyopod/core/bootstrap/`
- `yoyopod/core/loop.py`
- `yoyopod/core/bus.py`
- `yoyopod/core/scheduler.py`
- `yoyopod/core/events.py`
- `yoyopod/core/app_state.py`
- `yoyopod/integrations/`
- `yoyopod/backends/`
- `yoyopod/ui/`
- `yoyopod_cli/main.py`
- `yoyopod_cli/COMMANDS.md`
- `README.md`
- `docs/SYSTEM_ARCHITECTURE.md`
- `docs/POWER_MODULE.md`
- `docs/LVGL_MIGRATION_PLAN.md`
- `docs/LOCAL_FIRST_MUSIC_PLAN.md`

High-value commands
- Install/test env: `uv sync --extra dev`
- Tests: `uv run pytest -q`
- **CI quality gate (run before every commit + push):** `uv run python scripts/quality.py gate`
- **CI test suite (run before every commit + push):** `uv run pytest -q`
- Pi smoke: `yoyopod pi validate smoke`
- Remote operations: `yoyopod remote ...`
- Full command reference: `yoyopod_cli/COMMANDS.md` (auto-generated; regenerate via `yoyopod dev docs`)

Pre-commit rule
- Before every `git commit` (including `--amend`) and every `git push`, run BOTH commands above. They mirror exactly what CI runs in `.github/workflows/ci.yml` — the `quality` job runs `scripts/quality.py gate` (black + ruff + mypy on gate paths, no pytest), and the `test` job runs `pytest -q` (full suite).
- Per-file pytest/ruff runs are NOT enough. CI gates format + lint + type + full test suite across the paths in `[tool.yoyopod_quality]`, and rendering/behavior can differ between local terminals and Linux CI (terminal width, color, `COLUMNS` env).
- Windows note: CI is Linux-only. A handful of tests have known Windows-specific failures (faulthandler, native shim loading, Windows-path/font behavior) that are green on Linux. If you're on Windows and see failures, diff them against the latest green main CI run — flag only NEW failures.
- When dispatching implementer subagents, include "run `uv run python scripts/quality.py gate && uv run pytest -q` before the final commit step" as an explicit requirement.

Hardware modes
- Pimoroni Display HAT Mini: landscape + four buttons on the shared LVGL path
- PiSugar Whisplay: portrait + single button
- Simulation: shared LVGL browser preview + keyboard/web-button input

Guardrails
- Prefer narrow, reviewable changes.
- Keep raw LVGL confined to `yoyopod/ui/lvgl_binding/` and display-layer code.
- Prefer `yoyopod remote` over ad-hoc SSH sequences.
- Current code and runtime docs beat old plan docs when they disagree.
- `docs/archive/` is history, not truth.

If you need more than this file gives you, read the referenced rules/docs instead of expanding this file again.
