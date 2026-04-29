# Rust Bazel Feature Folders - Design Spec

## Problem

YoYoPod is moving the production runtime toward Rust. The current Rust
workspace has the UI and VoIP hosts under an extra `src/crates/` layer:

```text
src/
  Cargo.toml
  Cargo.lock
  crates/
    ui-host/
    voip-host/
```

That shape was useful while the Rust hosts were early sidecars, but it is not
the long-term production shape the project wants. The next refactor should make
the Rust tree read like product runtime code, not a staging area for experiments.

The user-requested target is Rust-only and inspired by the Codex Rust feature
layout, where each feature crate owns its own `src/`, `tests/`, and
`BUILD.bazel` file. The reference example is:

- <https://github.com/openai/codex/tree/main/codex-rs/core>
- <https://raw.githubusercontent.com/openai/codex/main/codex-rs/core/BUILD.bazel>

This slice should introduce Bazel and the feature-folder layout without moving
Python into Bazel and without changing runtime behavior.

## Goal

Make top-level `src/` the production Rust workspace with feature crates directly
under it:

```text
src/
  Cargo.toml
  Cargo.lock
  ui-host/
    Cargo.toml
    BUILD.bazel
    src/
    tests/
  voip-host/
    Cargo.toml
    BUILD.bazel
    src/
    tests/
```

Add Bazel as the Rust build system entrypoint:

```text
MODULE.bazel
BUILD.bazel
defs.bzl
src/
  BUILD.bazel
  ui-host/BUILD.bazel
  voip-host/BUILD.bazel
```

Cargo remains supported during the transition because the current CI artifact
and developer workflows already depend on it. Bazel should be introduced as a
first-class Rust validation path in this slice, then promoted to artifact
production after it is stable on CI.

## Non-Goals

- Do not move Python code into Bazel.
- Do not add Bazel targets for Python tests, packages, or deploy scripts.
- Do not change UI, VoIP, runtime, display, input, or SIP behavior.
- Do not change the Python-to-Rust worker protocols.
- Do not build Rust binaries on the Raspberry Pi Zero 2W.
- Do not delete Cargo support in this slice.
- Do not move historical plan docs just to update old path examples.

## Target Repository Structure

The production Rust source tree should become:

```text
src/
  Cargo.toml
  Cargo.lock
  BUILD.bazel
  ui-host/
    Cargo.toml
    BUILD.bazel
    src/
      main.rs
      ...
    tests/
      README.md
  voip-host/
    Cargo.toml
    BUILD.bazel
    src/
      main.rs
      ...
    tests/
      README.md
```

Meaning:

- `src/` remains the Rust workspace root.
- `yoyopod_rs/ui-host/` is the production Rust UI host feature folder.
- `yoyopod_rs/voip-host/` is the production Rust VoIP host feature folder.
- Each feature folder owns its own Cargo manifest, Bazel target file, source
  tree, and external integration-test home.
- Existing inline Rust unit tests may remain beside the modules they test.
  `tests/` is added as the home for future integration tests, not as a forced
  extraction of existing unit tests.
- There is no `src/rust/` layer and no `src/crates/` layer.

Future Rust runtime features should follow the same shape:

```text
src/
  feature-name/
    Cargo.toml
    BUILD.bazel
    src/
    tests/
```

## Move Plan

Move the current crates with `git mv`:

```text
src/crates/ui-host/   -> yoyopod_rs/ui-host/
src/crates/voip-host/ -> yoyopod_rs/voip-host/
```

Update `yoyopod_rs/Cargo.toml` workspace members:

```toml
[workspace]
resolver = "2"
members = [
    "ui-host",
    "voip-host",
]
```

The package and binary names do not change:

```text
yoyopod-ui-host
yoyopod-voip-host
```

The build output staging paths do change:

```text
yoyopod_rs/ui-host/build/yoyopod-ui-host
yoyopod_rs/voip-host/build/yoyopod-voip-host
```

## Bazel Design

Use Bazel with Bzlmod and `rules_rust`.

Root files:

```text
MODULE.bazel
BUILD.bazel
defs.bzl
```

`MODULE.bazel` should pin Bazel module dependencies, including `rules_rust`.
The implementation should pick current stable versions from upstream
`rules_rust` documentation at the time of the patch.

`defs.bzl` should hold small repo-local macros so feature `BUILD.bazel` files
stay readable. The first macro can wrap common settings for a YoYoPod Rust
binary crate:

```text
yoyopod_rust_binary(
    name = "yoyopod-ui-host",
    srcs = glob(["src/**/*.rs"]),
    edition = "2021",
    deps = [...],
)
```

The exact macro shape can be adjusted during implementation to fit `rules_rust`
well. The important design constraint is that Bazel files should remain
human-readable and feature-local.

Expected public targets:

```text
//yoyopod_rs/ui-host:yoyopod-ui-host
//yoyopod_rs/ui-host:tests
//yoyopod_rs/voip-host:yoyopod-voip-host
//yoyopod_rs/voip-host:tests
```

If `rules_rust` makes per-module test targets more idiomatic than one `:tests`
alias, use the idiomatic target layout and provide aliases for the stable public
target names above.

Third-party Rust dependencies should be sourced from the existing Cargo lock
file where possible. The preferred path is `rules_rust` crate universe support
from `yoyopod_rs/Cargo.lock`, so Cargo and Bazel do not drift into independent
dependency graphs.

## CI Design

Keep the existing Cargo-based Rust CI path initially, but update its paths for
the new feature folders:

```text
cargo test --workspace --locked --features whisplay-hardware
cargo build --release -p yoyopod-ui-host --features whisplay-hardware --locked
cargo build --release -p yoyopod-voip-host --locked
```

Artifact staging should become:

```text
yoyopod_rs/ui-host/build/yoyopod-ui-host
yoyopod_rs/voip-host/build/yoyopod-voip-host
```

Add a Bazel Rust validation step:

```text
bazel test //yoyopod_rs/ui-host/... //yoyopod_rs/voip-host/...
```

If CI does not already have Bazel, use Bazelisk in CI. The implementation should
avoid requiring a local, manually installed Bazel binary when there is a
reasonable Bazelisk path.

Do not switch production artifact generation from Cargo to Bazel in this slice
unless the Bazel binary output is simple, stable, and proven by CI in the same
PR. The safe default is:

- Cargo continues to produce deploy artifacts.
- Bazel proves that the new build graph can build and test the Rust hosts.
- A later PR can promote Bazel to artifact owner once the CI path is boring.

## Runtime And Deploy Path Updates

Update current source-of-truth runtime defaults and tools from old paths to new
paths:

```text
old: src/crates/ui-host/build/yoyopod-ui-host
new: yoyopod_rs/ui-host/build/yoyopod-ui-host

old: src/crates/voip-host/build/yoyopod-voip-host
new: yoyopod_rs/voip-host/build/yoyopod-voip-host
```

Known update areas:

- `.github/workflows/ci.yml`
- `yoyopod/config/models/app.py`
- `yoyopod/core/bootstrap/managers_boot.py`
- `yoyopod_cli/remote_validate.py`
- `yoyopod_cli/build.py`
- `yoyopod_cli/pi/rust_ui_host.py`
- path-focused tests under `tests/`
- `docs/RUST_UI_HOST.md`
- `docs/RUST_UI_POC.md`
- `docs/hardware/DEPLOYED_PI_DEPENDENCIES.md`
- `skills/yoyopod-rust-artifact/SKILL.md`

Historical plan/spec docs can keep old paths unless they are actively used as
current operational docs. The current docs and skills should be accurate.

## Validation

Required local validation before commit and push:

```text
cargo fmt --manifest-path yoyopod_rs/Cargo.toml --all --check
cargo test --manifest-path yoyopod_rs/Cargo.toml --workspace --locked
bazel test //yoyopod_rs/ui-host/... //yoyopod_rs/voip-host/...
uv run python scripts/quality.py gate
uv run pytest -q
```

If Bazel cannot run locally on Windows because of a toolchain bootstrap issue,
the implementation must document the exact blocker and prove the Bazel step on
GitHub Actions before the PR is considered mergeable.

Hardware validation is not required for this refactor by itself because runtime
behavior should not change. A post-merge or follow-up smoke test is still useful
because deploy artifact paths change.

## Risks

- Path churn can break CI artifact upload or target-side deploy commands.
- Cargo and Bazel dependency graphs can diverge if Bazel dependencies are
  hand-maintained.
- `rules_rust` setup can be noisy on Windows if the local Bazel bootstrap path
  is not explicit.
- Moving directories can make PR review noisy if behavior changes are mixed in.
- The word `src/` now means both Rust workspace root and per-feature source
  folder, so documentation must be precise.

## Acceptance Criteria

This design is accepted when:

- production Rust sources live directly under top-level `src/<feature>/`
- `src/crates/` is removed
- no `src/rust/` layer is introduced
- UI host has `yoyopod_rs/ui-host/{Cargo.toml,BUILD.bazel,src/,tests/}`
- VoIP host has `yoyopod_rs/voip-host/{Cargo.toml,BUILD.bazel,src/,tests/}`
- Cargo workspace members point to `ui-host` and `voip-host`
- Bazel can build and test the Rust hosts through checked-in Bazel targets
- CI runs the Bazel Rust validation path
- deploy artifact paths are updated to `yoyopod_rs/ui-host/build/...` and
  `yoyopod_rs/voip-host/build/...`
- Python runtime defaults and CLI validators use the new paths
- current operational docs and deploy skills use the new paths
- Rust code and Bazel files follow clean code and Rust guidelines:
  - `rustfmt` output is clean
  - module boundaries are narrow
  - names describe ownership and behavior
  - errors are explicit
  - control flow is straightforward
  - Bazel macros hide repetition but not important behavior
  - production code is human-readable before it is clever

## Implementation Sequence

1. Add Bazel root files and minimal Rust target plumbing.
2. Move `src/crates/ui-host` to `yoyopod_rs/ui-host`.
3. Move `src/crates/voip-host` to `yoyopod_rs/voip-host`.
4. Add `tests/README.md` placeholders for both feature folders.
5. Update Cargo workspace members.
6. Update CI artifact staging and upload paths.
7. Update Python runtime defaults, CLI helpers, tests, docs, and deploy skills.
8. Run Cargo, Bazel, quality, and pytest validation.
9. Commit and open a reviewable PR with no runtime behavior changes.

## Deferred Decisions

- When Bazel should replace Cargo as the artifact producer.
- Whether future Rust features should be one binary, multiple host binaries, or
  a shared runtime binary with internal services.
- Whether to add a shared Rust protocol crate before the next runtime slice.
- Whether to convert existing inline unit tests into external integration tests
  where that improves readability.
