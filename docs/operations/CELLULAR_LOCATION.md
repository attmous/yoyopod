# Cellular location operations

The YoYoPod worker owns the SIM7600G-H directly through its AT and PPP ports.
`deploy/udev/77-yoyopod-sim7600.rules` reserves its serial ports for that worker
and exposes its `cdc-wdm` QMI control port to ModemManager for registration and
voice calls. It does not exclude the entire modem. Deployment updates this host
rule and restarts ModemManager when the rule changes.

## Machine-local APN

Set the carrier APN in the lane environment file, never in a release artifact
or Git:

```sh
sudoedit /etc/default/yoyopod-dev
# Add:
YOYOPOD_MODEM_APN=web.vodafone.de
```

Use the equivalent `/etc/default/yoyopod-prod` file for production. The
Vodafone Germany default is `web.vodafone.de`; confirm it against the SIM's
subscription before acceptance testing. Restart only the selected YoYoPod lane
after changing the override.

## Acceptance checks

1. Confirm the stable AT and PPP aliases resolve to the SIM7600 interface 02
   and 03 ports.
2. Confirm `ID_MM_DEVICE_IGNORE=0`, serial `ID_MM_PORT_IGNORE=1`, and QMI
   `ID_MM_PORT_IGNORE=0`. Confirm `ModemManager.service` is active and `mmcli`
   discovers the SIM7600 through its QMI port without claiming its serial ports.
3. Acquire a GNSS fix outdoors and verify its modem-provided UTC time.
4. Verify Wi-Fi remains the preferred default route, then remove Wi-Fi and
   confirm `ppp0` packet data.
5. Verify 60-second moving and 300-second stationary reports, a live settings
   change, and an on-demand request while background tracking is disabled.
6. Disconnect all uplinks, collect fixes, restart the lane, reconnect, and
   verify oldest-first backfill. The private outbox is capped at 24 hours or
   3,000 fixes and deletes a fix only after the backend application ACK.

Do not print device tokens, secrets, raw cloud configuration responses, or
coordinates during these checks.
