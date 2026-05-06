# Verification Policy

The project is Rust-first for runtime work and no longer carries repo-local
automated suites. Verification is split between build/lint/type checks and Raspberry Pi
runtime validation.

## Rust Build Checks

Use focused Rust checks for the crate you changed:

```bash
cargo check --manifest-path device/Cargo.toml -p yoyopod-runtime --locked
cargo check --manifest-path device/Cargo.toml -p yoyopod-ui --locked
cargo check --manifest-path device/Cargo.toml -p yoyopod-media --locked
cargo check --manifest-path device/Cargo.toml -p yoyopod-voip --locked
cargo check --manifest-path device/Cargo.toml -p yoyopod-network --locked
```

For broad Rust workspace changes:

```bash
cargo check --manifest-path device/Cargo.toml --workspace --locked
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

Python remains for CLI, deployment, and compatibility tooling. Use the repo
quality gate for that surface:

```bash
uv run python scripts/quality.py gate
python -m compileall yoyopod_cli scripts
```

## Reporting

Always report the checks that actually ran. For hardware validation, include:

- branch
- exact commit SHA
- artifact names and CI run ID
- active runtime owner (`yoyopod-runtime`)
- Pi command result
- whether the dev service was left running
