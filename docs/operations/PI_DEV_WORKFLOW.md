# Raspberry Pi Dev Workflow

This guide covers the normal dev-machine-to-board loop for yoyopod.

For fresh-board bootstrap, lane structure, and rollback, read:

- [`DEV_PROD_LANES.md`](DEV_PROD_LANES.md)
- [`archive/SLOT_DEPLOY.md`](archive/SLOT_DEPLOY.md) (paused; pointer to Round 3 work)
- [`../ROADMAP.md`](../ROADMAP.md) for what's broken
  during the CLI rebuild

The default contract is:

1. finish the implementation locally
2. commit the intended changes
3. push the branch (CI must complete the `rust-device-arm64` build for
   the exact commit)
4. deploy that committed branch / commit SHA to the Pi via the Rust CLI
5. verify the runtime started cleanly and exercise the change

Dirty-tree deploys are not supported by `yoyopod target deploy`. The
CI-artifact contract requires a pushed commit so the matching
`yoyopod-rust-device-arm64-<sha>` bundle can be downloaded.

Terminology:

- `yoyopod target deploy` updates the **dev lane** checkout and
  installs the CI-built worker binaries.
- `yoyopod target restart` restarts `yoyopod-dev.service` and verifies
  startup.
- `yoyopod target mode status` should be checked before lane flips or
  hardware debugging.

## Stable Board Checkout

The Raspberry Pi reuses one stable dev checkout path, configured by
`project_dir` in `deploy/pi-deploy.yaml`. The tracked default is
`/opt/yoyopod-dev/checkout`.

Why one stable path:

- the systemd unit, logs, PID file, and CLI shell builders all expect
  it
- native LVGL rebuilds are expensive
- repeated fresh copies waste time

Do not normalise ad-hoc per-branch checkout directories on the board.

## Setup

Make sure your dev machine can SSH into the Raspberry Pi with an alias
or reachable hostname.

Install the Rust CLI on the dev machine:

```bash
cargo build --manifest-path cli/Cargo.toml --release
cargo install --path cli/yoyopod
```

`gh` (GitHub CLI) must be authenticated (`gh auth status`) for
`yoyopod target deploy` to pull CI artifacts.

The repo-tracked deploy contract lives in `deploy/pi-deploy.yaml`.

- keep `host` and `user` blank there
- keep the shared `project_dir` stable there
- put machine-specific values in `deploy/pi-deploy.local.yaml`
- create or update that file with:

```bash
yoyopod target config edit
```

Pi-side setup (system packages, lane directories, systemd units) is
manual until the CLI rebuild restores `yoyopod target setup`; see
[`SETUP_CONTRACT.md`](SETUP_CONTRACT.md) and
[`DEV_PROD_LANES.md`](DEV_PROD_LANES.md).

Examples:

```bash
ssh rpi-zero
ssh tifo@192.168.1.42
```

Optional environment defaults:

```bash
export YOYOPOD_PI_HOST=rpi-zero
export YOYOPOD_PI_USER=tifo
export YOYOPOD_PI_PROJECT_DIR=/opt/yoyopod-dev/checkout
```

The CLI reads these as fallbacks for the `--host`, `--user`, and
`--project-dir` flags.

## Daily loop

```bash
# 1. Confirm lane state.
yoyopod target mode status
yoyopod target mode activate dev          # if needed

# 2. Commit + push the change you want on hardware.
git add -p && git commit -m '…'
git push

# 3. Deploy. The CLI pushes if needed, finds the CI artifact, syncs the
#    Pi, installs the worker binaries, restarts and verifies startup.
yoyopod target deploy --branch <branch>   # or --sha <commit>

# 4. Manual eyes-on verification.
yoyopod target status
yoyopod target logs --follow
```

Add `--wait-for-ci` when CI is still queued or in-progress (timeout 30
minutes).

Add `--clean-native` after native LVGL / CMake input changes so the
Pi-side build dir gets wiped.

## Inspection commands

```bash
yoyopod target status                     # git SHA + processes + log tail
yoyopod target logs --lines 200
yoyopod target logs --errors
yoyopod target logs --filter ERROR
yoyopod target logs --follow --filter comm
yoyopod target screenshot                 # captures Pi display to logs/screenshots/
yoyopod target screenshot --readback      # LVGL readback path
yoyopod target restart                    # systemd restart + startup verify
```

## Validation gap

Automated on-Pi validation (`yoyopod target validate`) is a Round 1
stub that returns exit 2. Until Round 2 of the CLI rebuild lands,
validate manually after deploy:

```bash
yoyopod target status
yoyopod target logs --follow
ssh <user>@<host> 'journalctl -u yoyopod-dev.service -f'
```

Exercise the changed surface on the device with human eyes and report
the result.

## Troubleshooting

If `target deploy` fails:

```bash
yoyopod target logs --lines 200 --errors
yoyopod target status
ssh <user>@<host> 'systemctl status yoyopod-dev.service --no-pager -l'
```

Common causes:

- `gh` not authenticated → run `gh auth login`
- CI run for that commit still in-progress → use `--wait-for-ci`, or
  wait and rerun
- CI run failed → fix the underlying problem; don't try to deploy a
  broken commit
- prod lane active → `yoyopod target mode activate dev` first
- Pi checkout owned by wrong user → check ownership of
  `/opt/yoyopod-dev/checkout`

## Related Docs

- [`../ROADMAP.md`](../ROADMAP.md) for the rebuild
  roadmap
- [`DEV_PROD_LANES.md`](DEV_PROD_LANES.md) for lane structure
- [`archive/SLOT_DEPLOY.md`](archive/SLOT_DEPLOY.md) for the (paused) prod slot flow
- [`SETUP_CONTRACT.md`](SETUP_CONTRACT.md) for system dependencies
- [`QUALITY_GATES.md`](QUALITY_GATES.md) for what passes for
  verification today
- `rules/deploy.md` for the policy that backs all of the above
