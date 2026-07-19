---
title: VoIP Engine
description: "Whitelist calling under yoyocore: the voip worker, liblinphone, and the switchboard contract."
---

*The platform capability behind Talk — calls that only family can place or receive.*

:::tip[Proposed — the ideal design]
This page mixes as-built fact (covered by the Sources note) with the target
design, written out in full so it can be adopted, adapted, or dropped.
Everything marked *Proposed* is neither implemented nor committed.
:::

## Overview

Whitelist calls and voice messages are pillar one of V1 “Daylight”: approved contacts only, because reliable reachability is one of the two trust anchors the whole product rests on. The VoIP Engine is where that pillar becomes software. Inside yoyocore it takes the form of the voip worker — the as-built docs call it "the switchboard" — which owns the entire communication surface: SIP registration, call control, text and voice-note messaging, and call history. The family-facing experience it powers is described at [Talk](/apps/talk/); how the worker sits among its peers is described in the [architecture overview](/builders/software/architecture/).

## Key components

**The voip worker (`yoyopod-voip-host`).** At roughly 5,600 lines it is the largest worker in yoyocore, and the only one gated behind a cargo feature (`native-liblinphone`) — the binary refuses to start without it. Configuration is pushed, not read locally: a `voip.configure` command composed from the calling, secrets, messaging, and hardware-audio config files, with secrets redacted on every log path.

**liblinphone, in-process.** The worker wraps a native liblinphone core through a hand-rolled dlopen FFI shim (`yoyopod_liblinphone_*` C ABI). The library is dynamically loaded at runtime, all shim state lives behind a single global mutex, and one-core-per-process is enforced by construction. Call and capture audio go through ALSA (WM8960 defaults — see [audio hardware](/builders/hardware/audio/)), with `aplay` and `ffplay` as playback helpers.

**Policy stays in yoyocore's runtime, not the worker.** The switchboard only reports. Its `incoming_call` event is what triggers the runtime's canvas preemption and the pause-the-music house rule — the worker itself decides nothing about what the rest of the device does.

### Whitelist enforcement

*Proposed — the ideal design, not yet adopted.*

The whitelist is the load-bearing wall of the Talk promise, so the ideal design treats it the way load-bearing walls are treated: one authoritative copy, mirrored where it is needed, enforced in more than one place, and fail-closed everywhere.

**Where the list lives.** The authoritative whitelist lives in yoyocloud, and it is edited in exactly one place: [the yoyopod app](/apps/parent-app/), behind the parent's account. The device holds a mirrored copy — a cache of the last list yoyocloud confirmed — and enforcement always runs against that local mirror, so a dead network never turns enforcement off. Three architectures were considered:

| Option | How it works | Trade-off |
| --- | --- | --- |
| Device-authoritative | The list lives on the device; the yoyopod app edits it by talking to the device directly. | Fully offline-capable, but parent edits require a reachable device, and a lost or reset device loses the list. |
| **Cloud-authoritative + device cache (recommended)** | yoyocloud holds the single source of truth; the device mirrors it and enforces locally against the cached copy. | Parent edits land even when the device is offline; the device keeps enforcing the last-known list without the cloud. |
| Dual-authoritative | Both sides writable, with bidirectional sync and merge rules. | Conflict-resolution machinery that a parent-edited contact list simply does not need. |

The recommendation is cloud-authoritative with a device cache: it gives parents an edit surface that always works and gives the device an enforcement surface that never depends on connectivity — the only combination that keeps both halves of the promise.

**Enforced at two layers.** A single enforcement point is a single bug away from a stranger's call ringing on a child's device, so the ideal design enforces the list twice, independently:

1. **The dialing layer.** The VoIP Engine refuses to place an outbound call to any identity not on the mirrored list, and rejects inbound calls from non-whitelist identities before the device ever rings — no missed-call trace, no notification, nothing for the child to see. This check lives in the voip worker's call path itself, not in whatever UI happens to sit above it.
2. **The contact-first UI.** The canvas has no dial pad and no address field. [Talk](/apps/talk/) renders whitelisted contacts and only whitelisted contacts — calling a stranger is not merely blocked, it is unexpressible in the interface. The UI layer never even learns that non-whitelist identities exist.

If the SIP infrastructure ends up self-hosted (see [Today vs. target](#today-vs-target) below), the SIP server in yoyocloud becomes a natural third enforcement point: the server declines to route calls outside a family's whitelist, which makes the promise hold even against a hypothetically compromised device.

**How parent edits propagate.** An edit in the yoyopod app writes to yoyocloud first; yoyocloud then pushes the updated list to the device as a cloud command over the device link, and the device acknowledges once the mirror is applied. The app shows honest state: *pending* until the ack arrives, *applied* after. If the device is offline, the command queues in yoyocloud's store-and-forward path — the same behavior the [cloud backbone](/builders/software/cloud/) uses for everything else — and applies on reconnect. This matters for the removal case especially: a parent removing a contact should see, truthfully, whether the device has heard about it yet.

**Stale is not open.** A stale cache enforces the last-known list — never more, never less. An unreachable cloud, a failed sync, a corrupt update: none of these ever widen the list. And if a device has never synced a whitelist at all (a fresh unit mid-[setup](/apps/setup/)), the empty list is enforced, meaning no calls in either direction until the first sync lands. Fail-closed, always.

### Voice notes

*Proposed — the ideal design, not yet adopted.*

The worker already exposes a wire-level voice-note surface (record/send/playback commands and an idle → recording → recorded → sending session FSM), so the question is not whether the device can capture a voice note — it is how a note travels. Two transports were considered:

| Option | How it works | Trade-off |
| --- | --- | --- |
| In-band SIP messaging | The note rides the existing SIP path, device to device, using the worker's wire surface directly. | No new infrastructure, but both ends must be reachable at once — which defeats the point of leaving a message. |
| **Store-and-forward via yoyocloud (recommended)** | The device uploads the note to yoyocloud; yoyocloud holds it and delivers when each recipient is reachable. | One more cloud surface to run, but delivery works exactly when live calls don't. |

Store-and-forward is the recommendation because a voice note exists precisely for the moments a live call can't happen — a transport that requires simultaneous reachability solves the wrong problem.

**The flow.** The child holds the button to record — the same hold-to-talk grammar as everywhere else on the device ([using the button](/families/using-the-button/)); release ends the note. The device uploads the note over the cloud link to yoyocloud, which delivers it to the chosen whitelisted contact: either [the yoyopod app](/apps/parent-app/) or another yoyopod in the family. On the receiving yoyopod, the note appears in [Talk](/apps/talk/) as an unread item and plays through the speaker on demand — notes never auto-play. The whitelist governs voice notes exactly as it governs calls, at the same two layers: only whitelisted contacts can be chosen as recipients, and inbound notes from non-whitelist identities are refused by yoyocloud before they reach a device.

**Offline behaves like everything else.** If the device is offline when the note is recorded, the note queues locally and uploads when the link returns — consistent with the cloud link's store-and-forward behavior described on the [cloud backbone page](/builders/software/cloud/). Inbound notes for an offline device are held in yoyocloud and delivered on reconnect. The child's experience is "sent" the moment recording ends; the plumbing catches up.

**Proposed limits (defaults, not commitments).** A 60-second cap per note keeps notes note-shaped and bounds storage; recorded audio is compressed on-device before upload, keeping a maximum-length note well under a megabyte. Delivered notes are removed from yoyocloud once every recipient has received them; undelivered notes expire after 30 days. Notes are visible to parents in the yoyopod app under the same review model as the rest of the [parental controls](/families/parental-controls/) — family voice messages are family-visible by design, which is stated plainly rather than hidden.

## Interfaces & contracts

The worker speaks a contract of 19 commands and 12 events. Commands group into lifecycle (`configure`, `health`, `register`, `unregister`, `shutdown`), calls (`dial`, `answer`, `reject`, `hangup`, `set_mute`), messaging (`send_text_message`, `mark_call_history_seen`), and the voice-note set. Events include `ready`, `snapshot`, `registration_changed`, `incoming_call`, `call_state_changed`, `backend_stopped`, and the message-delivery family.

Two contract details carry real product weight. The registration FSM tracks a `recovery_pending` flag so that a re-registration after a failure is reported as *recovered*, not merely *registered* — the runtime and telemetry can tell a clean start from a comeback, which matters when reachability is the promise. And calls move through thirteen states, with a backend stop clearing any active call.

The boundary with the [Speech Engine](/builders/software/speech-engine/) follows the wire: voice-note *capture* lives here under `voip.*`, while Ask-flow speech is the interpreter's job under `voice.*`. One operational note: the backend polls liblinphone at a 20 ms default interval — starving that loop delays call state.

## Today vs. target

Today, the worker is real: in-process liblinphone, the SIP lifecycle, call control, and the messaging store (a 200-entry persistent JSON store with per-contact unread summaries) all exist as described above. What is honestly incomplete is end-to-end validation on hardware: the staged on-device validation stages for VoIP and cloud voice (`yoyopod-on-pi validate {voip, cloud-voice}`) are stubs that exit with an error, flagged in the as-built roadmap as a Round-2 follow-up of the staged CLI rebuild. Until that lands, call validation on a real device is a manual affair.

The target is the full Talk promise: calls and voice messages that only family can place or receive, with whitelist enforcement architected end to end (the placeholder above) and validated automatically on hardware. [The yoyocore Runtime](/builders/software/runtime/) covers how workers like this one are supervised along the way.

*Proposed — the ideal design, not yet adopted.* The target also requires deciding what the voip worker registers *against* — the SIP infrastructure decision. Nothing is committed today; the realistic options are:

| Option | What it buys | What it costs |
| --- | --- | --- |
| Managed VoIP provider | The fastest path to working calls; NAT traversal, media relay, and uptime are someone else's problem. | Call signaling and metadata for every family transit a third party, and registration semantics are whatever the provider offers. |
| **Self-hosted open-source SIP server in yoyocloud (recommended)** | Signaling, metadata, and media relay stay inside infrastructure yoyopod controls, and the server becomes a third whitelist enforcement point. | Real operations burden: running a well-known open-source SIP server plus a TURN/media relay, and owning their monitoring and upgrades. |
| Hybrid (self-hosted signaling, managed media relay) | Control over registration and routing without owning the relay fleet. | Media still transits a third party, and two vendors' failure modes to reason about. |

Self-hosting is the recommendation because the [privacy promise](/families/privacy/) and server-side whitelist enforcement both argue for infrastructure yoyopod controls, and family-only calling keeps traffic modest enough that self-hosting stays tractable. A managed provider remains an acceptable bridge while the self-hosted stack is stood up — but the decision should be made before the `validate voip` stage is built, since that check asserts against whichever infrastructure is chosen.

## Open questions

- **Whitelist authority.** Adopt cloud-authoritative with a device cache (the recommendation above), or keep the list device-authoritative and accept that parent edits require a reachable device?
- **Enforcement depth.** Adopt two-layer enforcement (dialing layer plus contact-first UI) as a hard invariant — with the SIP server as a third layer if self-hosted — or accept a single enforcement point for V1 “Daylight”?
- **Voice-note transport.** Adopt store-and-forward via yoyocloud, or build the family-facing experience directly on the in-band wire surface the worker already exposes?
- **SIP infrastructure.** Self-hosted open-source SIP server, managed provider, or hybrid — and does this get decided before the `yoyopod-on-pi validate voip` stage is filled in, so the check asserts against the real target?
- **Voice-note limits.** Adopt the proposed defaults (60-second cap, 30-day undelivered expiry, parent-visible notes), or set different retention and visibility rules before anything ships?

:::note[Sources]
Condensed from [`docs/product/PRODUCT_DEFINITION.md`](https://github.com/attmous/yoyopod/blob/main/docs/product/PRODUCT_DEFINITION.md) and the as-built docs site (website/ in the repository): the VoIP switchboard worker page, the product definition page, and the roadmap honesty page.
:::
