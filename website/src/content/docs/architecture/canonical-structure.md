---
title: Canonical Structure
description: Config topology, package ownership, and board overlay rules.
---

:::note[Canonical source]
This page is a summary. The authoritative document is
[`docs/architecture/CANONICAL_STRUCTURE.md`](https://github.com/attmous/yoyopod/blob/main/docs/architecture/CANONICAL_STRUCTURE.md)
in the repository.
:::

Configuration lives in a YAML tree under `config/` (app, audio, cloud,
communication, device, network, people, power, voice), with per-board
overrides under `config/boards/` — today only `rpi-zero-2w`. The canonical
structure document defines which package owns which config file, how board
overlays compose with the base tree, and where new configuration must go so
that ownership stays unambiguous.

:::caution[Partially superseded]
The config wiring is now documented in depth at
[Configuration Wiring](/runtime/configuration/). The canonical document's
"Canonical Package Ownership" section describes the **retired Python
layout** and no longer matches the Rust crates — see the runtime guide's
[Known Gaps](/runtime/gaps/).
:::
