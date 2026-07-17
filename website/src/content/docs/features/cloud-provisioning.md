---
title: Cloud Provisioning & Backend
description: Device claiming, authentication, config sync, and MQTT telemetry.
---

:::note[Canonical source]
This page is a summary. The authoritative document is
[`docs/features/CLOUD_PROVISIONING_AND_BACKEND.md`](https://github.com/attmous/yoyopod/blob/main/docs/features/CLOUD_PROVISIONING_AND_BACKEND.md)
in the repository.
:::

How a device is claimed and authenticated against the backend, how
configuration syncs down to the device, and how telemetry flows up over
MQTT via the `device/cloud` worker host. The document defines the
provisioning contract and the backend endpoints the device depends on.
