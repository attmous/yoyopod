# Slot Deploy (OTA-Ready)

This is the operator guide for the slot-deploy path.

Use slot deploy when you want immutable release directories under `/opt/yoyopod`,
atomic `current`/`previous` flips, and rollback support. The running app lives
under `/opt/yoyopod`. As of the current implementation, `yoyopod remote release`
no longer depends on a repo checkout on the Pi; the older `remote sync`,
`remote validate`, and `remote setup` flows still do, but they no longer require
`uv` to be installed on the Pi.

## Current Status

The slot-deploy flow is now the preferred deployment path for provisioned boards.
The legacy `yoyopod remote sync` and `yoyopod@.service` flow still exists for
working-tree debugging and older boards, but slot deploy is the path intended for
repeatable OTA-style updates.

Current contract:

- every release lives in `/opt/yoyopod/releases/<version>/`
- `current` points at the active release
- `previous` points at the last release for rollback
- self-contained slots carry their own `venv/bin/python` and native shim `.so` files
- `yoyopod remote release push` accepts either a slot directory or a `.tar.gz` artifact
- Pi-side hydration is now a legacy compatibility path used only with `--hydrate-on-target`
- `yoyopod remote release build-pi` builds a self-contained artifact on the Pi checkout and downloads it locally
- CI and tagged releases can publish a ready-to-install ARM64 slot tarball
- PR slot artifacts are built only when the PR has the `build-arm-slot` label
  or the CI workflow is run manually
- `deploy/scripts/install_release.sh` installs a published slot tarball directly under `/opt/yoyopod`
- tracked repo `config/` is bundled into every slot
- `YOYOPOD_STATE_DIR` exists for persistent state, but runtime config is still read
  from the slot's bundled `./config`

## On-Device Layout

```text
/opt/yoyopod/
|-- releases/
|   |-- 2026.04.23-hydrate-local5/
|   |   |-- app/
|   |   |-- assets/
|   |   |-- bin/launch
|   |   |-- config/
|   |   |-- manifest.json
|   |   |-- runtime-requirements.txt
|   |   `-- venv/
|   `-- 2026.04.23-fd711617/
|-- current -> releases/2026.04.23-hydrate-local5
|-- previous -> releases/2026.04.23-fd711617
|-- bin/rollback.sh
`-- state/
    |-- config/
    |-- logs/
    `-- tmp/
```

What each piece is for:

- `app/`: copied `yoyopod/` and `yoyopod_cli/` source trees
- `config/`: tracked repo config shipped with the release
- `runtime-requirements.txt`: dependency contract used for Pi-side hydration
- `venv/`: slot-local runtime Python environment
- `state/`: persistent board-owned state that must survive updates

## Before You Start

### Dev machine prerequisites

Run these once on the machine that will push releases:

```bash
uv sync --extra dev
uv run yoyopod setup verify-host --with-remote-tools
```

Create or update your local remote override:

```bash
yoyopod remote config edit
```

Recommended local settings:

- `host`: your SSH alias or Pi IP
- `user`: the Pi login user that should run the app
- `project_dir`: only needed for the legacy `remote sync/validate/setup` flows
- `slot.root`: `/opt/yoyopod` unless you intentionally use another root

### Pi prerequisites

For `yoyopod remote release ...`, the Pi does not need a live repo checkout after
bootstrap. Those commands now operate directly on `/opt/yoyopod`.

The older `yoyopod remote sync`, `yoyopod remote validate`, and
`yoyopod remote setup` flows still use the configured `project_dir` and therefore
still need a stable checkout on the board.

Those legacy checkout-based flows now bootstrap and use the checkout-local
`.venv/bin/python` directly. In other words: keep the checkout if you still use
those flows, but you do not need a separate `uv` install on the board anymore.

If you still use those legacy remote flows, the default checkout path is:

```bash
~/yoyopod-core
```

If you choose a different path, it must match `project_dir` in your deploy config.

## Fresh Board Install

Use this when the board does not already have a YoYoPod deployment.

### 1. Clone the repo on the Pi for bootstrap

SSH to the Pi and clone the repo somewhere convenient for bootstrap:

```bash
ssh tifo@rpi-zero
git clone <repo-url> ~/yoyopod-core
cd ~/yoyopod-core
```

### 2. Install the board prerequisites

From the dev machine, run the repo-owned setup flow against that checkout if you
want the legacy `remote setup/validate` tooling available:

```bash
uv run yoyopod remote setup --with-pisugar
uv run yoyopod remote verify-setup --with-pisugar
```

Add `--with-network` and/or `--with-voice` if that board needs the modem or
voice stack. `remote setup` now creates or refreshes the checkout `.venv` with
plain Python tooling on the board instead of relying on `uv`.

### 3. Bootstrap the slot-deploy root

On the Pi, from the repo checkout:

```bash
cd ~/yoyopod-core
sudo -E ./deploy/scripts/bootstrap_pi.sh
```

If you intentionally use a non-default root:

```bash
sudo -E ./deploy/scripts/bootstrap_pi.sh --root=/srv/yoyopod-alt
```

That value must match `slot.root` in `deploy/pi-deploy.local.yaml`.

After bootstrap completes, `yoyopod remote release ...` no longer needs this
checkout to remain on the Pi.

If you already have a published slot artifact URL, bootstrap can also install it
immediately:

```bash
cd ~/yoyopod-core
sudo -E ./deploy/scripts/bootstrap_pi.sh --release-url=<artifact-url>
```

### 4. Build the first self-contained slot

On the dev machine:

```bash
uv run yoyopod remote release build-pi --output build/releases --channel dev
```

That is the recommended workflow when your workstation is not itself a Linux/aarch64
build environment.

If you do have a matching builder already, you can build locally instead:

```bash
uv run python scripts/build_release.py --output build/releases --channel dev --with-venv
```

Or set the version explicitly:

```bash
uv run yoyopod remote release build-pi --output build/releases --channel dev --version 2026.04.23-mybuild
```

### 5. Push the first release

The first slot deploy has no rollback target yet, so `--first-deploy` is required:

```bash
uv run yoyopod remote release push build/releases/<version>.tar.gz --first-deploy
```

If you have not stored `host` and `user` locally yet:

```bash
uv run yoyopod remote --host rpi-zero --user tifo release push build/releases/<version>.tar.gz --first-deploy
```

If the artifact was published by CI or a tagged GitHub release, you can install
it on the Pi without a local build directory:

```bash
uv run yoyopod remote --host rpi-zero --user tifo release install-url <artifact-url> --first-deploy
```

### 6. Enable boot-time startup

After the first successful push:

```bash
ssh tifo@rpi-zero
sudo systemctl enable yoyopod-slot.service
```

### 7. Verify board state

```bash
uv run yoyopod remote release status
ssh tifo@rpi-zero 'systemctl status yoyopod-slot.service --no-pager -l'
```

Expected result:

- `current=<version>`
- `health=ok`
- `yoyopod-slot.service` is `active`

## Migrating an Existing `~/yoyopod-core` Board

Use this when the board already runs the legacy working-tree deployment under
`~/yoyopod-core`.

### Migration checklist

Before cutover, verify these points:

- any important local config edits under `~/yoyopod-core/config/` are reviewed
- you understand that slot deploy runs the bundled slot `config/`, not `state/config/`
- you have a maintenance window for the first cutover because `--first-deploy`
  has no rollback target yet

### 1. Preserve old board-owned files

On the Pi:

```bash
cd ~/yoyopod-core
sudo -E ./deploy/scripts/bootstrap_pi.sh --migrate
```

This preserves:

- `~/yoyopod-core/config/` -> `/opt/yoyopod/state/config/`
- `~/yoyopod-core/logs/` -> `/opt/yoyopod/state/logs/`

Important: those copied config files are preserved for reference and future
state-dir work, but the running slot still reads its own bundled `./config`.
If the old board depends on local config drift that is not tracked in git, bring
those changes into the repo's `config/` tree before the first slot build.

### 2. Build the first migration slot

On the dev machine:

```bash
uv run yoyopod remote release build-pi --output build/releases --channel dev
```

### 3. Cut over from the legacy service to the slot service

On the Pi, identify the legacy unit name first:

```bash
systemctl list-units 'yoyopod@*.service'
```

Then stop and disable it immediately before the first slot push:

```bash
sudo systemctl disable --now yoyopod@tifo.service
```

Now push the first slot release:

```bash
uv run yoyopod remote --host rpi-zero --user tifo release push build/releases/<version>.tar.gz --first-deploy
```

Or install the published release asset directly:

```bash
uv run yoyopod remote --host rpi-zero --user tifo release install-url <artifact-url> --first-deploy
```

After the push succeeds:

```bash
ssh tifo@rpi-zero
sudo systemctl enable yoyopod-slot.service
```

### 4. Verify the migration result

```bash
uv run yoyopod remote --host rpi-zero --user tifo release status
ssh tifo@rpi-zero 'readlink -f /opt/yoyopod/current && systemctl is-active yoyopod-slot.service'
```

Expected result:

- `current=<version>`
- `health=ok`
- `yoyopod-slot.service` is active
- the old `yoyopod@<user>.service` is disabled

### 5. First post-migration follow-up deploy

After one more successful slot release, `previous` becomes meaningful and normal
rollback is available:

```bash
uv run yoyopod remote release build-pi --output build/releases --channel dev
uv run yoyopod remote release push build/releases/<next-version>.tar.gz
```

## Normal Day-Two Deploys

After the board has already been migrated or bootstrapped once:

```bash
uv run yoyopod remote release build-pi --output build/releases --channel dev
uv run yoyopod remote release push build/releases/<version>.tar.gz
uv run yoyopod remote release status
```

For published artifacts:

```bash
uv run yoyopod remote release install-url <artifact-url>
uv run yoyopod remote release status
```

The published `.tar.gz` also has a `.tar.gz.sha256` sidecar for validating the
archive bytes. The `manifest.json` inside the slot records a stable digest of
the unpacked slot payload, excluding `manifest.json` itself; it intentionally
does not try to hash the tarball that contains it.

What happens during `release push`:

1. upload the new slot to `/opt/yoyopod/releases/<version>/`
2. repair `bin/launch` permissions on the Pi after upload
3. if the artifact is legacy source-only and you explicitly passed `--hydrate-on-target`,
   build the slot-local `venv/` and copy native runtime shims on the Pi
4. run `yoyopod health preflight`
5. atomically flip `current` and `previous`
6. restart `yoyopod-slot.service`
7. run a shell-only live probe against the active systemd unit and active slot path

What happens during `release install-url`:

1. download the published tarball on the Pi
2. safely extract it into a staging dir
3. run slot preflight using the slot-local runtime
4. atomically flip `current` and `previous`
5. restart `yoyopod-slot.service`
6. run the same shell-only live probe

## Rollback

Manual rollback:

```bash
uv run yoyopod remote release rollback
```

Automatic rollback:

- `yoyopod-slot.service` has `OnFailure=yoyopod-rollback.service`
- after repeated crash loops, systemd invokes `/opt/yoyopod/bin/rollback.sh`

Check the current rollback state:

```bash
uv run yoyopod remote release status
ssh tifo@rpi-zero 'readlink -f /opt/yoyopod/current && readlink -f /opt/yoyopod/previous'
```

## Known Limits and Pitfalls

These are the issues found while bringing the flow up on a real Pi Zero 2W.

### Release deploys no longer need a repo checkout; build-pi and legacy remote flows still do

`yoyopod remote release ...` now talks directly to `/opt/yoyopod`, so it does not
need `~/yoyopod-core` after bootstrap for `push`, `rollback`, or `status`.
`yoyopod remote release build-pi` still uses the stable checkout as a build factory,
and the older `remote sync`, `remote validate`, and `remote setup` flows still
depend on `project_dir`, so only remove the checkout if you are intentionally
dropping those workflows.

Those legacy checkout-based flows no longer require `uv` on the board, though:
they bootstrap and use the checkout-local `.venv` directly.

### First deploy has no safety net

`--first-deploy` is an explicit acknowledgement that `previous` does not exist yet.
Do not promise rollback until a second successful slot release has completed.

### Pi Zero memory is tight

Starting extra Python processes just to ask "is the app healthy?" can tip the
board into OOM pressure during startup. The release live probe now uses shell and
systemd state instead of spawning a second Python health check on the Pi.

### Do not reuse stale native build directories

Copying full CMake build trees between slots carries stale `CMakeCache.txt`
paths and breaks `ensure-native`. Copy only the built native artifacts, or rebuild
from scratch in the new slot.

### Slot-local imports must be forced

Pi-side helper commands like `health preflight` and `build ensure-native` must
import from the slot's `app/` tree, not whatever still exists in
the older board checkout. Otherwise a later SSH session can accidentally execute
the wrong code.

### Windows upload path needs permission repair

When `rsync` is unavailable or unreliable from Windows, the flow falls back to
`scp`. That path can drop the executable bit on `bin/launch`, so the deploy now
repairs it on the Pi after upload.

### `state/config` is not the live runtime config yet

Migration preserves old board config under `/opt/yoyopod/state/config/`, but the
running app still reads the slot's bundled `./config`. Treat state config as a
preserved backup until the runtime config loader moves to the state-dir contract.

### Legacy hydration is now an explicit escape hatch

`release push` now expects an authoritative self-contained artifact by default.
If you re-use an older source-only slot, the command will refuse it unless you
explicitly opt into `--hydrate-on-target`.

## Field Notes From Bring-Up

The main issues discovered while getting this live were:

- `launch.sh` must call `yoyopod.main.main()` directly; `python -m yoyopod.main`
  is not a valid runtime entrypoint
- slot launch must require the slot-local `venv/bin/python`; silently falling back
  to a board-global interpreter reintroduces hidden runtime dependencies
- built slots must include the tracked repo `config/` tree
- the release live probe must not depend on reading only `manifest.json`; it has
  to confirm the active unit and active slot
- the root CLI entrypoint is too heavy for Pi-side deploy probes; use lighter
  subapps or shell checks
- native build caches are not portable across slot paths
- Windows transport needs a robust fallback when `rsync` closes unexpectedly

## Related Docs

- [docs/PI_DEV_WORKFLOW.md](PI_DEV_WORKFLOW.md)
- [docs/RELEASE_PROCESS.md](RELEASE_PROCESS.md)
- [docs/DEPLOYED_PI_DEPENDENCIES.md](DEPLOYED_PI_DEPENDENCIES.md)
- [rules/deploy.md](../rules/deploy.md)
