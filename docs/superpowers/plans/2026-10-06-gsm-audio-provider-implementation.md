# GSM Audio Provider Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Subagent-driven execution was already selected; do not ask for the method again. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore incoming and outgoing GSM audio using current, provider-owned format evidence, exact native-call ownership and an explicitly maintained Debian provider package.

**Architecture:** Patch ModemManager's private voice/SIMTech implementation to separate initialization format from activated channel state and publish existing Call properties. Rust consumes a qualified profile and current metadata before targeted Start/Accept; the CLI stages and installs a verified dev-only package closure from the same exact-SHA artifact. Candidate installation can remain qualification pending with Start/Accept closed; applicable framing evidence is currently missing, so final audio acceptance is blocked until that evidence exists within the approved qualification boundary.

**Tech Stack:** Rust 2021, blocking zbus 5.12.0, GLib/GObject C, Meson, Debian quilt/dpkg, Bash/jq, native ARM64 CI in a digest-pinned Debian trixie environment.

**Spec:** [Approved GSM audio provider specification](../specs/2026-10-06-gsm-audio-provider-design.md), approved 2026-10-06; content committed at `7a65ffa8247f4c4a0ecadfe4b4786d0fee9b905d` before approval-status metadata.

**Status:** Written plan for user review. No provider implementation or maintenance action is authorized by presenting this plan. The coordinator commits the plan; the plan writer changes only this document.

## Global Constraints

- Work on existing `codex/call-manager`; original feature base is `31a7713640e1d14419ee6b0aca95f76d1c721637`. No new worktree/branch, PR, main or prod action.
- Preserve the approved original call manager and reconnect owner/epoch fences. Contacts, modes, priorities, interruption, one foreground session, UI/buttons and cleanup policies remain unchanged; music stays paused. Logs/dashboard synchronization stays deferred.
- Supported device: Pi Zero 2W, Whisplay, PiSugar 3, and qualified SIM7600G-H firmware/provider. Wiring/power is unknown; no physical cause has been diagnosed.
- Baseline provider: Debian `1.24.0-1+deb13u1`; initial patched revision: `1.24.0-1+deb13u1+yoyopod1`. Never publish different bytes under one package version.
- Required provider sequence: uncached `+CPCMFRM=1` ACK followed by one uncached `+CPCMFRM?` result `1`, each bounded to 3 seconds, no retry and no 8 kHz fallback.
- Candidate dictionary: `{encoding: "pcm", resolution: "s16le", rate: uint32(16000)}`. Its presence is not framing qualification. `qualification_pending` keeps both Start and Accept closed.
- Preserve QMI Call class and native-ID EndCall. No global ATH/CHUP/HangupAll, independent AT reader, static rate override, arbitrary AT/public PCM API, debug daemon, new polkit grant or replayed native commands.
- Preserve the retained native D-Bus connection/signal collector during normal call cleanup. Join local PCM relay/capture/playback resources; collector destruction/rebinding is not native release evidence.
- Build Rust and ModemManager off-Pi. Use digest-pinned Debian trixie ARM64 on the ARM runner; verify signed source/archive metadata, real dependency pins, upstream/focused tests, two clean matching package builds, corresponding source/licenses and normal `at_command_via_dbus=false`.
- Provider stays inside `yoyopod-rust-device-arm64-<full-sha>` with all nine current Rust binaries. Rust/provider manifests bind the same SHA and CI run; no second artifact selector.
- Only `target deploy --install-provider modemmanager` changes/restarts the system provider. Stage candidate and exact prior closure before stop; dev only, no calls, one owner, new unique owner/fresh init after maintenance, exact rollback.
- Qualification evidence precedes Start/Accept eligibility; functional incoming/outgoing calls follow that gate. Calls are user-controlled; agents do not dial/contact people to generate evidence.
- Every task ends with scoped tests and a fresh reviewer gate before the next task. Workers are not alone: respect the coordinator's files/deployment and other owners' edits; stage only task-owned files.

## Review Focus

1. Async completion from an invalidated generation or replaced operation must free its own results without publishing stale format/port or clearing a newer task (Tasks 2–3).
2. Same-path reset, same-owner reprobe or provider security upgrade must invalidate eligibility; old evidence/key/data leases cannot become a fresh admission (Task 4, retained reconnect tests in Task 5).
3. Partial package installation followed by failed rollback must keep the native owner stopped and report recovery state, never start mixed provider/Rust identities (Task 7).
4. Create uncertainty, cancellation after object creation, and pending/failed Start must preserve exact ownership; DeleteCall is limited to proven never-started UNKNOWN (Task 5).
5. Present candidate metadata with pending/missing qualification must not enable Start/Accept or be mistaken for installation failure/full audio success (Tasks 4, 7–8).

---

## Current interfaces and ownership map

The current `rust-device-arm64` job in `.github/workflows/ci.yml` uses `ubuntu-24.04-arm`, builds runtime/UI/cloud/media/VoIP/network/on-Pi/power/speech binaries, and tars only `device/`. Its artifact SHA is a PR head expression while checkout currently uses the default ref; Task 6 makes checkout and naming agree. Feature branches use `workflow_dispatch`, without creating a PR.

`cli/yoyopod/src/commands/target/deploy.rs::run` checks clean/pushed code, selects a successful exact-SHA CI run, downloads `.artifacts/rust-device/<sha>/`, syncs the checkout, runs `modem_manager_prerequisites_command`, uploads/extracts the bundle and uses `ops::build_restart`. The prerequisites helper can currently install/restart ModemManager and change udev rules. Task 7 separates this behavior from ordinary deployment; existing rules/security grants are not expanded.

`device/network/src/gsm.rs` owns blocking proxies, retained `ModemSignals`, `selected_epoch`, `owner`, `uncertain_create`, `CleanupEvidence`, `prepared_audio` and `audio`. `dial_session` currently prepares `sample_rate(None)` before Create; `apply_call` reads Ringing metadata before Accept; `start_owned_audio` waits for Active port. `gsm_calls.rs::register_outgoing` binds canonical keys. `worker.rs::enqueue_gsm_command` already reserves keyed data and sends at an acknowledged admission epoch; keep that contract. Runtime's `network.configure` supplies no rate and must not acquire a guessed rate.

| Task owner | Exact repository files and responsibility |
| --- | --- |
| 1: source/build-input owner | Create `deploy/providers/modemmanager/source-lock.json`, `build/resolve-lock.sh`, `build/verify-inputs.sh`, `tests/test-source-lock.sh`, `README.md`. Genuine lock acquisition/validation, not placeholder scaffolding. |
| 2: generic provider owner | Create `patches/series`, `patches/0002-yoyopod-voice-audio-lifecycle.patch`, `tests/provider-fixture.h`, `tests/provider-fixture.c`, `tests/test-voice-audio.c`, `build/test.sh`. Modify extracted upstream `src/mm-iface-modem-voice.c`, `src/mm-iface-modem-voice.h`, `src/meson.build`, `src/tests/meson.build` only through the patch/staging recipe. |
| 3: SIMTech/package owner | Create `patches/0003-yoyopod-simtech-pcm-readback.patch`, `patches/0004-yoyopod-audio-contract-tests.patch`, `tests/test-simtech-audio.c`, `build/build.sh`, `build/compare.sh`, `profile.json`, `manifest.schema.json`; update source lock/series/README. Modify extracted `src/plugins/simtech/mm-shared-simtech.c`, Debian changelog/rules and test registration through recorded patches. |
| 4: profile/readiness owner | Create `device/network/src/gsm_provider.rs`; modify `device/network/src/{lib.rs,gsm.rs,worker.rs}`, `device/network/Cargo.toml`, `device/Cargo.lock`, `device/runtime/src/runtime_loop/calls.rs`, `device/runtime/src/runtime_loop/calls/{operations.rs,tests.rs}`, `device/ui/src/components/screens/common.rs` and inline model tests. Profile/current-metadata gate, correlated failure visibility, runtime action/projection guard and existing incoming state-label reason. |
| 5: native outgoing owner | Create `device/network/src/gsm_pcm.rs`; modify `device/network/src/{lib.rs,gsm.rs,gsm_calls.rs,worker.rs}` and their actual tests. Minimal PCM-effect adapter, ordered Create/prepare/Start, unstarted deletion, uncertain ownership and data release. This follows Task 4 serially. |
| 6: artifact owner | Modify `.github/workflows/ci.yml`; create `deploy/providers/modemmanager/build/bundle.sh`, `tests/test-bundle.sh`. Add provider to existing nine-binary artifact and bind expected build identity into Rust. |
| 7: deployment owner | Create `cli/yoyopod/src/commands/target/provider.rs`, `deploy/providers/modemmanager/deploy/transaction.sh`, `tests/test-transaction.sh`; modify `cli/yoyopod/src/{cli.rs,commands/target/mod.rs,commands/target/deploy.rs}`, CLI Cargo files, `cli/README.md`, `docs/operations/DEV_PROD_LANES.md`. Exact opt-in staging/maintenance/rollback. |
| 8: qualification coordinator | Create `deploy/providers/modemmanager/qualification/evidence.md`; update `profile.json` only after proof, plus README operation instructions and final validation record. Coordinator alone operates the Pi; user controls calls. |

All paths in the provider rows are relative to `deploy/providers/modemmanager/` unless explicitly rooted. Extracted source is disposable build input, never a tracked full fork or product mirror. Each local patch includes DEP-3 origin, scope, upstream status and removal criterion. Preserve Debian's existing `0001-shared-fibocom-don-t-assume-parent-implements-the-fi.patch` first.

## Shared contracts

Use schema version `1` for lock/profile/manifests; `serde(deny_unknown_fields)` in Rust and strict jq validation in build tools. JSON keys are shared across tasks:

- `source-lock.json`: `schema_version`, `source_version`, `package_version`, `architecture`, `image` (ARM64 digest reference), `snapshot`, `source_date_epoch`, `archive_keyring_sha256`, `maintainer_keyring_sha256`, `signed_metadata` (URI/hash/signer fingerprint), `sources` (URI/hash), `build_dependencies` (name/version/architecture/package hash), `toolchain`, `patches` (ordered path/hash). No null or floating build pins.
- `profile.json`: `schema_version`, `profile_id`, `qualification` (`qualification_pending` or `qualified`), `modem` (manufacturer/model/revision/hardware_revision/plugin), `qmi_primary_type=6`, `format` (encoding/resolution/rate/channels), `contract_revision`, `evidence` (relative path/hash and covered identities). Initial observed candidate: `QUALCOMM INCORPORATED`, `SIMCOM_SIM7600G-H`, `LE20B04SIM7600G22`, `10000`, `simtech`; not qualified by those strings.
- Provider `manifest.json`: `schema_version`, `repo_sha`, `ci_run_id`, `source_version`, `package_version`, `architecture`, `source_lock_sha256`, `patch_series_sha256`, `profile_sha256`, `daemon_sha256`, `packages` (relative file/name/version/architecture/SHA256), `source_files` (relative file/SHA256), `reports` (relative file/SHA256). Hash source/tests/buildinfo/changes/licenses too; runtime compares daemon hash, not a `.deb` hash to executable bytes.
- Artifact `manifest.json`: `schema_version`, `repo_sha`, `ci_run_id`, nine binary file/hash entries, `provider_manifest_sha256`. Provider bytes live at `providers/modemmanager/`; no independent GitHub artifact.
- Installed receipt `/var/lib/yoyopod/providers/modemmanager/installed.json`: `schema_version`, verified `manifest`/`profile` copies, their SHA256 fields and maintenance-attested `running_identity` (`bus_id`, `unique_owner`, `pid`, `process_start_ticks`, `running_daemon_sha256`, `installed_executable_sha256`, `package_version`, `architecture`), root-owned `0644`, directory root-owned `0755`. Canonical privileged maintenance hashes actual `/proc/<pid>/exe` and binds it to that owner/process; Rust cross-checks receipt/current readable identity. It cannot override compiled profile/current metadata. Unexpected provider restart invalidates the receipt until explicit canonical maintenance reattests; ordinary deploy performs no provider restart/automatic attestation refresh.

In every manifest, `repo_sha` is a 40-character lowercase hexadecimal string and `ci_run_id` is a decimal string. SHA256 fields contain exactly 64 lowercase hexadecimal characters. `evidence` requires separate framing and lifecycle records for `qualified`; each record contains `kind`, `path`, `sha256`, and the exact covered modem fingerprint/provider input digest. Pending profiles use an empty evidence list. No vendor PDF is redistributed without permission; source references include URI, document hash, revision/pages and applicability assessment in the reviewed evidence record.

Runtime gets the expected provider manifest through compile-time `YOYOPOD_MM_BUILD_MANIFEST` JSON set by Task 6; absent locally means ineligible, never a fallback manifest. Embed tracked `profile.json` with `include_str!`. A profile-only final commit can carry qualification forward only if rebuilt provider inputs/package bytes and modem/firmware match the evidence; final manifests still use the final repo SHA/run.

Receipt origin SHA/run may precede a profile-only final artifact. Runtime compares receipt's source-lock/patch-series/package closure/daemon hashes to compiled expected provider **inputs/bytes**, validates its protected copied-manifest digest, and uses the final compiled profile's qualification. It does not require the old installed receipt's profile/SHA/run to equal the rebuilt profile-only artifact, silently rewrite that receipt, or trust an old pending profile to qualify. A test pins this legitimate identical-bytes carry-forward and rejects any changed provider input/package/process identity.

### Task 1: Acquire and validate genuine Debian ARM64 input pins

**Files/ownership:** Task 1 row above. No provider patch or package install on the Pi.

**Interfaces:** `resolve-lock.sh OUTPUT_JSON` resolves literal pins in an ARM build environment; `verify-inputs.sh LOCK CACHE_DIR` verifies provenance/hashes and stages the exact source; both exit nonzero on missing/mismatching evidence. Later `build/test.sh` and `build/build.sh` consume that verified source and lock.

Consumes: exact upstream source version/archives and official signed Debian snapshot indexes. Produces: reviewed literal `source-lock.json`, verified source in `CACHE_DIR/source/` and `CACHE_DIR/signature-report.json`; stdout is diagnostic only, never the source of build pins.

- [ ] **Step 1: Write a failing lock-validation test.** The shell test resolves a real candidate lock once, makes invalid copies in `mktemp -d`, and invokes the actual validator:

```bash
set -euo pipefail
test_dir=$(mktemp -d)
trap 'rm -rf -- "$test_dir"' EXIT
valid_lock="$test_dir/resolved.json"
bash build/resolve-lock.sh "$valid_lock"
jq 'del(.image)' "$valid_lock" > "$test_dir/missing-image.json"
if bash build/verify-inputs.sh "$test_dir/missing-image.json" "$test_dir/cache"; then
  echo 'accepted floating/missing image pin' >&2; exit 1
fi
jq '.sources[0].sha256 = "00"' "$valid_lock" > "$test_dir/bad-hash.json"
if bash build/verify-inputs.sh "$test_dir/bad-hash.json" "$test_dir/cache"; then
  echo 'accepted invalid source hash' >&2; exit 1
fi
```

Also mutate descriptor signer, signed metadata hash, dependency version/hash, architecture and snapshot. The validator must fail before extraction/build; actual fixtures with unknown keys fail rather than silently downgrade validation.

- [ ] **Step 2: Run RED.** From this provider directory on Linux ARM: `bash tests/test-source-lock.sh`. Expected nonzero because resolver/validator/lock do not exist, then explicit rejection when malformed locks reach the validator. Do not treat a missing tool alone as the final negative test.

- [ ] **Step 3: Implement literal pin acquisition, not invented values.** Use the official Debian image manifest to resolve its ARM64 child digest, then fetch a dated snapshot and verify its signatures. These are execution-time commands, not actions performed while writing this plan:

```bash
docker buildx imagetools inspect docker.io/library/debian:trixie-slim --raw > image-index.json
arm_digest=$(jq -er '[.manifests[] | select(.platform.os=="linux" and .platform.architecture=="arm64")] | if length==1 then .[0].digest else error("ambiguous ARM64 image") end' image-index.json)
image="docker.io/library/debian@$arm_digest"
docker image inspect "$image" >/dev/null 2>&1 || docker pull --platform linux/arm64 "$image"
```

The resolver runs inside that digest image. Start with requested snapshot `20261006T000000Z`; record the actual fetched snapshot URI and signed metadata bytes, and fail if the exact source version is unavailable. Configure snapshot `deb` and `deb-src`, preserve trusted Debian keyrings, and obtain the build-dependency closure of the exact extracted Debian control file. Record `dpkg-query -W -f='${binary:Package}\t${Version}\t${Architecture}\n'`, resolved `.deb` hashes from signed Packages indexes, compiler/Meson/dpkg versions, image manifest hash and key fingerprints. Snapshot expiry relaxation applies only to the fixed historical snapshot with verified signature/hash; it is not an unsigned-repository exemption.

```bash
gpgv --status-fd=1 --keyring /usr/share/keyrings/debian-archive-keyring.gpg InRelease > archive-signature.txt
apt-get source --download-only modemmanager=1.24.0-1+deb13u1
dscverify --keyring /usr/share/keyrings/debian-keyring.gpg modemmanager_1.24.0-1+deb13u1.dsc
sha256sum modemmanager_1.24.0.orig.tar.xz modemmanager_1.24.0-1+deb13u1.debian.tar.xz
```

Archive keyrings verify Release/Packages/Sources; the maintainer keyring verifies `.dsc`. Lock the verified signer and keyring package hashes; do not skip an unavailable signing key. Required archive hashes are `63ded4c0f3936bb0db5ae35ef1dfd57c5d5b4dd8a5cdaa7fb2182255218c9168` and `0362e74213576b3f830b344f139407843a6caf6b9ae892c5a085a340da6999f2`. Download tooling dependencies only in the build environment and capture their genuine versions/hashes in the lock. Never install build tooling on the Pi.

Implement validation with jq before fetching/extracting; pin checks include:

```bash
jq -e '.schema_version==1 and .source_version=="1.24.0-1+deb13u1"
 and .architecture=="arm64"
 and (.image|test("^docker.io/library/debian@sha256:[0-9a-f]{64}$"))
 and (.build_dependencies|length>0)
 and all(.sources[]; (.sha256|test("^[0-9a-f]{64}$")))' "$lock" >/dev/null
```

Set `SOURCE_DATE_EPOCH` from the locked provider source/packaging date, not a later profile/doc commit. Reject absent pins before using them. Verify signatures and archive bytes on every build; caching may avoid downloads, not verification. Document exact resolution outputs/commands in README. No fully qualified profile is created here.

- [ ] **Step 4: Run GREEN.** `bash tests/test-source-lock.sh`; `bash build/verify-inputs.sh source-lock.json .cache/verified`; check each invalid fixture exits nonzero and valid inputs reconstruct the exact Debian source/patch series. Review the actual resolved pins and signature report before accepting Task 1.
- [ ] **Step 5: Commit task-owned files.** `git add deploy/providers/modemmanager/source-lock.json deploy/providers/modemmanager/build/resolve-lock.sh deploy/providers/modemmanager/build/verify-inputs.sh deploy/providers/modemmanager/tests/test-source-lock.sh deploy/providers/modemmanager/README.md`; `git commit -m "build: lock verified Debian ModemManager provider inputs"`.

### Task 2: Separate provider configuration and active-channel lifetimes

**Files/ownership:** Task 2 row. Stage canonical tests into extracted `src/tests/` for this task; Task 3 records their exact bytes in the test quilt patch before packaging. Test registration changes may move `main.c` out of the shared source list and add it only to the daemon executable, allowing tests to link the same real daemon sources; do not replace core behavior with a model implementation.

**Interfaces:** Add private header token `MMVoiceAudioToken { guint64 generation; guint64 operation; }` and these internal helpers:

```c
typedef struct {
    guint64 generation;
    guint64 operation;
} MMVoiceAudioToken;
MMVoiceAudioToken mm_iface_modem_voice_audio_begin_configuration (MMIfaceModemVoice *self);
void mm_iface_modem_voice_audio_invalidate (MMIfaceModemVoice *self);
gboolean mm_iface_modem_voice_audio_publish_configured (MMIfaceModemVoice *self, MMVoiceAudioToken token, MMCallAudioFormat *format);
MMCallAudioFormat *mm_iface_modem_voice_audio_dup_configured (MMIfaceModemVoice *self);
MMVoiceAudioToken mm_iface_modem_voice_audio_begin_channel (MMIfaceModemVoice *self);
gboolean mm_iface_modem_voice_audio_commit_channel (MMIfaceModemVoice *self, MMVoiceAudioToken token, MMPort *port, MMCallAudioFormat *format);
gboolean mm_iface_modem_voice_audio_clear_channel (MMIfaceModemVoice *self, MMVoiceAudioToken token);
```

Configuration and channel operation IDs are separate. Publish/commit accept only live matching tokens; `dup_configured` returns a new reference or NULL. Channel cleanup begins a fresh channel operation, invalidates pending setup, and passes that cleanup token to clear-channel; stale cleanup cannot clear or disconnect a newer channel. Clearing consumes only its current operation and preserves configuration. Helpers are internal, not installed libmm-glib API.

Consumes: Task 1 verified source plus source lock. Produces: generic lifecycle patch/private token helpers, actual-helper/private-D-Bus regressions and `build/test.sh --filter NAME` / `build/test.sh --upstream` (exit zero only when requested tests pass).

Fixture declarations in `tests/provider-fixture.h` are concrete private test interfaces:

```c
typedef struct _VoiceFixture VoiceFixture;
VoiceFixture *voice_fixture_new (void);
void voice_fixture_free (VoiceFixture *f);
MMIfaceModemVoice *voice_fixture_voice (VoiceFixture *f);
MMBaseCall *voice_fixture_incoming (VoiceFixture *f, const gchar *number);
MMBaseCall *voice_fixture_outgoing (VoiceFixture *f, const gchar *number);
MMPort *voice_fixture_audio_port (VoiceFixture *f);
guint voice_fixture_read_format (VoiceFixture *f, MMBaseCall *call);
const gchar *voice_fixture_read_port (VoiceFixture *f, MMBaseCall *call);
void voice_fixture_complete_channel (VoiceFixture *f, MMVoiceAudioToken token,
                                     gboolean success);
void voice_fixture_cleanup_last_channel (VoiceFixture *f);
```

`VoiceFixture` owns a `GTestDBus`, a real modem/voice implementation, exported real Calls, returned borrowed objects/strings and mock serial transport. Constructors exercise real generic/provider constructors; getters read private D-Bus properties (`read_format` returns rate or zero for empty), and channel completion uses the actual async finish path. Link the production core/plugin objects, excluding daemon `main.c`. Wrap only fixed AT transport entry/finish effects using linker `--wrap`, with `GTask` results bound to the real source object; held completions and transport failures feed production callbacks. For QMI assertions, drive the actual QMI Call through a mock QMI transport and record native call ID/EndCall request, rather than asserting a class name on a surrogate Call.

- [ ] **Step 1: Write real-helper regressions.** Include first/second Ringing, outgoing UNKNOWN, in-flight publication, updater predicate, shared port, cleanup and stale callback. Representative C assertion:

```c
VoiceFixture *f = voice_fixture_new ();
MMIfaceModemVoice *voice = voice_fixture_voice (f);
MMVoiceAudioToken old = mm_iface_modem_voice_audio_begin_configuration (voice);
MMCallAudioFormat *format = mm_call_audio_format_new ();
mm_call_audio_format_set_encoding (format, "pcm");
mm_call_audio_format_set_resolution (format, "s16le");
mm_call_audio_format_set_rate (format, 16000);
mm_iface_modem_voice_audio_invalidate (voice);
MMVoiceAudioToken current = mm_iface_modem_voice_audio_begin_configuration (voice);
g_assert_false (mm_iface_modem_voice_audio_publish_configured (voice, old, format));
g_assert_true (mm_iface_modem_voice_audio_publish_configured (voice, current, format));
MMBaseCall *call = voice_fixture_incoming (f, "+49123456789");
g_assert_cmpuint (voice_fixture_read_format (f, call), ==, 16000);
g_assert_cmpstr (voice_fixture_read_port (f, call), ==, "");
g_object_unref (format);
voice_fixture_free (f);
```

Fixture numbers are test data, never dialed. Add channel setup→invalidate→new setup→old callback and old cleanup→new channel cases; assert current port/task survives and owned references are freed. These exercise Review Focus 1.

- [ ] **Step 2: Run RED.** `bash build/test.sh --filter test-voice-audio`; expected compilation failure for missing internal helpers, then failing first-call/second-call/property and token assertions on the uncorrected source.
- [ ] **Step 3: Implement generic lifecycle correction in the recorded patch.** Store configured format, generation/accepting-results and separate channel state/operation IDs in voice-owned object data. Consume async finish outputs into local references, then commit only matching generation/operation. Never recreate invalidated state from a callback. The core commit rule is:

```c
typedef struct {
    guint64 generation, configuration_operation, channel_operation;
    gboolean accepting_results;
    MMCallAudioFormat *configured_audio_format;
    MMPort *active_audio_port;
    MMCallAudioFormat *active_audio_format;
} VoiceAudioState;
/* ctx is the voice-owned VoiceAudioState; no callback allocates one. */
if (!ctx || !ctx->accepting_results || token.generation != ctx->generation ||
    token.operation != ctx->channel_operation)
    return FALSE; /* caller releases its own local port/format */
g_set_object (&ctx->active_audio_port, port);
g_set_object (&ctx->active_audio_format, format);
```

Use active format then configured format in constructor/update normalization; use only a successful active port. Fix ongoing updater to skip terminated Calls. Last-channel cleanup explicitly releases the old `MMPort` connected state exactly once, clears active port/format and surviving Calls' ports, but retains configured format. Disconnect only the owned old port before committing a replacement; a stale completion may free local references but may not disconnect the newer shared port or clear its task/cancellable pointer. Lifecycle invalidation advances generation, cancels operations and clears all observable old properties, including retained terminal objects. Wire initialization, disable, shutdown and observed invalidation/reset paths; no normal call-end generation advance. Tokens never wrap/reuse. Preserve QMI constructor/EndCall and other plugins' no-configured-state behavior.

- [ ] **Step 4: Run GREEN.** `bash build/test.sh --filter test-voice-audio`; assert first and two subsequent Ringing Calls, outgoing UNKNOWN constructor preservation, shared-port cleanup, ongoing/terminal update behavior, stale callbacks and cancellation reference cleanup. Run existing provider unit suite with `bash build/test.sh --upstream`. Make patch DEP-3 headers and source-lock patch hashes agree.
- [ ] **Step 5: Commit only Task 2 paths and changed lock.** `git add deploy/providers/modemmanager/patches deploy/providers/modemmanager/tests/provider-fixture.h deploy/providers/modemmanager/tests/provider-fixture.c deploy/providers/modemmanager/tests/test-voice-audio.c deploy/providers/modemmanager/build/test.sh deploy/providers/modemmanager/source-lock.json`; `git commit -m "fix: separate ModemManager configured and active audio state"`.

### Task 3: Require SIMTech ACK/readback and build the candidate Debian closure

**Files/ownership:** Task 3 row; functional SIMTech change stays in `src/plugins/simtech/mm-shared-simtech.c`. Debian rules explicitly preserve `hardening=+all` and add `-Dat_command_via_dbus=false`; service/polkit/D-Bus configuration is unchanged. Generate `0004-yoyopod-audio-contract-tests.patch` from the canonical fixture/test sources and registration, compare the applied patch's test bytes to the canonical files, and lock its digest. The final series is Debian 0001, lifecycle 0002, SIMTech 0003, tests 0004; no unrecorded test injection enters a source package. Debian changelog/rules modifications are tracked exact overlays in `build/build.sh`, included in the source package and input digest, not hidden edits or a full fork.

**Interfaces:** `build/build.sh --lock LOCK --repo-sha SHA --ci-run-id RUN --out DIR` builds in a clean locked container, runs all upstream/focused tests and produces source/binary packages, reports and `manifest.json`. `build/compare.sh FIRST SECOND` requires matching package/corresponding-source payloads and records report/provenance comparisons. `build/test.sh --filter test-simtech-audio` runs actual plugin callbacks with mock fixed AT transport.

Consumes: Task 1 verified input lock and Task 2 actual token helpers/tests. Produces: patched source closure, candidate `profile.json`, strict manifest schema, `build/build.sh` output and two-build comparison reports for Task 6.

Extend the same fixture with these declarations; held mock transport completions feed actual plugin callbacks after invalidation. No external modem participates.

```c
void voice_fixture_expect_at (VoiceFixture *f, const gchar *command,
                              guint timeout_seconds, gboolean cache_allowed,
                              const gchar *reply);
void voice_fixture_initialize (VoiceFixture *f);
void voice_fixture_disable_enable (VoiceFixture *f);
void voice_fixture_drain (VoiceFixture *f);
guint voice_fixture_at_count (VoiceFixture *f, const gchar *command);
```

- [ ] **Step 1: Add failing tests for exact commands and failure responses.** After actual initialization, the first Call must see rate only after both uncached completions:

```c
VoiceFixture *f = voice_fixture_new ();
voice_fixture_expect_at (f, "+CPCMFRM=1", 3, FALSE, "OK");
voice_fixture_expect_at (f, "+CPCMFRM?", 3, FALSE, "+CPCMFRM: 1\r\nOK");
voice_fixture_initialize (f);
voice_fixture_drain (f);
MMBaseCall *call = voice_fixture_outgoing (f, "+49123456789");
g_assert_cmpuint (voice_fixture_read_format (f, call), ==, 16000);
g_assert_cmpuint (voice_fixture_at_count (f, "+CPCMREG=1"), ==, 0);
voice_fixture_free (f);
```

Parameterize unsupported tests, setter ERROR/timeout, readback ERROR/timeout/`0`/empty/duplicate/malformed, cancellation, and stale completion. Require unknown format and no fallback. Test first enable preserves successful initialization; same-object disable/re-enable performs a new sequence; failed refresh cannot reuse old format. Successful channel setup returns actual port plus current format; failed activation returns no port even if generic setup succeeds. Assert real QMI Call type and mock native-ID EndCall; no generic AT subclass replacement.

- [ ] **Step 2: Run RED.** `bash build/test.sh --filter test-simtech-audio`; expected missing query/no dictionary failures against stock behavior, not merely source-text mismatches.
- [ ] **Step 3: Implement fixed provider sequence and candidate packaging.** Share one selection task between support initialization and enable refresh. Capture Task 2 configuration token plus strong source/cancellable. Setter finish must succeed before sending query; query parser must accept exactly one documented `+CPCMFRM: 1` response with whitespace/line-ending normalization and successful completion. Preserve existing support failures; capability flags are not proof. Publish candidate format only after token/lifecycle checks. The publication remains eligibility-neutral until Task 4's profile gate.

```c
MMCallAudioFormat *format = mm_call_audio_format_new ();
mm_call_audio_format_set_encoding (format, "pcm");
mm_call_audio_format_set_resolution (format, "s16le");
mm_call_audio_format_set_rate (format, 16000);
mm_iface_modem_voice_audio_publish_configured (voice, token, format);
g_object_unref (format);
```

Return a referenced current configured format only with successful channel finish. Neither Ringing nor created UNKNOWN activates CPCMREG. Populate candidate `profile.json` with observed identity and `qualification_pending`; `evidence=[]`. No fabricated signature, digest, firmware qualification or frame measurement.

Emit one bounded normal-level provider initialization result after the fixed selection task: contract revision/current internal generation and selection/readback success or failure. Do not log phone numbers, full modem responses or secrets. This permits call-free maintenance verification in normal daemon mode when `Calls=[]`; an installer cannot infer successful selection from nonexistent Call properties or require a diagnostic Call. Async/stale completion must not emit a current success marker. Test this same production completion path alongside metadata publication.

Inside the pinned environment, use `dpkg-buildpackage -us -uc` with exact dependency versions, fixed locked `SOURCE_DATE_EPOCH`, deterministic changelog for `+yoyopod1`, normal Debian hardening and no disabled tests. Generate actual dependency closure from produced `.deb` Depends plus target-compatible distro packages, using `dpkg-deb -f`; do not replace unrelated libraries. Preserve source archives, patch series, test sources, `.dsc`, `.buildinfo`, `.changes`, licenses and hashes in the output. Produce daemon hash from the extracted package's actual executable. Every manifest file path is relative, regular and within the output tree; reject symlinks/`..`.

- [ ] **Step 4: Run GREEN and two clean builds.** `bash build/test.sh --upstream`; `bash build/test.sh --filter test-simtech-audio`; invoke `build/build.sh` twice into distinct outputs from clean containers mounted at the same internal build path; `bash build/compare.sh first second`. Compare redistributed `.deb` and corresponding source bytes. Retain factual buildinfo/changes/report differences; do not claim those run-specific traces are reproducible unless they also match. Any unexplained package/source byte difference blocks candidate release. Record results, not just fixed inputs.
- [ ] **Step 5: Commit task-owned changes.** `git add deploy/providers/modemmanager`; inspect staged paths exclude caches/build outputs; `git commit -m "fix: attest current SIMTech PCM selection and package provider"`.

### Task 4: Gate current provider metadata with identity and qualification

**Files/ownership:** Task 4 row. Preserve existing signaling-isolation checks; profile/readiness failure must not convert rejected offers to accepted audio or weaken targeted cleanup. `worker.rs` rejects non-null `gsm_pcm_sample_rate_hz` as a bypass; runtime does not gain a new rate configuration.

**Interfaces:** In `gsm_provider.rs`, define `ProviderProfile`, `ProviderManifest`, `ProviderIdentity`, `Qualification` with the shared JSON contract; `VerifiedPcm` has private construction and `sample_rate_hz() -> u32`. Export `eligible_format(profile: &ProviderProfile, expected: &ProviderManifest, actual: &ProviderIdentity, format: &HashMap<String, zvariant::OwnedValue>) -> anyhow::Result<VerifiedPcm>`. Concrete identity reader contract:

Also export `provider_baseline_eligible(profile: &ProviderProfile, expected: &ProviderManifest, actual: &ProviderIdentity) -> anyhow::Result<()>` for qualified identity/provenance eligibility **without a Call**; `eligible_format` first calls this helper, then checks the current Call dictionary. Baseline eligibility is permission to create a keyed UNKNOWN object, never proof authorizing Start/Accept.

```rust
struct ModemFingerprint {
    manufacturer: String, model: String, revision: String,
    hardware_revision: String, plugin: String,
}
struct ProviderIdentity {
    package_version: String, architecture: String, running_daemon_sha256: String,
    modem: ModemFingerprint, primary_port: String, ports: Vec<(String, u32)>,
    bus_id: String, unique_owner: String, pid: u32, process_start_ticks: u64,
    installed_executable_sha256: String,
    receipt_manifest_sha256: String,
}
trait ProviderIdentityReader: Send {
    fn read(&self, connection: &zbus::blocking::Connection,
        unique_owner: &str, modem_path: &str) -> anyhow::Result<ProviderIdentity>;
}
```

Production reads fixed `dpkg-query` argv, readable `/proc/<pid>/stat`, fixed `/usr/sbin/ModemManager`, current D-Bus/modem identity and root-owned installed receipt; tests inject reads, not shell snippets. Coordinator's read-only `raouf` probe established `/proc/758/exe` hashing is denied, while stat and fixed executable hashing work. Therefore runtime does not attempt privileged running-exe hashing: `running_daemon_sha256` is the maintenance-attested process hash, accepted only when current bus/owner/PID/start-ticks/package/fixed-file/receipt identity agrees. Receipt, reader and transaction fixtures use the exact `running_identity` field names above. Missing attestation fails closed. Consumes: Task 3 profile plus Task 6 compile-time manifest (absent during interim builds is intentionally ineligible). Produces: eligibility and monotonically advancing local provider-lifetime/admission epoch on existing `GsmBackend`; Task 5 binds keys/preparation to it. No new public guard/property/security API.

- [ ] **Step 1: Write pending/upgrade/reset regressions.** Use explicitly synthetic fixture hashes and a real private D-Bus fixture. A candidate dictionary is insufficient:

```rust
#[test]
fn pending_dictionary_never_enables_control() {
    let profile = ProviderProfile::test_fixture(Qualification::QualificationPending);
    let expected = ProviderManifest::test_fixture();
    let actual = ProviderIdentity::test_fixture(&expected);
    let format = HashMap::from([
        ("encoding".into(), zvariant::OwnedValue::from(zvariant::Str::from("pcm"))),
        ("resolution".into(), zvariant::OwnedValue::from(zvariant::Str::from("s16le"))),
        ("rate".into(), zvariant::OwnedValue::from(16000_u32)),
    ]);
    assert!(eligible_format(&profile, &expected, &actual, &format).is_err());
}
```

Define those `#[cfg(test)]` fixture constructors in this task; they are not production defaults. Add qualified positive fixture, absent framing/lifecycle record, missing/wrong metadata types, 8000 rejection for this profile, wrong firmware/hardware/plugin/QMI port, unknown package, changed installed hash/version and absent compile manifest. Add missing/tampered/non-root-writable receipt, wrong attested running hash, changed bus ID/owner/PID/start ticks and denied stat/fixed-file read fixtures; they remain ineligible without requesting privileges. Positive normal-account fixture proves eligibility does not need `/proc/<pid>/exe` access and never equates installed-file hash alone with running hash.

For the ordered-message regression, extend existing `PrivateBus` with `LifecycleFixture::new_qualified() -> Self`, `epoch() -> u64`, `emit_modem_state(i32)`, `emit_call_format(Option<u32>)`, `flush_through_reply() -> Result<()>`, `refresh() -> Result<()>`, and `old_epoch_can_control(u64) -> bool`. These fixture methods emit real `PropertiesChanged`/`StateChanged` on unchanged owner/modem/Call paths, wait through the retained collector's reply barrier, and call the production gate; they do not simulate an alternative state machine.

```rust
#[test]
fn same_owner_path_reenable_does_not_restore_old_admission() {
    let mut f = LifecycleFixture::new_qualified();
    let old = f.epoch();
    f.emit_modem_state(4); // DISABLING, same unique owner/object
    f.emit_call_format(None);
    f.emit_modem_state(8); // REGISTERED again before the next property read
    f.emit_call_format(Some(16000));
    f.flush_through_reply().unwrap();
    f.refresh().unwrap();
    assert!(f.epoch() > old);
    assert!(!f.old_epoch_can_control(old));
}
```

Also queue existing `GsmWorker::send_at_epoch` Dial/Answer before the transition while the collector is held: after release the command fails its old epoch and issues neither Start nor Accept. Task 5's PCM-effect fixture adds delayed old Prepare/Create/Start/Accept result cases to this same bus lifecycle sequence. Fresh qualified metadata permits a new key only after clean idle reconciliation; old dirty native ownership remains retained. These tests cover Review Focus 2 and 5.

- [ ] **Step 2: Run RED.** `cargo test --manifest-path device/Cargo.toml -p yoyopod-network --locked gsm_provider`; expected missing module/gate failures, followed by behavior failures when the fixture is wired. Run private-bus cases on Linux with `dbus-daemon`, not this Windows seat.
- [ ] **Step 3: Implement strict eligibility and live identity reads.** Embed profile; parse compile-time manifest with no absent-value success. Add direct `sha2 = "=0.10.9"` (already genuinely present/checksummed in device lock); resolve/review CLI lock addition normally later. Resolve bus ID and `GetConnectionUnixProcessID` for immutable owner; compare readable process-start ticks, fixed installed hash/package and protected receipt's actual maintenance-attested running hash to compiled expected manifest. Verify owner/process identity again after reads. Reject non-root-owned or group/other-writable receipt/directory and symlink substitution. Package upgrade, unknown metadata or process replacement invalidates eligibility even if Version stays `1.24.0`. Reattestation after unexpected provider restart uses only explicit canonical Task 7 maintenance; no normal-deploy refresh, new grant, subprocess sudo or installed-path-as-running-hash shortcut.

```rust
anyhow::ensure!(profile.qualification == Qualification::Qualified,
    "GSM provider installed, qualification pending");
anyhow::ensure!(actual.package_version == expected.package_version
    && actual.running_daemon_sha256 == expected.daemon_sha256
    && actual.installed_executable_sha256 == expected.daemon_sha256,
    "GSM provider build identity changed");
```

Validate every modem fingerprint/profile/build field and exact `pcm/s16le/16000` dictionary before constructing `VerifiedPcm`; do not use the candidate/profile rate as live evidence. Replace `sample_rate(Option<&str>)` with required current Call path and eligible provider format. Preserve discovery and normal rejection/cleanup; gate outgoing Start and incoming Accept independently of Call discovery. Refresh metadata before control and Active audio; invalidate prepared proof on metadata loss/selected lifecycle change and retain dirty ownership. Current AUDIO inventory must contain the actual `AudioPort` and agree with prepared endpoint. No hard-coded ttyUSB index.

Extend the retained collector's ordered drain, currently focused on selected object removal, to consume observable lifecycle **values**: selected Modem State below ENABLED (`6`), voice-interface removal/unavailability, invalidated/empty/mismatching Call AudioFormat and loss/change of the owned active AudioPort. Process the `PropertiesChanged` changed/invalidated payload and `StateChanged` old/new values before later snapshots; a disable→reenable transition must latch even if a fresh GetAll already shows registered/16000. Property invalidation with unknown value closes the gate until a fresh ordered read. Ordinary last-call empty port with no prepared/active session is not a reset; preserve second-call configured-format behavior.

At the first observable invalidation, advance `selected_epoch` exactly once for that invalid lifetime, invalidate key-bound format/preparation proofs, join local PCM capture/playback/relay resources, fence old queued controls, and retain possible native ownership in Ending/quarantine. Keep the same native connection/collector. A later valid dictionary cannot revive old proof/key/intent; only fresh clean reconciliation can admit a new epoch/key. Reuse the existing ordered reply barrier and permanent evidence-gap quarantine before/after bounded property/native calls. A delayed Create/Start/Accept response from an old epoch must not publish Active/admit new work or synthesize native release. Preflight confirms normal-account readable identity/receipt operations; it never requires the already-denied unprivileged running-exe read or adds a grant.

Populate existing `GsmCallState.available/unavailable_reason` with context-appropriate eligibility while continuing native discovery and original known/unknown/mode handling. In clean idle, native readiness plus qualified provider baseline enables the outgoing route/Create request; no Call.AudioFormat/AudioPort exists or is required yet. For a displayed incoming Ringing Call, availability additionally requires that exact current Ringing dictionary to pass `eligible_format`, so Accept is disabled until format proof exists. Owned outgoing UNKNOWN may obtain format only after Create; Start independently requires that dictionary/preparation/current fences. Normal no-call empty port/ordinary terminal cleanup does not invalidate baseline or require a preceding successful call. Use concise reasons `Audio unavailable`, `Modem unavailable`, `Call audio failed`; retain PCM/profile/package/qualification details in existing diagnostics. Outgoing already consumes those fields. Incoming currently does not: `project_call` copies manager-only eligibility and CALL_STATE ignores the reason. Make the minimal correction here:

```rust
self.state.call.accept_enabled = self.manager.accept_enabled()
    && self.manager.session().is_none_or(|key|
        key.transport != CallTransport::Gsm || self.state.call.gsm_available);
```

In the runtime Session action path, before sending `UserAction(Answer)` to the manager, independently check that the key matches the current session and a GSM session is currently eligible. An ineligible matched Answer publishes the current reason and leaves Cancel/targeted Reject usable; it issues no Answer/data acquisition. Stale keys retain the existing manager fence. Network still performs fresh native/provider gates; the UI is not the authority. In `call_overlay_model`, use the existing `CallOverlayModel.state`/CALL_STATE text slot to display `gsm_unavailable_reason` for a blocked incoming GSM session before the generic CONNECTING/INCOMING text; no layout, labels, initial Accept focus, alert/wake/silent policy or protocol redesign.

Add actual runtime-loop tests using existing `fixture`, `offer`, `control` and `native_count`:

```rust
#[test]
fn gsm_pending_projection_and_answer_guard_agree() {
    let (mut runtime, mut io, key) = fixture(CallTransport::Gsm);
    runtime.state.call.gsm_available = false;
    runtime.state.call.gsm_unavailable_reason = "Audio unavailable".into();
    offer(&mut runtime, &mut io, &key, 100);
    assert!(!runtime.state().call.accept_enabled);
    control(&mut runtime, &mut io, &key, CallAction::Answer, 110);
    assert_eq!(native_count(&io, "answer"), 0);
    assert_eq!(runtime.state().call.gsm_unavailable_reason, "Audio unavailable");
}
```

Parameterize qualified GSM/SIP positive cases, stale displayed keys, lifecycle metadata loss and Cancel; Cancel must still produce the existing targeted Reject and cleanup. Inline UI model regression uses the real builder:

```rust
let mut snapshot = yoyopod_protocol::ui::RuntimeSnapshot::default();
snapshot.call.session = Some(SessionKey { transport: CallTransport::Gsm,
    generation: 9, call_id: "gsm-incoming-1".into() });
snapshot.call.session_phase = Some(CallPhase::Ringing);
snapshot.call.accept_enabled = false;
snapshot.call.gsm_available = false;
snapshot.call.gsm_unavailable_reason = "Audio unavailable".into();
let model = call_overlay_model(&snapshot, CallOverlayKind::Incoming, 0);
assert!(!model.accept_enabled);
assert_eq!(model.state, "Audio unavailable");
assert_eq!(model.focus_index, 0);
```

Import existing `SessionKey`, `CallTransport`, `CallPhase` in the inline test module. Exercise current navigator suppression; preserve both button labels/focus positions. Include preparation failure after a previously valid gate: when `calls/operations.rs` accepts a correlated current GSM native result, retain the failure's safe concise reason in existing GSM/overlay state before cleanup; stale/wrong-key results must not overwrite a current reason. Tests require `Call audio failed` visible after the matching Answer preparation failure and no false Active. Keep targeted cleanup/data ownership fences; no call-log/dashboard feature or general UI redesign.

Add qualified idle fixture with `Calls=[]` and no port/dictionary: outgoing route/request is enabled and Create occurs, while absent constructor format then blocks Start and uses proven unstarted cleanup. Repeat after normal terminal cleanup and after fresh clean lifecycle reconciliation. Task 5 positive case pins qualified idle→Create UNKNOWN→current format→prepare→Start. Pending baseline blocks initiating Create as well as both remote control actions. This avoids making per-Call evidence an impossible prerequisite to creating its object.

- [ ] **Step 4: Run GREEN.** `cargo test --manifest-path device/Cargo.toml -p yoyopod-network --locked gsm_provider`; run new private-bus profile/lifecycle tests and existing `gsm_reconnect`/`gsm_owner` filters. Run affected runtime-loop call tests and pure UI model/navigator tests; `cargo check --manifest-path device/Cargo.toml -p yoyopod-network -p yoyopod-runtime -p yoyopod-ui --locked`. Verify non-null rate override is rejected, normal empty configure stays valid, and blocked Accept is both visible and independently fenced.
- [ ] **Step 5: Commit only Task 4 paths.** `git add device/network/src/gsm_provider.rs device/network/src/lib.rs device/network/src/gsm.rs device/network/src/worker.rs device/network/Cargo.toml device/Cargo.lock device/runtime/src/runtime_loop/calls.rs device/runtime/src/runtime_loop/calls/operations.rs device/runtime/src/runtime_loop/calls/tests.rs device/ui/src/components/screens/common.rs`; `git commit -m "fix: gate GSM audio on qualified current provider evidence"`.

### Task 5: Order outgoing Create/format/prepare/Start and retain uncertain ownership

**Files/ownership:** Task 5 row, serial after Task 4. Retain `GsmBackend::dial_session(&SessionKey, &str) -> Result<()>` and typed worker protocol. No runtime admission-policy change.

**Interfaces:** Add internal `OutgoingStage::{Creating, CreatedUnstarted { path: String }, StartDispatched { path: String }}` bound to its canonical `SessionKey`; retain existing `uncertain_create`. `delete_created_unstarted(&mut self, key: &SessionKey) -> Result<()>` requires same-owner exact registered UNKNOWN and no Start dispatch. Existing `targeted_hangup`, `object_deleted`, `reconcile_paths`, `release_audio` and `finish_terminal` must respect sticky Start uncertainty. Consumes: Task 4 `VerifiedPcm`, live provider epoch and existing `GsmWorker`/keyed data contracts. Produces: exact ordered native effects, proven unstarted deletion and sticky uncertain cleanup without changing worker protocol.

The minimal private adapter in `gsm_pcm.rs` makes actual orchestration testable without constructing fake serial-backed `PreparedUsbPcm` values:

```rust
pub(crate) trait PcmEngine: Send {
    fn available(&self) -> bool;
    fn prepare(&self, format: &VerifiedPcm) -> anyhow::Result<Box<dyn PreparedPcm>>;
}
pub(crate) trait PreparedPcm: Send {
    fn port(&self) -> &std::path::Path;
    fn start(self: Box<Self>) -> anyhow::Result<Box<dyn ActivePcm>>;
}
pub(crate) trait ActivePcm: Send {
    fn set_mute(&self, muted: bool);
    fn healthy(&mut self) -> anyhow::Result<bool>;
}
```

`PcmAdapter` stores `Box<dyn PcmEngine>` and defaults only to `RealPcmEngine`. `RealPcmEngine::prepare` wraps current `UsbPcmAudio::prepare(format.sample_rate_hz())`; its `PreparedPcm` implementation exposes the actual canonical `port` and consumes the prepared value through `UsbPcmAudio::start`. `ActivePcm` delegates current health/mute methods and Drop's relay joins/reaping. Backend fields become `Option<Box<dyn PreparedPcm>>` / `Option<Box<dyn ActivePcm>>`. Test engines return their own fake prepared/active trait objects that record effects and block on controlled channels; production audio code/relay/endpoint ownership is unchanged. No test engine is selected through runtime configuration.

- [ ] **Step 1: Write private-bus/action-order tests.** Extend the existing `PrivateBus` fixture in `gsm.rs` with Create returning a real exported mock UNKNOWN, fixed metadata, Start/Hangup/Delete counters and controllable method/property replies. Use actual `dial_session`/cleanup helpers, not a second state machine. Record trace entries `create`, `format`, `prepare`, `start`, `delete`, `pcm_join`, `ended`:

Test-only `OutgoingFixture::new_qualified() -> Self` owns the real backend/retained `PrivateBus`, injected engine and mock Voice/Call objects; `dial(&SessionKey, &str) -> Result<()>` invokes production `dial_session`, `trace() -> Vec<String>`, `native_dial_count() -> usize`, and `started_key() -> Option<SessionKey>` expose recorded effects. The success test body is:

```rust
let mut fixture = OutgoingFixture::new_qualified();
let key = SessionKey { transport: CallTransport::Gsm, generation: 9,
    call_id: "runtime-outgoing-1".into() }; // fixture config generation is 9
fixture.dial(&key, "+49123456789").unwrap(); // test bus only
assert_eq!(fixture.trace(), ["create", "format", "prepare", "start"]);
assert_eq!(fixture.native_dial_count(), 1);
assert_eq!(fixture.started_key(), Some(key.clone()));
```

Define fixture methods here around retained bus and injected audio preparation, including `hold_boundary(ControlBoundary)`, `emit_same_path_reset()`, `release_boundary()`, `join_request() -> Result<()>` and `native_accept_count() -> usize`. `ControlBoundary::{Create, Prepare, Start, Accept}` holds the actual effect/reply; reset emits the real same-owner State/metadata transition from Task 4. For each boundary, release the old result only after reenable/new format and require the old key to remain fenced: Create/Prepare dispatch no Start; already-dispatched Start/Accept never produce trusted Active/release and remain uncertain until native proof. Queue old-epoch Dial/Answer/Start intent before the held transition as well. Only a fresh key after clean idle may proceed. These pin Review Focus 2 alongside Task 4's ordered invalidation test.

Other negative cases: cancel before Create; delayed Create/owner loss; success then format/preparation failure; cancel after prepare; old admission epoch; path reuse; loss/collector barrier; pending Start timeout/error followed by UNKNOWN; DeleteCall failure; absence from a replacement owner. Require no incoming Offer for created UNKNOWN, no Start before successful prepare, no Delete after any Start dispatch, and no key/data release without matching absence/terminal proof plus PCM joins. Assert collector connection identity/subscriptions remain the same. These pin Review Focus 4.

- [ ] **Step 2: Run RED.** `cargo test --manifest-path device/Cargo.toml -p yoyopod-network --locked gsm_outgoing`; expect current prepare-before-Create ordering and UNKNOWN Hangup cleanup failures. Add worker-level data-lease assertion for each uncertain result.
- [ ] **Step 3: Implement ordered ownership.** Keep worker's reservation/epoch before backend. Set owner/stage/Create uncertainty before RPC; register returned exact path before clearing Create uncertainty. Publish Preparing for UNKNOWN. Use Task 4's current qualified format and prepare PCM with capture/playback closed; fresh control checks immediately precede setting sticky StartDispatched and targeted Start:

```rust
self.owner = Some(key.clone());
self.uncertain_create = Some(key.clone());
self.outgoing_stage = Some((key.clone(), OutgoingStage::Creating));
let path = voice.call::<_, _, OwnedObjectPath>("CreateCall", &(properties,))?;
self.registry.as_mut().context("Not configured")?.register_outgoing(key, path.as_str())?;
self.outgoing_stage = Some((key.clone(), OutgoingStage::CreatedUnstarted { path: path.to_string() }));
self.uncertain_create = None; // path/key now bound; validation failures still own the object
```

Completion must also validate retained owner/modem **and provider-lifetime** epoch, created identity and cancellation; drain the ordered lifecycle barrier after Create/format/prepare and immediately before Start, then again before publishing the Start result. The snippet is the ordering core, not permission to omit those checks. Error from dispatched Create must retain `uncertain_create`/key/data until existing trusted reconciliation, with no retry or borrowed path. On never-started UNKNOWN failure, delete only its exact object through retained-owner Voice proxy, record deletion uncertainty and wait for same-owner absence and joined local PCM before Ended/data release. No Hangup of UNKNOWN. If Start is pending/dispatched, method failure/state uncertainty/path reuse/owner loss keeps Ending/quarantine. Even a later UNKNOWN or CallDeleted cannot downgrade a potentially started session into unstarted deletion; require trusted targeted EndCall/native terminal/recovery proof. Preserve `CleanupEvidence` failure fences and never use a new owner's empty Calls list as old release proof.

For incoming, keep fresh Ringing format→prepare→fenced Accept. For outgoing, Task 4's qualified idle baseline may initiate Create without per-Call metadata, but every Start requires the created object's current proof; test that distinction directly. For either direction, Active is required before capture/playback; actual compatible AUDIO port may arrive later within eight seconds. Channel failure/metadata loss performs targeted cleanup while preserving data and foreground ownership until release proof. Do not stop/rebind the retained native signal collector for a normal call end.

- [ ] **Step 4: Run GREEN.** `cargo test --manifest-path device/Cargo.toml -p yoyopod-network --locked gsm_outgoing`; run all affected network tests plus existing owner/reconnect/key/data handoff/audio-helper tests on Linux. `cargo test --manifest-path device/Cargo.toml -p yoyopod-runtime --locked call_manager`; `cargo check --manifest-path device/Cargo.toml -p yoyopod-network -p yoyopod-runtime -p yoyopod-protocol --locked`. Confirm unknown caller/mode/busy effects remain unchanged using existing manager tests.
- [ ] **Step 5: Commit scoped source.** `git add device/network/src/gsm_pcm.rs device/network/src/lib.rs device/network/src/gsm.rs device/network/src/gsm_calls.rs device/network/src/worker.rs`; `git commit -m "fix: prepare owned GSM calls before targeted native control"`.

### Task 6: Bind provider and nine Rust binaries in one exact-SHA artifact

**Files/ownership:** Task 6 row. Keep job name/artifact selector and nine binary paths; do not enable disabled slot/release jobs.

**Interfaces:** `build/bundle.sh --repo-sha SHA --ci-run-id RUN --provider DIR --rust-root DIR --out TAR` verifies provider schema/hashes, includes `providers/modemmanager/` and writes artifact `manifest.json`. Consumers receive exactly one tar and manifest; runtime receives compact expected provider manifest via compile-time environment before Cargo build.

Consumes: Task 3 complete provider output and current nine built binaries. Produces: one verified exact-SHA tar, root/provider manifest digests and the compile-time JSON expected by Task 4. `tests/test-bundle.sh PROVIDER_DIR` consumes a genuine valid Task 3 output; copies are mutated only inside its temporary fixture directory.

- [ ] **Step 1: Write failing actual-bundle tests.** Copy a Task 3 provider output built from the current checkout SHA, create dummy nine-binary files whose hashes are calculated from real bytes, invoke bundler, untar into a temporary directory and verify all nine paths and provider/source/reports. An actual mismatch test is:

```bash
set -euo pipefail
fixture=$(mktemp -d)
trap 'rm -rf -- "$fixture"' EXIT
cp -a -- "$1" "$fixture/provider"
repo_sha=$(git rev-parse HEAD)
ci_run_id=$(jq -er .ci_run_id "$fixture/provider/manifest.json")
for entry in runtime:yoyopod-runtime ui:yoyopod-ui-host cloud:yoyopod-cloud-host \
  media:yoyopod-media-host voip:yoyopod-voip-host network:yoyopod-network-host \
  on-pi:yoyopod-on-pi power:yoyopod-power-host speech:yoyopod-speech-host; do
  directory=${entry%%:*}; binary=${entry#*:}
  mkdir -p "$fixture/rust/device/$directory/build"
  printf 'synthetic test binary %s\n' "$binary" > "$fixture/rust/device/$directory/build/$binary"
done
jq '.repo_sha = "0000000000000000000000000000000000000000"' \
  "$fixture/provider/manifest.json" > "$fixture/provider/manifest.mutated"
mv -- "$fixture/provider/manifest.mutated" "$fixture/provider/manifest.json"
if bash deploy/providers/modemmanager/build/bundle.sh --repo-sha "$repo_sha" \
  --ci-run-id "$ci_run_id" --provider "$fixture/provider" \
  --rust-root "$fixture/rust" --out "$fixture/bad.tar.gz"; then
  echo 'accepted mismatching provider SHA' >&2; exit 1
fi
```

Parameterize other mutations: run ID, missing license/source, daemon hash, traversal/symlink file and one Rust binary byte after manifest generation. A separate checkout/SHA mismatch must fail before build/upload. Never rewrite production provenance to make a valid fixture pass.
- [ ] **Step 2: Run RED.** `bash deploy/providers/modemmanager/tests/test-bundle.sh .artifacts/provider`; expected missing bundler/manifest and current `tar ... device` omission, followed by behavioral mutation failures when wired.
- [ ] **Step 3: Implement CI sequencing and bundle verification.** Checkout `ref: ${{ github.event.pull_request.head.sha || github.sha }}` and assert `git rev-parse HEAD` equals `RUST_ARTIFACT_SHA`. Before Rust compilation, run Task 3's Debian container builds/tests/reproducibility comparison and verify output. Pass compact JSON to both check/build invocations:

```bash
test "$(git rev-parse HEAD)" = "$RUST_ARTIFACT_SHA"
printf 'YOYOPOD_MM_BUILD_MANIFEST=%s\n' "$(jq -c . .artifacts/provider/manifest.json)" >> "$GITHUB_ENV"
```

Then run the existing nine-package native Rust build unchanged in responsibility. Bundler hashes actual outputs and creates a tar containing `device`, `providers`, `manifest.json`; provider manifest's SHA/run match the top manifest. Every listed file must be a regular in-tree file; verify before upload. Source/licenses/buildinfo/changes/tests travel with binaries. Missing provider bundle blocks an explicit provider maintenance deployment; legacy/reconnect-only artifacts remain usable for ordinary deployment without provider mutation.
- [ ] **Step 4: Run GREEN.** `bash deploy/providers/modemmanager/tests/test-bundle.sh .artifacts/provider`; local exact-SHA bundle verification on ARM; after commit/push, coordinator dispatches `gh workflow run ci.yml --ref codex/call-manager` and checks the exact run SHA/artifact. No PR is created. CI is not a hardware audio pass.
- [ ] **Step 5: Commit owned CI/bundle files.** `git add .github/workflows/ci.yml deploy/providers/modemmanager/build/bundle.sh deploy/providers/modemmanager/tests/test-bundle.sh`; `git commit -m "build: bind GSM provider to exact Rust device artifact"`.

### Task 7: Explicit dev maintenance, complete staging and exact rollback

**Files/ownership:** Task 7 row. Preserve existing `deploy::run` clean/pushed/exact-CI behavior and `ops::build_startup_verification`; no new grant or implicit lane switch. Add CLI direct `sha2 = "=0.10.9"` only through reviewed Cargo resolution/lock update if needed to hash downloaded files.

**Interfaces:** `DeployArgs.install_provider: Option<ProviderKind>` with clap `ValueEnum` in `cli.rs` containing only `Modemmanager`. `provider.rs` exposes `verify_bundle(path: &Path, sha: &str, run: &str) -> Result<VerifiedBundle>`, `stage_provider(ctx: &TargetContext, bundle: &VerifiedBundle) -> Result<StagedProvider>`, and `apply_provider(ctx: &TargetContext, staged: &StagedProvider, lane: &LanePaths, pi: &PiPaths) -> Result<ProviderInstallOutcome>`. Import existing `crate::paths::{LanePaths, PiPaths}`; `VerifiedBundle`/`StagedProvider` fields are private. `ProviderInstallOutcome::{QualifiedReady, InstalledQualificationPending}` distinguishes identity/eligibility health from full functional acceptance; neither variant is an audio success claim.

Consumes: Task 6 tar/digests, current exact-SHA selector and existing `TargetContext`/SSH/lane/restart contracts. Produces: verified staged closure, durable phase/outcome receipt, exact committed Rust/provider installation or coherent rollback. Ordinary deploy consumes legacy/reconnect artifacts without provider mutation.

`deploy/transaction.sh STAGE_DIR DEV_SERVICE PROD_SERVICE` is one SSH execution under a single `flock`, with root-owned validated stage and durable phase journal. It defines separate effect functions `verify_stage(stage)`, `require_dev_no_calls(dev, prod)`, `capture_prior(stage)`, `stop_native(dev)`, `stop_provider()`, `install_candidate(stage)`, `start_provider()`, `verify_provider_init(stage)`, `start_native(dev)`, `verify_native_expected(stage)`, `restore_prior_packages(stage)`, `restore_prior_service(stage)`, `restore_prior_rust(stage)`, and `write_recovery_record(stage)`. Effects return exit statuses; pending is successful native health plus a distinct outcome JSON. Production functions use fixed package/systemd/probe argv; shell tests source real orchestration and override only effects. Entry executes only under `[[ ${BASH_SOURCE[0]} == "$0" ]]`; no test bypass is exposed in CLI/target policy.

- [ ] **Step 1: Write failing CLI/transaction tests.** Actual clap parsing accepts only `--install-provider modemmanager`; omitted option yields no apt/dpkg/ModemManager restart. Build temp artifact fixtures to reject hashes/SHA/run/path mismatch. Source real transaction functions with fault-injected effect wrappers and verify staging→no-calls→stop→install→new owner/init→Rust order. Test partial install plus failed rollback:

```bash
set -euo pipefail
stage=$(mktemp -d)
trap 'rm -rf -- "$stage"' EXIT
trace="$stage/trace"
: > "$trace"
source deploy/transaction.sh
install_candidate() { printf 'install-partial\n' >> "$trace"; return 1; }
restore_prior_packages() { printf 'rollback-failed\n' >> "$trace"; return 1; }
start_native() { printf 'unexpected-native-start\n' >> "$trace"; return 99; }
if provider_main "$stage" yoyopod-dev.service yoyopod-prod.service; then exit 1; fi
if grep -q unexpected-native-start "$trace"; then exit 1; fi
test -s "$stage/recovery.json"
```

Define `provider_main` in this task around those effects. Complete fixtures override other effects with recorded successful state and actual temp stage/receipts; retain production `write_recovery_record` so its JSON is verified. Fault every install/init/identity/selection/startup stage and interruption phase. Require no service stop when staging fails, no maintenance with any live Call, inactive/conflicting lane or unmanaged owner, and no new-owner empty-list shortcut. Pending qualification with valid install/init returns a distinct successful install outcome while Start/Accept remain closed; it does not roll back. These pin Review Focus 3 and 5.

- [ ] **Step 2: Run RED.** `cargo test --manifest-path cli/Cargo.toml provider`; `bash deploy/providers/modemmanager/tests/test-transaction.sh`. Expect missing opt-in/outcome and current ordinary-deploy provider mutation failures.
- [ ] **Step 3: Implement preflight and complete offline staging.** Verify tar manifest locally before extraction/upload; validate remote Debian trixie/ARM64, candidate identity, exact package dependency simulation, package-manager health/no competing transaction, dev ownership, inactive prod, no unmanaged owners and no nonterminated Calls on any managed modem. Stage candidate and exact prior closure bytes/hashes plus prior service/config/udev/receipt/Rust artifact identities. Record installed status and candidate-added packages so rollback removes additions as well as restoring prior versions/files. Resolve prior versions from signed package sources/cached exact `.deb` files; never assume apt can later download the rollback version. Simulate forward dependency selection and rollback from its predicted candidate status using `apt-get -s --no-download -o Dir::State::status="$stage/simulated-candidate-status"` with staged exact packages; refuse if closure is unavailable or simulation changes unrelated packages. The temporary status file is generated from current dpkg status and exact staged control records. Use root-owned stage under `/var/lib/yoyopod/providers/modemmanager/transactions/<sha>/` and preserve it on failure. Read-only running-identity access under the effective Rust service account must pass before stop, without new privileges.

Replace ordinary `modem_manager_prerequisites_command` behavior with read-only readiness/rule checks; missing daemon or required udev migration reports explicit maintenance prerequisite, without installing/restarting. Explicit provider maintenance can apply the unchanged existing rule if required, inside the reviewed no-call transaction. Existing Wi-Fi/BlueZ behavior/grants are not expanded by this task.

- [ ] **Step 4: Implement one locked transaction and rollback.** Journal durable phases; stop dev/native owner and verify exit, recheck no Calls, stop one normal provider, install offline closure, then start one normal provider and require new unique owner/fresh initialization/fixed ACK/readback. Within existing privileged maintenance execution, hash actual `/proc/<new-pid>/exe`, fixed executable and package, collect bus ID/owner/PID/start ticks twice around the reads, and atomically write the protected receipt only if they agree with the manifest. Verify current-owner/PID init completion through Task 3's normal-level result, not debug mode or invented VoiceAvailable. Suppress/control package-triggered early starts and restore temporary policy exactly. Start exact-SHA Rust and verify normal-account receipt/current-identity reads plus expected eligibility state.

```bash
provider_main() {
  verify_stage "$1" && require_dev_no_calls "$2" "$3" && capture_prior "$1" || return 1
  stop_native "$2" && stop_provider && install_candidate "$1" && start_provider \
    && verify_provider_init "$1" && start_native "$2" && verify_native_expected "$1" \
    && return 0
  stop_native "$2" && stop_provider || { write_recovery_record "$1"; return 2; }
  restore_prior_packages "$1" && restore_prior_service "$1" \
    && restore_prior_rust "$1" && return 1
  stop_native "$2" || true
  stop_provider || true
  write_recovery_record "$1" # defined here: preserve identities/phase and keep native stopped
  return 2
}
```

Wrap this flow in `flock` and traps for interruption; recheck captured package/service/call state under that lock before stop. If native/provider stop cannot be proved, write recovery state and do not mutate packages beneath a live unknown owner. Install/restore staged files through apt's offline transaction with validated quoted arrays. `write_recovery_record` preserves identities and stop failures using quoted paths/jq. Restore captured closure/config/udev/service/receipt with downgrade permission limited to it, remove candidate-added packages, then maintenance-reattest the new prior owner/process against its prior expected hashes before prior Rust resumes. Stock prior provider uses prior normal health, not patched PCM readiness, and remains audio ineligible. Pending qualification alone succeeds; genuine install/identity/init/selection/owner failure rolls back. Failed rollback attempts stop both services and verifies stopped state; inability to prove stop is reported as recovery required, never a false stopped/clean claim. Document the canonical explicit reattestation requirement after an unexpected provider restart as the cost of retaining the current privilege boundary.

- [ ] **Step 5: Run GREEN.** CLI parser/manifest tests and `tests/test-transaction.sh`, including interruption/partial install/failed rollback. `cargo test --manifest-path cli/Cargo.toml --locked`; `cargo check --manifest-path cli/Cargo.toml --workspace --locked`; `cargo fmt --manifest-path cli/Cargo.toml --all --check`. Inspect dry-run output only after normal committed-code checks; no Pi mutation as a test shortcut.
- [ ] **Step 6: Commit scoped CLI/deployment files.** `git add cli/yoyopod/src/cli.rs cli/yoyopod/src/commands/target/mod.rs cli/yoyopod/src/commands/target/deploy.rs cli/yoyopod/src/commands/target/provider.rs cli/yoyopod/Cargo.toml cli/Cargo.lock cli/README.md docs/operations/DEV_PROD_LANES.md deploy/providers/modemmanager/deploy/transaction.sh deploy/providers/modemmanager/tests/test-transaction.sh`; `git commit -m "feat: explicitly maintain pinned GSM provider on dev lane"`.

### Task 8: Qualify framing/reset evidence, then validate both GSM directions

**Files/ownership:** Task 8 row. Coordinator owns every Pi operation; user owns phone calls. No automatic dialing, contact messaging, manual provider bypass, arbitrary AT/debug grant, or build on Pi.

**Interfaces:** `qualification/evidence.md` records actual source/firmware/package identity, source/patch/manifest hashes, applicable framing evidence, reset observations, commands/results and final incoming/outgoing functional results. `profile.json` transitions to `qualified` only after reviewed framing and reset/lifecycle proof, with evidence path/hash; first/second-call functional success is a subsequent final feature gate.

Consumes: Task 3 exact provider bytes, Task 6 exact artifact and Task 7 explicit maintenance contract. Produces: reviewed qualified profile only when real framing/lifecycle evidence passes, followed by factual functional acceptance or a named blocked gate. At the start of implementation, before package maintenance, review framing feasibility and record the result: current references do not establish applicable complete framing. Software/build tests can proceed fail-closed, but this plan does not schedule installation solely to pursue an unavailable non-call PCM experiment. Candidate maintenance waits for an applicable vendor framing record or a separately user-reviewed written-spec amendment defining the needed qualification experiment.

- [ ] **Step 1: Prove qualification gate behavior in tests before installing.** Task 4's present-dictionary/pending tests and Task 7's installed-pending transaction case must pass. Add a profile fixture with one framing or reset proof omitted and require rejection. Use exact identity/hash comparisons, not a boolean changed by an operator without evidence.
- [ ] **Step 2: Finish scoped off-Pi verification and obtain exact CI.** Run device/CLI formatting, affected network/runtime/protocol checks/tests and provider suites/reproducibility from earlier tasks. Run one whole-branch source/security review focused on provider/state/ownership/installer changes, as required by Subagent-driven execution. No unchanged UI/navigation soak rerun is implied. Current Windows seat cannot execute Linux private-bus/native tests; use coordinator-managed Linux build environment and exact ARM CI. Existing native UI serial baseline and protocol strict-warning limitations were not independently reviewed by this plan; do not claim a new global pass or suppress unrelated warnings.
- [ ] **Step 3: Install candidate only within reviewed maintenance scope and feasible qualification.** Coordinator commits/pushes reviewed changes, dispatches exact CI and checks the complete bundle. After the framing-feasibility gate above and with reviewed maintenance scope, use `yoyopod target mode status`, then `yoyopod target deploy --branch codex/call-manager --sha "$sha" --install-provider modemmanager --wait-for-ci`. Stage/validate before stop; `installed, qualification pending` is expected while current readback/reset proof is incomplete. Verify Start/Accept closed, reason visible, native discovery/ordinary rejection correct, normal provider and one owner. No provider installation is implied while the framing gate has no reviewed path.
- [ ] **Step 4: Gather bounded evidence without bypassing the gate.** Read existing fixed selection/readback completion records and current owner/modem/Call properties. A user-controlled incoming offer can be inspected and rejected without Accept; record first Ringing dictionary/empty port. In no-call state, the coordinator runs only the reviewed provider lifecycle procedure (normal disable/re-enable and an observed reprobe/reset), recording same-path/same-owner invalidation, new selection/readback and old callback/key rejection. If a supported physical reset is invisible to the provider/runtime, stop qualification and leave pending; do not invent an observer.

For framing, obtain an applicable SIMCom record covering this model/firmware and raw USB stream: signed two's-complement 16-bit little-endian samples, one channel, no interleaved/header framing and the selector's 16000 Hz meaning. Record revision/hash/pages and applicability assessment. The rendered [SIMCom USB AUDIO Note V1.03](https://files.waveshare.com/upload/8/8e/SIM7100_SIM7500_SIM7600_Series_USB_AUDIO_Application_Note_V1.03.pdf), SHA256 `06eb5deda7cd2e815b1ef5c716faa2cccaee4b35b93f5f247c31a6553f2f2917`, shows call-dependent raw PCM exchange (pages 6–8) and command/port selection (pages 8–9); page 3 lists older module scope. It does not establish complete framing/applicability for `LE20B04SIM7600G22`. Its Intel entry is a separate COM device, not a PCM encoding setting. The [AT Manual V3.00, page 161](https://files.waveshare.com/wiki/SIM7600G-H/SIM7500_SIM7600_Series_AT_Command_Manual_V3.00.pdf#page=161) establishes selector/readback/nonpersistence, not complete framing. Historical working outbound calls and third-party code do not qualify this exact profile.

**Current concrete blocker:** no applicable complete framing record or authorized experiment has been established. The documented raw stream requires native call control, which this profile gate currently forbids. Therefore no non-call PCM measurement is prescribed. If no applicable vendor record becomes available, stop Task 8 before maintenance/qualification transition and report that GSM audio cannot be accepted under the current scope. A controlled single-owner native-call experiment would require a written-spec amendment and explicit user review before implementation or execution; this plan grants no such exception, public API, AT/debug bypass or static-rate path. Pending installation, if already explicitly performed under a reviewed feasible qualification scope, remains pending rather than falsely failing health or becoming qualified.

- [ ] **Step 5: Commit reviewed qualification, rebuild exact profile artifact.** Only after actual framing and reset proof passes, update `profile.json`/evidence hashes and run gate tests. `git add deploy/providers/modemmanager/profile.json deploy/providers/modemmanager/qualification/evidence.md deploy/providers/modemmanager/README.md`; `git commit -m "test: qualify pinned GSM provider framing and lifecycle"`. Rebuild through exact CI; carry evidence only if locked source/patch/package bytes and modem/firmware match. Changed provider bytes require a new revision/qualification and explicit maintenance again. Deploy the final exact Rust/profile artifact normally if provider bytes are already identical; normal deploy changes no provider.
- [ ] **Step 6: User-controlled functional acceptance.** Record fresh init → first saved-contact incoming Ringing format → physical-button targeted Accept → native Active and actual AUDIO port → intelligible audio both ways → native-ID EndCall/resource/data cleanup → second incoming call with format/empty port before Accept. Then user starts an outgoing call: owned Create UNKNOWN must not ring remotely; format/prepare/fresh gates precede targeted Start; Active port/audio/targeted end must pass. Exercise outgoing cancellation/preparation failure without remote Dial, uncertain Start/loss cleanup, observed reconnect with no dirty release, and unsupported/mismatched profile fixtures. Preserve original known/unknown/mode/busy/media behavior; no automatic music restart.
- [ ] **Step 7: Record final provenance/results, not a CI-only audio claim.** Include final full SHA/CI run/artifact, provider sub-bundle digest, exact closure/daemon hashes/source/patch/profile/modem revisions, actual command exit statuses, owner/call identity ordering, human audio observations and cleanup/reconnect results. Redact personal identifiers/secrets. Base `yoyopod target validate --sha "$sha"` can prove deployment/smoke/stability; VoIP/cloud-voice stubs are not audio acceptance. If any hardware gate remains unmet, report the exact pending gate and current installed state, retain fail-closed policy, and do not mark feature complete.

## Self-review and handoff

Coverage: provider lifetimes/callbacks/constructor/updater/port release → Tasks 2–3; fixed live selection and private-bus/mock-AT tests → Task 3; profile/firmware/package/current metadata, same-path reset/upgrade and normal-account receipt proof → Task 4; minimal incoming Accept projection/action guard/reason and correlated failure visibility → Task 4; both directions/UNKNOWN deletion/sticky Start/data ownership/retained collector → Task 5; signed locked Debian build, source/licenses/reproducibility → Tasks 1/3; same-SHA nine-binary artifact → Task 6; opt-in/no-call/dev staging/attestation/partial rollback/pending outcome → Task 7; evidence feasibility before maintenance, actual proof then user-controlled final calls → Task 8.

The five Review Focus inputs each have explicit negative tests in their owning tasks. Token/helper/type/JSON names are shared above; no package/image/dependency signature or framing proof is invented. Remaining real evidence is deliberately gated: signed lock resolution, exact firmware framing/readback/reset observations, matching clean builds and incoming/outgoing hardware results.

After the coordinator saves/commits this plan, the user reviews the written plan before any provider task begins. Preserve Subagent-driven execution and its per-task fresh review gates. This plan does not repeat authorization for the already-approved reconnect-only deployment, which keeps the stock provider unchanged.
