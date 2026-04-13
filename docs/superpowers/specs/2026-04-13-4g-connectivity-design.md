# 4G Cellular Connectivity — Design Spec

**Date:** 2026-04-13
**Hardware:** Waveshare SIM7600G-H 4G HAT B (pogo pin UART connection)
**Target:** Raspberry Pi Zero 2W

---

## Summary

Add a cellular connectivity layer to YoyoPod using the Waveshare SIM7600G-H 4G HAT B. The modem connects via 4-pin pogo connector (UART only — no USB). The module provides three capabilities:

1. **4G internet** — PPP data session over UART for VoIP calls
2. **Modem telemetry** — signal strength, carrier, SIM status surfaced in the UI
3. **GPS on demand** — lat/lng coordinates returned when requested by a backend

Audio for VoIP calls uses the Whisplay's mic and speaker, not the modem's audio codec.

---

## Approach

**Layered AT Backend — App Owns Modem, OS Owns PPP**

The app owns the modem lifecycle via AT commands (init, registration, GPS) on `/dev/ttyUSB2`. For the data path, the app configures the modem's PDP context via AT commands then hands off to `pppd` as a managed subprocess on `/dev/ttyUSB3` — following the existing `MpvProcess` pattern. Since AT and PPP use separate USB ports, telemetry and GPS queries work during active PPP sessions without interruption.

---

## Package Structure

```
yoyopy/network/
├── __init__.py
├── backend.py          # NetworkBackend protocol + Sim7600Backend
├── transport.py        # UART serial transport (pyserial)
├── at_commands.py      # AT command builder/parser
├── ppp.py              # pppd subprocess manager (MpvProcess-style)
├── gps.py              # GPS query and coordinate parsing
├── models.py           # ModemState, GpsCoordinate, NetworkInfo, config models
└── manager.py          # App-facing facade (like VoIPManager, PowerManager)
```

---

## Transport Layer

`SerialTransport` wraps `pyserial` for `/dev/ttyUSB2` (configurable). Provides:

- `send_command(cmd: str, timeout: float) -> str` — send AT command, return response
- `open()` / `close()` — lifecycle
- Thread lock for serial port access (one command at a time)

**Validated discovery:** The SIM7600G-H exposes 5 USB serial ports via the pogo pin connector:

| Port | Purpose |
|---|---|
| `/dev/ttyUSB0` | Diagnostic |
| `/dev/ttyUSB1` | GPS NMEA |
| `/dev/ttyUSB2` | **AT commands** (primary) |
| `/dev/ttyUSB3` | **Modem/PPP data** |
| `/dev/ttyUSB4` | Audio |

Because AT commands and PPP use separate USB ports, there is no serial sharing problem. GPS queries, telemetry, and PPP all work simultaneously. CMUX is not needed.

---

## AT Command Layer

Thin typed wrapper over raw AT strings in `at_commands.py`. Methods return parsed dataclasses:

- `check_sim() -> SimStatus` — `AT+CPIN?`
- `get_signal_quality() -> SignalInfo` — `AT+CSQ`
- `get_registration() -> RegistrationStatus` — `AT+CREG?` / `AT+CEREG?`
- `get_carrier() -> CarrierInfo` — `AT+COPS?`
- `get_network_type() -> str` — derive 2G/3G/4G from registration info
- `configure_pdp(apn: str)` — `AT+CGDCONT`
- `enable_gps()` — `AT+CGPS=1`
- `query_gps() -> GpsCoordinate | None` — `AT+CGPSINFO`
- `hangup()` — `ATH`
- `radio_off()` — `AT+CFUN=0`

---

## Modem Lifecycle

State machine:

```
OFF → PROBING → READY → REGISTERING → REGISTERED → PPP_STARTING → ONLINE
                                                                      ↓
                                                        PPP_STOPPING → REGISTERED
```

**Startup sequence** (driven by `Sim7600Backend`):

1. **Probe** — open serial, send `AT`, wait for `OK`. Retry with backoff.
2. **Init** — `ATE0` (echo off), `AT+CPIN?` (SIM ready), `AT+CSQ` (signal), `AT+COPS?` (carrier).
3. **Register** — `AT+CREG?` / `AT+CEREG?` to confirm network registration.
4. **Snapshot telemetry** — signal strength, carrier name, network type → store in `ModemState`, publish to EventBus.
5. **Enable GPS** — `AT+CGPS=1` (stays on).
6. **Start PPP** — configure PDP context, launch `pppd`.

**Shutdown:** Kill `pppd`, send `ATH`, optionally `AT+CFUN=0`.

---

## PPP Subprocess Management

`PppProcess` follows the `MpvProcess` pattern:

- Spawns `pppd` with serial device, APN, and dial options.
- Monitors stdout/stderr for link-up/link-down events.
- Publishes `NetworkEvent.PPP_UP` / `NetworkEvent.PPP_DOWN` on the EventBus.
- On unexpected death: re-probe modem, re-establish PPP with backoff.

---

## GPS Module

`GpsReader` class:

- `enable()` — `AT+CGPS=1`, called during modem init.
- `query() -> GpsCoordinate | None` — `AT+CGPSINFO`, parses NMEA-style response. Returns `None` if no fix.

`GpsCoordinate` dataclass: `lat`, `lng`, `altitude`, `speed`, `timestamp`.

GPS queries use the AT command port (`/dev/ttyUSB2`) which is separate from the PPP data port (`/dev/ttyUSB3`), so GPS works during active PPP sessions without interruption.

---

## EventBus Integration

New events in `yoyopy/events.py`:

- `NetworkEvent.MODEM_READY` — modem probed and initialized
- `NetworkEvent.REGISTERED` — attached to cellular network
- `NetworkEvent.PPP_UP` / `NetworkEvent.PPP_DOWN` — internet connectivity state
- `NetworkEvent.SIGNAL_UPDATE` — signal strength / carrier info changed
- `NetworkEvent.GPS_FIX` — GPS coordinate available after on-demand query

---

## UI Surface

**No new screens.** The existing status bar in the Graffiti Buddy theme already renders signal bars and connection type.

- `AppContext.signal_strength` (0-4 bars) ← mapped from `AT+CSQ` raw value (0-31)
- `AppContext.connection_type` ← `"4g"` when PPP is up, `"none"` otherwise

**VoIP interaction:** `YoyoPodApp` waits for `NetworkEvent.PPP_UP` before starting SIP registration. If PPP drops, VoIP gets a network-down signal and the call coordinator handles it (same path as WiFi loss today).

---

## Configuration

Config model added to `yoyopy/config/models.py`:

```python
class NetworkConfig:
    enabled: bool = False
    serial_port: str = "/dev/ttyUSB2"
    ppp_port: str = "/dev/ttyUSB3"
    baud_rate: int = 115200
    apn: str = ""
    pin: str | None = None
    gps_enabled: bool = True
    ppp_timeout: int = 30
```

YAML in `config/yoyopod_config.yaml`:

```yaml
network:
  enabled: false
  serial_port: /dev/ttyUSB2
  ppp_port: /dev/ttyUSB3
  baud_rate: 115200
  apn: "your-carrier-apn"
  gps_enabled: true
```

Env overrides:

- `YOYOPOD_MODEM_PORT` — serial device path
- `YOYOPOD_MODEM_APN` — carrier APN
- `YOYOPOD_MODEM_BAUD` — baud rate

**`network.enabled: false` by default** — opt-in, existing WiFi setups unaffected.

---

## CLI Commands

Under `yoyoctl pi network`:

- `yoyoctl pi network status` — modem state, signal, carrier, PPP up/down
- `yoyoctl pi network gps` — query GPS fix, print coordinates
- `yoyoctl pi network probe` — check if modem responds to AT commands

Remote variant:

- `yoyoctl remote network --host rpi-zero`

Follows existing patterns (`yoyoctl pi power battery`, `yoyoctl pi voip check`).

---

## Demo GPS Server

Minimal FastAPI app at `demos/demo_gps_server.py`, runs **on the Pi** alongside the YoyoPod app:

- `GET /location` — calls `NetworkManager.query_gps()` in-process, returns `{ lat, lng, altitude, speed, timestamp }`
- `GET /health` — modem status, signal, carrier from cached `ModemState`

For quick testing without the server: `yoyoctl pi network gps` over SSH.

---

## Pi Setup Requirements (one-time)

- Disable ModemManager: `sudo systemctl disable ModemManager`
- Install pppd: `sudo apt install ppp`
- Add `pyserial` as project dependency
- User in `dialout` group for serial access
- Connect both LTE and GPS antennas to the HAT

---

## Deferred to Future Iterations

- **SMS support** — not needed for demo
- **WiFi/4G failover** — always 4G for now
- **Proper tracking backend** — replace demo server with real API
- **Modem audio codec** — calls use Whisplay audio, not modem audio
- **Policy routing** — route VoIP traffic over 4G while keeping SSH on WiFi
