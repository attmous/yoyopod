# Device Workspace And Python Runtime Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rename the Rust on-device workspace to `device/`, keep Python as the CLI operations layer, and remove the old Python app runtime from active ownership.

**Architecture:** `device/` becomes the only on-device runtime workspace and keeps the existing Rust runtime-plus-sidecars process model. `yoyopod_cli/` remains Python and owns build/deploy/release/remote validation; CLI-needed contracts are extracted from `yoyopod/` before old runtime code is quarantined or deleted. Production tests stay around CLI, deploy, config, scripts, and device contracts; old Python runtime tests are removed or parked under a legacy bucket.

**Tech Stack:** Rust Cargo workspace, Bazel BUILD files, Python `uv` CLI/deploy tooling, GitHub Actions, slot packaging, pytest, Black/Ruff/mypy quality gate.

---

## Source Spec

Implement this plan against:

- `docs/superpowers/specs/2026-05-06-device-python-runtime-cleanup-design.md`
- `docs/architecture/WORK_AREAS.md`
- `AGENTS.md`

## Phase Summary

1. `Phase 0`: Commit the spec/plan and add cleanup guard tests.
2. `Phase 1`: Rename `yoyopod_rs/` to `device/` and update active paths.
3. `Phase 2`: Extract CLI contracts from `yoyopod/` into `yoyopod_cli/`.
4. `Phase 3`: Remove Python runtime launch paths from the CLI and deploy docs.
5. `Phase 4`: Reshape tests into active tests and legacy runtime tests.
6. `Phase 5`: Quarantine or delete the Python runtime package.
7. `Phase 6`: Run final validation, push, and prepare hardware validation.

Each phase should be independently reviewable. Do not combine the `device/`
rename with the Python runtime deletion in one commit.

---

## Phase 0: Baseline And Guardrails

**Files:**

- Create: `docs/superpowers/specs/2026-05-06-device-python-runtime-cleanup-design.md`
- Create: `docs/superpowers/plans/2026-05-06-device-python-runtime-cleanup.md`
- Create: `tests/device/test_workspace_structure.py`
- Modify: `tests/cli/test_rust_workspace_structure.py`

### Task 0.1: Commit Spec And Plan

- [ ] **Step 1: Inspect planning diff**

Run:

```bash
git status --short --branch
git diff -- docs/superpowers/specs/2026-05-06-device-python-runtime-cleanup-design.md docs/superpowers/plans/2026-05-06-device-python-runtime-cleanup.md
```

Expected:

- only the new spec and plan are present
- no generated files are staged

- [ ] **Step 2: Run whitespace check**

Run:

```bash
git diff --check
```

Expected:

- exit code `0`

- [ ] **Step 3: Commit planning docs**

Run:

```bash
git add docs/superpowers/specs/2026-05-06-device-python-runtime-cleanup-design.md docs/superpowers/plans/2026-05-06-device-python-runtime-cleanup.md
git commit -m "docs: plan device workspace cleanup"
```

Expected:

- one docs-only commit exists

### Task 0.2: Add Device Workspace Guard Test

- [ ] **Step 1: Create `tests/device/`**

Run:

```powershell
New-Item -ItemType Directory -Force tests/device | Out-Null
```

- [ ] **Step 2: Move the existing Rust workspace structure test**

Run:

```bash
git mv tests/cli/test_rust_workspace_structure.py tests/device/test_workspace_structure.py
```

- [ ] **Step 3: Update the moved test to target `device/`**

Replace `tests/device/test_workspace_structure.py` with:

```python
from __future__ import annotations

from pathlib import Path

import tomllib


REPO_ROOT = Path(__file__).resolve().parents[2]
DEVICE_ROOT = REPO_ROOT / "device"


def _cargo_workspace_members() -> set[str]:
    with (DEVICE_ROOT / "Cargo.toml").open("rb") as handle:
        payload = tomllib.load(handle)
    return set(payload["workspace"]["members"])


def test_device_workspace_has_expected_manifest() -> None:
    assert (DEVICE_ROOT / "Cargo.toml").is_file()
    assert (DEVICE_ROOT / "Cargo.lock").is_file()


def test_device_workspace_has_no_generated_target_member() -> None:
    members = _cargo_workspace_members()

    assert "target" not in members
    assert not any(member.startswith("target/") for member in members)


def test_old_yoyopod_rs_workspace_is_gone() -> None:
    assert not (REPO_ROOT / "yoyopod_rs").exists()
```

- [ ] **Step 4: Keep a temporary compatibility test until Phase 1 completes**

Create `tests/cli/test_rust_workspace_structure.py` with:

```python
from __future__ import annotations


def test_rust_workspace_structure_tests_moved_to_device() -> None:
    """The active workspace structure tests live under tests/device."""

    assert True
```

This keeps test discovery stable before the `device/` rename commit. Delete this
temporary file in Phase 1 after the rename is complete.

- [ ] **Step 5: Run the new guard and confirm it fails before the rename**

Run:

```bash
uv run pytest -q tests/device/test_workspace_structure.py
```

Expected:

- fails because `device/Cargo.toml` does not exist yet

- [ ] **Step 6: Commit guard movement**

Run:

```bash
git add tests/device/test_workspace_structure.py tests/cli/test_rust_workspace_structure.py
git commit -m "test: add device workspace guard"
```

Expected:

- guard commit exists and documents the intended `device/` target

---

## Phase 1: Rename Rust Workspace To `device/`

**Files:**

- Move: `yoyopod_rs/` to `device/`
- Modify: `.github/workflows/ci.yml`
- Modify: `.dockerignore`
- Modify: `BUILD.bazel`
- Modify: `MODULE.bazel.lock`
- Modify: `AGENTS.md`
- Modify: `README.md`
- Modify: `docs/README.md`
- Modify: `docs/architecture/WORK_AREAS.md`
- Modify: `docs/operations/QUALITY_GATES.md`
- Modify: `skills/yoyopod-rust-artifact/SKILL.md`
- Modify: `config/voice/assistant.yaml`
- Modify: `deploy/docker/slot-builder.Dockerfile`
- Modify: `scripts/build_release.py`
- Modify: `scripts/build_slot_artifact_ci.sh`
- Modify: `yoyopod_cli/build.py`
- Modify: `yoyopod_cli/remote_release.py`
- Modify: `yoyopod_cli/remote_validate.py`
- Modify: `yoyopod_cli/slot_contract.py`
- Modify: `tests/cli/`
- Modify: `tests/deploy/`
- Modify: `tests/config/`
- Modify: `tests/scripts/`
- Modify: `tests/device/`

### Task 1.1: Move The Workspace Directory

- [ ] **Step 1: Confirm the worktree is clean**

Run:

```bash
git status --short --branch
```

Expected:

- no unstaged or staged source changes

- [ ] **Step 2: Move `yoyopod_rs/` to `device/`**

Run:

```bash
git mv yoyopod_rs device
```

Expected:

- Git records the directory move
- `device/Cargo.toml` exists
- `yoyopod_rs/` no longer exists

- [ ] **Step 3: Replace active path references**

Run this scan:

```bash
rg -n "yoyopod_rs" . -g "!docs/archive/**" -g "!docs/history/**" -g "!docs/superpowers/**" -g "!device/target/**"
```

Replace active references with `device`. Expected examples:

```text
cargo test --manifest-path device/Cargo.toml --workspace --locked
device/runtime/build/yoyopod-runtime
device/speech/build/yoyopod-speech-host
app/device/runtime/build/yoyopod-runtime
app/device/speech/build/yoyopod-speech-host
```

Historical docs under `docs/archive/`, `docs/history/`, and old
`docs/superpowers/` specs may keep `yoyopod_rs/` if they describe past work.

- [ ] **Step 4: Update root Bazel labels**

Update `BUILD.bazel` and all `device/*/BUILD.bazel` references so CI can run:

```text
//device/ui/...
//device/cloud/...
//device/media/...
//device/voip/...
//device/network/...
//device/power/...
//device/speech/...
//device/runtime/...
```

Expected:

- no active Bazel label starts with `//yoyopod_rs/`

- [ ] **Step 5: Update slot contract paths**

In `yoyopod_cli/slot_contract.py`, ensure the artifact constants use:

```python
SLOT_VOICE_WORKER_ARTIFACT = Path("app") / "device" / "speech" / "build" / "yoyopod-speech-host"

APP_NATIVE_RUNTIME_ARTIFACTS: tuple[Path, ...] = (
    Path("yoyopod") / "ui" / "lvgl_binding" / "native" / "build" / "libyoyopod_lvgl_shim.so",
    Path("yoyopod") / "ui" / "lvgl_binding" / "native" / "build" / "lvgl" / "lib" / "liblvgl.so.9",
    Path("device") / "cloud" / "build" / "yoyopod-cloud-host",
    Path("device") / "media" / "build" / "yoyopod-media-host",
    Path("device") / "voip" / "build" / "yoyopod-voip-host",
    Path("device") / "network" / "build" / "yoyopod-network-host",
    Path("device") / "power" / "build" / "yoyopod-power-host",
    Path("device") / "speech" / "build" / "yoyopod-speech-host",
    Path("device") / "runtime" / "build" / "yoyopod-runtime",
)
```

- [ ] **Step 6: Delete the temporary compatibility test**

Run:

```bash
git rm tests/cli/test_rust_workspace_structure.py
```

Expected:

- device workspace guard lives only at `tests/device/test_workspace_structure.py`

### Task 1.2: Validate The Rename

- [ ] **Step 1: Run Cargo metadata**

Run:

```bash
cargo metadata --manifest-path device/Cargo.toml --locked --no-deps
```

Expected:

- exit code `0`

- [ ] **Step 2: Run Rust workspace validation**

Run:

```bash
cargo test --manifest-path device/Cargo.toml --workspace --locked
cargo clippy --manifest-path device/Cargo.toml --workspace --all-targets --locked -- -D warnings
cargo fmt --manifest-path device/Cargo.toml --all --check
```

Expected:

- all commands pass

- [ ] **Step 3: Run path-sensitive Python tests**

Run:

```bash
uv run pytest -q tests/device tests/cli/test_yoyopod_cli_build.py tests/cli/test_slot_contract.py tests/cli/test_remote_release.py tests/deploy/test_ci_workflows.py tests/scripts/test_build_release.py tests/config/test_config_models.py -k "rust or device or slot or release or ci or voice or config"
```

Expected:

- all selected tests pass

- [ ] **Step 4: Build renamed artifacts**

Run:

```bash
uv run yoyopod build rust-runtime
uv run yoyopod build voice-worker
```

Expected:

- `device/runtime/build/yoyopod-runtime` exists on Linux/macOS or
  `device/runtime/build/yoyopod-runtime.exe` exists on Windows
- `device/speech/build/yoyopod-speech-host` exists on Linux/macOS or
  `device/speech/build/yoyopod-speech-host.exe` exists on Windows

- [ ] **Step 5: Ensure active old paths are gone**

Run:

```bash
rg -n "yoyopod_rs/" . -g "!docs/archive/**" -g "!docs/history/**" -g "!docs/superpowers/**" -g "!device/target/**"
```

Expected:

- no output except intentionally historical references if the path filters are
  adjusted

- [ ] **Step 6: Commit Phase 1**

Run:

```bash
git add .github .dockerignore BUILD.bazel MODULE.bazel.lock AGENTS.md README.md docs rules skills config deploy scripts tests yoyopod yoyopod_cli device
git commit -m "refactor: rename rust workspace to device"
```

Expected:

- one rename commit exists
- working tree is clean except ignored build output

---

## Phase 2: Extract CLI Contracts From `yoyopod/`

**Files:**

- Create: `yoyopod_cli/contracts/__init__.py`
- Create: `yoyopod_cli/contracts/setup.py`
- Create: `yoyopod_cli/contracts/release.py`
- Move: `yoyopod/_version.py` to `yoyopod_cli/_version.py`
- Modify: `pyproject.toml`
- Modify: `yoyopod_cli/__init__.py`
- Modify: `yoyopod_cli/health.py`
- Modify: `yoyopod_cli/release.py`
- Modify: `tests/cli/test_health.py`
- Modify: `tests/cli/test_remote_release.py`
- Modify: `tests/cli/test_setup_cli.py`
- Modify: `tests/cli/test_yoyopod_cli_main.py`
- Modify: `tests/cli/test_yoyopod_cli_release.py`
- Modify: `tests/deploy/test_install_release_shell.py`
- Move: `tests/core/test_release.py` to `tests/cli/test_release_contract.py`

### Task 2.1: Move Version Metadata Into `yoyopod_cli`

- [ ] **Step 1: Move the version file**

Run:

```bash
git mv yoyopod/_version.py yoyopod_cli/_version.py
```

- [ ] **Step 2: Update package version metadata**

In `pyproject.toml`, change:

```toml
[tool.hatch.version]
path = "yoyopod_cli/_version.py"
```

- [ ] **Step 3: Update CLI version import**

In `yoyopod_cli/__init__.py`, use:

```python
"""yoyopod_cli - flat CLI package for YoYoPod.

Entry point is `yoyopod_cli.main:run`. See COMMANDS.md for the full command reference.
"""

from __future__ import annotations

from yoyopod_cli._version import __version__ as __version__
```

- [ ] **Step 4: Update release command version file path**

In `yoyopod_cli/release.py`, set:

```python
_VERSION_FILE = REPO_ROOT / "yoyopod_cli" / "_version.py"
```

- [ ] **Step 5: Update tests importing the version**

Replace:

```python
from yoyopod._version import __version__
```

with:

```python
from yoyopod_cli._version import __version__
```

in:

```text
tests/cli/test_yoyopod_cli_main.py
tests/cli/test_yoyopod_cli_release.py
```

- [ ] **Step 6: Run version tests**

Run:

```bash
uv run pytest -q tests/cli/test_yoyopod_cli_bootstrap.py tests/cli/test_yoyopod_cli_main.py::test_version_flag_prints_version tests/cli/test_yoyopod_cli_release.py
```

Expected:

- all selected tests pass

### Task 2.2: Move Setup Contract Into `yoyopod_cli/contracts`

- [ ] **Step 1: Create the contracts package**

Create `yoyopod_cli/contracts/__init__.py`:

```python
"""Production contracts shared by the Python CLI and deploy tooling."""

from __future__ import annotations

from yoyopod_cli.contracts.setup import (
    RUNTIME_REQUIRED_CONFIG_FILES,
    SETUP_TRACKED_CONFIG_FILES,
)

__all__ = [
    "RUNTIME_REQUIRED_CONFIG_FILES",
    "SETUP_TRACKED_CONFIG_FILES",
]
```

- [ ] **Step 2: Move setup contract code**

Create `yoyopod_cli/contracts/setup.py`:

```python
"""Shared setup and boot-time config contract for YoYoPod slots."""

from __future__ import annotations

from pathlib import Path

RUNTIME_REQUIRED_CONFIG_FILES: tuple[Path, ...] = (
    Path("config/app/core.yaml"),
    Path("config/audio/music.yaml"),
    Path("config/device/hardware.yaml"),
    Path("config/power/backend.yaml"),
    Path("config/network/cellular.yaml"),
    Path("config/voice/assistant.yaml"),
    Path("config/communication/calling.yaml"),
    Path("config/communication/messaging.yaml"),
    Path("config/people/directory.yaml"),
)

SETUP_TRACKED_CONFIG_FILES: tuple[Path, ...] = (
    *RUNTIME_REQUIRED_CONFIG_FILES,
    Path("config/communication/calling.secrets.example.yaml"),
    Path("config/communication/integrations/liblinphone_factory.conf"),
    Path("config/people/contacts.seed.yaml"),
    Path("deploy/pi-deploy.yaml"),
)
```

- [ ] **Step 3: Update active imports**

Replace:

```python
from yoyopod.core.setup_contract import RUNTIME_REQUIRED_CONFIG_FILES
```

with:

```python
from yoyopod_cli.contracts.setup import RUNTIME_REQUIRED_CONFIG_FILES
```

Replace:

```python
from yoyopod.core import RUNTIME_REQUIRED_CONFIG_FILES
```

with:

```python
from yoyopod_cli.contracts.setup import RUNTIME_REQUIRED_CONFIG_FILES
```

in:

```text
yoyopod_cli/health.py
tests/cli/test_health.py
tests/cli/test_remote_release.py
tests/cli/test_setup_cli.py
tests/deploy/test_install_release_shell.py
```

- [ ] **Step 4: Keep the old setup module as a temporary re-export**

Replace `yoyopod/core/setup_contract.py` with:

```python
"""Compatibility re-export for setup contracts.

Active CLI and deploy code should import from `yoyopod_cli.contracts.setup`.
"""

from __future__ import annotations

from yoyopod_cli.contracts.setup import (
    RUNTIME_REQUIRED_CONFIG_FILES,
    SETUP_TRACKED_CONFIG_FILES,
)

__all__ = [
    "RUNTIME_REQUIRED_CONFIG_FILES",
    "SETUP_TRACKED_CONFIG_FILES",
]
```

Delete this file during the legacy runtime deletion phase.

- [ ] **Step 5: Run setup/health tests**

Run:

```bash
uv run pytest -q tests/cli/test_health.py tests/cli/test_remote_release.py tests/cli/test_setup_cli.py tests/deploy/test_install_release_shell.py
```

Expected:

- all tests pass

### Task 2.3: Move Release Metadata Contract

- [ ] **Step 1: Create release contract module**

Create `yoyopod_cli/contracts/release.py`:

```python
"""Release metadata helpers used by CLI health checks."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ReleaseInfo:
    """A subset of the manifest the running service cares about."""

    version: str
    channel: str
    released_at: str

    def __post_init__(self) -> None:
        if not isinstance(self.version, str):
            raise ValueError(f"version must be str, got {type(self.version).__name__}")
        if not isinstance(self.channel, str):
            raise ValueError(f"channel must be str, got {type(self.channel).__name__}")
        if not isinstance(self.released_at, str):
            raise ValueError(f"released_at must be str, got {type(self.released_at).__name__}")


_DEFAULT_MANIFEST_PATH = "/opt/yoyopod/current/manifest.json"


def _manifest_path() -> Path:
    return Path(os.environ.get("YOYOPOD_RELEASE_MANIFEST", _DEFAULT_MANIFEST_PATH))


def current_release() -> ReleaseInfo | None:
    """Return the currently-running release, or None if not in a slot deploy."""

    path = _manifest_path()
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text())
        if not isinstance(raw, dict):
            return None
        return ReleaseInfo(
            version=raw["version"],
            channel=raw["channel"],
            released_at=raw["released_at"],
        )
    except (OSError, ValueError, KeyError):
        return None


def state_dir() -> Path:
    """Return the persistent state directory for CLI/deploy consumers."""

    override = os.environ.get("YOYOPOD_STATE_DIR")
    if override:
        return Path(override)
    return Path.home() / ".local" / "share" / "yoyopod"
```

- [ ] **Step 2: Update health import**

In `yoyopod_cli/health.py`, replace:

```python
from yoyopod.core.release import current_release
```

with:

```python
from yoyopod_cli.contracts.release import current_release
```

Also update the module docstring line so it says:

```text
live: reads YOYOPOD_RELEASE_MANIFEST (via yoyopod_cli.contracts.release.current_release)
```

- [ ] **Step 3: Move release tests to CLI**

Run:

```bash
git mv tests/core/test_release.py tests/cli/test_release_contract.py
```

In `tests/cli/test_release_contract.py`, replace imports from:

```python
from yoyopod.core.release import (
    ReleaseInfo,
    current_release,
    state_dir,
)
```

to:

```python
from yoyopod_cli.contracts.release import (
    ReleaseInfo,
    current_release,
    state_dir,
)
```

- [ ] **Step 4: Keep the old release module as a temporary re-export**

Replace `yoyopod/core/release.py` with:

```python
"""Compatibility re-export for release metadata helpers.

Active CLI code should import from `yoyopod_cli.contracts.release`.
"""

from __future__ import annotations

from yoyopod_cli.contracts.release import ReleaseInfo, current_release, state_dir

__all__ = [
    "ReleaseInfo",
    "current_release",
    "state_dir",
]
```

Delete this file during the legacy runtime deletion phase.

- [ ] **Step 5: Run release contract tests**

Run:

```bash
uv run pytest -q tests/cli/test_release_contract.py tests/cli/test_health.py::test_live_reports_current_release_from_env
```

Expected:

- all selected tests pass

### Task 2.4: Validate CLI Contract Extraction

- [ ] **Step 1: Scan active CLI imports**

Run:

```bash
rg -n "from yoyopod\\.|import yoyopod|yoyopod\\." yoyopod_cli tests/cli tests/deploy -g "*.py"
```

Expected at this phase:

- no `yoyopod_cli/` imports from `yoyopod.*` except the runtime launch fallback
  in `yoyopod_cli/main.py`, which Phase 3 removes
- tests may still import `yoyopod.*` only for legacy runtime coverage

- [ ] **Step 2: Run quality gate**

Run:

```bash
uv run python scripts/quality.py gate
```

Expected:

- exit code `0`

- [ ] **Step 3: Commit Phase 2**

Run:

```bash
git add pyproject.toml yoyopod_cli yoyopod tests yoyopod/core/setup_contract.py yoyopod/core/release.py
git commit -m "refactor(cli): extract runtime contracts"
```

Expected:

- CLI contracts live under `yoyopod_cli/contracts`

---

## Phase 3: Remove Python Runtime Launch Paths

**Files:**

- Modify: `yoyopod_cli/main.py`
- Modify: `yoyopod_cli/paths.py`
- Modify: `yoyopod_cli/remote_config.py`
- Modify: `yoyopod_cli/remote_ops.py`
- Modify: `deploy/systemd/yoyopod-dev.service`
- Modify: `deploy/scripts/launch.sh`
- Modify: `docs/operations/DEV_PROD_LANES.md`
- Modify: `docs/operations/PI_DEV_WORKFLOW.md`
- Modify: `README.md`
- Modify: `tests/cli/test_yoyopod_cli_main.py`
- Modify: `tests/cli/test_yoyopod_cli_paths.py`
- Modify: `tests/cli/test_remote_config_helpers.py`
- Modify: `tests/cli/test_yoyopod_cli_remote_ops.py`

### Task 3.1: Make Root CLI Show Help Instead Of Launching Python

- [ ] **Step 1: Update CLI root behavior**

In `yoyopod_cli/main.py`, change the root Typer app to:

```python
app = typer.Typer(
    name="yoyopod",
    help="YoYoPod operations CLI.",
    no_args_is_help=True,
    add_completion=False,
)
```

Replace `_root` with:

```python
@app.callback(invoke_without_command=True)
def _root(
    ctx: typer.Context,
    version: bool = typer.Option(
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show version and exit.",
    ),
) -> None:
    """Run YoYoPod operations commands."""

    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit(0)
```

Remove this import path entirely:

```python
from yoyopod.main import main as launch_app
```

- [ ] **Step 2: Update CLI root tests**

In `tests/cli/test_yoyopod_cli_main.py`, replace no-subcommand launch tests with:

```python
def test_no_subcommand_prints_help() -> None:
    result = runner.invoke(app)

    assert result.exit_code == 0
    assert "YoYoPod operations CLI" in result.output
    assert "build" in result.output
    assert "remote" in result.output
```

Delete tests that monkeypatch `sys.modules["yoyopod.main"]`.

- [ ] **Step 3: Run CLI root tests**

Run:

```bash
uv run pytest -q tests/cli/test_yoyopod_cli_main.py
```

Expected:

- all tests pass

### Task 3.2: Remove Supported Python App Process Defaults

- [ ] **Step 1: Inspect process defaults**

Run:

```bash
rg -n "python yoyopod.py|yoyopod.py --simulate|YOYOPOD_DEV_RUNTIME=python|YOYOPOD_DEV_RUNTIME" yoyopod_cli deploy docs README.md tests -g "*"
```

- [ ] **Step 2: Update process default tests**

In `tests/cli/test_yoyopod_cli_paths.py`, replace expectations like:

```python
assert PROCS.app == "python yoyopod.py"
```

with the Rust runtime command:

```python
assert PROCS.app == "device/runtime/build/yoyopod-runtime --config-dir config"
```

If `PROCS.app` is only used for documentation output, use the exact string
implemented in `yoyopod_cli/paths.py`.

- [ ] **Step 3: Update remote config helper tests**

In `tests/cli/test_remote_config_helpers.py`, replace fixture YAML containing:

```yaml
start_cmd: python yoyopod.py
```

with:

```yaml
start_cmd: device/runtime/build/yoyopod-runtime --config-dir config
```

- [ ] **Step 4: Update remote ops tests**

In `tests/cli/test_yoyopod_cli_remote_ops.py`, replace:

```python
start_cmd="python yoyopod.py --simulate"
```

with:

```python
start_cmd="device/runtime/build/yoyopod-runtime --config-dir config"
```

Keep the negative assertion but update it to:

```python
assert "python yoyopod.py" not in shell
```

- [ ] **Step 5: Update CLI/deploy implementation**

Update `yoyopod_cli/paths.py`, `yoyopod_cli/remote_config.py`, and
`yoyopod_cli/remote_ops.py` so default app process command values use the Rust
runtime path:

```text
device/runtime/build/yoyopod-runtime --config-dir config
```

If a path must be slot-relative, use:

```text
app/device/runtime/build/yoyopod-runtime --config-dir config
```

- [ ] **Step 6: Run launch-path tests**

Run:

```bash
uv run pytest -q tests/cli/test_yoyopod_cli_paths.py tests/cli/test_remote_config_helpers.py tests/cli/test_yoyopod_cli_remote_ops.py
```

Expected:

- all tests pass

### Task 3.3: Validate Python Runtime Launch Path Removal

- [ ] **Step 1: Run active launch scans**

Run:

```bash
rg -n "python yoyopod.py|yoyopod.py --simulate|from yoyopod.main|import yoyopod.main" yoyopod_cli deploy docs README.md tests/cli tests/deploy -g "*"
```

Expected:

- no output in active CLI/deploy/docs/tests

- [ ] **Step 2: Run focused CLI/deploy validation**

Run:

```bash
uv run python scripts/quality.py gate
uv run pytest -q tests/cli tests/deploy tests/scripts
```

Expected:

- all tests pass

- [ ] **Step 3: Commit Phase 3**

Run:

```bash
git add yoyopod_cli deploy docs README.md tests/cli tests/deploy tests/scripts
git commit -m "refactor(cli): remove python runtime launch path"
```

Expected:

- no supported CLI path launches the old Python app runtime

---

## Phase 4: Test Tree Cleanup

**Files:**

- Create: `tests/legacy_python_runtime/README.md` if quarantine is used
- Move or delete: `tests/e2e/`
- Move or delete: `tests/backends/`
- Move or delete: `tests/core/`
- Move or delete: `tests/integrations/`
- Move or delete: `tests/ui/`
- Keep: `tests/cli/`
- Keep: `tests/deploy/`
- Keep: `tests/config/`
- Keep: `tests/device/`
- Keep: `tests/scripts/`

### Task 4.1: Classify Existing Test Directories

- [ ] **Step 1: Count test files by directory**

Run:

```bash
Get-ChildItem tests -Recurse -Filter "test_*.py" | ForEach-Object {
  $_.FullName.Replace((Resolve-Path tests).Path + [IO.Path]::DirectorySeparatorChar, "")
} | ForEach-Object {
  ($_ -split "[/\\]")[0]
} | Group-Object | Sort-Object Name
```

Expected:

- visible counts for `cli`, `deploy`, `config`, `device`, `scripts`, and legacy
  runtime-oriented directories

- [ ] **Step 2: List remaining direct `yoyopod.*` imports outside kept folders**

Run:

```bash
rg -n "from yoyopod\\.|import yoyopod|yoyopod\\." tests/e2e tests/backends tests/core tests/integrations tests/ui -g "*.py"
```

Expected:

- output identifies old Python runtime tests

### Task 4.2: Quarantine Python Runtime Tests

- [ ] **Step 1: Create legacy test bucket**

Run:

```powershell
New-Item -ItemType Directory -Force tests/legacy_python_runtime | Out-Null
```

Create `tests/legacy_python_runtime/README.md`:

```markdown
# Legacy Python Runtime Tests

These tests cover the retired Python app runtime. They are not part of the
supported Rust device runtime or Python CLI operations gate.

Keep this directory only while reviewing old behavior for parity. Delete it when
the cleanup reaches the final deletion phase.
```

- [ ] **Step 2: Move legacy runtime test directories**

Run:

```bash
git mv tests/e2e tests/legacy_python_runtime/e2e
git mv tests/backends tests/legacy_python_runtime/backends
git mv tests/core tests/legacy_python_runtime/core
git mv tests/integrations tests/legacy_python_runtime/integrations
git mv tests/ui tests/legacy_python_runtime/ui
```

If a directory is already absent, skip only that directory and continue.

- [ ] **Step 3: Restore active tests accidentally moved**

Move these files back if they were in moved directories and still protect active
CLI/deploy contracts:

```text
tests/legacy_python_runtime/core/test_release.py -> already moved to tests/cli/test_release_contract.py in Phase 2
```

Expected:

- no active release/setup/health contract tests remain inside
  `tests/legacy_python_runtime/`

- [ ] **Step 4: Update pytest configuration if needed**

In `pyproject.toml`, keep:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
```

Add this only if the legacy tests should be excluded from default pytest:

```toml
norecursedirs = ["tests/legacy_python_runtime"]
```

### Task 4.3: Validate Active Test Set

- [ ] **Step 1: Run active tests only**

Run:

```bash
uv run pytest -q tests/cli tests/deploy tests/config tests/device tests/scripts
```

Expected:

- all active tests pass

- [ ] **Step 2: Scan active tests for old runtime launch paths**

Run:

```bash
rg -n "python yoyopod.py|from yoyopod\\.app|from yoyopod\\.main|import yoyopod\\.main" tests/cli tests/deploy tests/config tests/device tests/scripts -g "*.py"
```

Expected:

- no output

- [ ] **Step 3: Commit Phase 4**

Run:

```bash
git add pyproject.toml tests
git commit -m "test: isolate legacy python runtime coverage"
```

Expected:

- active test tree protects only current CLI/deploy/config/device/script
  behavior

---

## Phase 5: Legacy Python Runtime Quarantine Or Deletion

**Files:**

- Move or delete: `yoyopod/`
- Move or delete: `yoyopod.py`
- Create: `legacy/python-runtime/README.md` if quarantine is used
- Modify: `pyproject.toml`
- Modify: `docs/`
- Modify: `AGENTS.md`
- Modify: `rules/`

### Task 5.1: Verify Active Code No Longer Imports `yoyopod/`

- [ ] **Step 1: Scan active code**

Run:

```bash
rg -n "from yoyopod\\.|import yoyopod|yoyopod\\." yoyopod_cli deploy scripts tests/cli tests/deploy tests/config tests/device tests/scripts -g "*.py"
```

Expected:

- no output

- [ ] **Step 2: Scan active docs and deploy files for Python runtime ownership**

Run:

```bash
rg -n "python yoyopod.py|Python runtime|legacy Python runtime|yoyopod/" README.md AGENTS.md docs rules deploy config scripts yoyopod_cli tests -g "!tests/legacy_python_runtime/**"
```

Expected:

- no statement describes Python as the app runtime owner
- references to `yoyopod_cli/` are allowed
- references to package name `yoyopod` in release artifact names are allowed

### Task 5.2: Quarantine The Python Runtime

- [ ] **Step 1: Create legacy runtime directory**

Run:

```powershell
New-Item -ItemType Directory -Force legacy/python-runtime | Out-Null
```

Create `legacy/python-runtime/README.md`:

```markdown
# Legacy Python Runtime

This directory contains the retired Python app runtime. It is not a supported
runtime owner for the device.

Supported runtime code lives under `device/`. Supported operations tooling lives
under `yoyopod_cli/`.

Do not import this directory from active code. Delete it after final parity and
hardware validation are complete.
```

- [ ] **Step 2: Move old runtime package**

Run:

```bash
git mv yoyopod legacy/python-runtime/yoyopod
git mv yoyopod.py legacy/python-runtime/yoyopod.py
```

- [ ] **Step 3: Update packaging metadata**

In `pyproject.toml`, keep only `yoyopod_cli` as an active wheel package:

```toml
[tool.hatch.build.targets.wheel]
packages = ["yoyopod_cli"]
```

Update sdist include list:

```toml
[tool.hatch.build.targets.sdist]
include = [
    "/README.md",
    "/pyproject.toml",
    "/yoyopod_cli",
]
```

Expected:

- the retired Python runtime is not packaged as active app code

- [ ] **Step 4: Run packaging and CLI tests**

Run:

```bash
uv run python scripts/quality.py gate
uv run pytest -q tests/cli tests/deploy tests/config tests/device tests/scripts
```

Expected:

- all active tests pass

### Task 5.3: Decide Delete Or Keep Temporary Legacy

- [ ] **Step 1: If keeping legacy temporarily, commit quarantine**

Run:

```bash
git add legacy pyproject.toml docs AGENTS.md rules tests
git commit -m "refactor: quarantine legacy python runtime"
```

Expected:

- old runtime exists only under `legacy/python-runtime/`

- [ ] **Step 2: If deleting immediately, remove legacy runtime and legacy tests**

Run:

```bash
git rm -r legacy/python-runtime tests/legacy_python_runtime
git commit -m "refactor: remove legacy python runtime"
```

Expected:

- no old Python runtime code remains
- no legacy Python runtime tests remain

Choose either Step 1 or Step 2 for this phase. Do not do both in the same
commit.

---

## Phase 6: Final Validation And Handoff

**Files:**

- No planned source files.
- Modify PR body only if validation results require it.

### Task 6.1: Full Local Validation

- [ ] **Step 1: Run Rust validation**

Run:

```bash
cargo test --manifest-path device/Cargo.toml --workspace --locked
cargo clippy --manifest-path device/Cargo.toml --workspace --all-targets --locked -- -D warnings
cargo fmt --manifest-path device/Cargo.toml --all --check
```

Expected:

- all commands pass

- [ ] **Step 2: Run Python CLI validation**

Run:

```bash
uv run python scripts/quality.py gate
uv run pytest -q tests/cli tests/deploy tests/config tests/device tests/scripts
```

Expected:

- all active tests pass

- [ ] **Step 3: Build artifacts**

Run:

```bash
uv run yoyopod build rust-runtime
uv run yoyopod build voice-worker
```

Expected:

- `device/runtime/build/yoyopod-runtime` exists on Linux/macOS or
  `device/runtime/build/yoyopod-runtime.exe` exists on Windows
- `device/speech/build/yoyopod-speech-host` exists on Linux/macOS or
  `device/speech/build/yoyopod-speech-host.exe` exists on Windows

- [ ] **Step 4: Run deletion/path scans**

Run:

```bash
rg -n "yoyopod_rs/" . -g "!docs/archive/**" -g "!docs/history/**" -g "!docs/superpowers/**" -g "!device/target/**"
rg -n "python yoyopod.py|yoyopod.py --simulate|from yoyopod\\.main|import yoyopod\\.main" . -g "!legacy/**" -g "!tests/legacy_python_runtime/**"
rg -n "from yoyopod\\.|import yoyopod|yoyopod\\." yoyopod_cli deploy scripts tests/cli tests/deploy tests/config tests/device tests/scripts -g "*.py"
git diff --check
git ls-files -ci --exclude-standard
```

Expected:

- path scans have no active-source output
- `git diff --check` passes
- `git ls-files -ci --exclude-standard` prints nothing

### Task 6.2: CI And Hardware Prep

- [ ] **Step 1: Push branch**

Run:

```bash
BRANCH="$(git branch --show-current)"
COMMIT="$(git rev-parse HEAD)"
git push -u origin "$BRANCH"
printf 'branch=%s\ncommit=%s\n' "$BRANCH" "$COMMIT"
```

Expected:

- branch is pushed
- commit SHA is recorded for validation

- [ ] **Step 2: Confirm CI**

Run:

```bash
gh pr checks --watch --interval 15
```

Expected:

- `quality` passes
- `test` passes
- `rust-device-arm64` passes
- slot/release artifact job passes or is skipped according to workflow rules

- [ ] **Step 3: Prepare hardware validation note**

Use this note in the PR:

```markdown
## Hardware Validation

- Branch: `<branch>`
- Commit: `<commit>`
- Runtime artifact: `device/runtime/build/yoyopod-runtime`
- Worker artifacts: `device/*/build/yoyopod-*-host`
- Command: `yoyopod remote validate --branch <branch> --sha <commit>`
- Result: record exact pass/fail output from the Pi.
```

---

## Review Checklist

Before merging the cleanup:

- [ ] `device/` exists and `yoyopod_rs/` does not exist in active source paths.
- [ ] Deployed binary names remain `yoyopod-runtime` and `yoyopod-*-host`.
- [ ] `yoyopod_cli/` imports no old Python runtime modules.
- [ ] `uv run yoyopod` with no subcommand prints operations CLI help.
- [ ] No active CLI/deploy path launches `python yoyopod.py`.
- [ ] `tests/device/` owns device workspace tests.
- [ ] Active tests are limited to `tests/cli`, `tests/deploy`, `tests/config`,
      `tests/device`, and `tests/scripts`.
- [ ] Legacy Python runtime tests are quarantined or deleted.
- [ ] Slot packaging uses `device/*/build/` artifact paths.
- [ ] CI workflows use `device/...` Cargo/Bazel paths.
- [ ] Local Rust, Python CLI, artifact build, and path-scan validation passes.
