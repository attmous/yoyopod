# Pillar-by-Pillar Hardware Validation

Use this runbook when a Pi has been idle, its hardware state is uncertain,
or an integrated failure needs to be reduced to one subsystem. Validate in
order: later pillars rely on the earlier ownership and provenance contracts.

## Evidence Rules

- Only one lane may own hardware. `yoyopod target mode status` must show
  either dev or prod active, never both.
- Source and binaries must be the same commit. The installed
  `device/runtime/build/ARTIFACT_SHA` must equal `git rev-parse HEAD`.
- Stop the integrated service before starting a standalone hardware worker.
  `yoyopod target validate` does this for its UI stages and restores the
  service on exit.
- Record `PASS`, `FAIL`, or `BLOCKED`. Use `BLOCKED` only when required
  hardware, credentials, another endpoint, or user interaction is absent.
- A worker process being alive is not a pass. Require a domain-specific
  result and then repeat the check through the integrated runtime.

## Validation Order

| # | Pillar | Isolated evidence | Pass condition |
|---|---|---|---|
| 1 | Operator and artifact provenance | Pushed commit, successful ARM64 CI artifact, SHA marker | Checkout, marker, reported deploy SHA, and CI artifact name all match |
| 2 | Lane and lifecycle ownership | Dev/prod service state, SIGTERM stop, PID and worker sweep | One lane active; stop removes runtime, workers, and PID; restart creates a fresh PID |
| 3 | Config, runtime, and protocol | Runtime `--dry-run`, required config and worker binary checks | Config loads and every Rust worker from the exact artifact is executable |
| 4 | UI, LVGL, display, and button | Smoke/navigation/LVGL stages, shadow and readback screenshots, physical button action | One UI host owns the panel, frames advance, screenshots are coherent, and button input changes the expected screen |
| 5 | PiSugar power | PiSugar server query plus power-worker health | I2C is connected and battery/charging values are returned without transport errors |
| 6 | SIM7600 network and GPS | USB/serial enumeration plus network-worker snapshot | Stable modem ports resolve, AT transport responds, and PPP/GPS state is reported accurately |
| 7 | WM8960 audio and local media | ALSA playback/capture enumeration and a known local track | The media worker controls mpv and audible progress advances through the configured sound card |
| 8 | Liblinphone VoIP | SIP registration followed by a real two-endpoint call | Registration reaches `ok`; ring, answer, microphone, speaker, and hang-up all work |
| 9 | Speech, STT, Ask, and TTS | PCM capture, STT/Ask response, generated TTS playback | Recorded speech is transcribed, Ask returns a response, and TTS is audible on the device |
| 10 | Cloud provisioning and MQTT | Cloud status plus a fresh heartbeat | Device is provisioned, MQTT is connected, and heartbeat/command timestamps advance |
| 11 | Integrated runtime stability | All workers under one runtime, logs, physical end-to-end flows | No duplicate owners or restart loop; all available pillars stay healthy together |

## Standard Flow

```powershell
yoyopod target mode status
yoyopod target deploy --branch <branch> --sha <sha>
yoyopod target validate --sha <sha> --with-lvgl-soak --with-navigation
yoyopod target status
yoyopod target logs --errors --lines 200
```

After the automated stages, complete the physical checks that automation
cannot prove: panel appearance, side-button input, audible playback, a
two-endpoint call, and spoken STT/TTS. Never convert a missing PiSugar,
SIM7600, SIP peer, or user interaction into a software pass or failure.

## Recovery Record

For each run, record:

- branch, full commit SHA, PR, CI run, and artifact name
- Pi model and lane/service owner
- one row per pillar with status, command, and decisive output
- screenshots or audio/call observations where required
- physical blockers and the exact reconnection or interaction needed
- integrated runtime PID, worker list, and post-validation error log
