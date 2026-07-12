# Project Review: Investor-Demo Readiness

Date: 2026-07-12
Scope: full-repo review of implemented features vs. gaps, plus a
prioritized plan for a **live device demo for investors in ~2–4 weeks**.
Demo format: the investor holds the real device. A parent-facing
backend/dashboard exists in a separate repo and can drive the device
over MQTT.

Like [`../ROADMAP.md`](../ROADMAP.md), this is an honesty doc: what
works, what doesn't, and what to do about it in the demo window.

## Executive summary

The device runtime is real, deep, and largely demo-ready: ~36k lines of
Rust across 11 crates, with working integrations against mpv,
liblinphone, the SIM7600 modem, PiSugar, MQTT, and OpenAI. There is no
stubbed product code in `device/` — the stubs live in operator tooling
(`yoyopod target validate`, prod release pipeline), which is mid-rebuild
per [`../ROADMAP.md`](../ROADMAP.md).

The gap that matters for investors: the product's two **trust anchors**
([`../product/PRODUCT_DEFINITION.md`](../product/PRODUCT_DEFINITION.md))
are the weakest links in practice today.

1. **Calls/voice messages**: fully implemented in `device/voip/`
   (~5.7k LOC, real liblinphone), but the native liblinphone backend is
   **unavailable on the current device image**
   ([`../features/REMOTE_PLAYBACK.md`](../features/REMOTE_PLAYBACK.md),
   Real Validation Notes). The voip host hard-exits without it. This
   also degrades **Ask**, which captures mic audio through the VoIP
   worker's recorder.
2. **Live location**: GPS fix querying exists in `device/network/`, but
   location telemetry is not wired end-to-end to the cloud host
   ([`../features/CLOUD_PROVISIONING_AND_BACKEND.md`](../features/CLOUD_PROVISIONING_AND_BACKEND.md)).

Everything else needed for a strong hand-held demo — music, playlists,
shuffle, now-playing, remote dashboard-pushed playback, battery/power
UX, physical navigation — works and has been validated on real
hardware.

**The 2–4 week cut-line:** fix VoIP on the device image, script and
soak a golden-path demo, and rehearse the remote-playback wow-moment
with the existing dashboard. Location wiring is the best stretch goal.
Everything else waits.

## Implemented-feature inventory

Ratings: ✅ demo-ready · 🟡 works with caveats · 🔴 not demonstrable today.

| Domain | Rating | What actually works | Evidence |
|---|---|---|---|
| Music (`device/media/`) | ✅ | mpv subprocess + JSON-IPC: play/pause/resume/stop, next/prev, volume, m3u playlists, shuffle-all, recents (persisted), now-playing metadata, remote media cache/import (sha256, LRU) | `device/media/src/host.rs`, `library.rs`, `recents.rs`; hardware-validated per [`../features/LOCAL_FIRST_MUSIC_PLAN.md`](../features/LOCAL_FIRST_MUSIC_PLAN.md) |
| Remote playback (MQTT) | ✅ | Dashboard-driven `play_track`/`store_media` with ack/buffering/playing lifecycle, duplicate-command suppression, offline queueing | Validated on the real `piz` device — [`../features/REMOTE_PLAYBACK.md`](../features/REMOTE_PLAYBACK.md) |
| UI (`device/ui/`, 11k LOC) | ✅ | 18 screens (Hub, Listen, Playlists, RecentTracks, NowPlaying, Ask, Talk, Contacts, CallHistory, VoiceNote, call screens, Power…), LVGL 9.5 via FFI, data-driven navigation, dirty-rect rendering, Whisplay + mock hardware modes | `device/ui/src/router/routes.rs`, `device/ui/src/components/screens/` |
| Power (`device/power/`) | ✅ | PiSugar over TCP: battery %, charging, temperature, RTC sync/alarm, hardware watchdog; runtime-owned low-battery warning + auto-shutdown | `device/power/src/host.rs`, `device/runtime/src/runtime_loop.rs` |
| Network (`device/network/`) | 🟡 | SIM7600 modem lifecycle state machine (probe→register→PPP online, degraded/recovery backoff), SIM PIN/PUK, 4G via pppd, GPS fix query | `device/network/src/runtime.rs`, `modem.rs`, `ppp.rs`, `gps.rs`. Caveat: GPS data goes nowhere yet (see gaps) |
| Cloud (`device/cloud/`) | 🟡 | MQTT (rustls) provisioning state machine, heartbeat/battery/connectivity/playback telemetry, command receive + ACK/NACK, bounded offline queue | `device/cloud/src/host.rs`, `mqtt.rs`. Caveat: no location or PTT telemetry wired |
| Speech / Ask (`device/speech/`) | 🟡 | Full voice loop: OpenAI STT → local command routing / LLM fallback → TTS, conversation history, deadlines/cancellation | `device/speech/src/provider.rs`, `device/runtime/src/voice.rs`. Caveat: mic capture depends on the VoIP worker (`device/runtime/src/event.rs`), so it degrades on images where VoIP is down |
| VoIP (`device/voip/`, 5.7k LOC) | 🔴 | Register, dial, answer/reject/hangup, mute, SIP text messages, voice-note record/send/play, call history, persisted message store — all implemented against real liblinphone | `device/voip/src/host.rs`, `liblinphone/`. Blocker: native backend unavailable on the current device image; binary exits without the `native-liblinphone` feature (`device/voip/src/main.rs`) |
| Operator CLI (`cli/`) | 🟡 | `target deploy` end-to-end (push → CI artifact → Pi sync → install → restart → verify), status/restart/logs/screenshot, dev/prod mode switch | `cli/yoyopod/src/commands/target/`. Caveats: `target validate` is a Round 2 stub; no prod release surface (Round 3) |
| Deploy (`deploy/`) | 🟡 | Two-lane model (dev checkout / prod slots), idempotent Pi bootstrap, install with live-probe + atomic symlink flip + rollback-on-failure | `deploy/scripts/`. Caveats: no new prod slot artifacts can be built; install preflight is a no-op |

## Gap and risk register

1. **VoIP absent from the device image** (blocker). The largest feature
   investment in the repo is invisible in a live demo, and it is the #1
   trust anchor for parents. This is a packaging/bring-up problem, not
   a code problem.
2. **Location telemetry unwired** (trust anchor #2). GPS query code and
   cloud telemetry publishing both exist; the runtime wiring between
   them is the admitted missing piece
   ([`../features/CLOUD_PROVISIONING_AND_BACKEND.md`](../features/CLOUD_PROVISIONING_AND_BACKEND.md)).
3. **No prod release capability** (Round 3 of the CLI rebuild) and no
   automated hardware validation (`target validate`, Round 2). The demo
   must run on the **dev lane** from a frozen known-good SHA.
4. **CI runs no tests.** `rust-device-arm64` does `cargo check` + build
   only; the `cli/` workspace has no CI at all; ~22 unit tests exist
   repo-wide, none in `ui`, `media`, `voip`, `cloud`, `power`, or
   `speech`. Risk during the demo window: a regression lands silently
   the week before demo day.
5. **Parent app is out of repo.** `apps/` is a placeholder. The parent
   story depends on the external backend/dashboard repo; "show me the
   parent app" gets answered there, not here.
6. **Docs vs. reality drift** (partially fixed alongside this review):
   README marketed calls/location as current capabilities; age range
   was inconsistent (7–13 vs 7–14);
   [`../features/CLOUD_VOICE_WORKER.md`](../features/CLOUD_VOICE_WORKER.md)
   called the Rust speech host a "Go" worker. Remaining known drift:
   the Hub's fourth tile is labelled "Setup" but routes to the Power
   screen (`device/protocol/src/ui/snapshot.rs`,
   `device/ui/src/router/routes.rs`); stale Python remnants live in
   `deploy/scripts/launch.sh`, the prod systemd unit, and
   `deploy/pi-deploy.yaml` (harmless for old slots, but contradicts the
   "Rust-only" narrative under technical diligence).
7. **Licensing note for diligence.** Distributed binaries linking
   liblinphone are AGPLv3 combined works (see `LICENSE` discussion in
   the root README). Not a demo blocker; have the answer ready.

## Prioritized plan (~2–4 weeks to demo)

### P0 — demo blockers

**1. Get VoIP running on the device image.**
Build/install the native liblinphone dependencies on the prototype
image (CI already builds the voip host with `native-liblinphone` — the
gap is on-device runtime libraries), configure SIP accounts, and verify
register → dial → answer → voice note on hardware against a second
endpoint (second device or a softphone). Then re-verify Ask, since its
mic path runs through the VoIP recorder. This single item turns the
demo from "music player" into "the product we pitched."

**2. Golden-path demo script + device prep.**
A scripted ~10-minute flow with the device in the investor's hands:
boot → Hub → Listen (playlist, shuffle, now-playing) → Talk (live call
+ voice note) → Ask (one rehearsed question) → Power/battery screen.
Preload music, seed contacts (`config/people/directory.yaml`), charge,
and prepare the fallback narrative (screenshots + tour GIF in
`docs/assets/readme/`) in case hardware misbehaves.

**3. Demo-day reliability.**
Freeze a known-good SHA and soak the golden path on it repeatedly.
Verify watchdog and service-restart recovery behave when things go
wrong mid-demo. Keep `yoyopod target deploy` and `target screenshot`
ready as the rollback/recovery story: redeploying the frozen SHA is the
"known-good reset."

### P1 — high value if time permits

**4. Remote-playback wow-moment.**
Rehearse the dashboard→device flow with the existing external backend:
parent pushes a track from the dashboard, the device in the investor's
hand starts playing it. Already validated once on `piz`
([`../features/REMOTE_PLAYBACK.md`](../features/REMOTE_PLAYBACK.md));
this is rehearsal + configuration, not new code.

**5. Wire location telemetry end-to-end.**
Publish the GPS fix through the cloud host so the dashboard can show
"the device is here." Closes trust anchor #2 and completes the
parent-peace-of-mind pitch. Modest, well-bounded runtime wiring between
two components that already exist.

**6. Minimal CI hardening.**
Add `cargo test` + clippy for the device workspace and a build/test job
for `cli/` to `.github/workflows/ci.yml`. Hours of work; protects the
demo window from silent regressions.

### P2 — post-demo

- Round 2: restore hardware validation (`target validate`).
- Round 3: restore the prod release pipeline (currently no new prod
  artifacts can ship).
- Test-coverage buildout across the domain crates (the
  `device/harness/` helpers exist and are essentially unused).
- Either build a real Setup screen or relabel the Hub tile "Power."
- Power productization backlog
  ([`../hardware/POWER_MODULE.md`](../hardware/POWER_MODULE.md)):
  settings UI, alarm scheduling, battery history.
- Purge Python remnants from `deploy/scripts/launch.sh`, the prod
  systemd unit, and `deploy/pi-deploy.yaml`.

## Demo-day runbook sketch

- **Hardware:** primary device charged + a charged spare; second call
  endpoint tested; power bank; the frozen SHA deployed to both.
- **Network:** decide 4G vs. venue WiFi in advance and test the chosen
  path at the venue; have the other as fallback. MQTT broker and
  OpenAI reachability checked the morning of.
- **Reset procedure:** if the device wedges mid-demo, restart the
  service (`yoyopod target restart`) or power-cycle; both paths
  rehearsed. Screenshots/GIF ready if hardware fails entirely.
- **Q&A prep:** parent app (separate repo — show the dashboard),
  AGPL/liblinphone licensing, "when can you ship?" (Round 3 restores
  the release pipeline; see [`../ROADMAP.md`](../ROADMAP.md)).
