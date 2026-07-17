---
title: Power Module
description: PiSugar 3 battery, RTC, watchdog, and the power safety policy.
---

:::note[Canonical source]
This page is a summary. The authoritative document is
[`docs/hardware/POWER_MODULE.md`](https://github.com/attmous/yoyocore/blob/main/docs/hardware/POWER_MODULE.md)
in the repository.
:::

Power comes from a PiSugar 3 battery HAT on the I2C bus (`i2c-1`, addresses
`0x57`/`0x68`), managed through `pisugar-server` and owned by the
`device/power` worker. The power module document covers battery telemetry,
the RTC, the software watchdog, shutdown safety policy, and the
inactivity-driven display backlight timeout — plus the config keys in
`config/power/backend.yaml`.
