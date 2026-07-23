# On-Device Wi-Fi Onboarding

Connect a YoYoPod to home Wi-Fi with no companion app and no keyboard: on the
device pick **Settings → Wi-Fi**, and it turns its own radio into a temporary
Access Point, shows a QR code, and serves a captive-portal web page where a
phone selects the network and enters the password.

Owned by the network worker (`device/network/`); the flow lives in
`device/network/src/provisioning.rs` and runs on a background thread so the
worker stays responsive.

## Flow

1. **Settings → Wi-Fi** (the item sits before *About* in the wheel) starts
   provisioning.
2. The provisioning thread, single-radio aware, scans nearby networks first and
   caches them, then brings up a WPA2 hotspot via NetworkManager
   (`802-11-wireless mode=ap`, `ipv4=shared` pinned to `10.42.0.1/24`).
3. A `tiny_http` captive portal binds to `10.42.0.1:80` (the AP gateway only).
   The device screen shows the AP SSID + key and a `WIFI:` join **QR code**.
4. The phone scans the QR, joins the AP, and the OS captive-portal sheet opens
   `http://10.42.0.1/`. The portal lists the scanned networks; the user picks one
   (or types a hidden SSID) and taps **Connect**.
5. The device tears the AP down and joins the chosen network as a station; the
   screen shows progress, then "Connected".

## Timeouts & lifecycle

- **120 s** portal idle timeout → tear the AP down and let NetworkManager
  auto-reconnect the previously active profile, so the device returns online on
  its own if the user walks away.
- **40 s** AP-activation tolerance (NM's shared-mode dnsmasq setup is slow on the
  Pi Zero; a timeout is treated as "still coming up", not a failure).
- **30 s** station-connect timeout (wrong password / DHCP failure is surfaced,
  not reported as success).
- Leaving the Setup screen **cancels promptly**: the stop signal threads into
  every activation wait (AP startup *and* station connect), so teardown never
  blocks for a full timeout.
- A `Drop` guard on the provisioner (graceful exits) plus a startup sweep
  (`cleanup_stale_setup_ap`, called from `worker::run`) guarantee the setup AP is
  never left broadcasting after any exit, graceful or not.

## Security model

- The setup AP is WPA2 with a **fresh random key shown only on the device
  screen** — you must physically see the screen to join.
- The portal binds to the **AP gateway only** (`10.42.0.1`), never `0.0.0.0`, so
  `/connect` is not reachable over cellular/PPP or any other interface.
- **Saved Wi-Fi passwords are never sent to the phone.** Selecting a saved
  network reconnects by reactivating the device's existing NetworkManager profile
  server-side (preserving its static-IP / hidden / autoconnect settings); the
  stored key stays inside NetworkManager.
- `/connect` bodies are size-capped (8 KiB, `413` on excess) and read off the
  control loop with a deadline, so a slow or hostile client cannot exhaust memory
  or wedge the single radio in AP mode.
- **Enterprise (802.1X)** networks are rejected, not silently downgraded to
  WPA-PSK. Raw 64-hex-digit PSKs are accepted.

## Deploy requirements

Installed automatically by `yoyopod target deploy`
(`cli/yoyopod/src/commands/target/deploy.rs`) and, for a fresh board, by
`deploy/scripts/bootstrap_pi.sh`:

- **polkit rule** granting the network-host service user the NetworkManager
  actions the flow needs: `wifi.scan`, `settings.modify.system`,
  `network-control`, `checkpoint-rollback`, and `wifi.share.protected`/`open`.
  (The service runs as a non-login systemd session, which is not implicitly
  authorized for these.)
- **`CAP_NET_BIND_SERVICE`** ambient capability on the network-host unit
  (`deploy/systemd/yoyopod-*.service`) so the portal can bind port 80.
- **dnsmasq captive-DNS snippet**
  (`/etc/NetworkManager/dnsmasq-shared.d/010-yoyopod-captive.conf`) resolving all
  names to `10.42.0.1` so phones auto-open the portal. Applied only while a
  shared connection is active; inert during normal operation.
- Requires **NetworkManager** with its shared-mode dnsmasq helper on the Pi.

## Key code

| Area | Location |
|------|----------|
| AP lifecycle, captive portal, NM station join | `device/network/src/provisioning.rs` |
| Captive-portal page (embedded via `include_str!`) | `device/network/src/portal.html` |
| Setup → Wi-Fi item, QR screen | `device/ui/src/components/screens/setup.rs`, `.../widgets/setup.rs` |
| Deploy-time polkit rule | `cli/yoyopod/src/commands/target/deploy.rs` (`render_wifi_polkit_rule`) |
| Fresh-board bootstrap (polkit + captive DNS) | `deploy/scripts/bootstrap_pi.sh` |
