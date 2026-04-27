# Cloud Provisioning, Secure Backend Connection, And MQTT Telemetry

This document is the device/runtime-side reference for how YoYoPod talks to the backend.

It covers:

- provisioning inputs required by the device runtime
- how the Python runtime authenticates and refreshes device access
- how remote config is fetched and cached
- how MQTT telemetry and commands are handled
- what is currently implemented versus what the backend already expects

When this file and older plans disagree, trust the current code in:

- `yoyopod/integrations/cloud/`
- `yoyopod/backends/cloud/`
- `yoyopod/core/bootstrap/`
- `yoyopod/core/loop.py`
- `yoyopod/integrations/power/service.py`

## 1. Device-Side Concept

The runtime treats cloud/backend integration as a dedicated subsystem.

Its responsibilities are:

1. load provisioned runtime secrets
2. authenticate the device against the backend
3. refresh the device token before expiry
4. fetch remote config from the backend
5. cache config for offline startup
6. persist cloud status for operator inspection
7. publish selected telemetry over MQTT
8. react to backend MQTT commands that request immediate action

This subsystem does not own parent claiming UX. Claiming is a backend and dashboard concern.

## 2. Current Runtime Components

Current core files:

- [yoyopod/integrations/cloud/manager.py](../../yoyopod/integrations/cloud/manager.py)
- [yoyopod/backends/cloud/http.py](../../yoyopod/backends/cloud/http.py)
- [yoyopod/backends/cloud/mqtt.py](../../yoyopod/backends/cloud/mqtt.py)
- [yoyopod/integrations/cloud/models.py](../../yoyopod/integrations/cloud/models.py)
- [yoyopod/config/models/](../../yoyopod/config/models/)
- [yoyopod/core/bootstrap/__init__.py](../../yoyopod/core/bootstrap/__init__.py)
- [yoyopod/core/loop.py](../../yoyopod/core/loop.py)
- [yoyopod/integrations/power/service.py](../../yoyopod/integrations/power/service.py)

Current architecture:

```text
core bootstrap
  -> ConfigManager loads cloud config + secrets
  -> CloudManager.prepare_boot()
     -> reload provisioning inputs
     -> load cached config if present
     -> start MQTT client
  -> runtime loop
     -> CloudManager.tick()
        -> authenticate if needed
        -> refresh token before expiry
        -> fetch config on schedule
        -> back off on errors
  -> power coordinator
     -> publish battery telemetry on interval
```

## 3. Provisioning Inputs Required By The Runtime

Current cloud config model is defined in:

- [yoyopod/config/models/](../../yoyopod/config/models/)

Tracked backend settings include:

- `api_base_url`
- `auth_path`
- `refresh_path`
- `config_path_template`
- `timeout_seconds`
- `config_poll_interval_seconds`
- `claim_retry_seconds`
- `cache_file`
- `status_file`
- `mqtt_broker_host`
- `mqtt_broker_port`
- `mqtt_use_tls`
- `mqtt_username`
- `mqtt_password`
- `battery_report_interval_seconds`

Runtime-only secrets are:

- `device_id`
- `device_secret`

Current defaults:

- `auth_path = /v1/auth/device`
- `refresh_path = /v1/auth/device/refresh`
- `config_path_template = /v1/devices/{device_id}/config`

## 4. Current Provisioning State Model

Current `CloudManager` tracks provisioning state through `CloudStatusSnapshot`.

Key states:

- `unprovisioned`
  - no device secrets present
- `invalid_provisioning`
  - secret file exists but is incomplete or malformed
- `provisioned`
  - `device_id` and `device_secret` are both present

Cloud state is tracked separately with values such as:

- `offline`
- `authenticating`
- `ready`
- `degraded`
- `unclaimed`

Important distinction:

- provisioned means local runtime secrets exist
- claimed is a backend ownership state

## 5. Current Boot Sequence

Current boot wiring happens in:

- [yoyopod/core/bootstrap/__init__.py](../../yoyopod/core/bootstrap/__init__.py)

At boot:

1. `CloudManager` is created from config
2. `prepare_boot()` runs
3. provisioning inputs are reloaded
4. config cache is applied if it matches the current `device_id`
5. MQTT client startup is attempted
6. the main loop later advances auth and config sync through `tick()`

This lets the device start with cached config even before reaching the backend.

## 6. Current HTTPS Auth And Refresh Design

Current HTTP client:

- [yoyopod/backends/cloud/http.py](../../yoyopod/backends/cloud/http.py)

Current operations:

- `authenticate(device_id, device_secret)`
- `refresh(access_token)`
- `fetch_config(access_token, device_id)`

Current token scheduling behavior in `CloudManager`:

- refresh happens before expiry
- threshold is the smaller of:
  - 20% of token lifetime
  - 2 hours before expiry

Current error handling behavior:

- `device_unclaimed`
  - state becomes `unclaimed`
  - auth retries after `claim_retry_seconds`
- invalid credentials
  - state becomes `degraded`
  - further auth effectively stops until provisioning changes
- network/backend failures
  - back off with 30s, 60s, 120s, then 300s

## 7. Current Config Fetch And Cache Design

Current config fetch behavior:

- once authenticated, the runtime fetches:
  - `GET /v1/devices/{device_id}/config`
- polls at `config_poll_interval_seconds`
- can be forced by:
  - network reconnection
  - local runtime requests
  - MQTT `fetch_config` command

Current cache behavior:

- cache file path comes from `cloud.backend.cache_file`
- cache is only applied if cached `device_id` matches current device
- raw payload is persisted with:
  - `device_id`
  - `config_version`
  - `fetched_at`
  - `source`
  - `raw_payload`
  - `unapplied_keys`

Current status persistence:

- status file path comes from `cloud.backend.status_file`
- status includes:
  - device id
  - provisioning state
  - cloud state
  - config source
  - config version
  - backend reachability
  - last successful sync
  - last error summary
  - unapplied keys

## 8. Current Runtime Side Effects Of Remote Config

After a successful config fetch, `CloudManager` currently:

- applies config overrides through `ConfigManager`
- updates max-volume related context state
- clamps current output volume if needed
- applies default output volume when present
- updates VoIP manager voice-note duration settings when available

So remote config is not just cached; parts of it are actively enforced into the running app.

## 9. Current MQTT Design On The Device

Current MQTT implementation:

- [yoyopod/backends/cloud/mqtt.py](../../yoyopod/backends/cloud/mqtt.py)

Current topic usage:

- publish device events to:
  - `yoyopod/{device_id}/evt`
- subscribe for backend commands on:
  - `yoyopod/{device_id}/cmd`

Current published event helpers:

- `publish_battery(level, charging)`
- `publish_heartbeat(firmware_version?)`
- `publish_connectivity(connection_type)`

Current command handling:

- parses JSON command payload
- logs the command type
- forwards it to `CloudManager`

Current command application in `CloudManager`:

- `fetch_config`
  - sets `_next_config_poll_at = 0.0`
  - causes the next loop tick to re-fetch config immediately
- other command types are currently only logged as unhandled

Current lifecycle guardrails:

- `CloudManager.prepare_boot()` relies on provisioning reload to start MQTT once
- replacing MQTT configuration stops the previous client before creating a new one
- `DeviceMqttClient` uses one managed Paho network loop instead of separate reconnect threads

This matters because duplicate MQTT clients using the same device id can force broker session takeovers and prevent battery telemetry from reaching the backend reliably.

## 10. Current Telemetry Definitely Wired In The Python Runtime

The safest claim is what is definitely wired today.

### Battery telemetry

Battery telemetry is currently wired through:

- [yoyopod/integrations/power/service.py](../../yoyopod/integrations/power/service.py)

When power snapshots update:

- if battery level is known
- and MQTT is connected
- and the report interval has elapsed
- `CloudManager.publish_battery()` emits a `battery` event

### Heartbeat

Heartbeat is currently emitted:

- after successful live config sync
- when runtime code explicitly requests it

Relevant references:

- [yoyopod/integrations/cloud/manager.py](../../yoyopod/integrations/cloud/manager.py)
- [yoyopod/integrations/display/service.py](../../yoyopod/integrations/display/service.py)

### Connectivity change awareness

The runtime tells `CloudManager` when backend/network connectivity changes:

- connected -> trigger auth/config work immediately
- disconnected -> mark cloud offline

Relevant references:

- [yoyopod/app.py](../../yoyopod/app.py)

## 11. Current Device-Side Gaps Relative To Backend Expectations

The backend already handles more MQTT event types than the Python runtime clearly emits today.

Backend expects event types such as:

- `battery`
- `heartbeat`
- `connectivity`
- `location`
- `error`
- `ptt_started`
- `ptt_finished`

The Python runtime definitely includes:

- auth and refresh
- config fetch and cache
- battery publishing
- heartbeat publishing
- MQTT command receive

Current gaps or at least not-yet-clearly-wired areas from the device repo’s perspective:

- publishing `location` telemetry into the backend MQTT event contract
- publishing `connectivity` changes from the actual network manager into MQTT
- publishing `ptt_started` / `ptt_finished` in the backend envelope expected for message ingest
- publishing explicit `error` telemetry into the backend event stream
- handling more backend command types than `fetch_config`

## 12. Claiming From The Device Runtime Perspective

Current runtime code is best understood as post-provisioning and post-claim-aware, not as the surface that performs claiming itself.

Current behavior when the backend says the device is unclaimed:

- auth error code `device_unclaimed`
- cloud state becomes `unclaimed`
- next auth attempt is delayed by `claim_retry_seconds`

That gives the runtime a clean waiting-to-be-claimed state after being provisioned with runtime secrets.

What it does not currently do:

- obtain a claim token locally
- complete parent claim from the device itself

That flow belongs primarily to backend provisioning and dashboard claim UX.

## 13. Relationship To The Dashboard

The device runtime never talks to `yoyo_dash` directly.

The interaction chain is:

- `yoyo_dash` updates backend state over HTTPS
- `yoyo_end` stores config, commands, messages, and notifications
- `yoyopod-core` authenticates to `yoyo_end`, pulls config, and publishes telemetry

The dashboard then reads stored backend state back over REST.

## 14. Files Worth Watching During Future Work

If you change the device/backend integration, review these together:

- [yoyopod/integrations/cloud/manager.py](../../yoyopod/integrations/cloud/manager.py)
- [yoyopod/backends/cloud/http.py](../../yoyopod/backends/cloud/http.py)
- [yoyopod/backends/cloud/mqtt.py](../../yoyopod/backends/cloud/mqtt.py)
- [yoyopod/config/models/](../../yoyopod/config/models/)
- [yoyopod/core/bootstrap/__init__.py](../../yoyopod/core/bootstrap/__init__.py)
- [yoyopod/core/loop.py](../../yoyopod/core/loop.py)
- [yoyopod/integrations/power/service.py](../../yoyopod/integrations/power/service.py)
- [tests/config/test_cloud_config_manager.py](../../tests/config/test_cloud_config_manager.py)

Pair those with:

- backend canonical doc in `yoyo_end/docs/DEVICE_PROVISIONING_AND_CLOUD_FLOW.md`
- dashboard canonical doc in `yoyo_dash/docs/BACKEND_DEVICE_INTEGRATION.md`
