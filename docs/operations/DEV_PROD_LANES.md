# Dev and Prod Lane Contract

yoyopod boards can keep two deployment lanes installed at the same time:

- **Dev lane**: mutable checkout for fast hardware testing from a PR branch.
- **Prod lane**: immutable slot/OTA runtime for packaged releases.

Only one app lane should be active at a time. The CLI lane switch commands stop
the opposite lane before starting the requested one.

## Paths

```text
/opt/yoyopod-dev/
|-- checkout/        # git checkout used by yoyopod target deploy
|-- state/           # dev-only runtime state
|-- logs/
|-- tmp/
`-- bin/

/opt/yoyopod-prod/
|-- releases/
|   `-- <version>/   # immutable release slot
|-- current -> releases/<version>
|-- previous -> releases/<version>
|-- state/           # prod-only persistent state
|-- tmp/
`-- bin/
```

The tracked default config lives in `deploy/pi-deploy.yaml`:

```yaml
project_dir: /opt/yoyopod-dev/checkout

lane:
  dev_root: /opt/yoyopod-dev
  dev_checkout: /opt/yoyopod-dev/checkout
  prod_root: /opt/yoyopod-prod

slot:
  root: /opt/yoyopod-prod
```

Per-board overrides still belong in `deploy/pi-deploy.local.yaml`.

## Services

- `yoyopod-dev.service` runs the mutable checkout from `/opt/yoyopod-dev/checkout`.
- `yoyopod-prod.service` runs `/opt/yoyopod-prod/current/bin/launch`.
- `yoyopod-prod-rollback.service` is triggered by prod service failure.
- `yoyopod-prod-ota.timer` and `yoyopod-prod-ota.service` are reserved for the OTA poller.

The dev and prod runtime units conflict with each other. Lane
activation stops the other lane and any unmanaged `yoyopod-runtime`
processes before starting the requested one.

Before changing lanes, run `yoyopod target mode status`. It reports the
active service for each lane and a summary of unrelated `yoyopod-*`
processes that may still own hardware.

## Lane Commands

Check state:

```bash
yoyopod target mode status
```

Activate dev for PR hardware testing:

```bash
yoyopod target mode activate dev
yoyopod target deploy --branch <branch>           # or --sha <commit>
```

`target deploy` always uses a CI-built artifact for the exact commit;
there is no dirty-tree fallback. Add `--clean-native` if branch
switching leaves stale native LVGL CMake caches.

Activate prod again:

```bash
yoyopod target mode activate prod
```

`yoyopod target release status` (prod slot status) returns in Round 3
of the CLI rebuild; see
[`../ROADMAP.md`](../ROADMAP.md). Until then, check prod
state directly via `systemctl status yoyopod-prod.service` over SSH.

`yoyopod target mode deactivate` is not yet ported; stop a lane
directly with `sudo systemctl stop yoyopod-dev.service` (or
`yoyopod-prod.service`) over SSH.

## Fresh Board Bootstrap

Bootstrap installs the prod and dev lane folders plus their systemd units.
Use the installer directly on the Pi; do not clone a bootstrap checkout:

```bash
ssh <user>@<pi>
curl -fsSL https://raw.githubusercontent.com/moustafattia/yoyopod-core/main/deploy/scripts/install_pi.sh | sudo -E bash -s --
```

If you already have a published prod artifact:

```bash
curl -fsSL https://raw.githubusercontent.com/moustafattia/yoyopod-core/main/deploy/scripts/install_pi.sh | sudo -E bash -s -- --release-url=<artifact-url>
```

For PR/testing a non-main installer, pin the source ref explicitly:

```bash
curl -fsSL https://raw.githubusercontent.com/moustafattia/yoyopod-core/<ref>/deploy/scripts/install_pi.sh | sudo env YOYOPOD_INSTALL_REF=<ref> bash -s --
```

After bootstrap, dev commands need `/opt/yoyopod-dev/checkout`. For a
fresh board, seed it before using `target deploy`:

```bash
sudo chown -R <user>:<user> /opt/yoyopod-dev
sudo -u <user> git clone <repo-url> /opt/yoyopod-dev/checkout
```

(`yoyopod target setup` for one-command Pi setup returns in a later
round of the CLI rebuild.)

## Migrating an Existing Board

For a board that already has the old `~/yoyopod-core` checkout:

```bash
ssh <user>@<pi>
curl -fsSL https://raw.githubusercontent.com/moustafattia/yoyopod-core/main/deploy/scripts/install_pi.sh | sudo -E bash -s -- --migrate
```

`--migrate` preserves old config/log files under prod state for reference, but
it does not copy the legacy checkout into the dev lane. After migration, treat
the old `~/yoyopod-core` checkout as an archive only; the live dev truth is
`/opt/yoyopod-dev/checkout`.

Populate the dev lane explicitly before using `target deploy`:

```bash
sudo chown -R <user>:<user> /opt/yoyopod-dev
sudo -u <user> git clone <repo-url> /opt/yoyopod-dev/checkout
```

Then activate the desired lane:

```bash
yoyopod target mode activate dev
```

or:

```bash
yoyopod target mode activate prod
```

Migration copies old `config/` and `logs/` into `/opt/yoyopod-prod/state/` for
reference. The running app still reads the config bundled into the active slot
or checkout, so merge any important local-only config drift into the repo before
publishing a prod slot.

## Pitfalls

- Do not run dev and prod runtime services together; they share
  hardware, audio, and the PID file contract.
- `target mode activate dev|prod` is the supported way to clean up
  unrelated `yoyopod-*` processes that may still own hardware.
- Do not mutate prod release directories in place; publish a new version
  and flip `current` (blocked until Round 3 of the CLI rebuild).
- Do not trust dev native build dirs after large branch switches; pass
  `--clean-native` to `yoyopod target deploy` to wipe LVGL CMake caches.
- Do not delete `/opt/yoyopod-prod/previous` before a normal prod
  update; it is the rollback target.
- Do not assume old `~/yoyopod-core` is the dev lane. The dev lane
  checkout is `/opt/yoyopod-dev/checkout`.

## Prod OTA Guard

The future prod OTA service should use this guard as an `ExecCondition`:

```ini
ExecCondition=/opt/yoyopod-prod/bin/prod-ota-guard.sh
```

The guard skips OTA work when `yoyopod-dev.service` is active or when
`yoyopod-prod.service` is not active. This keeps OTA from mutating prod state
while the board is intentionally in the dev lane.
