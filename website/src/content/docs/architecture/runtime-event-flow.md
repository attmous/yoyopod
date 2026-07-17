---
title: Runtime Event Flow
description: How events travel from worker hosts through the runtime into app state.
---

:::note[Canonical source]
This page is a summary. The authoritative document is
[`docs/architecture/RUNTIME_EVENT_FLOW.md`](https://github.com/attmous/yoyocore/blob/main/docs/architecture/RUNTIME_EVENT_FLOW.md)
in the repository.
:::

Worker hosts emit events (playback progress, call state, battery level,
network status) over the line protocol; `yoyopod-runtime` aggregates them
into application state and pushes snapshots back down to the UI host, which
renders them. The event-flow document traces this loop end to end — event
origin, envelope shape, runtime handling, and how a state change becomes a
visible UI update.
