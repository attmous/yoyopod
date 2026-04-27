# pi_validate Split Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split `yoyopod_cli/pi_validate.py` (2940 LOC) + `_pi_validate_helpers.py` (1350 LOC) + `pi_validate_helpers.py` (shim) into a `yoyopod_cli/pi_validate/` subpackage with one module per validation domain plus a focused `_navigation_soak/` sub-subpackage. No behavior changes.

**Architecture:** Pure mechanical refactor in three logical phases: (1) capture baseline fixtures, (2) build the new package contents under a temporary name `_pi_validate_pkg/` to avoid the file-vs-package import collision, (3) atomic switchover that deletes the old files, renames the temp package to `pi_validate/`, updates the four test files that touched private symbols, and verifies the gate + tests + smoke. Each task leaves the codebase in a working state so the PR is bisectable.

**Tech Stack:** Python 3.12, typer (CLI), pytest, black/ruff/mypy gate via `scripts/quality.py`, uv for environments.

**Spec:** [docs/superpowers/specs/2026-04-27-pi-validate-split-design.md](../specs/2026-04-27-pi-validate-split-design.md) — the line-by-line module mapping table in §5 of the spec is the source of truth for what code lands where. This plan describes the procedure; consult the spec for which lines move.

---

## Phase 1: Baseline capture

### Task 1: Capture CLI baseline help output

**Files:**
- Create: `tests/cli/_pi_validate_help_baseline.txt` (gitignored after task 14)

- [ ] **Step 1: Capture baseline `--help` output for the 8 subcommands**

Use programmatic `CliRunner` capture with a fixed terminal width so later diffs aren't polluted by terminal-width differences:

```bash
mkdir -p .tmp/pi_validate_baseline
uv run python - <<'PY'
from pathlib import Path
from typer.testing import CliRunner
from yoyopod_cli import pi_validate

runner = CliRunner()
out = Path(".tmp/pi_validate_baseline")
out.mkdir(parents=True, exist_ok=True)

(out / "_root.txt").write_text(runner.invoke(pi_validate.app, ["--help"], terminal_width=200).stdout)
for sub in ["deploy", "cloud-voice", "smoke", "music", "voip", "stability", "navigation", "lvgl"]:
    result = runner.invoke(pi_validate.app, [sub, "--help"], terminal_width=200)
    (out / f"{sub.replace('-', '_')}.txt").write_text(result.stdout)
print("baseline captured")
PY
ls -la .tmp/pi_validate_baseline/
```

Expected: `baseline captured` printed; 9 files in `.tmp/pi_validate_baseline/`, each non-empty. The `_root.txt` lists all 8 subcommands.

> **Note on subcommand names:** the baseline script uses `cloud-voice` (hyphen). If the original `pi_validate.py` registers it as `cloud_voice` (underscore), the script will fail with "no such command." If that happens, switch to underscore here AND in Task 9 step 1's `app.command(name=...)` calls. Use whatever the original used. Look at the original `@app.command(...)` decorators in `pi_validate.py` to confirm.

- [ ] **Step 2: Verify baseline test suite passes (no commit yet)**

Run: `uv run pytest -q tests/cli/`
Expected: PASS (no errors related to pi_validate). On Windows, ignore any known Windows-specific failures per `CLAUDE.md`.

- [ ] **Step 3: Verify quality gate passes on a clean tree**

Run: `uv run python scripts/quality.py gate`
Expected: `[quality] result=passed`. If the gate fails on `main` HEAD, stop and surface to user — there's pre-existing breakage.

(No commit for this task. Baseline outputs live in `.tmp/` and are reference material for Task 14.)

---

## Phase 2: Build new structure under temporary name

> **Why a temp name:** Python won't allow `pi_validate.py` (file) and `pi_validate/` (directory) to coexist in the same parent — the import resolution becomes ambiguous. We build the new package as `_pi_validate_pkg/` while the old file still works, then rename in Task 11.

### Task 2: Create the `_pi_validate_pkg/` scaffold

**Files:**
- Create: `yoyopod_cli/_pi_validate_pkg/__init__.py` (empty for now)
- Create: `yoyopod_cli/_pi_validate_pkg/_common.py`
- Create: `yoyopod_cli/_pi_validate_pkg/_navigation_soak/__init__.py` (empty for now)

- [ ] **Step 1: Create the directory tree and empty `__init__.py` files**

Run:
```bash
mkdir -p yoyopod_cli/_pi_validate_pkg/_navigation_soak
touch yoyopod_cli/_pi_validate_pkg/__init__.py
touch yoyopod_cli/_pi_validate_pkg/_navigation_soak/__init__.py
touch yoyopod_cli/_pi_validate_pkg/_common.py
```

- [ ] **Step 2: Verify tests still pass**

Run: `uv run pytest -q tests/cli/`
Expected: PASS. The empty package isn't imported by anything yet.

- [ ] **Step 3: Commit**

```bash
git add yoyopod_cli/_pi_validate_pkg/
git commit -m "refactor(pi_validate): scaffold _pi_validate_pkg package"
```

### Task 3: Populate `_common.py` with shared helpers

**Files:**
- Modify: `yoyopod_cli/_pi_validate_pkg/_common.py`
- Reference: `yoyopod_cli/pi_validate.py:66-103, 88-103, 995-1018` (per spec §5)

- [ ] **Step 1: Copy shared helpers from `pi_validate.py` into `_common.py`**

Move these symbols (per spec §5) — copy the function bodies and class definitions verbatim from `yoyopod_cli/pi_validate.py`:

- Lines 66–103: `_CheckResult`, `_print_summary`, `_resolve_runtime_path`, `_nearest_existing_parent`
- Lines 995–1018: `_load_app_config`, `_load_media_config`

The new `_common.py` needs these imports (derive from the original file's imports — keep only what these symbols use):
```python
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any
import json

if TYPE_CHECKING:
    from yoyopod.config import MediaConfig
```

Do NOT modify `pi_validate.py` yet. The new file is a parallel copy at this stage.

- [ ] **Step 2: Verify the new module imports cleanly**

Run: `uv run python -c "from yoyopod_cli._pi_validate_pkg import _common; print(_common._CheckResult)"`
Expected: prints `<class 'yoyopod_cli._pi_validate_pkg._common._CheckResult'>`. No ImportError.

- [ ] **Step 3: Run gate (catches any black/ruff issues in the new file)**

Run: `uv run python scripts/quality.py gate`
Expected: `[quality] result=passed`.

- [ ] **Step 4: Commit**

```bash
git add yoyopod_cli/_pi_validate_pkg/_common.py
git commit -m "refactor(pi_validate): extract shared helpers to _common"
```

### Task 4: Build `_navigation_soak/` subpackage

**Files:**
- Create: `yoyopod_cli/_pi_validate_pkg/_navigation_soak/handle.py`
- Create: `yoyopod_cli/_pi_validate_pkg/_navigation_soak/plan.py`
- Create: `yoyopod_cli/_pi_validate_pkg/_navigation_soak/pump.py`
- Create: `yoyopod_cli/_pi_validate_pkg/_navigation_soak/idle.py`
- Create: `yoyopod_cli/_pi_validate_pkg/_navigation_soak/runner.py`
- Modify: `yoyopod_cli/_pi_validate_pkg/_navigation_soak/__init__.py`
- Reference: `yoyopod_cli/_pi_validate_helpers.py` (per spec §5)

- [ ] **Step 1: Create `handle.py` with app handle protocols (lines 27–234 of `_pi_validate_helpers.py`)**

Copy these symbols verbatim:
- `_NavigationSoakAppHandle` (Protocol)
- `_YoyoPodAppNavigationSoakHandle`
- `_NavigationSoakAppFactory` (Protocol)
- `_default_app_factory`

Required imports:
```python
from __future__ import annotations
from typing import Any, Protocol
from yoyopod.ui.input import InputAction, InteractionProfile
```

(Add other imports as needed by the copied bodies — look at the head of `_pi_validate_helpers.py` for the original import list and prune.)

- [ ] **Step 2: Create `plan.py` with plan/report dataclasses (lines 236–432)**

Copy verbatim:
- `NavigationSoakError`
- `NavigationSoakStep`
- `NavigationSoakReport`
- `build_navigation_soak_plan`

Required imports:
```python
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any
from yoyopod.ui.input import InputAction
```

- [ ] **Step 3: Create `pump.py` with pump utilities (lines 434–595)**

Copy verbatim:
- `_temporary_env`
- `_pump_app`
- `_current_route`
- `_dispatch_action`
- `_reset_selection`
- `_wait_for_route`
- `_wait_for_track`
- `_exercise_sleep_wake`
- `_prepare_validation_music_dir`

These import from `handle.py` (`_NavigationSoakAppHandle` for type hints) — use `from .handle import _NavigationSoakAppHandle`.

- [ ] **Step 4: Create `idle.py` with idle soak (lines 596–716)**

Copy verbatim:
- `run_navigation_idle_soak`
- Any helpers used only by it

Imports from `plan.py` (`NavigationSoakStep`, `NavigationSoakReport`) and `pump.py` and `handle.py` as the body requires. Use relative imports (`from .plan import ...`, `from .pump import ...`).

- [ ] **Step 5: Create `runner.py` with active soak runner (lines 717–end)**

Copy verbatim:
- `NavigationSoakFailure`
- `NavigationSoakStats`
- `_temporary_env_var`
- `_RuntimePump`
- `NavigationSoakRunner`
- `run_navigation_soak`

Imports from `plan.py`, `pump.py`, `handle.py` as the body requires.

- [ ] **Step 6: Wire `_navigation_soak/__init__.py` re-exports**

Replace empty `__init__.py` with:
```python
"""Navigation soak utilities for pi_validate."""

from yoyopod_cli._pi_validate_pkg._navigation_soak.handle import (
    _NavigationSoakAppHandle,
    _YoyoPodAppNavigationSoakHandle,
    _NavigationSoakAppFactory,
    _default_app_factory,
)
from yoyopod_cli._pi_validate_pkg._navigation_soak.plan import (
    NavigationSoakError,
    NavigationSoakStep,
    NavigationSoakReport,
    build_navigation_soak_plan,
)
from yoyopod_cli._pi_validate_pkg._navigation_soak.runner import (
    NavigationSoakFailure,
    NavigationSoakStats,
    NavigationSoakRunner,
    run_navigation_soak,
)
from yoyopod_cli._pi_validate_pkg._navigation_soak.idle import (
    run_navigation_idle_soak,
)

__all__ = [
    "NavigationSoakError",
    "NavigationSoakFailure",
    "NavigationSoakRunner",
    "NavigationSoakStats",
    "run_navigation_idle_soak",
    "run_navigation_soak",
]
```

- [ ] **Step 7: Verify the subpackage imports cleanly**

Run:
```bash
uv run python -c "from yoyopod_cli._pi_validate_pkg._navigation_soak import run_navigation_soak; print(run_navigation_soak)"
```
Expected: prints the function object. No ImportError, no circular import.

- [ ] **Step 8: Run gate**

Run: `uv run python scripts/quality.py gate`
Expected: `[quality] result=passed`.

- [ ] **Step 9: Commit**

```bash
git add yoyopod_cli/_pi_validate_pkg/_navigation_soak/
git commit -m "refactor(pi_validate): build _navigation_soak subpackage"
```

### Task 5: Build small domain modules (stability, navigation, lvgl, music)

**Files:**
- Create: `yoyopod_cli/_pi_validate_pkg/stability.py`
- Create: `yoyopod_cli/_pi_validate_pkg/navigation.py`
- Create: `yoyopod_cli/_pi_validate_pkg/lvgl.py`
- Create: `yoyopod_cli/_pi_validate_pkg/music.py`
- Reference: `pi_validate.py:1249-1361, 2551-2576, 2728-2795, 2796-2875, 2876-end` (per spec §5)

- [ ] **Step 1: Create `stability.py` with the `stability()` typer command (lines 2728–2795)**

Copy the function body. Remove the `@app.command()` decorator if present — registration happens in `__init__.py` (per spec §6).

Top of file:
```python
"""Stability validation subcommand."""

from __future__ import annotations

import typer
# (other imports as the body requires — copy from pi_validate.py top-of-file)
```

If the function body references `_load_app_config` or other shared helpers, import them via `from yoyopod_cli._pi_validate_pkg._common import _load_app_config`.

- [ ] **Step 2: Create `lvgl.py` with the `lvgl()` typer command (lines 2876–end)**

Same pattern as Step 1.

- [ ] **Step 3: Create `navigation.py` with the `navigation()` typer command (lines 2796–2875)**

Same pattern. This module imports from `_navigation_soak`:
```python
from yoyopod_cli._pi_validate_pkg._navigation_soak import (
    NavigationSoakError,
    run_navigation_idle_soak,
    run_navigation_soak,
)
```

- [ ] **Step 4: Create `music.py` with `_music_check` (lines 1249–1361) and `music()` command (lines 2551–2576)**

Both helper and command land in the same file. Same pattern.

- [ ] **Step 5: Verify all four modules import cleanly**

Run:
```bash
uv run python -c "from yoyopod_cli._pi_validate_pkg import stability, navigation, lvgl, music; print('ok')"
```
Expected: `ok`. No ImportError.

- [ ] **Step 6: Run gate**

Run: `uv run python scripts/quality.py gate`
Expected: `[quality] result=passed`.

- [ ] **Step 7: Commit**

```bash
git add yoyopod_cli/_pi_validate_pkg/{stability,navigation,lvgl,music}.py
git commit -m "refactor(pi_validate): extract small domain modules"
```

### Task 6: Build deploy and system modules

**Files:**
- Create: `yoyopod_cli/_pi_validate_pkg/deploy.py`
- Create: `yoyopod_cli/_pi_validate_pkg/system.py`
- Reference: `pi_validate.py:104-246, 1019-1248, 2314-2339, 2495-2550` (per spec §5)

- [ ] **Step 1: Create `deploy.py` (helpers 104–246 + `deploy()` command 2314–2339)**

Copy verbatim. Imports as body requires; shared helpers via `from yoyopod_cli._pi_validate_pkg._common import ...`. Drop `@app.command()` decorator.

- [ ] **Step 2: Create `system.py` (helpers 1019–1248 + `smoke()` command 2495–2550)**

The `smoke()` command orchestrates multiple checks (env, display, input, power, rtc). Keep them all together in `system.py`. Drop `@app.command()` decorator on `smoke`.

- [ ] **Step 3: Verify both modules import cleanly**

Run:
```bash
uv run python -c "from yoyopod_cli._pi_validate_pkg import deploy, system; print('ok')"
```
Expected: `ok`.

- [ ] **Step 4: Run gate**

Run: `uv run python scripts/quality.py gate`
Expected: `[quality] result=passed`.

- [ ] **Step 5: Commit**

```bash
git add yoyopod_cli/_pi_validate_pkg/{deploy,system}.py
git commit -m "refactor(pi_validate): extract deploy and system modules"
```

### Task 7: Build cloud_voice module

**Files:**
- Create: `yoyopod_cli/_pi_validate_pkg/cloud_voice.py`
- Reference: `pi_validate.py:247-994, 2340-2494` (per spec §5)

- [ ] **Step 1: Create `cloud_voice.py`**

This is the largest single move (~900 LOC). Copy the helper block (lines 247–994) and the `cloud_voice()` typer command (lines 2340–2494) verbatim into the new file.

Top of file imports — derive from the original file's imports, keeping only what cloud-voice symbols actually use:
```python
"""Cloud voice validation subcommand."""

from __future__ import annotations

import os
import shutil
import subprocess
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import typer

from yoyopod.core.workers.protocol import (
    WorkerEnvelope,
    encode_envelope,
    make_envelope,
    parse_envelope_line,
)
from yoyopod.integrations.voice import VoiceSettings, match_voice_command
from yoyopod.integrations.voice.worker_contract import (
    build_speak_payload,
    build_transcribe_payload,
    parse_health_result,
    parse_speak_result,
    parse_transcribe_result,
)
from yoyopod_cli._pi_validate_pkg._common import _CheckResult, _print_summary
```

(Add or remove imports based on what the actual function bodies reference.)

Drop the `@app.command()` decorator on `cloud_voice`.

- [ ] **Step 2: Verify the module imports cleanly**

Run: `uv run python -c "from yoyopod_cli._pi_validate_pkg import cloud_voice; print('ok')"`
Expected: `ok`.

- [ ] **Step 3: Run gate**

Run: `uv run python scripts/quality.py gate`
Expected: `[quality] result=passed`.

- [ ] **Step 4: Commit**

```bash
git add yoyopod_cli/_pi_validate_pkg/cloud_voice.py
git commit -m "refactor(pi_validate): extract cloud_voice module"
```

### Task 8: Build voip module

**Files:**
- Create: `yoyopod_cli/_pi_validate_pkg/voip.py`
- Reference: `pi_validate.py:1362-2313, 2577-2727` (per spec §5)

- [ ] **Step 1: Create `voip.py`**

Largest move (~1100 LOC). Copy the helper block (1362–2313) and the `voip()` typer command (2577–2727) verbatim.

Top of file imports — derive from the original file. Notable symbols this module owns:
- `_voip_check`
- `_lazy_connected_call_states`
- `_VoIPManagerLike` (Protocol)
- `_DrillResult`
- `_VoIPDrillRecorder`
- `_build_voip_manager_for_drill`
- All the `_wait_*`, `_hold_*`, `_run_*` helpers for registration / call soak
- `_run_voip_call_soak`, `_run_voip_reconnect_drill`, `_run_voip_registration_stability`, `_run_quick_voip_check`
- `_print_drill_result`
- `voip()` command itself

Drop `@app.command()` decorator on `voip`.

Shared helpers from `_common.py` are imported as needed.

- [ ] **Step 2: Verify the module imports cleanly**

Run: `uv run python -c "from yoyopod_cli._pi_validate_pkg import voip; print('ok')"`
Expected: `ok`.

- [ ] **Step 3: Run gate**

Run: `uv run python scripts/quality.py gate`
Expected: `[quality] result=passed`.

- [ ] **Step 4: Commit**

```bash
git add yoyopod_cli/_pi_validate_pkg/voip.py
git commit -m "refactor(pi_validate): extract voip module"
```

### Task 9: Wire up `_pi_validate_pkg/__init__.py` with typer registration

**Files:**
- Modify: `yoyopod_cli/_pi_validate_pkg/__init__.py`

- [ ] **Step 1: Replace empty `__init__.py` with typer assembly**

Per spec §6:
```python
"""Pi validation suite — staged checks for deployed YoYoPod hardware."""

from __future__ import annotations

import typer

from yoyopod_cli._pi_validate_pkg import (
    deploy as _deploy,
    cloud_voice as _cloud_voice,
    system as _system,
    music as _music,
    voip as _voip,
    stability as _stability,
    navigation as _navigation,
    lvgl as _lvgl,
)

app = typer.Typer()

app.command(name="deploy")(_deploy.deploy)
app.command(name="cloud-voice")(_cloud_voice.cloud_voice)
app.command(name="smoke")(_system.smoke)
app.command(name="music")(_music.music)
app.command(name="voip")(_voip.voip)
app.command(name="stability")(_stability.stability)
app.command(name="navigation")(_navigation.navigation)
app.command(name="lvgl")(_lvgl.lvgl)

__all__ = ["app"]
```

> **Important:** Use `cloud-voice` (with hyphen) not `cloud_voice` if the original file used the hyphenated form. Check `pi_validate.py` for the original `@app.command(name=...)` argument — typer's default name policy may convert underscores to hyphens, but explicit names override this. Diff against the baseline `--help` output in Task 11 to catch any mismatch.

- [ ] **Step 2: Verify the package's `app` is constructable**

Run:
```bash
uv run python -c "from yoyopod_cli._pi_validate_pkg import app; from typer.testing import CliRunner; result = CliRunner().invoke(app, ['--help']); print(result.exit_code); print(result.stdout[:500])"
```
Expected: `0` exit code, help text listing the 8 subcommands.

- [ ] **Step 3: Diff against baseline `--help`**

Run:
```bash
uv run python -c "from yoyopod_cli._pi_validate_pkg import app; from typer.testing import CliRunner; print(CliRunner().invoke(app, ['--help'], terminal_width=200).stdout)" > .tmp/pi_validate_baseline/_root_new.txt
diff .tmp/pi_validate_baseline/_root.txt .tmp/pi_validate_baseline/_root_new.txt | head -50
```

Expected: zero diff, OR diff is only command-name format differences that you'll resolve. If the diff shows missing or wrong-named commands, fix `__init__.py` registration before proceeding.

- [ ] **Step 4: Diff each subcommand `--help`**

```bash
for sub in deploy cloud-voice smoke music voip stability navigation lvgl; do
  uv run python -c "from yoyopod_cli._pi_validate_pkg import app; from typer.testing import CliRunner; print(CliRunner().invoke(app, ['$sub', '--help'], terminal_width=200).stdout)" > ".tmp/pi_validate_baseline/${sub}_new.txt"
  diff ".tmp/pi_validate_baseline/${sub}.txt" ".tmp/pi_validate_baseline/${sub}_new.txt" > /dev/null && echo "$sub: OK" || echo "$sub: DIFFERS"
done
```

Expected: every subcommand reports `OK`. Any `DIFFERS` indicates a flag or option got dropped during the move — investigate before proceeding.

- [ ] **Step 5: Run gate**

Run: `uv run python scripts/quality.py gate`
Expected: `[quality] result=passed`.

- [ ] **Step 6: Commit**

```bash
git add yoyopod_cli/_pi_validate_pkg/__init__.py
git commit -m "refactor(pi_validate): wire typer registration in __init__"
```

---

## Phase 3: Switchover

### Task 10: Identify all `pi_validate` import and attribute-access call sites

**Files:**
- Read-only: repo-wide grep

- [ ] **Step 1: Sweep for imports**

Run:
```bash
grep -rn "from yoyopod_cli\.pi_validate" yoyopod/ yoyopod_cli/ tests/ scripts/ deploy/ 2>/dev/null
grep -rn "from yoyopod_cli import pi_validate" yoyopod/ yoyopod_cli/ tests/ scripts/ deploy/ 2>/dev/null
grep -rn "import yoyopod_cli\.pi_validate" yoyopod/ yoyopod_cli/ tests/ scripts/ deploy/ 2>/dev/null
grep -rn "from yoyopod_cli import _pi_validate_helpers\|from yoyopod_cli import pi_validate_helpers" yoyopod/ yoyopod_cli/ tests/ scripts/ deploy/ 2>/dev/null
```

Expected hits (from earlier exploration):
- `yoyopod_cli/main.py:130` — `from yoyopod_cli import pi_validate as _pi_validate`
- `tests/cli/test_pi_validate_cloud_voice.py` — `from yoyopod_cli import pi_validate`
- `tests/cli/test_pi_validate_helpers.py` — both `_pi_validate_helpers` and `pi_validate_helpers`
- `tests/cli/test_voip_cli.py` — `import yoyopod_cli.pi_validate as voip_cli`
- `tests/cli/test_yoyopod_cli_pi_validate.py` — `import yoyopod_cli.pi_validate as pi_validate`

Save this list. If new hits appear that aren't covered by Tasks 12–13, surface them and add new tasks before proceeding.

- [ ] **Step 2: Sweep for attribute-access patterns (monkeypatching, helper access)**

Run:
```bash
grep -rn "pi_validate\._\|pi_validate\.shutil\|pi_validate\.os\|pi_validate\.subprocess\|pi_validate\.VoiceSettings\|pi_validate\.app" tests/ 2>/dev/null | head -50
```

Expected: dozens of hits in the four test files, each accessing a private symbol or a re-imported module by attribute. These are the ~30–60 call sites the spec mentions.

(No commit for this task. The grep output is reference material for Tasks 12–13.)

### Task 11: Atomic switchover — delete old, rename new, update main.py

**Files:**
- Delete: `yoyopod_cli/pi_validate.py`
- Delete: `yoyopod_cli/_pi_validate_helpers.py`
- Delete: `yoyopod_cli/pi_validate_helpers.py`
- Rename: `yoyopod_cli/_pi_validate_pkg/` → `yoyopod_cli/pi_validate/`
- Modify: every internal import inside the renamed package (s/_pi_validate_pkg/pi_validate/g)
- Verify: `yoyopod_cli/main.py` still works (its existing `from yoyopod_cli import pi_validate as _pi_validate` resolves to the new package — no edit needed)

> **This is the dangerous commit.** The diff is large (~4300 LOC of deletions + ~4300 LOC of renames). Take it carefully. Each step is reversible up to Step 5 (the actual delete + rename).

- [ ] **Step 1: Delete the three old files**

Run:
```bash
git rm yoyopod_cli/pi_validate.py yoyopod_cli/_pi_validate_helpers.py yoyopod_cli/pi_validate_helpers.py
```

After this, attempting to import `yoyopod_cli.pi_validate` will fail because the package isn't named that yet. Don't run tests — they'll all fail.

- [ ] **Step 2: Rename `_pi_validate_pkg/` → `pi_validate/`**

Run:
```bash
git mv yoyopod_cli/_pi_validate_pkg yoyopod_cli/pi_validate
```

- [ ] **Step 3: Update internal imports inside the renamed package**

The new package's modules reference themselves as `yoyopod_cli._pi_validate_pkg.*` — change to `yoyopod_cli.pi_validate.*`.

Run a sed-style replacement (verify the diff before committing):
```bash
# On Linux/macOS:
find yoyopod_cli/pi_validate -name "*.py" -exec sed -i 's|yoyopod_cli\._pi_validate_pkg|yoyopod_cli.pi_validate|g' {} \;

# On Windows (Git Bash):
find yoyopod_cli/pi_validate -name "*.py" -exec sed -i 's|yoyopod_cli\._pi_validate_pkg|yoyopod_cli.pi_validate|g' {} \;
```

Or do it via the `Edit` tool per file, replacing `yoyopod_cli._pi_validate_pkg` with `yoyopod_cli.pi_validate`.

- [ ] **Step 4: Verify no leftover references to the temp name**

Run: `grep -rn "_pi_validate_pkg" yoyopod_cli/ tests/`
Expected: zero hits.

- [ ] **Step 5: Verify the package is importable**

Run: `uv run python -c "from yoyopod_cli.pi_validate import app; print(app)"`
Expected: prints typer app object. No ImportError.

- [ ] **Step 6: Verify `yoyopod_cli/main.py` still works**

Run: `uv run python -c "from yoyopod_cli import main; print('ok')"`
Expected: `ok`. The existing `from yoyopod_cli import pi_validate as _pi_validate` in `main.py` now resolves to the package, not the file.

- [ ] **Step 7: Diff CLI surface against baseline**

Re-capture using the same programmatic approach as Task 1 step 1 (so terminal-width is consistent):

```bash
uv run python - <<'PY'
from pathlib import Path
from typer.testing import CliRunner
from yoyopod_cli import pi_validate

runner = CliRunner()
out = Path(".tmp/pi_validate_baseline")
(out / "_root_after.txt").write_text(runner.invoke(pi_validate.app, ["--help"], terminal_width=200).stdout)
for sub in ["deploy", "cloud-voice", "smoke", "music", "voip", "stability", "navigation", "lvgl"]:
    (out / f"{sub.replace('-', '_')}_after.txt").write_text(
        runner.invoke(pi_validate.app, [sub, "--help"], terminal_width=200).stdout
    )
print("after captured")
PY

diff .tmp/pi_validate_baseline/_root.txt .tmp/pi_validate_baseline/_root_after.txt
for sub in deploy cloud_voice smoke music voip stability navigation lvgl; do
  diff ".tmp/pi_validate_baseline/${sub}.txt" ".tmp/pi_validate_baseline/${sub}_after.txt" > /dev/null && echo "$sub: OK" || echo "$sub: DIFFERS"
done
```

Expected: zero diff on root; every subcommand reports `OK`. Any `DIFFERS` indicates a flag, option, or help-text change introduced during the move — investigate before proceeding.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "refactor(pi_validate): switch to subpackage; delete old flat files"
```

### Task 12: Update `tests/cli/test_pi_validate_helpers.py`

**Files:**
- Modify: `tests/cli/test_pi_validate_helpers.py`

- [ ] **Step 1: Replace the two old imports with one new import**

The current top of file (per Task 10 grep):
```python
from yoyopod_cli import _pi_validate_helpers as helpers
from yoyopod_cli import pi_validate_helpers as public_helpers
```

Replace with:
```python
from yoyopod_cli.pi_validate import _navigation_soak as helpers
# `public_helpers` is gone — the shim is deleted. Update any uses of
# `public_helpers.X` in the test body to `helpers.X` (the symbol surface
# is identical).
```

- [ ] **Step 2: Update `public_helpers.*` references in the test body**

Use `Grep` to find every `public_helpers.` in the file, replace with `helpers.`. Verify no other behavior is touched.

- [ ] **Step 3: Update `helpers.*` references for symbols that moved into submodules**

`helpers` now points at `_navigation_soak/__init__.py` which re-exports the public surface. Most existing `helpers.NavigationSoakError`, `helpers.run_navigation_soak`, etc. continue to work because of the re-exports.

For private symbols (those not re-exported in `_navigation_soak/__init__.py`), update the access path to point at the specific submodule:
- `helpers._RuntimePump` → `from yoyopod_cli.pi_validate._navigation_soak import runner; runner._RuntimePump`
- `helpers._pump_app` → `from yoyopod_cli.pi_validate._navigation_soak import pump; pump._pump_app`
- (etc.)

For each private-symbol access, identify which submodule (handle/plan/pump/idle/runner) owns it (per Task 4 line ranges) and import from there.

- [ ] **Step 4: Run only this test file**

Run: `uv run pytest -q tests/cli/test_pi_validate_helpers.py -v`
Expected: PASS. If it fails on `AttributeError: module has no attribute X`, the symbol's home submodule is wrong — re-check Task 4 mapping.

- [ ] **Step 5: Commit**

```bash
git add tests/cli/test_pi_validate_helpers.py
git commit -m "test(pi_validate): migrate helpers test to new submodule paths"
```

### Task 13: Update `tests/cli/test_pi_validate_cloud_voice.py`

**Files:**
- Modify: `tests/cli/test_pi_validate_cloud_voice.py`

- [ ] **Step 1: Replace the import**

Current:
```python
from yoyopod_cli import pi_validate
```

Replace with:
```python
from yoyopod_cli.pi_validate import cloud_voice as pi_validate_cv
```

(Use `pi_validate_cv` as the alias to make the test body's intent explicit and avoid name-clash with the package.)

- [ ] **Step 2: Sweep `pi_validate.<symbol>` → `pi_validate_cv.<symbol>` in the test body**

For each grep hit in this file (from Task 10), update:
- `pi_validate._load_cloud_voice_env_file` → `pi_validate_cv._load_cloud_voice_env_file`
- `pi_validate._cloud_voice_settings_check` → `pi_validate_cv._cloud_voice_settings_check`
- `pi_validate._cloud_voice_command_match_check` → `pi_validate_cv._cloud_voice_command_match_check`
- `pi_validate._resolve_cloud_voice_worker_argv` → `pi_validate_cv._resolve_cloud_voice_worker_argv`
- `pi_validate._cloud_voice_worker_binary_check` → `pi_validate_cv._cloud_voice_worker_binary_check`
- `pi_validate._VoiceWorkerProtocolClient` → `pi_validate_cv._VoiceWorkerProtocolClient`
- `pi_validate._cloud_voice_acoustic_loopback_check` → `pi_validate_cv._cloud_voice_acoustic_loopback_check`
- `pi_validate.VoiceSettings` → `pi_validate_cv.VoiceSettings`
- `pi_validate.shutil` → `pi_validate_cv.shutil` (monkeypatch target)
- `pi_validate.subprocess` → `pi_validate_cv.subprocess` (monkeypatch target)
- `pi_validate.os` → `pi_validate_cv.os` (monkeypatch target)
- `pi_validate.app` → `pi_validate_cv.app` will NOT work — `app` lives in `pi_validate/__init__.py`, not in `cloud_voice.py`.

For the `pi_validate.app` references, add a separate import:
```python
from yoyopod_cli.pi_validate import app as pi_validate_app
```
And replace `pi_validate.app` → `pi_validate_app` in the test body.

- [ ] **Step 3: Run only this test file**

Run: `uv run pytest -q tests/cli/test_pi_validate_cloud_voice.py -v`
Expected: PASS. Investigate any `AttributeError` immediately — most likely the symbol moved to a different module than expected.

- [ ] **Step 4: Commit**

```bash
git add tests/cli/test_pi_validate_cloud_voice.py
git commit -m "test(pi_validate): migrate cloud_voice test to submodule paths"
```

### Task 14: Update `tests/cli/test_voip_cli.py`

**Files:**
- Modify: `tests/cli/test_voip_cli.py`

- [ ] **Step 1: Replace the import**

Current:
```python
import yoyopod_cli.pi_validate as voip_cli
```

Replace with:
```python
from yoyopod_cli.pi_validate import voip as voip_cli
```

- [ ] **Step 2: Verify body uses are still valid**

The alias name `voip_cli` is preserved. Symbols accessed as `voip_cli.<X>` should resolve to symbols in `pi_validate/voip.py`. If the test references the typer `app`, add `from yoyopod_cli.pi_validate import app as pi_validate_app` and replace those references.

- [ ] **Step 3: Run only this test file**

Run: `uv run pytest -q tests/cli/test_voip_cli.py -v`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/cli/test_voip_cli.py
git commit -m "test(pi_validate): migrate voip_cli test to submodule paths"
```

### Task 15: Update `tests/cli/test_yoyopod_cli_pi_validate.py`

**Files:**
- Modify: `tests/cli/test_yoyopod_cli_pi_validate.py`

- [ ] **Step 1: Update imports**

Current:
```python
import yoyopod_cli.pi_validate as pi_validate
app = pi_validate.app
```

Update to:
```python
from yoyopod_cli import pi_validate
from yoyopod_cli.pi_validate import app
```

(`pi_validate` is now a package; `pi_validate.app` still works because the package `__init__.py` exposes `app`. Both forms are equivalent — pick the one that minimizes downstream test-body edits.)

- [ ] **Step 2: For helper accesses, route through the right submodule**

Any `pi_validate.<helper>` access where the helper isn't `app` needs to be re-routed to its submodule (e.g., `pi_validate.deploy._something`, `pi_validate.system._environment_check`). Use the spec §5 mapping or grep `pi_validate.py` (from git history) for the symbol's original location.

- [ ] **Step 3: Run only this test file**

Run: `uv run pytest -q tests/cli/test_yoyopod_cli_pi_validate.py -v`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/cli/test_yoyopod_cli_pi_validate.py
git commit -m "test(pi_validate): migrate top-level CLI test to submodule paths"
```

---

## Phase 4: Final verification + PR

### Task 16: Full verification sweep

**Files:** none modified — verification only.

- [ ] **Step 1: Quality gate**

Run: `uv run python scripts/quality.py gate`
Expected: `[quality] result=passed`.

- [ ] **Step 2: Full CLI test suite**

Run: `uv run pytest -q tests/cli/`
Expected: PASS.

- [ ] **Step 3: Full project test suite**

Run: `uv run pytest -q`
Expected: PASS (mod known Windows-specific failures per `CLAUDE.md` — diff against latest green main CI if on Windows).

- [ ] **Step 4: Final import sweep**

Run:
```bash
grep -rn "yoyopod_cli\._pi_validate_pkg\|yoyopod_cli\._pi_validate_helpers\|yoyopod_cli\.pi_validate_helpers" yoyopod/ yoyopod_cli/ tests/ scripts/ deploy/
```

Expected: zero hits. All references to the old paths and the temp name are gone.

- [ ] **Step 5: Verify old files are deleted**

Run:
```bash
ls yoyopod_cli/pi_validate.py yoyopod_cli/_pi_validate_helpers.py yoyopod_cli/pi_validate_helpers.py 2>&1
```

Expected: all three report "No such file or directory."

- [ ] **Step 6: CLI surface diff (final, end-to-end)**

```bash
for sub in deploy cloud-voice smoke music voip stability navigation lvgl; do
  uv run yoyopod pi validate "$sub" --help > ".tmp/pi_validate_baseline/${sub}_final.txt" 2>&1 || true
  diff ".tmp/pi_validate_baseline/${sub}.txt" ".tmp/pi_validate_baseline/${sub}_final.txt" > /dev/null && echo "$sub: OK" || echo "$sub: DIFFERS"
done
```

Expected: all `OK`.

(No commit — this is a verification gate.)

### Task 17: Push and open PR

**Files:** none.

- [ ] **Step 1: Push the branch**

Run:
```bash
git push -u origin refactor/pi-validate-split
```

Expected: branch pushed to remote. Note the remote URL — the upstream may have moved (the YoYoPod repo migrated from `moustafattia/yoyopod-core` to `attmous/yoyocore`); pass `--repo attmous/yoyocore` to `gh pr create` if so.

- [ ] **Step 2: Open the PR**

Run:
```bash
gh pr create --repo attmous/yoyocore --head attmous:refactor/pi-validate-split \
  --title "refactor(pi_validate): split into per-domain subpackage" \
  --body "$(cat <<'EOF'
## Summary
- Splits `yoyopod_cli/pi_validate.py` (2940 LOC) + `_pi_validate_helpers.py` (1350 LOC) + `pi_validate_helpers.py` (shim) into a `yoyopod_cli/pi_validate/` subpackage with 8 domain modules + a `_navigation_soak/` sub-subpackage with 5 focused modules.
- Pure mechanical refactor: no logic changes, no behavior changes, no CLI surface changes.
- Drops the public re-export shim. Tests updated to use submodule attribute paths.

## Spec
See [docs/superpowers/specs/2026-04-27-pi-validate-split-design.md](docs/superpowers/specs/2026-04-27-pi-validate-split-design.md).

## Test plan
- [x] Quality gate passes locally (`uv run python scripts/quality.py gate`)
- [x] Full pytest passes locally (`uv run pytest -q`)
- [x] CLI `--help` output for all 8 subcommands diffs to zero against pre-split baseline
- [x] Final import sweep shows no references to old paths
- [ ] Smoke run on Pi (`yoyopod pi validate smoke`) — to be done by reviewer or in CI

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

Expected: PR URL printed.

- [ ] **Step 3: Drop temp baseline files**

```bash
rm -rf .tmp/pi_validate_baseline
```

(No commit — these are scratch.)

---

## Risks and rollback

- **If Task 11 (the switchover) leaves the codebase broken** and the issue isn't fixable in <30 min: `git revert HEAD` cleanly returns to the state where `_pi_validate_pkg/` and the old files coexist.
- **If a test in Tasks 12–15 reveals a missed symbol move**: identify which submodule the symbol should live in (per spec §5), edit the relevant `pi_validate/<module>.py` to add the missing symbol, re-run the test, then commit as a fix-up.
- **If the CLI surface diff in Task 11 step 7 is non-zero**: either a command name changed (check `app.command(name=...)` arguments in `__init__.py`), a flag was dropped during the move, or the help text formatting changed. The first two are bugs; the third is acceptable if it's purely whitespace.
- **If during Tasks 5–8 you discover a helper that's used by 2+ domain modules** (e.g., `voip.py` and `cloud_voice.py` both call the same private helper): per spec §8, promote it to `_common.py` rather than have one domain module import sideways from another. If unsure, default to `_common.py`. Sideways imports between domain modules invite circular-import pain.
- **If the typer command-name decorator on the original used underscores not hyphens** (e.g., `cloud_voice` not `cloud-voice`): every place this plan writes `cloud-voice` must switch to `cloud_voice`. Do this once globally before starting Phase 2.
