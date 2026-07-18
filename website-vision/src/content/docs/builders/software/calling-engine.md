---
title: Calling Engine
description: "Whitelist calling under yoyocore: the voip worker, liblinphone, and the switchboard contract."
---

*The platform capability behind Talk — calls that only family can place or receive.*

:::caution[Partially filled]
Sections marked *Placeholder* have no as-built content yet; everything else is condensed from the repository (see Sources at the bottom).
:::

## Overview

Whitelist calls and voice messages are pillar one of V1 “Daylight”: approved contacts only, because reliable reachability is one of the two trust anchors the whole product rests on. The Calling Engine is where that pillar becomes software. Inside yoyocore it takes the form of the voip worker — the as-built docs call it "the switchboard" — which owns the entire communication surface: SIP registration, call control, text and voice-note messaging, and call history. The family-facing experience it powers is described at [Talk](/apps/talk/); how the worker sits among its peers is described in the [architecture overview](/builders/software/architecture/).

## Key components

**The voip worker (`yoyopod-voip-host`).** At roughly 5,600 lines it is the largest worker in yoyocore, and the only one gated behind a cargo feature (`native-liblinphone`) — the binary refuses to start without it. Configuration is pushed, not read locally: a `voip.configure` command composed from the calling, secrets, messaging, and hardware-audio config files, with secrets redacted on every log path.

**liblinphone, in-process.** The worker wraps a native liblinphone core through a hand-rolled dlopen FFI shim (`yoyopod_liblinphone_*` C ABI). The library is dynamically loaded at runtime, all shim state lives behind a single global mutex, and one-core-per-process is enforced by construction. Call and capture audio go through ALSA (WM8960 defaults — see [audio hardware](/builders/hardware/audio/)), with `aplay` and `ffplay` as playback helpers.

**Policy stays in yoyocore's runtime, not the worker.** The switchboard only reports. Its `incoming_call` event is what triggers the runtime's canvas preemption and the pause-the-music house rule — the worker itself decides nothing about what the rest of the device does.

### Whitelist enforcement

*Placeholder — no as-built content yet.*

- Where the whitelist authoritatively lives — on the device, in yoyocloud, or mirrored in both — is an open question below.
- How parent edits in [the yoyopod app](/apps/parent-app/) propagate to the device's calling config.
- What the device does when the whitelist is unreachable or stale.

### Voice notes

*Placeholder — no as-built content yet.*

- The worker already exposes a wire-level voice-note surface (record/send/playback commands and an idle → recording → recorded → sending session FSM), but the family-facing voice-note experience is not built yet.
- How voice notes appear in [Talk](/apps/talk/) and in [the yoyopod app](/apps/parent-app/).

## Interfaces & contracts

The worker speaks a contract of 19 commands and 12 events. Commands group into lifecycle (`configure`, `health`, `register`, `unregister`, `shutdown`), calls (`dial`, `answer`, `reject`, `hangup`, `set_mute`), messaging (`send_text_message`, `mark_call_history_seen`), and the voice-note set. Events include `ready`, `snapshot`, `registration_changed`, `incoming_call`, `call_state_changed`, `backend_stopped`, and the message-delivery family.

Two contract details carry real product weight. The registration FSM tracks a `recovery_pending` flag so that a re-registration after a failure is reported as *recovered*, not merely *registered* — the runtime and telemetry can tell a clean start from a comeback, which matters when reachability is the promise. And calls move through thirteen states, with a backend stop clearing any active call.

The boundary with the [Voice & Ask Engine](/builders/software/voice-ask/) follows the wire: voice-note *capture* lives here under `voip.*`, while Ask-flow speech is the interpreter's job under `voice.*`. One operational note: the backend polls liblinphone at a 20 ms default interval — starving that loop delays call state.

## Today vs. target

Today, the worker is real: in-process liblinphone, the SIP lifecycle, call control, and the messaging store (a 200-entry persistent JSON store with per-contact unread summaries) all exist as described above. What is honestly incomplete is end-to-end validation on hardware: the staged on-device validation stages for VoIP and cloud voice (`yoyopod-on-pi validate {voip, cloud-voice}`) are stubs that exit with an error, flagged in the as-built roadmap as a Round-2 follow-up of the staged CLI rebuild. Until that lands, call validation on a real device is a manual affair.

The target is the full Talk promise: calls and voice messages that only family can place or receive, with whitelist enforcement architected end to end (the placeholder above) and validated automatically on hardware. The [runtime guide](/builders/software/runtime/) covers how workers like this one are supervised along the way.

## Open questions

- Where does the whitelist live authoritatively — on the device, in yoyocloud, or both — and which side wins on conflict?
- When does the `yoyopod-on-pi validate voip` stage get filled in, and what does a passing end-to-end call check assert?
- Given the wire-level voice-note surface already in the worker, what is the committed family-facing shape of voice notes for V1 “Daylight”?

:::note[Sources]
Condensed from [`docs/product/PRODUCT_DEFINITION.md`](https://github.com/attmous/yoyopod/blob/main/docs/product/PRODUCT_DEFINITION.md) and the as-built docs site (website/ in the repository): the VoIP switchboard worker page, the product definition page, and the roadmap honesty page.
:::
