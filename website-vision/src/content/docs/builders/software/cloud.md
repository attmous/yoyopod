---
title: Cloud & Provisioning
description: Backend, provisioning, and the device's cloud link.
---

*How a device gets an identity, a SIM, and a safe line home — the device's side of **yoyocloud**, the backend backbone.*

:::caution[Partially filled]
Sections marked *Placeholder* have no as-built content yet; everything else is condensed from the repository (see Sources at the bottom).
:::

## Overview

The backend backbone is named **yoyocloud**: it speaks MQTT with the
device, receives location and telemetry, and routes them to the parent
app. Whether we build yoyocloud ourselves or adopt an open-source solution
is a deliberately open decision — what is fixed is the contract on this
page. The cloud domain is the device ↔ backbone link, owned by the
device's cloud worker. Identity is two runtime-only secrets — `device_id`
plus `device_secret` — and the line home is MQTT. The division of labor is
strict: the device loads provisioned secrets, publishes requested
telemetry, receives backend commands, and persists an operator-visible
status snapshot; the backend/dashboard own claiming, household and parent
flows, and policy. The device never talks to a dashboard directly.

The link's defining behavior is **store-and-forward**: publishes queue
while disconnected (max 32, drop-oldest) and flush on reconnect. On a
device that lives on cellular, "the line is down" is weather, not
failure.

## Key components

| Component | What it is |
| --- | --- |
| Cloud worker | `yoyopod-cloud-host`: an MQTT client (tcp / tls / ws / wss) on its own thread, persisting status to `data/cloud/status.json` |
| Provisioning | both secrets present → `provisioned`; neither → `unprovisioned`; a partial pair → `invalid_provisioning`. The worker runs and queues regardless — provisioning gates what the backend accepts, not what the device tries |
| Cloud voice worker | the OpenAI-backed STT/TTS/Ask behind the Ask screen, enabled via the systemd lane environment file; the API key is a device secret, and with cloud TTS enabled the device speaks with an AI-generated voice and must be disclosed as such |

### Parent-facing backend surface

*Placeholder — no as-built content yet.*

- Parent-app-facing backend surface (future)
- The contracts a future parent app consumes, via planned shared `packages/` (see [App Platform](/builders/software/apps/))

## Interfaces & contracts

| Topic | Direction | Carries |
| --- | --- | --- |
| `yoyopod/{device_id}/evt` | device → backend | events + telemetry |
| `yoyopod/{device_id}/ack` | device → backend | command acknowledgements |
| `yoyopod/{device_id}/cmd` | backend → device | commands |

The runtime decides what is telemetry-worthy and sends explicit
`publish_*` commands (heartbeat, battery, connectivity, playback, generic
event/telemetry); the worker never invents messages. Inbound backend
commands are forwarded to the runtime, which routes them and answers with
an ack. Connectivity and telemetry publishes are deduplicated against
their last value; battery reports are throttled to a configured interval.
Location reporting stays live-ish by design, never real-time.

## Today vs. target

- **Implemented today:** battery, heartbeat, connectivity, generic event and telemetry publishes, command ack, and store-and-forward queueing while offline.
- **Configured or intended but not wired:** HTTP/REST sync — `api_base_url` is config-only and the REST surface does not exist yet; MQTT is the only live transport. Also intended-not-current: location telemetry, PTT start/finish events, and richer backend command types.
- Cloud voice degrades gracefully: a missing or invalid API key leaves local controls working, with the Ask screen's offline state as the visible result. Automated on-device voice validation is paused until a Round-2 follow-up.
- Target: provisioning documented end to end, factory through family setup, plus the parent-facing backend surface above — entirely future work.

## Open questions

- TODO: yoyocloud build-vs-adopt — which open-source backends are candidates?
- TODO: which provisioning steps happen at the factory vs. in a parent's hands?
- TODO: broker topology for the MQTT link — managed service or self-hosted (TBD)?
- TODO: how does a device change families — resale, hand-me-down to a sibling?

:::note[Sources]
Condensed from [`docs/features/CLOUD_PROVISIONING_AND_BACKEND.md`](https://github.com/attmous/yoyopod/blob/main/docs/features/CLOUD_PROVISIONING_AND_BACKEND.md) and [`docs/features/CLOUD_VOICE_WORKER.md`](https://github.com/attmous/yoyopod/blob/main/docs/features/CLOUD_VOICE_WORKER.md), and the as-built docs site (`website/` in the repository): the cloud worker profile, the cloud provisioning and backend page, and the cloud voice worker runbook.
:::
