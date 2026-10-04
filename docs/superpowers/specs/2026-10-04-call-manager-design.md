# Unified incoming call manager

Date: 2026-10-04
Branch: `codex/call-manager`
Base: latest fetched `origin/main`, `31a7713640e1d14419ee6b0aca95f76d1c721637`
Status: written specification for user review; implementation has not started.

## Intent and agreed behavior

YoYoPod must admit incoming GSM and SIP calls only from saved contacts and
coordinate calls with every device activity. The supported target remains the
Pi Zero 2W, Whisplay HAT, PiSugar 3, and the current Rust runtime/workers.

The user agreed to the following policies during brainstorming:

| Situation | Required behavior |
| --- | --- |
| Unknown, withheld, or unmatchable caller | Reject immediately and silently; do not wake the display, ring, pause playback, or interrupt recording. |
| A call is ringing, preparing, connecting, active, or ending | Reject an additional call as busy and preserve the existing session, across either transport. |
| Saved caller and no call in progress | Apply device mode and priority policy; if admitted, interrupt competing activities, wake the display, and show the incoming-call screen immediately. |
| Music playing | Pause without losing the track or position; remain paused after every call outcome until the user restarts playback. |
| Music already paused/stopped | Preserve that state. |
| Recording or assistant activity | Interrupt it, preserve usable voice-note audio as an unsent draft, and cancel pending assistant work. Do not restart automatically. |
| Voice-note or spoken prompt playback | Stop playback and release audio before call audio begins. |
| Display asleep or ambient | Wake immediately for an admitted call. |
| Shutdown underway | Reject new incoming calls as busy; complete shutdown. |

The incoming screen displays contact name, caller number/SIP address, transport,
and **Accept / Cancel**. Accept is selected initially. Single press switches
selection; double press activates the selected option. Existing call controls
for mute and hangup remain available after connection.

After termination, restore the prior usable screen and focus. Never restore a
stale loading screen or reopen recording/assistant activity. If the prior
screen cannot be restored, use Home. Resume ordinary display inactivity rules
after cleanup rather than immediately blanking the restored screen.

## Device modes and priority contacts

Device mode is an explicit runtime policy with three values. Mode applies to
incoming call admission and alerting; it does not mute an accepted conversation
or prevent the user from starting an outgoing call.

| Mode | Ordinary saved contact | Priority saved contact |
| --- | --- | --- |
| Normal | Admit with audible ringing and display wake. | Admit with audible ringing and display wake. |
| Silent | Admit without audible ringing; wake and show Accept / Cancel. | Admit without audible ringing; wake and show Accept / Cancel. |
| Do Not Disturb | Reject as busy without waking, ringing, or interrupting activities. | Admit without audible ringing; wake and show Accept / Cancel. |

Unknown/withheld callers always fail admission in every mode. Priority never
overrides an existing call, shutdown, or failed caller identification. An
admitted silent call still pauses music and interrupts recording/assistant
activity, as agreed; a mode-rejected call leaves all those activities untouched.
Silent means no incoming-call tone, spoken caller announcement, or equivalent
audible alert on any configured output, including Bluetooth.

Represent priority as a per-contact boolean, default false, applying to all
that contact's GSM and SIP addresses. Preserve it through contact parsing,
storage, updates, and worker/UI snapshots wherever contact records round-trip.
Older records with no priority field remain non-priority. Omission on replacement
updates must not accidentally retain a previous priority grant.

Expose mode selection and contact priority editing through existing device
Settings/contact flows, with current mode visible while selecting it. Persist
these settings using the existing settings and mutable contact ownership;
fresh/default mode is Normal. Missing mode configuration defaults to Normal;
malformed stored mode is reported and uses Do Not Disturb as a safe fallback.
Do not infer mode solely from volume being zero or create a second contact store.
Dashboard editing and synchronization are not added by this feature.

Changing mode during an active call does not terminate it or mute its audio.
For a pending incoming session, entering Silent stops audible alerts immediately.
Entering Do Not Disturb terminates a non-priority incoming session as busy;
a priority session remains available without sound. Returning to Normal may
ring a still-pending admitted session after audio readiness. Once an answer has
been dispatched, finish that operation rather than race it with a mode-change
rejection. Mode changes never resurrect previously rejected calls. Priority
changes apply to future offers, consistent with fixed admitted contact identity.

## Scope and exclusions

This change includes incoming GSM discovery/answering, shared admission and
session policy, device modes and priority settings, controlled ringing, audio
interruption, display preemption, and robust termination/recovery. Existing outgoing GSM/SIP calls must acquire
the same session ownership so incoming calls cannot disturb them.

Call waiting, holding, conferencing, automatic music resume, and automatic
assistant/recording restart are excluded. Device/dashboard call-log storage
and synchronization are explicitly deferred to a later feature. Preserve
existing history behavior where compatible; do not add a dashboard API,
sync queue, or new persistence scheme. Operational diagnostics are allowed.

## Current code and gaps

- `device/runtime/src/event.rs` routes call commands and pauses music on SIP
  snapshots. It rejects SIP incoming calls during GSM ownership, but lacks a
  complete common admission/cleanup policy. GSM Answer currently emits no command.
- `device/runtime/src/state.rs` derives call UI state from worker snapshots;
  GSM updates currently depend on already-selected GSM call ownership.
- `device/network/src/gsm.rs` supports outgoing ModemManager calls, hangup,
  mute, and USB PCM audio. It does not discover or accept incoming calls.
- `device/network/src/worker.rs` coordinates GSM commands with cellular data
  suspension/resumption. Incoming calls need the same ownership discipline.
- `device/voip/src/liblinphone/runtime.rs` operates on a current-call handle
  and configures native ringing. Both must be hardened for admission and
  multiple simultaneous transport sessions.
- `device/ui/src/router/guards.rs` currently prioritizes error/loading screens
  over calls. Existing call scenes and button gestures can be reused.

## Architecture and ownership

Add a focused call-manager module inside `device/runtime/src/`. It owns
contact admission, one foreground session, lifecycle transitions, interruption
coordination, deadlines, and cleanup. Keep hardware APIs in their existing
workers; do not introduce another process or move policy into the UI/CLI.

Use typed protocol contracts in `device/protocol/` for call offers, session
updates, targeted actions, and acknowledgements. A session key combines
transport with a backend call identifier and worker generation. Every
answer/reject/busy/hangup action targets that key, not an implicit current call.
Use generation/correlation IDs for audio and assistant work as well.

Worker facts enter the manager before they become user-visible call state.
Rejected offers never become foreground UI calls. A new offer must not
overwrite the existing foreground peer, duration, mute state, or backend handle.
Registration/availability snapshots remain independent from session state.

## Caller admission

Use the current mutable contacts directory shared by runtime behavior.
Normalize the caller and saved contact identifiers with the same routines.
Telephone matching strips formatting and compares complete canonical numbers;
do not use suffix matching or guess a country code. National/international
equivalence requires an explicitly configured dialing region or equivalent
stored address. SIP matching uses the canonical account address, preserves
user identity, and normalizes host case; display names never authorize a call.
Empty, malformed, anonymous, or ambiguous identities fail admission.

Evaluate contacts when the offer arrives. Once admitted, retain that contact
identity for the session; editing contacts does not retarget or terminate an
already admitted call. Missing/unavailable contacts fail closed. This policy
recognizes presented caller identity; it does not add transport authentication.

## Lifecycle and ordering

Foreground lifecycle:

`Idle -> Preparing -> Ringing -> Answering -> Active -> Ending -> Idle`

An outgoing call uses the same ownership with an outgoing/connecting phase.
Transport facts, including a remote termination during preparation or answering,
may transition any non-idle state to Ending. Error is an outcome with cleanup,
not a permanent session lock.

1. On an offer, reject unknown identities silently. Reject known identities
   as busy if ownership exists or shutdown has started. Then apply device
   mode: reject non-priority contacts as busy in Do Not Disturb; otherwise
   admit with the audible/silent alert policy specified above.
2. Reserve ownership atomically for an admitted offer. Capture the prior UI
   context and invalidate pending assistant/prompt results. Wake and show the
   incoming screen immediately, while audio interruption is prepared.
3. Pause music, stop voice playback, and finalize/cancel recording without
   sending it. Start audible ringing only in Normal mode and only after
   competing audio has released ownership. Silent admission skips alert playback.
   Accept can be queued during preparation, but never answers before readiness.
4. Accept stops any ringing, prepares the transport/audio route, then sends a
   targeted answer. Show Connecting until the backend confirms Active. Cancel
   targets the admitted session and enters Ending.
5. Terminal events stop ringing, release microphone/speaker ownership, restore
   any cellular-data handoff, and restore the usable UI context. Leave music
   paused. Release session ownership after required cleanup completes.

Repeated actions and duplicate terminal events are idempotent. Remote hangup
wins over a queued answer. Out-of-order updates and events from old worker
generations cannot revive a session. User/remote commands attempting to start
music, capture, or another call while ownership exists must be blocked through
the common runtime policy, regardless of command entry point.

## Transport and audio integration

GSM: observe ModemManager call objects for incoming offers and their identity,
direction, and state. Add targeted answer/reject/busy actions. Handle multiple
objects without hanging up the active object. Stop/delete only the targeted
terminal object. Preserve the modem/data ownership contract and restore the
configured data policy once after voice ownership ends. Incoming discovery
must work while packet data is enabled; verify this on the supported modem.

SIP: retain each offered Liblinphone call separately and target responses by
call ID. Reject busy with the transport's appropriate busy disposition; reject
unapproved callers without allowing native automatic ringtone playback.
Disable native autonomous ringing so admission always precedes local alerts.
Callback handling and native handle lifetimes remain owned by the VoIP worker.

Ringing uses a separately controlled alert playback handle owned by an audio
worker, under manager commands. It must not replace the music playlist/position
or require an additional worker process. Respect current configured alert
volume and output routing. Ringing has explicit start/stop acknowledgements
and stops on cancellation, answer, remote termination, failure, or shutdown.
Ensure microphone privacy and avoid simultaneous ringtone/call playback.

Interrupted voice notes become closed, playable unsent drafts using the
existing voice-note storage. If no usable audio exists, discard the empty
capture. Failure to save is reported without sending or restarting recording.
Late assistant completion/playback is ignored after cancellation.

## UI and error handling

An admitted call outranks unrelated loading and recoverable error overlays.
Underlying operations may complete, but their overlays cannot hide the call.
Fatal hardware/runtime failure still requires failure handling and termination;
the call manager cannot promise service while the runtime or display is down.
Use existing LVGL scenes and navigation, with contact/transport data supplied
by the manager. Reset focus once on a new session, not on every snapshot.
Call gestures consume their input so they cannot trigger an underlying action.

Use a default 8-second bounded deadline for each preparation/action/cleanup
operation, matching the current runtime command timeout scale. The incoming
decision window ends on user action, transport termination, or the configured
`calling.ring_duration_seconds` deadline (currently 30 seconds), for both audible
and silent offers. On expiry, terminate the incoming session and restore the UI.
Operation deadline
failure enters Ending and attempts targeted termination. Do not release
ownership while a backend may still own live audio: if normal termination
cannot be confirmed, supervised recovery of the responsible worker must
establish resource release before a new call can be admitted.

Worker exit triggers ringtone stop, invalidation of its session/generation,
resource recovery, and a concise call failure indication. Do not replay old
answer/dial commands after restart. Preserve data and hardware routing policy
when recovering. Log decisions, transitions, action results, and recovery facts
using current Rust tracing conventions; diagnostics are not synchronized call logs.

## Verification and acceptance

Meaningful Rust tests should verify the state machine and effects using fake
workers: contacts matching; silent rejection without side effects; competing
offers across both transports; outgoing ownership; pause without auto-resume;
draft preservation; cancellation of late assistant output; every device-mode
and contact-priority combination; mode changes while ringing/answering/active;
settings persistence and missing priority fields; display priority
and focus; remote hangup racing answer; duplicate actions; stale updates;
deadline failures; worker restart; and shutdown.

Run formatting, appropriate workspace checks, and affected crate tests. Hardware
validation must use a pushed exact-commit CI artifact and `yoyopod target`
deployment, never Rust builds on the Pi. Report commit SHA, artifact name,
commands, and observed results.

On Pi, exercise known/unknown/withheld GSM and SIP callers, incoming discovery
during packet data, Accept/Cancel with the physical button, display wake,
music/recording/assistant interruption, Silent and Do Not Disturb with both
ordinary and priority contacts, mode persistence across restart, silent output
on built-in/Bluetooth routes, simultaneous/second calls, remote
hangup during answering, audio-route failure, transport loss, and worker
recovery. Confirm no audible alert or UI interruption for rejected callers,
no disturbance of an existing call, no automatic playback restart, and correct
microphone/speaker and cellular-data cleanup.

## Next artifact

After the user reviews this written specification, create a sequenced
implementation plan with concrete files, protocol contracts, test coverage,
and hardware checks. Product code, deployment, and call-log synchronization
are not part of this design-document commit.
