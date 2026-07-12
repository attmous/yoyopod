# Project Review: Investor-Demo Readiness

Date: 2026-07-12
Scope: full-repo review of implemented features vs. gaps, with a
detailed per-feature code review, plus a prioritized plan for a **live
device demo for investors in ~2–4 weeks**. Demo format: the investor
holds the real device. A parent-facing backend/dashboard exists in a
separate repo and can drive the device over MQTT.

Like [`../ROADMAP.md`](../ROADMAP.md), this is an honesty doc: what
works, what doesn't, and what to do about it in the demo window.

## Executive summary

The device runtime is real, deep, and largely demo-ready: ~36k lines of
Rust across 11 crates, with working integrations against mpv,
liblinphone, the SIM7600 modem, PiSugar, MQTT, and OpenAI. There is no
stubbed product code in `device/` — the stubs live in operator tooling
(`yoyopod target validate`, prod release pipeline), which is mid-rebuild
per [`../ROADMAP.md`](../ROADMAP.md).

Three findings dominate:

1. **Calls don't run on the current device image.** The VoIP crate is
   complete (~5.7k LOC, real liblinphone), but the host `dlopen`s
   `liblinphone.so` at runtime and the library is missing from the
   prototype image. SIP account config also ships empty. This is
   packaging + provisioning, not new code — and it also degrades
   **Ask**, whose mic capture runs through the VoIP worker's recorder.
2. **The device has no second chances.** The supervisor never respawns
   a crashed worker, mpv is never restarted after it dies, a single
   5-second UI stall leaves a sticky error screen until reboot, and any
   cloud hiccup freezes Ask on "Thinking" forever. Happy paths are
   solid; every failure path is a dead end. For a hand-held demo this
   is the top reliability theme.
3. **The remote-playback "wow-moment" is not wired in the Rust
   runtime.** `play_track`/`store_media` from the dashboard are
   explicitly NACKed as `unsupported_command`
   (`device/runtime/src/event.rs:733`). The validation notes in
   [`../features/REMOTE_PLAYBACK.md`](../features/REMOTE_PLAYBACK.md)
   describe the retired Python runtime (`yoyo-py`, line 3). The
   building blocks (media cache, import commands) all exist — the
   orchestration between cloud command and media worker is missing.
   Conversely, **location is closer than the docs claim**: the
   `location.fix` telemetry publisher already exists; the only gap is
   that GPS is queried exactly once at boot.

Ratings: ✅ demo-ready · 🟡 works with caveats · 🔴 not demonstrable today.

| Feature | Rating | One-liner |
|---|---|---|
| Music | ✅ | Happy path hardware-validated; no crash recovery, no resume after call |
| Calls & voice messages | 🔴 | Code complete; liblinphone missing on image, SIP unprovisioned, no whitelist |
| Ask | 🟡 | Full loop works; every failure path freezes on "Thinking" |
| Location & connectivity | 🟡 | Modem/PPP solid; GPS queried once at boot; 4G recovery too slow for stage |
| Cloud & remote control | 🟡 | Transport/telemetry solid; play_track/store_media NACKed; reconnect fragile |
| Power & battery | 🟡 | Telemetry/safety solid; silent auto-shutdown could kill the demo |
| UI & interaction | 🟡 | 18 screens, clean navigation; sticky error overlay, placeholder Setup pages |
| Operator tooling | 🟡 | `target deploy` polished; no prod pipeline, `validate` stub, CLI has no CI |

**The 2–4 week cut-line:** bring VoIP up on the device image, fix the
small set of demo-survival reliability bugs, and script + soak a
golden-path demo. Wiring the remote-playback wow-moment and live GPS
are the two best stretch goals. Everything else waits.

## Feature reviews

Each section: what works (with code evidence), what's good, what needs
fixing — tagged **[DEMO]** demo-critical, **[POLISH]** nice for the
demo, **[POST]** post-demo.

### Music

**Works today.** Play/pause/resume/stop/next/prev over mpv JSON-IPC
(`device/media/src/host.rs:742`), state-aware play/pause toggle from
the UI (`device/runtime/src/event.rs:341`); recursive `.m3u` playlist
discovery (`device/media/src/library.rs:83`); shuffle-all with a clear
error on an empty library (`host.rs:227`); recents persisted as JSON,
deduped, capped at 50 (`device/media/src/recents.rs:98`); volume
clamped 0–100 plus voice volume up/down; ALSA device selection at
spawn and runtime; auto-**pause** when a call starts
(`event.rs:848`); SHA-256-verified remote media cache with LRU pruning
and traversal-safe filenames (`device/media/src/remote_cache.rs:97`).
mpv connect has a 10s retry deadline with stale-socket cleanup.

**Good.** Trait seams (`MediaRuntime`, `MpvIpcTransport`,
`ProcessSpawner`) make the stack testable without real mpv; the IPC
client correlates request ids on a dedicated reader thread with timeout
cleanup (`mpv_ipc.rs:86`); every mpv reply is checked for
`error: success`; corrupt recents degrade to empty instead of crashing.

**Needs fixing.**
- **[DEMO] No mpv crash recovery.** mpv death is detected and reported
  (`host.rs:800`) but nothing respawns it — `ensure_runtime_started`
  only starts from cold (`host.rs:339`), the runtime ignores
  `media.backend_availability_changed` (`event.rs:252`), and
  `MpvProcess::respawn` (`mpv_process.rs:122`) is never called. If mpv
  dies mid-demo, music is dead until service restart.
- **[DEMO] `auto_resume_after_call` is config fiction.** Parsed
  (`config/audio/music.yaml:8`, `runtime/src/config.rs:54`) but never
  consumed; music pauses for a call and stays paused.
- **[POLISH] Volume state snaps back to default.** Snapshots carry only
  `default_volume` (`host.rs:321`), and `apply_media_snapshot` falls
  back to it (`state.rs:907`), so displayed volume resets to 100 after
  every snapshot and repeated voice "volume down" recomputes from 100.
  `get_volume` (`host.rs:770`) is never called. Related: the configured
  `default_volume` is never actually applied to mpv at spawn.
- **[POLISH]** Manual track-skip briefly emits `TrackChanged(None)`
  before the next `FileLoaded` (`host.rs:621`) — UI can flash "Nothing
  Playing". One unreadable subdirectory aborts the whole library scan
  (`library.rs:140`) — playlists silently appear empty.
- **[POST]** Every mpv `time-pos` tick (~4/sec) triggers a full
  `media.snapshot` → cloud `music.state` telemetry spam
  (`media/src/worker.rs:189`, `event.rs:809`). Failed commands mark the
  worker Degraded with no auto-clear (`event.rs:248`).

**Bottom line:** the strongest pillar; happy path is demo-ready today.
The work is recovery (mpv respawn) and honoring the resume-after-call
promise.

### Calls & voice messages

**Works today (in code).** Registration with password/HA1 auth
(`device/voip/src/host.rs:175`, `liblinphone/runtime.rs:82`); dial,
answer, reject, hangup, mute (`device/voip/src/worker.rs:235`);
incoming/outgoing/in-call screens preempt navigation
(`device/ui/src/router/guards.rs:3`); SIP text messages with
client↔backend id translation (`voip/src/messages.rs:94`); voice notes
recorded via the liblinphone recorder, sent as file transfer, played
via aplay (`liblinphone/runtime.rs:427`, `playback.rs:21`); delivery
states, per-contact unread counts, persisted message store
(`message_store.rs:64`); call history with
completed/missed/rejected/cancelled outcomes (`calls.rs:61`); contacts
seeded from `config/people/contacts.seed.yaml` with voice-dial aliases
("mama") and a voice-call confirmation flow; music auto-pauses on call
activity.

**Good.** Clean layering — all call/message logic lives in a pure
`VoipHost` behind a `VoipRuntimeBackend` trait, testable without
liblinphone; dlopen-based FFI shim reports per-symbol errors;
snapshot-after-every-event keeps UI state convergent.

**Needs fixing.**
- **[DEMO] liblinphone missing on the Pi image.** CI builds the binary
  with `native-liblinphone` on a native arm64 runner
  (`.github/workflows/ci.yml`), so the artifact is fine — it does not
  link liblinphone; it `dlopen`s `liblinphone.so` / `.so.12` / `.so.11`
  at runtime (`voip/src/liblinphone/ffi.rs:631`). Fix is on-device:
  install `liblinphone-dev` (already documented in
  [`../operations/SETUP_CONTRACT.md`](../operations/SETUP_CONTRACT.md))
  — the `-dev` package provides the unversioned `.so` symlink the
  candidate list needs — then verify symbol resolution (recorder APIs
  are version-sensitive, `runtime.rs:502`). This also restores Ask's
  mic path.
- **[DEMO] SIP accounts unprovisioned.**
  `config/communication/calling.yaml` ships empty
  `sip_username`/`sip_identity`, and `voip.configure` hard-fails on
  empty identity/server (`voip/src/config.rs:68`). Need an untracked
  `calling.secrets.yaml` (see `calling.secrets.example.yaml`) and two
  provisioned SIP accounts — device plus a parent counterpart matching
  the seeded contacts.
- **[DEMO] No recovery after failure.** `voip.register` is sent exactly
  once at boot (`runtime/src/cli.rs:328`); nothing consumes
  `recovery_pending` (`voip/src/lifecycle.rs:43`), and the supervisor
  never restarts an exited worker (`event.rs:195`). Late WiFi at boot
  or a mid-demo worker death kills calls until a full restart.
- **[DEMO-adjacent] No whitelist enforcement.** Product pillar #1 is
  *whitelist* calls, but incoming calls are surfaced unconditionally
  (`liblinphone/runtime.rs:1176`) — the caller is never checked against
  contacts, and `calling.yaml` has no whitelist key. Low practical risk
  during a demo (nobody knows the SIP URI), but "can strangers call my
  kid?" currently answers **yes** — have the roadmap answer ready.
- **[POLISH]** A second incoming call clobbers
  `state.current_call` (`runtime.rs:1160`) — answer/hangup then target
  the newest call. Audio-device contention: mpv holds ALSA while
  paused; liblinphone and aplay open the same WM8960 card — works only
  if the image's default PCM is dmix-backed; verify on hardware. Dead
  config: `auto_answer`, `ring_duration_seconds`, `priority_over_music`,
  `speed_dial` are consumed nowhere.
- **[POST]** Call history is in-memory only (`history.rs:14`); call
  duration includes ring time.

**Bottom line:** not demo-ready today, but close — the code is
genuinely complete; the gap is packaging + provisioning + a
registration retry. This is P0 #1.

### Ask (voice assistant)

**Works today.** Full loop verified end-to-end in code: PTT press/hold
routes (`device/ui/src/router/routes.rs:282`) → recording via the VoIP
worker (`device/runtime/src/event.rs:427`) → OpenAI STT with a 12s
deadline (`event.rs:867`, `device/speech/src/provider.rs:355`) →
transcript routing (`route_voice_transcript`,
`device/runtime/src/voice.rs:304`): exit phrases, local commands
(call/play/volume) with fuzzy matching and negation guards, whitelisted
navigation, LLM fallback with history → TTS → aplay playback. Mock
provider allows keyless dev; recorder failure shows "Mic Unavailable"
(`state.rs:1259`).

**Good.** Real cost controls (480-char response cap, 4-turn history,
30s max audio enforced before upload); deadline-aware HTTP timeouts and
abortable requests; single-flight worker with busy rejection and a
clean cancel protocol; warm child-oriented prompts; API key is env-only
— never in the repo.

**Needs fixing.**
- **[DEMO] Stuck "Thinking" on any cloud error.** `voice.error` only
  marks worker health (`event.rs:322`) and `voice.cancelled` is ignored
  (`event.rs:326`); neither resets `voice.phase`. Missing key, timeout,
  WiFi drop, or a busy rejection leaves the Ask screen on "Thinking —
  Finding an answer..." forever. The friendly "I cannot reach Ask right
  now" fallback (`state.rs:1174`) only fires on a malformed *success* —
  unreachable in practice.
- **[DEMO] VoIP-down = silent hang.** Command send failures are
  discarded (`runtime_loop.rs:124`) and workers are never respawned; if
  the VoIP worker is dead, `AskStart` shows "Listening" and nothing
  ever arrives — no error UX at all. (Fixing VoIP on the image reduces
  exposure, but the failure path stays a dead end.)
- **[DEMO] No LLM deadline.** `voice.ask` is issued with default
  `deadline_ms: 0` (`event.rs:580`, `protocol/src/lib.rs:74`), falling
  back to a 30s HTTP timeout — worst case is 30 silent seconds on
  stage. Set ~12s like STT/TTS.
- **[DEMO] Child-safety prompt is style-only.** The default Ask
  instructions (`voice.rs:184`) set tone and "ask a grown-up"
  deflection but contain no jailbreak hardening, no moderation, no
  output filtering — and are config-overridable to empty. An investor
  *will* ask something edgy. Harden the instructions and rehearse.
- **[POLISH]** Stale answers play after leaving the screen — the
  runtime never sends `voice.cancel` and TTS results play
  unconditionally (`event.rs:617`). Latency is 3 sequential round trips
  (STT→LLM→TTS), realistically ~5–9s per answer — rehearse the pause.
  Response truncation chops mid-word at 480 chars and TTS speaks the
  cut. Docs drift: the `YOYOPOD_CLOUD_ASK_*` env vars documented in
  [`../features/CLOUD_VOICE_WORKER.md`](../features/CLOUD_VOICE_WORKER.md)
  are read nowhere in device code.
- **[POST]** Decouple mic capture from liblinphone; `ReadScreen` and
  `MuteMic` voice commands are recognized but unwired (`event.rs:660`).

**Bottom line:** the happy path is solidly built and demoable; the
failure paths are the risk. Error-UX + deadline + prompt hardening is a
small, high-leverage fix batch.

### Location & connectivity

**Works today.** 10-state modem lifecycle
(Off→Probing→Ready→Registering→Registered→PppStarting→Online, plus
Recovering/Degraded) with exponential backoff 1s→30s
(`device/network/src/runtime.rs:26`); SIM PIN/PUK handled, PUK
correctly fatal (`modem.rs:420`); signal/carrier/registration re-polled
every 5s while online; pppd spawn with default-route detection and
health checks (`ppp.rs:247`, `modem.rs:277`); GPS `AT+CGPSINFO` parsed
to lat/lng/alt/speed (`gps.rs:13`) and — further than the docs claim —
consumed end-to-end: snapshot → Setup GPS page rows → **cloud
`location.fix` telemetry already publishes**
(`device/runtime/src/event.rs:944`).
[`../features/CLOUD_PROVISIONING_AND_BACKEND.md`](../features/CLOUD_PROVISIONING_AND_BACKEND.md)
is stale on this. With the modem disabled (default,
`config/network/cellular.yaml`) everything else runs happily on OS
WiFi.

**Good.** Clean trait seams (`ModemController`, `LineTransport`,
`PppLifecycle`) with injected probes/sleepers; snapshot dedup; stable
serial-port aliasing via `/dev/serial/by-id`; graceful `Noop` fallback
on bad config.

**Needs fixing.**
- **[DEMO if showing location] GPS is queried exactly once, at boot**
  (`device/runtime/src/cli.rs:314`). GPS cold-fix takes minutes, so the
  single query returns `no_fix` and nothing ever re-queries —
  `location.fix` is permanently false. The seam is small: add periodic
  `network.query_gps` while online (mirroring the 5s live-facts poll).
  Everything downstream already works. Estimate: 1–2 days including
  tests; +1 day if the backend must ingest `yoyopod/telemetry/*` (note:
  that topic carries no device_id, unlike `yoyopod/{id}/evt`).
- **[DEMO if demoing 4G] Recovery reboots the radio.** Any PPP flap
  triggers `AT+CFUN=6` — full modem reset, USB re-enumeration,
  realistic 30–90s reconnect on stage (`at.rs:184`, `modem.rs:300`);
  bring-up also blocks the worker loop up to 30s. Recommendation: run
  the demo on WiFi, stage 4G as a controlled showpiece.
- **[POLISH]** On WiFi-only the UI says "Offline/Disabled"
  (`connection_type` is only ever `4g`/`none`, `snapshot.rs:173`) —
  looks broken to an investor even though cloud works. `AT+CGPS=1` on
  an already-enabled GPS returns ERROR and fails the entire bring-up
  (`modem.rs:383`).
- **[POST]** GPS timestamp discarded; no data-path health check (no
  ping); `pppd persist` races runtime recovery; only 3 unit tests in
  the crate.

**Bottom line:** WiFi demo path is safe today; live 4G is risky. GPS →
dashboard is the cheapest remaining trust-anchor win.

### Cloud & remote control

**Works today.** Provisioning state machine
(unprovisioned/invalid/provisioned) gating startup
(`device/cloud/src/host.rs:59`); secrets from
`config/cloud/device.secrets.yaml`, `/etc/yoyopod/cloud/`, or env
overrides; MQTT over rustls with real cert validation (`mqtt.rs:167`),
QoS1 subscribe to `yoyopod/{id}/cmd`; telemetry: heartbeat, battery
(60s throttle), connectivity (dedup-on-change), playback, generic
telemetry with payload dedup (`host.rs:142-234`); command ACK/NACK
envelopes; bounded offline queue (32, drop-oldest, FIFO flush on
reconnect); pause/resume/stop routed to the media worker with proper
ACKs (`device/runtime/src/event.rs:729`); SHA-256-verified download
cache with LRU pruning and path confinement
(`device/media/src/remote_cache.rs`).

**Good.** Trait-abstracted MQTT backend and downloader (testable); no
credentials committed; operator-visible persisted status.json; clean
provisioning/connection separation.

**Needs fixing.**
- **[DEMO for the wow-moment] `play_track`/`store_media` are NACKed
  `unsupported_command`** (`event.rs:733`, payload even flags
  `"rust_runtime": true`).
  [`../features/REMOTE_PLAYBACK.md`](../features/REMOTE_PLAYBACK.md)
  documents the retired Python runtime (line 3: `yoyo-py`); its "Real
  Validation Notes" predate the Rust runtime. The pieces exist — cache,
  `media.prepare_remote_asset` / `media.import_remote_asset` worker
  commands (`media/src/worker.rs:366`) — but the cloud→media
  orchestration, the ack→buffering→playing lifecycle publishing, and
  duplicate `commandId` suppression are all missing in Rust. This is
  the real scope of the P1 wow-moment: wiring work, not rehearsal.
- **[DEMO] Reconnect likely loses the command subscription.** Subscribe
  is issued once pre-connect with `clean_session(true)`
  (`mqtt.rs:64-72`) and never re-issued on Connected — a broker blip
  mid-demo could silently kill remote control. No explicit backoff;
  each failure also rewrites status.json (SD-card churn while
  unreachable).
- **[DEMO] Download robustness.** `ureq::get(...).call()` with no
  timeout and no retry (`remote_cache.rs:38`); the media worker is
  sequential, so a stalled download blocks all media commands; there is
  no on-screen buffering feedback.
- **[POLISH]** No periodic heartbeat scheduler in the runtime (sent
  once from `cli.rs:310`); silently dropped queue entries include ACKs;
  missing `backend.yaml` falls back to plaintext `:1883` with TLS off.
- **[POST]** Admitted-missing: PTT events, richer error telemetry; no
  step-by-step device-claiming runbook (deferred to backend/dashboard).

**Bottom line:** transport, telemetry, and cache layers are demo-solid;
the headline dashboard→device flow needs real (but well-bounded) wiring
plus reconnect/download hardening.

### Power & battery

**Works today.** PiSugar reads (%, voltage, charging, plugged,
temperature, RTC, safe-shutdown settings) over Unix socket/TCP with
per-field error isolation (`device/power/src/host.rs:155-272`); 30s
polling; RTC sync and alarms; hardware watchdog enable/feed/disable via
i2c (off by default); runtime-owned safety policy: warn ≤20% (5-min
cooldown), auto-shutdown ≤10% after a 15s delay, external power cancels
(`device/runtime/src/state.rs:711-785`); shutdown sequence suppresses
the watchdog, persists state for post-mortem, runs `sudo -n shutdown`
(`runtime_loop.rs:99`); battery + safety events published to cloud;
Power screen pages and a status-bar battery icon.

**Good.** Trait-based backend with a clean disabled fallback; one
failed read doesn't kill the snapshot; watchdog suppression before
poweroff prevents reboot-after-shutdown loops; charger-cancels-shutdown
logic exists.

**Needs fixing.**
- **[DEMO] Silent death.** Safety actions map only to *cloud* events
  (`event.rs:997`); the UI snapshot omits warning/shutdown-pending
  state (`state.rs:1524`). At ≤10% the device powers off 15s later with
  no on-screen warning — in an investor's hand it "just dies."
- **[DEMO] Single-reading shutdown trigger + cancel race.** Raw
  percentage is used directly (`state.rs:734`) — one glitchy PiSugar
  reading arms shutdown; and since polling (30s) is slower than the
  shutdown delay (15s), plugging in a charger mid-countdown usually
  can't cancel in time. Demo profile mitigation: full charge + set
  `critical_shutdown_percent` ~3% or `auto_shutdown_enabled: false` in
  `config/power/backend.yaml`.
- **[DEMO] Stale 100% display.** If pisugar-server is down, the Power
  page honestly shows "Offline", but the status bar keeps the default
  **100%** forever (`state.rs:557`, `chrome.rs:108`) — misleadingly
  healthy. Also: if `sudo -n shutdown` fails (sudoers), the error is
  swallowed and the app exits anyway (`runtime_loop.rs:117`) — frozen
  device instead of poweroff.
- **[POLISH]** Setup sub-pages show hard-coded placeholders ("RTC:
  Unknown", "Watchdog: Off") despite tracked values (`state.rs:1694`).
  TCP connect has no timeout.
- **[POST]** Zero tests across the safety/watchdog/backend logic;
  [`../hardware/POWER_MODULE.md`](../hardware/POWER_MODULE.md) still
  references deleted Python paths.

**Bottom line:** conditionally demo-ready mostly via configuration.
Set the demo power profile, and add the on-screen low-battery warning
if time permits.

### UI & interaction

**Works today.** 18 screens in a const route table validated at worker
startup (`device/ui/src/router/routes.rs:25`); one-button input model
(50ms debounce, tap=advance, double=select, hold=back) with PTT
passthrough on Ask/VoiceNote (`input/machine.rs`); LVGL 9.5 rendering
with a reconciler, scene graph, quantized animation gating, and
dirty-rect status-bar patches; status bar with signal bars, GPS, VoIP
dot, battery (`components/widgets/status_bar.rs:16`); incoming calls
correctly preempt any screen and restore focus after hangup
(`router/guards.rs:3`, `application/navigator.rs:334`); tick-stall
watchdog (5s → error modal) and manager-silence exit (15s);
`ui.health` frame/button/patch stats.

**Good.** Declarative routing with startup validation; conservative
dirty-rect policy (low glitch risk); list widget recycling; a widget
budget guard; three-tier fallback for Power page data.

**Needs fixing.**
- **[DEMO] Sticky "Lost runtime link" error.** A single 5s tick stall
  sets a local error overlay (`application/runtime.rs:97`); the runtime
  always sends overlay-empty and full snapshots only once at startup
  (`runtime/src/state.rs:1545`, `cli.rs:331`), so no patch ever clears
  it — every subsequent patch re-preempts to the Error screen even
  after the user holds Back. Stuck until service restart. Fix: clear
  the local overlay when ticks resume, or resend full snapshots
  periodically.
- **[DEMO] Worker hard-death paths.** Widget-budget overflow `bail!`s
  out of the render apply → worker exits → frozen/blank screen
  (`renderer/lvgl_renderer.rs:51`), and the supervisor won't restart
  it. The 11k-LOC UI crate has **zero tests** — verify worst-case
  widget counts per screen before the demo.
- **[DEMO] Placeholder Setup pages.** The "Setup" tile is actually
  coherent (it opens pages titled Power/Network/GPS/Time/Care/Voice) —
  the real problem is placeholder content: "RTC Unknown", "Uptime --",
  "Watchdog Off", "Mic Unknown" (`runtime/src/state.rs:1694-1739`).
  Populate real values or hide Time/Care/Voice pages for the demo.
- **[POLISH]** Long titles: only the call title gets ellipsis; card,
  page, and list-row titles wrap inside fixed boxes and get chopped
  (`assets/layouts.ron`) — set dots/ellipsis mode on those styles.
  Status-bar "clock" shows elapsed-since-boot mm:ss capped at 99 —
  reads as a broken clock. IncomingCall shows the raw SIP address
  instead of the contact name
  (`components/screens/incoming_call.rs:15`). NowPlaying renders
  progress as plain text ("Progress: 42%") though a progress-bar
  primitive exists. Single-tap has inherent ~350ms latency from the
  300ms double-tap window — feels sluggish; consider tightening.
- **[POST]** Loading screen is unreachable (hardcoded false); check
  `ui.health` frame rates under looping Hub animations (unbounded stdin
  channel + 20ms ticks could back up behind slow SPI flushes).

**Bottom line:** architecture is solid and the happy paths look
coherent; fix the sticky error recovery, fill or hide the placeholder
pages, and batch the small visual polish.

### Operator tooling & deploy (context)

`yoyopod target deploy` is a genuinely polished single-command loop
(push → CI artifact → Pi sync → install → restart → verify) with dirty-
tree refusal — this is how the demo device gets its frozen build.
Gaps per [`../ROADMAP.md`](../ROADMAP.md): `target validate` is a
Round 2 stub; the prod release pipeline is Round 3 (no new prod
artifacts can ship — the demo runs on the dev lane); the `cli/`
workspace has no CI at all; CI runs `cargo check` + build only — no
tests, clippy, or fmt anywhere.

## Cross-cutting risks

1. **No recovery anywhere.** The supervisor never respawns crashed
   workers (`event.rs:195`); mpv is never restarted; the UI error
   overlay never clears; Ask freezes on error; VoIP registers once.
   Individually small, together they mean any single fault ends the
   demo. The demo-survival fix batch (P0 #2) targets exactly these.
2. **Test coverage ≈ 22 unit tests repo-wide**, zero in `ui`, `media`,
   `voip`, `cloud`, `power`, `speech` — and CI runs none of them. A
   regression the week before demo day lands silently.
3. **Docs vs. reality drift** (beyond what this PR fixes):
   [`../features/REMOTE_PLAYBACK.md`](../features/REMOTE_PLAYBACK.md)
   describes the retired Python runtime as current;
   [`../features/CLOUD_PROVISIONING_AND_BACKEND.md`](../features/CLOUD_PROVISIONING_AND_BACKEND.md)
   understates location wiring; documented `YOYOPOD_CLOUD_ASK_*` env
   vars are unread; several `calling.yaml` keys are dead config; stale
   Python remnants live in `deploy/scripts/launch.sh`, the prod systemd
   unit, and `deploy/pi-deploy.yaml`.
4. **Whitelist gap vs. product claim.** Pillar #1 says whitelist
   calling; the code accepts any SIP caller. Fine for a demo, bad
   diligence answer — schedule enforcement early post-demo.
5. **Parent app is out of repo.** `apps/` is a placeholder; "show me
   the parent app" is answered by the external dashboard repo.
6. **AGPL note for diligence.** Binaries linking liblinphone are
   AGPLv3 combined works (see root README). Not a blocker; have the
   answer ready.

## Prioritized plan (~2–4 weeks to demo)

### P0 — demo blockers

**1. Bring calls up on the device image.**
Install `liblinphone-dev` on the Pi image (the voip host `dlopen`s the
unversioned `.so`); verify symbol resolution; provision two SIP
accounts; fill `calling.yaml` + untracked `calling.secrets.yaml`; then
rehearse register → dial → answer → voice note on hardware, and
re-verify Ask's mic path. Add a registration retry so a WiFi hiccup at
boot can't kill calls (small runtime change; `recovery_pending` already
exists).

**2. Demo-survival reliability batch.** Small, targeted fixes to the
"no second chances" theme — each is hours, not days:
- clear the sticky UI "Lost runtime link" overlay when ticks resume
- map `voice.error`/`voice.cancelled`/failed sends to a friendly Ask
  fallback (spoken + shown) with phase reset; set `deadline_ms` ≈ 12s
  on `voice.ask`
- respawn mpv on IPC disconnect (`MpvProcess::respawn` already exists)
- demo power profile: full charge, `critical_shutdown_percent` ≈ 3% or
  auto-shutdown off; fix the stale-100% status-bar fallback if time
  permits
- harden the Ask child-safety instructions and rehearse edgy questions

**3. Golden-path demo script + device prep + soak.**
Scripted ~10-minute flow (boot → Hub → Listen: playlist/shuffle/
now-playing → Talk: live call + voice note → Ask: one rehearsed
question → Power screen), preloaded music, seeded contacts, frozen
known-good SHA deployed via `target deploy`, repeated end-to-end soak,
rehearsed recovery (service restart, power-cycle), fallback narrative
(screenshots + tour GIF in `docs/assets/readme/`). Decide the venue
network now: **WiFi recommended**; 4G as a staged showpiece only.

### P1 — high value if time permits

**4. Wire the remote-playback wow-moment.** Route `play_track` /
`store_media` from the cloud command handler to the existing
`media.prepare_remote_asset`/`media.import_remote_asset` commands,
publish the ack→buffering→playing lifecycle, add duplicate-commandId
suppression, a download timeout, and resubscribe-on-reconnect. The
validated Python-era contract in REMOTE_PLAYBACK.md is the spec.
Roughly 3–5 days including hardware validation — the single biggest
P1 item, and the best demo moment with the existing dashboard.

**5. Live location.** Add periodic `network.query_gps` while online —
the `location.fix` telemetry publisher already exists, so this is
~1–2 days device-side (plus confirming backend ingestion of
`yoyopod/telemetry/*`). Fix the `AT+CGPS=1`-already-enabled bring-up
failure (~half day) if 4G is in the demo.

**6. Minimal CI hardening.** Add `cargo test` + clippy for the device
workspace and a build/test job for `cli/`. Hours of work; protects the
frozen-SHA window from silent regressions.

**7. Visible-polish batch (pick from):** resume music after call
(`auto_resume_after_call`), contact name on IncomingCall, ellipsis on
long titles, NowPlaying progress bar, hide placeholder Setup pages,
real volume reporting.

### P2 — post-demo

- Whitelist enforcement for incoming calls (product claim #1).
- Supervisor worker-respawn policy (the systemic fix for the
  reliability theme).
- Round 2 (`target validate`) and Round 3 (prod release pipeline).
- Test-coverage buildout (the unused `device/harness/` helpers are the
  starting point); UI crate especially.
- Update stale docs (REMOTE_PLAYBACK.md to the Rust contract, cloud
  provisioning doc, CLOUD_VOICE_WORKER env vars); purge Python
  remnants from prod deploy scripts.
- Power productization backlog
  ([`../hardware/POWER_MODULE.md`](../hardware/POWER_MODULE.md)).

## Demo-day runbook sketch

- **Hardware:** primary device charged + a charged spare; second call
  endpoint (parent phone with SIP client) tested; power bank; the
  frozen SHA deployed to both devices.
- **Network:** WiFi as primary (verify at the venue in the morning);
  4G only as a staged showpiece — its recovery path takes 30–90s if it
  flaps. MQTT broker + OpenAI reachability checked morning-of.
- **Power profile:** demo config applied (shutdown threshold lowered
  or disabled); start >80% charge; charger on hand.
- **Reset procedure:** if the device wedges, `yoyopod target restart`
  or power-cycle — both rehearsed. Screenshots/GIF ready if hardware
  fails entirely.
- **Q&A prep:** parent app (separate repo — show the dashboard),
  whitelist enforcement (roadmapped), AI disclosure for Ask,
  AGPL/liblinphone licensing, "when can you ship?" (Round 3 restores
  the release pipeline; see [`../ROADMAP.md`](../ROADMAP.md)).
