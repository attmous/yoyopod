# Slot Deploy (Prod Lane)

This is the operator guide for the prod slot/OTA lane. For the complete
dev/prod split, read [DEV_PROD_LANES.md](DEV_PROD_LANES.md) first.

Terminology: `remote release ...` means prod slot work. `remote sync` means dev
checkout work. Use `remote mode status` when you are unsure which lane owns the
hardware.

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

On the Pi, run the installer directly. Do not clone a bootstrap checkout:

```bash
curl -fsSL https://raw.githubusercontent.com/moustafattia/yoyopod-core/main/deploy/scripts/install_pi.sh | sudo -E bash -s --
```

The installer downloads the matching source payload, runs the board bootstrap,
and removes its installer workspace afterward.

If you already have a published artifact URL:

```bash
curl -fsSL https://raw.githubusercontent.com/moustafattia/yoyopod-core/main/deploy/scripts/install_pi.sh | sudo -E bash -s -- --release-url=<artifact-url>
```

The installer forwards first-deploy semantics to the bootstrap/release installer.

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

Prod OTA services must not run while the dev lane is active. Future OTA units
should use `/opt/yoyopod-prod/bin/prod-ota-guard.sh` as an `ExecCondition` so
systemd skips OTA work unless the prod lane owns the board.

## Migration Notes

For an old board with `~/yoyopod-core`, run:

```bash
curl -fsSL https://raw.githubusercontent.com/moustafattia/yoyopod-core/main/deploy/scripts/install_pi.sh | sudo -E bash -s -- --migrate
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
slot `config/`, not the preserved state copy. Migration does not seed
`/opt/yoyopod-dev/checkout` from the old checkout; clone the repo there
explicitly if you want to return to the dev lane.

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
- [DEPLOYED_PI_DEPENDENCIES.md](../hardware/DEPLOYED_PI_DEPENDENCIES.md)
