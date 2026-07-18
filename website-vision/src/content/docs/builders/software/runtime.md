---
title: Device Runtime & Workers
description: The supervisor and its worker processes.
---

*The Rust runtime that supervises every on-device capability as a worker process.*

## Overview

Behind the glass, yoyopod is one supervisor process — `yoyopod-runtime` —
and up to seven child processes, talking newline-framed JSON over stdio
pipes. No sockets, no bus daemons: the process tree is the architecture.
Workers report; the runtime aggregates the one true state ledger; the UI
renders it. Every cross-domain behavior (a call pausing music, low
battery ending the show) is runtime code — workers never talk to each
other.

Startup is UI-first: the UI host is the one **fatal** child — no
`ui.ready` within 5 seconds and the runtime aborts. Every other worker
gets 3 seconds; a late one is marked `Degraded` and boot continues.

## Key components

| Child | Owns |
| --- | --- |
| UI host (`device/ui/`) | rendering and button-facing behavior — see [UI System](/builders/software/ui/) |
| media | local music playback via mpv |
| voip | liblinphone: calls, messages, voice notes |
| network | cellular modem (SIM7600), PPP, GPS |
| cloud | MQTT to the backend — see [Cloud & Provisioning](/builders/software/cloud/) |
| power | PiSugar battery, RTC, watchdog |
| speech | cloud STT/TTS/Ask |

Shared pieces: `device/protocol/` (the envelope plus the UI contract) and
`device/worker/` (helpers for uniform ready/health/error envelopes).

## Interfaces & contracts

- **The wire** — every message is one NDJSON line: a typed envelope whose `schema_version` must equal 1 (anything else is hard-rejected), with a kind (`command` · `event` · `result` · `error` · `heartbeat`) and a `"domain.action"` routing key. A bad telegram is refused whole; mismatched peers fail closed at the first line.
- **The loop** — steady state is one function called at roughly **50 Hz** (a 20 ms sleep per turn): drain the inbox (capped at 64 messages per domain per turn), translate events to commands, apply to the state ledger, diff, dispatch.
- **Snapshot + patches** — a full snapshot at startup, then per-domain patches: only changed domains ever cross the wire to the UI, and a `Tick` goes to the UI every turn.
- **Per-worker vocabularies** — only the UI has a shared, typed contract; `media.*`, `cloud.*`, and the rest are conventions owned by each worker crate, so the shared crate never becomes a bottleneck.

## Today vs. target

- **No in-process restarts, by design.** A dead worker's domain is marked `Stopped` and stays that way; recovery is systemd restarting the entire runtime (`Restart=on-failure`, 5 s), which rebuilds every process from scratch. Slower than a surgical respawn — but provably consistent, because state is only guaranteed coherent at startup.
- Honest flags carried from the as-built docs: the `heartbeat` envelope kind is defined and nobody sends one; the worker `restart_count` field is never incremented; the shared worker helpers are used only by the power worker today.
- The deep dive — message names, timing budgets, failure paths — is the as-built Runtime & Workers Guide in the engineering docs (`website/` in the repository). This page stays the map; that guide stays the territory.

## Open questions

- TODO: is this worker split stable for the target, or do workers merge or appear?
- TODO: what happens to running workers during an update — drain, restart, stagger?

:::note[Sources]
Condensed from [`docs/architecture/SYSTEM_ARCHITECTURE.md`](https://github.com/attmous/yoyopod/blob/main/docs/architecture/SYSTEM_ARCHITECTURE.md) and [`docs/architecture/RUNTIME_EVENT_FLOW.md`](https://github.com/attmous/yoyopod/blob/main/docs/architecture/RUNTIME_EVENT_FLOW.md), and the as-built docs site (`website/` in the repository): the Runtime & Workers Guide — overview, process model, the 50 Hz loop, and the protocol page.
:::
