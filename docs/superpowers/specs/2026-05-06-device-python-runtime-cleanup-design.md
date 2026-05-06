# Device Workspace And Python Runtime Cleanup Design

**Date:** 2026-05-06
**Owner:** Moustafa
**Status:** Draft for review
**Target hardware:** Raspberry Pi Zero 2W, Whisplay dev/prod lanes

---

## 1. Problem

YoYoPod has crossed the architectural line from Python runtime to Rust runtime.
The Rust workspace now owns runtime orchestration and device domain sidecars,
but the repository still carries old names and old Python runtime structure:

- The Rust on-device workspace is still named `yoyopod_rs/`, which describes
  the language instead of the product boundary.
- The Python package `yoyopod/` mixes useful CLI/deploy contracts with the old
  Python app runtime.
- The Python CLI still has compatibility paths that can launch or validate
  `python yoyopod.py`.
- The test tree mixes production-relevant CLI/deploy/config coverage with old
  Python runtime parity tests.
- Future app and package roots now exist, but the repo still needs a clean
  final boundary between device runtime, operations tooling, apps, packages,
  and legacy code.

The cleanup should remove ambiguity while keeping the working deploy path
stable. The Python CLI survives as the operations layer. The Python app runtime
does not remain a supported runtime owner.

---

## 2. Goals

- Rename `yoyopod_rs/` to `device/`.
- Keep the Rust runtime and Rust sidecar architecture unchanged.
- Keep deployed binary names unchanged:
  - `yoyopod-runtime`
  - `yoyopod-cloud-host`
  - `yoyopod-media-host`
  - `yoyopod-network-host`
  - `yoyopod-power-host`
  - `yoyopod-speech-host`
  - `yoyopod-ui-host`
  - `yoyopod-voip-host`
- Preserve `yoyopod_cli/` as the Python build/deploy/remote validation tool.
- Extract CLI-needed contracts from `yoyopod/` before deleting old runtime code.
- Remove supported paths that launch `python yoyopod.py`.
- Separate production-relevant tests from legacy Python runtime tests.
- Keep tests that protect CLI, deploy, slot, config, CI, and device runtime
  contracts.
- Delete or archive tests that only protect the retired Python app runtime.
- Leave the repo in a shape where future web/mobile work can live under
  `apps/` and shared packages can live under `packages/`.

---

## 3. Non-goals

- Do not merge Rust sidecar workers into the Rust runtime process.
- Do not change the NDJSON-over-stdio worker protocol.
- Do not rewrite feature behavior during this cleanup.
- Do not port the Python CLI to Rust.
- Do not introduce web or mobile application code in this migration.
- Do not preserve old Python runtime tests for their own sake.
- Do not keep `yoyopod/` as a permanent compatibility package unless a specific
  production CLI/deploy contract still requires it.
- Do not rename deployed systemd service names unless a later service cleanup
  spec explicitly covers it.

---

## 4. Target Repository Layout

Final intended repo shape:

```text
device/
  Cargo.toml
  Cargo.lock

  runtime/      # Rust orchestrator binary
  protocol/     # shared NDJSON envelope/schema crate
  worker/       # shared stdin/stdout worker helpers
  harness/      # device worker protocol test helpers

  cloud/        # cloud sidecar host
  media/        # media/mpv sidecar host
  network/      # modem/PPP/GPS sidecar host
  power/        # battery/RTC/watchdog sidecar host
  speech/       # Ask/STT/TTS sidecar host
  ui/           # Whisplay/LVGL sidecar host
  voip/         # Liblinphone/SIP sidecar host

yoyopod_cli/
  # Python operations CLI: build, deploy, release, remote validation, health

deploy/
  # systemd, installer, slot, Docker, and release packaging scripts

config/
  # authored runtime config inputs

tests/
  cli/
  deploy/
  config/
  device/
  scripts/

apps/
  # future web/mobile applications

packages/
  # future contracts, SDKs, shared app packages

legacy/
  python-runtime/   # temporary only, deleted after extraction confidence
```

`device/` is the on-device Rust workspace. It is allowed to contain Rust, C
bindings, generated native glue, and device-specific assets needed by the
runtime. It is not a home for the Python CLI, web apps, mobile apps, or shared
SDK packages.

---

## 5. Runtime Ownership Rules

- `device/runtime/` owns runtime process orchestration.
- `device/{cloud,media,network,power,speech,ui,voip}/` own domain sidecar
  workers.
- Rust sidecars communicate with `device/runtime/` through NDJSON over
  stdin/stdout.
- `yoyopod_cli/` owns developer and device operations:
  - local build commands
  - artifact packaging
  - slot release creation
  - remote sync/release flows
  - Pi validation commands
  - health/status commands
- `deploy/` owns systemd, installer, Docker, slot launch, and release scripts.
- `config/` owns authored runtime configuration inputs.
- `apps/` must not be imported by `device/`.
- `packages/` may hold shared contracts later, but app packages must not become
  runtime dependencies.

---

## 6. Python Package Strategy

The `yoyopod/` package must be dismantled deliberately.

### Keep or move into `yoyopod_cli/`

These Python surfaces may still be production-relevant and should be moved
before deleting `yoyopod/`:

- version metadata needed by CLI release commands
- setup contract constants used by health/install tests
- release manifest/current release helpers used by CLI health
- config models used by CLI validation or slot generation
- validation helpers used by `yoyopod remote validate`
- navigation-soak helpers only if they remain part of supported hardware
  validation

Preferred destinations:

```text
yoyopod_cli/contracts/
yoyopod_cli/config/
yoyopod_cli/health/
yoyopod_cli/pi/validate/
```

### Remove or move to `legacy/python-runtime/`

These are old runtime surfaces and should not stay in the active root:

- `yoyopod/app.py`
- `yoyopod/main.py`
- Python app lifecycle/runtime loop
- Python event bus/runtime state
- Python music/VoIP/power/network/cloud runtime managers already owned by Rust
- Python UI screen runtime
- Python worker supervisor/runtime compatibility code
- `yoyopod.py` as a supported app launch path

If immediate deletion is too risky, move the old runtime to:

```text
legacy/python-runtime/yoyopod/
legacy/python-runtime/yoyopod.py
```

The legacy directory must be treated as temporary. It should not be imported by
new code.

---

## 7. Test Strategy

Tests are not all equally valuable after the Rust migration. The cleanup should
keep tests that protect production operations and delete tests that only keep
the old Python runtime alive.

### Keep

```text
tests/cli/
tests/deploy/
tests/config/
tests/device/
tests/scripts/
```

Keep tests that protect:

- CLI command behavior
- build commands
- slot contract paths
- release artifact packaging
- CI workflow path assumptions
- config model loading used by Rust runtime or CLI
- device workspace structure
- Rust worker protocol and artifact names
- remote validation command construction

### Rename

Rust workspace tests should use product-boundary naming:

```text
tests/cli/test_rust_workspace_structure.py -> tests/device/test_workspace_structure.py
```

Use `device` instead of `rust_workspace` because the folder describes the
on-device product boundary, not just the implementation language.

### Delete or archive

Move to `tests/legacy_python_runtime/` first only if a final parity review is
needed. Otherwise delete directly.

Candidates:

- Python app orchestration tests
- Python backend domain tests for music, VoIP, power, network, cloud
- Python UI/screen tests
- Python app lifecycle/runtime loop tests
- Python worker supervisor tests for the old runtime
- tests that assert `python yoyopod.py` behavior
- old Python voice runtime tests once `device/speech/` owns the behavior

### Required test cleanup rule

No test should remain only because it is old. A surviving test must protect one
of these active contracts:

- Python CLI behavior
- deploy/release behavior
- config behavior consumed by CLI or Rust runtime
- Rust device runtime behavior
- hardware validation command behavior
- CI/package path behavior

---

## 8. Path Migration Requirements

All active references must move from `yoyopod_rs/` to `device/`.

Update:

- `device/Cargo.toml`
- all Rust crate path dependencies
- all Bazel BUILD labels and source paths
- `.github/workflows/ci.yml`
- `.dockerignore`
- `deploy/docker/slot-builder.Dockerfile`
- `scripts/build_release.py`
- `scripts/build_slot_artifact_ci.sh`
- `yoyopod_cli/build.py`
- `yoyopod_cli/slot_contract.py`
- `yoyopod_cli/remote_release.py`
- `yoyopod_cli/remote_validate.py`
- config defaults
- docs and rules that describe active architecture
- active tests

Expected artifact paths after migration:

```text
device/runtime/build/yoyopod-runtime
device/cloud/build/yoyopod-cloud-host
device/media/build/yoyopod-media-host
device/network/build/yoyopod-network-host
device/power/build/yoyopod-power-host
device/speech/build/yoyopod-speech-host
device/ui/build/yoyopod-ui-host
device/voip/build/yoyopod-voip-host
```

Historical docs may mention `yoyopod_rs/` only if they clearly describe past
work and live under historical/archive paths.

---

## 9. CLI Runtime Requirements

The Python CLI must support the Rust runtime without the Python app runtime.

Required behavior:

- `uv run yoyopod build rust-runtime` builds `device/runtime/build/yoyopod-runtime`.
- `uv run yoyopod build voice-worker` builds
  `device/speech/build/yoyopod-speech-host`.
- release packaging includes all required `device/*/build/yoyopod-*-host`
  artifacts.
- hydrated slot validation checks the same artifact set.
- dev/prod lane commands do not require `python yoyopod.py`.
- health/status commands can run without importing old Python runtime modules.
- `YOYOPOD_DEV_RUNTIME=rust` remains the supported dev runtime owner while any
  transition toggle exists.

Unsupported after cleanup:

```text
python yoyopod.py
python yoyopod.py --simulate
unmanaged Python app runtime service ownership
```

Simulation or browser preview must either be Rust/device-owned or explicitly
documented as a separate development tool.

---

## 10. Deletion Gates

Before deleting `yoyopod/`, all of these scans must be clean or intentionally
point only to `legacy/python-runtime/`:

```bash
rg -n "from yoyopod\\.|import yoyopod|yoyopod\\." yoyopod_cli deploy scripts tests -g "*.py"
rg -n "python yoyopod.py|yoyopod.py --simulate|YOYOPOD_DEV_RUNTIME=python" .
rg -n "yoyopod_rs/" . -g "!docs/archive/**" -g "!docs/history/**" -g "!docs/superpowers/**"
```

Allowed surviving Python imports:

- `yoyopod_cli.*`
- standard library modules
- third-party dependencies declared in `pyproject.toml`

If `packages/contracts/` exists by the time cleanup runs, generated contracts
may be imported by `yoyopod_cli/`, but not by old `yoyopod/` runtime code.

---

## 11. Validation

Required local validation after the full cleanup:

```bash
cargo test --manifest-path device/Cargo.toml --workspace --locked
cargo clippy --manifest-path device/Cargo.toml --workspace --all-targets --locked -- -D warnings
cargo fmt --manifest-path device/Cargo.toml --all --check
uv run python scripts/quality.py gate
uv run pytest -q tests/cli tests/deploy tests/config tests/device tests/scripts
uv run yoyopod build rust-runtime
uv run yoyopod build voice-worker
git diff --check
git ls-files -ci --exclude-standard
```

Required CI validation:

- `quality`
- `test`
- `rust-device-arm64`
- slot/release artifact job when applicable

Required hardware validation before merging the final deletion phase:

```bash
yoyopod remote validate --branch <branch> --sha <commit>
```

Expected hardware result:

- Rust runtime starts.
- Domain sidecar binaries spawn from `device/*/build/`.
- UI, power, media, network, cloud, VoIP, and speech worker health checks report
  expected status for available hardware.
- No Python app runtime process owns device hardware.

---

## 12. Migration Phases

### Phase 1: Rename Rust workspace to `device/`

- Move `yoyopod_rs/` to `device/`.
- Update Cargo, Bazel, CI, deploy, config, docs, and tests.
- Keep binary names unchanged.
- Validate Rust workspace and artifact builds.

### Phase 2: Extract CLI contracts from `yoyopod/`

- Identify every `yoyopod.*` import used by `yoyopod_cli/`.
- Move active contracts into `yoyopod_cli/`.
- Update imports and tests.
- Keep CLI behavior stable.

### Phase 3: Remove Python runtime launch paths

- Remove supported `python yoyopod.py` CLI/deploy/service paths.
- Update docs and tests to treat Rust as the only app runtime owner.
- Keep Python CLI commands for operations.

### Phase 4: Test tree cleanup

- Create `tests/device/`.
- Move active device workspace/path tests into `tests/device/`.
- Keep `tests/cli`, `tests/deploy`, `tests/config`, and `tests/scripts`.
- Delete or archive old Python runtime tests.

### Phase 5: Legacy runtime quarantine

- Move any remaining Python runtime code to `legacy/python-runtime/` if it
  cannot be deleted immediately.
- Add a clear README stating it is unsupported and temporary.
- Ensure active CLI/deploy/device code does not import it.

### Phase 6: Final deletion

- Delete `legacy/python-runtime/` when scans and validation prove it is unused.
- Delete stale docs and compatibility adapters.
- Re-run all validation gates.

---

## 13. Review Checklist

- [ ] `device/` is the only Rust on-device workspace.
- [ ] `yoyopod_rs/` no longer exists in active source paths.
- [ ] Deployed binary names still include `yoyopod-runtime` and `yoyopod-*-host`.
- [ ] `yoyopod_cli/` does not import old Python runtime modules.
- [ ] No supported path launches `python yoyopod.py`.
- [ ] `tests/device/` owns device workspace tests.
- [ ] Old Python runtime tests are deleted or quarantined under
      `tests/legacy_python_runtime/`.
- [ ] `tests/cli`, `tests/deploy`, `tests/config`, and `tests/scripts` still
      protect production operations.
- [ ] Slot packaging uses `device/*/build/` paths.
- [ ] CI uses `device/...` Bazel/Cargo paths.
- [ ] Hardware validation confirms the Rust runtime owns device execution.
