---
title: Work Areas
description: Where Rust-first work belongs, by area of the codebase.
---

:::note[Canonical source]
This page is a summary. The authoritative document is
[`docs/architecture/WORK_AREAS.md`](https://github.com/attmous/yoyopod/blob/main/docs/architecture/WORK_AREAS.md)
in the repository.
:::

A routing table for contributors and agents: for each kind of change —
runtime behavior, a worker host, the operator CLI, deploy tooling,
configuration, docs — the work-areas document names the directory that owns
it and the constraints that apply there. Read it before starting work to
avoid landing changes in the wrong layer. For runtime and worker-host
changes specifically, the
[Runtime & Workers Guide](/runtime/) documents each crate in depth.
