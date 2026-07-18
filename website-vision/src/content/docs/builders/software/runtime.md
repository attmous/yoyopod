---
title: Device Runtime & Workers
description: The supervisor and its worker processes.
---

*The Rust runtime that supervises every on-device capability as a worker process.*

:::caution[Vision stub]
Placeholder in the vision docs — the structure is decided, the content is
not written yet. As-built engineering docs live in the main docs site
(`website/` in the repository).
:::

## Overview

- One supervisor, many workers: each on-device capability runs as its own process under the Rust runtime
- Why process isolation matters on a kids device: a crashed worker gets restarted, the device keeps going
- The supervision chain: systemd supervises the runtime, the runtime supervises the workers
- What the target state adds beyond today's worker set (TBD)

## Key components

- media worker — music and stories playback via mpv, local-first
- voip worker — whitelist calls and voice messages
- network worker — 4G modem and connectivity
- cloud worker — the MQTT link home
- power worker — battery and power management
- speech worker — push-to-talk capture behind the button hold

## Interfaces & contracts

- How the supervisor talks to workers: lifecycle commands and message shapes (outline, not spec)
- Restart and backoff policy per worker (TBD)
- Health reporting: what the runtime knows about each worker at any moment
- Which runtime contracts the future `packages/` layer would surface to the parent app (TBD)

## Today vs. target

- Today: all six workers run under the Rust runtime, with systemd supervising the runtime itself
- The deep dive is the as-built Runtime & Workers Guide in the engineering docs (`website/` in the repository)
- Target: this page stays the map; the as-built guide stays the territory
- Worker candidates beyond the current six, if any (TBD)

## Open questions

- TODO: is the six-worker split stable for the target, or do workers merge or appear?
- TODO: how much supervisor protocol belongs here vs. deferred to the as-built guide?
- TODO: what happens to running workers during an update — drain, restart, stagger?
