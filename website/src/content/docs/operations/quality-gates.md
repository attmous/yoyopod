---
title: Quality Gates
description: The verification required before merging.
---

:::note[Canonical source]
This page is a summary. The authoritative document is
[`docs/operations/QUALITY_GATES.md`](https://github.com/attmous/yoyopod/blob/main/docs/operations/QUALITY_GATES.md)
in the repository.
:::

The pre-merge bar: per-workspace `cargo check`, `cargo test`, and
`cargo clippy` mirroring CI exactly, plus any area-specific validation the
change touches. Running the gate locally before pushing is expected — CI is
the backstop, not the first line.
