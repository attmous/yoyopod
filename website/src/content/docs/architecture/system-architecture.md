---
title: System Architecture
description: The runtime supervisor, per-domain worker hosts, and the operator CLI.
---

:::note[Canonical source]
This page is a summary. The authoritative document is
[`docs/architecture/SYSTEM_ARCHITECTURE.md`](https://github.com/attmous/yoyocore/blob/main/docs/architecture/SYSTEM_ARCHITECTURE.md)
in the repository.
:::

On the device, a single supervisor binary — `yoyopod-runtime` — spawns and
supervises one worker host per domain: UI (`yoyopod-ui-host`), media, VoIP,
network, cloud, power, and speech. Hosts talk to the runtime over a
stdin/stdout line protocol using shared envelope types from
`device/protocol`. On the development machine, the Rust operator CLI
(`yoyopod`) orchestrates builds, deploys, and device operations. The
architecture document describes this topology, the responsibilities of each
host, and the boundaries between them.
