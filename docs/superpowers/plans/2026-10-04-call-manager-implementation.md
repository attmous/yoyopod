# Unified Call Manager Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Admit incoming GSM/SIP calls from saved contacts under Normal, Silent, and Do Not Disturb policies, preserving an existing call and coordinating device audio, display, and recovery.

**Architecture:** A pure runtime call manager decides admission and lifecycle effects. Typed session commands target worker-owned GSM/SIP handles, while runtime adapters coordinate audio interruption, display wake, command acknowledgements, and supervised recovery. The UI projects only admitted sessions and keeps its existing navigation and gestures.

**Tech Stack:** Rust 2021, current pinned workspace toolchains, serde NDJSON worker protocol, Liblinphone, ModemManager through blocking zbus, mpv, ALSA helpers, Rust LVGL 9.5.0 scenes, Whisplay 240x280.

**Spec:** `docs/superpowers/specs/2026-10-04-call-manager-design.md` (approved in chat after device modes and priority exceptions were added).

## Global Constraints

- Work on `codex/call-manager`, based on `origin/main` at `31a7713640e1d14419ee6b0aca95f76d1c721637`; do not reset it or create another branch for these tasks.
- Supported hardware: Pi Zero 2W, Whisplay HAT, PiSugar 3; portrait 240x280.
- Unknown, withheld, or ambiguous identity: immediate silent rejection before any activity interruption.
- One call owns the device through preparation, ringing, answering, active conversation, and cleanup; additional calls are rejected as busy.
- Normal admits saved contacts audibly; Silent admits saved contacts silently; Do Not Disturb admits priority contacts silently and rejects ordinary contacts without interruption.
- Priority defaults false, applies to both contact addresses, and never overrides existing call ownership or shutdown.
- Admitted calls wake the display immediately, show Accept / Cancel with Accept initially selected, and interrupt recording/assistant activity.
- Music remains paused until the user restarts it. Usable interrupted recordings are closed unsent drafts; never auto-send or auto-restart.
- Operation deadlines default to 8 seconds; incoming decision timeout follows `calling.ring_duration_seconds`, currently 30 seconds.
- No call waiting, conference, hold, automatic music resume, dashboard editing/API additions, or synchronized call logs in this change.
- Hardware deploy uses committed/pushed exact-commit CI artifacts through `yoyopod target`; never build Rust or LVGL on the Pi.
- Worker stdout stays protocol-owned; diagnostics use Rust tracing/stderr. Keep existing contact/history policy compatible.

## Review Focus

1. Contact permission migration: records currently filtered by `can_call` must remain available for incoming identity matching without allowing unauthorized outgoing calls or voice-note sends (Tasks 1–3, 7).
2. Caller number arriving after a GSM offer: an initially missing identity must remain rejected and must not subsequently wake or ring (Tasks 2, 5).
3. Native ringing after an audio-route update: SIP configuration and Bluetooth routing must never restore autonomous audible ringing (Tasks 4, 6, 10).
4. Audio helper surviving worker death: ownership must remain blocked until helper/resource release is confirmed; a child process exit alone does not prove modem call termination (Tasks 6, 7, 10).
5. Contact removal or stale Settings action: editing priority cannot recreate removed contacts, and a cloud replacement omitting priority cannot retain a previous priority grant (Tasks 3, 8).

## File and dependency map

New focused modules:

| Path | Responsibility |
| --- | --- |
| `device/protocol/src/call.rs` | Session, mode, offer/update/action and interruption DTOs. |
| `device/runtime/src/call_manager/mod.rs` | Manager state, public API, reducer. |
| `device/runtime/src/call_manager/identity.rs` | Conservative full-address matching. |
| `device/runtime/src/call_manager/policy.rs` | Mode, priority, and ownership admission. |
| `device/runtime/src/call_manager/effects.rs` | Runtime command/ack translation and readiness ledger. |
| `device/runtime/src/call_manager/tests.rs` | Deterministic state-machine fixtures and race tests. |
| `device/runtime/src/call_preferences.rs` | Atomic persistent mode load/save. |
| `device/voip/src/liblinphone/call_registry.rs` | Stable per-call native handle lifetimes. |
| `device/network/src/gsm_calls.rs` | ModemManager call-object registry and discovery events. |
| `device/media/src/ringtone.rs` | Separate bounded ringtone playback handle. |
| `docs/features/CALL_MANAGER.md` | Operator/user behavior and hardware validation instructions. |

Modify existing protocol UI DTOs, runtime loop/state/config/routing, cloud contacts
writer, transport workers/backends, media/speech interruption, and UI Settings/
call scene files in the tasks below. Do not broadly split unrelated existing files.

Tasks are sequential: 1 defines contracts; 2 builds policy; 3 persists settings;
4–6 implement worker contracts; 7 connects the runtime; 8–9 finish UI; 10 validates
the whole feature. Intermediate commits need not expose the incomplete feature.
Enable the new manager only when worker contracts and runtime integration are ready.

## Task 1: Define session contracts and preserve the full contact directory

**Files:** Create `device/protocol/src/call.rs`; modify `device/protocol/src/lib.rs`,
`device/protocol/src/ui/mod.rs`, `device/protocol/src/ui/snapshot.rs`,
`device/runtime/src/config.rs`, `device/runtime/src/state.rs`.

**Interfaces:** Export these serde DTOs from `yoyopod_protocol::call`; derive
Debug/Clone/PartialEq/Eq and serde, with snake_case enum representations:

```rust
pub enum CallTransport { Gsm, Sip }
pub enum DeviceMode { Normal, Silent, DoNotDisturb }
pub struct SessionKey {
    pub transport: CallTransport,
    pub generation: u64,
    pub call_id: String,
}
pub enum CallDirection { Incoming, Outgoing }
pub enum CallPhase { Preparing, Ringing, Answering, Outgoing, Active, Ending, Ended }
pub struct CallOffer { pub key: SessionKey, pub address: String }
pub struct CallUpdate {
    pub key: SessionKey, pub direction: CallDirection, pub phase: CallPhase,
    pub address: String, pub duration_seconds: u64, pub muted: bool,
    pub sequence: u64,
}
pub enum RejectReason { Unapproved, Busy, Cancelled, Timeout }
pub enum CallAction { Answer, Reject(RejectReason), Hangup, SetMute(bool) }
pub struct CallCommand { pub key: SessionKey, pub action: CallAction }
pub struct InterruptForCall { pub key: SessionKey, pub activity_generation: u64 }
pub struct RingtoneRequest { pub key: SessionKey }
pub struct ContactPrioritySet { pub contact_id: String, pub priority: bool }
```

Make `DeviceMode::default()` Normal. Add default-false `priority` and default-true
`can_call` to contact config/runtime/ListItemSnapshot representations. Preserve
existing `can_receive` semantics for voice-note recipients; do not repurpose it
as incoming-call permission. Preserve all saved records for incoming matching,
but enforce `can_call` in outgoing call target selection and related UI actions.
Do not conflate `favorite`/`is_primary` with `priority`.

Add `session: Option<SessionKey>`, `session_phase: Option<CallPhase>`,
`accept_enabled: bool`, and `alert_audible: bool` to the call UI snapshot,
and `device_mode: DeviceMode` to Settings snapshot with serde defaults. Add
`SettingsIntent::DeviceModeSet(DeviceMode)` and
`SettingsIntent::ContactPrioritySet(ContactPrioritySet)`.
Existing call intents retain their UI shape; the runtime attaches the currently
admitted key. Extend every existing struct literal/conversion accordingly.
Keep the current envelope schema version; the new message names identify these
typed payloads. Reject missing/empty session IDs, missing generation, and invalid
enum values on session actions rather than defaulting to the current call.

- [ ] Write protocol round-trip and permission-regression tests first:

```rust
#[test]
fn old_contact_has_no_priority_grant() {
    let item: ListItemSnapshot = serde_json::from_value(serde_json::json!({
        "id":"dad", "title":"Dad", "sip_address":"sip:dad@example.test"
    })).unwrap();
    assert!(!item.priority);
    assert!(item.can_call);
}

#[test]
fn targeted_action_round_trips() {
    let command = CallCommand {
        key: SessionKey { transport: CallTransport::Sip, generation: 2,
            call_id: "incoming-7".into() },
        action: CallAction::Reject(RejectReason::Busy),
    };
    let decoded: CallCommand = serde_json::from_value(
        serde_json::to_value(&command).unwrap()).unwrap();
    assert_eq!(decoded, command);
}
```

- [ ] Add a runtime config test with a `can_call:false` saved contact: assert
  it remains in `PeopleRuntimeConfig::to_contact_items()`, while
  `approved_call_target()` returns None. Existing `can_receive:false` tests
  must still reject voice-note recipient selection. Add intent round-trips
  for mode and explicit true/false priority.
- [ ] Run `cargo test --manifest-path device/Cargo.toml -p yoyopod-protocol -p yoyopod-runtime --locked`;
  expect compilation/test failure for the new fields before implementation.
- [ ] Implement the DTOs, exports, serde defaults, conversions, and permission
  checks; keep raw worker offers separate from existing foreground snapshots.
- [ ] Repeat the affected tests and `cargo check --manifest-path device/Cargo.toml --workspace --locked`.
- [ ] Commit: `feat: define targeted call sessions and contact priority contracts`.

## Task 2: Implement the pure admission and lifecycle manager

**Files:** Create `device/runtime/src/call_manager/{mod,identity,policy,tests}.rs`;
modify `device/runtime/src/lib.rs`. No worker/hardware calls in this task.

**Interfaces:** Public manager API and local types:

```rust
pub struct ContactIdentity {
    pub contact_id: String, pub name: String,
    pub sip_address: String, pub phone_number: String, pub priority: bool,
}
pub struct CallContext { pub contacts: Vec<ContactIdentity>, pub shutdown: bool }
pub enum CallManagerEvent {
    Offer(CallOffer), Update(CallUpdate),
    RequestOutgoing { key: SessionKey, contact_id: String, address: String },
    UserAction(CallCommand),
    AudioPrepared { key: SessionKey, ok: bool },
    CommandFinished { key: SessionKey, request_id: String, ok: bool },
    CleanupConfirmed(SessionKey),
    WorkerExited { transport: CallTransport, generation: u64 },
    SetMode(DeviceMode), Tick, Shutdown,
}
pub enum CallEffect {
    Transport(CallCommand), Dial { key: SessionKey, address: String },
    PrepareAudio(InterruptForCall),
    StartRingtone(RingtoneRequest), StopRingtone(RingtoneRequest),
    WakeDisplay(SessionKey), Publish, RestoreUi(SessionKey),
    RecoverTransport { transport: CallTransport, generation: u64 },
}
// Public methods on CallManager:
// new(mode: DeviceMode, operation_timeout_ms: u64, ring_duration_ms: u64) -> Self
// handle(&mut self, event: CallManagerEvent, context: &CallContext,
//        now_ms: u64) -> Vec<CallEffect>
// session(&self) -> Option<&SessionKey>
// phase(&self) -> Option<CallPhase>
// mode(&self) -> DeviceMode
// alert_audible(&self) -> bool
// identity::match_contact<'a>(transport: CallTransport, address: &str,
//      contacts: &'a [ContactIdentity]) -> Option<&'a ContactIdentity>
```

Keep a terminal/tombstone set for the worker generation so updates to rejected
offers cannot become a new admission. Retain the latest sequence per key.
Use monotonic `now_ms`, not wall clock. Outgoing keys are allocated by runtime
before dispatch; workers adopt that logical ID and map it to their native
handle/object path. Reserve ownership before emitting the dial command.

- [ ] Write these manager tests, with the fixture functions in the same test file:

```rust
fn key(id: &str) -> SessionKey {
    SessionKey { transport: CallTransport::Sip, generation: 1, call_id: id.into() }
}
fn context(priority: bool) -> CallContext {
    CallContext { shutdown: false, contacts: vec![ContactIdentity {
        contact_id: "dad".into(), name: "Dad".into(),
        sip_address: "sip:dad@example.test".into(), phone_number: "+49123456789".into(),
        priority,
    }] }
}
#[test]
fn unknown_offer_has_only_targeted_rejection() {
    let mut manager = CallManager::new(DeviceMode::Normal, 8_000, 30_000);
    let effects = manager.handle(CallManagerEvent::Offer(CallOffer {
        key: key("a"), address: "sip:stranger@example.test".into(),
    }), &context(false), 0);
    assert_eq!(effects, vec![CallEffect::Transport(CallCommand {
        key: key("a"), action: CallAction::Reject(RejectReason::Unapproved),
    })]);
    assert!(manager.session().is_none());
}
#[test]
fn dnd_priority_offer_wakes_without_ringtone() {
    let mut manager = CallManager::new(DeviceMode::DoNotDisturb, 8_000, 30_000);
    let mut effects = manager.handle(CallManagerEvent::Offer(CallOffer {
        key: key("a"), address: "sip:dad@example.test".into(),
    }), &context(true), 0);
    effects.extend(manager.handle(CallManagerEvent::AudioPrepared {
        key: key("a"), ok: true,
    }, &context(true), 10));
    assert!(effects.contains(&CallEffect::WakeDisplay(key("a"))));
    assert!(!effects.iter().any(|e| matches!(e, CallEffect::StartRingtone(_))));
    assert_eq!(manager.phase(), Some(CallPhase::Ringing));
}
```

- [ ] Add named tests for all six mode/priority combinations, cross-transport
  second offers in every owned phase, Answer queued during preparation,
  duplicate Cancel, remote Ended before an Answer ack, reject-withheld followed
  by a later populated number, stale generation/sequence, ring timeout,
  8-second operation timeout, mode change in each phase, and shutdown.
- [ ] Write identity tests: formatting-only phone equivalence; no suffix or
  guessed-country matching; case-normalized SIP host with user case retained;
  explicit `sip:`/`sips:` handling; malformed/empty identities; duplicate address
  across contacts rejects as ambiguous. Do not add a new phone library or
  dialing-region feature: require complete stored numbers in this version.
- [ ] Run `cargo test --manifest-path device/Cargo.toml -p yoyopod-runtime call_manager --locked`;
  expect new API failures, then implement conservative matching and reducer.
- [ ] Implement rejection before PrepareAudio/WakeDisplay, preparation readiness,
  and a teardown barrier. `Publish` projects Preparing/Ringing as incoming,
  Answering as connecting, and terminal outcomes as cleanup before idle.
  A successful command ack alone must not fabricate Active/Ended transport facts.
- [ ] Run manager tests; confirm rejected calls emit no Publish/PrepareAudio/
  WakeDisplay effects and retain the original session during all second offers.
- [ ] Commit: `feat: add shared call admission and lifecycle policy`.

## Task 3: Persist mode and priority through the existing contact writer

**Files:** Create `device/runtime/src/call_preferences.rs`; modify
`device/runtime/src/{lib,config,cli,event,state}.rs`,
`device/cloud/src/{contacts,host,worker}.rs`, `config/communication/calling.yaml`.

**Interfaces:**

```rust
// Runtime-owned mode file, resolved relative to the configured runtime root:
pub fn load_mode(path: &std::path::Path) -> Result<DeviceMode, String>;
pub fn save_mode(path: &std::path::Path, mode: DeviceMode) -> Result<(), String>;
// In the cloud contacts module, the existing single writer:
pub fn set_contact_priority(config: &CloudHostConfig,
    change: &ContactPrioritySet) -> anyhow::Result<Vec<serde_json::Value>>;
```

Add `calling.mode_file: data/device/call-policy.json`. Mode is persistent local
user state, not synchronized call history. Missing file defaults Normal;
invalid file returns an error and runtime starts in DoNotDisturb with a warning.
Atomic writes use a same-directory temp, flush/sync, rename, and Unix 0600.
Do not publish a successful Settings ack or new effective mode until persistence
has succeeded; failed writes preserve the prior effective value.

Priority writes use `cloud.contact_priority_set`, executed serially by the
existing cloud contacts owner, and return the updated directory. This local
operation must work without MQTT connectivity. Validate stable contact ID and
explicit boolean; do not create missing records or rewrite their addresses,
permissions, aliases, or order. Cloud replacement remains authoritative: absent
priority is explicitly false, not merged from the previous file. No outbound
dashboard sync or endpoint is added.
Emit `cloud.contacts_updated` with `{"contacts": updated_records}` after the
atomic write, and a correlated result for `cloud.contact_priority_set`. Runtime
decodes this local-store shape with `contact_configs_from_value`, projects the
full directory, and does not feed it through the cloud replacement converter
that remaps `is_primary` to `favorite`. A stale UI request must never recreate
a contact that disappeared before the writer executed it.

- [ ] Write persistence tests with `tempfile` (add the existing workspace-version
  dev dependency to runtime if absent): missing/corrupt files, restart load,
  failed save retaining effective mode, and exact enum round-trips.
- [ ] Add this cloud regression test to `contacts.rs`, using its existing fixtures:

```rust
#[test]
fn replacement_without_priority_revokes_old_priority() {
    let root = tempfile::tempdir().unwrap();
    let config = CloudHostConfig {
        runtime_root: root.path().to_string_lossy().into_owned(),
        ..Default::default()
    };
    let mut entry = contact("one", "Dad", "sip:dad@example.test");
    entry["priority"] = serde_json::json!(true);
    persist_contacts(&config, &serde_json::json!({"contacts":{"entries":[entry]}})).unwrap();
    let saved = persist_contacts(&config, &serde_json::json!({"contacts":{"entries":[
        contact("one", "Dad", "sip:dad@example.test")
    ]}})).unwrap().unwrap();
    assert_eq!(saved[0]["priority"], serde_json::json!(false));
}
```

- [ ] Add tests for local priority edits offline, unknown/deleted IDs, invalid
  booleans, failure before rename, and contact/address preservation. Cloud
  config validation accepts omitted priority but rejects a present non-boolean.
- [ ] Run `cargo test --manifest-path device/Cargo.toml -p yoyopod-cloud -p yoyopod-runtime --locked`;
  observe new persistence tests fail, then implement writer/Settings routing.
- [ ] Project committed changes into full contact snapshots and manager context;
  retain admitted contact identity even if the directory changes mid-call.
- [ ] Repeat tests and commit: `feat: persist call mode and contact priority settings`.

## Task 4: Make SIP call control session-specific and suppress native alerts

**Files:** Create `device/voip/src/liblinphone/call_registry.rs`; modify
`device/voip/src/{host,calls,events,worker,runtime_snapshot}.rs` and
`device/voip/src/liblinphone/{mod,state,runtime,backend,events,ffi,abi_event}.rs`.

**Interfaces:** Extend `VoipRuntimeBackend` with
`apply_call(&mut self, command: &CallCommand) -> Result<(), String>` and
`make_session_call(&mut self, key: &SessionKey, address: &str) -> Result<(), String>`.
Publish typed `call.offer` and `call.update` payloads with actual per-call ID,
generation, and increasing sequence. Add full call ID to the shim event ABI;
update both producer/decoder layouts together. Do not truncate IDs into collisions.

Implement a safe registry container around native RAII handles:

```rust
pub(crate) struct SessionRegistry<H> {
    calls: std::collections::BTreeMap<String, H>,
}
// new() -> Self
// insert(&mut self, call_id: String, handle: H) -> Result<(), String>
// get(&self, call_id: &str) -> Option<&H>
// remove(&mut self, call_id: &str) -> Option<H>
// NativeCallHandle retains linphone_call_ref at creation, and releases
// exactly one linphone_call_unref on Drop. All operations stay on the host.
```

- [ ] Write the safe-registry regression first:

```rust
#[test]
fn removing_second_call_preserves_first_handle() {
    let mut calls = SessionRegistry::new();
    calls.insert("a".into(), 101_u64).unwrap();
    calls.insert("b".into(), 202_u64).unwrap();
    assert_eq!(calls.remove("b"), Some(202));
    assert_eq!(calls.get("a"), Some(&101));
    assert!(calls.get("b").is_none());
}
```

- [ ] Add fake-backend worker tests for targeted Answer/Busy/Hangup, rejected
  stale generations, unknown IDs, incoming B while A is active, and terminal
  callback B not clearing A. Test that native offers do not directly change
  foreground `CallSession` before runtime admission.
- [ ] Run `cargo test --manifest-path device/Cargo.toml -p yoyopod-voip --locked`;
  expect new registry/contracts failures, then replace implicit handle control.
- [ ] Load native ref/unref APIs; retain handles until safe terminal release.
  Generate opaque monotonic IDs independently of caller URI. Reject Busy using
  the pinned library's `LinphoneReasonBusy`, and Unapproved/Cancelled using
  `LinphoneReasonDeclined`; verify enum values from installed/pinned headers
  instead of guessing numeric constants. Use `linphone_call_decline` only for
  incoming calls and targeted terminate for cleanup after connection.
- [ ] Force autonomous ringing off at core startup and after every
  `voip.set_audio_devices`/volume change; disable incoming tone indications,
  including call-waiting tones, where supported. Ringtone is runtime-controlled.
  Do not merely mute native ringing after an offer callback has already sounded.
- [ ] Keep outgoing IDs provided by runtime distinct from generated incoming IDs;
  route every callback through its corresponding registry record. Replace or
  remove old unscoped answer/reject/hangup paths once Task 7 is integrated.
- [ ] Repeat unit tests and run
  `cargo check --manifest-path device/Cargo.toml -p yoyopod-voip --features native-liblinphone --locked`
  in a supported Unix environment; Windows pure tests do not establish native correctness.
- [ ] Commit: `feat: target SIP actions by session and disable autonomous ringing`.

Native reference: [Liblinphone call control](https://download.linphone.org/releases/docs/liblinphone/5.4/c/group__group__call__control.html)
documents Declined/Busy rejection. Actual symbols, enum values, and core tone
configuration must match the version shipped in the existing CI artifact.

## Task 5: Discover and control incoming GSM sessions safely

**Files:** Create `device/network/src/gsm_calls.rs`; modify
`device/network/src/{lib,gsm,worker,runtime,gsm_audio}.rs`.

**Interfaces:** Replace the single tracked modem call with an object registry.
Add typed offers/updates to backend refresh observations while preserving GSM
availability snapshots. Extend `GsmBackend` with
`apply_call(&mut self, command: &CallCommand) -> anyhow::Result<()>` and
`dial_session(&mut self, key: &SessionKey, number: &str) -> anyhow::Result<()>`.
The GSM command channel carries key and command request ID; worker results are
emitted after execution, not merely after enqueueing to the GSM thread.

`GsmCallRegistry` has these methods, testable using object-path strings:

```rust
// new(generation: u64) -> Self
// observe(&mut self, object_path: &str, direction: CallDirection,
//         phase: CallPhase, number: &str) -> Vec<CallManagerWireEvent>
// path_for(&self, key: &SessionKey) -> Option<&str>
// remove(&mut self, key: &SessionKey) -> Option<String>
pub enum CallManagerWireEvent { Offer(CallOffer), Update(CallUpdate) }
```

Outgoing registration maps the preallocated logical key to `CreateCall`'s
object path. Incoming registration uses unique logical IDs per generation and
stores the native path separately. Enumerate existing calls once on discovery,
then consume CallAdded/CallDeleted and property/state updates with bounded
polling of tracked objects as recovery; avoid repeated full D-Bus enumeration.

- [ ] Write registry tests for two objects with identical numbers, one initial
  offer per object, monotonically sequenced state updates, object removal,
  unknown ID, empty number followed by Number update, and old generation.
- [ ] Write a fake backend test: A is Active, B arrives and gets Busy; assert
  Hangup targets B's path, A's PCM stays alive, and cellular-data resume is not
  triggered by B's terminal event.
- [ ] Run `cargo test --manifest-path device/Cargo.toml -p yoyopod-network gsm --locked`;
  expect new incoming/session tests fail before implementation.
- [ ] Observe incoming Direction/Number/State without starting call audio or
  suspending packet data. `gsm.answer` first receives runtime readiness, acquires
  the existing voice-data handoff, then invokes the offered Call object's Accept.
  Reject invokes only that object's Hangup and deletes it after terminal confirmation.
  Never use HangupAll, HoldAndAccept, or the existing unqualified ATH path.
- [ ] Ensure incoming GSM discovery functions while packet data is enabled.
  Keep ModemManager ownership of the control channel; no alternate raw AT caller
  detection. Only an admitted answered/outgoing GSM session may acquire a data
  pause. Restore previous cellular enabled/disabled policy exactly once.
- [ ] Treat MM Waiting/Held as distinct states; do not silently map Held to
  active audio ownership or accept a second call. Unsolicited non-owned Active
  state triggers targeted termination/reconciliation rather than UI admission.
- [ ] Prepare USB PCM endpoints before answering while keeping capture/playback
  inactive until answer readiness. If SIM7600 requires post-Accept setup, bound
  that operation and terminate on failure; no microphone or ringtone overlap.
- [ ] Give GSM audio relay helpers verified parent-death/process-group cleanup
  and test that forced network-worker termination releases both ALSA endpoints.
  Reconcile the modem's still-live call after restart; process exit cannot prove
  remote call termination.
- [ ] Preserve D-Bus's bounded timeout; late command results cannot apply to an
  old session. GSM Busy is an immediate targeted rejection policy: the Call
  API does not accept a selectable busy reason. Record actual carrier-facing
  behavior during hardware testing rather than promising a specific network tone.
- [ ] Repeat tests and commit: `feat: add targeted incoming GSM discovery and answering`.

Native references: upstream ModemManager [Call interface](https://raw.githubusercontent.com/linux-mobile-broadband/ModemManager/main/introspection/org.freedesktop.ModemManager1.Call.xml)
and [Voice interface](https://raw.githubusercontent.com/linux-mobile-broadband/ModemManager/main/introspection/org.freedesktop.ModemManager1.Modem.Voice.xml).
Use installed version introspection on the Pi to confirm supported capabilities.

## Task 6: Add controlled ringtone and interruption without auto-send

**Files:** Create `device/media/src/ringtone.rs`; modify
`device/media/src/{lib,host,worker,config,mpv_process}.rs`,
`device/voip/src/{host,voice_notes,worker,playback}.rs`,
`device/speech/src/worker.rs`, `device/runtime/src/{config,state,event}.rs`.

**Interfaces:** Media accepts `media.ringtone_start` / `media.ringtone_stop`
with `RingtoneRequest`. VoIP accepts `voip.interrupt_for_call` with
`InterruptForCall` and returns a draft reference if one was saved. Speech reuses
`voice.cancel` with its existing `target_request_id` payload and correlated result.
Media pause and VoIP interruption results mean their audio is released, not
only that an operation was queued.

Use a separate ringtone playback handle; never load ringtone into music mpv.
Generate/cache a small deterministic WAV locally in the media worker (no downloaded
asset/dependency). Play it through a separately owned mpv helper or equivalent
existing process abstraction, with configured alert volume/output route, no
microphone capture, and finite lifetime. Helpers have EOF/shutdown/lease cleanup
and a verified Linux parent-death/process-group policy so they cannot outlive
their owner. Do not embed shell-built commands or reuse the music socket.

```rust
pub struct RingtonePlayer {
    process: Option<Box<dyn crate::mpv_process::ProcessHandle>>,
    session: Option<SessionKey>,
    lease_deadline_ms: u64,
}
// new() -> Self
// start(&mut self, request: &RingtoneRequest, output: &str, volume: u8,
//       now_ms: u64, lease_ms: u64) -> Result<(), String>
// stop(&mut self, request: &RingtoneRequest) -> Result<(), String>
// tick(&mut self, now_ms: u64) -> Result<(), String>
// Drop terminates and waits for its owned helper.

// VoipHost:
// interrupt_for_call(&mut self, backend: &mut dyn VoipRuntimeBackend,
//     request: &InterruptForCall) -> Result<Option<String>, String>
// Returned String is the closed draft path, not a message/send identifier.
```

- [ ] Test ringtone separately from music: record the music runtime's current
  track and position, pause, start/stop a ringtone, and assert unchanged track/
  position and Paused state. Test an old-session stop cannot stop a new ringtone,
  duplicate stop succeeds, silent admission creates no helper, and expired
  lease/worker shutdown kills and waits for the helper.
- [ ] Add a recording regression with the existing fake VoIP backend: interruption
  stops recording, closes usable WAV, returns its path, and never calls
  `send_voice_note`. Zero-length captures are discarded. A failed save reports
  failure and still releases capture before readiness is acknowledged.
- [ ] Add speech cancellation regression: after a correlated `voice.cancel`,
  a delayed ask/STT/TTS/focus completion cannot produce playback or a new voice
  command. Reuse the speech worker's generation mechanism and add the runtime
  activity generation check rather than attempting to kill an HTTP thread.
- [ ] Run
  `cargo test --manifest-path device/Cargo.toml -p yoyopod-media -p yoyopod-voip -p yoyopod-speech --locked`;
  observe new interruption tests fail, then implement worker contracts.
- [ ] Clear runtime `auto_send_after_capture` and pending recipient/send state
  before issuing interruption, so a resulting recorded/review snapshot cannot
  trigger the existing `auto_send_voice_note_command`. Retain a draft reference
  independent of foreground call state; add access to that draft in Task 9.
- [ ] Stop voice-note and focus playback idempotently. Block late stale start
  commands at workers using activity/session generations. Ringtone routing follows
  current alert route, including disconnect fallback, without mutating native
  SIP ring suppression. A route update during Silent/DND cannot start sound.
- [ ] Repeat tests, then commit: `feat: coordinate call alerts and preserve interrupted voice drafts`.

## Task 7: Connect manager effects, acknowledgements, and supervised recovery

**Files:** Create `device/runtime/src/call_manager/effects.rs`; modify
`device/runtime/src/{runtime_loop,event,state,worker,cli,config}.rs`.

**Interfaces:** `RuntimeLoop` owns `CallManager`. Its event adapter produces
`CallManagerEvent` before ordinary snapshot application. The effect adapter
exposes:

```rust
// translate_effect(effect: CallEffect, state: &RuntimeState,
//     pending: &mut CallOperationLedger, now_ms: u64) -> Vec<RuntimeCommand>
// CallOperationLedger derives Default and retains operation purpose,
// session key, required readiness acks and monotonic deadlines:
// register(&mut self, key: SessionKey, request_id: String,
//          domain: WorkerDomain, deadline_ms: u64)
// complete(&mut self, domain: WorkerDomain, request_id: &str,
//          ok: bool) -> Option<CallManagerEvent>
// expire(&mut self, now_ms: u64) -> Vec<CallManagerEvent>
// invalidate(&mut self, key: &SessionKey)
// RuntimeLoop::run_once_at(&mut self, io: &mut impl LoopIo, now_ms: u64) -> usize
// RuntimeLoop::begin_shutdown(&mut self, io: &mut impl LoopIo, now_ms: u64)
```

Add `RuntimeCommand::RecoverWorker { domain: WorkerDomain }` and
`LoopIo::recover_worker(&mut self, domain: WorkerDomain) -> Result<(), String>`.
The supervisor retains each original WorkerSpec, kills/waits the old worker
and owned helpers, advances its generation, starts the replacement, and
reconfigures it through existing startup payloads. It does not replay old
call/assistant actions. Keep reconstruction bounded and report failures.
Transport workers include their generation in call IDs/events; runtime config
assigns it on every start and accepts no mismatched-generation call messages.

- [ ] Extend existing `FakeLoopIo` with recovery recording and injected send
  failures. Add deterministic `run_once_at` tests for known and unknown offers
  from both transport domains, command results, and deadlines.
- [ ] Write the actual no-side-effect assertion around the fake-loop sent
  envelopes; this goes beyond reducer-only tests:

```rust
fn assert_no_local_call_interruption(sent: &[(WorkerDomain, WorkerEnvelope)]) {
    for (domain, envelope) in sent {
        assert!(!matches!(envelope.message_type.as_str(),
            "media.pause" | "media.ringtone_start" | "voip.interrupt_for_call" |
            "voice.cancel" | "voice.cancel_focus_prompt" | "ui.set_backlight"));
        if *domain == WorkerDomain::Ui {
            let payload = &envelope.payload;
            assert_ne!(payload.pointer("/call/state").and_then(Value::as_str),
                Some("incoming"));
        }
    }
}
```

- [ ] Add tests for music at 12,345 ms staying paused after every outcome,
  already-paused/stopped music unchanged, and remote Play/Capture/Call commands
  blocked during ownership. Inject second offers while a GSM data handoff is
  pending and prove their rejection does not resume data.
- [ ] Add failure tests: dispatch failure, command ack timeout, remote Ended
  during preparation, worker.exited while ringtone child survives, failed cleanup,
  stale events after restart, and SIGINT/power shutdown. Ensure the first call
  stays owned until terminal transport/audio facts or successful reconciliation.
- [ ] Run `cargo test --manifest-path device/Cargo.toml -p yoyopod-runtime --locked`;
  expect integration assertions fail before wiring the manager.
- [ ] Intercept raw offer/update messages before `RuntimeEvent::apply` can
  overwrite call state or issue legacy music pauses. Registration/availability
  snapshots still apply; foreground call fields are solely manager projections.
  Remove the obsolete `commands_for_voip_snapshot` call interruption path and
  method-based GSM ignore logic only after equivalent tests pass.
- [ ] Translate PrepareAudio into a correlated readiness barrier: invalidate
  voice activity/auto-send, pause active music, cancel speech, interrupt VoIP
  recording/playback, then report AudioPrepared only after all required acks.
  WakeDisplay emits the existing backlight command at configured brightness
  and the manager call patch immediately, independently of this barrier.
- [ ] StartRingtone requires prepared audio and Normal mode. StopRingtone
  completion precedes native Answer/audio enable. Gate Answer once dispatched;
  Confirm Active only from a matching transport update. Incoming snapshot state
  remains incoming during Answering with phase/accept_enabled reflecting
  Connecting; it must not be labeled an outgoing call.
- [ ] Allocate outgoing ownership/key before `voip.dial` or `gsm.dial`, including
  voice/cloud entry points. Pass that key with the existing dial payload. Keep
  `can_call` checks and outgoing busy rejection in one runtime path. Translate
  `CallEffect::Dial` into the transport's session-aware dial command; correlate
  its backend result through the same operation ledger.
- [ ] Secondary rejection failures retry only the secondary key. Do not restart
  a transport or hang up the primary call because a second offer could not be
  rejected. If the modem cannot isolate call objects, report that hardware
  limitation and do not fall back to global hangup.
- [ ] For a failed foreground cleanup, stop alerts, retain the admission barrier,
  recover only the responsible worker, and reconcile remaining modem objects
  after restart. Worker death alone cannot prove GSM network termination.
  Confirm no stale active call/audio before reopening admission; never auto-answer.
- [ ] Route all shutdown sources through begin_shutdown before stop_all. Allow
  bounded cleanup but never delay emergency power shutdown past its existing
  safety deadline; parent-death/lease cleanup handles forced worker stop.
- [ ] Run runtime tests plus workspace check and commit:
  `feat: integrate unified call ownership and recovery into runtime`.

## Task 8: Add Settings controls for mode and priority contacts

**Files:** Modify `device/protocol/src/ui/{mod,snapshot}.rs`,
`device/ui/src/router/{routes,select,mod}.rs`,
`device/ui/src/application/{navigator,focus,accessibility,options,runtime}.rs`,
`device/ui/src/components/screens/{setup,contacts,mod,chrome}.rs`,
`device/runtime/src/{event,state}.rs`. Modify corresponding UI snapshot domain
parsers under `device/ui/src/application/snapshot/domains/` where fields are
read individually rather than deserialized through shared DTOs.

**Interfaces:** Add `UiScreen::SetupCallMode` and a Settings root entry labeled
`Call mode`. Its selectable entries are exactly Normal, Silent, Do Not Disturb.
Selecting one emits the Task 1 DeviceModeSet intent. Show the committed mode in
Settings; failed writes produce a recoverable error instead of pretending the
selection persisted. Reuse existing scene primitives/icons and routes.

In Settings -> Contacts, show each existing contact's Priority On/Off state;
selecting its priority action emits explicit ContactPrioritySet with stable
`contact_id`. This does not dial or change `favorite`, addresses, or permissions.
Priority contact editing is local in this feature; subsequent authoritative
cloud replacements follow Task 3's default-false policy.

- [ ] Write UI intent tests before adding controls: navigate to each mode,
  activate with Select, assert the correct typed intent and no music/call intent.
  Test the updated Settings root count and cyclic focus so the new entry can
  be reached without hard-coded seven-item counters.
- [ ] Add the navigator selector and direct intent test, then connect it to the
  new route. This selector does not optimistically update persisted mode:

```rust
pub fn select_call_mode(runtime: &mut UiRuntime) {
    let modes = [DeviceMode::Normal, DeviceMode::Silent, DeviceMode::DoNotDisturb];
    if let Some(mode) = modes.get(runtime.focus_index) {
        runtime.intents.push(UiIntent::Settings(
            SettingsIntent::DeviceModeSet(mode.clone())));
    }
}

#[test]
fn selecting_dnd_emits_only_mode_intent() {
    let mut runtime = UiRuntime::default();
    runtime.focus_index = 2;
    navigator::select_call_mode(&mut runtime);
    assert_eq!(runtime.take_intents(), vec![UiIntent::Settings(
        SettingsIntent::DeviceModeSet(DeviceMode::DoNotDisturb))]);
    assert_eq!(runtime.snapshot.settings.device_mode, DeviceMode::Normal);
}
```
- [ ] Test two contacts with the same name but different stable IDs: changing
  one priority emits only that ID and never toggles the other. Feed a directory
  removal patch before activation and assert no stale mutation recreates it.
- [ ] Run `cargo test --manifest-path device/Cargo.toml -p yoyopod-ui -p yoyopod-runtime --locked`;
  expect route/focus tests fail, then implement the new Settings screen/actions.
- [ ] Update every exhaustive UiScreen/SettingsIntent match, accessibility text,
  focus count, setup counter, snapshot mapper, and SVG/icon fallback through
  existing UI structure. Selection activates a persisted request; checkbox/state
  changes after its committed snapshot arrives. Avoid new navigation systems.
- [ ] Repeat tests and compile UI native features in the supported CI environment;
  commit: `feat: expose call modes and priority contact controls`.

## Task 9: Finish call preemption, display wake, and interrupted-draft access

**Files:** Modify `device/ui/src/router/guards.rs`,
`device/ui/src/application/{state,navigator,runtime,intents,accessibility}.rs`,
`device/ui/src/components/screens/{incoming_call,common,voice_note,talk_contact}.rs`,
`device/ui/src/components/widgets/call_overlay.rs`,
`device/ui/src/scene/deck.rs`, and matching renderers under
`device/ui/src/renderer/` only where new model fields need rendering.
Modify `device/runtime/src/{state,event}.rs` and
`device/protocol/src/ui/snapshot.rs` for draft snapshot projection.

**Interfaces:** UiRuntime saves one interrupted navigation entry keyed by
SessionKey, including screen/focus/selection. Subsequent call phase patches
replace the call screen without pushing another copy. New session entry clears
gesture/PTT state and sets focus to index 0 (Accept). Same-session duration
updates preserve the user's selected Cancel focus. On idle, restore a usable
entry or Hub, leave ambient mode, and restart inactivity timing.

Expose `interrupted_draft_path: Option<String>` through the existing voice-note
snapshot; existing draft duration/recipient fields identify it. The restored
TalkContact/VoiceNote flow offers Review and Discard. Send still requires a new
explicit action and current recipient permission; recipient deletion does not
auto-send or recreate a contact. Do not publish local draft paths to the dashboard.

- [ ] Add guard and runtime tests with loading/error overlays plus admitted
  call patches: calls win; rejected calls produce no call route; fatal UI failure
  reports failure rather than presenting a successful wake.
- [ ] Add the same-session focus regression using the existing UiRuntime input
  test style and Task 1 fields:

```rust
#[test]
fn duration_patch_does_not_reset_cancel_focus() {
    let mut runtime = UiRuntime::default();
    runtime.snapshot.call.state = "incoming".into();
    runtime.snapshot.call.session = Some(SessionKey {
        transport: CallTransport::Sip, generation: 1, call_id: "a".into(),
    });
    navigator::apply_runtime_preemption(&mut runtime);
    assert_eq!(runtime.focus_index, 0);
    runtime.handle_input(InputAction::Advance, 100);
    assert_eq!(runtime.focus_index, 1);
    navigator::apply_runtime_preemption(&mut runtime);
    assert_eq!(runtime.focus_index, 1);
    runtime.handle_input(InputAction::Select, 200);
    assert_eq!(runtime.take_intents(), vec![UiIntent::Call(CallIntent::Reject)]);
}
```

- [ ] Test ambient and backlight wake, input consumed on call screens, Answer
  queued during Preparing, Connecting display/disabled duplicate Accept, Cancel
  during Answering using targeted cleanup, idle restoration of valid selection,
  stale overlay/recording fallback to Hub, and inactivity timing after cleanup.
- [ ] Test interrupted draft review/discard and explicit-send permission checks;
  loading a draft after hangup emits no auto-send and does not start recording.
- [ ] Run `cargo test --manifest-path device/Cargo.toml -p yoyopod-ui -p yoyopod-runtime --locked`;
  observe new regressions fail, then implement navigation/scene changes.
- [ ] Show name, address, and GSM/VoIP within existing 240x280 margins. Silent
  and DND priority calls show the same Accept / Cancel controls, with no spoken
  focus/caller prompt. Long press/Home must not escape incoming ownership;
  use existing call-screen back rejection semantics rather than activate PTT.
- [ ] Repeat tests/native UI check and commit:
  `feat: wake call UI and restore safe navigation after interruption`.

## Task 10: Validate the complete feature and document hardware results

**Files:** Create `docs/features/CALL_MANAGER.md`; update
`docs/features/README.md` and the implementation plan checkboxes. Add remaining
cross-worker tests to `device/runtime/src/runtime_loop.rs` and worker test
modules only where Task 7's fake-loop coverage does not cover a transport contract.

**Interfaces:** No new product APIs. Document mode/priority controls, complete
stored phone/SIP address matching, unsent draft handling, configured decision
timeout, Busy rejection policy, and local priority replacement behavior. Explicitly
state dashboard log sync is deferred and record actual GSM carrier behavior.

- [x] Add a parametrized end-to-end fake-loop matrix that sends typed offers
  through actual event decoding for both transports and asserts worker command
  keys and UI projections. Cover all modes, permissions, priority, Unknown,
  music/recording/assistant state, second call, caller hangup during Answer,
  failed readiness, cleanup retry, worker restart, and shutdown. No tests that
  merely serialize implementation output back into itself.
- [x] Verify formatting: `cargo fmt --manifest-path device/Cargo.toml --all -- --check`.
- [x] Run `cargo check --manifest-path device/Cargo.toml --workspace --locked`.
- [x] Run affected crate tests once after final integration:
  `cargo test --manifest-path device/Cargo.toml -p yoyopod-protocol -p yoyopod-runtime -p yoyopod-cloud -p yoyopod-media -p yoyopod-voip -p yoyopod-network -p yoyopod-speech -p yoyopod-ui --locked`.
- [x] Run `cargo clippy --manifest-path device/Cargo.toml --workspace --all-targets --locked`
  in supported environment. If Windows native/network dependencies prevent
  checks, record the exact limitation and run through existing supported CI;
  do not count a skipped build as passing. CI must compile native LVGL,
  Whisplay, and native Liblinphone paths, as in `.github/workflows/ci.yml`.
- [ ] Request required Rust/code review after implementation using the applicable
  review agent/skill. Address actionable findings, then re-run only checks affected
  by fixes. Do not request a reviewer to implement unrelated cleanup.
- [ ] Commit final source/docs, push `codex/call-manager`, and obtain the exact
  commit SHA using `git rev-parse HEAD`. Do not merge or rebase onto a later main
  silently as part of this validation.
- [ ] Read repository deploy/status/screenshot playbooks. Run
  `yoyopod target mode status`; activate dev if needed under the established
  lane rules. Run `yoyopod target deploy --branch codex/call-manager --sha <actual-commit-sha> --wait-for-ci`
  with the actual pushed SHA substituted, then `yoyopod target status`.
- [ ] Record the downloaded `yoyopod-rust-device-arm64-<actual-commit-sha>`
  artifact name and service startup evidence. Substitute the pushed source
  commit SHA into deployment commands and the artifact name.
- [ ] On the supported Pi, exercise the following matrix with real phones/SIP
  accounts and physical-button observation. Capture `yoyopod target screenshot`
  and relevant `yoyopod target logs` for admitted call UI and failure recovery:

| Exercise | Required observation |
| --- | --- |
| Unknown/withheld GSM and SIP during music or recording | Immediate rejection; no local sound, wake, pause, or capture interruption. |
| Normal known caller | Wake, ring, caller identity/transport, Accept initially selected; single/double press work. |
| Silent ordinary/priority callers | Wake and Accept / Cancel; no sound on built-in or connected Bluetooth outputs. |
| DND ordinary caller | Reject without interrupting device activity or waking display. |
| DND priority caller | Wake and Accept / Cancel silently; accepted conversation has normal audio. |
| Restart after mode/priority edit | Committed mode/priority restored; missing priority remains false. |
| Music, voice-note recording, assistant, voice playback | Appropriate interruption; usable unsent draft accessible; no late assistant audio or automatic music restart. |
| GSM packet data enabled/disabled | Incoming detection works in both policies; answer handoff and cleanup restore original data policy. |
| A ringing/connecting/active, B arrives; both transport combinations | B rejected without overwriting/hanging up A; record carrier-facing GSM behavior. |
| Caller hangs up during preparation/answering; repeated presses | No stuck ringtone, no wrong-session action, correct restoration. |
| Route loss, transport loss, killed worker/audio helper | Bounded failure recovery; no orphan audio/capture or premature new admission. |
| Mode changes during ringing/answering/active | Matches the approved spec; no termination of an active call. |
| Shutdown during ringing/active | New calls rejected; cleanup completes or obeys power safety deadline. |

- [ ] Hardware tests needing unavailable caller devices or accounts remain explicitly
  unverified. Do not claim a human-eyes or GSM carrier pass from screenshots/unit
  tests alone. Report observed limitations and keep the implementation incomplete
  if a required hardware invariant fails.
- [ ] Update `CALL_MANAGER.md` with commands, exact SHA/artifact, results, and any
  remaining verification gaps. Commit validation documentation without claiming
  that its newer docs-only commit is the binary tested on hardware.

## Execution and review handoff

This is a single coordinated subsystem; do not deliver independent GSM and SIP
admission policies. Review the written plan before implementation. Recommended
execution is subagent-driven with sequential tasks and review gates, because
transport identity, audio readiness, and cleanup interfaces are tightly coupled
and native lifetime mistakes can affect real calls. Native execution in this
chat is also available with a final independent review.

Tasks 1–9 are implemented and task-reviewed. Task 10 source integration and host validation are complete; final independent review and hardware acceptance remain pending. Keep each task's files
owned by its assigned worker and do not revert others' changes. No deployment
or merge is implied by completion of this plan document.
