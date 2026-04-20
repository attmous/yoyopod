# CLI Polish — Design

**Date:** 2026-04-20
**Owner:** Moustafa
**Status:** Approved for implementation planning
**Supersedes:** `docs/superpowers/plans/2026-04-10-yoyopod-cli.md` (the original `yoyopod` CLI scaffold plan)

---

## 1. Goals

The current CLI (`src/yoyopod/cli/`, ~8,800 lines across ~30 files) has grown organically and now exhibits three kinds of friction:

1. **Too many layers per command.** A typical remote command passes through a Typer handler → an `argparse.Namespace` shim → a `build_X_command()` builder → `run_remote()`. Readers trace three files to understand one command.
2. **Boilerplate duplication.** Every remote command re-declares the same four Pi-connection options (`--host / --user / --project-dir / --branch`) with identical help text — 20+ copies.
3. **Scattered path and process constants.** Log paths, PID files, screenshot paths, process names, and rsync excludes are defined in 10+ places, making "where do I edit if this path changes?" a non-trivial question.

Plus a pile of commands that are no longer part of any real workflow (duplicates, one-shot bring-up helpers, specialist soak drills).

**Success criteria:**

- One flat package at the repo root, one file per command subgroup, no nested directories.
- Every CLI command follows the same template (signature → shared state pull → inline shell → exit).
- All path and process constants live in a single `paths.py`.
- Every surviving command is one you run often enough to justify keeping.
- `yoyopod` is gone; `yoyopod` is both the app launcher and the CLI dispatcher.
- An auto-generated `COMMANDS.md` at the CLI root lists every command.

---

## 2. Scope

**In scope:**
- Move CLI from `src/yoyopod/cli/` to a new top-level `yoyopod_cli/` package.
- Prune ~15 rarely-used or duplicate commands.
- Fold the three VoIP soak commands into `pi validate voip --soak {kind}`.
- Add five top-level shortcut commands (`deploy`, `status`, `logs`, `restart`, `validate`).
- Consolidate all path and process constants into `yoyopod_cli/paths.py`.
- Introduce a single shared-options callback for the remote Pi connection.
- Remove the `cli/remote/ops/__init__.py` 152-line re-export shim.
- Remove the `argparse.Namespace` bridge in every remote handler.
- Rename the console script `yoyopod` → `yoyopod` (cold cutover, no alias).
- Regenerate and commit `yoyopod_cli/COMMANDS.md` from Typer introspection.
- Update all documentation, skills, CLAUDE.md, and tests.

**Out of scope:**
- Changing the behavior of any surviving command (same flags, same outputs).
- Rewriting off-CLI code such as `YoyoPodApp`, coordinators, runtime services, or config models.
- Changing `config/**/*.yaml` layouts (app config stays where it is).
- Migrating away from Typer, argparse, or any framework.

---

## 3. Target layout

```
<repo root>/
├── yoyopod_cli/                          ← new flat package
│   ├── __init__.py                       ← __version__, run(), lazy build_app()
│   ├── main.py                           ← single entry + usage docstring + root callback
│   ├── paths.py                          ← all path/process constants
│   ├── common.py                         ← configure_logging, REPO_ROOT re-export
│   ├── remote_shared.py                  ← build_remote_app(), pi_conn(), RemoteConnection
│   ├── remote_transport.py               ← run_remote, run_local, ssh/rsync helpers
│   ├── remote_config.py                  ← yoyopod remote config {show,edit}
│   ├── remote_ops.py                     ← status, sync, restart, logs, screenshot
│   ├── remote_validate.py                ← validate (with --with-music/--with-voip/--with-lvgl-soak/--with-navigation), preflight
│   ├── remote_infra.py                   ← power, rtc, service
│   ├── remote_setup.py                   ← setup, verify-setup
│   ├── pi_validate.py                    ← deploy, smoke, music, voip (with --soak), stability, navigation
│   ├── pi_voip.py                        ← check, debug
│   ├── pi_power.py                       ← battery, rtc {status,sync-to,sync-from,set-alarm,disable-alarm}
│   ├── pi_network.py                     ← probe, status
│   ├── build.py                          ← lvgl, liblinphone
│   ├── setup.py                          ← host, pi, verify-host, verify-pi
│   ├── _docgen.py                        ← introspection helper for COMMANDS.md
│   └── COMMANDS.md                       ← auto-generated command reference
└── src/yoyopod/                          ← app code only; cli/ subdir deleted
```

**~17 Python files flat.** Each 100–1100 lines. No subdirs, no re-export shims, no compat layer.

`pi_gallery.py`, `pi_tune.py`, `pi_lvgl.py`, `pi_music.py`, `remote_lvgl.py`, `remote_navigation.py` do **not** appear — their commands are cut (see §4).

---

## 4. Command triage (the definitive cut list)

### KEEP — the surviving command set (~25 commands)

**`yoyopod` top-level shortcuts (new; thin aliases to `remote`):**
- `yoyopod` — bare invocation launches the app (via `main:run` → `YoyoPodApp`)
- `yoyopod deploy` — alias for `remote sync`
- `yoyopod status` — alias for `remote status`
- `yoyopod logs` — alias for `remote logs`
- `yoyopod restart` — alias for `remote restart`
- `yoyopod validate` — alias for `remote validate`

**`yoyopod remote …` (dev machine → Pi via SSH):**
- `remote status`, `remote sync`, `remote validate [--with-music --with-voip --with-lvgl-soak --with-navigation]`, `remote preflight`, `remote restart`, `remote logs`, `remote screenshot`, `remote config {show,edit}`, `remote service {install,uninstall,status,start,stop}`, `remote setup`, `remote verify-setup`, `remote power`, `remote rtc {status,sync-to,sync-from,set-alarm,disable-alarm}`

**`yoyopod pi …` (on the Pi):**
- `pi validate {deploy, smoke, music, voip, stability, navigation, lvgl}` — `lvgl` is new, absorbs the cut `pi lvgl soak`
- `pi validate voip [--soak {registration,reconnect,call}]` — absorbs the three cut soak commands
- `pi voip {check, debug}`
- `pi power battery`, `pi power rtc {status,sync-to,sync-from,set-alarm,disable-alarm}`
- `pi network {probe, status}`

**`yoyopod build …`:**
- `build lvgl`, `build liblinphone`

**`yoyopod setup …`:**
- `setup host`, `setup pi`, `setup verify-host`, `setup verify-pi`

### CUT — removed commands (~15 commands)

| Command | Reason |
|---|---|
| `pi smoke` | Duplicate of `pi validate smoke` |
| `remote smoke` | Duplicate of `remote validate` |
| `remote rsync` | Legacy direct-mode alternative to `remote sync` |
| `remote provision-test-music` | Dead — covered by `pi validate music` |
| `pi music provision-test-library` | Dead — covered by `pi validate music` |
| `pi network gps` | One-shot modem bring-up, effectively never run |
| `pi lvgl probe` | Superseded by `pi lvgl soak`, and lvgl-soak itself gets folded |
| `pi lvgl soak` | Folded into `pi validate lvgl` (used on-Pi) and surfaced as `remote validate --with-lvgl-soak` from the dev machine |
| `pi voip registration-stability` | Folded into `pi validate voip --soak registration` |
| `pi voip reconnect-drill` | Folded into `pi validate voip --soak reconnect` |
| `pi voip call-soak` | Folded into `pi validate voip --soak call` |
| `pi tune` | Whisplay bring-up tooling, effectively frozen |
| `pi gallery` | Whisplay bring-up tooling, effectively frozen |
| `remote whisplay` | Cut with `pi tune` |
| `remote navigation-soak` | Folded into `remote validate --with-navigation` |
| `remote lvgl-soak` | Folded into `remote validate --with-lvgl-soak` |

Net effect: ~40 commands → ~25 commands (38% reduction), with every survivor on a real workflow.

---

## 5. The command pattern (applied to every file)

Every command in every file conforms to this template. Consistency across files is the core readability win.

### Template

```python
# yoyopod_cli/remote_ops.py
import shlex
import typer

from yoyopod_cli.common import configure_logging
from yoyopod_cli.paths import load_pi_paths
from yoyopod_cli.remote_shared import build_remote_app, pi_conn
from yoyopod_cli.remote_transport import run_remote

app = build_remote_app("ops", "Runtime ops on the Pi via SSH.")


@app.command()
def logs(
    ctx: typer.Context,
    lines: int = 50,
    follow: bool = typer.Option(False, "--follow", "-f"),
    errors: bool = False,
    filter: str = "",
    verbose: bool = False,
) -> None:
    """Tail yoyopod logs on the Pi."""
    configure_logging(verbose)
    conn = pi_conn(ctx)
    pi = load_pi_paths()

    log_path = pi.error_log_file if errors else pi.log_file
    cmd = f"tail -n {lines}{' -f' if follow else ''} {log_path}"
    if filter:
        cmd += f" | grep {shlex.quote(filter)}"

    raise typer.Exit(run_remote(conn, cmd, tty=follow))
```

### Rules (applied uniformly to every CLI file)

1. **One file per command subgroup.** No split between handlers and builders.
2. **One function = one command.** Typer parameters are typed Python parameters; no `argparse.Namespace` anywhere.
3. **Shared remote options are declared once** in `build_remote_app()` inside `remote_shared.py`. Every remote command pulls the typed `RemoteConnection` via `pi_conn(ctx)`.
4. **Shell commands are inline f-strings** using paths from `load_pi_paths()`. No `build_X_command()` layer.
5. **Exit codes propagate via `raise typer.Exit(run_remote(...))`.** No manual `if rc != 0` ladders.
6. **Module-level `app = typer.Typer(...)` or `build_remote_app(...)`**, registered into the root app by `main.py`. Every file exposes its `app` under the same name.

### Reader's locality promise

To understand any command, the reader needs to hold in their head:
- The command's own function body (≤30 lines typical).
- One accessor call (`pi_conn(ctx)`, `load_pi_paths()`).
- The shell string it builds.

To go deeper, the reader follows exactly one of these paths:
- `paths.py` — where the path came from.
- `remote_transport.py` — what `run_remote` does.
- `remote_shared.py` — what `pi_conn` returns.

Each is a single ≤120-line file with no cross-references between them. Flat dependency graph. No circular imports. No cycles.

---

## 6. Shared remote options (kill the 4× duplication)

```python
# yoyopod_cli/remote_shared.py
from __future__ import annotations

from dataclasses import dataclass

import typer


@dataclass(frozen=True)
class RemoteConnection:
    host: str
    user: str
    project_dir: str
    branch: str

    @property
    def ssh_target(self) -> str:
        return f"{self.user}@{self.host}" if self.user else self.host


def build_remote_app(name: str, help: str) -> typer.Typer:
    """Build a Typer sub-app that captures the shared Pi-connection options once."""
    app = typer.Typer(name=name, help=help, no_args_is_help=True)

    @app.callback()
    def _capture_connection(
        ctx: typer.Context,
        host: str = typer.Option("", "--host", envvar="YOYOPOD_PI_HOST"),
        user: str = typer.Option("", "--user", envvar="YOYOPOD_PI_USER"),
        project_dir: str = typer.Option("", "--project-dir", envvar="YOYOPOD_PI_PROJECT_DIR"),
        branch: str = typer.Option("", "--branch", envvar="YOYOPOD_PI_BRANCH"),
    ) -> None:
        ctx.obj = _resolve_remote_connection(host, user, project_dir, branch)

    return app


def pi_conn(ctx: typer.Context) -> RemoteConnection:
    """Typed accessor — returns a RemoteConnection, not a vague ctx.obj."""
    return ctx.ensure_object(RemoteConnection)


def _resolve_remote_connection(host: str, user: str, project_dir: str, branch: str) -> RemoteConnection:
    """Merge CLI flags over env vars over pi-deploy.yaml defaults."""
    # ...loads yaml, applies defaults, returns RemoteConnection
```

**Resolution precedence** (highest wins): CLI flag → env var → `deploy/pi-deploy.local.yaml` → `deploy/pi-deploy.yaml` → hardcoded defaults in `paths.py`. Matches current behavior exactly.

Every remote command signature becomes **just its own flags** — `host/user/project_dir/branch` are present at the group level but invisible to individual command handlers.

---

## 7. `paths.py` — the single config file

All path and process constants live in `yoyopod_cli/paths.py`. When anything path-shaped changes, it's the one file to edit.

### Structure

```python
# yoyopod_cli/paths.py
"""All CLI paths and process constants — single source of truth."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class HostPaths:
    repo_root: Path = REPO_ROOT
    deploy_config: Path = REPO_ROOT / "deploy" / "pi-deploy.yaml"
    deploy_config_local: Path = REPO_ROOT / "deploy" / "pi-deploy.local.yaml"
    systemd_unit_template: Path = REPO_ROOT / "deploy" / "systemd" / "yoyopod@.service"


@dataclass(frozen=True)
class PiPaths:
    project_dir: str = "~/YoyoPod_Core"
    venv: str = ".venv"
    start_cmd: str = "python yoyopod.py"
    log_file: str = "logs/yoyopod.log"
    error_log_file: str = "logs/yoyopod_errors.log"
    pid_file: str = "/tmp/yoyopod.pid"
    screenshot_path: str = "/tmp/yoyopod_screenshot.png"
    test_music_target_dir: str = "logs/test-music"
    startup_marker: str = "YoyoPod starting"
    kill_processes: tuple[str, ...] = ("python", "linphonec")
    rsync_exclude: tuple[str, ...] = (
        ".git/", ".cache/", "__pycache__/", "*.pyc",
        ".venv/", "build/", "logs/", "models/",
        "node_modules/", "*.egg-info/",
    )


@dataclass(frozen=True)
class ConfigFiles:
    core: Path = REPO_ROOT / "config" / "app" / "core.yaml"
    music: Path = REPO_ROOT / "config" / "audio" / "music.yaml"
    hardware: Path = REPO_ROOT / "config" / "device" / "hardware.yaml"
    cellular: Path = REPO_ROOT / "config" / "network" / "cellular.yaml"
    voice: Path = REPO_ROOT / "config" / "voice" / "assistant.yaml"
    calling: Path = REPO_ROOT / "config" / "communication" / "calling.yaml"
    messaging: Path = REPO_ROOT / "config" / "communication" / "messaging.yaml"
    people: Path = REPO_ROOT / "config" / "people" / "directory.yaml"
    cloud_backend: Path = REPO_ROOT / "config" / "cloud" / "backend.yaml"


@dataclass(frozen=True)
class ProcessNames:
    app: str = "python yoyopod.py"
    mpv: str = "mpv"
    linphonec: str = "linphonec"


HOST = HostPaths()
PI_DEFAULTS = PiPaths()
CONFIGS = ConfigFiles()
PROCS = ProcessNames()


def load_pi_paths() -> PiPaths:
    """Return PiPaths with overrides from deploy/pi-deploy.{,.local}.yaml applied.

    Reads fresh on every call — commands are short-lived processes.
    """
    # reads HOST.deploy_config + HOST.deploy_config_local, merges, returns overridden PiPaths
```

### What this consolidates

Replaces path constants currently scattered across:
- `cli/remote/config.py` (`PiDeployConfig`, `DEPLOY_CONFIG_PATH`, `LOCAL_DEPLOY_CONFIG_PATH`, `DEFAULT_PI_PROJECT_DIR`, defaults inside `parse_pi_deploy_config`)
- `cli/common.py` (`REPO_ROOT`)
- `cli/setup.py` (`TRACKED_CONFIG_PATHS`, `NATIVE_ARTIFACTS`)
- Inline string literals in 10+ handler files

Non-path constants such as the host apt package lists (`CORE_PI_PACKAGES`, etc.) stay in `setup.py` — `paths.py` is for paths and process names only.

### Override model (unchanged)

`deploy/pi-deploy.yaml` + `deploy/pi-deploy.local.yaml` continue to override any `PiPaths` field per host. The YAML layer's merge logic moves from `cli/remote/config.py` into `paths.load_pi_paths()` without behavior change.

---

## 8. `main.py` — the entry point

```python
# yoyopod_cli/main.py
"""
yoyopod — app launcher and CLI dispatcher.

Usage:
    yoyopod                      # Launch the YoyoPod app
    yoyopod deploy               # Sync code to Pi and restart
    yoyopod status               # Pi health dashboard
    yoyopod logs [-f --errors]   # Tail logs from the Pi
    yoyopod restart              # Restart app on the Pi
    yoyopod validate             # Run validation suite on the Pi
    yoyopod remote <cmd>         # Dev-machine → Pi commands (full list: yoyopod remote --help)
    yoyopod pi <cmd>             # On-device commands (yoyopod pi --help)
    yoyopod build <cmd>          # Native extension builds
    yoyopod setup <cmd>          # Host and Pi setup
"""
from __future__ import annotations

import typer

from yoyopod_cli import remote_ops, remote_validate, pi_validate, pi_voip, pi_power, pi_network
from yoyopod_cli import remote_config, remote_infra, remote_setup, build, setup

app = typer.Typer(name="yoyopod", help="YoyoPod app launcher and CLI.", no_args_is_help=False)


@app.callback(invoke_without_command=True)
def _root(ctx: typer.Context) -> None:
    """Launch the app when invoked with no subcommand."""
    if ctx.invoked_subcommand is None:
        from yoyopod.main import main as launch_app
        launch_app()


# --- sub-apps
remote_app = typer.Typer(name="remote", help="Dev-machine → Pi via SSH.", no_args_is_help=True)
# ... merge remote_ops/remote_validate/remote_config/remote_infra/remote_setup into remote_app
app.add_typer(remote_app)

pi_app = typer.Typer(name="pi", help="Commands that run on the Pi.", no_args_is_help=True)
# ... merge pi_validate/pi_voip/pi_power/pi_network into pi_app
app.add_typer(pi_app)

app.add_typer(build.app, name="build")
app.add_typer(setup.app, name="setup")


# --- top-level shortcuts (thin aliases)
app.command("deploy")(remote_ops.sync)
app.command("status")(remote_ops.status)
app.command("logs")(remote_ops.logs)
app.command("restart")(remote_ops.restart)
app.command("validate")(remote_validate.validate)


def run() -> None:
    app()
```

### Entry-point rewiring

**`pyproject.toml`:**
```toml
[project.scripts]
yoyopod = "yoyopod_cli.main:run"
# yoyopod removed entirely
```

The bare-`yoyopod`-launches-the-app behavior uses Typer's `@app.callback(invoke_without_command=True)` — no custom sys.argv parsing.

---

## 9. `COMMANDS.md` — auto-generated reference

One markdown file at `yoyopod_cli/COMMANDS.md`, generated from the live Typer tree.

### Generator

- `yoyopod_cli/_docgen.py` walks the app tree, collects `(command_path, help_text, parameters)` triples, and emits the markdown.
- Invoked via a new dev command: `yoyopod dev docs`.
- Run as part of CI (quality gate) to catch drift between code and `COMMANDS.md`.

### Output shape

Grouped sections for top-level shortcuts, `remote`, `pi`, `build`, `setup`. Each section is a table: Command | What it does. Sub-variants listed inline (e.g., `remote validate [--with-music --with-voip --with-lvgl-soak --with-navigation]`).

### Why auto-generated

With 25 commands and expected churn, a hand-written table drifts. CI regenerates the file on every run and fails if the regenerated output does not match the committed `COMMANDS.md` — so `yoyopod --help` and the committed reference table cannot disagree.

---

## 10. Testing approach

### Files to migrate (import-path rewrites, no behavior changes)

- `tests/test_cli.py`
- `tests/test_cli_bootstrap.py`
- `tests/test_pi_remote.py`
- `tests/test_setup_cli.py`
- `tests/test_voip_cli.py`
- `tests/test_navigation_soak.py`
- `tests/test_remote_config_helpers.py`
- `tests/test_quality_script.py`

### Files to delete (test cut commands)

- `tests/test_pi_gallery.py` — `pi gallery` removed
- `tests/test_whisplay_tune.py` — `pi tune` / `remote whisplay` removed

### Monkeypatch targets

Tests that patch `yoyopod.cli.remote.ops.subprocess.run`, `yoyopod.cli.remote.ops.run_local_capture`, `yoyopod.cli.remote.ops.validation.run_remote`, etc. must be rewritten to patch the new module boundaries:

- `yoyopod_cli.remote_transport.subprocess.run`
- `yoyopod_cli.remote_transport.run_remote`
- `yoyopod_cli.remote_transport.run_local_capture`

Every monkeypatch target in `tests/test_pi_remote.py` (~15 lines) gets a one-line path rewrite. No test logic changes.

### New tests (minimal)

- `test_paths.py` — verify `load_pi_paths()` merges defaults + yaml + local override correctly.
- `test_remote_shared.py` — verify `build_remote_app` callback captures flags / env / defaults and produces a valid `RemoteConnection`.
- `test_main_shortcuts.py` — verify `yoyopod status` invokes the same handler as `yoyopod remote status`.

---

## 11. Documentation updates

### Files requiring find-and-replace of `yoyopod` → `yoyopod`

- `CLAUDE.md` (project instructions)
- `README.md`
- `AGENTS.md`
- `docs/DEVELOPMENT_GUIDE.md`
- `docs/PI_DEV_WORKFLOW.md`
- `docs/RPI_SMOKE_VALIDATION.md`
- `docs/SYSTEM_ARCHITECTURE.md` (anywhere it mentions CLI)
- `skills/yoyopod-deploy/SKILL.md`
- `skills/yoyopod-sync/SKILL.md`
- `skills/yoyopod-logs/SKILL.md`
- `skills/yoyopod-restart/SKILL.md`
- `skills/yoyopod-status/SKILL.md`
- `skills/yoyopod-screenshot/SKILL.md`
- Any `rules/*.md` referencing `yoyopod`

Global `grep -rn yoyopod` + find-replace pass, followed by human review.

### Updates covering removed commands

- Skills that specifically invoke `pi gallery`, `pi tune`, `remote whisplay`, `remote rsync`, `pi voip registration-stability/reconnect-drill/call-soak`, `pi lvgl probe/soak`, `remote navigation-soak`, `remote lvgl-soak` get their instructions rewritten to use the surviving equivalents or are noted as "removed in 2026-04-20 CLI polish; use `remote validate --with-lvgl-soak`" where applicable.

### `pyproject.toml` gate paths

The `[tool.yoyopod_quality]` `gate_format_paths`, `gate_lint_paths`, `gate_type_paths` entries pointing at `src/yoyopod/cli/*` become `yoyopod_cli/` so the new CLI package stays under strict quality enforcement.

---

## 12. Migration / cutover plan

Low-risk because scope is well-contained to one package plus its tests and docs.

### Step sequence

1. **Scaffold** `yoyopod_cli/` with `paths.py`, `common.py`, `remote_shared.py`, `remote_transport.py`, empty `main.py` skeleton, `__init__.py`. No commands yet. Verify `python -c "import yoyopod_cli"` works.
2. **Rewire entry point.** `pyproject.toml`: `yoyopod = "yoyopod_cli.main:run"`. Remove `yoyopod` line. Verify `yoyopod --help` shows the skeleton.
3. **Port `build` + `setup` groups** (smallest, least cross-referenced — warm-up).
4. **Port `remote_ops`** (status, sync, restart, logs, screenshot) — proves the shared-options pattern on the hot path.
5. **Port `remote_config`, `remote_infra`, `remote_setup`** — rest of remote except validate.
6. **Port `remote_validate`** — fold `lvgl-soak` and `navigation-soak` in as `--with-*` flags.
7. **Port `pi_voip`, `pi_power`, `pi_network`** — small on-device groups.
8. **Port `pi_validate`** with the new `--soak {registration,reconnect,call}` flag absorbing the three soak commands.
9. **Add top-level shortcuts** (`deploy`, `status`, `logs`, `restart`, `validate`).
10. **Build `_docgen.py`** and generate `COMMANDS.md`.
11. **Delete `src/yoyopod/cli/`** in one commit. Update `pyproject.toml` quality-gate paths.
12. **Migrate tests** — import-path rewrites, monkeypatch target updates, delete tests for cut commands. Run `uv run python scripts/quality.py ci` to green.
13. **Doc sweep** — find-replace `yoyopod` → `yoyopod` across docs/skills/CLAUDE.md/rules. Note removed commands in relevant skills.
14. **Final verification** — full CI pass, `yoyopod pi validate deploy` + `yoyopod pi validate smoke` on real hardware.

### Risk notes

- **Tests that monkeypatch legacy paths are the biggest nuisance.** The current `cli/remote/ops/__init__.py` shim exists specifically for legacy test paths. New tests monkeypatch at the new module boundaries. ~15 lines to rewrite; no test logic changes.
- **Cold cutover means one painful day for anyone with `yoyopod` in muscle memory or personal scripts.** That's the user (and accepted).
- **Doc drift risk.** ~50 mentions of `yoyopod` across docs/skills. A single grep + find-replace catches most; human review catches the rest.
- **Steps 1–11 are pre-deletion.** You can run the new CLI end-to-end and exercise every command before anything gets deleted. Rollback is `git checkout` of steps 2–11.

---

## 13. Open questions

None at design time. All architectural decisions above are locked after the brainstorming round.

Implementation-level decisions (file-by-file call choices, exact helper signatures, minor YAML-merge details) are intentionally deferred to the writing-plans step.

---

## 14. References

- Current implementation: `src/yoyopod/cli/` (~8,800 lines, ~30 files)
- Reference layout: Hermes Agent `hermes_cli/` — flat package at repo root, bare-`hermes` launches app
- Superseded plan: `docs/superpowers/plans/2026-04-10-yoyopod-cli.md` (original scaffold plan)
- Related docs: `rules/project.md`, `rules/architecture.md`, `rules/deploy.md`
