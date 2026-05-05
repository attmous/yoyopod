# Verification Policy

The project is now Rust-first for runtime work. The old Python quality gate is
not the default local pre-commit or pre-push requirement for Rust runtime,
worker, or LVGL scene work.

## Rust Runtime Checks

Use focused Rust checks for the crate you changed:

```bash
cargo test --manifest-path yoyopod_rs/Cargo.toml -p yoyopod-runtime --locked
cargo test --manifest-path yoyopod_rs/Cargo.toml -p yoyopod-ui --locked
cargo test --manifest-path yoyopod_rs/Cargo.toml -p yoyopod-media --locked
cargo test --manifest-path yoyopod_rs/Cargo.toml -p yoyopod-voip --locked
cargo test --manifest-path yoyopod_rs/Cargo.toml -p yoyopod-network --locked
```

For broad Rust workspace changes:

```bash
cargo test --manifest-path yoyopod_rs/Cargo.toml --workspace --locked
```

If native LVGL or Whisplay hardware features are involved, use the CI-built ARM
artifact for the exact commit before claiming hardware parity.

## Hardware Checks

The Raspberry Pi is the real validation target for runtime ownership, display,
button input, audio, SIP, modem, power, and LVGL behavior.

Normal committed-code flow:

```bash
git rev-parse HEAD
yoyopod remote mode activate dev
yoyopod remote validate --branch <branch> --sha <commit> --with-rust-ui-host --with-lvgl-soak
```

When testing `yoyopod-runtime`, install the exact-SHA Rust artifacts first. See
`skills/yoyopod-rust-artifact/SKILL.md`.

## Python Checks

Python remains for CLI, deployment, compatibility, and selected tests. Run
targeted Python tests when those surfaces change:

```bash
uv run pytest -q tests/cli
uv run pytest -q tests/deploy
```

The legacy wrapper still exists for Python CI maintenance, but it is no longer
documented as a default local gate. Use it only when you are working on Python
tooling, fixing CI, or explicitly asked to mirror the current Python CI jobs.
Do not treat it as the default gate for Rust runtime iteration.

## Reporting

Always report the checks that actually ran. For hardware validation, include:

- branch
- exact commit SHA
- artifact names and CI run ID
- active runtime owner (`yoyopod-runtime` or Python fallback)
- Pi command result
- whether the dev service was left running
