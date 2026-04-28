# Rust UI Host Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Promote the Rust Whisplay UI path into a production Rust UI host under top-level `src/`, then make it the exclusive owner of UI state, display, and input while Python remains the app/runtime service owner.

**Architecture:** The Rust UI Host runs as a supervised process while Python owns music, call, voice, power, network, config, and process supervision. Python sends normalized runtime snapshots and receives narrow UI intents; Rust owns display/input hardware, screen routing, focus, transitions, one-button gestures, rendering, and UI health. The first production source move keeps behavior unchanged, then Python boot gains a Rust UI mode that skips Python display/input/screen ownership.

**Tech Stack:** Rust 2021, Cargo workspace under `src/`, `rppal`, `serde`, `serde_json`, LVGL native C shim via `libloading`, Python 3.12, Typer CLI, pytest, GitHub Actions ARM64 runner, Raspberry Pi Zero 2W Whisplay hardware.

---

## Scope Check

This plan implements one cohesive subsystem migration: Rust UI ownership. It intentionally does not move music/mpv, VoIP/liblinphone, power, network, location, or voice runtime ownership into Rust. Those remain Python-owned runtime services until the UI host is stable.

## Required Execution Rules

- Do not run Rust builds on the Pi Zero.
- For target validation, use the GitHub Actions `ui-rust` artifact for the exact pushed commit.
- Rust code must be idiomatic and human readable: run `rustfmt`, keep modules narrow, prefer descriptive names, use explicit errors, and avoid clever abstractions unless they remove real complexity.
- Before every commit and every push, run:

```bash
uv run python scripts/quality.py gate
uv run pytest -q
```

- For Rust changes, also run the relevant Cargo commands from the new top-level Rust workspace:

```bash
cargo fmt --manifest-path src/Cargo.toml
cargo test --manifest-path src/Cargo.toml --workspace --locked
cargo test --manifest-path src/Cargo.toml --workspace --features whisplay-hardware --locked
```

## File Structure

Create or modify these files during the full implementation:

- Create: `src/Cargo.toml` - production Rust workspace root.
- Move: `workers/ui/rust/Cargo.lock` -> `src/Cargo.lock`.
- Move: `workers/ui/rust/Cargo.toml` -> `src/crates/ui-host/Cargo.toml`.
- Move: `workers/ui/rust/src/**` -> `src/crates/ui-host/src/**`.
- Modify: `.github/workflows/ci.yml` - build/test/upload `yoyopod-ui-host` from `src/`.
- Modify: `yoyopod_cli/build.py` - add `rust-ui-host` build command and keep `rust-ui-poc` as a compatibility alias.
- Modify: `yoyopod_cli/pi/__init__.py` - register `rust-ui-host` command and keep `rust-ui-poc` alias.
- Create: `yoyopod_cli/pi/rust_ui_host.py` - target-side UI host smoke command.
- Modify: `yoyopod_cli/pi/rust_ui_poc.py` - compatibility import/wrapper for the renamed command.
- Modify: `yoyopod_cli/remote_validate.py` and CLI shortcut tests - use the new UI host path.
- Modify: `yoyopod/config/models/app.py` - add Rust UI host config fields with compatibility for existing sidecar env names.
- Create: `yoyopod/ui/rust_host/__init__.py`.
- Create: `yoyopod/ui/rust_host/facade.py`.
- Create: `yoyopod/ui/rust_host/snapshot.py`.
- Create: `yoyopod/ui/rust_host/intents.py`.
- Create: `yoyopod/ui/rust_host/protocol.py`.
- Modify: `yoyopod/ui/rust_sidecar/__init__.py`, `coordinator.py`, `state.py`, `protocol.py`, `supervisor.py` - compatibility re-exports after the new package exists.
- Modify: `yoyopod/core/application.py` - add `rust_ui_host` runtime field.
- Modify: `yoyopod/core/bootstrap/components_boot.py` - support Rust UI mode without Python display/input/screen ownership.
- Modify: `yoyopod/core/bootstrap/__init__.py` - wire Rust UI host setup after managers/runtime helpers exist.
- Modify: `yoyopod/core/bootstrap/runtime_helpers_boot.py` - support screenless app-state helper setup.
- Modify: `yoyopod/core/bootstrap/screens_boot.py` - extract screen-independent voice runtime setup or skip screen construction cleanly in Rust UI mode.
- Modify: `yoyopod/core/event_subscriptions.py` - subscribe Rust UI host worker messages.
- Modify: `yoyopod/core/loop.py` - tick Rust UI host and send snapshots from the coordinator loop.
- Create: `docs/RUST_UI_HOST.md` - current Rust UI Host build/deploy contract.
- Modify: `docs/RUST_UI_POC.md` - short compatibility note pointing to `docs/RUST_UI_HOST.md`.
- Modify: `yoyopod_cli/COMMANDS.md` via `uv run yoyopod dev docs`.
- Test: `tests/cli/test_yoyopod_cli_build.py`.
- Create: `tests/cli/test_pi_rust_ui_host.py`.
- Modify: `tests/cli/test_pi_rust_ui_poc.py` - compatibility alias tests.
- Test: `tests/cli/test_yoyopod_cli_remote_validate.py`.
- Test: `tests/config/test_config_models.py`.
- Test: `tests/ui/test_rust_sidecar_*.py` and new `tests/ui/test_rust_host_*.py`.
- Create: `tests/core/bootstrap/test_rust_ui_host_boot.py`.

## Task 1: Move Rust UI Source To `src/` And Rename The Crate

**Files:**
- Create: `src/Cargo.toml`
- Move: `workers/ui/rust/Cargo.lock` -> `src/Cargo.lock`
- Move: `workers/ui/rust/Cargo.toml` -> `src/crates/ui-host/Cargo.toml`
- Move: `workers/ui/rust/src/**` -> `src/crates/ui-host/src/**`
- Modify: `src/crates/ui-host/Cargo.toml`
- Test: Rust crate tests under `src/crates/ui-host/src/**`

- [ ] **Step 1: Verify the old Rust crate is the only Rust UI source**

Run:

```bash
rg --files workers/ui/rust
Test-Path src
```

Expected: Rust UI sources are under `workers/ui/rust`; `src/Cargo.toml` does not exist before this task starts.

- [ ] **Step 2: Move the crate with Git tracking**

Run from the repo root:

```bash
New-Item -ItemType Directory -Force src/crates/ui-host
git mv workers/ui/rust/Cargo.toml src/crates/ui-host/Cargo.toml
git mv workers/ui/rust/Cargo.lock src/Cargo.lock
git mv workers/ui/rust/src src/crates/ui-host/src
```

If `workers/ui/rust` is now empty, remove only the empty directories:

```bash
Remove-Item -LiteralPath workers/ui/rust -Force
Remove-Item -LiteralPath workers/ui -Force
```

Expected: `git status --short` shows renames or deletes/adds for the Rust crate files and no production Rust source remains under `workers/ui/rust`.

- [ ] **Step 3: Create the top-level Rust workspace manifest**

Create `src/Cargo.toml`:

```toml
[workspace]
resolver = "2"
members = [
    "crates/ui-host",
]
```

- [ ] **Step 4: Rename the crate and binary**

Edit `src/crates/ui-host/Cargo.toml` so the package and binary are named `yoyopod-ui-host`:

```toml
[package]
name = "yoyopod-ui-host"
version = "0.1.0"
edition = "2021"
rust-version = "1.82"

[[bin]]
name = "yoyopod-ui-host"
path = "src/main.rs"
```

Keep the existing dependencies and features after that block:

```toml
[dependencies]
anyhow = "1.0"
clap = { version = "4.5", features = ["derive"] }
embedded-graphics = "0.8.2"
libloading = "0.8"
serde = { version = "1.0", features = ["derive"] }
serde_json = "1.0"
thiserror = "2.0"

[target.'cfg(target_os = "linux")'.dependencies]
rppal = { version = "0.22.1", optional = true }

[features]
default = []
whisplay-hardware = ["dep:rppal"]
```

- [ ] **Step 5: Update the Clap command name**

In `src/crates/ui-host/src/main.rs`, replace:

```rust
#[command(name = "yoyopod-rust-ui-poc")]
#[command(about = "Whisplay-only Rust UI hardware I/O proof of concept")]
```

with:

```rust
#[command(name = "yoyopod-ui-host")]
#[command(about = "Whisplay Rust UI host")]
```

- [ ] **Step 6: Refresh the lockfile for the renamed package**

Run:

```bash
cargo generate-lockfile --manifest-path src/Cargo.toml
```

Expected: `src/Cargo.lock` references `name = "yoyopod-ui-host"` and not `name = "yoyopod-rust-ui-poc"`.

- [ ] **Step 7: Run Rust formatting and tests from the new workspace**

Run:

```bash
cargo fmt --manifest-path src/Cargo.toml
cargo test --manifest-path src/Cargo.toml --workspace --locked
cargo test --manifest-path src/Cargo.toml --workspace --features whisplay-hardware --locked
```

Expected: all Rust tests pass from the new `src/` workspace.

- [ ] **Step 8: Run mandatory repo gates**

Run:

```bash
uv run python scripts/quality.py gate
uv run pytest -q
```

Expected: quality gate passes and pytest reports the full suite passing.

- [ ] **Step 9: Commit the move**

Run:

```bash
git add src workers/ui/rust workers/ui
git commit -m "refactor: move rust ui host to src workspace"
```

Expected: commit contains only the Rust source move, crate rename, and workspace manifest.

## Task 2: Update CI, Build CLI, Pi Command, And Docs For `yoyopod-ui-host`

**Files:**
- Modify: `.github/workflows/ci.yml`
- Modify: `yoyopod_cli/build.py`
- Modify: `tests/cli/test_yoyopod_cli_build.py`
- Create: `yoyopod_cli/pi/rust_ui_host.py`
- Modify: `yoyopod_cli/pi/rust_ui_poc.py`
- Modify: `yoyopod_cli/pi/__init__.py`
- Create: `tests/cli/test_pi_rust_ui_host.py`
- Modify: `tests/cli/test_pi_rust_ui_poc.py`
- Modify: `yoyopod_cli/remote_validate.py`
- Modify: `tests/cli/test_yoyopod_cli_remote_validate.py`
- Modify: `tests/cli/test_yoyopod_cli_shortcuts.py`
- Create: `docs/RUST_UI_HOST.md`
- Modify: `docs/RUST_UI_POC.md`
- Modify: `yoyopod_cli/COMMANDS.md`

- [ ] **Step 1: Write failing build CLI tests for the new command and path**

In `tests/cli/test_yoyopod_cli_build.py`, add:

```python
def test_rust_ui_host_build_help() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["rust-ui-host", "--help"])

    assert result.exit_code == 0
    assert "rust ui host" in result.output.lower()


def test_build_rust_ui_host_invokes_cargo_workspace(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace_dir = tmp_path / "src"
    crate_dir = workspace_dir / "crates" / "ui-host"
    crate_dir.mkdir(parents=True)
    calls: list[tuple[list[str], Path | None, dict[str, str] | None]] = []
    copies: list[tuple[Path, Path]] = []
    monkeypatch.setattr(build_cli, "_rust_ui_host_workspace_dir", lambda: workspace_dir)
    monkeypatch.setattr(
        build_cli,
        "_run",
        lambda command, cwd=None, env=None: calls.append((command, cwd, env)),
    )
    monkeypatch.setattr(
        build_cli.shutil,
        "copy2",
        lambda source, target: copies.append((Path(source), Path(target))),
    )

    output = build_cli.build_rust_ui_host()

    assert output.name.startswith("yoyopod-ui-host")
    assert calls == [
        (
            [
                "cargo",
                "build",
                "--release",
                "-p",
                "yoyopod-ui-host",
                "--locked",
                "--features",
                "whisplay-hardware",
            ],
            workspace_dir,
            None,
        )
    ]
    assert copies == [
        (
            workspace_dir / "target" / "release" / output.name,
            crate_dir / "build" / output.name,
        )
    ]
```

Run:

```bash
uv run pytest -q tests/cli/test_yoyopod_cli_build.py::test_rust_ui_host_build_help tests/cli/test_yoyopod_cli_build.py::test_build_rust_ui_host_invokes_cargo_workspace
```

Expected: fails because `rust-ui-host` helpers and command do not exist.

- [ ] **Step 2: Add new Rust UI host build helpers**

In `yoyopod_cli/build.py`, replace the Rust UI helper block with:

```python
def _rust_ui_host_workspace_dir() -> Path:
    return _REPO_ROOT / "src"


def _rust_ui_host_crate_dir() -> Path:
    return _rust_ui_host_workspace_dir() / "crates" / "ui-host"


def _rust_ui_host_binary_path() -> Path:
    suffix = ".exe" if os.name == "nt" else ""
    return _rust_ui_host_crate_dir() / "build" / f"yoyopod-ui-host{suffix}"


def _rust_ui_poc_dir() -> Path:
    return _rust_ui_host_crate_dir()


def _rust_ui_poc_binary_path() -> Path:
    return _rust_ui_host_binary_path()
```

Replace `build_rust_ui_poc` with a new function and compatibility wrapper:

```python
def build_rust_ui_host(*, hardware_feature: bool = True) -> Path:
    """Build the Rust Whisplay UI host and return the copied binary path."""

    workspace_dir = _rust_ui_host_workspace_dir()
    output = _rust_ui_host_binary_path()
    output.parent.mkdir(parents=True, exist_ok=True)

    command = [
        "cargo",
        "build",
        "--release",
        "-p",
        "yoyopod-ui-host",
        "--locked",
    ]
    if hardware_feature:
        command.extend(["--features", "whisplay-hardware"])
    _run(command, cwd=workspace_dir)

    suffix = ".exe" if os.name == "nt" else ""
    built_binary = workspace_dir / "target" / "release" / f"yoyopod-ui-host{suffix}"
    shutil.copy2(built_binary, output)
    return output


def build_rust_ui_poc(*, hardware_feature: bool = True) -> Path:
    """Compatibility wrapper for the renamed Rust UI host build."""

    return build_rust_ui_host(hardware_feature=hardware_feature)
```

- [ ] **Step 3: Register the new build command and keep the old alias**

In `yoyopod_cli/build.py`, add:

```python
@app.command("rust-ui-host")
def build_rust_ui_host_command(
    no_hardware_feature: Annotated[
        bool,
        typer.Option(
            "--no-hardware-feature",
            help="Build without the whisplay-hardware Cargo feature.",
        ),
    ] = False,
) -> None:
    """Build the Rust UI host binary."""

    output = build_rust_ui_host(hardware_feature=not no_hardware_feature)
    typer.echo(f"Built Rust UI host: {output}")
```

Update the existing `rust-ui-poc` command body:

```python
@app.command("rust-ui-poc")
def build_rust_ui_poc_command(
    no_hardware_feature: Annotated[
        bool,
        typer.Option(
            "--no-hardware-feature",
            help="Build without the whisplay-hardware Cargo feature.",
        ),
    ] = False,
) -> None:
    """Compatibility alias for `yoyopod build rust-ui-host`."""

    output = build_rust_ui_host(hardware_feature=not no_hardware_feature)
    typer.echo(f"Built Rust UI host: {output}")
```

- [ ] **Step 4: Make the build tests pass**

Run:

```bash
uv run pytest -q tests/cli/test_yoyopod_cli_build.py::test_rust_ui_host_build_help tests/cli/test_yoyopod_cli_build.py::test_build_rust_ui_host_invokes_cargo_workspace tests/cli/test_yoyopod_cli_build.py::test_build_rust_ui_poc_invokes_cargo
```

Expected: tests pass. Update the old PoC test expected binary name to `yoyopod-ui-host` if it still asserts `yoyopod-rust-ui-poc`.

- [ ] **Step 5: Update GitHub Actions**

In `.github/workflows/ci.yml`, change the `ui-rust` job:

```yaml
      - name: Run Rust UI host tests
        working-directory: src
        run: cargo test --workspace --locked --features whisplay-hardware

      - name: Build Rust UI Whisplay host
        working-directory: src
        run: |
          set -euo pipefail
          cargo build --release -p yoyopod-ui-host --features whisplay-hardware --locked
          mkdir -p crates/ui-host/build
          cp target/release/yoyopod-ui-host crates/ui-host/build/yoyopod-ui-host

      - name: Upload Rust UI ARM64 host
        uses: actions/upload-artifact@v4
        with:
          name: yoyopod-ui-host-${{ github.sha }}
          path: src/crates/ui-host/build/yoyopod-ui-host
          if-no-files-found: error
```

- [ ] **Step 6: Add the Pi command under the new name**

Create `yoyopod_cli/pi/rust_ui_host.py` by moving the implementation from `rust_ui_poc.py` and changing user-facing names:

```python
"""Whisplay-only Rust UI host validation command."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal, cast

import typer

from yoyopod.ui.rust_host.hub import HubRenderer, RustHubSnapshot
from yoyopod.ui.rust_host.protocol import UiEnvelope
from yoyopod.ui.rust_host.supervisor import RustUiHostSupervisor


def _default_worker_path() -> Path:
    suffix = ".exe" if __import__("os").name == "nt" else ""
    return Path("src") / "crates" / "ui-host" / "build" / f"yoyopod-ui-host{suffix}"
```

Keep the existing command behavior and rename the function to `rust_ui_host`.

- [ ] **Step 7: Keep `rust-ui-poc` as a compatibility CLI alias**

Replace `yoyopod_cli/pi/rust_ui_poc.py` with:

```python
"""Compatibility alias for the renamed Rust UI host validation command."""

from yoyopod_cli.pi.rust_ui_host import rust_ui_host as rust_ui_poc

__all__ = ["rust_ui_poc"]
```

In `yoyopod_cli/pi/__init__.py`, register both commands:

```python
from yoyopod_cli.pi import (
    network as _network,
    power as _power,
    rust_ui_host as _rust_ui_host,
    rust_ui_poc as _rust_ui_poc,
    validate as _validate,
    voip as _voip,
)

app.command(name="rust-ui-host")(_rust_ui_host.rust_ui_host)
app.command(name="rust-ui-poc")(_rust_ui_poc.rust_ui_poc)
```

- [ ] **Step 8: Update Pi command tests**

Add or update tests so both command names work:

```python
def test_rust_ui_host_help() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["rust-ui-host", "--help"])

    assert result.exit_code == 0
    assert "rust ui host" in result.output.lower()


def test_rust_ui_poc_alias_still_works() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["rust-ui-poc", "--help"])

    assert result.exit_code == 0
    assert "rust ui host" in result.output.lower()
```

Run:

```bash
uv run pytest -q tests/cli/test_pi_rust_ui_poc.py
```

Expected: tests pass after expected output and binary names are updated.

- [ ] **Step 9: Update remote validation path without building on Pi**

In `yoyopod_cli/remote_validate.py`, replace:

```python
_RUST_UI_POC_WORKER = "workers/ui/rust/build/yoyopod-rust-ui-poc"
```

with:

```python
_RUST_UI_HOST_WORKER = "src/crates/ui-host/build/yoyopod-ui-host"
_RUST_UI_POC_WORKER = _RUST_UI_HOST_WORKER
```

Update shell generation to run:

```bash
test -x src/crates/ui-host/build/yoyopod-ui-host
venv/bin/python -m yoyopod_cli.main pi rust-ui-host --worker src/crates/ui-host/build/yoyopod-ui-host
```

Keep `--with-rust-ui-poc` as an accepted flag for compatibility and add `--with-rust-ui-host`.

- [ ] **Step 10: Update docs and generated commands**

Update `docs/RUST_UI_POC.md` to state that it is now the Rust UI Host path, with the artifact and binary names:

```text
CI artifact: yoyopod-ui-host-<sha>
Pi checkout binary: src/crates/ui-host/build/yoyopod-ui-host
```

Run:

```bash
uv run yoyopod dev docs
```

Expected: `yoyopod_cli/COMMANDS.md` includes `yoyopod build rust-ui-host` and `yoyopod pi rust-ui-host`.

- [ ] **Step 11: Run validation and commit**

Run:

```bash
cargo fmt --manifest-path src/Cargo.toml
cargo test --manifest-path src/Cargo.toml --workspace --locked
cargo test --manifest-path src/Cargo.toml --workspace --features whisplay-hardware --locked
uv run python scripts/quality.py gate
uv run pytest -q
```

Commit:

```bash
git add .github/workflows/ci.yml yoyopod_cli docs tests src
git commit -m "chore: rename rust ui host build path"
```

Expected: CI/build/docs now point to `src/crates/ui-host/build/yoyopod-ui-host`.

## Task 3: Add `yoyopod.ui.rust_host` And Keep Compatibility Imports

**Files:**
- Create: `yoyopod/ui/rust_host/__init__.py`
- Create: `yoyopod/ui/rust_host/protocol.py`
- Create: `yoyopod/ui/rust_host/snapshot.py`
- Create: `yoyopod/ui/rust_host/supervisor.py`
- Create: `yoyopod/ui/rust_host/facade.py`
- Create: `yoyopod/ui/rust_host/intents.py`
- Move or copy: `yoyopod/ui/rust_sidecar/hub.py` -> `yoyopod/ui/rust_host/hub.py`
- Modify: `yoyopod/ui/rust_sidecar/*.py`
- Test: `tests/ui/test_rust_host_protocol.py`
- Test: `tests/ui/test_rust_host_snapshot.py`
- Test: `tests/ui/test_rust_host_facade.py`

- [ ] **Step 1: Write package-level compatibility tests**

Create `tests/ui/test_rust_host_imports.py`:

```python
from __future__ import annotations

from yoyopod.ui.rust_host import RustUiFacade, RustUiRuntimeSnapshot, UiEnvelope
from yoyopod.ui.rust_sidecar import (
    RustUiSidecarCoordinator,
    RustUiRuntimeSnapshot as LegacyRustUiRuntimeSnapshot,
    UiEnvelope as LegacyUiEnvelope,
)


def test_rust_host_exports_new_facade_names() -> None:
    assert RustUiFacade.__name__ == "RustUiFacade"
    assert RustUiRuntimeSnapshot.__name__ == "RustUiRuntimeSnapshot"
    assert UiEnvelope.__name__ == "UiEnvelope"


def test_rust_sidecar_imports_remain_compatible() -> None:
    assert RustUiSidecarCoordinator.__name__ == "RustUiFacade"
    assert LegacyRustUiRuntimeSnapshot is RustUiRuntimeSnapshot
    assert LegacyUiEnvelope is UiEnvelope
```

Run:

```bash
uv run pytest -q tests/ui/test_rust_host_imports.py
```

Expected: fails because `yoyopod.ui.rust_host` does not exist.

- [ ] **Step 2: Create the new package by moving current bridge code**

Move current files:

```bash
New-Item -ItemType Directory -Force yoyopod/ui/rust_host
git mv yoyopod/ui/rust_sidecar/protocol.py yoyopod/ui/rust_host/protocol.py
git mv yoyopod/ui/rust_sidecar/state.py yoyopod/ui/rust_host/snapshot.py
git mv yoyopod/ui/rust_sidecar/supervisor.py yoyopod/ui/rust_host/supervisor.py
git mv yoyopod/ui/rust_sidecar/coordinator.py yoyopod/ui/rust_host/facade.py
git mv yoyopod/ui/rust_sidecar/hub.py yoyopod/ui/rust_host/hub.py
```

Rename class names in the moved files:

```python
class RustUiFacade:
    """Translate Python runtime state and Rust UI host intents across the worker seam."""
```

```python
class RustUiHostSupervisor:
    """Subprocess supervisor for the Rust UI host."""
```

Keep `RustUiRuntimeSnapshot`, `RustUiListItem`, `RustUiHubCard`, `UiEnvelope`, and `UiProtocolError` names unchanged.

- [ ] **Step 3: Update imports inside the new package**

In `yoyopod/ui/rust_host/facade.py`, import:

```python
from yoyopod.ui.rust_host.snapshot import RustUiRuntimeSnapshot
```

In `yoyopod/ui/rust_host/supervisor.py`, import:

```python
from yoyopod.ui.rust_host.protocol import UiEnvelope, UiProtocolError
```

- [ ] **Step 4: Recreate compatibility wrappers under `rust_sidecar`**

Create `yoyopod/ui/rust_sidecar/protocol.py`:

```python
from yoyopod.ui.rust_host.protocol import UiEnvelope, UiProtocolError

__all__ = ["UiEnvelope", "UiProtocolError"]
```

Create `yoyopod/ui/rust_sidecar/state.py`:

```python
from yoyopod.ui.rust_host.snapshot import RustUiHubCard, RustUiListItem, RustUiRuntimeSnapshot

__all__ = ["RustUiHubCard", "RustUiListItem", "RustUiRuntimeSnapshot"]
```

Create `yoyopod/ui/rust_sidecar/supervisor.py`:

```python
from yoyopod.ui.rust_host.supervisor import RustUiHostSupervisor

RustUiSidecarSupervisor = RustUiHostSupervisor

__all__ = ["RustUiHostSupervisor", "RustUiSidecarSupervisor"]
```

Create `yoyopod/ui/rust_sidecar/coordinator.py`:

```python
from yoyopod.ui.rust_host.facade import RustUiFacade

RustUiSidecarCoordinator = RustUiFacade

__all__ = ["RustUiFacade", "RustUiSidecarCoordinator"]
```

Create `yoyopod/ui/rust_sidecar/hub.py`:

```python
from yoyopod.ui.rust_host.hub import HubRenderer, RustHubSnapshot

__all__ = ["HubRenderer", "RustHubSnapshot"]
```

Create `yoyopod/ui/rust_sidecar/__init__.py`:

```python
"""Compatibility imports for the renamed Rust UI host bridge."""

from yoyopod.ui.rust_host import RustUiFacade, RustUiRuntimeSnapshot, UiEnvelope, UiProtocolError
from yoyopod.ui.rust_host.facade import RustUiFacade as RustUiSidecarCoordinator
from yoyopod.ui.rust_host.supervisor import RustUiHostSupervisor as RustUiSidecarSupervisor

__all__ = [
    "RustUiFacade",
    "RustUiRuntimeSnapshot",
    "RustUiSidecarCoordinator",
    "RustUiSidecarSupervisor",
    "UiEnvelope",
    "UiProtocolError",
]
```

- [ ] **Step 5: Create the new package exports**

Create `yoyopod/ui/rust_host/__init__.py`:

```python
"""Rust UI host integration helpers."""

from yoyopod.ui.rust_host.facade import RustUiFacade
from yoyopod.ui.rust_host.protocol import UiEnvelope, UiProtocolError
from yoyopod.ui.rust_host.snapshot import RustUiRuntimeSnapshot
from yoyopod.ui.rust_host.supervisor import RustUiHostSupervisor

__all__ = [
    "RustUiFacade",
    "RustUiHostSupervisor",
    "RustUiRuntimeSnapshot",
    "UiEnvelope",
    "UiProtocolError",
]
```

- [ ] **Step 6: Update tests to prefer the new package**

For new tests, import from `yoyopod.ui.rust_host`. Keep existing `rust_sidecar` tests in place until all callers have moved.

Run:

```bash
uv run pytest -q tests/ui/test_rust_host_imports.py tests/ui/test_rust_sidecar_protocol.py tests/ui/test_rust_sidecar_state.py tests/ui/test_rust_sidecar_supervisor.py tests/ui/test_rust_sidecar_coordinator.py
```

Expected: all old and new bridge tests pass.

- [ ] **Step 7: Run validation and commit**

Run:

```bash
uv run python scripts/quality.py gate
uv run pytest -q
```

Commit:

```bash
git add yoyopod/ui/rust_host yoyopod/ui/rust_sidecar tests/ui
git commit -m "refactor: rename rust ui bridge to host"
```

Expected: Python bridge naming now matches the Rust UI Host design while legacy imports remain working.

## Task 4: Add Rust UI Host Config And Runtime Facade Wiring

**Files:**
- Modify: `yoyopod/config/models/app.py`
- Modify: `tests/config/test_config_models.py`
- Modify: `yoyopod/ui/rust_host/facade.py`
- Modify: `tests/ui/test_rust_host_facade.py`
- Modify: `yoyopod/core/application.py`
- Modify: `yoyopod/core/event_subscriptions.py`
- Modify: `yoyopod/core/loop.py`

- [ ] **Step 1: Write config tests for new host names and old env compatibility**

In `tests/config/test_config_models.py`, add:

```python
def test_display_config_exposes_rust_ui_host_env(monkeypatch):
    """Rust UI host settings should be opt-in and env-overridable."""
    from yoyopod.config.models import AppDisplayConfig, build_config_model

    monkeypatch.setenv("YOYOPOD_RUST_UI_HOST_ENABLED", "true")
    monkeypatch.setenv("YOYOPOD_RUST_UI_HOST_WORKER", "/opt/yoyopod/yoyopod-ui-host")

    config = build_config_model(AppDisplayConfig, {})

    assert config.rust_ui_host_enabled is True
    assert config.rust_ui_host_worker == "/opt/yoyopod/yoyopod-ui-host"
    assert config.rust_ui_enabled is True
    assert config.rust_ui_worker_path == "/opt/yoyopod/yoyopod-ui-host"


def test_display_config_keeps_rust_ui_sidecar_env_compatibility(monkeypatch):
    """Existing sidecar env vars should still enable the renamed Rust UI host."""
    from yoyopod.config.models import AppDisplayConfig, build_config_model

    monkeypatch.setenv("YOYOPOD_RUST_UI_SIDECAR_ENABLED", "true")
    monkeypatch.setenv("YOYOPOD_RUST_UI_WORKER", "/opt/yoyopod/legacy-ui-worker")

    config = build_config_model(AppDisplayConfig, {})

    assert config.rust_ui_host_enabled is False
    assert config.rust_ui_sidecar_enabled is True
    assert config.rust_ui_enabled is True
    assert config.rust_ui_worker_path == "/opt/yoyopod/legacy-ui-worker"
```

Run:

```bash
uv run pytest -q tests/config/test_config_models.py::test_display_config_exposes_rust_ui_host_env tests/config/test_config_models.py::test_display_config_keeps_rust_ui_sidecar_env_compatibility
```

Expected: fails because the new host fields and compatibility properties do not exist.

- [ ] **Step 2: Add config fields and properties**

In `yoyopod/config/models/app.py`, update `AppDisplayConfig`:

```python
    rust_ui_host_enabled: bool = config_value(
        default=False,
        env="YOYOPOD_RUST_UI_HOST_ENABLED",
    )
    rust_ui_host_worker: str = config_value(
        default="src/crates/ui-host/build/yoyopod-ui-host",
        env="YOYOPOD_RUST_UI_HOST_WORKER",
    )
    rust_ui_sidecar_enabled: bool = config_value(
        default=False,
        env="YOYOPOD_RUST_UI_SIDECAR_ENABLED",
    )
    rust_ui_worker: str = config_value(
        default="src/crates/ui-host/build/yoyopod-ui-host",
        env="YOYOPOD_RUST_UI_WORKER",
    )

    @property
    def rust_ui_enabled(self) -> bool:
        return self.rust_ui_host_enabled or self.rust_ui_sidecar_enabled

    @property
    def rust_ui_worker_path(self) -> str:
        if self.rust_ui_host_worker.strip() != "src/crates/ui-host/build/yoyopod-ui-host":
            return self.rust_ui_host_worker
        return self.rust_ui_worker
```

- [ ] **Step 3: Make config tests pass**

Run:

```bash
uv run pytest -q tests/config/test_config_models.py::test_display_config_exposes_rust_ui_host_env tests/config/test_config_models.py::test_display_config_keeps_rust_ui_sidecar_env_compatibility tests/config/test_config_models.py::test_display_config_exposes_rust_ui_sidecar_env
```

Expected: tests pass.

- [ ] **Step 4: Write facade tests for snapshots, ticks, activity, and intents**

Create `tests/ui/test_rust_host_facade.py`:

```python
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from yoyopod.core.events import WorkerMessageReceivedEvent
from yoyopod.ui.rust_host.facade import RustUiFacade


class _Supervisor:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, dict[str, Any] | None, str | None]] = []
        self.registered: list[tuple[str, object]] = []
        self.started: list[str] = []

    def register(self, domain: str, config: object) -> None:
        self.registered.append((domain, config))

    def start(self, domain: str) -> bool:
        self.started.append(domain)
        return True

    def send_command(
        self,
        domain: str,
        *,
        type: str,
        payload: dict[str, Any] | None = None,
        request_id: str | None = None,
        timestamp_ms: int = 0,
        deadline_ms: int = 0,
    ) -> bool:
        self.sent.append((domain, type, payload, request_id))
        return True


class _Services:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, Any]] = []

    def call(self, domain: str, service: str, data: Any = None) -> None:
        self.calls.append((domain, service, data))


def test_facade_starts_ui_host_worker() -> None:
    supervisor = _Supervisor()
    app = SimpleNamespace(worker_supervisor=supervisor)
    facade = RustUiFacade(app, worker_domain="ui")

    assert facade.start_worker("src/crates/ui-host/build/yoyopod-ui-host", hardware="whisplay")

    domain, config = supervisor.registered[0]
    assert domain == "ui"
    assert getattr(config, "argv") == [
        "src/crates/ui-host/build/yoyopod-ui-host",
        "--hardware",
        "whisplay",
    ]


def test_facade_sends_snapshot_and_tick_without_request_tracking() -> None:
    supervisor = _Supervisor()
    app = SimpleNamespace(
        worker_supervisor=supervisor,
        context=None,
        app_state_runtime=None,
        people_directory=None,
    )
    facade = RustUiFacade(app, worker_domain="ui")

    assert facade.send_snapshot()
    assert facade.send_tick(renderer="lvgl")

    assert supervisor.sent[0][1] == "ui.runtime_snapshot"
    assert supervisor.sent[0][3] is None
    assert supervisor.sent[1] == ("ui", "ui.tick", {"renderer": "lvgl"}, None)


def test_facade_dispatches_intents_to_python_services() -> None:
    services = _Services()
    app = SimpleNamespace(services=services)
    facade = RustUiFacade(app, worker_domain="ui")

    facade.handle_worker_message(
        WorkerMessageReceivedEvent(
            domain="ui",
            kind="event",
            type="ui.intent",
            request_id=None,
            payload={"domain": "call", "action": "answer", "payload": {"source": "rust-ui"}},
        )
    )

    assert services.calls == [("call", "answer", {"source": "rust-ui"})]
```

Run:

```bash
uv run pytest -q tests/ui/test_rust_host_facade.py
```

Expected: fails until `RustUiFacade` exposes the expected methods and import paths.

- [ ] **Step 5: Update `RustUiFacade` to be the runtime-facing bridge**

In `yoyopod/ui/rust_host/facade.py`, keep current coordinator behavior and ensure these methods exist with the same bodies as the current `RustUiSidecarCoordinator` after imports are renamed:

```python
class RustUiFacade:
    """Translate Python runtime state and Rust UI host intents across the worker seam."""

    def start_worker(
        self,
        worker_path: str,
        *,
        hardware: str = "mock",
        cwd: str | None = None,
        env: dict[str, str] | None = None,
    ) -> bool:
        supervisor = getattr(self.app, "worker_supervisor", None)
        register = getattr(supervisor, "register", None)
        start = getattr(supervisor, "start", None)
        if not callable(register) or not callable(start):
            return False

        register(
            self.worker_domain,
            WorkerProcessConfig(
                name=self.worker_domain,
                argv=[worker_path, "--hardware", hardware],
                cwd=cwd,
                env=env,
            ),
        )
        return bool(start(self.worker_domain))

    def send_snapshot(self) -> bool:
        supervisor = getattr(self.app, "worker_supervisor", None)
        send_command = getattr(supervisor, "send_command", None)
        if not callable(send_command):
            return False
        return bool(
            send_command(
                self.worker_domain,
                type="ui.runtime_snapshot",
                payload=RustUiRuntimeSnapshot.from_app(self.app).to_payload(),
            )
        )

    def send_tick(self, *, renderer: str = "auto") -> bool:
        supervisor = getattr(self.app, "worker_supervisor", None)
        send_command = getattr(supervisor, "send_command", None)
        if not callable(send_command):
            return False
        return bool(
            send_command(
                self.worker_domain,
                type="ui.tick",
                payload={"renderer": renderer},
            )
        )

    def handle_worker_message(self, event: WorkerMessageReceivedEvent) -> None:
        if event.domain != self.worker_domain:
            return
        if event.type == "ui.intent":
            self._dispatch_intent(event.payload)
        elif event.type == "ui.screen_changed":
            logger.debug("Rust UI screen changed: {}", event.payload.get("screen"))
```

Keep `_map_service()` for `music`, `call`, and `voice` intents, and add support for:

```python
if domain == "voice" and action == "capture_toggle":
    return "call", "toggle_voice_note_recording"
```

Implement `capture_toggle` deterministically with existing services:

```python
if domain == "voice" and action == "capture_toggle":
    context = getattr(self.app, "context", None)
    interaction = getattr(getattr(context, "voice", None), "interaction", None)
    if bool(getattr(interaction, "capture_in_flight", False)) or bool(
        getattr(interaction, "ptt_active", False)
    ):
        return "call", "stop_voice_note_recording"
    return "call", "start_voice_note_recording"
```

- [ ] **Step 6: Add app field and event subscription**

In `yoyopod/core/application.py`, add:

```python
        self.rust_ui_host: object | None = None
```

In `yoyopod/core/event_subscriptions.py`, subscribe worker messages after existing subscriptions:

```python
        rust_ui_host = getattr(self.app, "rust_ui_host", None)
        handle_worker_message = getattr(rust_ui_host, "handle_worker_message", None)
        if callable(handle_worker_message):
            bus.subscribe(WorkerMessageReceivedEvent, handle_worker_message)
```

Because `rust_ui_host` is created after initial subscription registration in the live boot path, Task 5 adds an explicit subscription during Rust UI host setup as well.

- [ ] **Step 7: Add loop tick seam without enabling it yet**

In `yoyopod/core/loop.py`, add:

```python
    def tick_rust_ui_host(self) -> None:
        rust_ui_host = getattr(self.app, "rust_ui_host", None)
        if rust_ui_host is None:
            return
        send_snapshot = getattr(rust_ui_host, "send_snapshot", None)
        send_tick = getattr(rust_ui_host, "send_tick", None)
        if callable(send_snapshot):
            send_snapshot()
        if callable(send_tick):
            send_tick(renderer="lvgl")
```

Do not call it from `run_iteration` until Task 5 wires Rust UI mode.

- [ ] **Step 8: Run tests and commit**

Run:

```bash
uv run pytest -q tests/config/test_config_models.py tests/ui/test_rust_host_facade.py tests/ui/test_rust_host_imports.py
uv run python scripts/quality.py gate
uv run pytest -q
```

Commit:

```bash
git add yoyopod/config/models/app.py yoyopod/ui/rust_host yoyopod/ui/rust_sidecar yoyopod/core tests
git commit -m "feat: add rust ui host facade"
```

Expected: config and facade exist but Rust UI host mode is still opt-in and not the default boot path.

## Task 5: Boot With Rust As Exclusive UI Display/Input Owner

**Files:**
- Modify: `yoyopod/core/bootstrap/components_boot.py`
- Modify: `yoyopod/core/bootstrap/__init__.py`
- Modify: `yoyopod/core/bootstrap/runtime_helpers_boot.py`
- Modify: `yoyopod/core/bootstrap/screens_boot.py`
- Modify: `yoyopod/core/loop.py`
- Modify: `tests/core/bootstrap/test_rust_ui_host_boot.py`

- [ ] **Step 1: Write boot tests proving Python UI owners are skipped**

Create `tests/core/bootstrap/test_rust_ui_host_boot.py`:

```python
from __future__ import annotations

from types import SimpleNamespace

from yoyopod.core.bootstrap.components_boot import ComponentsBoot


class _FailingDisplay:
    def __init__(self, *args, **kwargs) -> None:
        raise AssertionError("Python display must not initialize in Rust UI mode")


def _fake_input_manager(*args, **kwargs):
    raise AssertionError("Python input must not initialize in Rust UI mode")


class _FailingScreenManager:
    def __init__(self, *args, **kwargs) -> None:
        raise AssertionError("Python screen manager must not initialize in Rust UI mode")


class _Settings:
    display = SimpleNamespace(
        hardware="whisplay",
        whisplay_renderer="lvgl",
        lvgl_buffer_lines=40,
        rust_ui_enabled=True,
        rust_ui_worker_path="src/crates/ui-host/build/yoyopod-ui-host",
    )
    input = SimpleNamespace()


def test_components_boot_skips_python_ui_hardware_when_rust_ui_enabled() -> None:
    app = SimpleNamespace(
        simulate=False,
        app_settings=_Settings(),
        media_settings=SimpleNamespace(music=SimpleNamespace(default_volume=80)),
        display=None,
        context=None,
        config_manager=None,
        output_volume=None,
        music_backend=None,
        audio_volume_controller=None,
        screen_power_service=SimpleNamespace(
            configure_screen_power=lambda initial_now: None,
            update_screen_runtime_metrics=lambda now: None,
        ),
        voice_note_events=SimpleNamespace(sync_talk_summary_context=lambda: None),
        music_fsm=None,
        call_fsm=None,
        call_interruption_policy=None,
        input_manager=None,
        screen_manager=None,
        _lvgl_backend=None,
        _lvgl_input_bridge=None,
        runtime_loop=SimpleNamespace(last_lvgl_pump_at=0.0),
        note_input_activity=lambda *args, **kwargs: None,
        note_handled_input=lambda *args, **kwargs: None,
        note_visible_refresh=lambda *args, **kwargs: None,
        scheduler=SimpleNamespace(run_on_main=lambda fn: fn()),
    )
    boot = ComponentsBoot(
        app,
        logger=SimpleNamespace(info=lambda *args, **kwargs: None, exception=lambda *args, **kwargs: None),
        display_cls=_FailingDisplay,
        get_input_manager_fn=_fake_input_manager,
        screen_manager_cls=_FailingScreenManager,
        lvgl_input_bridge_cls=object,
        contract_error_cls=RuntimeError,
        build_contract_message_fn=lambda message: message,
    )

    assert boot.init_core_components()
    assert app.display is None
    assert app.input_manager is None
    assert app.screen_manager is None
    assert app.context is not None
```

Run:

```bash
uv run pytest -q tests/core/bootstrap/test_rust_ui_host_boot.py
```

Expected: fails because `ComponentsBoot` still initializes Python display/input/screen manager first.

- [ ] **Step 2: Add a Rust UI enabled helper**

In `ComponentsBoot`, add:

```python
    def _rust_ui_host_enabled(self) -> bool:
        settings = getattr(self.app, "app_settings", None)
        display = getattr(settings, "display", None)
        return bool(getattr(display, "rust_ui_enabled", False))
```

- [ ] **Step 3: Split context/orchestration setup from Python UI hardware setup**

Refactor `init_core_components()` into:

```python
    def init_core_components(self) -> bool:
        self.logger.info("Initializing core components...")
        try:
            assert self.app.app_settings is not None
            if not self._rust_ui_host_enabled():
                self._init_python_ui_hardware()
            self._init_app_context()
            self._init_orchestration_models()
            if not self._rust_ui_host_enabled():
                self._init_python_input_and_screen_manager()
            else:
                self.logger.info("  - Rust UI Host owns display/input/screens")
            return True
        except Exception:
            self.logger.exception("Failed to initialize core components")
            return False
```

Move existing display/LVGL setup into `_init_python_ui_hardware()`, AppContext/audio volume setup into `_init_app_context()`, FSM setup into `_init_orchestration_models()`, and InputManager/ScreenManager setup into `_init_python_input_and_screen_manager()`.

In `_init_app_context()`, when Rust UI mode is enabled, set:

```python
from yoyopod.ui.input import InteractionProfile

self.app.context.interaction_profile = InteractionProfile.ONE_BUTTON
```

- [ ] **Step 4: Skip screen construction in Rust UI mode**

In `RuntimeBootService.setup()`, replace:

```python
            if not self.setup_screens():
                logger.error("Failed to setup screens")
                return False
```

with:

```python
            if not self.rust_ui_host_enabled():
                if not self.setup_screens():
                    logger.error("Failed to setup screens")
                    return False
            else:
                logger.info("Skipping Python screen construction because Rust UI Host is enabled")
                self.setup_screenless_voice_runtime()
```

Add methods:

```python
    def rust_ui_host_enabled(self) -> bool:
        settings = getattr(self.app, "app_settings", None)
        display = getattr(settings, "display", None)
        return bool(getattr(display, "rust_ui_enabled", False))

    def setup_screenless_voice_runtime(self) -> None:
        self._screens_boot.setup_screenless_voice_runtime()
```

- [ ] **Step 5: Extract screenless voice runtime setup**

In `ScreensBoot`, add:

```python
    def setup_screenless_voice_runtime(self) -> None:
        """Initialize voice runtime pieces that do not require Python screens."""

        if self.app.voice_runtime is not None:
            return
        if self.app.context is None:
            return
        # Reuse the existing VoiceRuntimeCoordinator construction with a
        # screen summary provider that describes the Rust-owned Ask route.
```

Move the current `VoiceRuntimeCoordinator` construction into a helper that accepts a `screen_summary_provider`. For Rust UI mode, use:

```python
screen_summary_provider=lambda: "You are on the Rust Ask screen."
```

Keep Python screen object construction only in `setup_screens()`.

- [ ] **Step 6: Start and subscribe the Rust UI host after runtime helpers exist**

In `RuntimeBootService.setup()`, after `self.ensure_runtime_helpers()` and callback setup, add:

```python
            if self.rust_ui_host_enabled():
                self.setup_rust_ui_host()
```

Add:

```python
    def setup_rust_ui_host(self) -> bool:
        from yoyopod.ui.rust_host import RustUiFacade

        assert self.app.app_settings is not None
        worker_path = self.app.app_settings.display.rust_ui_worker_path
        facade = RustUiFacade(self.app, worker_domain="ui")
        self.app.rust_ui_host = facade
        self.app.bus.subscribe(WorkerMessageReceivedEvent, facade.handle_worker_message)
        started = facade.start_worker(worker_path, hardware="whisplay")
        if not started:
            logger.error("Failed to start Rust UI Host")
            return False
        facade.send_snapshot()
        return True
```

Import `WorkerMessageReceivedEvent` at the top of `yoyopod/core/bootstrap/__init__.py`.

- [ ] **Step 7: Tick Rust UI host from the coordinator loop only in Rust UI mode**

In `RuntimeLoopService.run_iteration()`, after `worker_poll` and before `screen_power`, add:

```python
            self._measure_blocking_span(
                "rust_ui_host",
                self.tick_rust_ui_host,
            )
```

Update `tick_rust_ui_host()`:

```python
    def tick_rust_ui_host(self) -> None:
        rust_ui_host = getattr(self.app, "rust_ui_host", None)
        if rust_ui_host is None:
            return
        send_snapshot = getattr(rust_ui_host, "send_snapshot", None)
        send_tick = getattr(rust_ui_host, "send_tick", None)
        if callable(send_snapshot):
            send_snapshot()
        if callable(send_tick):
            send_tick(renderer="lvgl")
```

- [ ] **Step 8: Make boot tests pass**

Run:

```bash
uv run pytest -q tests/core/bootstrap/test_rust_ui_host_boot.py
```

Expected: tests pass and prove Python display/input/screen classes are not constructed in Rust UI mode.

- [ ] **Step 9: Run broader runtime tests and commit**

Run:

```bash
uv run pytest -q tests/core tests/ui tests/config
uv run python scripts/quality.py gate
uv run pytest -q
```

Commit:

```bash
git add yoyopod/core yoyopod/ui tests
git commit -m "feat: let rust own whisplay ui boot"
```

Expected: Rust UI mode is opt-in; default Python UI mode still works; Rust UI mode does not open Python display/input/screen owners.

## Task 6: Complete Rust UI State Machine And Screen Coverage

**Files:**
- Modify: `src/crates/ui-host/src/ui_state.rs`
- Create: `src/crates/ui-host/src/runtime/mod.rs`
- Create: `src/crates/ui-host/src/runtime/snapshot.rs`
- Create: `src/crates/ui-host/src/runtime/state_machine.rs`
- Create: `src/crates/ui-host/src/runtime/intent.rs`
- Create: `src/crates/ui-host/src/screens/mod.rs`
- Create: `src/crates/ui-host/src/screens/hub.rs`
- Create: `src/crates/ui-host/src/screens/listen.rs`
- Create: `src/crates/ui-host/src/screens/music.rs`
- Create: `src/crates/ui-host/src/screens/ask.rs`
- Create: `src/crates/ui-host/src/screens/talk.rs`
- Create: `src/crates/ui-host/src/screens/call.rs`
- Create: `src/crates/ui-host/src/screens/power.rs`
- Create: `src/crates/ui-host/src/screens/overlay.rs`
- Modify: `src/crates/ui-host/src/worker.rs`

- [ ] **Step 1: Add state-machine tests for all required preemption and navigation flows**

In `src/crates/ui-host/src/runtime/state_machine.rs`, add tests:

```rust
#[cfg(test)]
mod tests {
    use super::*;
    use crate::input::InputAction;

    fn runtime_with_defaults() -> UiRuntime {
        UiRuntime::default()
    }

    #[test]
    fn hub_select_opens_focused_route() {
        let mut runtime = runtime_with_defaults();

        runtime.handle_input(InputAction::Select);

        assert_eq!(runtime.active_screen(), UiScreen::Listen);
        assert_eq!(runtime.focus_index(), 0);
    }

    #[test]
    fn incoming_call_preempts_current_screen_and_idle_returns() {
        let mut runtime = runtime_with_defaults();
        runtime.handle_input(InputAction::Select);
        assert_eq!(runtime.active_screen(), UiScreen::Listen);

        let mut snapshot = RuntimeSnapshot::default();
        snapshot.call.state = "incoming".to_string();
        snapshot.call.peer_name = "Mama".to_string();
        runtime.apply_snapshot(snapshot);

        assert_eq!(runtime.active_screen(), UiScreen::IncomingCall);

        let mut idle = RuntimeSnapshot::default();
        idle.call.state = "idle".to_string();
        runtime.apply_snapshot(idle);

        assert_eq!(runtime.active_screen(), UiScreen::Listen);
    }

    #[test]
    fn loading_and_error_overlays_preempt_runtime_routes() {
        let mut runtime = runtime_with_defaults();
        let mut loading = RuntimeSnapshot::default();
        loading.overlay.loading = true;
        loading.overlay.message = "Syncing".to_string();

        runtime.apply_snapshot(loading);
        assert_eq!(runtime.active_screen(), UiScreen::Loading);

        let mut error = RuntimeSnapshot::default();
        error.overlay.error = "Network unavailable".to_string();
        runtime.apply_snapshot(error);
        assert_eq!(runtime.active_screen(), UiScreen::Error);
    }

    #[test]
    fn required_screens_have_view_models() {
        let snapshot = RuntimeSnapshot::default();
        for screen in [
            UiScreen::Hub,
            UiScreen::Listen,
            UiScreen::Playlists,
            UiScreen::RecentTracks,
            UiScreen::NowPlaying,
            UiScreen::Ask,
            UiScreen::Talk,
            UiScreen::Contacts,
            UiScreen::CallHistory,
            UiScreen::VoiceNote,
            UiScreen::IncomingCall,
            UiScreen::OutgoingCall,
            UiScreen::InCall,
            UiScreen::Power,
            UiScreen::Loading,
            UiScreen::Error,
        ] {
            let view = UiRuntime::view_for_screen(screen, &snapshot, 0);
            assert_eq!(view.screen, screen);
        }
    }
}
```

Run:

```bash
cargo test --manifest-path src/Cargo.toml -p yoyopod-ui-host runtime::state_machine
```

Expected: fails until `RecentTracks`, `Talk`, `Contacts`, `CallHistory`, and `VoiceNote` screen variants and view models exist.

- [ ] **Step 2: Split `ui_state.rs` into readable runtime modules**

Move types without changing behavior:

```rust
// src/crates/ui-host/src/runtime/mod.rs
pub mod intent;
pub mod snapshot;
pub mod state_machine;

pub use intent::UiIntent;
pub use snapshot::{
    CallRuntimeSnapshot, HubCardSnapshot, HubRuntimeSnapshot, ListItemSnapshot,
    MusicRuntimeSnapshot, NetworkRuntimeSnapshot, OverlayRuntimeSnapshot, PowerRuntimeSnapshot,
    RuntimeSnapshot, VoiceRuntimeSnapshot,
};
pub use state_machine::{UiRuntime, UiScreen, UiView};
```

Update `src/crates/ui-host/src/main.rs`:

```rust
mod runtime;
```

Update imports in `worker.rs`, `render.rs`, and `lvgl_bridge.rs` from `crate::ui_state` to `crate::runtime`.

- [ ] **Step 3: Add complete screen enum and string mapping**

In `runtime/state_machine.rs`, define:

```rust
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum UiScreen {
    Hub,
    Listen,
    Playlists,
    RecentTracks,
    NowPlaying,
    Ask,
    Talk,
    Contacts,
    CallHistory,
    VoiceNote,
    IncomingCall,
    OutgoingCall,
    InCall,
    Power,
    Loading,
    Error,
}
```

`as_str()` must return:

```rust
match self {
    Self::Hub => "hub",
    Self::Listen => "listen",
    Self::Playlists => "playlists",
    Self::RecentTracks => "recent_tracks",
    Self::NowPlaying => "now_playing",
    Self::Ask => "ask",
    Self::Talk => "talk",
    Self::Contacts => "contacts",
    Self::CallHistory => "call_history",
    Self::VoiceNote => "voice_note",
    Self::IncomingCall => "incoming_call",
    Self::OutgoingCall => "outgoing_call",
    Self::InCall => "in_call",
    Self::Power => "power",
    Self::Loading => "loading",
    Self::Error => "error",
}
```

- [ ] **Step 4: Implement full one-button route behavior**

In `select_focused()`, use this routing:

```rust
UiScreen::Hub => match self.focus_index {
    0 => self.push_screen(UiScreen::Listen),
    1 => self.push_screen(UiScreen::Talk),
    2 => self.push_screen(UiScreen::Ask),
    _ => self.push_screen(UiScreen::Power),
},
UiScreen::Listen => match self.focus_index {
    0 => self.push_screen(UiScreen::NowPlaying),
    1 => self.push_screen(UiScreen::Playlists),
    2 => self.push_screen(UiScreen::RecentTracks),
    _ => {
        self.intents.push(UiIntent::new("music", "shuffle_all"));
        self.push_screen(UiScreen::NowPlaying);
    }
},
UiScreen::Talk => match self.focus_index {
    0 => self.push_screen(UiScreen::Contacts),
    1 => self.push_screen(UiScreen::CallHistory),
    _ => self.push_screen(UiScreen::VoiceNote),
},
UiScreen::Contacts => self.emit_call_start_for_focused_contact(),
UiScreen::CallHistory => self.emit_call_start_for_focused_history_item(),
UiScreen::VoiceNote => self.intents.push(UiIntent::new("voice", "capture_toggle")),
```

Keep incoming/active call behavior:

```rust
UiScreen::IncomingCall => self.intents.push(UiIntent::new("call", "answer")),
UiScreen::InCall => self.intents.push(UiIntent::new("call", "toggle_mute")),
```

- [ ] **Step 5: Add view models for every screen**

Implement `UiRuntime::view_for_screen(screen, snapshot, focus_index)` and have `active_view()` call it.

Required list item providers:

```rust
fn listen_items(&self) -> Vec<ListItemSnapshot> {
    vec![
        ListItemSnapshot::new("now_playing", "Now Playing", &self.snapshot.music.title, "track"),
        ListItemSnapshot::new("playlists", "Playlists", "Saved mixes", "playlist"),
        ListItemSnapshot::new("recent_tracks", "Recent", "Recently played", "recent"),
        ListItemSnapshot::new("shuffle", "Shuffle All", "Start music", "shuffle"),
    ]
}

fn talk_items(&self) -> Vec<ListItemSnapshot> {
    vec![
        ListItemSnapshot::new("contacts", "Contacts", "People", "person"),
        ListItemSnapshot::new("call_history", "History", "Recent calls", "phone"),
        ListItemSnapshot::new("voice_note", "Voice Note", "Record message", "microphone"),
    ]
}
```

Add a constructor to `ListItemSnapshot`:

```rust
impl ListItemSnapshot {
    pub fn new(
        id: impl Into<String>,
        title: impl Into<String>,
        subtitle: impl Into<String>,
        icon_key: impl Into<String>,
    ) -> Self {
        Self {
            id: id.into(),
            title: title.into(),
            subtitle: subtitle.into(),
            icon_key: icon_key.into(),
        }
    }
}
```

- [ ] **Step 6: Make Rust tests pass**

Run:

```bash
cargo fmt --manifest-path src/Cargo.toml
cargo test --manifest-path src/Cargo.toml -p yoyopod-ui-host runtime::state_machine
cargo test --manifest-path src/Cargo.toml --workspace --locked
cargo test --manifest-path src/Cargo.toml --workspace --features whisplay-hardware --locked
```

Expected: Rust UI state-machine tests pass and no Rust file grows into a large mixed-responsibility module.

- [ ] **Step 7: Run repo gates and commit**

Run:

```bash
uv run python scripts/quality.py gate
uv run pytest -q
```

Commit:

```bash
git add src
git commit -m "feat: complete rust ui state machine"
```

Expected: Rust owns all UI routes required by the design.

## Task 7: Make LVGL A Persistent Rust-Owned Renderer

**Files:**
- Modify: `src/crates/ui-host/src/lvgl_bridge.rs`
- Create: `src/crates/ui-host/src/render/mod.rs`
- Create: `src/crates/ui-host/src/render/lvgl.rs`
- Create: `src/crates/ui-host/src/render/framebuffer.rs`
- Modify: `src/crates/ui-host/src/worker.rs`
- Test: Rust renderer tests in `src/crates/ui-host/src/render/lvgl.rs`

- [ ] **Step 1: Add renderer lifecycle tests**

Create `src/crates/ui-host/src/render/lvgl.rs` with tests that can run without loading the real shim:

```rust
#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn renderer_mode_names_are_stable() {
        assert_eq!(RendererMode::Auto.as_str(), "auto");
        assert_eq!(RendererMode::Lvgl.as_str(), "lvgl");
        assert_eq!(RendererMode::Framebuffer.as_str(), "framebuffer");
    }

    #[test]
    fn persistent_renderer_tracks_last_screen() {
        let mut state = RendererState::default();

        assert!(state.needs_rebuild(UiScreen::Hub));
        state.mark_screen_built(UiScreen::Hub);
        assert!(!state.needs_rebuild(UiScreen::Hub));
        assert!(state.needs_rebuild(UiScreen::Listen));
    }
}
```

Run:

```bash
cargo test --manifest-path src/Cargo.toml -p yoyopod-ui-host render::lvgl
```

Expected: fails until renderer module and types exist.

- [ ] **Step 2: Create renderer module boundaries**

Create `src/crates/ui-host/src/render/mod.rs`:

```rust
pub mod framebuffer;
pub mod lvgl;

pub use framebuffer::FramebufferRenderer;
pub use lvgl::{LvglRenderer, RendererMode, RendererState};
```

Move fallback functions from old `render.rs` into `render/framebuffer.rs`.

- [ ] **Step 3: Add persistent renderer state**

In `render/lvgl.rs`, add:

```rust
use crate::runtime::UiScreen;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RendererMode {
    Auto,
    Lvgl,
    Framebuffer,
}

impl RendererMode {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Auto => "auto",
            Self::Lvgl => "lvgl",
            Self::Framebuffer => "framebuffer",
        }
    }
}

#[derive(Debug, Default)]
pub struct RendererState {
    active_screen: Option<UiScreen>,
}

impl RendererState {
    pub fn needs_rebuild(&self, screen: UiScreen) -> bool {
        self.active_screen != Some(screen)
    }

    pub fn mark_screen_built(&mut self, screen: UiScreen) {
        self.active_screen = Some(screen);
    }
}
```

- [ ] **Step 4: Convert `LvglShim` ownership into an initialized renderer**

Replace per-call `render_view_with_lvgl()` use in the worker with a renderer object:

```rust
pub struct LvglRenderer {
    shim: LvglShim,
    state: RendererState,
}

impl LvglRenderer {
    pub fn open(explicit_shim_path: Option<&Path>) -> Result<Self> {
        let shim_path = resolve_shim_path(explicit_shim_path)?;
        let shim = unsafe { LvglShim::load(&shim_path)? };
        unsafe {
            shim.check((shim.init)(), "init")?;
        }
        Ok(Self {
            shim,
            state: RendererState::default(),
        })
    }

    pub fn render_view(
        &mut self,
        framebuffer: &mut Framebuffer,
        view: &UiView,
        snapshot: &RuntimeSnapshot,
    ) -> Result<()> {
        if self.state.needs_rebuild(view.screen) {
            self.destroy_active_screen();
            self.build_screen(view.screen)?;
            self.state.mark_screen_built(view.screen);
        }
        self.sync_screen(framebuffer, view, snapshot)?;
        unsafe {
            (self.shim.force_refresh)();
            (self.shim.timer_handler)();
        }
        Ok(())
    }
}
```

Implement `Drop`:

```rust
impl Drop for LvglRenderer {
    fn drop(&mut self) {
        self.destroy_active_screen();
        unsafe {
            (self.shim.shutdown)();
        }
    }
}
```

- [ ] **Step 5: Keep framebuffer fallback diagnostic-only**

In `worker.rs`, hold one renderer:

```rust
let mut lvgl_renderer = LvglRenderer::open(None).ok();
```

When `RendererMode::Lvgl` is requested and `lvgl_renderer` is `None`, emit `ui.error` and return the command error. When `RendererMode::Auto` is requested, use framebuffer fallback only after writing a clear stderr line:

```text
LVGL runtime renderer unavailable; using framebuffer diagnostic renderer
```

- [ ] **Step 6: Run renderer tests**

Run:

```bash
cargo fmt --manifest-path src/Cargo.toml
cargo test --manifest-path src/Cargo.toml -p yoyopod-ui-host render::lvgl
cargo test --manifest-path src/Cargo.toml --workspace --locked
cargo test --manifest-path src/Cargo.toml --workspace --features whisplay-hardware --locked
```

Expected: renderer tests pass; no per-render LVGL init/shutdown remains in the hot render path.

- [ ] **Step 7: Run repo gates and commit**

Run:

```bash
uv run python scripts/quality.py gate
uv run pytest -q
```

Commit:

```bash
git add src
git commit -m "feat: persist rust lvgl renderer"
```

Expected: Rust UI Host owns a persistent LVGL renderer lifecycle.

## Task 8: Hardware Artifact Validation Path

**Files:**
- Modify: `docs/RUST_UI_POC.md` or `docs/RUST_UI_HOST.md`
- Modify: `yoyopod_cli/remote_validate.py`
- Modify: `tests/cli/test_yoyopod_cli_remote_validate.py`
- No target-side Rust build commands.

- [ ] **Step 1: Push the implementation branch only after local gates pass**

Run:

```bash
uv run python scripts/quality.py gate
uv run pytest -q
git push origin codex/rust-whisplay-ui-poc
```

Expected: push succeeds. Do not start any Rust build on the Pi.

- [ ] **Step 2: Wait for the `ui-rust` CI job artifact**

Use GitHub Actions for the exact pushed SHA. Artifact name must be:

```text
yoyopod-ui-host-<sha>
```

Expected: artifact contains one executable named `yoyopod-ui-host`.

- [ ] **Step 3: Copy the CI artifact to the Pi checkout**

After downloading the artifact locally, copy it to:

```text
/opt/yoyopod-dev/checkout/src/crates/ui-host/build/yoyopod-ui-host
```

Use:

```bash
ssh tifo@rpi-zero "mkdir -p /opt/yoyopod-dev/checkout/src/crates/ui-host/build"
scp <downloaded-yoyopod-ui-host> tifo@rpi-zero:/opt/yoyopod-dev/checkout/src/crates/ui-host/build/yoyopod-ui-host
ssh tifo@rpi-zero "chmod +x /opt/yoyopod-dev/checkout/src/crates/ui-host/build/yoyopod-ui-host"
```

- [ ] **Step 4: Ensure Python dev/prod services are not owning hardware**

Run:

```bash
uv run python -m yoyopod_cli.main remote mode status
uv run python -m yoyopod_cli.main remote mode deactivate dev
```

Expected: no Python app service is actively holding display/input hardware during direct Rust UI validation.

- [ ] **Step 5: Run no-touch input validation**

On the Pi, run a 30-second no-touch `ui.tick` script against `--hardware whisplay`.

Expected:

```text
ui.ready
button_events=0
```

No `ui.input` events should appear while the button is untouched.

- [ ] **Step 6: Run physical click validation**

Run a 60-second tick window and click the Whisplay button on GPIO 17.

Expected:

```text
ui.input action=advance method=single_tap
ui.screen_changed
```

Double click should emit `select`; long hold should emit `back`.

- [ ] **Step 7: Run orientation and color validation**

Render the Rust UI host Hub and test scene from the CI artifact.

Expected:

- Hub is upright.
- RGB colors are correct.
- Red appears red, green appears green, blue appears blue.
- No full-screen solid red regression.
- No upside-down display regression.

- [ ] **Step 8: Run runtime snapshot validation**

Send these snapshots to the Rust UI host:

```json
{"call":{"state":"incoming","peer_name":"Mama","peer_address":"sip:mama@example.com"}}
{"call":{"state":"active","peer_name":"Mama","duration_text":"0:03"}}
{"call":{"state":"idle"}}
{"overlay":{"loading":true,"message":"Syncing"}}
{"overlay":{"error":"Network unavailable"}}
```

Expected:

- incoming snapshot shows `incoming_call`
- active snapshot shows `in_call`
- idle snapshot returns to the previous non-call screen
- loading snapshot shows `loading`
- error snapshot shows `error`

- [ ] **Step 9: Run 10-minute navigation/render soak**

Run a scripted `ui.tick` loop with periodic snapshots and manual button navigation for 10 minutes.

Expected:

- worker stays alive
- frame count increases
- no display corruption
- no input stall
- no Python app service owns display/input at the same time

- [ ] **Step 10: Record results in the PR**

Add a PR comment or update PR body with:

```text
Rust UI Host hardware validation:
- SHA:
- Artifact:
- Pi path: /opt/yoyopod-dev/checkout/src/crates/ui-host/build/yoyopod-ui-host
- no-touch input:
- physical click:
- orientation/color:
- snapshot preemption:
- soak:
```

Expected: reviewers can see that the Rust UI Host path was validated on Whisplay hardware from a CI-built artifact.

## Final Verification Before PR Ready State

Run locally:

```bash
cargo fmt --manifest-path src/Cargo.toml
cargo test --manifest-path src/Cargo.toml --workspace --locked
cargo test --manifest-path src/Cargo.toml --workspace --features whisplay-hardware --locked
uv run python scripts/quality.py gate
uv run pytest -q
```

Run on hardware only with the CI artifact:

```bash
uv run python -m yoyopod_cli.main remote mode status
yoyopod pi rust-ui-host --worker src/crates/ui-host/build/yoyopod-ui-host --frames 10
```

Do not mark the PR ready until local gates, CI, and Whisplay hardware validation are recorded.
