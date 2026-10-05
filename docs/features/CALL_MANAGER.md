# Unified call manager

The Rust runtime coordinates incoming GSM and SIP calls with a single owner from preparation through native and audio cleanup. Only a uniquely matching saved contact is admitted. Unknown, withheld, malformed and ambiguous identities are rejected silently before display wake, music pause or recording interruption. Presented caller identity is a contact policy, not transport authentication.

Telephone matching strips formatting and compares the complete canonical number; no suffix matching or inferred country code is used. Store the appropriate complete address. SIP matching preserves the account user and normalizes host case; display names do not authorize calls. Identity and priority are captured at admission. Later contact edits apply to future offers. `can_call` controls outgoing calls; a saved incoming identity does not require outgoing permission.

## Modes and controls

| Device mode | Ordinary saved contact | Priority saved contact |
| --- | --- | --- |
| Normal | Audible ring, wake, Accept / Cancel | Audible ring, wake, Accept / Cancel |
| Silent | Silent wake, Accept / Cancel | Silent wake, Accept / Cancel |
| Do Not Disturb | Busy rejection, no interruption | Silent wake, Accept / Cancel |

Settings → Call mode selects Normal, Silent or Do Not Disturb and shows the committed current choice. Settings → Contacts edits priority using the existing mutable address book. Both controls operate offline. Priority defaults false and applies to both stored GSM and SIP addresses. Replacement updates omitting priority remove the previous grant. Favorite/primary status does not confer priority. Existing settings/contact persistence restores committed values after restart; missing mode defaults Normal and malformed stored mode reports an error with Do Not Disturb fallback. Dashboard editing and synchronization are deferred.

An admitted offer immediately wakes and shows contact identity, address, transport and Accept / Cancel, initially focused on Accept. Single press changes selection; double press activates it. Controls carry the displayed session key, so a delayed action for A cannot act on later call B. Actual physical-button and glass observations remain pending.

Silent suppresses incoming alerts on all configured outputs, including Bluetooth, while accepted conversation and outgoing calls retain their ordinary audio. Entering Silent stops pending alerts; entering Do Not Disturb ends an ordinary pending incoming call as busy. Priority calls remain silent. Returning to Normal can restart a still-pending alert only after route readiness, within its original decision window. Changes never resurrect rejected calls or terminate an active call; an already dispatched answer finishes its operation.

A second call is rejected busy across either transport while the first prepares, rings, answers, is active or cleans up. Priority never overrides ownership or shutdown. Waiting/Held native facts do not provide call waiting, hold controls or permission to admit another call. Actual GSM carrier-facing disposition remains unverified.

## Interruption and deadlines

Admitted calls pause music, stop voice playback, close usable voice-note audio as an unsent draft, and cancel assistant work. Music stays paused at its track/position until explicitly restarted. Empty capture is discarded; failed draft copying retains recovery ownership. No automatic send, assistant restart, recording restart or music resume occurs. Cleanup restores a usable prior screen/focus or Home, not an obsolete recording/loading screen.

Unsent drafts expose Review, Send and Discard through existing voice-note UI. Send rechecks current recipient permission and immutable displayed draft identity. A confirmed sender-worker exit while sending shows **Delivery unknown**; Review and Discard remain available, and **Send again** requires an explicit action that may duplicate a remotely received message. Local accepted processing/upload completion is not proof of peer delivery or peer playback duration. Interrupted draft ownership is not newly persisted across a full runtime restart.

Preparation, answer, alert and cleanup operations have default 8-second deadlines. Incoming decision timeout uses `calling.ring_duration_seconds` (currently 30 seconds), including silent calls. At equality the deadline has expired. The loop expires manager deadlines before consuming queued UI/worker input; late Accept/readiness/stop cannot dispatch Answer before Tick. A timely user decision may finish within its operation deadline after the original decision window. Mode/route changes preserve the original admission deadline. Timeout does not fabricate native release: late genuine terminal and resource-cleanup evidence remains usable, and ownership stays held until required proof arrives.

## GSM backend and recovery

Initial GSM support is restricted to the demonstrated isolated pinned SIMTech QMI ModemManager backend. Unsupported AT/unknown capability does not permit global hangup. No modem was found in the controller's pre-deploy inventory; modem class, packet-data handoff, PCM/audio format, real incoming detection, and carrier disposition remain unverified. Do not infer a sample rate or claim supported hardware calling from fake-worker tests.

Startup/restart defers cellular AT/PPP/GPS work whenever native call quiescence cannot be established, including absent/unsupported ModemManager voice control. Wi-Fi/Bluetooth continue. Cellular data can stay unavailable until supported control/reconciliation is restored. Async ModemManager CreateCall can outlive a dead worker before object publication: an empty replacement cache, process death, command acknowledgment or arbitrary delay is not remote completion. Recovery may require external verified termination; no automatic new admission follows uncertainty.

Before GSM native dispatch, the runtime durably writes `calling.native_operation_guard_file`, default `data/device/native-call-guard.json` relative to runtime paths. Version 1 contains `version`, session `key` (transport/generation/call_id), and optional `native_owner`; it contains no caller address or call log. A missing file is clean. Existing valid dirty, malformed or unreadable files quarantine global call admission/network startup after full runtime restart. Write failure prevents native dispatch. Clearing requires native/resource proof; deleting the marker or a synthetic Terminated fact is not evidence of safety.

Supervised audio recovery requires Linux pidfds, readable consistent procfs and retained worker/helper identity. Retirement persists through failure and Pending/Ready polling keeps power deadlines responsive. Proven unprivileged Media/VoIP/Voice launch also requires the fixed setpriv no-new-privileges boundary; privileged domains retain their launch behavior. Unreadable eligible processes can leave recovery required. Worker death alone never proves GSM ended.

The audio launch boundary strips inheritable/ambient capabilities and sets no-new-privileges using verified ordinary setpriv/worker executables. The child and supervisor independently verify equal expected UIDs, zero capabilities and NNP1 before native readiness. Original groups are preserved. A fatal or exited UI latches call admission closed until a full runtime restart verifies a fresh usable UI; buffered Ready cannot clear this latch.

Network has a fixed privileged subreaper guardian using the service's existing sudo authority. It authenticates and retains a per-lifetime supervisor socket before launching Network. Nonroot service UID/GID/groups and the original zero/bind-service capability profile with NNP0 are restored and checked in Network, preserving port80 and nested PPP sudo behavior. Root runtime launches its guardian directly and retains its existing root credential behavior. No sudoers, service policy, or extra grants are installed. Missing existing privilege authority fails closed. The guardian kills only kernel-owned direct/adopted descendants using stable pidfds and reaps to ECHILD; only then does it acknowledge drain. Runtime must receive that ACK and reap the original sudo launcher before replacement. Missing registration, endpoint loss, denial and incomplete cleanup never establish success. Retirement stays asynchronous for power handling.

Call identities are canonical positive decimal `sip-incoming-N`, `gsm-N`, or `runtime-outgoing-N`. Allocation/publication is serialized by the owning worker/runtime. Separate incoming/outgoing watermarks per transport/generation reject retired replay without accumulating tombstones. Live native/host registries are capped at64 each; manager tracks at most128 live keys. Capacity retains current owners and refuses new work, potentially requiring verified cleanup/recovery before service resumes. Native Released removes retained call ownership; quota eviction never asserts cleanup. External producers must follow this identity/publication contract; deprecated unkeyed GSM dial refuses. SIP identity that cannot fit completely into the native event is unmatchable, never authorized by its truncated prefix. Native incoming early media is explicitly disabled before Core startup and reconfiguration.

Saved drafts block replacement capture, while ordinary outgoing calls and replay remain available. Talk exposes a separate saved-draft route even without contacts. Saved send attempts have separate identities and an eight-second uncertainty deadline; old results/snapshots cannot change a retry. Copied WAVs are reserved mode0600 before bytes under an owned private0700 directory; unsafe writable parents fail preservation rather than disclose audio.

### Trusted offline GSM cold recovery

This is operator-attested physical maintenance, not a software inference from an empty modem list. The maintenance command requires root, inactive dev/prod/legacy runtime and ModemManager units, no old runtime/workers/native owner, no non-hub USB peripheral, and a complete readable process/descriptor census showing no open audio/serial/modem-control resources. Denied or incomplete proof refuses. New markers include boot ID; the recovery boot must differ. Legacy markers require the additional explicit attestation flag because old boot/physical provenance cannot be observed.

1. Stop all runtime lanes and ModemManager; prevent automatic/manual starts during maintenance.
2. Shut the Pi down, remove physical power from both Pi and modem (including independent/back-power sources), disconnect the modem and all non-hub USB peripherals, then boot the Pi with the modem disconnected.
3. Stop/reverify all four units again after boot; verify no old workers and maintain exclusive offline control. Do not reconnect the modem yet.
4. Run the exact installed runtime as root with its normal config directory and `--recover-gsm-after-physical-cold-reset`. Add `--attest-legacy-marker-cold-reset` only for a legacy marker after independently performing/attesting the same physical procedure. The flag is an explicit physical-reset attestation, not permission to skip these steps.
5. Require successful synced receipt/archive output. The receipt preserves the parsed old marker identity, new boot and attestation. It is durably written before marker archive/retirement. Never remove the dirty marker by hand to bypass refusal.
6. Reconnect the modem, start ModemManager, select one runtime lane and start it; verify actual modem availability and call readiness. Old in-memory guard state stays quarantined and cannot clear or publish into the recovered runtime.

Corrupt/unreadable markers cannot produce a parsed recovery receipt and remain blocked. This maintenance has not been performed during feature validation; absent modem inventory supplies no physical-reset evidence.

### Safe exact-artifact process diagnostic

After source review and exact ARM64 artifact installation, the controller may run `<artifact>/yoyopod-runtime --network-owner-proof` as the same nonroot service account in an isolated stopped-service session with its existing bind-service capability profile and NNP0. This fixed diagnostic starts no modem, real PPP link or call. It runs the real sudo guardian, a fixed worker, nested sudo root fixture and a setsid descendant. Success JSON requires root descendant startup, stable pidfd death, guardian ECHILD ACK and original launcher reap; the token-stripped field must be true under the target env_reset policy. Nonroot host tests do not substitute for this actual-root result. Existing sudo authority is required; failure must be reported without granting new permissions.

## Validation and deployment record

Source integration tests exercise actual decoded worker/UI envelopes and native `call.action` keys; native Linux checks prove compilation/ABI without starting a Liblinphone Core. Exact validation head/results are recorded in the Task 10 report and will be incorporated after controller review. Hardware acceptance is pending: no caller devices/accounts were supplied and no real SIP delivery, peer duration, physical-button, silent Bluetooth, two-party audio or carrier result is claimed.

The controller owns push, workflow_dispatch, exact artifact deployment and safe hardware sequencing. A branch push alone does not trigger CI. Verify dispatch head SHA/branch/event, native job success and fresh artifact `yoyopod-rust-device-arm64-<full-source-sha>` before deployment. PR artifact labels can name a head SHA while checkout builds a merge commit. Preserve exact run/artifact/download/install provenance.

Controller deployment sequence after review:

```text
yoyopod target mode status
yoyopod target deploy --branch codex/call-manager --sha <verified-source-sha> --wait-for-ci
yoyopod target status
yoyopod target screenshot
yoyopod target logs
```

No deployment has yet been performed for this feature. The binary source SHA, CI run URL, artifact identity, installation/startup evidence and each real-call matrix result must be recorded before claiming hardware acceptance. A later docs-only commit must be labeled separately from the tested binary SHA.

Stock `target validate` only checks dry-run configuration and standalone Whisplay UI; it does not install or verify binary SHA and does not stop services. Running it alongside a hardware-owning service is unsafe. Controller must stop dev, establish inactive prod/old workers, run isolated stages and restore/reverify dev. Default two cycles visit Listen/Talk; the preexisting cycles≥3 hub map mismatch and missing SetupCallMode coverage mean stage passes do not validate Settings or call behavior. Screenshots are rendered output, not human glass/button/carrier evidence. No Rust/LVGL builds are permitted on the Pi.

All real hardware matrix items remain pending: unknown/withheld callers during activity; Normal/Silent/DND ordinary/priority calls; built-in/Bluetooth silence; committed settings restart; music/recording/assistant/playback interruption and draft recovery; packet data enabled/disabled; every second-call pairing; caller hangup/repeated presses; route/transport/worker loss; mode changes; shutdown. Controller preflight confirms dev active/prod inactive and clean checkout, with no ModemManager modem, only as availability metadata.

Runtime tracing/stderr diagnostics remain operational evidence. Synchronized device/dashboard call logs are deferred; this feature adds no call-log sync queue or dashboard API.

Host validation completed at source checkpoint `7a19f6606113b92261d7c8e8856bc90f452a7954`: full device formatting/default workspace check, affected eight-crate suite (538 passed; two existing network subprocess fixtures ignored), full workspace all-targets clippy and native workspace compile with Whisplay/LVGL/Liblinphone features passed. Baseline clippy/native UI warnings remain; exact locations and logs are in the Task 10 report. Genuine native VoIP ABI suite (30 passed) ran at `308868b1cdba48ded7d1e92a469e18169d024cff`; native VoIP source is unchanged at the final source checkpoint. Native UI fatal-wake regression passed at `7a570f3124b2fbff1b13ede220cdbb922f8672a8`; UI source is unchanged. These Linux checks start no Liblinphone Core and prove no real hardware calls. The later documentation commit records these source checkpoints and is not a tested hardware binary SHA.
