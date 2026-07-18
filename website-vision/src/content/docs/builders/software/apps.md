---
title: App Platform
description: The yoyopod app and the shared contracts underneath it.
---

*The planned apps/ and packages/ layer: the yoyopod app and the contracts it shares with the device.*

:::tip[Proposed — the ideal design]
This page is the target design, written out in full so it can be adopted,
adapted, or dropped. Everything marked *Proposed* is neither implemented
nor committed; the one as-built fact is that nothing in this layer exists
yet.
:::

## Overview

*Proposed — the ideal design, not yet adopted.*

The App Platform is the buyer's half of the product. Kids hold the device; parents hold their phone. Everything a parent configures, approves, or reviews happens in **the yoyopod app**, which ships on **iOS and Android** from day one — a household with one iPhone parent and one Android parent is the normal case, not the edge case.

In the repository, this layer lives in two planned directories that do not exist yet:

- `apps/` — the yoyopod app itself (product-facing outline at [Parent App](/apps/parent-app/)).
- `packages/` — the shared contracts: the schemas and generated types that the app, [yoyocloud](/builders/software/cloud/), and the Rust device side all consume, so that a field renamed in one place breaks the build everywhere instead of failing silently at runtime.

The V1 “Daylight” scope for the app is deliberately narrow — five jobs, done well:

1. **Pairing** — bind a new device to a household account.
2. **Whitelist management** — decide who the device can call and message (family-facing story at [Parental Controls](/families/parental-controls/)).
3. **Live-ish location view** — see roughly where the device is, on the cadence it reports (product page at [Locate](/apps/locate/)). Live-ish, never real-time.
4. **Content loading** — put audio content onto the device.
5. **Help Agent builder** — create and manage the Help Agents that appear on the device's Ask wheel (product page at [Ask](/apps/ask/)).

Anything beyond these five is V2 material and should be resisted until V1 ships.

## Key components

*Proposed — the ideal design, not yet adopted.*

**The yoyopod app.** A single app for the whole household, organized around the device rather than around features: a parent opens the app, sees their child's yoyopod, and everything — whitelist, location, content, Help Agents — hangs off that device view. Multiple parents share one household account with equal rights in V1; role differentiation (owner vs. viewer) is a V2 question. The setup walkthrough is the family-facing companion at [Setup](/apps/setup/).

**Shared contracts in `packages/`.** The single source of truth for every payload that crosses a boundary — app ↔ yoyocloud and yoyocloud ↔ device. The rule is schema-first: a human-edited schema file is the artifact of record, and code generation produces the Rust types for the device side, the client types for the app, and the validation layer in yoyocloud. Nobody hand-writes a struct that mirrors a schema; if the generated code is awkward, the schema changes.

| Schema technology | Strengths | Weaknesses |
| --- | --- | --- |
| **JSON Schema** (recommended) | Protocol-neutral; human-readable; validates the JSON actually on the wire; solid code generation into Rust and into Swift/Kotlin/Dart; embeds directly into an OpenAPI description | No binary encoding; codegen quality varies by target |
| Protocol Buffers | Best-in-class codegen everywhere; compact binary wire format; strong versioning discipline | Commits the wire format to protobuf; JSON debugging becomes second-class; heavier toolchain for a small team |
| OpenAPI (schemas inline) | Describes endpoints *and* payloads in one file; generates full API clients | Couples the data model to one specific REST surface; awkward as a shared truth for the device side, which is not a REST client |

**Recommendation: JSON Schema** as the source of truth, referenced from an OpenAPI description of yoyocloud's HTTP surface — it keeps the data model independent of any one transport, which matters because the same `Whitelist` shape must serve a phone app over HTTPS and a Rust device process over its own channel.

**The Help Agent builder.** The app-side half of the Help Agents concept. A parent creates a Help Agent in four steps: pick a **topic area** (math, science, animals, reading, and so on), pick a **tone** (playful, patient, or matter-of-fact), set **boundaries** (what is off-limits for this helper), and give it a name. The result is a configuration object — not a prompt string — that yoyocloud stores and enforces server-side; the age-appropriate content policy lives in yoyocloud regardless of what any agent configuration says (see [Voice & Ask Engine](/builders/software/voice-ask/)). The kid's side of the same feature is the Ask wheel: spin, pick a helper, hold the button, ask. The builder also surfaces transcript review (proposed default retention 30 days, parent-controlled) so a parent can see what was asked and answered.

**The pairing flow.** Pairing is the one moment the app and the device must agree on something before any trust exists, so it is kept dumb and observable: the device shows a short code on the canvas; the parent types it into the app or scans it; the app sends the code to yoyocloud; yoyocloud verifies that this device is currently presenting that code and binds the device to the household. The device and the phone never talk to each other directly — yoyocloud is the matchmaker, which means pairing works identically whether the phone and device share a room or a continent. Threat model and code lifetime belong to [Security](/builders/software/security/).

## Interfaces & contracts

*Proposed — the ideal design, not yet adopted.*

**One rule above all: the app talks only to yoyocloud.** Never to devices directly — not over the local network, not over Bluetooth, not during setup. Every app↔device interaction is two hops through the backbone. This costs a little latency and buys a lot: one authentication story, one audit point, one protocol to version, and no device-side listener for a phone to find.

| App ↔ yoyocloud protocol | Strengths | Weaknesses |
| --- | --- | --- |
| **REST + JSON, with platform push notifications for wake-ups** (recommended) | Boring and debuggable; first-class tooling on every mobile platform; caching and retries are solved problems; push handles the "something changed" case without holding a connection | Not truly real-time — which the product explicitly does not promise anyway |
| MQTT over WSS | Genuinely bidirectional; efficient for many small updates | A second protocol to operate and secure; mobile OSes punish long-lived connections in the background; overkill for a settings-and-status app |
| GraphQL | Flexible queries; single endpoint | Solves an over-fetching problem this small API does not have; adds a server and client layer a two-engineer team must own |

**Recommendation: REST + JSON with push notifications** — the app is a low-frequency control surface, not a telemetry firehose, and the dullest protocol is the one that never pages anyone.

**The whitelist editing flow, end to end.** A parent adds a contact in the app → the app `PUT`s the new whitelist (a complete versioned document, not a diff) to yoyocloud → yoyocloud validates it against the shared schema, stores it as the new version, and acknowledges → yoyocloud notifies the device over the device's own channel → the device applies the new whitelist and confirms the version it is now running → the app displays two distinct states, "saved" (yoyocloud has it) and "active on device" (the device confirmed it), so a parent with an offline device sees the truth: the change is saved and will apply when the device next connects. Whole-document versioning makes conflicts trivial — last write wins on a document small enough for parents to eyeball.

**Location view honesty.** The location view shows the device's last reported position and, prominently, *when* that report arrived. It is live-ish by design — the device reports on a cadence, and the app never animates, extrapolates, or implies a live tracking feed. If the last report is stale, the app says so plainly rather than showing a confident dot. The privacy rationale for this restraint is at [Privacy](/families/privacy/).

## Today vs. target

**Today: nothing in this layer exists.** `apps/` and `packages/` are planned directories, not present ones. There is no parent app, no shared-contract package, and no app↔yoyocloud protocol in use. Today's device and cloud sides are documented in the as-built engineering docs (`website/` in the repository).

*Proposed — the ideal design, not yet adopted.*

The target is one parent app and one shared-contract layer with zero drift between them — and the framework choice should be sized honestly to a two-engineer team that also owns a Rust device stack and a cloud backbone:

| App framework | Strengths | Weaknesses |
| --- | --- | --- |
| Native Swift + Kotlin | Best platform fidelity; no framework risk | Two codebases, two skill sets — it doubles the surface a two-engineer team must carry |
| **Flutter** (recommended) | One codebase and one skill set for both stores; mature tooling; consistent rendering; strong fit for a forms-and-status control app | Non-native widget layer; Dart is a new language for the team |
| React Native | Huge ecosystem; web-adjacent skills transfer | Native-module glue work tends to land on exactly the kind of small team that can least afford it |
| Kotlin Multiplatform | Shared logic with fully native UI | Still two UI codebases; the least mature tooling of the four |

**Recommendation: Flutter** — for a two-engineer team, one codebase that ships to both stores is worth more than native pixel-perfection in an app whose job is settings, status, and setup.

## Open questions

*Proposed — the key adopt/drop decisions.*

- **Adopt or drop the cloud-only rule for the app?** Committing to "the app never talks to the device directly" simplifies security and versioning forever, but forecloses local-network setup tricks — decide now, because the pairing design depends on it.
- **Adopt JSON Schema as the single contract source, or choose protobuf before any code exists?** Switching schema technology after both sides generate code from it is the most expensive migration on this page.
- **Adopt Flutter, or pay for two native codebases?** This is a hiring and velocity decision as much as a technical one, and it should be made before the first screen is built.
- **Adopt the five-job V1 scope as a hard cap?** Pairing, whitelist, live-ish location, content loading, Help Agent builder — every addition delays the date a parent can actually use the device.
- **Adopt the proposed transcript-review default (30 days, parent-controlled) as the shipped setting?** It balances parental oversight against data minimization, but it is a product-values call that belongs to the founder, not the schema.
