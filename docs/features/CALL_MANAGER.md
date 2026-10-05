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

Final review must resolve the live-service launch concern: the observed service runs as UID 1000 with inherited/permitted/effective/ambient CAP_NET_BIND_SERVICE and NoNewPrivs=0. Current zero-capability eligibility therefore falls back to the full newer-process census, where unrelated root/SSH processes can block proof. Zero-cap fake fixtures do not establish deployed recovery operability. Network portal port 80/PPP privileges must be preserved. Per-generation manager terminal/sequence collections, SIP ended records and GSM used IDs also grow without a numeric cap; safe retirement cannot use naive FIFO eviction because stale offers can resurrect keys. These are concrete pending final review/fix concerns.

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
