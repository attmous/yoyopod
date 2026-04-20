# yoyopod CLI Design

**Date:** 2026-04-10
**Status:** Draft
**Goal:** Replace the 13 loose scripts in `scripts/` with a unified, grouped CLI tool built on typer.

---

## Motivation

The `scripts/` folder has 13 Python files (~3,000 lines) with inconsistent CLI patterns (some argparse, some bare `main()`). They're invoked via `uv run python scripts/foo.py`, which is verbose and hard to remember. The code is hard to navigate and has duplicated patterns across scripts.

`yoyopod` replaces this with a single entry point using typer, organized into logical command groups.

---

## Command Tree

```
yoyopod
├── pi                          # runs ON the Pi
│   ├── smoke                   # from pi_smoke.py
│   ├── tune                    # from whisplay_tune.py
│   ├── gallery                 # from whisplay_gallery.py
│   ├── lvgl
│   │   ├── soak                # from lvgl_soak.py
│   │   └── probe               # from lvgl_probe.py
│   ├── voip
│   │   ├── check               # from check_voip_registration.py
│   │   └── debug               # from debug_incoming_call.py
│   └── power
│       ├── battery             # from pisugar_power.py
│       └── rtc                 # from pisugar_rtc.py (status, sync-to, sync-from, set-alarm, disable-alarm)
├── remote                      # runs FROM dev machine, SSHes to Pi
│   ├── status                  # from pi_remote.py
│   ├── sync                    # from pi_remote.py
│   ├── smoke                   # from pi_remote.py
│   ├── preflight               # from pi_remote.py
│   ├── lvgl-soak               # from pi_remote.py
│   ├── power                   # from pi_remote.py
│   ├── config                  # from pi_remote.py
│   └── service                 # from pi_remote.py
└── build                       # native extension builds
    ├── lvgl                    # from lvgl_build.py
    └── liblinphone             # from liblinphone_build.py
```

### Dropped from CLI

- `generate_test_sounds.py` — run-once utility, not worth a CLI command. Kept as a standalone file at `scripts/generate_test_sounds.py` for occasional manual use.

---

## Package Layout

```
src/yoyopod/cli/
  __init__.py              # root typer app, group wiring
  pi/__init__.py           # pi group app
  pi/smoke.py              # pi smoke test runner
  pi/tune.py               # whisplay gesture tuning
  pi/gallery.py            # whisplay screenshot gallery
  pi/lvgl.py               # lvgl soak + probe commands
  pi/voip.py               # voip check + debug commands
  pi/power.py              # pisugar battery + rtc commands
  remote/__init__.py       # remote group app
  remote/ops.py            # status, sync, smoke, preflight
  remote/infra.py          # config, service, power
  remote/lvgl.py           # lvgl-soak over SSH
  build.py                 # lvgl + liblinphone build commands
```

### Design decisions

- **One module per logical group**, not one module per original script. Related small scripts (e.g. `pisugar_power.py` + `pisugar_rtc.py`) merge into a single module (`power.py`).
- **`pi_remote.py` splits across `remote/`** — it's 500+ lines and has distinct concerns (ops vs infrastructure vs lvgl).
- **Flat commands stay flat** — `smoke`, `tune`, `gallery` don't get subgroups since they're singletons.
- **Subgroups for 2+ related commands** — `lvgl`, `voip`, `power` each have enough commands to justify a subgroup.

---

## Dependency Setup

### pyproject.toml changes

```toml
[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "pytest-cov>=4.1.0",
    "black>=24.0.0",
    "ruff>=0.3.0",
    "mypy>=1.8.0",
    "typer>=0.12.0",
]

[project.scripts]
yoyopod = "yoyopod.main:main"
yoyopod = "yoyopod.main:main"
yoyopod = "yoyopod.cli:app"
```

### Key constraint

`typer` is a dev-only dependency. The `yoyopod` entry point only works when installed with `uv sync --extra dev`. The Pi production environment installs only prod dependencies and never sees typer or the CLI package.

The `src/yoyopod/cli/` package must not be imported by any prod code path (`src/yoyopod/app.py`, `src/yoyopod/main.py`, etc.).

---

## Migration Strategy

### What changes

1. Each script's `main()` logic is refactored into typer command functions — same behavior, new wiring.
2. argparse argument definitions become typer `Option()` / `Argument()` annotations.
3. The `scripts/` folder is deleted after all commands are ported and verified.
4. CLAUDE.md updated: `uv run python scripts/pi_remote.py status --host rpi-zero` becomes `yoyopod remote status --host rpi-zero`.
5. Docs and skill files updated to reference `yoyopod` invocations.

### What stays the same

- All flags, arguments, and defaults preserved exactly.
- Runtime behavior unchanged — this is a structural refactor.
- `yoyopod` and `yoyopod` console entry points untouched.
- No changes to any production code paths.

### Verification

- Every original script invocation documented in CLAUDE.md must work identically via `yoyopod`.
- `uv run pytest -q` continues to pass.
- `python -m compileall yoyopod` continues to pass.
- `yoyopod --help` shows the full command tree with descriptions.
- Each leaf command's `--help` matches the original script's argument documentation.

---

## Example Usage (before → after)

```bash
# Before
uv run python scripts/pi_remote.py status --host rpi-zero
uv run python scripts/pi_smoke.py --with-music --with-voip
uv run python scripts/pisugar_power.py --verbose
uv run python scripts/pisugar_rtc.py status
uv run python scripts/lvgl_soak.py --cycles 5 --simulate
uv run python scripts/check_voip_registration.py
uv run python scripts/lvgl_build.py --skip-fetch

# After
yoyopod remote status --host rpi-zero
yoyopod pi smoke --with-music --with-voip
yoyopod pi power battery --verbose
yoyopod pi power rtc status
yoyopod pi lvgl soak --cycles 5 --simulate
yoyopod pi voip check
yoyopod build lvgl --skip-fetch
```

---

## Scope Boundaries

### In scope

- Structural refactor of all 13 scripts (minus `generate_test_sounds.py`) into `src/yoyopod/cli/`.
- typer wiring and entry point registration.
- pyproject.toml dependency changes.
- CLAUDE.md and docs updates.
- Deletion of `scripts/` folder.

### Out of scope

- Changing any runtime behavior or flags.
- Touching production code paths.
- Adding new commands or features.
- Changing the main app entry points (`yoyopod`, `yoyopod`).
