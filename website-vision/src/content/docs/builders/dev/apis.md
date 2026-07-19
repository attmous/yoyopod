---
title: APIs & SDKs
description: The future contracts and packages surface.
---

*The API surface yoyopod will one day offer app and integration developers.*

:::tip[Proposed — the ideal design]
This page is the target design, written out in full so it can be adopted,
adapted, or dropped. Everything on it is proposed — neither implemented
nor committed.
:::

## Overview

yoyopod's public API story fits in one sentence: **yoyocloud's REST API is
the only public API.** Every client that will ever exist — the yoyopod app
first, a first-party SDK second, any partner integration a distant third —
speaks REST + JSON to [yoyocloud](/builders/software/cloud/) and to nothing
else. The device itself has no public interface at all: no local socket, no
Bluetooth service, no LAN endpoint a phone could discover. This is the same
rule the [App Platform](/builders/software/apps/) page states from the
app's side — the app talks only to yoyocloud, and app and device never talk
directly — restated here as an API commitment rather than an app behavior.

Why have an API surface at all? Because the yoyopod app needs stable
contracts to be built against, and because a contract that exists only as
an implementation detail inside one backend is a contract that drifts. The
seed of the SDK already has a shape: the planned `packages/` directory,
where schema-first contracts live as human-edited JSON Schema files and
code generation produces the Rust types for the device, the client types
for the app, and the validation layer in yoyocloud. The SDK is not a
separate project to be written one day — it grows out of those generated
types, so the public surface and the app are provably the same thing.

The other job of this page is to draw a line and keep it drawn: internal
protocols are not public APIs. Two internal contracts exist or are planned
— the NDJSON wire between the yoyocore Runtime and its workers, and the
MQTT link between the device and yoyocloud — and both are permanently
internal, for reasons spelled out below.

## Planned surfaces

**The public API: yoyocloud's REST surface.** One HTTP API, described in a
single OpenAPI document whose payload schemas are references into the
`packages/` JSON Schemas — the OpenAPI file describes endpoints, the
schemas remain the single source of truth for shapes. The surface covers
exactly what the app's five V1 “Daylight” jobs need: household accounts
and device claiming (the pairing code flow), the whitelist as a versioned
whole document (a `PUT` of the complete document, with the API exposing
both "saved" and "active on device" states), the live-ish location read
(REST pull, with a platform push notification as the nudge to look),
content loading, and Help Agent profiles with their reviewable
transcripts. Push notifications ride the standard iOS and Android
channels and carry no payload a client must parse to stay correct — they
are wake-ups, not a second API.

**The SDK: generated, not handwritten.** The `packages/` schemas are the
seed; the question is what grows from them.

| SDK approach | Strengths | Weaknesses |
| --- | --- | --- |
| **Client generated from the OpenAPI description** (recommended) | One source of truth end to end; the yoyopod app consumes the generated client, so the public surface is dogfooded by the flagship client every day; regeneration catches drift at build time | Generated ergonomics are rarely beautiful; some hand-written convenience layer will still accrete on top |
| Hand-written SDK per platform | Idiomatic, polished developer experience | A second implementation of every contract, maintained by hand by a two-engineer team — drift is a matter of time |
| No SDK — published OpenAPI and docs only | Zero maintenance | Every client re-implements auth, retries, and the saved-vs-active whitelist dance; the parent app would end up with a private client library anyway, unshared |

**Recommendation: a generated client that the yoyopod app itself is built
on.** If the generated client is not good enough for our own app, it is
not good enough to publish — dogfooding is the quality gate.

**Versioning and deprecation.** A public API is a promise, and the policy
should be decided before the first client ships, not after.

| Versioning policy | Strengths | Weaknesses |
| --- | --- | --- |
| **Path versioning (`/v1/`), additive-only within a version** (recommended) | Visible in every URL and every log line; boring and universally understood; additive change (new optional fields, new endpoints) needs no coordination | A true breaking change means a `/v2/` and a migration window to manage |
| Header or media-type versioning | Clean URLs; fine-grained per-resource versions | Invisible in logs and casual debugging; easy to get subtly wrong in caches and proxies |
| No versioning — additive-only forever | Simplest possible story | One day a breaking change is genuinely needed, and there is no mechanism left to make it |

**Recommendation: `/v1/` in the path, additive-only within a version**,
with a deprecation window measured against shipped app installs — parents
do not update apps promptly, so an old version stays supported until the
install base that depends on it has actually drained, not until a date on
a roadmap.

**Explicit non-surface: the NDJSON worker wire.** Inside the device, the
[yoyocore Runtime](/builders/software/runtime/) supervises its worker
processes over newline-framed JSON on stdio pipes — a typed envelope with
a `schema_version` that must equal 1, where a bad telegram is refused
whole. This wire is not a public API, will never be one, and the reason is
structural, not precautionary: **it versions with the firmware, not with
partners.** Both ends of the pipe ship together inside one signed yoyoOS +
yoyocore image, updated atomically over A/B slots — there is no
independent party on the far end, so there is nothing to be compatible
*with*. Freezing this wire for outside consumers would trade away the one
freedom the firmware needs most: the ability to rename a message, split a
worker, or bump `schema_version` in a single commit that updates both
sides at once. The same logic covers the device's MQTT link to yoyocloud:
its topic contract versions with the firmware-and-backbone pair, it is
authenticated per device (per-device mTLS in the target design), and no
third party is ever on that channel. MQTT is device-side only; the public
surface is REST.

**A future partner surface — parked.** If a partner or integration
surface ever exists, its plausible shapes are already visible: scoped,
read-only status integrations (a family calendar that shows the device is
charged and online), audio content partners publishing catalogs into the
content-loading pipeline, and parent-initiated data export for
portability. All of it is parked, deliberately, until the yoyopod app has
shipped on both stores and the five V1 jobs work in families' hands — the
first-party app must prove the public surface before anyone else builds
on it. Every future candidate must also pass the design constraints
below unchanged; a partner surface that needs an exception to them is a
partner surface we do not build.

## Design constraints

**Parent-managed by construction.** Every credential the API issues
belongs to a parent account in a household — passkey-authenticated, with
equal rights among parents in V1. There is no child-facing token, no
device-facing public endpoint, and no API path by which anyone other than
a household's parents can read or change that household's data. An SDK
inherits this for free: it can only do what a signed-in parent can do.

**Least data.** No surface may expose more about a child than the yoyopod
app itself shows. A child profile is a first name and an age band —
nothing more exists to leak. Location is live-ish at the API level too:
the endpoint returns the last coarse fix and its timestamp, retention is
short, and there is no history endpoint that could reconstruct a movement
profile (the reasoning lives at [Privacy](/families/privacy/)).

**No back door to an app store.** The device has no browser and no app
store, and the API surface must never become either by accident. No
endpoint pushes executable content to a device: content loading delivers
audio, whitelist entries are contacts the on-device
[VoIP Engine](/builders/software/voip-engine/) enforces, and a Help Agent
is exactly four configuration choices — topic area, tone, boundaries, and
a name — assembled and policy-checked server-side in yoyocloud, never raw
prompt text from a client.

**Offline-tolerant clients.** The contracts model the truth that a device
may be deliberately offline. The whitelist API's two states — "saved" in
yoyocloud versus "active on device" — exist precisely so a client never
has to pretend; an offline device enforces its last-synced whitelist, and
music and stories keep working with no internet because content is
local-first. Any SDK must surface this distinction rather than papering
over it with a single misleading "done".

**Stability over breadth.** A small surface we can keep is worth more
than a wide one we cannot. The API grows only when the yoyopod app needs
it to, and every addition is a promise the team must keep for as long as
a shipped app depends on it — which, per the deprecation policy above, is
a long time.

## Today vs. target

Today there is no public API and no `packages/` directory. The only
contracts in existence are internal: the runtime-to-worker NDJSON wire on
the device, and the device's MQTT link to the backend — and on that link,
the REST side is configuration without implementation (`api_base_url`
exists in config; no REST surface answers it). The yoyopod app is itself
future work, which means the public contract is currently unconstrained
by any shipped client. That is not a gap to apologize for — it is the
one window in the product's life when getting schema-first right costs
nothing, because there is no installed base to migrate.

The target unfolds in a deliberate order. First, the `packages/` schemas
land as the source of truth, and yoyocloud's REST surface validates
against them from its first endpoint. Second, the OpenAPI description is
written referencing those schemas, and the client is generated from it.
Third, the yoyopod app is built on that generated client — the public
surface and the flagship client become the same artifact, and drift
becomes a build failure instead of a production incident. Finally, the
contract reference is published on this site with the internal/public
boundary documented in the same breath: the NDJSON protocol stays
documented for contributors in the as-built engineering docs (`website/`
in the repository) under an explicit "not a compatibility promise"
banner, so nobody mistakes visibility for stability. The partner surface
stays parked behind all of it, waiting for the app to ship first.

## Open questions

- **Adopt the one-public-API rule permanently?** yoyocloud's REST surface
  as the only public API — with the NDJSON wire and the MQTT link
  internal forever — is the decision everything else on this page hangs
  from; adopting it forecloses device-local integrations for good.
- **Adopt the generated-client SDK with the yoyopod app as its first
  consumer**, or hand-write the app's client now and extract an SDK
  later — accepting the drift risk in exchange for early ergonomics?
- **Adopt `/v1/` path versioning with additive-only change inside a
  version**, and if so, commit to a deprecation window measured against
  shipped app installs rather than calendar dates?
- **Adopt the parked stance on partner access?** No third-party surface
  of any kind until the yoyopod app has shipped and proven the contracts
  — or leave room for an earlier, narrower exception such as read-only
  status.
