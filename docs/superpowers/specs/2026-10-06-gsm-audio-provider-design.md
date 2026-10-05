# GSM audio metadata provider

Date: 2026-10-06. Status: written specification approved by the user.

The user approved this written specification on 2026-10-06. It defines a new
provider extension;
approval of the original call manager and Rust reconnect work does not approve
this extension's implementation plan or installation of a system package.

## Purpose and preserved behavior

Restore both outgoing and incoming GSM with provider-owned format evidence
before targeted Start or Accept, then expose the actual activated audio port
for that same call. Correct the Debian ModemManager SIMTech provider rather
than supplying an assumed PCM rate in Rust. The supported device remains
Pi Zero 2W, Whisplay, PiSugar 3, and the
qualified SIM7600G-H firmware/provider combination.

The [original call-manager specification](2026-10-04-call-manager-design.md)
continues to govern caller admission, one foreground session across GSM/SIP,
Normal/Silent/Do Not Disturb, priority contacts, activity interruption, display
and button behavior, cleanup, and recovery. Music stays paused after calls;
recording/assistant work does not resume automatically. Incoming and outgoing
calls retain the same ownership rules. Call-log storage, dashboard editing and
synchronization remain deferred.

This extension consists of a narrow provider patch, its tests and reproducible
Debian packaging, a qualified provider profile consumed by the Rust network
owner, and an explicit dev-lane CLI maintenance path. It adds no public AT or
D-Bus command interface, debug capability, polkit grant, second modem owner,
global hangup fallback, PR, main-branch change, or prod deployment. Modem
wiring and power state are unconfirmed; neither is an established cause of the
audio problem.

## Source evidence and limits

Exact-source findings are recorded in the local
`gsm-audio-proof-exploration.md` and `gsm-provider-metadata-design.md` reports
under `.superpowers/sdd/2026-10-04-call-manager-implementation/`. The latter
also exists as `gsm-provider-proposal.md` in the external validation directory.
This specification carries their source findings forward. Hardware observations
below are attributed to the coordinator's preflight rather than inferred from
that source analysis.

The coordinator's read-only preflight at
`2026-10-06T00:20:38+02:00` observed the following candidate identity:

| Observed fact | Value |
| --- | --- |
| Installed provider | `1.24.0-1+deb13u1`, `arm64` |
| Modem identity | Modem `3`, plugin `simtech`, manufacturer `QUALCOMM INCORPORATED`, model `SIMCOM_SIM7600G-H` |
| Firmware/hardware revision | `LE20B04SIM7600G22` / `10000` |
| State and call inventory | Registered (`State=8`), `Calls=[]` |
| Daemon identity through another reprobe at `00:10:49` | PID `758`, unique D-Bus owner `:1.11` remained unchanged |

This is an observed candidate, not a qualified PCM or reset profile. A
same-owner reprobe is additional reason to require modem/interface/lifecycle
fences: an unchanged daemon owner alone cannot prove initialization freshness.

| Baseline input | Identity |
| --- | --- |
| Debian source | `modemmanager 1.24.0-1+deb13u1` |
| Original source archive SHA256 | `63ded4c0f3936bb0db5ae35ef1dfd57c5d5b4dd8a5cdaa7fb2182255218c9168` |
| Debian patch archive SHA256 | `0362e74213576b3f830b344f139407843a6caf6b9ae892c5a085a340da6999f2` |
| Existing Debian quilt patch | `0001-shared-fibocom-don-t-assume-parent-implements-the-fi.patch`, preserved |

The report checked archive hashes against the [exact source descriptor](https://deb.debian.org/debian/pool/main/m/modemmanager/modemmanager_1.24.0-1+deb13u1.dsc),
but did not independently verify its signature. The build must verify trusted
signed Debian metadata and the descriptor before accepting those inputs.

The inspected SIMTech support sequence tests `CPCMREG` and `CPCMFRM`, then
sends uncached `CPCMFRM=1`. Its successful callback records no audio format.
Channel setup sends `CPCMREG=1` after a delay and supplies a discovered port,
but a null format. The generic voice updater incorrectly skips nonterminated
calls, so the first ongoing call can miss its delayed port. Generic incoming
and outgoing constructors also overwrite provider-created audio settings from
the transient voice context. These defects are in the
[SIMTech source](https://sources.debian.org/src/modemmanager/1.24.0-1%2Bdeb13u1/src/plugins/simtech/mm-shared-simtech.c/#L1040)
and [generic voice source](https://sources.debian.org/src/modemmanager/1.24.0-1%2Bdeb13u1/src/mm-iface-modem-voice.c/#L148).

The [SIMCom AT manual V3.00, page 161](https://files.waveshare.com/wiki/SIM7600G-H/SIM7500_SIM7600_Series_AT_Command_Manual_V3.00.pdf#page=161)
documents `CPCMFRM=1` as selection of 16 kHz USB audio, a read form, and
nonpersistent storage. It does not establish every PCM framing detail for the
installed firmware. Selection acknowledgement, matching readback, and a
qualified framing profile establish configured format; they do not constitute
an independent measurement of a live stream or prove intelligible audio.

The current outgoing path also needs repair. It prepares PCM before
`CreateCall`, using `sample_rate(None)`, while the normal runtime supplies no
configured rate. It therefore fails before creating a Call even if the
provider's incoming metadata is corrected. The constructor/lifetime correction
must serve outgoing Calls too, and Rust must create the owned object before
reading its format, preparing PCM and dispatching targeted Start.

The scratch `gsm-outgoing-incoming-explanation.md` records the exact-source
history. Earlier code at `310c08d8` created/started the native call first; the
audio path at `83a326dc` used a direct if02 AT rate query and `CPCMREG` command,
an if04 PCM bridge, and an implicit 8 kHz fallback. That different route is
consistent with the user's earlier real outgoing audio success. The exact
revision and transport used for that successful call are not established.
`7f0675bc` removed direct AT and fallback ownership. This extension does not
restore them or treat the earlier success as evidence of today's metadata or
provider qualification.

In this exact provider, `Voice.CreateCall` constructs, exports and lists an
UNKNOWN QMI Call object; it does not dial. Native QMI Dial occurs in
`Call.Start`. UNKNOWN `Call.Hangup` is rejected. `Voice.DeleteCall` removes an
object from the exported call list and does not end a native modem call. These
distinctions are requirements for the outgoing ordering and cleanup below,
not permission to delete a potentially started call. The source-backed
[creation path](https://sources.debian.org/src/modemmanager/1.24.0-1%2Bdeb13u1/src/mm-iface-modem-voice.c/#L670),
[Start/native Dial](https://sources.debian.org/src/modemmanager/1.24.0-1%2Bdeb13u1/src/mm-call-qmi.c/#L138),
[UNKNOWN Hangup gate](https://sources.debian.org/src/modemmanager/1.24.0-1%2Bdeb13u1/src/mm-base-call.c/#L697)
and [DeleteCall implementation](https://sources.debian.org/src/modemmanager/1.24.0-1%2Bdeb13u1/src/mm-call-list.c/#L172)
define this boundary.

## Chosen evidence contract

The provider establishes configuration through its own existing AT transport.
It must successfully complete both fixed commands, in order, without cached
responses and within the same current configuration generation:

1. `+CPCMFRM=1`: successful modem acknowledgement.
2. `+CPCMFRM?`: one readback whose strictly parsed result is `1`.

Each command has a 3-second timeout. The two-command selection task therefore
has a maximum 6-second command budget and no automatic retry. Existing support
probes keep their existing bounded behavior; probe success alone is not
selection evidence. The readback parser accepts the documented response with
ordinary surrounding whitespace/line endings, and rejects missing, duplicate,
malformed, ambiguous, or mismatching values. A readback of `0` after a
successful setter is a failure, not an 8 kHz fallback.

Publish configured format only after both completions and the lifecycle
fences succeed. The intended dictionary for the candidate implementation is
`{encoding: "pcm", resolution: "s16le", rate: uint32(16000)}`. PCM channel
count, sample packing, signedness, bit depth and byte order must have primary
vendor evidence applying to the exact firmware, or documented bench
qualification, before this tuple/profile is accepted. The known rate command
does not supply that framing evidence. A candidate package can expose the
dictionary so its propagation and reset invalidation can be tested while
qualification is pending. This remains an implementation claim under test,
not a qualified wire-format claim: Rust must keep GSM Start/Accept disabled until
the framing and reset/lifecycle gates pass in the tracked profile. Existing
Call properties need no new public qualification property. A qualified static
profile interprets current provider evidence; it never substitutes for the
setter/readback.

Unsupported commands, timeout, modem error, cancellation or unexpected response
leave format unknown. Missing qualification keeps the format ineligible for
Start/Accept even when a candidate provider dictionary is present. There is no
guessed 8 kHz, static `gsm_pcm_sample_rate_hz` override, independent serial reader, or
arbitrary-AT diagnostic route.

## Component ownership

| Component | Responsibility |
| --- | --- |
| ModemManager generic voice core | Configuration generation, configured format lifetime, shared active channel lifetime, Call property propagation and invalidation. |
| Shared SIMTech plugin | Fixed selection/readback task and successful owner-managed channel activation; consume real command results. |
| Existing QMI Call implementation | Native call identity, signaling, Start/Accept and native-ID EndCall. Its constructor/class is preserved. |
| Rust network owner | Immutable unique D-Bus owner/modem/call and epoch fences, current metadata reads, qualified profile checks, exact-call actions, bounded audio readiness and recovery. |
| Rust runtime call manager | Existing contact/mode admission, foreground session, activity/UI coordination and cleanup policy. |
| CLI and CI | Exact-commit artifacts, package/profile provenance, preflight, dev maintenance and rollback. They do not own runtime call behavior. |

The functional provider changes are confined to
`src/mm-iface-modem-voice.c`, its private/internal header, and
`src/plugins/simtech/mm-shared-simtech.c`, plus focused tests, test build
registration and clarification of existing Call-property documentation.
Internal C lifecycle helpers are not installed libmm-glib API or new D-Bus
methods. Do not replace `mm_call_qmi_new` with an AT or generic Call type.

## Metadata lifetimes and exported properties

Voice-owned state separates these fields even if it shares one allocation:

| State | Created by | Cleared by |
| --- | --- | --- |
| Configuration generation and result-accepting flag | Fresh initialization or enable after invalidation; tokens are never reused. | Disable, reinitialization, shutdown, invalidation/removal, observed reset. |
| `configured_audio_format` | Successful setter/readback in the matching generation; profile qualification separately governs eligibility. | Configuration invalidation; ordinary call cleanup preserves it. |
| `active_audio_port` and active-channel format | Successful current owner-managed channel setup. | Successful last-channel cleanup or lifecycle invalidation. |
| Current async operation identity/cancellable | Each selection, setup or cleanup task. | Its own completion/cancellation; an older task cannot clear a newer one. |

A fresh initialization invalidates previous metadata before accepting new
results. The first enable may retain a successful initialization result when
there has been no intervening invalidation. Disable invalidates it even if the
modem object survives. Re-enable must rerun the shared fixed selection/readback
task before voice enable completes when the current generation has no valid
format; it cannot rely on capability flags or object destruction. The initial
initialization/enable episode must not needlessly select twice.

The same normalization helper serves constructors and later updates: choose
valid active-channel format when available, otherwise current configured
format, otherwise no format; choose a port only from valid successful active
channel state. Both generic constructors use this helper after provider call
creation, so their final update preserves configured format. Publishing format
also updates an already-created nonterminated Call. Absence of a call list
during probing is normal.

Correct `call_list_foreach_audio_settings` to skip terminated Calls and update
ongoing Calls. A first incoming Ringing Call after fresh initialization has
configured `AudioFormat` and an empty `AudioPort` before Accept. Ringing alone
does not send `CPCMREG=1`. Calls created while another active channel exists
can inherit shared active settings under existing provider semantics; the
runtime still rejects a competing offer as busy and does not use its port.

After a targeted Start or Accept, successful owner-managed SIMTech channel
setup returns the actual discovered port and a referenced current configured
format. Update that existing Call after the asynchronous activation completes.
An activation error publishes no port even if generic in-call setup otherwise
reports success. Outgoing setup may occur while native signaling is Dialing;
Rust keeps capture/playback closed until native Active and current port/format
readiness both hold. Native Active alone is not audio readiness.

Successful last-channel cleanup explicitly clears the port's connected state,
then releases active port/format references. It preserves configured format
and updates any surviving ringing/waiting Calls to empty port plus configured
format. A new second incoming Call therefore has format before Accept without
retaining the first call's activation. Termination of one among multiple
provider Calls must not prematurely clear a still-shared port. Dropping a
context reference alone is insufficient because terminated objects may retain
port references.

Lifecycle invalidation clears configured and active state and propagates empty
audio properties to exported Calls that remain observable, including retained
terminal objects, before the old generation can be treated as eligible again.
This is distinct from the ordinary updater's terminated-call skip. Failed
cleanup must not falsely declare resource release; existing targeted recovery
establishes release before a new foreground session is admitted.

## Async and reset fences

Every provider async task captures a strong source-object reference, the
configuration generation, and its operation identity. A callback consumes its
own finish result into local owned references first. It commits them only if
the source is still valid, uncancelled, accepting results, and both tokens match
current state; otherwise it releases them. It cannot recreate cleared state,
publish format/port after invalidation, or clear a newer task's cancellable.
The generic `in_call_setup_ready` must follow this rule rather than write
unchecked finish outputs directly into shared context. Cleanup completions
need the same operation fence so an old cleanup cannot erase a newer channel.

An ordinary call end does not advance the configuration generation. Disable,
fresh initialization, voice shutdown, modem invalidation/removal and every
observed modem reset do. Same-object disable/re-enable is a required regression
case, not an assumption that USB reset always creates a new object.

An in-memory property cannot prove continuity through a reset invisible to
ModemManager. Qualification must show that the supported device/firmware reset
paths produce provider invalidation/reinitialization and externally visible
metadata loss before stale state can qualify another Start/Accept. If that
cannot be demonstrated, this profile is not accepted and GSM acceptance remains
closed. Adding a new safe reset observer or provider guarded-acceptance API
would be a separate reviewed extension; this spec does not assume either.

Existing Call properties do not provide an atomic comparison of generation
with Start/Accept dispatch. Rust binds fresh reads and every method call to the exact immutable
unique D-Bus owner, modem path, Call path/native identity and native session
epoch. Owner/interface/lifecycle changes and metadata loss invalidate the
selection. Reused paths, replacement owners, old snapshots and late method
results cannot transfer ownership or revive a session. The tests and hardware
qualification must prove the required observable fences for this profile;
properties from a prior initialization are never a recovery shortcut.

## Rust consumption contract

Incoming: before dispatching the existing exact-call Accept, the native network
owner must freshly read this Ringing Call's qualified 16 kHz PCM/s16le format from
the pinned provider and pass existing modem/owner/session fences. Port absence
at this stage is expected for the first call. Unknown format/profile produces
an explicit audio-readiness failure through existing session handling; it
cannot answer using a configured constant. Ringing, contact admission, modes,
button UI and local alert ownership retain their original policies.

Outgoing uses the same qualified constructor format without a static rate or
new public PCM interface. Its required ordering is:

1. Acquire the existing canonical runtime/native session key, foreground
   ownership and cellular-data reservation before creating a provider object.
   Check cancellation, current immutable daemon owner/modem admission epoch
   and collector/loss fences before dispatching any native action.
2. Mark Create uncertainty under that key before exact-owner `Voice.CreateCall`.
   Creation exports an UNKNOWN QMI Call but does not dial. A failed, timed-out
   or lost Create result keeps ownership/uncertainty for reconciliation; it
   must not create again or infer clean release from a new owner's empty list.
3. Immediately bind the exact returned Call path and owner to the already
   reserved key before clearing Create uncertainty or starting other work.
   Validate the created object's direction/state/identity against that key.
   A created-but-unstarted UNKNOWN object remains Preparing and is never
   offered as an incoming call or rebound to another session.
4. Freshly read this UNKNOWN Call's configured format from the qualified
   provider, applying the same current generation/profile and owner fences as
   incoming. Prepare the PCM endpoint with that format while microphone and
   playback remain closed. Missing/stale format or failed preparation cannot
   dispatch Start.
5. Immediately before targeted `Call.Start`, recheck the selected modem epoch,
   immutable unique owner, exact key/path, cancellation, collector/loss state
   and native UNKNOWN state. Mark Start pending before dispatch. Only this
   exact current owned object may Start; an old epoch never Starts. Remote
   dialing cannot occur before audio preparation and these gates pass.

Pre-Start failure/cancellation uses a distinct exact-object cleanup path.
`Call.Hangup` cannot clean an UNKNOWN object in this provider. Use the existing
same-owner `Voice.DeleteCall` only when that keyed object is freshly proven
UNKNOWN and Start has **never** been dispatched. Retain deletion uncertainty,
session/data ownership and prepared resources until same-owner keyed absence
is established and local PCM relay/capture/playback resource joins complete.
Normal call cleanup retains the native D-Bus signal collector, its same
connection/subscriptions and immutable owner. Rebinding, stopping or joining
that collector is not native release proof. Successful DeleteCall alone is
not proof that the full native owner is clean.

Once Start is pending/dispatched, or its result/native state is uncertain,
never use DeleteCall as native termination even if a later state read says
UNKNOWN. A method failure does not prove the remote side was untouched.
Call-path reuse, owner/proxy loss, unresolved Create/Start or failed cleanup
keeps the native session in Ending/quarantine until the existing owner-bound
termination/reconciliation/recovery establishes release. Active/potentially
started calls retain targeted QMI native-ID EndCall; DeleteCall does not replace
it. Do not release the session key or resume cellular data on a dirty outcome.

For either direction, after native Active, wait at most the existing 8-second
action/readiness deadline for compatible format and this same Call's actual
nonempty `AudioPort`. Check that port against the same owned modem's current AUDIO port
inventory; do not hard-code a ttyUSB index or infer readiness from port
classification. Open the audio pipeline only after the current Call,
generation/owner fences and port/format all agree. Metadata loss, timeout or
route failure uses exact-call termination/recovery, preserves original
resource-release rules and leaves music paused.

Keep QMI native-ID EndCall, all immutable Rust owner/epoch fences and the
reconnect implementation. Do not introduce `HangupAll`, global ATH/CHUP,
replay of old Answer/Dial, an application modem command sequence, or a second
reader of the modem transport. The provider is the sole owner of selection and
activation; Rust consumes its existing read-only properties and targeted call
methods.

## Tracked provider, profile and build inputs

Store the source lock, ordered DEP-3 quilt patches, focused tests, build recipe,
profile definition and maintenance documentation under
`deploy/providers/modemmanager/`. Preserve the original Debian patch and source
licenses; carry local changes as a small patch series rather than an unexplained
full fork. Each patch describes its origin, upstream status and removal rule:
remove it only when an adopted upstream/Debian version passes the same behavior
and lifecycle qualification. Package that version as a newly qualified profile.

The first package revision for this extension is
`1.24.0-1+deb13u1+yoyopod1`, distinct from the installed stock package. The
earlier proposal used this only as an example; no package was built under it.
A changed published patch or packaging input requires a new revision; never
publish different package bytes under the same version.

Build native ARM64 on the ARM CI runner inside a digest-pinned Debian trixie
container/chroot. Do not compile the package against the Ubuntu runner's host
libraries. The lock must include the actual image digest, dated Debian
snapshot, trusted archive keyring identity, signed metadata/descriptor hashes,
the two source archive hashes above, patch-series hash, exact build-dependency
versions and toolchain versions. Missing or unverifiable pins fail the build;
the spec supplies no invented image or dependency identities.

Use Debian's normal package build and hardening, record `SOURCE_DATE_EPOCH`,
run upstream and focused tests, and explicitly keep
`-Dat_command_via_dbus=false`. Preserve normal service/D-Bus/polkit configuration
and do not launch with `--debug`. Build the source package as well as binaries;
distribute corresponding patched source, license/copyright notices,
`.buildinfo`, `.changes`, test reports and package checksums. Build twice from
separate clean environments with identical locked inputs and compare outputs.
Only matching outputs support a bit-reproducibility claim; differences are a
release blocker until explained and resolved.

Inspect generated dependency constraints and include exactly the necessary
binary package closure. Do not assume the daemon `.deb` alone suffices or
replace system libraries outside that closure. The provider manifest records
full repository SHA, CI run identity, source/package versions, architecture,
build image/dependency-lock hashes, patch digest, installed executable hashes,
package names/versions/SHA256, and corresponding-source/test-report hashes.

The profile records the expected SIMTech/QMI implementation, exact modem and
firmware identity, candidate framing, selection/readback/lifecycle contract
revision, qualification status/evidence, and exact package/build manifest
identity. Candidate installation validates identity, provenance and supported
candidate scope; it does not require hardware framing/reset evidence to exist
before the corrected provider reaches the bench. A profile remains
`qualification_pending` until its tracked framing and reset/lifecycle evidence
is complete and reviewed. Rust treats this status as ineligible for Start/Accept.
Unknown firmware, stock or unknown package, mismatching executable/hash,
missing build provenance, or absent qualification also fail closed. Matching a
model name alone is insufficient. These are internal profile/deployment
statuses, not new device UI controls or a new public provider API.

## One exact-commit artifact

Bundle the provider under `providers/modemmanager/` inside the existing
`yoyopod-rust-device-arm64-<full-sha>` artifact, including its `.deb` closure,
manifest, corresponding source and reports. The top-level Rust artifact
manifest binds the provider-manifest digest and the same full repository SHA.
Use one successful exact-commit CI run for the Rust and provider outputs. A
provider sub-bundle has a manifest/digest, not a separately selected GitHub
artifact; there is no second version-selection path.

Verify the checkout SHA before building and artifact naming. Existing
feature-branch `workflow_dispatch` can obtain an exact build without a PR;
do not label a merge checkout with a head SHA. A missing/mismatching provider
bundle fails the explicit provider path, while a reconnect-only deployment
continues to use the ordinary exact-SHA Rust artifact path.

## Explicit dev maintenance and rollback

Add the proposed CLI option
`yoyopod target deploy --sha <full-sha> --install-provider modemmanager`.
This option is a new command contract to implement after written-spec and
written-plan review; it is not available yet. Omitting it must not install,
upgrade, downgrade or restart ModemManager, including through a prerequisites
helper. A reconnect-only deploy has no provider-maintenance authority.

The provider path is dev-lane-only and must never switch lanes implicitly. It
is a system-wide maintenance action even though the Rust deployment is dev
only. Execution remains subject to the user's review of this specification and
the concrete plan/maintenance scope. Approval of the preceding approach did
not already authorize replacing or restarting the installed provider.

The reviewed plan must authorize candidate installation and the controlled
qualification procedure explicitly. The stages have separate outcomes:

| Stage | Gate and reported outcome |
| --- | --- |
| Candidate ready to install | Locked source/build inputs, provider tests, reproducibility, exact artifact/package hashes, known candidate identity and rollback are valid. Hardware framing/reset qualification may still be pending. |
| Candidate installed for qualification | Package installation, running identity, fresh initialization, setter/readback and ordinary Rust/native-owner startup checks pass. If framing/reset evidence is incomplete, report `installed, qualification pending`; GSM Start/Accept remain disabled. This is not a full provider/audio qualification pass. |
| Profile qualified for Start/Accept | Reviewed tracked evidence establishes exact framing and reset/lifecycle invalidation for the installed package bytes and modem/firmware. The matching exact-SHA Rust artifact can enable existing targeted Start/Accept under all normal owner/session fences. |
| Feature accepted | First/second incoming calls, outgoing dialing, bidirectional audio, targeted cleanup and reconnect functional tests pass after the profile qualification gate. This is the final feature gate, not a prerequisite for installing the candidate. |

Preflight and staging complete before any service is stopped:

1. Enforce clean committed/pushed exact-SHA selection and the existing CI
   artifact contract. Verify the Rust/provider manifests, every staged file
   hash and the common SHA/run identity.
2. Verify Debian trixie ARM64, exact modem/firmware identity within the reviewed
   candidate profile scope, identity of the existing provider being replaced,
   package manager health and the exact dependency transaction. Reject
   unrelated package changes, an external package transaction or automatic
   upgrade conflict.
3. Verify active dev lane, inactive prod lane, no unmanaged hardware owners,
   exactly one normal ModemManager owner, and no nonterminated incoming or
   outgoing Calls on any managed modem. Refuse maintenance while a call exists;
   do not end a call to make deployment possible.
4. Stage the complete candidate closure and exact prior package closure,
   including package bytes/hashes, package versions, relevant service/config
   state and rollback instructions. Simulate both forward and rollback
   transactions with offline staged files; lack of an exact restorable prior
   set stops preflight. Capture the prior Rust artifact/checkout identity for
   a coherent rollback. A successful download is not package-install atomicity.

After successful preflight and within the authorized maintenance scope, hold
an exclusive maintenance lock, stop the dev runtime/native network owner and
verify its exit. Recheck call inventory immediately before stopping the single
system ModemManager service. Install the staged closure through the package
manager using the simulated exact transaction, without fetching unpinned
packages. Control package-triggered service starts so no duplicate/early owner
can race the transaction; then start one normal ModemManager service.

Require a new unique D-Bus owner, actual running executable/package identity,
fresh modem initialization and successful current-generation selection/readback.
Only then install/start the exact-SHA dev Rust artifact and verify startup and
native-owner discovery/identity health. When qualification is pending, verify
that the native owner keeps Start/Accept closed; this expected fail-closed result
does not trigger rollback. Missing framing/reset qualification alone reports
`installed, qualification pending` and preserves the validated candidate for
the reviewed evidence-gathering procedure. Do not report PCM readiness or
bidirectional audio success from these installation checks.

Gather selection and metadata/lifecycle evidence through the candidate's
provider-owned fixed sequence, existing read-only Call/modem properties,
normal journals and the reviewed lifecycle procedure. An incoming Ringing
offer may be inspected and rejected without Accept to check property
propagation; call-free disable/re-enable or observed reprobe/reset can check
invalidation. No arbitrary AT/debug access, manual provider replacement,
independent serial reader or new public API is introduced. Framing evidence
must be primary vendor evidence or an explicitly reviewed bench procedure
that preserves the same ownership/security boundary and keeps GSM Start/Accept
disabled. If no such bench procedure is available, qualification remains
pending; that is not permission to bypass the gate.

Commit the reviewed qualification evidence/profile before enabling Start/Accept.
Produce the matching exact-SHA CI artifact and validate it through the normal
deploy path. Evidence can carry forward only when the locked provider inputs,
rebuilt package bytes/hashes and modem/firmware identity are unchanged; a
profile-only evidence update need not change package revision. The final
artifact still binds provider and Rust manifests to its one repo SHA/run.
Changed provider bytes require new qualification and the explicit maintenance
path again. Incoming and outgoing audio testing follow this profile gate.

Keep SIP/media and modem/data behavior under the existing runtime ownership
rules; no parallel daemon, hand-copied executable,
debug service override or expanded security policy is allowed.

If installation, running identity, fresh initialization, fixed selection/
readback or ordinary runtime/native-owner health fails, stop/keep stopped the
Rust native owner while restoring the exact prior package closure and
service/config state through the package manager. Allow downgrade only for
that captured closure. Restart the single prior normal provider, require a new
owner and fresh initialization, then restore the prior exact Rust deployment.
An unqualified prior provider remains ineligible for GSM Start/Accept. If rollback
cannot verify a coherent provider/native-owner state, keep GSM acceptance
disabled and report the failed stage and recoverable saved identities; do not
declare success or release a dirty native session as clean.

Record forward/rollback commands, exit statuses, installed closure and owner
transitions in the deployment result. Security updates are not suppressed
forever by the source pin: a changed provider identity invalidates qualification
until the patch is rebased, rebuilt and requalified against the security
release. The profile check must reject an unnoticed upgraded provider rather
than silently retain an old acceptance claim.

## Verification and acceptance matrix

Provider tests run the actual modified C helpers/constructors with mocked
asynchronous AT completion and private test D-Bus. Source-text checks alone do
not prove the contract. Run upstream tests as well as these regressions:

| Test case | Required observation |
| --- | --- |
| First initialization, setter ACK and readback `1` | First incoming Ringing Call has configured candidate format and empty port; qualification remains a separate Rust gate before Accept; no premature `CPCMREG=1`. |
| Unsupported command, setter error/timeout, readback error/timeout/`0`/malformed/duplicate, or cancellation | Format remains unknown; no fallback and no publication from capability flags. |
| Call created before selection finishes; incoming and outgoing generic constructors | Current successful format reaches the exported Call; constructors do not overwrite it with NULL; outgoing UNKNOWN receives format before Start/native Dial. |
| Native Active before channel completion | Existing Call gains the actual port and compatible format only after successful activation. Failed activation leaves port empty despite generic setup success. |
| Ongoing versus terminated Calls; shared activation | Ongoing Calls update, ordinary terminal updates are skipped, and one terminal Call does not disconnect a channel still in use. |
| Last-channel cleanup and two subsequent incoming calls | Connected state is released once; configured format survives; each next Ringing Call begins with empty port. |
| Same-object disable/re-enable, reinitialization and observed reset/removal | Both metadata lifetimes invalidate; fresh selection/readback is required; exported stale metadata clears. |
| Late selection/setup/cleanup after invalidation or replacement operation | Old task cannot publish, clear newer task state or disconnect a newer channel; references/cancellables are released. |
| QMI SIMTech and unaffected plugin paths | QMI Call class/native-ID EndCall survive; other plugins retain intended format semantics; no global termination fallback. |
| Package/build contract | Tests pass; Debian closure/source/licenses are complete; no new security API/grant/debug mode; two clean package builds match. |

Affected Rust tests must cover pre-Accept format with delayed Active port,
format/port loss, a present candidate dictionary with pending qualification,
unknown profile identity, wrong modem AUDIO port, readiness timeout, old
owner/reused path/session epoch, and targeted cleanup/reconnect.
Retain the existing immutable owner/epoch tests and original call-manager
acceptance coverage. Outgoing ownership tests must exercise the real ordered
helpers with fake native/audio effects at every boundary:

| Outgoing boundary | Required observation |
| --- | --- |
| Before Create, cancellation or lost modem epoch | Existing key/data reservation is reconciled without Create, Start or an unowned object. |
| Create dispatched, result pending/error/lost owner | Create uncertainty retains exact key/data ownership; no replay, no new-owner empty-list cleanup proof and no Start. |
| Create returns UNKNOWN | Exact path binds to its existing key before Create uncertainty clears; collector refresh cannot offer it as incoming or change session ownership. |
| Format read/PCM preparation fails or cancels before Start | Only the same-owner keyed, proven never-started UNKNOWN object uses DeleteCall; no Hangup of UNKNOWN or native Dial; release waits for absence plus local PCM resource joins while retaining the native signal collector. |
| Preparation succeeds, then cancellation/epoch loss/path reuse before dispatch | Fresh gate blocks Start; uncertain identity retains Ending/quarantine rather than deleting a replacement object. |
| Start pending, method failure, native state uncertainty or owner loss | Never downgrade to DeleteCall cleanup, including a later UNKNOWN read; retain ownership until targeted termination/recovery proves release. |
| Valid current key, qualified format and successful preparation | Targeted Start occurs once only after gates; Active port/readiness and QMI native-ID EndCall work without a static rate. |

CLI tests must prove opt-in behavior, no-call/lane guards,
complete staging before stop, dependency/manifest rejection and exact rollback
ordering, plus `qualification_pending` installation without Start/Accept, a false
audio pass or automatic rollback. Run Rust formatting, appropriate workspace
checks and affected crate tests. Provider tests do not replace Rust owner tests.

Hardware qualification first installs a validated candidate under the reviewed
maintenance/qualification scope, then gathers framing/reset evidence with
Start/Accept disabled, and finally runs calls in both directions after the
tracked profile is qualified. Each stage uses the pushed full-SHA CI artifact
and authorized CLI path; build neither Rust nor ModemManager on the Pi. Base
`yoyopod target validate` stages can check deployment/runtime stability. GSM
call/audio acceptance is a recorded manual hardware test until its dedicated
validator exists; the current VoIP/cloud-voice stubs do not establish a pass.

| Hardware sequence | Required evidence |
| --- | --- |
| Candidate installation while qualification is pending | Package identity/init/selection and Rust/native-owner health pass; Start/Accept stay disabled; result says `installed, qualification pending`, not full audio success. |
| Framing and reset/lifecycle qualification | Reviewed evidence is complete for the exact package bytes and modem/firmware before the tracked profile becomes eligible for Start/Accept. |
| Fresh boot/provider init | Exact running provider/package/profile and unique owner; current setter/readback success; no stale format or active port. |
| First saved-contact incoming call | First Ringing Call exposes format before physical-button Accept; runtime admission/mode/UI behavior matches the original specification. |
| Targeted Accept, native Active and delayed port | Same native Call and owner; actual AUDIO port appears after activation; audio starts only when all readiness checks pass. |
| Conversation and targeted end | Both directions are intelligible on the supported Whisplay route; exact native-ID EndCall terminates only the owned call; microphone/speaker and data handoff clean up. |
| Second incoming call after cleanup | Format is already available with empty port; Accept, activation, intelligibility and targeted cleanup succeed again without reusing activation. |
| Outgoing call after clean release | Same-key Create exports UNKNOWN without remote ringing; qualified format is read and PCM prepared before targeted Start; actual Active port, bidirectional intelligibility and native-ID EndCall then succeed without a configured-rate override. |
| Outgoing pre-Start cancellation/audio failure | No remote Dial; only proven unstarted UNKNOWN uses keyed DeleteCall; exact absence/local PCM resource joins precede session/data release without replacing the retained native signal collector. |
| Observed disconnect/reset and reconnect | Metadata invalidation and a fresh generation/selection/readback are visible; old call results are ignored; no session releases ownership while backend audio may remain live. |
| Failed/unsupported selection and unknown identity fixtures | Acceptance stays closed, diagnosis identifies missing evidence, and no guessed format or global hangup appears. |

The result must state full repo SHA and CI run, exact Rust artifact name,
provider sub-bundle manifest digest, package closure/versions/hashes, source and
patch digest, modem/firmware/profile identity, commands/exit results, D-Bus owner
and call identities, observed property ordering, audio observations and cleanup
results. Redact secrets and personal call identifiers in shared reports.
Operational diagnostics use existing logging; they add no synchronized call
log or dashboard feature.

## Evidence still required before acceptance

The source investigation establishes the metadata/timing defects and the
documented rate-selection command. It has not supplied trusted descriptor
signature verification, qualified exact PCM framing for the installed
firmware, a successful live `CPCMFRM?` response from that firmware, proof that
its supported reset paths invalidate provider/Rust evidence, two matching clean
package builds, or incoming/outgoing bidirectional hardware results. Build and
provenance gates precede candidate installation; framing/reset gates precede
Start/Accept; functional audio gates follow qualified native control. They are
not presumed successes or one impossible preinstallation prerequisite. Wiring/power remains
unconfirmed and cannot be used as a diagnosed cause.

If primary vendor framing evidence is unavailable, bench qualification must be
completed within separately reviewed hardware scope before accepting the
profile and running the normal call-manager audio test. This spec does not
authorize a product fallback or unrestricted modem diagnostic to bypass that
gate. If reset visibility or framing cannot be qualified, the extension remains
unaccepted and GSM audio acceptance stays closed.

## Trade-offs and next review

| Choice | Benefit | Cost/alternative considered |
| --- | --- | --- |
| Provider-owned setter plus readback | Current configuration evidence with fixed bounded commands and one modem owner. | Adds firmware/readback qualification and provider maintenance; setter-only ACK is weaker evidence and is not selected. |
| Separate configured format and active channel | First-call pre-Accept metadata and second-call readiness survive ordinary cleanup while resets invalidate both. | Needs explicit lifecycle/callback tests; one forever-cached format or a constructor-only patch fails these requirements. |
| Existing Call properties and QMI class | Preserves targeted signaling and security/public API boundary. | No atomic generation-and-Start/Accept method; acceptance requires demonstrated lifecycle visibility and immutable Rust fences. |
| Create owned outgoing UNKNOWN before PCM preparation | Constructor metadata serves outbound without dialing before readiness. | Requires exact-key creation uncertainty and proven unstarted DeleteCall cleanup; preparing before Create cannot read per-call provider format. |
| Exact Debian patch and package closure | Narrow source scope and repeatable rollback. | Must rebase/requalify security updates; a full provider upgrade has broader compatibility scope and no demonstrated fix here. |
| Provider inside the exact-SHA Rust artifact | One provenance/selection path binds provider and native consumer. | Larger artifact and ARM Debian build; separate independently selected artifacts are not used. |

After the user approves this written specification, prepare a sequenced written
implementation plan with source/test ownership, the locked build inputs,
qualification work and the explicit provider-maintenance scope. The user must
review that plan and select execution before implementation of this new
extension. The already-authorized Rust reconnect work remains a separate
handoff and can be deployed without changing the provider.
