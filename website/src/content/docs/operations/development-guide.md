---
title: Development Guide
description: Toolchain setup, running the workspace, validation, and daily workflow.
---

:::note[Canonical source]
This page is a summary. The authoritative document is
[`docs/operations/DEVELOPMENT_GUIDE.md`](https://github.com/attmous/yoyocore/blob/main/docs/operations/DEVELOPMENT_GUIDE.md)
in the repository.
:::

The day-one document: installing the Rust toolchain, building the `device/`
workspace and the `cli/` workspace, running tests and clippy the way CI does,
and the daily edit–build–validate loop. Pair it with the
[Quality Gates](/operations/quality-gates/) before opening a PR.
