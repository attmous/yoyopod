---
title: APIs & SDKs
description: The future contracts and packages surface.
---

*The API surface yoyopod will one day offer app and integration developers.*

:::caution[Placeholder]
No as-built content exists for this page yet — the outline below is the target structure.
:::

## Overview

- Framing: everything on this page is future work — no public API exists today
- Why an API surface at all: the parent app and any integrations need stable contracts
- Where the code will live: the planned `packages/` directory for SDKs, alongside the planned `apps/`
- The line this page must draw: internal protocols are not public APIs (see below)

## Planned surfaces

- SDK packages under `packages/` for building against the yoyopod cloud (TBD scope and languages)
- The contract the parent mobile app consumes: family setup, whitelist management, live-ish location, device status
- Cloud-side contracts riding on the existing MQTT cloud link (TBD shape)
- Explicit non-surface: the internal NDJSON worker protocol between the runtime and its workers exists today but is not a public API — it can change without notice and will never be a compatibility promise
- What versioning and deprecation policy these surfaces adopt (TBD)

## Design constraints

- Parent-managed by construction: every surface assumes the parent, not the child, is the account holder
- Least data: no surface should expose more about a child than the parent app itself shows
- No third-party app store on the device — the device has no browser and no app store, and the API surface must not become a back door to one
- Offline-tolerant clients: contracts must handle a device that is deliberately offline (local-first audio still works)
- Stability over breadth: a small surface we can keep is worth more than a wide one we cannot

## Today vs. target

- Today: no `packages/`, no public API; the only contracts are internal (runtime-to-worker NDJSON, MQTT cloud link)
- Today: the parent app itself is future work, so its contract is unconstrained by shipped clients
- Target: a first-party SDK that the parent app is built on, dogfooding the public surface
- Target: a published contract reference on this site, with the internal/public boundary documented

## Open questions

- TODO: Is the first public surface a cloud HTTP API, an SDK package, or both — and which ships first?
- TODO: Will third parties ever get access, or is the surface first-party-only for the foreseeable future?
- TODO: What is the versioning and deprecation policy for contracts consumed by a shipped parent app?
- TODO: How do we document the internal NDJSON protocol for contributors without implying it is public?
