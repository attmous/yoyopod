---
title: Security Model
description: Identity, whitelisting, transport, and updates.
---

*The security posture a parent-managed kids device must be able to defend.*

:::tip[Proposed — the ideal design]
This page is the target design, written out in full so it can be adopted,
adapted, or dropped. Everything marked *Proposed* is neither implemented
nor committed; the as-built facts it builds on are cited in the Sources
note at the bottom.
:::

## Overview

*Proposed — the ideal design, not yet adopted.*

yoyopod's security model starts from an uncomfortable framing: this is a device carried by a kid, managed by a parent, and reachable over 4G. Every design decision on this page answers one question — *what does that combination have to defend against?* The answer is not "everything"; it is a short, specific list: strangers reaching the child, the device being lost or resold, the cloud being breached, an update being tampered with, and anyone — including us — hearing more of a child's voice than the parent agreed to.

The first line of defense is what the hardware refuses to have, by design: no camera, no browser, no app store. A capability that does not exist cannot be exploited, misconfigured, or socially engineered. The same logic extends into software: security here follows the [product principles](/company/principles/) rather than sitting beside them. Local-first is not only a resilience stance, it is a privacy stance — audio that is played from the device, and interactions that never leave the canvas, produce no data to protect. What we refuse to build is documented at [What we are not](/company/what-we-are-not/).

Where data must exist, the rule is minimization by design. This is a European product handling children's data, which puts it in the strictest tier of GDPR: collect the minimum, retain it briefly, give the parent the controls, and be able to show all three. The proposal is to host all yoyocloud data in the EU, state retention windows publicly, and treat "we cannot answer that question about your child because we never stored the data" as the preferred answer. The family-facing version of this promise lives at [Privacy](/families/privacy/).

## Key components

*Proposed — the ideal design, not yet adopted.*

### Device identity

Today, a device authenticates to yoyocloud with a `device_id` and a `device_secret` — a shared-secret scheme that works, but makes the cloud's credential store a single high-value target and gives us no cryptographic story for "this device is provably itself."

The proposed target is a per-device keypair with mutual TLS: each device holds a private key generated or injected at provisioning time, and presents a client certificate when it connects. yoyocloud then authenticates the device at the transport layer, before any application message is parsed, and a breach of the cloud's database leaks no reusable device credentials — only public keys.

| Option | How it works | Trade-off |
| --- | --- | --- |
| Keep `device_id` + `device_secret` | Shared secret checked by yoyocloud on connect | Simplest; but secrets are reusable if the cloud store leaks, and rotation is a bespoke protocol we must build and audit ourselves |
| **mTLS client certificates** | Per-device keypair; certificate presented in the TLS handshake; yoyocloud runs a small private CA | **Recommended: it moves authentication into a boring, well-audited layer (TLS), makes stolen server data useless for impersonation, and mainstream MQTT brokers support it out of the box.** |
| Hardware-backed keys (secure element / TPM) | Private key generated inside a tamper-resistant chip, never extractable | Strongest; but adds BOM cost and provisioning complexity that is hard to justify before a product board exists |

The sensible sequencing is mTLS in software for V0 “Dawn”, with the certificate issuance flow designed so that a hardware-backed key on a V1 “Daylight” product board slots in without changing the cloud side.

### Signed updates over the slot concept

The update path builds on the slot concept that already exists in the platform: two OS slots (A/B), an update written to the inactive slot, a reboot into it, and automatic rollback if the new slot fails to come up healthy. That mechanism is a reliability feature today; the proposal is to make it a security feature by requiring that **every update — the yoyoOS image and the yoyocore application alike — is signed, and the device verifies the signature before writing a single byte to a slot**.

Concretely: release artifacts are signed in CI with an offline-protected key; the device ships with the corresponding public key baked into the image; an unsigned or wrongly-signed update is rejected and reported, never installed. Combined with A/B rollback, this gives two independent guarantees — a tampered update cannot be installed, and a *bad* signed update cannot brick the device. Well-established open-source OTA frameworks for embedded Linux implement exactly this pattern; the proposal is to adopt one rather than build the machinery ourselves.

### Secret provisioning

Device secrets — today the `device_secret`, tomorrow the private key — are injected at provisioning time and live only on the device and (as public material or hashes) in yoyocloud. They are never present in tracked configuration, which is consistent with the secret boundary the configuration system already draws: config that describes the device is versioned; material that *authenticates* the device is not, ever. The proposed factory flow is: the provisioning station generates the keypair, submits a certificate signing request to the private CA, writes the signed certificate and key to a protected partition, and records only the public certificate centrally. No secret ever transits a spreadsheet, a repo, or a support ticket.

### Parent account security

The parent's account in the yoyopod app is the device's remote control — whoever holds it controls the whitelist, the Help Agents, and live-ish location. It deserves the same rigor as the device identity.

| Option | Trade-off |
| --- | --- |
| Password + optional 2FA | Familiar; but the weakest parents' password becomes the weakest link to their child's device |
| **Passkeys (platform authenticators)** | **Recommended: phishing-resistant by construction, nothing for a parent to invent or reuse, and native on both iOS and Android where the yoyopod app lives.** |
| Sign-in with Apple / Google only | Low friction; but ties a kid's device to a third-party account and its recovery policies |

Passkeys as the default, with a carefully designed recovery path (a second registered device or a printed recovery code from [setup](/apps/setup/)), is the proposed stance. Account recovery is the real attack surface for any authentication scheme, so the recovery flow gets the same threat-model scrutiny as login itself.

## Interfaces & contracts

*Proposed — the ideal design, not yet adopted.*

**Transport.** The proposed posture makes the MQTT line home TLS-only — no plaintext listener in any environment (the as-built worker still accepts plain `tcp` as a development convenience; the proposal retires it). With mTLS adopted, the same handshake that encrypts the channel also authenticates both ends: the device proves itself to yoyocloud, and yoyocloud proves itself to the device, which closes off impersonation of the cloud on hostile networks.

**Whitelist enforcement.** The whitelist is a security control, not just a UX feature: only parent-approved contacts can call or leave voice messages. The proposed contract matches the [Calling Engine](/builders/software/calling-engine/): yoyocloud is the authoritative **store** — parents edit it in the yoyopod app, the device syncs and caches it — while **enforcement happens on the device at two independent layers**: the Calling Engine's call path rejects non-whitelisted calls, and the contact-first UI never offers them in the first place. A stale cache still enforces the last-known list, so an offline device never widens the circle. If the SIP infrastructure decision lands on a self-hosted server, server-side rejection is added as a third layer — defense in depth on top of the device-side gate, not a replacement for it. The family-facing rules live at [Parental controls](/families/parental-controls/).

**Help Agent content policy.** The Ask wheel's Help Agents answer only through yoyocloud, and the proposed design enforces the age-appropriate content policy there, server-side — in code that inspects requests and responses, not merely in the prompt handed to a model. Prompts are steering; policy is enforcement, and enforcement must live where a jailbroken prompt cannot reach it. Push-to-talk is the only microphone path — the device never listens on its own — the AI-generated voice is always disclosed as such, and parents can review transcripts under a parent-controlled retention window (proposed default: 30 days). Details at [Voice & Ask Engine](/builders/software/voice-ask/).

**Location.** Location is reported live-ish — periodic, coarse-grained check-ins, never a continuous track — and retained briefly under the same minimization rule as everything else. The family-facing view is at [Privacy](/families/privacy/); the transport rides the same TLS-only MQTT line as everything else, described at [Connectivity](/builders/hardware/connectivity/).

**The proposed threat model, compactly:**

| Threat | Defense |
| --- | --- |
| Stranger tries to call or message the kid | Whitelist enforced on the device at two layers (call path + contact-first UI), synced from the authoritative store in yoyocloud; server-side rejection added where the SIP path allows it |
| Device stolen or resold | Parent unbinds the device from the household in the yoyopod app; unbind triggers a remote wipe of local data and revokes the device certificate |
| yoyocloud breach | Minimal stored data, short retention, EU hosting; with mTLS, no reusable device credentials exist to steal |
| Tampered update | Signature verification before install; A/B slots with automatic rollback if the new slot fails health checks |
| Snooping on a child's voice | Push-to-talk only — no always-listening path exists; AI voice always disclosed; transcripts parent-reviewable with parent-controlled retention |

## Today vs. target

Honestly: most of this page is proposed, not built. What exists today is the foundation the proposals are shaped to fit — the MQTT link home and device provisioning work; the secret boundary in configuration is real (device secrets are already kept out of tracked config); and [The yoyocore Runtime](/builders/software/runtime/) already isolates capabilities into separate processes, so a fault or compromise in one engine's worker is contained rather than total. That process isolation is a genuine, working security property and the model this page extends.

The target adds the layers around that core: mTLS device identity, signed updates over the existing slots, the factory provisioning flow, passkey-secured parent accounts, cloud-authoritative whitelist enforcement, and server-side Help Agent policy. Each is written above with its enforcement point so it can be adopted piecemeal — none of them requires the others to land first, though device identity is the one the most other pieces lean on. Implementation status stays where it belongs, in the as-built engineering docs (`website/` in the repository).

## Open questions

- **Device identity — adopt mTLS for V0 “Dawn”, or ship `device_id` + `device_secret` and migrate at V1 “Daylight”?** Migrating later means a credential-rotation project across a live fleet; adopting now means CA plumbing before launch.
- **Public commitments — do we publish EU hosting and concrete retention numbers (30-day transcript default, short location retention) as promises, or keep them as internal policy?** Published numbers build trust but bind us.
- **Update signing — full signature verification on the prototype path too, or product-board only?** Signing everything from day one is more work now but avoids ever shipping hardware that trusted unsigned updates.
- **Parent accounts — passkeys-only, or passkeys with a password fallback?** A fallback eases support load but reopens the phishing surface passkeys exist to close.
- **Whitelist enforcement — is the two-layer device-side gate (as proposed, matching the Calling Engine) sufficient, or do we require a SIP path that also allows server-side rejection?** Requiring the third layer constrains the self-hosted-vs-managed SIP decision.

:::note[Sources]
The as-built facts this page builds on — `device_id` + `device_secret`
identity, the A/B slot concept, the configuration secret boundary, the
MQTT transport modes, and per-engine process isolation — are condensed
from the as-built docs site (`website/` in the repository): the cloud
worker profile, the runtime process model, configuration wiring, and the
dev/prod lanes pages.
:::
