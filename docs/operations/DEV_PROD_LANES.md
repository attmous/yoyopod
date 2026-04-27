# Dev and Prod Lane Contract

YoYoPod boards can keep two deployment lanes installed at the same time:

- **Dev lane**: mutable checkout for fast hardware testing from a PR branch.
- **Prod lane**: immutable slot/OTA runtime for packaged releases.

Only one app lane should be active at a time. The CLI lane switch commands stop
the opposite lane before starting the requested one.

## Paths

```text
/opt/yoyopod-dev/
|-- checkout/        # git checkout used by remote sync, validate, setup
|-- venv/            # checkout virtualenv; no uv dependency on the Pi
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
venv: /opt/yoyopod-dev/venv

lane:
  dev_root: /opt/yoyopod-dev
  dev_checkout: /opt/yoyopod-dev/checkout
  dev_venv: /opt/yoyopod-dev/venv
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

The dev and prod app units conflict with each other. Lane activation also
disables and removes unsupported old `yoyopod-slot.service` and
`yoyopod@<user>.service` unit files, removes `/etc/default/yoyopod`, and stops
unmanaged `python ... yoyopod.py` app processes before starting the requested
lane.

Before changing lanes, run `yoyopod remote mode status`. It reports:

- `active_lane`: `dev`, `prod`, `legacy`, `manual-process`, `conflict`, or `none`.
- `legacy_units`: unsupported old `yoyopod@*.service` or `yoyopod-slot.service`
  units that can still own hardware.
- `manual_processes`: ad hoc `python ... yoyopod.py` or `yoyopod.main` processes.
- `prod_ota_conflict`: whether prod OTA is active while dev owns the board.
- `conflict_reasons`: the active conflict sources.

## Lane Commands

Check state:

```bash
uv run yoyopod remote mode status
```

Activate dev for PR hardware testing:

```bash
uv run yoyopod remote mode activate dev
uv run yoyopod remote sync --branch <branch>
```

If branch switching leaves stale native CMake caches, force a clean native
rebuild during sync:

```bash
uv run yoyopod remote sync --branch <branch> --clean-native
```

Activate prod again:

```bash
uv run yoyopod remote mode activate prod
uv run yoyopod remote release status
```

Deactivate a lane without enabling the other:

```bash
uv run yoyopod remote mode deactivate dev
uv run yoyopod remote mode deactivate prod
```

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

After bootstrap, prod release commands do not need a repo checkout. Dev commands
do need `/opt/yoyopod-dev/checkout`; for a fresh board, seed it before using
`remote sync`:

```bash
sudo chown -R <user>:<user> /opt/yoyopod-dev
sudo -u <user> git clone <repo-url> /opt/yoyopod-dev/checkout
```

Then run `yoyopod remote setup` once to create `/opt/yoyopod-dev/venv`.

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

Populate the dev lane explicitly before using `remote sync`:

```bash
sudo chown -R <user>:<user> /opt/yoyopod-dev
sudo -u <user> git clone <repo-url> /opt/yoyopod-dev/checkout
uv run yoyopod remote setup
```

Then activate the desired lane:

```bash
uv run yoyopod remote mode activate dev
```

or:

```bash
uv run yoyopod remote mode activate prod
```

Migration copies old `config/` and `logs/` into `/opt/yoyopod-prod/state/` for
reference. The running app still reads the config bundled into the active slot
or checkout, so merge any important local-only config drift into the repo before
publishing a prod slot.

## Pitfalls

- Do not run dev and prod app services together; they share hardware, audio, and
  the PID file contract.
- Do not ignore `active_lane=conflict`; `remote mode activate dev|prod` is the
  supported cleanup path for legacy/manual owners.
- Do not mutate prod release directories in place; publish a new version and
  flip `current`.
- Do not depend on `uv` on the Pi; dev uses `/opt/yoyopod-dev/venv`, prod slots
  carry their own runtime.
- Do not trust dev native build dirs after large branch switches; use
  `yoyopod remote sync --clean-native` or run `yoyopod build clean-native` inside
  the dev checkout before rebuilding.
- Do not delete `/opt/yoyopod-prod/previous` before a normal prod update; it is
  the rollback target.
- Do not assume old `~/yoyopod-core` is the dev lane. The dev lane checkout is
  `/opt/yoyopod-dev/checkout`.

## Prod OTA Guard

The future prod OTA service should use this guard as an `ExecCondition`:

```ini
ExecCondition=/opt/yoyopod-prod/bin/prod-ota-guard.sh
```

The guard skips OTA work when `yoyopod-dev.service` is active or when
`yoyopod-prod.service` is not active. This keeps OTA from mutating prod state
while the board is intentionally in the dev lane.
