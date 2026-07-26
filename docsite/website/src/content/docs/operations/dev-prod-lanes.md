---
title: Dev/Prod Lanes
description: The two deploy lanes on a board — mutable dev checkout vs immutable prod slots — and the commands that switch them.
---

Every board hosts two lanes, **mutually exclusive** — only one runs at a
time, and lane-switch commands stop the other first (they share the
hardware, audio, and PID file).

| Lane | Nature | Runs |
| --- | --- | --- |
| **Dev** | mutable git checkout for fast hardware testing | `yoyopod-dev.service` → the checkout's built binaries |
| **Prod** | immutable versioned slots for packaged releases | `yoyopod-prod.service` → `/opt/yoyopod-prod/current/bin/launch` |

## The paths

```text
/opt/yoyopod-dev/{checkout, state, logs, tmp, bin}
/opt/yoyopod-prod/{releases/<version>, current -> releases/<v>,
                   previous -> releases/<v>, state, tmp, bin}
```

`previous` is the rollback target (`yoyopod-prod-rollback.service`
flips to it on prod failure) — **never delete it**. Tracked defaults
live in `deploy/pi-deploy.yaml`; per-board overrides in the gitignored
`pi-deploy.local.yaml`.

## Lane commands

```bash
yoyopod target mode status            # always check first
yoyopod target mode activate dev
yoyopod target deploy --branch <branch>
yoyopod target mode activate prod
```

`mode status` also reports stray `yoyopod-*` processes holding hardware
— `mode activate` cleans them up. To stop a lane outright (until
`mode deactivate` is ported): `sudo systemctl stop yoyopod-dev.service`.

## Fresh board bootstrap

Run the installer **on the Pi** (don't clone a bootstrap checkout):

```bash
curl -fsSL https://raw.githubusercontent.com/attmous/yoyopod/main/deploy/scripts/install_pi.sh | sudo -E bash -s --
# then seed the dev lane:
sudo chown -R <user>:<user> /opt/yoyopod-dev
sudo -u <user> git clone <repo-url> /opt/yoyopod-dev/checkout
yoyopod target mode activate dev
```

Migrating a board with an old `~/yoyopod-core` checkout: add
`--migrate` — it preserves the old config/logs for reference but does
**not** copy the legacy checkout into the dev lane. `~/yoyopod-core` is
archive; live truth is `/opt/yoyopod-dev/checkout`.

## Pitfalls

- Never run both lane services together.
- Never mutate a prod release dir in place — publish a new version and
  flip `current` (blocked until Round 3 anyway —
  [Roadmap](/product/roadmap/)).
- The running app reads config bundled into its active lane — merge
  local config drift into the repo before publishing a prod slot.
- After big branch switches, `--clean-native`.

The future OTA poller is guarded: `prod-ota-guard.sh` skips OTA whenever
the dev lane is active, so OTA can't mutate prod while a board is
intentionally in dev.

:::note[Canonical source]
Condensed from
[`docs/operations/DEV_PROD_LANES.md`](https://github.com/attmous/yoyopod/blob/main/docs/operations/DEV_PROD_LANES.md).
Prod slot publishing and `target release status` return in Round 3.
:::
