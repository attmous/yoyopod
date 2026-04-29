# Rust Bazel Feature Folders Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move production Rust sources from `src/crates/<feature>` to `src/<feature>` and add Bazel targets for the Rust UI and VoIP hosts.

**Architecture:** Keep Cargo as the artifact producer for this slice, while Bazel becomes an additive Rust build/test validation path. Feature folders own their own `Cargo.toml`, `BUILD.bazel`, `src/`, and `tests/`; Python runtime paths and CLI validation move to the new artifact staging paths.

**Tech Stack:** Rust 2021, Cargo workspace under `src/`, Bazel Bzlmod, `rules_rust` crate universe, GitHub Actions, pytest.

---

### Task 1: Test The New Layout Contract

**Files:**
- Modify: `tests/deploy/test_ci_workflows.py`
- Modify: `tests/config/test_config_models.py`
- Modify: `tests/cli/test_yoyopod_cli_remote_validate.py`
- Modify: `tests/cli/test_yoyopod_cli_shortcuts.py`
- Modify: `tests/core/bootstrap/test_rust_ui_host_boot.py`
- Modify: `tests/core/test_bootstrap.py`
- Modify: `tests/ui/test_rust_host_facade.py`
- Modify: `tests/ui/test_rust_sidecar_coordinator.py`

- [ ] **Step 1: Update expected Rust artifact paths to the new feature folders**

Replace assertions for:

```text
src/crates/ui-host/build/yoyopod-ui-host
src/crates/voip-host/build/yoyopod-voip-host
```

with:

```text
yoyopod_rs/ui-host/build/yoyopod-ui-host
yoyopod_rs/voip-host/build/yoyopod-voip-host
```

- [ ] **Step 2: Add CI assertions for Bazel**

In `tests/deploy/test_ci_workflows.py`, assert the workflow contains:

```python
assert "bazelbuild/setup-bazelisk" in workflow
assert "bazel test //yoyopod_rs/ui-host/... //yoyopod_rs/voip-host/..." in workflow
assert "yoyopod_rs/ui-host/build/yoyopod-ui-host" in workflow
assert "yoyopod_rs/voip-host/build/yoyopod-voip-host" in workflow
```

- [ ] **Step 3: Add layout assertions**

In `tests/deploy/test_ci_workflows.py`, add a test that asserts these files exist:

```python
assert (REPO_ROOT / "MODULE.bazel").exists()
assert (REPO_ROOT / "BUILD.bazel").exists()
assert (REPO_ROOT / "defs.bzl").exists()
assert (REPO_ROOT / "src" / "BUILD.bazel").exists()
assert (REPO_ROOT / "src" / "ui-host" / "BUILD.bazel").exists()
assert (REPO_ROOT / "src" / "ui-host" / "tests" / "README.md").exists()
assert (REPO_ROOT / "src" / "voip-host" / "BUILD.bazel").exists()
assert (REPO_ROOT / "src" / "voip-host" / "tests" / "README.md").exists()
assert not (REPO_ROOT / "src" / "crates").exists()
```

- [ ] **Step 4: Run the focused tests and verify they fail**

Run:

```text
uv run pytest -q tests/deploy/test_ci_workflows.py tests/config/test_config_models.py tests/cli/test_yoyopod_cli_remote_validate.py tests/cli/test_yoyopod_cli_shortcuts.py tests/core/bootstrap/test_rust_ui_host_boot.py tests/core/test_bootstrap.py tests/ui/test_rust_host_facade.py tests/ui/test_rust_sidecar_coordinator.py
```

Expected: FAIL because paths and Bazel files have not moved yet.

### Task 2: Move Rust Feature Folders

**Files:**
- Move: `src/crates/ui-host/` -> `yoyopod_rs/ui-host/`
- Move: `src/crates/voip-host/` -> `yoyopod_rs/voip-host/`
- Modify: `yoyopod_rs/Cargo.toml`
- Create: `yoyopod_rs/ui-host/tests/README.md`
- Create: `yoyopod_rs/voip-host/tests/README.md`

- [ ] **Step 1: Move the feature folders with git**

Run:

```text
git mv src/crates/ui-host yoyopod_rs/ui-host
git mv src/crates/voip-host yoyopod_rs/voip-host
```

- [ ] **Step 2: Remove the empty `src/crates` directory**

If the directory remains empty after `git mv`, remove it.

- [ ] **Step 3: Update Cargo workspace members**

Set `yoyopod_rs/Cargo.toml` to:

```toml
[workspace]
resolver = "2"
members = [
    "ui-host",
    "voip-host",
]
```

- [ ] **Step 4: Add integration-test homes**

Create `yoyopod_rs/ui-host/tests/README.md`:

```markdown
# UI Host Integration Tests

External Rust integration tests for `yoyopod-ui-host` belong here. Unit tests
that exercise private module details may remain inline beside the source they
cover.
```

Create `yoyopod_rs/voip-host/tests/README.md`:

```markdown
# VoIP Host Integration Tests

External Rust integration tests for `yoyopod-voip-host` belong here. Unit tests
that exercise private module details may remain inline beside the source they
cover.
```

### Task 3: Add Bazel Rust Build Graph

**Files:**
- Create: `MODULE.bazel`
- Create: `BUILD.bazel`
- Create: `defs.bzl`
- Create: `yoyopod_rs/BUILD.bazel`
- Create: `yoyopod_rs/ui-host/BUILD.bazel`
- Create: `yoyopod_rs/voip-host/BUILD.bazel`

- [ ] **Step 1: Add root Bazel module**

Create `MODULE.bazel` with `rules_rust` Bzlmod setup, a stable Rust toolchain
matching the CI/toolchain reality, and crate universe reading `yoyopod_rs/Cargo.toml`
plus `yoyopod_rs/Cargo.lock`.

- [ ] **Step 2: Add root package marker**

Create `BUILD.bazel` with package visibility and aliases for the stable host
targets.

- [ ] **Step 3: Add Bazel helper macros**

Create `defs.bzl` with:

```python
load("@rules_rust//rust:defs.bzl", "rust_binary")

COMMON_RUST_DEPS = [...]

def yoyopod_rust_host_binary(name, crate_root = "src/main.rs", srcs = None, deps = None, **kwargs):
    rust_binary(
        name = name,
        crate_root = crate_root,
        srcs = srcs or glob(["src/**/*.rs"]),
        deps = COMMON_RUST_DEPS + (deps or []),
        edition = "2021",
        visibility = ["//visibility:public"],
        **kwargs
    )
```

The implementation can adjust labels and proc macro handling to match the
actual `rules_rust` crate universe output.

- [ ] **Step 4: Add feature BUILD files**

`yoyopod_rs/ui-host/BUILD.bazel` should expose:

```text
//yoyopod_rs/ui-host:yoyopod-ui-host
//yoyopod_rs/ui-host:tests
```

`yoyopod_rs/voip-host/BUILD.bazel` should expose:

```text
//yoyopod_rs/voip-host:yoyopod-voip-host
//yoyopod_rs/voip-host:tests
```

### Task 4: Update Runtime Paths, CI, Docs, And Skills

**Files:**
- Modify: `.github/workflows/ci.yml`
- Modify: `yoyopod/config/models/app.py`
- Modify: `yoyopod/core/bootstrap/managers_boot.py`
- Modify: `yoyopod_cli/remote_validate.py`
- Modify: `yoyopod_cli/build.py`
- Modify: `yoyopod_cli/pi/rust_ui_host.py`
- Modify: `docs/RUST_UI_HOST.md`
- Modify: `docs/RUST_UI_POC.md`
- Modify: `docs/hardware/DEPLOYED_PI_DEPENDENCIES.md`
- Modify: `skills/yoyopod-rust-artifact/SKILL.md`

- [ ] **Step 1: Replace source-of-truth artifact paths**

Replace:

```text
src/crates/ui-host/build/yoyopod-ui-host
src/crates/voip-host/build/yoyopod-voip-host
```

with:

```text
yoyopod_rs/ui-host/build/yoyopod-ui-host
yoyopod_rs/voip-host/build/yoyopod-voip-host
```

- [ ] **Step 2: Update Rust UI local build helper**

In `yoyopod_cli/build.py`, make `_rust_ui_host_crate_dir()` return:

```python
return _rust_ui_host_workspace_dir() / "ui-host"
```

- [ ] **Step 3: Update CLI default worker path**

In `yoyopod_cli/pi/rust_ui_host.py`, make `_default_worker_path()` return:

```python
return Path("src") / "ui-host" / "build" / f"yoyopod-ui-host{suffix}"
```

- [ ] **Step 4: Update CI cargo staging and upload paths**

In `.github/workflows/ci.yml`, stage artifacts into:

```text
ui-host/build
voip-host/build
```

and upload:

```text
yoyopod_rs/ui-host/build/yoyopod-ui-host
yoyopod_rs/voip-host/build/yoyopod-voip-host
```

- [ ] **Step 5: Add CI Bazel validation**

Add a Bazelisk setup step and:

```text
bazel test //yoyopod_rs/ui-host/... //yoyopod_rs/voip-host/...
```

### Task 5: Verify And Commit

**Files:**
- All files from Tasks 1-4

- [ ] **Step 1: Run Rust formatting**

Run:

```text
cargo fmt --manifest-path yoyopod_rs/Cargo.toml --all --check
```

Expected: PASS.

- [ ] **Step 2: Run Cargo tests**

Run:

```text
cargo test --manifest-path yoyopod_rs/Cargo.toml --workspace --locked
```

Expected: PASS.

- [ ] **Step 3: Run Bazel tests**

Run:

```text
bazel test //yoyopod_rs/ui-host/... //yoyopod_rs/voip-host/...
```

If local Windows Bazel is unavailable, use Bazelisk. Expected: PASS locally or
documented local bootstrap blocker with CI Bazel configured.

- [ ] **Step 4: Run required Python gates**

Run:

```text
uv run python scripts/quality.py gate
uv run pytest -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```text
git add .
git commit -m "build: add rust bazel feature folders"
```

Expected: commit succeeds with only the intended refactor files staged.
