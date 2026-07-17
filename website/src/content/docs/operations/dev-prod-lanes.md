---
title: Dev/Prod Lanes
description: The two deployment lanes on the device and how to switch between them.
---

:::note[Canonical source]
This page is a summary. The authoritative document is
[`docs/operations/DEV_PROD_LANES.md`](https://github.com/attmous/yoyopod/blob/main/docs/operations/DEV_PROD_LANES.md)
in the repository.
:::

Each device carries two lanes: a mutable dev lane (a git checkout at
`/opt/yoyopod-dev/checkout` run by `yoyopod-dev.service`) and an immutable
prod lane (versioned slots under `/opt/yoyopod-prod` with `current`/
`previous` symlinks and a rollback unit). The document explains lane
activation via `yoyopod target mode activate`, the systemd units involved,
and the guarantees each lane provides.
