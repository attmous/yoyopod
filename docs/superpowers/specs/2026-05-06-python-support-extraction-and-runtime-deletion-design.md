# Python Support Extraction And Runtime Deletion Design

**Date:** 2026-05-06
**Owner:** Moustafa
**Status:** Draft for review
**Target hardware:** Raspberry Pi Zero 2W, Whisplay dev/prod lanes

---

## 1. Problem

The first cleanup pass made the Rust `device/` workspace the supported runtime
owner and quarantined the old Python runtime entrypoints. It did not fully
delete the Python runtime package because active CLI and Pi-validation code
still imports pieces from `yoyopod/`.

That leaves the repo in an intermediate state:

- `device/runtime/` owns the app process.
- `yoyopod_cli/` owns operations tooling.
- `yoyopod/` still contains a mix of old runtime code and Python support
  modules used by active CLI validation.
- `pyproject.toml` still packages `yoyopod`, so retired runtime code can leak
  into installed artifacts.
- Default active tests still cover Python config/support modules because some
  CLI flows depend on them.

The next cleanup must separate useful Python operations support from the retired
Python app runtime, then remove the old runtime package from active packaging
and tests.

---

## 2. Goals

- Remove active `yoyopod_cli/` imports from `yoyopod.*`.
- Remove active tests outside `tests/legacy_python_runtime/` that import
  runtime-only `yoyopod.*` modules.
- Move CLI-needed Python support into `yoyopod_cli/` under explicit operations
  namespaces.
- Keep `yoyopod_cli` as Python for build, deploy, release, and Pi validation.
- Keep Rust `device/` as the only app runtime owner.
- Delete or quarantine the old Python app runtime package after extraction.
- Stop packaging `yoyopod/` as active wheel or sdist content.
- Preserve supported CLI behavior and Pi validation behavior unless a validation
  path is proven to depend only on retired Python runtime behavior.

---

## 3. Non-goals

- Do not port the Python CLI itself to Rust.
- Do not change Rust runtime or sidecar process architecture.
- Do not change the NDJSON worker protocol.
- Do not rewrite device domain behavior in this cleanup.
- Do not add web or mobile app code.
- Do not keep compatibility imports from `yoyopod.*` in active CLI modules.
- Do not preserve Python runtime tests simply to keep old coverage numbers high.

---

## 4. Current Remaining Couplings

Active scans show the following `yoyopod/` dependencies still matter.

### Config Support

Current active config tests import:

- `yoyopod.config`
- `yoyopod.config.manager`
- `yoyopod.config.models`
- `yoyopod.config.composition`

These are candidates for `yoyopod_cli.config` or
`yoyopod_cli.contracts.config`.

### Worker Protocol Support

Current CLI/Pi validation imports:

- `yoyopod.core.workers.protocol`

This is a candidate for `yoyopod_cli.contracts.worker_protocol`, unless it can
be replaced by direct JSON envelope helpers local to the validation command.

### Pi Validation Support

Current validation code imports runtime-facing modules:

- `yoyopod.ui.input`
- `yoyopod.ui.display`
- `yoyopod.ui.lvgl_binding`
- `yoyopod.integrations.power`
- `yoyopod.integrations.call`
- `yoyopod.integrations.music`
- `yoyopod.integrations.voice`
- `yoyopod.backends.music`
- `yoyopod.backends.voice`
- `yoyopod.backends.cloud`
- `yoyopod.backends.voip`

Each import must be classified as one of:

- true operations support that moves into `yoyopod_cli/pi/`
- simple contract/model code that moves into `yoyopod_cli/contracts/`
- retired Python runtime validation that is deleted or moved to legacy

### Runtime App Coupling

The navigation soak helpers still import:

- `yoyopod.app.YoyoPodApp`
- `yoyopod.core.events.UserActivityEvent`

This is not compatible with a Rust-only runtime. The soak command must either
be rewritten to drive the Rust runtime/worker protocol or moved out of active
validation.

### Packaging Coupling

`pyproject.toml` still includes:

```toml
[tool.hatch.build.targets.wheel]
packages = ["yoyopod", "yoyopod_cli"]
```

and sdist entries for `yoyopod`. After extraction, only `yoyopod_cli` should be
packaged as Python application code.

---

## 5. Target Layout

```text
yoyopod_cli/
  contracts/
    release.py
    setup.py
    worker_protocol.py
    config.py              # if shared config contracts remain needed
    voice.py               # if voice dictionary/trace contracts remain needed

  config/
    manager.py             # only if CLI needs mutable config operations
    models.py              # only active operations models

  pi/
    validate/
      # validation commands that do not import the retired runtime package
    support/
      audio.py
      display.py
      input.py
      power.py
      voip.py
      voice.py

device/
  # unchanged Rust runtime and sidecar workspace

legacy/
  python-runtime/
    yoyopod.py             # temporary, then deleted
    yoyopod/               # temporary, then deleted if quarantine is chosen

tests/
  cli/
  config/
  deploy/
  device/
  scripts/
  legacy_python_runtime/   # temporary, excluded from default pytest
```

The final preferred state has no active `yoyopod/` package. If a temporary
legacy quarantine is needed, it must live under `legacy/python-runtime/` and
must not be packaged.

---

## 6. Extraction Rules

- Move behavior only when active CLI or Pi validation still needs it.
- Prefer small contract modules over moving whole runtime subsystems.
- Keep moved Python modules importable from `yoyopod_cli.*`, not re-exported
  through `yoyopod.*`.
- Do not add compatibility shims from `yoyopod/` back into `yoyopod_cli/`.
- Delete validation commands that only instantiate the retired Python app.
- When a Python validation command should survive, make it validate an external
  process, config file, hardware surface, or Rust worker protocol.
- Keep tests close to the surviving owner:
  - CLI behavior under `tests/cli/`
  - config contracts under `tests/config/`
  - deploy/slot behavior under `tests/deploy/`
  - Rust device behavior under `tests/device/` or `device/*/tests`

---

## 7. Proposed Phases

### Phase 1: Inventory And Guardrails

- Add tests/scans that fail on new active `from yoyopod` imports.
- Add packaging tests that assert `yoyopod` is not shipped once the extraction
  is complete.
- Classify every active `yoyopod.*` import as keep/move/delete.

### Phase 2: Extract Shared Contracts

- Move worker envelope helpers from `yoyopod.core.workers.protocol` into
  `yoyopod_cli.contracts.worker_protocol`.
- Move config model/loader contracts needed by CLI into `yoyopod_cli.config`
  or `yoyopod_cli.contracts.config`.
- Move voice dictionary and trace helpers needed by the CLI into
  `yoyopod_cli.contracts.voice` or `yoyopod_cli.voice_support`.

### Phase 3: Replace Pi Validation Runtime Imports

- Replace power, voice, VoIP, music, display, and input imports with
  `yoyopod_cli.pi.support.*` modules or Rust-worker/protocol checks.
- Remove `YoyoPodApp` construction from active navigation soak validation.
- Keep only validations that still make sense for the Rust runtime.

### Phase 4: Prune Active Tests

- Update tests to import from `yoyopod_cli.*`.
- Move retired runtime-only tests to `tests/legacy_python_runtime/` or delete
  them.
- Keep active tests focused on current CLI/deploy/config/device behavior.

### Phase 5: Remove Runtime Package From Packaging

- Update `pyproject.toml` wheel package list to `["yoyopod_cli"]`.
- Remove `yoyopod` and old root runtime paths from sdist includes.
- Confirm installed CLI still works.

### Phase 6: Delete Or Final-Quarantine Legacy Runtime

- If no parity inspection is still needed, delete:
  - `yoyopod/`
  - `legacy/python-runtime/`
  - `tests/legacy_python_runtime/`
- If temporary quarantine is chosen, move `yoyopod/` under
  `legacy/python-runtime/yoyopod/` and exclude it from packaging and active
  tests.

---

## 8. Acceptance Criteria

- `rg -n "from yoyopod\\.|import yoyopod|yoyopod\\." yoyopod_cli tests/cli tests/config tests/deploy tests/device tests/scripts -g "*.py"` has no active dependency output.
- `uv run yoyopod` still prints the operations CLI help.
- `uv run python scripts/quality.py gate` passes.
- `uv run pytest -q tests/cli tests/deploy tests/config tests/device tests/scripts` passes.
- `cargo test --manifest-path device/Cargo.toml --workspace --locked` passes.
- `cargo clippy --manifest-path device/Cargo.toml --workspace --all-targets --locked -- -D warnings` passes.
- `cargo fmt --manifest-path device/Cargo.toml --all --check` passes.
- Wheel metadata packages only `yoyopod_cli`.
- Active sdist includes do not include `yoyopod/` or old runtime entrypoints.
- No active docs describe Python as the app runtime owner.
- Rust dev and prod launch paths still resolve runtime and worker binaries.

---

## 9. Risks And Mitigations

- **Risk:** Pi validation loses useful hardware checks.
  **Mitigation:** Replace runtime-object validation with config, process,
  worker-protocol, or hardware-surface checks before deleting commands.

- **Risk:** Moving config models breaks release or remote validation.
  **Mitigation:** Move config support in small slices and keep focused tests for
  each CLI command that consumes it.

- **Risk:** The Python package deletion removes native LVGL helper paths still
  needed by deployment.
  **Mitigation:** Classify LVGL helper code separately. If native build helpers
  are still needed by CLI, move them under `yoyopod_cli.pi.support.display` or
  a dedicated native-build support module before deleting `yoyopod/`.

- **Risk:** Tests become easier but less meaningful.
  **Mitigation:** Keep tests only when they protect active behavior; replace
  deleted runtime tests with Rust runtime, worker, CLI, or deploy tests where
  the behavior remains product-critical.

---

## 10. Open Decisions

- Should legacy Python runtime code be deleted immediately after extraction, or
  kept for one additional PR under `legacy/python-runtime/yoyopod/`?
- Should navigation soak be rewritten against Rust runtime events now, or
  removed from active validation until hardware-driven soak exists?
- Should config support live under `yoyopod_cli.config` or remain contract-only
  under `yoyopod_cli.contracts.config`?
- Should Python voice trace tooling remain in the CLI, or should long-term
  trace analysis move to a separate package under `packages/` later?
