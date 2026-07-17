---
title: Pi Dev Workflow
description: The day-to-day loop from your dev machine to a running device.
---

:::note[Canonical source]
This page is a summary. The authoritative document is
[`docs/operations/PI_DEV_WORKFLOW.md`](https://github.com/attmous/yoyocore/blob/main/docs/operations/PI_DEV_WORKFLOW.md)
in the repository.
:::

The core loop: push a branch, let CI build the arm64 bundle, then
`yoyopod target deploy --branch <branch>` to sync the device's dev-lane
checkout at `/opt/yoyopod-dev/checkout`, restart `yoyopod-dev.service`, and
verify startup. The document covers the supporting commands — logs, status,
screenshots — and what to do when a deploy goes sideways.
