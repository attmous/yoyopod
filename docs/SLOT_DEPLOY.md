# Slot Deploy (Prod Lane)

This is the operator guide for the prod slot/OTA lane. For the complete
dev/prod split, read [DEV_PROD_LANES.md](DEV_PROD_LANES.md) first.

## Contract

- Prod slots live under `/opt/yoyopod-prod/releases/<version>/`.
- `/opt/yoyopod-prod/current` points at the active release.
- `/opt/yoyopod-prod/previous` points at the rollback release.
- `yoyopod-prod.service` runs `/opt/yoyopod-prod/current/bin/launch`.
- `yoyopod-prod-rollback.service` swaps `current` and `previous` after repeated prod failures.
- `deploy/scripts/install_release.sh` installs published artifacts directly into `/opt/yoyopod-prod`.
- `yoyopod remote release push`, `rollback`, `status`, and `install-url` do not require `uv` or a repo checkout on the Pi after bootstrap.
- `yoyopod remote release build-pi` still needs the dev checkout because it uses the Pi as an ARM build factory.

## Layout

```text
/opt/yoyopod-prod/
|-- releases/
|   |-- <version>/
|   |   |-- app/
|   |   |-- assets/
|   |   |-- bin/launch
|   |   |-- config/
|   |   |-- manifest.json
|   |   |-- runtime-requirements.txt
|   |   `-- venv/
|-- current -> releases/<version>
|-- previous -> releases/<version>
|-- bin/
|   |-- install-release.sh
|   `-- rollback.sh
`-- state/
    `-- tmp/
```

## Fresh Board Install

On the Pi, run bootstrap from any temporary checkout:

```bash
git clone <repo-url> /tmp/yoyopod-bootstrap
cd /tmp/yoyopod-bootstrap
sudo -E ./deploy/scripts/bootstrap_pi.sh
```

Bootstrap installs the prod and dev lane folders and systemd units. It does not
need the temporary checkout afterward unless you also want to use it as a dev
checkout.

If you already have a published artifact URL:

```bash
sudo -E ./deploy/scripts/bootstrap_pi.sh --release-url=<artifact-url>
```

The bootstrap script forwards first-deploy semantics to the installer.

## First Release

Build on the Pi and download the artifact:

```bash
uv run yoyopod remote release build-pi --output build/releases --channel dev
```

Push the first release:

```bash
uv run yoyopod remote release push build/releases/<version>.tar.gz --first-deploy
```

Or install a CI/GitHub-published artifact directly:

```bash
uv run yoyopod remote release install-url <artifact-url> --first-deploy
```

Verify:

```bash
uv run yoyopod remote release status
ssh <user>@<pi> 'systemctl status yoyopod-prod.service --no-pager -l'
```

Expected result:

- `current=<version>`
- `health=ok`
- `yoyopod-prod.service` is active

## Normal Prod Update

```bash
uv run yoyopod remote release build-pi --output build/releases --channel dev
uv run yoyopod remote release push build/releases/<version>.tar.gz
uv run yoyopod remote release status
```

Published artifact path:

```bash
uv run yoyopod remote release install-url <artifact-url>
uv run yoyopod remote release status
```

`release push` uploads the slot, repairs `bin/launch` permissions, runs
preflight, flips `current`/`previous`, restarts `yoyopod-prod.service`, and
performs a shell-only live probe against the active systemd PID and slot path.

## Rollback

Manual rollback:

```bash
uv run yoyopod remote release rollback
```

Check rollback state:

```bash
uv run yoyopod remote release status
ssh <user>@<pi> 'readlink -f /opt/yoyopod-prod/current && readlink -f /opt/yoyopod-prod/previous'
```

Automatic rollback uses:

- `OnFailure=yoyopod-prod-rollback.service`
- `/opt/yoyopod-prod/bin/rollback.sh`
- `systemctl reset-failed yoyopod-prod.service` before restart

## Migration Notes

For an old board with `~/yoyopod-core`, run:

```bash
cd ~/yoyopod-core
sudo -E ./deploy/scripts/bootstrap_pi.sh --migrate
```

Then either activate dev:

```bash
uv run yoyopod remote mode activate dev
```

or publish/activate prod:

```bash
uv run yoyopod remote release install-url <artifact-url> --first-deploy
uv run yoyopod remote mode activate prod
```

The migration preserves old `config/` and `logs/` under
`/opt/yoyopod-prod/state/` for reference. The live prod app reads the bundled
slot `config/`, not the preserved state copy. If `/opt/yoyopod-dev/checkout`
is empty, migration also seeds it from the old checkout and removes stale
`.venv`, `build`, and `logs` directories from that copy.

## Pitfalls Found During Bring-Up

- The live probe must verify the systemd service PID and active slot path, not
  just read `manifest.json`.
- Reusing a version must not mutate the active release in place; bump the
  version for every prod artifact.
- Source-only slots are legacy; the default prod path expects self-contained
  runtime artifacts.
- The Pi Zero is memory-constrained, so prod deploy probes avoid launching a
  second Python process after restart.
- Windows `scp` fallback may lose executable bits, so deploy repairs
  `bin/launch` after upload.
- Native build directories are path-sensitive; copy only built shims or rebuild.

## Related Docs

- [DEV_PROD_LANES.md](DEV_PROD_LANES.md)
- [PI_DEV_WORKFLOW.md](PI_DEV_WORKFLOW.md)
- [RELEASE_PROCESS.md](RELEASE_PROCESS.md)
- [DEPLOYED_PI_DEPENDENCIES.md](DEPLOYED_PI_DEPENDENCIES.md)
