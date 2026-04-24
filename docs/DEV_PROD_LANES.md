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

The dev and prod app units conflict with each other. The CLI also stops the old
legacy `yoyopod-slot.service` when activating dev, so a migrated board does not
accidentally keep the previous prod service running.

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

Bootstrap installs the prod and dev lane folders plus their systemd units:

```bash
ssh <user>@<pi>
git clone <repo-url> /tmp/yoyopod-bootstrap
cd /tmp/yoyopod-bootstrap
sudo -E ./deploy/scripts/bootstrap_pi.sh
```

If you already have a published prod artifact:

```bash
sudo -E ./deploy/scripts/bootstrap_pi.sh --release-url=<artifact-url> --migrate
```

After bootstrap, prod release commands do not need the bootstrap checkout. Dev
commands do need `/opt/yoyopod-dev/checkout`; for a fresh board, seed it before
using `remote sync`:

```bash
sudo chown -R <user>:<user> /opt/yoyopod-dev
sudo -u <user> git clone <repo-url> /opt/yoyopod-dev/checkout
```

Then run `yoyopod remote setup` once to create `/opt/yoyopod-dev/venv`.

## Migrating an Existing Board

For a board that already has the old `~/yoyopod-core` checkout:

```bash
ssh <user>@<pi>
cd ~/yoyopod-core
sudo -E ./deploy/scripts/bootstrap_pi.sh --migrate
```

`--migrate` copies the old checkout into `/opt/yoyopod-dev/checkout` when the
dev checkout is empty, then removes stale `.venv`, `build`, and `logs` folders
from that copy. It also preserves old config/log files under prod state for
reference.

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
- Do not mutate prod release directories in place; publish a new version and
  flip `current`.
- Do not depend on `uv` on the Pi; dev uses `/opt/yoyopod-dev/venv`, prod slots
  carry their own runtime.
- Do not delete `/opt/yoyopod-prod/previous` before a normal prod update; it is
  the rollback target.
- Do not assume old `~/yoyopod-core` is the dev lane. The dev lane checkout is
  `/opt/yoyopod-dev/checkout`.
