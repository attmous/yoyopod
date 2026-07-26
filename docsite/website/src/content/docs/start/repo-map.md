---
title: Repo Map & Source of Truth
description: How the yoyopod repository is organized and which documents to trust when they disagree.
---

:::note[Canonical source]
This page is a summary. The authoritative document is
[`docs/README.md`](https://github.com/attmous/yoyopod/blob/main/docs/README.md)
in the repository.
:::

The repository is Rust end to end: the device runtime and its worker hosts
live in `device/`, the operator CLI in `cli/`, deploy tooling in `deploy/`,
configuration in `config/`, and all Markdown documentation in `docs/`. The
UI design handoff package — normative pixel and behavior specs for every
screen — lives in `device/ui/assets/ui/`.

When documents disagree, trust sources in this order:

1. Current Rust runtime and worker host code in `device/`
2. The Rust operator CLI in `cli/` and deploy tooling under `deploy/`
3. [`docs/ROADMAP.md`](https://github.com/attmous/yoyopod/blob/main/docs/ROADMAP.md) — what is currently broken or paused
4. The operations, architecture, hardware, features, and design docs under `docs/`
5. Rules and agent guidance in `rules/`, `AGENTS.md`, and `skills/`

The project is mid-way through a staged Rust CLI rebuild — `docs/ROADMAP.md`
is the honesty document that says which commands work today and which are
paused. Read it before trusting any workflow description.
