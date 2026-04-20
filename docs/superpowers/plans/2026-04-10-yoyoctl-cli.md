# yoyopod CLI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate 12 scripts from `scripts/` into a unified `yoyopod` CLI built on typer, organized into `pi`, `remote`, and `build` command groups.

**Architecture:** A `src/yoyopod/cli/` subpackage with one module per command group. Root app in `__init__.py` wires subgroups via `app.add_typer()`. Shared logging/config helpers extracted into a common module. typer is a dev-only dependency.

**Tech Stack:** typer>=0.12.0, loguru (existing), pathlib (existing)

**Spec:** `docs/superpowers/specs/2026-04-10-yoyopod-cli-design.md`

---

### Task 1: Scaffold CLI package and entry point

**Files:**
- Create: `src/yoyopod/cli/__init__.py`
- Create: `src/yoyopod/cli/common.py`
- Modify: `pyproject.toml:36-47`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write the failing test**

```python
"""tests/test_cli.py — yoyopod CLI smoke tests."""

from typer.testing import CliRunner

from yoyopod.cli import app

runner = CliRunner()


def test_root_help():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "pi" in result.output
    assert "remote" in result.output
    assert "build" in result.output


def test_pi_help():
    result = runner.invoke(app, ["pi", "--help"])
    assert result.exit_code == 0


def test_remote_help():
    result = runner.invoke(app, ["remote", "--help"])
    assert result.exit_code == 0


def test_build_help():
    result = runner.invoke(app, ["build", "--help"])
    assert result.exit_code == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'yoyopod.cli'`

- [ ] **Step 3: Add typer to dev dependencies**

In `pyproject.toml`, add `typer>=0.12.0` to the dev extras:

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
```

Add the `yoyopod` entry point:

```toml
[project.scripts]
yoyopod = "yoyopod.main:main"
yoyopod = "yoyopod.main:main"
yoyopod = "yoyopod.cli:run"
```

Run: `uv sync --extra dev`

- [ ] **Step 4: Create the shared helpers module**

All scripts share a `configure_logging(verbose)` pattern and a config-dir resolution pattern. Extract these into `src/yoyopod/cli/common.py`:

```python
"""src/yoyopod/cli/common.py — shared CLI helpers."""

from __future__ import annotations

import sys
from pathlib import Path

from loguru import logger


REPO_ROOT = Path(__file__).resolve().parents[2]


def configure_logging(verbose: bool) -> None:
    """Configure loguru for CLI commands."""
    logger.remove()
    level = "DEBUG" if verbose else "INFO"
    logger.add(sys.stderr, level=level, format="{time:HH:mm:ss} | {level:<7} | {message}")


def resolve_config_dir(config_dir: str) -> Path:
    """Resolve config directory relative to repo root."""
    p = Path(config_dir)
    if not p.is_absolute():
        p = REPO_ROOT / p
    return p
```

- [ ] **Step 5: Create the root CLI app with empty subgroups**

```python
"""src/yoyopod/cli/__init__.py — yoyopod root application."""

from __future__ import annotations

import typer

app = typer.Typer(
    name="yoyopod",
    help="YoyoPod development and hardware CLI.",
    no_args_is_help=True,
)

# -- pi group (on-device commands) -----------------------------------------
pi_app = typer.Typer(name="pi", help="Commands that run ON the Raspberry Pi.", no_args_is_help=True)
app.add_typer(pi_app)

# -- remote group (SSH wrapper commands) ------------------------------------
remote_app = typer.Typer(name="remote", help="Commands that SSH to the Raspberry Pi from the dev machine.", no_args_is_help=True)
app.add_typer(remote_app)

# -- build group (native extension builds) ----------------------------------
build_app = typer.Typer(name="build", help="Build native C extensions.", no_args_is_help=True)
app.add_typer(build_app)


def run() -> None:
    """Entry point for the yoyopod console script."""
    app()
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_cli.py -v`
Expected: All 4 tests PASS

- [ ] **Step 7: Verify compileall**

Run: `python -m compileall src/yoyopod/cli`
Expected: No errors

- [ ] **Step 8: Commit**

```bash
git add src/yoyopod/cli/__init__.py src/yoyopod/cli/common.py tests/test_cli.py pyproject.toml
git commit -m "feat(cli): scaffold yoyopod with pi/remote/build groups"
```

---

### Task 2: Port build commands (lvgl_build + liblinphone_build)

**Files:**
- Create: `src/yoyopod/cli/build.py`
- Modify: `src/yoyopod/cli/__init__.py`
- Test: `tests/test_cli.py`
- Source: `scripts/lvgl_build.py`, `scripts/liblinphone_build.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_cli.py`:

```python
def test_build_lvgl_help():
    result = runner.invoke(app, ["build", "lvgl", "--help"])
    assert result.exit_code == 0
    assert "--source-dir" in result.output
    assert "--build-dir" in result.output
    assert "--skip-fetch" in result.output


def test_build_liblinphone_help():
    result = runner.invoke(app, ["build", "liblinphone", "--help"])
    assert result.exit_code == 0
    assert "--build-dir" in result.output
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cli.py::test_build_lvgl_help tests/test_cli.py::test_build_liblinphone_help -v`
Expected: FAIL

- [ ] **Step 3: Create build module**

Create `src/yoyopod/cli/build.py`. Move the logic from `scripts/lvgl_build.py` and `scripts/liblinphone_build.py` into typer commands. Preserve all arguments with their exact types and defaults:

```python
"""src/yoyopod/cli/build.py — native extension build commands."""

from __future__ import annotations

from pathlib import Path

import typer

from yoyopod.cli.common import REPO_ROOT, configure_logging

build_app = typer.Typer(name="build", help="Build native C extensions.", no_args_is_help=True)


@build_app.command()
def lvgl(
    source_dir: Path = typer.Option(
        None,
        help="LVGL source directory. Defaults to cache location.",
    ),
    build_dir: Path = typer.Option(
        None,
        help="Build output directory. Defaults to native/ in repo.",
    ),
    skip_fetch: bool = typer.Option(False, "--skip-fetch", help="Skip fetching LVGL sources."),
) -> None:
    """Build the LVGL C extension."""
    # Import and delegate to the existing build logic from scripts/lvgl_build.py.
    # Move the body of scripts/lvgl_build.py main() here, replacing argparse
    # references with the typer parameters above.
    # Use REPO_ROOT for default path resolution.
    configure_logging(verbose=False)
    from scripts.lvgl_build import _fetch_sources, _configure, _build  # refactor: inline the logic

    # The actual implementation should inline the subprocess calls from
    # scripts/lvgl_build.py rather than importing from scripts/.
    # Copy the ~60 lines of build logic directly into this function.
    raise typer.Exit(0)


@build_app.command()
def liblinphone(
    build_dir: Path = typer.Option(
        None,
        help="Build output directory.",
    ),
) -> None:
    """Build the Liblinphone CFFI binding."""
    configure_logging(verbose=False)
    # Inline the ~30 lines of build logic from scripts/liblinphone_build.py.
    raise typer.Exit(0)
```

**Important:** The code above is a skeleton showing the typer signature. When implementing, copy the full `main()` body from each source script into the command function, replacing `args.source_dir` with the `source_dir` parameter, etc. Do NOT import from `scripts/` — inline the logic.

- [ ] **Step 4: Wire build_app into root**

In `src/yoyopod/cli/__init__.py`, replace the placeholder `build_app` with the real one:

```python
from yoyopod.cli.build import build_app  # noqa: E402 — after app creation

# Remove the old placeholder:
#   build_app = typer.Typer(name="build", ...)
#   app.add_typer(build_app)

# Replace with:
app.add_typer(build_app)
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_cli.py -v`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add src/yoyopod/cli/build.py src/yoyopod/cli/__init__.py tests/test_cli.py
git commit -m "feat(cli): port build lvgl and liblinphone commands"
```

---

### Task 3: Port pi voip commands (check + debug)

**Files:**
- Create: `src/yoyopod/cli/pi/__init__.py`
- Create: `src/yoyopod/cli/pi/voip.py`
- Modify: `src/yoyopod/cli/__init__.py`
- Test: `tests/test_cli.py`
- Source: `scripts/check_voip_registration.py`, `scripts/debug_incoming_call.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_cli.py`:

```python
def test_pi_voip_check_help():
    result = runner.invoke(app, ["pi", "voip", "check", "--help"])
    assert result.exit_code == 0


def test_pi_voip_debug_help():
    result = runner.invoke(app, ["pi", "voip", "debug", "--help"])
    assert result.exit_code == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cli.py::test_pi_voip_check_help tests/test_cli.py::test_pi_voip_debug_help -v`
Expected: FAIL

- [ ] **Step 3: Create pi package and voip module**

Create `src/yoyopod/cli/pi/__init__.py`:

```python
"""src/yoyopod/cli/pi/__init__.py — pi command group (on-device commands)."""

from __future__ import annotations

import typer

from yoyopod.cli.pi.voip import voip_app

pi_app = typer.Typer(name="pi", help="Commands that run ON the Raspberry Pi.", no_args_is_help=True)
pi_app.add_typer(voip_app)
```

Create `src/yoyopod/cli/pi/voip.py`:

```python
"""src/yoyopod/cli/pi/voip.py — VoIP diagnostic commands."""

from __future__ import annotations

import typer

from yoyopod.cli.common import configure_logging

voip_app = typer.Typer(name="voip", help="VoIP diagnostic commands.", no_args_is_help=True)


@voip_app.command()
def check() -> None:
    """Run a verbose SIP registration check against the Liblinphone backend."""
    configure_logging(verbose=True)
    # Inline the ~50 lines of logic from scripts/check_voip_registration.py main().
    # Key steps: load config, create backend, register, check status, teardown.
    raise typer.Exit(0)


@voip_app.command()
def debug() -> None:
    """Monitor for incoming SIP calls with verbose logging."""
    configure_logging(verbose=True)
    # Inline the ~50 lines of logic from scripts/debug_incoming_call.py main().
    # Key steps: load config, create backend, register, poll loop, teardown.
    raise typer.Exit(0)
```

- [ ] **Step 4: Wire pi_app into root**

In `src/yoyopod/cli/__init__.py`, replace the placeholder `pi_app` with the import:

```python
from yoyopod.cli.pi import pi_app

# Remove the old placeholder pi_app and its add_typer call.
# Add:
app.add_typer(pi_app)
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_cli.py -v`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add src/yoyopod/cli/pi/__init__.py src/yoyopod/cli/pi/voip.py src/yoyopod/cli/__init__.py tests/test_cli.py
git commit -m "feat(cli): port pi voip check and debug commands"
```

---

### Task 4: Port pi power commands (battery + rtc)

**Files:**
- Create: `src/yoyopod/cli/pi/power.py`
- Modify: `src/yoyopod/cli/pi/__init__.py`
- Test: `tests/test_cli.py`
- Source: `scripts/pisugar_power.py`, `scripts/pisugar_rtc.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_cli.py`:

```python
def test_pi_power_battery_help():
    result = runner.invoke(app, ["pi", "power", "battery", "--help"])
    assert result.exit_code == 0
    assert "--config-dir" in result.output
    assert "--verbose" in result.output


def test_pi_power_rtc_help():
    result = runner.invoke(app, ["pi", "power", "rtc", "--help"])
    assert result.exit_code == 0


def test_pi_power_rtc_status_help():
    result = runner.invoke(app, ["pi", "power", "rtc", "status", "--help"])
    assert result.exit_code == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cli.py::test_pi_power_battery_help tests/test_cli.py::test_pi_power_rtc_help -v`
Expected: FAIL

- [ ] **Step 3: Create power module**

Create `src/yoyopod/cli/pi/power.py`:

```python
"""src/yoyopod/cli/pi/power.py — PiSugar battery and RTC commands."""

from __future__ import annotations

import typer

from yoyopod.cli.common import configure_logging, resolve_config_dir

power_app = typer.Typer(name="power", help="PiSugar battery and RTC commands.", no_args_is_help=True)

# -- rtc subgroup -----------------------------------------------------------
rtc_app = typer.Typer(name="rtc", help="PiSugar RTC control.", no_args_is_help=True)
power_app.add_typer(rtc_app)


@power_app.command()
def battery(
    config_dir: str = typer.Option("config", help="Config directory path."),
    verbose: bool = typer.Option(False, "--verbose", help="Enable debug logging."),
) -> None:
    """Show PiSugar battery status, charging state, and shutdown config."""
    configure_logging(verbose)
    cfg_path = resolve_config_dir(config_dir)
    # Inline ~80 lines from scripts/pisugar_power.py main().
    # Key steps: load config, create PiSugarBackend, read telemetry, print table.
    raise typer.Exit(0)


@rtc_app.command()
def status(
    config_dir: str = typer.Option("config", help="Config directory path."),
    verbose: bool = typer.Option(False, "--verbose", help="Enable debug logging."),
) -> None:
    """Show RTC time, system time, and alarm state."""
    configure_logging(verbose)
    cfg_path = resolve_config_dir(config_dir)
    # Inline from scripts/pisugar_rtc.py cmd_status().
    raise typer.Exit(0)


@rtc_app.command(name="sync-to")
def sync_to_rtc(
    config_dir: str = typer.Option("config", help="Config directory path."),
    verbose: bool = typer.Option(False, "--verbose", help="Enable debug logging."),
) -> None:
    """Sync system time to the RTC."""
    configure_logging(verbose)
    cfg_path = resolve_config_dir(config_dir)
    # Inline from scripts/pisugar_rtc.py cmd_sync_to_rtc().
    raise typer.Exit(0)


@rtc_app.command(name="sync-from")
def sync_from_rtc(
    config_dir: str = typer.Option("config", help="Config directory path."),
    verbose: bool = typer.Option(False, "--verbose", help="Enable debug logging."),
) -> None:
    """Sync RTC time to the system clock."""
    configure_logging(verbose)
    cfg_path = resolve_config_dir(config_dir)
    # Inline from scripts/pisugar_rtc.py cmd_sync_from_rtc().
    raise typer.Exit(0)


@rtc_app.command(name="set-alarm")
def set_alarm(
    time: str = typer.Option(..., help="Alarm time in ISO 8601 format."),
    repeat_mask: int = typer.Option(127, help="Repeat bitmask (default: every day)."),
    config_dir: str = typer.Option("config", help="Config directory path."),
    verbose: bool = typer.Option(False, "--verbose", help="Enable debug logging."),
) -> None:
    """Set an RTC wake alarm."""
    configure_logging(verbose)
    cfg_path = resolve_config_dir(config_dir)
    # Inline from scripts/pisugar_rtc.py cmd_set_alarm().
    raise typer.Exit(0)


@rtc_app.command(name="disable-alarm")
def disable_alarm(
    config_dir: str = typer.Option("config", help="Config directory path."),
    verbose: bool = typer.Option(False, "--verbose", help="Enable debug logging."),
) -> None:
    """Disable the RTC wake alarm."""
    configure_logging(verbose)
    cfg_path = resolve_config_dir(config_dir)
    # Inline from scripts/pisugar_rtc.py cmd_disable_alarm().
    raise typer.Exit(0)
```

- [ ] **Step 4: Register power_app in pi group**

In `src/yoyopod/cli/pi/__init__.py`, add:

```python
from yoyopod.cli.pi.power import power_app

pi_app.add_typer(power_app)
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_cli.py -v`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add src/yoyopod/cli/pi/power.py src/yoyopod/cli/pi/__init__.py tests/test_cli.py
git commit -m "feat(cli): port pi power battery and rtc commands"
```

---

### Task 5: Port pi lvgl commands (soak + probe)

**Files:**
- Create: `src/yoyopod/cli/pi/lvgl.py`
- Modify: `src/yoyopod/cli/pi/__init__.py`
- Test: `tests/test_cli.py`
- Source: `scripts/lvgl_soak.py`, `scripts/lvgl_probe.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_cli.py`:

```python
def test_pi_lvgl_soak_help():
    result = runner.invoke(app, ["pi", "lvgl", "soak", "--help"])
    assert result.exit_code == 0
    assert "--cycles" in result.output
    assert "--simulate" in result.output
    assert "--hold-seconds" in result.output


def test_pi_lvgl_probe_help():
    result = runner.invoke(app, ["pi", "lvgl", "probe", "--help"])
    assert result.exit_code == 0
    assert "--scene" in result.output
    assert "--duration-seconds" in result.output
    assert "--simulate" in result.output
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cli.py::test_pi_lvgl_soak_help tests/test_cli.py::test_pi_lvgl_probe_help -v`
Expected: FAIL

- [ ] **Step 3: Create lvgl module**

Create `src/yoyopod/cli/pi/lvgl.py`:

```python
"""src/yoyopod/cli/pi/lvgl.py — LVGL soak and probe commands."""

from __future__ import annotations

from typing import Optional

import typer

from yoyopod.cli.common import configure_logging, resolve_config_dir

lvgl_app = typer.Typer(name="lvgl", help="LVGL display testing commands.", no_args_is_help=True)


@lvgl_app.command()
def soak(
    config_dir: str = typer.Option("config", help="Config directory path."),
    simulate: bool = typer.Option(False, "--simulate", help="Use simulation display."),
    cycles: int = typer.Option(2, help="Number of soak cycles."),
    hold_seconds: float = typer.Option(0.2, help="Hold time per screen in seconds."),
    skip_sleep: bool = typer.Option(False, "--skip-sleep", help="Skip inter-screen sleeps."),
    verbose: bool = typer.Option(False, "--verbose", help="Enable debug logging."),
) -> None:
    """Run an LVGL stress test cycling through all screens."""
    configure_logging(verbose)
    cfg_path = resolve_config_dir(config_dir)
    # Inline ~150 lines from scripts/lvgl_soak.py main().
    raise typer.Exit(0)


@lvgl_app.command()
def probe(
    scene: str = typer.Option("carousel", help="Scene to render."),
    duration_seconds: float = typer.Option(10.0, help="Duration in seconds."),
    simulate: bool = typer.Option(False, "--simulate", help="Use simulation display."),
    verbose: bool = typer.Option(False, "--verbose", help="Enable debug logging."),
) -> None:
    """Run a standalone LVGL proof-of-concept scene."""
    configure_logging(verbose)
    # Inline ~60 lines from scripts/lvgl_probe.py main().
    raise typer.Exit(0)
```

- [ ] **Step 4: Register lvgl_app in pi group**

In `src/yoyopod/cli/pi/__init__.py`, add:

```python
from yoyopod.cli.pi.lvgl import lvgl_app

pi_app.add_typer(lvgl_app)
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_cli.py -v`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add src/yoyopod/cli/pi/lvgl.py src/yoyopod/cli/pi/__init__.py tests/test_cli.py
git commit -m "feat(cli): port pi lvgl soak and probe commands"
```

---

### Task 6: Port pi smoke, tune, and gallery commands

**Files:**
- Create: `src/yoyopod/cli/pi/smoke.py`
- Create: `src/yoyopod/cli/pi/tune.py`
- Create: `src/yoyopod/cli/pi/gallery.py`
- Modify: `src/yoyopod/cli/pi/__init__.py`
- Test: `tests/test_cli.py`
- Source: `scripts/pi_smoke.py`, `scripts/whisplay_tune.py`, `scripts/whisplay_gallery.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_cli.py`:

```python
def test_pi_smoke_help():
    result = runner.invoke(app, ["pi", "smoke", "--help"])
    assert result.exit_code == 0
    assert "--with-music" in result.output
    assert "--with-voip" in result.output
    assert "--with-power" in result.output
    assert "--with-lvgl-soak" in result.output


def test_pi_tune_help():
    result = runner.invoke(app, ["pi", "tune", "--help"])
    assert result.exit_code == 0
    assert "--debounce-ms" in result.output
    assert "--hardware" in result.output


def test_pi_gallery_help():
    result = runner.invoke(app, ["pi", "gallery", "--help"])
    assert result.exit_code == 0
    assert "--output-dir" in result.output
    assert "--simulate" in result.output
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cli.py::test_pi_smoke_help tests/test_cli.py::test_pi_tune_help tests/test_cli.py::test_pi_gallery_help -v`
Expected: FAIL

- [ ] **Step 3: Create smoke module**

Create `src/yoyopod/cli/pi/smoke.py`:

```python
"""src/yoyopod/cli/pi/smoke.py — on-Pi smoke test runner."""

from __future__ import annotations

import typer

from yoyopod.cli.common import configure_logging, resolve_config_dir

smoke_app = typer.Typer(name="smoke", invoke_without_command=True, no_args_is_help=False)


@smoke_app.callback(invoke_without_command=True)
def smoke(
    config_dir: str = typer.Option("config", help="Config directory path."),
    with_music: bool = typer.Option(False, "--with-music", help="Include music playback tests."),
    with_power: bool = typer.Option(False, "--with-power", help="Include PiSugar power tests."),
    with_rtc: bool = typer.Option(False, "--with-rtc", help="Include RTC tests."),
    with_voip: bool = typer.Option(False, "--with-voip", help="Include VoIP registration tests."),
    with_lvgl_soak: bool = typer.Option(False, "--with-lvgl-soak", help="Include LVGL soak test."),
    music_timeout: int = typer.Option(5, help="Music test timeout in seconds."),
    voip_timeout: float = typer.Option(10.0, help="VoIP test timeout in seconds."),
    display_hold_seconds: float = typer.Option(0.5, help="Display hold time in seconds."),
    verbose: bool = typer.Option(False, "--verbose", help="Enable debug logging."),
) -> None:
    """Run on-Pi hardware smoke tests."""
    configure_logging(verbose)
    cfg_path = resolve_config_dir(config_dir)
    # Inline ~450 lines from scripts/pi_smoke.py main().
    raise typer.Exit(0)
```

- [ ] **Step 4: Create tune module**

Create `src/yoyopod/cli/pi/tune.py`:

```python
"""src/yoyopod/cli/pi/tune.py — Whisplay gesture tuning."""

from __future__ import annotations

from typing import Optional

import typer

from yoyopod.cli.common import configure_logging, resolve_config_dir

tune_app = typer.Typer(name="tune", invoke_without_command=True, no_args_is_help=False)


@tune_app.callback(invoke_without_command=True)
def tune(
    config_dir: str = typer.Option("config", help="Config directory path."),
    debounce_ms: Optional[int] = typer.Option(None, help="Debounce threshold in ms."),
    double_tap_ms: Optional[int] = typer.Option(None, help="Double-tap window in ms."),
    long_hold_ms: Optional[int] = typer.Option(None, help="Long-hold threshold in ms."),
    duration_seconds: float = typer.Option(30.0, help="Session duration in seconds."),
    hardware: str = typer.Option("whisplay", help="Hardware target."),
    no_display: bool = typer.Option(False, "--no-display", help="Disable display rendering."),
    verbose: bool = typer.Option(False, "--verbose", help="Enable debug logging."),
) -> None:
    """Interactive gesture-tuning helper for Whisplay hardware."""
    configure_logging(verbose)
    cfg_path = resolve_config_dir(config_dir)
    # Inline ~250 lines from scripts/whisplay_tune.py main().
    raise typer.Exit(0)
```

- [ ] **Step 5: Create gallery module**

Create `src/yoyopod/cli/pi/gallery.py`:

```python
"""src/yoyopod/cli/pi/gallery.py — Whisplay screenshot gallery."""

from __future__ import annotations

import typer

from yoyopod.cli.common import configure_logging

gallery_app = typer.Typer(name="gallery", invoke_without_command=True, no_args_is_help=False)


@gallery_app.callback(invoke_without_command=True)
def gallery(
    output_dir: str = typer.Option("temp/pi_gallery", help="Output directory for screenshots."),
    simulate: bool = typer.Option(False, "--simulate", help="Use simulation display."),
    settle_seconds: float = typer.Option(0.18, help="Settle time per screen in seconds."),
    verbose: bool = typer.Option(False, "--verbose", help="Enable debug logging."),
) -> None:
    """Capture a deterministic gallery of Whisplay LVGL screens."""
    configure_logging(verbose)
    # Inline ~800 lines from scripts/whisplay_gallery.py main().
    raise typer.Exit(0)
```

- [ ] **Step 6: Register all three in pi group**

Update `src/yoyopod/cli/pi/__init__.py` to import and register:

```python
from yoyopod.cli.pi.smoke import smoke_app
from yoyopod.cli.pi.tune import tune_app
from yoyopod.cli.pi.gallery import gallery_app

pi_app.add_typer(smoke_app)
pi_app.add_typer(tune_app)
pi_app.add_typer(gallery_app)
```

- [ ] **Step 7: Run tests**

Run: `uv run pytest tests/test_cli.py -v`
Expected: All tests PASS

- [ ] **Step 8: Commit**

```bash
git add src/yoyopod/cli/pi/smoke.py src/yoyopod/cli/pi/tune.py src/yoyopod/cli/pi/gallery.py src/yoyopod/cli/pi/__init__.py tests/test_cli.py
git commit -m "feat(cli): port pi smoke, tune, and gallery commands"
```

---

### Task 7: Port remote commands (pi_remote.py)

**Files:**
- Create: `src/yoyopod/cli/remote/__init__.py`
- Create: `src/yoyopod/cli/remote/ops.py`
- Create: `src/yoyopod/cli/remote/infra.py`
- Create: `src/yoyopod/cli/remote/lvgl.py`
- Modify: `src/yoyopod/cli/__init__.py`
- Test: `tests/test_cli.py`
- Source: `scripts/pi_remote.py`

This is the largest migration — `pi_remote.py` is 500+ lines with 8 subcommands. Split across three modules by concern.

- [ ] **Step 1: Write failing tests**

Append to `tests/test_cli.py`:

```python
def test_remote_status_help():
    result = runner.invoke(app, ["remote", "status", "--help"])
    assert result.exit_code == 0
    assert "--host" in result.output


def test_remote_sync_help():
    result = runner.invoke(app, ["remote", "sync", "--help"])
    assert result.exit_code == 0
    assert "--host" in result.output
    assert "--branch" in result.output


def test_remote_smoke_help():
    result = runner.invoke(app, ["remote", "smoke", "--help"])
    assert result.exit_code == 0


def test_remote_preflight_help():
    result = runner.invoke(app, ["remote", "preflight", "--help"])
    assert result.exit_code == 0


def test_remote_lvgl_soak_help():
    result = runner.invoke(app, ["remote", "lvgl-soak", "--help"])
    assert result.exit_code == 0


def test_remote_power_help():
    result = runner.invoke(app, ["remote", "power", "--help"])
    assert result.exit_code == 0


def test_remote_config_help():
    result = runner.invoke(app, ["remote", "config", "--help"])
    assert result.exit_code == 0


def test_remote_service_help():
    result = runner.invoke(app, ["remote", "service", "--help"])
    assert result.exit_code == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cli.py -k "test_remote_" -v`
Expected: FAIL (except the existing `test_remote_help` which should still pass)

- [ ] **Step 3: Create remote ops module**

Read `scripts/pi_remote.py` thoroughly to understand the argument structure for `status`, `sync`, `smoke`, and `preflight` subcommands. Create `src/yoyopod/cli/remote/ops.py`:

```python
"""src/yoyopod/cli/remote/ops.py — remote operational commands (status, sync, smoke, preflight)."""

from __future__ import annotations

from typing import Optional

import typer

from yoyopod.cli.common import configure_logging

# Commands are registered on the remote_app in remote/__init__.py.
# Each function is a standalone command.


def status(
    host: str = typer.Option(..., help="Pi hostname or IP."),
    verbose: bool = typer.Option(False, "--verbose", help="Enable debug logging."),
) -> None:
    """Show Pi device status (uptime, memory, processes)."""
    configure_logging(verbose)
    # Inline status logic from scripts/pi_remote.py.
    raise typer.Exit(0)


def sync(
    host: str = typer.Option(..., help="Pi hostname or IP."),
    branch: str = typer.Option("main", help="Git branch to sync."),
    verbose: bool = typer.Option(False, "--verbose", help="Enable debug logging."),
) -> None:
    """Git-push and sync the project to the Pi."""
    configure_logging(verbose)
    # Inline sync logic from scripts/pi_remote.py.
    raise typer.Exit(0)


def smoke(
    host: str = typer.Option(..., help="Pi hostname or IP."),
    with_music: bool = typer.Option(False, "--with-music", help="Include music tests."),
    with_voip: bool = typer.Option(False, "--with-voip", help="Include VoIP tests."),
    with_lvgl_soak: bool = typer.Option(False, "--with-lvgl-soak", help="Include LVGL soak."),
    verbose: bool = typer.Option(False, "--verbose", help="Enable debug logging."),
) -> None:
    """Run smoke tests on the Pi via SSH."""
    configure_logging(verbose)
    # Inline smoke logic from scripts/pi_remote.py.
    raise typer.Exit(0)


def preflight(
    host: str = typer.Option(..., help="Pi hostname or IP."),
    with_music: bool = typer.Option(False, "--with-music", help="Include music preflight."),
    with_voip: bool = typer.Option(False, "--with-voip", help="Include VoIP preflight."),
    with_lvgl_soak: bool = typer.Option(False, "--with-lvgl-soak", help="Include LVGL soak preflight."),
    verbose: bool = typer.Option(False, "--verbose", help="Enable debug logging."),
) -> None:
    """Run preflight checks on the Pi via SSH."""
    configure_logging(verbose)
    # Inline preflight logic from scripts/pi_remote.py.
    raise typer.Exit(0)
```

- [ ] **Step 4: Create remote infra module**

Create `src/yoyopod/cli/remote/infra.py`:

```python
"""src/yoyopod/cli/remote/infra.py — remote infrastructure commands (config, service, power)."""

from __future__ import annotations

import typer

from yoyopod.cli.common import configure_logging


def power(
    host: str = typer.Option(..., help="Pi hostname or IP."),
    verbose: bool = typer.Option(False, "--verbose", help="Enable debug logging."),
) -> None:
    """Check PiSugar power status on the Pi via SSH."""
    configure_logging(verbose)
    # Inline power logic from scripts/pi_remote.py.
    raise typer.Exit(0)


def config(
    host: str = typer.Option(..., help="Pi hostname or IP."),
    verbose: bool = typer.Option(False, "--verbose", help="Enable debug logging."),
) -> None:
    """Manage Pi deployment configuration."""
    configure_logging(verbose)
    # Inline config logic from scripts/pi_remote.py.
    raise typer.Exit(0)


def service(
    host: str = typer.Option(..., help="Pi hostname or IP."),
    action: str = typer.Argument(help="Service action (install, start, stop, status)."),
    verbose: bool = typer.Option(False, "--verbose", help="Enable debug logging."),
) -> None:
    """Manage the yoyopod systemd service on the Pi."""
    configure_logging(verbose)
    # Inline service logic from scripts/pi_remote.py.
    raise typer.Exit(0)
```

- [ ] **Step 5: Create remote lvgl module**

Create `src/yoyopod/cli/remote/lvgl.py`:

```python
"""src/yoyopod/cli/remote/lvgl.py — remote LVGL soak over SSH."""

from __future__ import annotations

import typer

from yoyopod.cli.common import configure_logging


def lvgl_soak(
    host: str = typer.Option(..., help="Pi hostname or IP."),
    cycles: int = typer.Option(2, help="Number of soak cycles."),
    verbose: bool = typer.Option(False, "--verbose", help="Enable debug logging."),
) -> None:
    """Run LVGL soak test on the Pi via SSH."""
    configure_logging(verbose)
    # Inline lvgl-soak logic from scripts/pi_remote.py.
    raise typer.Exit(0)
```

- [ ] **Step 6: Wire remote group**

Create `src/yoyopod/cli/remote/__init__.py`:

```python
"""src/yoyopod/cli/remote/__init__.py — remote command group (SSH to Pi)."""

from __future__ import annotations

import typer

from yoyopod.cli.remote.ops import status, sync, smoke, preflight
from yoyopod.cli.remote.infra import power, config, service
from yoyopod.cli.remote.lvgl import lvgl_soak

remote_app = typer.Typer(name="remote", help="Commands that SSH to the Raspberry Pi from the dev machine.", no_args_is_help=True)

remote_app.command()(status)
remote_app.command()(sync)
remote_app.command()(smoke)
remote_app.command()(preflight)
remote_app.command(name="lvgl-soak")(lvgl_soak)
remote_app.command()(power)
remote_app.command()(config)
remote_app.command()(service)
```

Update `src/yoyopod/cli/__init__.py` to import from remote:

```python
from yoyopod.cli.remote import remote_app

# Remove the old placeholder remote_app and its add_typer call.
app.add_typer(remote_app)
```

- [ ] **Step 7: Run tests**

Run: `uv run pytest tests/test_cli.py -v`
Expected: All tests PASS

- [ ] **Step 8: Commit**

```bash
git add src/yoyopod/cli/remote/ src/yoyopod/cli/__init__.py tests/test_cli.py
git commit -m "feat(cli): port remote commands from pi_remote.py"
```

---

### Task 8: Inline script logic into all command skeletons

**Files:**
- Modify: all `src/yoyopod/cli/**/*.py` modules
- Remove: `scripts/check_voip_registration.py`, `scripts/debug_incoming_call.py`, `scripts/liblinphone_build.py`, `scripts/lvgl_build.py`, `scripts/lvgl_probe.py`, `scripts/lvgl_soak.py`, `scripts/pi_remote.py`, `scripts/pi_smoke.py`, `scripts/pisugar_power.py`, `scripts/pisugar_rtc.py`, `scripts/whisplay_gallery.py`, `scripts/whisplay_tune.py`
- Keep: `scripts/generate_test_sounds.py`

This is the largest task — it replaces every `raise typer.Exit(0)` placeholder with the real logic from each source script. Work through one module at a time.

- [ ] **Step 1: Port build commands**

Open `scripts/lvgl_build.py` and `scripts/liblinphone_build.py`. Copy each `main()` body into the corresponding typer command in `src/yoyopod/cli/build.py`. Replace `args.source_dir` with `source_dir`, `args.build_dir` with `build_dir`, etc. Remove the `raise typer.Exit(0)` placeholders. Remove the `sys.path` manipulation — imports are now inside the package.

- [ ] **Step 2: Port pi voip commands**

Open `scripts/check_voip_registration.py` and `scripts/debug_incoming_call.py`. Copy each `main()` body into `src/yoyopod/cli/pi/voip.py`. Replace argparse references with typer parameters.

- [ ] **Step 3: Port pi power commands**

Open `scripts/pisugar_power.py` and `scripts/pisugar_rtc.py`. Copy the logic into `src/yoyopod/cli/pi/power.py`. For rtc, each subcommand handler (`cmd_status`, `cmd_sync_to_rtc`, etc.) maps to its corresponding typer command.

- [ ] **Step 4: Port pi lvgl commands**

Open `scripts/lvgl_soak.py` and `scripts/lvgl_probe.py`. Copy into `src/yoyopod/cli/pi/lvgl.py`.

- [ ] **Step 5: Port pi smoke command**

Open `scripts/pi_smoke.py`. Copy `main()` body into `src/yoyopod/cli/pi/smoke.py`. This is ~450 lines — keep the internal helper functions as module-level private functions in `smoke.py`.

- [ ] **Step 6: Port pi tune command**

Open `scripts/whisplay_tune.py`. Copy into `src/yoyopod/cli/pi/tune.py`.

- [ ] **Step 7: Port pi gallery command**

Open `scripts/whisplay_gallery.py`. This is ~800 lines. Copy into `src/yoyopod/cli/pi/gallery.py`. Keep internal helpers as module-level private functions.

- [ ] **Step 8: Port remote commands**

Open `scripts/pi_remote.py`. This is the most complex — ~500 lines split across `remote/ops.py`, `remote/infra.py`, and `remote/lvgl.py`. Identify the handler function for each subcommand and copy it to the right module. Shared SSH/subprocess helpers should go into a `src/yoyopod/cli/remote/ssh.py` module if they're reused across files, otherwise keep them local.

- [ ] **Step 9: Run full test suite**

Run: `uv run pytest -q`
Expected: All tests PASS (including existing tests and new CLI tests)

Run: `python -m compileall yoyopod`
Expected: No errors

- [ ] **Step 10: Verify CLI end-to-end**

Run: `yoyopod --help`
Expected: Shows pi, remote, build groups

Run: `yoyopod pi --help`
Expected: Shows smoke, tune, gallery, lvgl, voip, power subgroups

Run: `yoyopod remote --help`
Expected: Shows status, sync, smoke, preflight, lvgl-soak, power, config, service

Run: `yoyopod build --help`
Expected: Shows lvgl, liblinphone

- [ ] **Step 11: Delete migrated scripts**

Remove all migrated scripts. Keep only `scripts/generate_test_sounds.py`:

```bash
rm scripts/check_voip_registration.py scripts/debug_incoming_call.py \
   scripts/liblinphone_build.py scripts/lvgl_build.py scripts/lvgl_probe.py \
   scripts/lvgl_soak.py scripts/pi_remote.py scripts/pi_smoke.py \
   scripts/pisugar_power.py scripts/pisugar_rtc.py \
   scripts/whisplay_gallery.py scripts/whisplay_tune.py
```

- [ ] **Step 12: Commit**

```bash
git add -A
git commit -m "feat(cli): inline all script logic and remove migrated scripts"
```

---

### Task 9: Update existing tests

**Files:**
- Modify: `tests/test_pi_remote.py`

- [ ] **Step 1: Check test_pi_remote.py imports**

Read `tests/test_pi_remote.py`. It imports from `scripts.pi_remote` or uses `subprocess` to run the script. Update imports to point to `yoyopod.cli.remote` modules instead.

- [ ] **Step 2: Update import paths**

Replace any `from scripts.pi_remote import ...` with imports from the new location in `yoyopod.cli.remote.*`. If the test runs `python scripts/pi_remote.py` via subprocess, change to `yoyopod remote ...` or import and invoke directly.

- [ ] **Step 3: Run tests**

Run: `uv run pytest tests/test_pi_remote.py -v`
Expected: All tests PASS

Run: `uv run pytest -q`
Expected: Full suite PASS

- [ ] **Step 4: Commit**

```bash
git add tests/test_pi_remote.py
git commit -m "fix(tests): update pi_remote tests for cli module paths"
```

---

### Task 10: Update CLAUDE.md and docs

**Files:**
- Modify: `CLAUDE.md`
- Modify: any doc files that reference `scripts/` invocations
- Modify: any skill files under `skills/` that reference `scripts/`

- [ ] **Step 1: Update CLAUDE.md Raspberry Pi Workflow section**

Replace all `uv run python scripts/...` invocations with `yoyopod` equivalents:

```markdown
## Raspberry Pi Workflow

Preferred remote helper:

\`\`\`bash
yoyopod remote status --host rpi-zero
yoyopod remote preflight --host rpi-zero --with-music --with-voip --with-lvgl-soak
yoyopod remote sync --host rpi-zero --branch main
yoyopod remote smoke --host rpi-zero --with-music --with-voip --with-lvgl-soak
yoyopod remote lvgl-soak --host rpi-zero --cycles 2
yoyopod remote power --host rpi-zero
yoyopod remote service install --host rpi-zero
\`\`\`

Direct smoke helper on the Pi:

\`\`\`bash
yoyopod pi smoke
yoyopod pi smoke --with-music --with-voip
yoyopod pi lvgl soak
\`\`\`
```

- [ ] **Step 2: Update CLAUDE.md Debug Entry Points section**

```markdown
## Debug Entry Points

\`\`\`bash
yoyopod pi voip check
yoyopod pi voip debug
\`\`\`
```

- [ ] **Step 3: Update CLAUDE.md Important Packages section**

Replace references to `scripts/pisugar_power.py` and `scripts/pisugar_rtc.py` with their new locations under `src/yoyopod/cli/pi/power.py`.

Add a new section for the CLI package:

```markdown
### CLI (dev-only)

- `src/yoyopod/cli/__init__.py` - root yoyopod app and group wiring
- `src/yoyopod/cli/common.py` - shared logging and config helpers
- `src/yoyopod/cli/build.py` - native extension build commands
- `src/yoyopod/cli/pi/` - on-Pi hardware and diagnostic commands
- `src/yoyopod/cli/remote/` - SSH-based remote Pi operations
```

- [ ] **Step 4: Update skill files**

Read each file in `skills/` that references `scripts/`. Update invocation examples to use `yoyopod`.

- [ ] **Step 5: Run compileall and tests one final time**

Run: `python -m compileall yoyopod`
Run: `uv run pytest -q`
Expected: Both pass

- [ ] **Step 6: Commit**

```bash
git add CLAUDE.md skills/ docs/
git commit -m "docs: update all references from scripts/ to yoyopod"
```

---

Plan complete and saved to `docs/superpowers/plans/2026-04-10-yoyopod-cli.md`. Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?