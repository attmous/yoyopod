---
title: Cloud Provisioning & Backend
description: How the device is provisioned, what it publishes over MQTT, and how backend commands reach the runtime.
---

The cloud domain is the device ↔ backend link. The mechanics live in the
[telegraph desk profile](/runtime/workers/cloud/); this page carries the
provisioning and contract view.

## The division of labor

- **The device** loads provisioned secrets, runs the MQTT client when
  provisioning is valid, publishes requested telemetry, receives backend
  commands, and persists an operator-visible status snapshot.
- **The backend/dashboard** own claiming, household/parent flows, and
  policy. The device never talks to the dashboard directly — it consumes
  provisioned secrets and the command channel.

## Provisioning

Identity is two runtime-only secrets — `device_id` + `device_secret` —
in `config/cloud/device.secrets.yaml` (fallback
`/etc/yoyopod/cloud/`). Both present → `provisioned`; neither →
`unprovisioned`; a partial pair → `invalid_provisioning`. Backend
settings (broker host/port/TLS/transport, status paths, battery report
interval) live in `cloud/backend.yaml`, all overridable via
`YOYOPOD_CLOUD_*` env vars.

## The MQTT contract

| Topic | Direction | Carries |
| --- | --- | --- |
| `yoyopod/{device_id}/evt` | device → backend | events + telemetry |
| `yoyopod/{device_id}/ack` | device → backend | command acknowledgements |
| `yoyopod/{device_id}/cmd` | backend → device | commands |

Worker protocol: the runtime sends explicit `cloud.publish_*` commands
(heartbeat, battery, connectivity, playback, generic event/telemetry)
and `cloud.ack`; the host emits `cloud.ready`, `cloud.snapshot`,
`cloud.command` (inbound, forwarded to the runtime), `cloud.error`,
`cloud.stopped`. The *runtime* decides what is telemetry-worthy — a
[house rule](/runtime/routing-and-policies/#everything-interesting-is-telegraphed);
the desk only transports.

## Implemented vs. intended

**Implemented:** battery, heartbeat, connectivity, generic event and
telemetry publishes, command ack, store-and-forward queueing while
offline.

**Configured or backend-supported but not fully wired:** HTTP/REST sync
(`api_base_url` is config-only — [gap #3](/runtime/gaps/)), location
telemetry, PTT start/finish events, richer backend command types beyond
fetch/config + generic routing. Treat these as the intended surface, not
the current one.

See [Remote Playback](/features/remote-playback/) for the fully-specified
command/ack/event contract that *is* live.

:::note[Canonical source]
Condensed from
[`docs/features/CLOUD_PROVISIONING_AND_BACKEND.md`](https://github.com/attmous/yoyopod/blob/main/docs/features/CLOUD_PROVISIONING_AND_BACKEND.md).
:::
