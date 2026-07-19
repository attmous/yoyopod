---
title: Cloud & Provisioning
description: Backend, provisioning, and the device's cloud link.
---

*How a device gets an identity, a SIM, and a safe line home — the device's side of **yoyocloud**, the backend backbone.*

:::tip[Proposed — the ideal design]
This page mixes as-built fact (covered by the Sources note) with the target
design, written out in full so it can be adopted, adapted, or dropped.
Everything marked *Proposed* is neither implemented nor committed.
:::

## Overview

The backend backbone is named **yoyocloud**: it speaks MQTT with the
device, receives location and telemetry, and routes them to the yoyopod
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

*Proposed — the ideal design, not yet adopted.*

Today yoyocloud has one face: it talks MQTT with devices. In the target
design it grows a second face — the surface the yoyopod app consumes —
and the same strict division of labor extends to it: the app never talks
to a device directly, just as the device never talks to a dashboard
directly. Everything a parent sees or changes flows through yoyocloud,
which is the only place policy can be enforced honestly. The surface
owns seven things.

**Accounts and households.** A parent account belongs to a household; a
household owns devices and child profiles. This is the smallest possible
identity model: enough to know which parents may see which device, and
nothing more. Data minimalism is a design input, not an afterthought — a
child profile is a first name and an age band, never a behavioral
dossier (see [Privacy](/families/privacy/)).

**Device claiming and pairing.** The factory provisions `device_id` and
`device_secret`; a claim code delivered with the device lets a parent
bind it to their household during [first-time setup](/apps/setup/).
Claiming is what turns "a provisioned device" into "our device."
Unclaiming is a first-class operation, not a support ticket: it wipes
the household binding server-side and returns the device to a claimable
state, so resale and sibling hand-me-downs are ordinary flows.

**Whitelist storage — authoritative.** The approved-contacts whitelist
lives in yoyocloud as the single source of truth; parents edit it in the
yoyopod app, and yoyocloud syncs a copy down to the device so calls keep
working when the line home is down. The [Calling
Engine](/builders/software/voip-engine/) consumes the synced copy and
never accepts a contact that yoyocloud has not blessed.

**Help Agent profile storage.** Help Agents are created in the yoyopod
app — a topic area, a tone, boundaries, and a name — and their profiles
live in yoyocloud, synced to the device's Ask wheel. Crucially, the
age-appropriate content policy is enforced in yoyocloud on every
exchange, not only in the prompt, so a clever question cannot talk its
way past it. Transcripts are reviewable by parents, with a proposed
default retention of 30 days under parent control. See the
[Speech Engine](/builders/software/speech-engine/) for the device side of
this contract.

**Location ingestion and a live-ish location API.** Devices publish
location telemetry over MQTT; yoyocloud keeps the latest fix and a short
history, and the yoyopod app reads it through a live-ish API — the
backend half of [Locate](/apps/locate/). Live-ish is a promise, not a
euphemism: the API's shape should make real-time expectations
impossible to form.

| Option | What it means | Trade-off |
| --- | --- | --- |
| **REST pull + push nudge** | the app fetches the latest fix when opened; a push notification wakes it when a fresh fix is worth a look | **Recommended** — simplest, honest about live-ish, and cheapest on the device's battery and data budget |
| Persistent stream to the app (WebSocket-class) | the app holds an open channel and fixes stream in | implies a real-time promise we deliberately do not make, and adds always-on infrastructure for no product gain |

**Voice-note relay.** Push-to-talk voice notes between the device and
the yoyopod app relay through yoyocloud with the same store-and-forward
temperament as the rest of the link: notes queue while either end is
offline and deliver on reconnect. This is the backend half of
[Talk](/apps/talk/) and the reason [talking through
yoyopod](/families/talking/) never depends on both ends being awake at
once.

**Push notifications to the yoyopod app.** yoyocloud is the single
producer of pushes, delivered over the standard iOS and Android push
channels: a new voice note has arrived, a battery is critically low, a
device has come back online. Notifications inform parents; they never
nag them, and no notification ever originates from a Help Agent — agents
never initiate contact.

The API recommendation, consistent with the [App
Platform](/builders/software/apps/) page: the app-facing surface is
**REST + JSON plus push**, with contracts published as shared
`packages/` types so the app and backend cannot drift apart. MQTT
remains a device-side protocol only — the app never holds an MQTT
connection.

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

*Proposed — the ideal design, not yet adopted.* The build-vs-adopt
question the Overview leaves open deserves a written-out answer. Three
realistic shapes for yoyocloud:

| Option | What it looks like | Trade-off |
| --- | --- | --- |
| **(a) Thin custom API over proven parts** | a small custom service (e.g. in Rust, matching yoyocore's language) in front of a proven open-source MQTT broker (Mosquitto or EMQX class) and Postgres | **Recommended** — the contracts stay ours, the minimum of kid data is stored, and the attack surface stays small enough to actually audit |
| (b) Full open-source IoT platform (ThingsBoard-class) | adopt a platform that ships device registry, dashboards, and rule engine out of the box | fastest start, but a much heavier surface and a data model that is the platform's, not ours — the parent-facing contracts above would be bent to fit it |
| (c) Fully managed cloud IoT | a hyperscaler's managed IoT service handles the broker, registry, and scaling | least operations work, but the most lock-in and the hardest data-locality and data-minimalism questions for a product whose users are children |

The recommendation follows from the page's own logic: what is fixed is
the contract, and option (a) is the only shape in which every contract
on this page — MQTT topics, the whitelist as single source of truth, the
Help Agent policy enforcement point, the live-ish location API — remains
ours to define and ours to keep small.

## Open questions

- **Build-vs-adopt:** adopt option (a) — a thin custom API over a proven MQTT broker and Postgres — or trade contract ownership for a platform's faster start?
- **App-facing API:** confirm REST + JSON plus push as the yoyopod app's surface (MQTT stays device-side), consistent with the [App Platform](/builders/software/apps/) recommendation, or drop it for a streaming design?
- **Whitelist authority:** adopt yoyocloud as the single source of truth for approved contacts, with the device holding only a synced copy the [VoIP Engine](/builders/software/voip-engine/) consumes?
- **Help Agent data policy:** adopt the 30-day parent-controlled transcript retention default and the rule that content policy is enforced in yoyocloud, not only in the prompt?
- **Claim/unclaim model:** adopt factory secrets plus a parent claim code as the pairing story, with unclaiming as a first-class flow covering resale and sibling hand-me-downs?

:::note[Sources]
Condensed from [`docs/features/CLOUD_PROVISIONING_AND_BACKEND.md`](https://github.com/attmous/yoyopod/blob/main/docs/features/CLOUD_PROVISIONING_AND_BACKEND.md) and [`docs/features/CLOUD_VOICE_WORKER.md`](https://github.com/attmous/yoyopod/blob/main/docs/features/CLOUD_VOICE_WORKER.md), and the as-built docs site (`website/` in the repository): the cloud worker profile, the cloud provisioning and backend page, and the cloud voice worker runbook.
:::
