# yoyopod CLI (Rust)

The Rust replacement for the retired Python `yoyopod_cli`. See
[../docs/ROADMAP.md](../docs/ROADMAP.md)
for the full rebuild plan; this README covers the **Round 1 MVP**.

## What's here in Round 1

Single binary, `yoyopod`. Nine commands all under `yoyopod target ...`:

| Command | Status |
|---|---|
| `target config edit` | implemented |
| `target mode status` | implemented |
| `target mode activate {dev,prod}` | implemented |
| `target deploy [--sha ...] [--clean-native] [--wait-for-ci]` | implemented |
| `target status` | implemented |
| `target restart` | implemented |
| `target logs [--lines N] [--follow] [--errors] [--filter PATTERN]` | implemented |
| `target screenshot [--out PATH] [--readback]` | implemented |
| `target validate [--sha S] [--with-lvgl-soak] [--with-navigation]` | implemented (Round 2; voip / cloud-voice stages still pending) |

Everything else from the old Python CLI returns in later rounds.

### What `target validate` does (Round 2)

Enforces the same committed-code contract as `target deploy`, then over
SSH: syncs the Pi checkout to the pushed revision, verifies the
CI-built binaries are installed, and runs the staged validation suite
via the on-Pi companion binary shipped inside the artifact bundle:

```
device/onpi/build/yoyopod-on-pi validate deploy
device/onpi/build/yoyopod-on-pi validate smoke
device/onpi/build/yoyopod-on-pi validate stability
# --with-lvgl-soak   adds: validate lvgl
# --with-navigation  adds: validate navigation
```

The `voip` and `cloud-voice` stages are not ported yet (Round 2
follow-up); `--with-voip` is rejected with a clear message until then.
The on-Pi binary source lives at `../device/onpi/`.

## Install

```bash
# From the repo root:
cargo build --manifest-path cli/Cargo.toml --release
# The binary is at cli/target/release/yoyopod

# Optional: install into your PATH:
cargo install --path cli/yoyopod
```

The binary is named `yoyopod`. There is no Python CLI installed alongside
— the old `yoyopod` console script was retired with `yoyopod_cli/`.

## Configure

The CLI looks for a Pi target via three layers, highest first:

1. CLI flags: `--host`, `--user`, `--project-dir`, `--branch`
2. Environment variables: `YOYOPOD_PI_HOST`, `YOYOPOD_PI_USER`,
   `YOYOPOD_PI_PROJECT_DIR`, `YOYOPOD_PI_BRANCH`
3. `deploy/pi-deploy.yaml` (tracked baseline) + `deploy/pi-deploy.local.yaml`
   (per-machine override; not tracked)

First-time setup:

```bash
yoyopod target config edit
```

This opens `deploy/pi-deploy.local.yaml` in `$EDITOR` (creating it from a
template if needed). Fill in `host:` and `user:` for your Pi and save.

## The daily dev loop

```bash
# 1. Confirm the Pi is on the dev lane.
yoyopod target mode status
yoyopod target mode activate dev      # if not already

# 2. After committing and pushing a change to a branch:
yoyopod target deploy --branch <branch>
# or, to pin to a specific commit:
yoyopod target deploy --sha <commit-sha>

# 3. Inspect.
yoyopod target status
yoyopod target logs --follow
yoyopod target screenshot
```

### What `target deploy` does

Replaces the multi-step manual `skills/yoyopod-rust-artifact/SKILL.md`
flow with one command:

1. Verifies the local worktree is clean and the requested commit is
   pushed to origin.
2. Uses `gh` (the GitHub CLI) to find the successful CI run for the
   exact commit and download `yoyopod-rust-device-arm64-<sha>` locally
   (cached at `.artifacts/rust-device/<sha>/`).
3. SSHes to the Pi, fetches and checks out the same commit in the dev
   lane checkout, and cleans build dirs.
4. `scp`s the artifact tarball, extracts it into the checkout, and
   `chmod +x`s every worker host binary.
5. Restarts `yoyopod-dev.service` and waits for the runtime to install
   its startup marker in the log.

Pass `--wait-for-ci` if you want to fire-and-forget while CI is still
queued or in-progress (timeout 30 min).

`target deploy` requires `gh` to be on `$PATH` and authenticated
(`gh auth status`).

## Dry-run

Most `target` commands accept `--dry-run` (global flag, before the
subcommand name) and will print the SSH command they would have run
without executing it:

```bash
yoyopod --dry-run target --host pi.local --user pi status
yoyopod --dry-run target --host pi.local --user pi logs --filter ERROR
yoyopod --dry-run target --host pi.local --user pi mode activate dev
```

Useful for inspecting what the CLI is about to do, or comparing against
the old Python output during the rebuild.

`target deploy` honours `--dry-run` AFTER the local committed-code
checks pass — the pre-checks are fail-fast even in dry mode by design.

## Architecture

```
cli/
├── Cargo.toml                   # workspace
├── rust-toolchain.toml          # pin stable
└── yoyopod/
    ├── Cargo.toml               # binary crate
    └── src/
        ├── main.rs              # clap dispatch
        ├── cli.rs               # Args / Command enums
        ├── repo.rs              # repo-root discovery
        ├── quoting.rs           # POSIX shell + ~/ preserving quoter
        ├── paths.rs             # PiPaths / LanePaths defaults
        ├── deploy_config.rs     # pi-deploy.yaml + .local.yaml merge
        ├── ssh.rs               # build/run SSH commands
        ├── local.rs             # local subprocess helpers
        ├── logging.rs           # tracing-subscriber init
        └── commands/
            └── target/
                ├── mod.rs       # dispatch + dry-run helper
                ├── config.rs    # config edit
                ├── mode.rs      # mode status/activate
                ├── ops.rs       # status, restart (+ shared builders)
                ├── logs.rs      # logs
                ├── screenshot.rs
                ├── deploy.rs    # the big one
                └── validate.rs  # SSH orchestration of yoyopod-on-pi
```

No async runtime. All SSH and subprocess work is synchronous and
sequential — the CLI is an orchestrator, not a server.

## Build / test

```bash
cargo build   --manifest-path cli/Cargo.toml
cargo test    --manifest-path cli/Cargo.toml
cargo clippy  --manifest-path cli/Cargo.toml --all-targets
cargo fmt     --manifest-path cli/Cargo.toml --all
```

35 unit tests cover quoting edge cases, YAML merge semantics, SSH
command shape, deploy pre-checks, and the major shell-builder outputs.

## Roadmap

Round 2 (in progress): base validation stages are restored via the
`yoyopod-on-pi` companion binary; the `voip` and `cloud-voice` stage
ports are the remaining follow-up.

Round 3: restore the prod release pipeline (slot builder, manifest,
preflight) and re-enable the disabled CI jobs.

Round 4+: on-Pi diagnostics (`pi voip`, `pi power`, `pi network`) as
needed.

See [../docs/ROADMAP.md](../docs/ROADMAP.md).
