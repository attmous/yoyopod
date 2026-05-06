# Python Support Extraction And Runtime Deletion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove active `yoyopod/` Python runtime ownership by moving CLI-needed support into `yoyopod_cli/`, stopping active packaging of `yoyopod`, and quarantining the retired Python runtime under `legacy/`.

**Architecture:** Keep `device/` as the Rust runtime and worker workspace. Keep Python only as operations tooling under `yoyopod_cli/`, with shared contracts in `yoyopod_cli/contracts/`, config support in `yoyopod_cli/config/`, and Pi validation support in `yoyopod_cli/pi/support/`. Runtime-only Python app code moves to `legacy/python-runtime/yoyopod/` and is excluded from packaging and default tests.

**Tech Stack:** Python 3.12, Typer CLI, pytest, Black, Ruff, mypy, Hatch packaging, Rust Cargo workspace.

---

## Source Spec

Implement against:

- `docs/superpowers/specs/2026-05-06-python-support-extraction-and-runtime-deletion-design.md`
- `docs/superpowers/specs/2026-05-06-device-python-runtime-cleanup-design.md`
- `AGENTS.md`

This plan chooses temporary quarantine over immediate hard deletion for the
old Python runtime package. The active repo root will no longer contain
`yoyopod/`, and package artifacts will no longer ship it. The quarantined copy
under `legacy/python-runtime/yoyopod/` can be deleted after one hardware
validation cycle.

---

## Phase Summary

1. `Phase 0`: Commit this plan and capture import inventory.
2. `Phase 1`: Extract worker protocol and Rust UI host support.
3. `Phase 2`: Move config contracts and config tests to `yoyopod_cli.config`.
4. `Phase 3`: Extract voice CLI support and cloud voice validation contracts.
5. `Phase 4`: Replace or retire Python-runtime Pi validation imports.
6. `Phase 5`: Add active import/package guard tests.
7. `Phase 6`: Quarantine `yoyopod/` and remove it from packaging.
8. `Phase 7`: Run full validation, push, and update the PR.

Each phase should be a separate commit.

---

## Target File Structure

Create or populate these active support packages:

```text
yoyopod_cli/
  contracts/
    worker_protocol.py

  config/
    __init__.py
    composition.py
    manager.py
    models/
      __init__.py
      app.py
      cloud.py
      communication.py
      core.py
      media.py
      network.py
      people.py
      power.py
      runtime.py
      voice.py

  pi/
    support/
      __init__.py
      call_models.py
      call_integration/
      cloud_backend/
      cloud_integration/
      display/
      input.py
      input_runtime/
      lvgl_binding/
      music_backend/
      music_integration/
      power_backend/
      power_integration/
      rust_ui_host/
        __init__.py
        protocol.py
        snapshot.py
        supervisor.py
      voip_backend/
      voice_dictionary.py
      voice_dictionary_validator.py
      voice_models.py
      voice_output.py
      voice_settings.py
      voice_trace.py
      voice_trace_analysis.py
      voice_worker_contract.py
      voice.py
```

Quarantine this retired runtime tree:

```text
legacy/python-runtime/yoyopod/
```

Update these active test owners:

```text
tests/cli/
tests/config/
tests/deploy/
tests/device/
tests/scripts/
```

---

## Phase 0: Plan Commit And Inventory

**Files:**

- Create: `docs/superpowers/plans/2026-05-06-python-support-extraction-and-runtime-deletion.md`

### Task 0.1: Commit The Plan

- [ ] **Step 1: Confirm branch and worktree**

Run:

```powershell
git status --short --branch
```

Expected:

- branch is `codex/python-support-extraction-spec`
- only the new plan file is uncommitted

- [ ] **Step 2: Check plan whitespace**

Run:

```powershell
git diff --check -- docs/superpowers/plans/2026-05-06-python-support-extraction-and-runtime-deletion.md
```

Expected:

- exit code `0`

- [ ] **Step 3: Commit the plan**

Run:

```powershell
git add docs/superpowers/plans/2026-05-06-python-support-extraction-and-runtime-deletion.md
git commit -m "docs: plan python support extraction cleanup"
```

Expected:

- one docs-only commit exists

### Task 0.2: Capture The Starting Import Inventory

- [ ] **Step 1: Run the active import scan**

Run:

```powershell
rg -n "from yoyopod\\.|import yoyopod|yoyopod\\." yoyopod_cli tests\cli tests\config tests\deploy tests\device tests\scripts -g "*.py"
```

Expected:

- output lists current active imports from `yoyopod.*`
- keep this output in the terminal for the phase-by-phase comparison

- [ ] **Step 2: Run package metadata scan**

Run:

```powershell
Select-String -Path pyproject.toml -Pattern 'packages =|"/yoyopod"|"/yoyopod.py"|audit_type_paths' -Context 0,2
```

Expected:

- output shows `packages = ["yoyopod", "yoyopod_cli"]`
- output shows sdist includes for `/yoyopod` and `/yoyopod.py`
- output shows audit type paths still include `yoyopod`

---

## Phase 1: Worker Protocol And Rust UI Host Support

**Files:**

- Move: `yoyopod/core/workers/protocol.py` to `yoyopod_cli/contracts/worker_protocol.py`
- Move: `yoyopod/ui/rust_host/protocol.py` to `yoyopod_cli/pi/support/rust_ui_host/protocol.py`
- Move: `yoyopod/ui/rust_host/snapshot.py` to `yoyopod_cli/pi/support/rust_ui_host/snapshot.py`
- Move: `yoyopod/ui/rust_host/supervisor.py` to `yoyopod_cli/pi/support/rust_ui_host/supervisor.py`
- Create: `yoyopod_cli/pi/support/__init__.py`
- Create: `yoyopod_cli/pi/support/rust_ui_host/__init__.py`
- Modify: `yoyopod_cli/contracts/__init__.py`
- Modify: `yoyopod_cli/pi/network.py`
- Modify: `yoyopod_cli/pi/rust_ui_host.py`
- Modify: `yoyopod_cli/pi/validate/cloud_voice.py`
- Modify: `tests/cli/test_pi_rust_ui_host.py`
- Create: `tests/cli/test_worker_protocol_contract.py`

### Task 1.1: Move Worker Protocol Contract

- [ ] **Step 1: Move the protocol file**

Run:

```powershell
git mv yoyopod\core\workers\protocol.py yoyopod_cli\contracts\worker_protocol.py
```

Expected:

- `yoyopod_cli/contracts/worker_protocol.py` exists
- `yoyopod/core/workers/protocol.py` is removed from the active runtime package

- [ ] **Step 2: Update active imports**

Replace:

```python
from yoyopod.core.workers.protocol import (
    WorkerEnvelope,
    WorkerProtocolError,
    encode_envelope,
    make_envelope,
    parse_envelope_line,
)
```

with:

```python
from yoyopod_cli.contracts.worker_protocol import (
    WorkerEnvelope,
    WorkerProtocolError,
    encode_envelope,
    make_envelope,
    parse_envelope_line,
)
```

In:

```text
yoyopod_cli/pi/network.py
yoyopod_cli/pi/validate/cloud_voice.py
```

- [ ] **Step 3: Export the protocol from contracts package**

Append this to `yoyopod_cli/contracts/__init__.py`:

```python
from yoyopod_cli.contracts.worker_protocol import (
    SUPPORTED_SCHEMA_VERSION,
    WorkerEnvelope,
    WorkerProtocolError,
    encode_envelope,
    make_envelope,
    parse_envelope_line,
)
```

Add these names to `__all__`:

```python
    "SUPPORTED_SCHEMA_VERSION",
    "WorkerEnvelope",
    "WorkerProtocolError",
    "encode_envelope",
    "make_envelope",
    "parse_envelope_line",
```

- [ ] **Step 4: Add active protocol tests**

Create `tests/cli/test_worker_protocol_contract.py`:

```python
from __future__ import annotations

import pytest

from yoyopod_cli.contracts.worker_protocol import (
    WorkerProtocolError,
    encode_envelope,
    make_envelope,
    parse_envelope_line,
)


def test_worker_protocol_round_trips_command_envelope() -> None:
    envelope = make_envelope(
        kind="command",
        type="network.health",
        request_id="req-1",
        payload={"check": "modem"},
    )

    encoded = encode_envelope(envelope)
    parsed = parse_envelope_line(encoded)

    assert parsed == envelope
    assert encoded.endswith("\n")
    assert '"type":"network.health"' in encoded


def test_worker_protocol_rejects_invalid_kind() -> None:
    with pytest.raises(WorkerProtocolError, match="invalid worker envelope kind"):
        make_envelope(kind="not-a-kind", type="network.health")
```

- [ ] **Step 5: Run focused protocol tests**

Run:

```powershell
uv run pytest -q tests\cli\test_worker_protocol_contract.py tests\cli\test_yoyopod_cli_pi_network.py tests\cli\test_pi_validate_cloud_voice.py
```

Expected:

- all selected tests pass

### Task 1.2: Move Rust UI Host Support

- [ ] **Step 1: Create support package directories**

Run:

```powershell
New-Item -ItemType Directory -Force yoyopod_cli\pi\support\rust_ui_host | Out-Null
```

- [ ] **Step 2: Add package marker files**

Create `yoyopod_cli/pi/support/__init__.py`:

```python
"""Support modules for CLI-owned Pi validation commands."""

from __future__ import annotations
```

Create `yoyopod_cli/pi/support/rust_ui_host/__init__.py`:

```python
"""Rust UI host helpers used by the operations CLI."""

from __future__ import annotations

from yoyopod_cli.pi.support.rust_ui_host.protocol import UiEnvelope, UiProtocolError
from yoyopod_cli.pi.support.rust_ui_host.snapshot import RustUiRuntimeSnapshot
from yoyopod_cli.pi.support.rust_ui_host.supervisor import RustUiHostSupervisor

__all__ = [
    "RustUiHostSupervisor",
    "RustUiRuntimeSnapshot",
    "UiEnvelope",
    "UiProtocolError",
]
```

- [ ] **Step 3: Move Rust UI helper modules**

Run:

```powershell
git mv yoyopod\ui\rust_host\protocol.py yoyopod_cli\pi\support\rust_ui_host\protocol.py
git mv yoyopod\ui\rust_host\snapshot.py yoyopod_cli\pi\support\rust_ui_host\snapshot.py
git mv yoyopod\ui\rust_host\supervisor.py yoyopod_cli\pi\support\rust_ui_host\supervisor.py
```

- [ ] **Step 4: Update Rust UI active imports**

Replace:

```python
from yoyopod.ui.rust_host.protocol import UiEnvelope
from yoyopod.ui.rust_host.snapshot import RustUiRuntimeSnapshot
from yoyopod.ui.rust_host.supervisor import RustUiHostSupervisor
```

with:

```python
from yoyopod_cli.pi.support.rust_ui_host import (
    RustUiHostSupervisor,
    RustUiRuntimeSnapshot,
    UiEnvelope,
)
```

In:

```text
yoyopod_cli/pi/rust_ui_host.py
tests/cli/test_pi_rust_ui_host.py
```

- [ ] **Step 5: Update internal imports inside moved files**

Run:

```powershell
rg -n "yoyopod\.ui\.rust_host|from \.protocol|from \.snapshot" yoyopod_cli\pi\support\rust_ui_host tests\cli\test_pi_rust_ui_host.py
```

Expected:

- relative imports inside `yoyopod_cli/pi/support/rust_ui_host/*.py` are valid
- no import starts with `yoyopod.ui.rust_host`

- [ ] **Step 6: Run Rust UI host CLI tests**

Run:

```powershell
uv run pytest -q tests\cli\test_pi_rust_ui_host.py tests\cli\test_yoyopod_cli_shortcuts.py -k "rust_ui or ui_host or shortcut"
```

Expected:

- all selected tests pass

### Task 1.3: Commit Phase 1

- [ ] **Step 1: Run active worker/UI scan**

Run:

```powershell
rg -n "yoyopod\.core\.workers\.protocol|yoyopod\.ui\.rust_host" yoyopod_cli tests\cli -g "*.py"
```

Expected:

- no output

- [ ] **Step 2: Run quality gate**

Run:

```powershell
uv run python scripts\quality.py gate
```

Expected:

- exit code `0`

- [ ] **Step 3: Commit**

Run:

```powershell
git add yoyopod_cli tests\cli
git commit -m "refactor(cli): extract worker protocol support"
```

Expected:

- one focused commit exists

---

## Phase 2: Config Support Extraction

**Files:**

- Move: `yoyopod/config/` to `yoyopod_cli/config/`
- Modify: `yoyopod_cli/pi/power.py`
- Modify: `yoyopod_cli/pi/rust_voip_runtime.py`
- Modify: `yoyopod_cli/pi/validate/_common.py`
- Modify: `yoyopod_cli/pi/validate/cloud_voice.py`
- Modify: `yoyopod_cli/pi/validate/music.py`
- Modify: `yoyopod_cli/pi/validate/system.py`
- Modify: `yoyopod_cli/pi/validate/voip.py`
- Modify: `yoyopod_cli/voice.py`
- Modify: `tests/config/*.py`

### Task 2.1: Move Config Package

- [ ] **Step 1: Move config package**

Run:

```powershell
git mv yoyopod\config yoyopod_cli\config
```

Expected:

- `yoyopod_cli/config/__init__.py` exists
- `yoyopod/config` no longer exists

- [ ] **Step 2: Rewrite config imports**

Run:

```powershell
rg -l "yoyopod\.config" yoyopod_cli tests\config tests\cli -g "*.py" | ForEach-Object {
  (Get-Content $_) -replace "yoyopod\.config", "yoyopod_cli.config" | Set-Content $_
}
```

Expected:

- imports such as `from yoyopod.config import ConfigManager` now read
  `from yoyopod_cli.config import ConfigManager`
- imports such as `from yoyopod.config.models import ...` now read
  `from yoyopod_cli.config.models import ...`

- [ ] **Step 3: Rewrite internal config package imports**

Run:

```powershell
rg -l "yoyopod\.config" yoyopod_cli\config -g "*.py" | ForEach-Object {
  (Get-Content $_) -replace "yoyopod\.config", "yoyopod_cli.config" | Set-Content $_
}
```

Expected:

- no file under `yoyopod_cli/config` imports `yoyopod.config`

- [ ] **Step 4: Run config import scan**

Run:

```powershell
rg -n "yoyopod\.config" yoyopod_cli tests\config tests\cli -g "*.py"
```

Expected:

- no output

### Task 2.2: Move Contact Models Required By Config Tests

- [ ] **Step 1: Create contacts support module**

Create `yoyopod_cli/config/contacts.py`:

```python
"""Contact models used by config composition and CLI validation."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Contact:
    name: str
    sip_address: str
    aliases: tuple[str, ...] = field(default_factory=tuple)
    favorite: bool = False
    notes: str = ""
    can_call: bool = True
    can_message: bool = True
```

- [ ] **Step 2: Update active config tests to import contacts support**

Replace:

```python
from yoyopod.integrations.contacts.models import (
    Contact,
)
```

with:

```python
from yoyopod_cli.config.contacts import Contact
```

In:

```text
tests/config/test_config_helpers.py
```

- [ ] **Step 3: Update config code imports**

Run:

```powershell
rg -n "integrations\.contacts\.models|Contact" yoyopod_cli\config tests\config -g "*.py"
```

Expected:

- any active `Contact` import points at `yoyopod_cli.config.contacts`

### Task 2.3: Validate Config Extraction

- [ ] **Step 1: Run config tests**

Run:

```powershell
uv run pytest -q tests\config
```

Expected:

- all config tests pass

- [ ] **Step 2: Run CLI tests that load config**

Run:

```powershell
uv run pytest -q tests\cli\test_yoyopod_cli_voice.py tests\cli\test_pi_validate_cloud_voice.py tests\cli\test_pi_validate_voip.py tests\cli\test_yoyopod_cli_pi_validate.py
```

Expected:

- all selected tests pass

- [ ] **Step 3: Commit Phase 2**

Run:

```powershell
git add yoyopod_cli tests\config tests\cli
git commit -m "refactor(cli): move config support into cli package"
```

Expected:

- config support imports are owned by `yoyopod_cli.config`

---

## Phase 3: Voice CLI And Cloud Voice Validation Support

**Files:**

- Move: `yoyopod/integrations/voice/dictionary.py` to `yoyopod_cli/pi/support/voice_dictionary.py`
- Move: `yoyopod/integrations/voice/dictionary_validator.py` to `yoyopod_cli/pi/support/voice_dictionary_validator.py`
- Move: `yoyopod/integrations/voice/models.py` to `yoyopod_cli/pi/support/voice_models.py`
- Move: `yoyopod/integrations/voice/settings.py` to `yoyopod_cli/pi/support/voice_settings.py`
- Move: `yoyopod/integrations/voice/trace.py` to `yoyopod_cli/pi/support/voice_trace.py`
- Move: `yoyopod/integrations/voice/trace_analysis.py` to `yoyopod_cli/pi/support/voice_trace_analysis.py`
- Move: `yoyopod/integrations/voice/worker_contract.py` to `yoyopod_cli/pi/support/voice_worker_contract.py`
- Move: `yoyopod/backends/voice/output.py` to `yoyopod_cli/pi/support/voice_output.py`
- Modify: `yoyopod_cli/voice.py`
- Modify: `yoyopod_cli/pi/validate/cloud_voice.py`
- Modify: `tests/cli/test_yoyopod_cli_voice.py`
- Modify: `tests/cli/test_pi_validate_cloud_voice.py`

### Task 3.1: Move Voice Support Modules

- [ ] **Step 1: Move voice contract modules**

Run:

```powershell
git mv yoyopod\integrations\voice\dictionary.py yoyopod_cli\pi\support\voice_dictionary.py
git mv yoyopod\integrations\voice\dictionary_validator.py yoyopod_cli\pi\support\voice_dictionary_validator.py
git mv yoyopod\integrations\voice\models.py yoyopod_cli\pi\support\voice_models.py
git mv yoyopod\integrations\voice\settings.py yoyopod_cli\pi\support\voice_settings.py
git mv yoyopod\integrations\voice\trace.py yoyopod_cli\pi\support\voice_trace.py
git mv yoyopod\integrations\voice\trace_analysis.py yoyopod_cli\pi\support\voice_trace_analysis.py
git mv yoyopod\integrations\voice\worker_contract.py yoyopod_cli\pi\support\voice_worker_contract.py
git mv yoyopod\backends\voice\output.py yoyopod_cli\pi\support\voice_output.py
```

- [ ] **Step 2: Update voice CLI imports**

In `yoyopod_cli/voice.py`, replace:

```python
from yoyopod.integrations.voice.dictionary_validator import validate_voice_command_dictionary
from yoyopod.integrations.voice.trace import VoiceTraceStore
from yoyopod.integrations.voice.trace_analysis import analyze_voice_trace
```

with:

```python
from yoyopod_cli.pi.support.voice_dictionary_validator import (
    validate_voice_command_dictionary,
)
from yoyopod_cli.pi.support.voice_trace import VoiceTraceStore
from yoyopod_cli.pi.support.voice_trace_analysis import analyze_voice_trace
```

- [ ] **Step 3: Update cloud voice validation imports**

In `yoyopod_cli/pi/validate/cloud_voice.py`, replace:

```python
from yoyopod.integrations.voice import VoiceSettings, match_voice_command
from yoyopod.integrations.voice.worker_contract import (
```

with:

```python
from yoyopod_cli.pi.support.voice_dictionary import match_voice_command
from yoyopod_cli.pi.support.voice_settings import VoiceSettings
from yoyopod_cli.pi.support.voice_worker_contract import (
```

Replace:

```python
from yoyopod.backends.voice.output import AlsaOutputPlayer
```

with:

```python
from yoyopod_cli.pi.support.voice_output import AlsaOutputPlayer
```

Replace:

```python
from yoyopod.integrations.voice.settings import VoiceSettingsResolver
```

with:

```python
from yoyopod_cli.pi.support.voice_settings import VoiceSettingsResolver
```

- [ ] **Step 4: Rewrite internal moved-module imports**

Run:

```powershell
rg -l "yoyopod\.integrations\.voice|yoyopod\.backends\.voice|yoyopod\.config" yoyopod_cli\pi\support -g "*.py" | ForEach-Object {
  (Get-Content $_) `
    -replace "yoyopod\.integrations\.voice\.dictionary_validator", "yoyopod_cli.pi.support.voice_dictionary_validator" `
    -replace "yoyopod\.integrations\.voice\.dictionary", "yoyopod_cli.pi.support.voice_dictionary" `
    -replace "yoyopod\.integrations\.voice\.models", "yoyopod_cli.pi.support.voice_models" `
    -replace "yoyopod\.integrations\.voice\.settings", "yoyopod_cli.pi.support.voice_settings" `
    -replace "yoyopod\.integrations\.voice\.trace_analysis", "yoyopod_cli.pi.support.voice_trace_analysis" `
    -replace "yoyopod\.integrations\.voice\.trace", "yoyopod_cli.pi.support.voice_trace" `
    -replace "yoyopod\.integrations\.voice\.worker_contract", "yoyopod_cli.pi.support.voice_worker_contract" `
    -replace "yoyopod\.backends\.voice\.output", "yoyopod_cli.pi.support.voice_output" `
    -replace "yoyopod\.config", "yoyopod_cli.config" |
  Set-Content $_
}
```

Expected:

- moved voice support modules no longer import `yoyopod.integrations.voice`
- moved voice support modules no longer import `yoyopod.backends.voice`

### Task 3.2: Validate Voice Extraction

- [ ] **Step 1: Run voice import scan**

Run:

```powershell
rg -n "yoyopod\.integrations\.voice|yoyopod\.backends\.voice" yoyopod_cli tests\cli -g "*.py"
```

Expected:

- no output except string literals in tests that intentionally patch old names
- update those patch strings to the new `yoyopod_cli.pi.support.*` module paths

- [ ] **Step 2: Run voice tests**

Run:

```powershell
uv run pytest -q tests\cli\test_yoyopod_cli_voice.py tests\cli\test_pi_validate_cloud_voice.py
```

Expected:

- all selected tests pass

- [ ] **Step 3: Commit Phase 3**

Run:

```powershell
git add yoyopod_cli tests\cli
git commit -m "refactor(cli): move voice support into cli package"
```

Expected:

- voice CLI and cloud voice validation no longer depend on `yoyopod.integrations.voice`

---

## Phase 4: Pi Validation Runtime Import Replacement

**Files:**

- Create: `yoyopod_cli/pi/support/input.py`
- Create: `yoyopod_cli/pi/support/call_models.py`
- Move: `yoyopod/backends/cloud/` to `yoyopod_cli/pi/support/cloud_backend/`
- Move: `yoyopod/integrations/cloud/` to `yoyopod_cli/pi/support/cloud_integration/`
- Move: `yoyopod/backends/music/` to `yoyopod_cli/pi/support/music_backend/`
- Move: `yoyopod/integrations/music/` to `yoyopod_cli/pi/support/music_integration/`
- Move: `yoyopod/backends/power/` to `yoyopod_cli/pi/support/power_backend/`
- Move: `yoyopod/integrations/power/` to `yoyopod_cli/pi/support/power_integration/`
- Move: `yoyopod/backends/voip/` to `yoyopod_cli/pi/support/voip_backend/`
- Move: `yoyopod/integrations/call/` to `yoyopod_cli/pi/support/call_integration/`
- Move: `yoyopod/ui/display/` to `yoyopod_cli/pi/support/display/`
- Move: `yoyopod/ui/input/` to `yoyopod_cli/pi/support/input_runtime/`
- Move: `yoyopod/ui/lvgl_binding/` to `yoyopod_cli/pi/support/lvgl_binding/`
- Modify: `yoyopod_cli/pi/power.py`
- Modify: `yoyopod_cli/pi/voip.py`
- Modify: `yoyopod_cli/pi/rust_voip_runtime.py`
- Modify: `yoyopod_cli/pi/validate/_common.py`
- Modify: `yoyopod_cli/pi/validate/_navigation_soak/*.py`
- Modify: `yoyopod_cli/pi/validate/music.py`
- Modify: `yoyopod_cli/pi/validate/system.py`
- Modify: `yoyopod_cli/pi/validate/voip.py`
- Modify: `tests/cli/test_pi_validate_helpers.py`
- Modify: `tests/cli/test_voip_cli.py`
- Modify: `tests/cli/test_yoyopod_cli_pi_validate.py`

### Task 4.1: Move Small Data Contracts

- [ ] **Step 1: Create input support contract**

Create `yoyopod_cli/pi/support/input.py`:

```python
"""Input action contracts used by CLI validation."""

from __future__ import annotations

from enum import StrEnum


class InputAction(StrEnum):
    UP = "up"
    DOWN = "down"
    LEFT = "left"
    RIGHT = "right"
    SELECT = "select"
    BACK = "back"
    PTT_PRESS = "ptt_press"
    PTT_RELEASE = "ptt_release"
```

- [ ] **Step 2: Create call model support contract**

Create `yoyopod_cli/pi/support/call_models.py`:

```python
"""VoIP state contracts used by CLI validation."""

from __future__ import annotations

from enum import StrEnum


class RegistrationState(StrEnum):
    UNREGISTERED = "unregistered"
    REGISTERING = "registering"
    REGISTERED = "registered"
    FAILED = "failed"


class CallState(StrEnum):
    IDLE = "idle"
    INCOMING = "incoming"
    OUTGOING = "outgoing"
    RINGING = "ringing"
    CONNECTED = "connected"
    ENDED = "ended"
    FAILED = "failed"
```

- [ ] **Step 3: Update direct model imports**

Replace:

```python
from yoyopod.ui.input import InputAction
```

with:

```python
from yoyopod_cli.pi.support.input import InputAction
```

Replace:

```python
from yoyopod.integrations.call.models import CallState, RegistrationState
```

with:

```python
from yoyopod_cli.pi.support.call_models import CallState, RegistrationState
```

In:

```text
yoyopod_cli/pi/voip.py
yoyopod_cli/pi/validate/_navigation_soak/plan.py
yoyopod_cli/pi/validate/_navigation_soak/pump.py
yoyopod_cli/pi/validate/_navigation_soak/runner.py
yoyopod_cli/pi/validate/voip.py
tests/cli/test_pi_validate_helpers.py
tests/cli/test_voip_cli.py
```

### Task 4.2: Retire Python App Navigation Soak Factory

- [ ] **Step 1: Remove default `YoyoPodApp` construction**

In `yoyopod_cli/pi/validate/_navigation_soak/handle.py`, replace
`_default_app_factory` with:

```python
def _default_app_factory(*, config_dir: str, simulate: bool) -> _NavigationSoakAppHandle:
    """Reject direct Python app soak execution after the Rust runtime cutover."""

    from yoyopod_cli.pi.validate._navigation_soak.plan import NavigationSoakError

    _ = (config_dir, simulate)
    raise NavigationSoakError(
        "navigation soak no longer constructs the retired Python app runtime; "
        "use hardware-backed Rust runtime validation instead"
    )
```

- [ ] **Step 2: Update navigation soak tests**

In `tests/cli/test_pi_validate_helpers.py`, replace fake `yoyopod.app`
module setup with assertions that the default factory fails:

```python
from yoyopod_cli.pi.validate._navigation_soak.handle import _default_app_factory
from yoyopod_cli.pi.validate._navigation_soak.plan import NavigationSoakError


def test_default_navigation_soak_factory_rejects_python_runtime() -> None:
    with pytest.raises(NavigationSoakError, match="retired Python app runtime"):
        _default_app_factory(config_dir="config", simulate=False)
```

- [ ] **Step 3: Keep injected factory tests**

Keep tests that pass an explicit fake app factory into the soak runner. Those
tests verify the plan/pump logic without importing `yoyopod.app`.

### Task 4.3: Move Or Replace Remaining Hardware Support Imports

- [ ] **Step 1: Scan remaining active runtime imports**

Run:

```powershell
rg -n "from yoyopod\\.|import yoyopod|yoyopod\\." yoyopod_cli tests\cli tests\config -g "*.py"
```

Expected:

- remaining output is limited to power, music, cloud, display, or VoIP runtime
  support imports

- [ ] **Step 2: Move cloud support used only by config tests**

Move cloud models/errors that are still active:

```powershell
git mv yoyopod\backends\cloud yoyopod_cli\pi\support\cloud_backend
git mv yoyopod\integrations\cloud yoyopod_cli\pi\support\cloud_integration
```

Rewrite imports:

```powershell
rg -l "yoyopod\.backends\.cloud|yoyopod\.integrations\.cloud" yoyopod_cli tests\config tests\cli -g "*.py" | ForEach-Object {
  (Get-Content $_) `
    -replace "yoyopod\.backends\.cloud", "yoyopod_cli.pi.support.cloud_backend" `
    -replace "yoyopod\.integrations\.cloud", "yoyopod_cli.pi.support.cloud_integration" |
  Set-Content $_
}
```

- [ ] **Step 3: Move music support used by validation**

Move active music support:

```powershell
git mv yoyopod\backends\music yoyopod_cli\pi\support\music_backend
git mv yoyopod\integrations\music yoyopod_cli\pi\support\music_integration
```

Rewrite imports:

```powershell
rg -l "yoyopod\.backends\.music|yoyopod\.integrations\.music" yoyopod_cli tests\config tests\cli -g "*.py" | ForEach-Object {
  (Get-Content $_) `
    -replace "yoyopod\.backends\.music", "yoyopod_cli.pi.support.music_backend" `
    -replace "yoyopod\.integrations\.music", "yoyopod_cli.pi.support.music_integration" |
  Set-Content $_
}
```

- [ ] **Step 4: Move power support used by validation**

Move active power support:

```powershell
git mv yoyopod\integrations\power yoyopod_cli\pi\support\power_integration
git mv yoyopod\backends\power yoyopod_cli\pi\support\power_backend
```

Rewrite imports:

```powershell
rg -l "yoyopod\.integrations\.power|yoyopod\.backends\.power" yoyopod_cli tests\config tests\cli -g "*.py" | ForEach-Object {
  (Get-Content $_) `
    -replace "yoyopod\.integrations\.power", "yoyopod_cli.pi.support.power_integration" `
    -replace "yoyopod\.backends\.power", "yoyopod_cli.pi.support.power_backend" |
  Set-Content $_
}
```

- [ ] **Step 5: Move VoIP support used by validation**

Move active VoIP support:

```powershell
git mv yoyopod\integrations\call yoyopod_cli\pi\support\call_integration
git mv yoyopod\backends\voip yoyopod_cli\pi\support\voip_backend
```

Rewrite imports:

```powershell
rg -l "yoyopod\.integrations\.call|yoyopod\.backends\.voip" yoyopod_cli tests\config tests\cli -g "*.py" | ForEach-Object {
  (Get-Content $_) `
    -replace "yoyopod\.integrations\.call", "yoyopod_cli.pi.support.call_integration" `
    -replace "yoyopod\.backends\.voip", "yoyopod_cli.pi.support.voip_backend" |
  Set-Content $_
}
```

- [ ] **Step 6: Move display/input hardware helpers used by system validation**

Move active display/input support:

```powershell
git mv yoyopod\ui\display yoyopod_cli\pi\support\display
git mv yoyopod\ui\input yoyopod_cli\pi\support\input_runtime
git mv yoyopod\ui\lvgl_binding yoyopod_cli\pi\support\lvgl_binding
```

Rewrite imports:

```powershell
rg -l "yoyopod\.ui\.display|yoyopod\.ui\.input|yoyopod\.ui\.lvgl_binding" yoyopod_cli tests\config tests\cli -g "*.py" | ForEach-Object {
  (Get-Content $_) `
    -replace "yoyopod\.ui\.display", "yoyopod_cli.pi.support.display" `
    -replace "yoyopod\.ui\.input", "yoyopod_cli.pi.support.input_runtime" `
    -replace "yoyopod\.ui\.lvgl_binding", "yoyopod_cli.pi.support.lvgl_binding" |
  Set-Content $_
}
```

### Task 4.4: Validate Pi Support Extraction

- [ ] **Step 1: Run active import scan**

Run:

```powershell
rg -n "from yoyopod\\.|import yoyopod|yoyopod\\." yoyopod_cli tests\cli tests\config tests\deploy tests\device tests\scripts -g "*.py"
```

Expected:

- no output except string literals in negative tests
- update negative-test strings to avoid matching this scan by building strings
  from parts, for example `"python " + "yoyopod.py"`

- [ ] **Step 2: Run CLI and config tests**

Run:

```powershell
uv run pytest -q tests\cli tests\config
```

Expected:

- all tests pass

- [ ] **Step 3: Commit Phase 4**

Run:

```powershell
git add yoyopod_cli tests\cli tests\config
git commit -m "refactor(cli): extract pi validation support"
```

Expected:

- active CLI and config tests no longer import `yoyopod.*`

---

## Phase 5: Active Guard Tests

**Files:**

- Create: `tests/cli/test_no_active_yoyopod_runtime_imports.py`
- Create: `tests/cli/test_python_package_surface.py`
- Modify: `tests/cli/test_yoyopod_cli_bootstrap.py`

### Task 5.1: Add Active Import Guard

- [ ] **Step 1: Create import guard test**

Create `tests/cli/test_no_active_yoyopod_runtime_imports.py`:

```python
from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
ACTIVE_ROOTS = (
    REPO_ROOT / "yoyopod_cli",
    REPO_ROOT / "tests" / "cli",
    REPO_ROOT / "tests" / "config",
    REPO_ROOT / "tests" / "deploy",
    REPO_ROOT / "tests" / "device",
    REPO_ROOT / "tests" / "scripts",
)
PATTERNS = (
    "from yoyopod.",
    "import yoyopod.",
    "yoyopod.",
)


def _active_python_files() -> list[Path]:
    files: list[Path] = []
    for root in ACTIVE_ROOTS:
        if not root.exists():
            continue
        files.extend(
            path
            for path in root.rglob("*.py")
            if "__pycache__" not in path.parts
            and path.name != "test_no_active_yoyopod_runtime_imports.py"
        )
    return files


def test_active_python_sources_do_not_import_retired_yoyopod_runtime() -> None:
    offenders: list[str] = []
    for path in _active_python_files():
        text = path.read_text(encoding="utf-8")
        for pattern in PATTERNS:
            if pattern in text:
                offenders.append(f"{path.relative_to(REPO_ROOT)} contains {pattern!r}")

    assert offenders == []
```

- [ ] **Step 2: Run the guard**

Run:

```powershell
uv run pytest -q tests\cli\test_no_active_yoyopod_runtime_imports.py
```

Expected:

- test passes

### Task 5.2: Add Packaging Surface Guard

- [ ] **Step 1: Create package surface test**

Create `tests/cli/test_python_package_surface.py`:

```python
from __future__ import annotations

from pathlib import Path

import tomllib


REPO_ROOT = Path(__file__).resolve().parents[2]


def _pyproject() -> dict[str, object]:
    with (REPO_ROOT / "pyproject.toml").open("rb") as handle:
        return tomllib.load(handle)


def test_wheel_packages_only_cli_package() -> None:
    pyproject = _pyproject()
    wheel = pyproject["tool"]["hatch"]["build"]["targets"]["wheel"]

    assert wheel["packages"] == ["yoyopod_cli"]


def test_sdist_does_not_include_retired_python_runtime() -> None:
    pyproject = _pyproject()
    sdist = pyproject["tool"]["hatch"]["build"]["targets"]["sdist"]

    assert "/yoyopod" not in sdist["include"]
    assert "/yoyopod.py" not in sdist["include"]
    assert "/legacy" not in sdist["include"]
```

- [ ] **Step 2: Run the package surface test and confirm it fails before Phase 6**

Run:

```powershell
uv run pytest -q tests\cli\test_python_package_surface.py
```

Expected:

- fails because `pyproject.toml` still packages `yoyopod`

- [ ] **Step 3: Do not commit yet**

Expected:

- keep these tests unstaged until Phase 6 updates packaging

---

## Phase 6: Quarantine Runtime Package And Remove Packaging Surface

**Files:**

- Move: `yoyopod/` to `legacy/python-runtime/yoyopod/`
- Modify: `legacy/python-runtime/README.md`
- Modify: `pyproject.toml`
- Modify: `tests/cli/test_python_package_surface.py`
- Modify: `tests/cli/test_yoyopod_cli_bootstrap.py`

### Task 6.1: Move Runtime Package To Legacy

- [ ] **Step 1: Confirm active import scan is clean**

Run:

```powershell
rg -n "from yoyopod\\.|import yoyopod|yoyopod\\." yoyopod_cli tests\cli tests\config tests\deploy tests\device tests\scripts -g "*.py"
```

Expected:

- no output

- [ ] **Step 2: Move the remaining package to legacy**

Run:

```powershell
git mv yoyopod legacy\python-runtime\yoyopod
```

Expected:

- repo root no longer has `yoyopod/`
- `legacy/python-runtime/yoyopod/` exists

- [ ] **Step 3: Update legacy README**

Replace `legacy/python-runtime/README.md` with:

```markdown
# Legacy Python Runtime

This directory contains the retired Python app runtime. It is not a supported
runtime owner for the device and is excluded from packaging and default tests.

Supported runtime code lives under `device/`. Supported operations tooling
lives under `yoyopod_cli/`.

Do not import this directory from active code. Delete this directory after the
Rust runtime has completed one hardware validation cycle without needing Python
runtime parity inspection.
```

### Task 6.2: Remove `yoyopod` From Packaging

- [ ] **Step 1: Update wheel package list**

In `pyproject.toml`, replace:

```toml
[tool.hatch.build.targets.wheel]
packages = ["yoyopod", "yoyopod_cli"]
```

with:

```toml
[tool.hatch.build.targets.wheel]
packages = ["yoyopod_cli"]
```

- [ ] **Step 2: Update sdist includes**

In `pyproject.toml`, replace:

```toml
include = [
    "/README.md",
    "/pyproject.toml",
    "/yoyopod",
    "/yoyopod.py",
    "/yoyopod_cli",
]
```

with:

```toml
include = [
    "/README.md",
    "/pyproject.toml",
    "/yoyopod_cli",
]
```

- [ ] **Step 3: Update quality audit type paths**

In `pyproject.toml`, replace:

```toml
audit_type_paths = ["yoyopod"]
```

with:

```toml
audit_type_paths = ["yoyopod_cli"]
```

### Task 6.3: Validate Packaging Surface

- [ ] **Step 1: Run package guard tests**

Run:

```powershell
uv run pytest -q tests\cli\test_python_package_surface.py tests\cli\test_yoyopod_cli_bootstrap.py
```

Expected:

- all selected tests pass

- [ ] **Step 2: Build wheel and inspect contents**

Run:

```powershell
Remove-Item -Recurse -Force dist -ErrorAction SilentlyContinue
uv build --wheel
python -m zipfile -l (Get-ChildItem dist\*.whl | Select-Object -First 1).FullName
```

Expected:

- output contains `yoyopod_cli/`
- output does not contain `yoyopod/`
- output does not contain `legacy/python-runtime`

- [ ] **Step 3: Run CLI smoke from the working tree**

Run:

```powershell
uv run yoyopod --help
```

Expected:

- exit code `0`
- output contains `YoYoPod operations CLI`

- [ ] **Step 4: Commit Phase 6 and guard tests**

Run:

```powershell
git add pyproject.toml legacy tests\cli yoyopod_cli
git commit -m "refactor: quarantine retired python runtime package"
```

Expected:

- root `yoyopod/` is gone
- wheel package surface is `yoyopod_cli` only

---

## Phase 7: Final Validation And Handoff

**Files:**

- No planned source files
- Modify PR body if validation results need updating

### Task 7.1: Full Local Validation

- [ ] **Step 1: Run active import and path scans**

Run:

```powershell
rg -n "from yoyopod\\.|import yoyopod|yoyopod\\." yoyopod_cli tests\cli tests\config tests\deploy tests\device tests\scripts -g "*.py"
rg -n "python yoyopod.py|yoyopod.py --simulate|from yoyopod\\.main|import yoyopod\\.main" . -g "!legacy/**" -g "!tests/legacy_python_runtime/**" -g "!device/target/**" -g "!.git/**"
rg -n "yoyopod_rs/" . -g "!docs/archive/**" -g "!docs/history/**" -g "!docs/superpowers/**" -g "!device/target/**" -g "!.git/**"
```

Expected:

- no active-source output

- [ ] **Step 2: Run Python validation**

Run:

```powershell
uv run python scripts\quality.py gate
uv run pytest -q tests\cli tests\deploy tests\config tests\device tests\scripts
```

Expected:

- both commands pass

- [ ] **Step 3: Run Rust validation**

Run:

```powershell
cargo test --manifest-path device\Cargo.toml --workspace --locked
cargo clippy --manifest-path device\Cargo.toml --workspace --all-targets --locked -- -D warnings
cargo fmt --manifest-path device\Cargo.toml --all --check
```

Expected:

- all commands pass

- [ ] **Step 4: Build runtime artifacts**

Run:

```powershell
uv run yoyopod build rust-runtime
uv run yoyopod build voice-worker
```

Expected:

- `device/runtime/build/yoyopod-runtime.exe` exists on Windows
- `device/speech/build/yoyopod-speech-host.exe` exists on Windows

- [ ] **Step 5: Run repository cleanliness checks**

Run:

```powershell
git diff --check
git ls-files -ci --exclude-standard
git status --short --branch
```

Expected:

- `git diff --check` passes
- ignored tracked files scan prints nothing
- branch has only committed changes

### Task 7.2: Push And PR

- [ ] **Step 1: Push branch**

Run:

```powershell
git push -u origin (git branch --show-current)
```

Expected:

- branch pushes successfully

- [ ] **Step 2: Create draft PR**

Run:

```powershell
$body = @'
## Summary
- move CLI-needed Python support out of the retired `yoyopod/` runtime package
- keep operations code under `yoyopod_cli/`
- quarantine the old Python runtime under `legacy/python-runtime/yoyopod/`
- remove `yoyopod` from wheel and sdist packaging
- add guards preventing active `yoyopod.*` imports from returning

## Validation
- `uv run python scripts\quality.py gate`
- `uv run pytest -q tests\cli tests\deploy tests\config tests\device tests\scripts`
- `cargo test --manifest-path device\Cargo.toml --workspace --locked`
- `cargo clippy --manifest-path device\Cargo.toml --workspace --all-targets --locked -- -D warnings`
- `cargo fmt --manifest-path device\Cargo.toml --all --check`
- `uv run yoyopod build rust-runtime`
- `uv run yoyopod build voice-worker`
'@
gh pr create --draft --base main --head (git branch --show-current) --title "[codex] Extract Python support from retired runtime" --body $body
```

Expected:

- draft PR URL is printed

---

## Review Checklist

- [ ] `yoyopod_cli/` has no active imports from `yoyopod.*`.
- [ ] Active tests under `tests/cli`, `tests/config`, `tests/deploy`,
      `tests/device`, and `tests/scripts` have no imports from `yoyopod.*`.
- [ ] `yoyopod/` no longer exists at repo root.
- [ ] Retired runtime code is under `legacy/python-runtime/yoyopod/`.
- [ ] Wheel packaging includes only `yoyopod_cli`.
- [ ] Sdist packaging excludes `yoyopod/`, `yoyopod.py`, and `legacy/`.
- [ ] `uv run yoyopod --help` works.
- [ ] Rust runtime and worker validation still passes.
- [ ] No supported launch path points at Python runtime.
- [ ] The PR body clearly states that legacy code is quarantined, not active.
