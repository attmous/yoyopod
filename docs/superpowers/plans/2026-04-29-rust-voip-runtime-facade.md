# Rust VoIP Runtime Facade Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Rust VoIP host the canonical owner for live VoIP runtime state while Python remains the app supervisor, persistence mirror, UI bridge, and music coordination bridge.

**Architecture:** The Rust worker already owns liblinphone and emits `voip.snapshot` events. This slice promotes those snapshots into the app-facing state source: Python parses typed Rust snapshots, mirrors them into `VoIPManager`, and keeps existing Python services as compatibility/persistence adapters. Commands still flow through the existing `VoIPBackend` facade so current UI and voice command surfaces do not change.

**Tech Stack:** Rust 2021 workspace under `src/`, Python 3.12, NDJSON worker protocol, pytest, Cargo tests, GitHub Actions ARM64 artifacts, Raspberry Pi Zero 2W.

---

## Scope

This is one PR after the hardware validation of `9eab168b88a9ffe964d4738ad3ba854846161d98`.

In scope:

- Typed Rust VoIP runtime snapshot model on the Python side.
- `RustHostBackend` stores the latest Rust-owned snapshot.
- `RustHostBackend` dispatches a snapshot event when Rust emits `voip.snapshot`.
- `VoIPManager` mirrors registration, call, lifecycle, active peer, active call id, active voice-note state, and last message facts from the Rust snapshot.
- Python message store and call history remain persistence mirrors.
- Existing Python UI/runtime consumers keep using `VoIPManager`.

Out of scope:

- Moving app bus, scheduler, UI host, music interruption policy, contacts directory, config loading, or file persistence to Rust.
- Removing the Python sidecar or in-process Liblinphone fallback.
- Replacing the C liblinphone shim with direct Rust bindings.

## Task 1: Add Typed Runtime Snapshot Models

**Files:**
- Modify: `yoyopod/integrations/call/models.py`
- Test: `tests/backends/test_rust_host_voip.py`

- [x] Add frozen dataclasses for `VoIPLifecycleSnapshot`, `VoIPVoiceNoteSnapshot`, `VoIPMessageSnapshot`, `VoIPRuntimeSnapshot`, and `VoIPRuntimeSnapshotChanged`.
- [x] Keep enum conversion strict at the adapter edge, not inside the dataclasses.
- [x] Add tests proving a Rust `voip.snapshot` payload becomes a typed snapshot event.

## Task 2: Promote Rust Snapshots in `RustHostBackend`

**Files:**
- Modify: `yoyopod/backends/voip/rust_host.py`
- Test: `tests/backends/test_rust_host_voip.py`

- [x] Store the latest typed snapshot on every `voip.snapshot`.
- [x] Expose `get_runtime_snapshot() -> VoIPRuntimeSnapshot | None`.
- [x] Dispatch `VoIPRuntimeSnapshotChanged` after the existing deduplicated registration/call updates.
- [x] Preserve existing `RegistrationStateChanged` and `CallStateChanged` events for compatibility.
- [x] Treat malformed snapshot enum fields as safe defaults instead of crashing the worker bridge.

## Task 3: Mirror Rust-Owned State in `VoIPManager`

**Files:**
- Modify: `yoyopod/integrations/call/manager.py`
- Test: `tests/backends/test_voip_backend.py`

- [x] Handle `VoIPRuntimeSnapshotChanged`.
- [x] Mirror `running`, `registered`, `registration_state`, `call_state`, `current_call_id`, and `caller_address`.
- [x] Continue using `_update_registration_state()` and `_update_call_state()` where callbacks are expected.
- [x] Avoid duplicate callback emissions when individual events and snapshots report the same state.
- [x] Keep `CallRuntime` and music interruption behavior driven by current callbacks for this PR.

## Task 4: Mirror Rust Voice-Note Runtime Facts

**Files:**
- Modify: `yoyopod/integrations/call/voice_notes.py`
- Test: `tests/integrations/test_voip_services.py`

- [x] Add an `apply_runtime_snapshot()` method that updates an active draft from Rust voice-note state.
- [x] Preserve existing Python-created draft metadata: recipient, display name, local file, and send timeout.
- [x] Map Rust `recording`, `recorded`, `sending`, `sent`, `failed`, and `idle` to existing UI-facing `send_state` values.
- [x] Do not delete local files just because Rust reports `idle`; only explicit discard/cancel deletes.

## Task 5: Mirror Rust Last-Message Facts Without Taking Over Persistence

**Files:**
- Modify: `yoyopod/integrations/call/messaging.py`
- Test: `tests/integrations/test_voip_services.py`

- [x] Add an `apply_runtime_snapshot()` method for `last_message`.
- [x] Use it to update known records when Rust reports a delivery state or local file path.
- [x] Do not create incomplete records without peer/kind/direction; wait for normal message events for that.
- [x] Notify summary callbacks only when mirrored persistence changes.

## Task 6: Rust Snapshot Contract Coverage

**Files:**
- Modify: `src/crates/voip-host/src/host.rs`
- Modify: `src/crates/voip-host/src/main.rs`
- Test: Rust unit tests under `src/crates/voip-host/src/`

- [x] Ensure `voip.snapshot` includes lifecycle, call, voice-note, pending outbound message, and last-message facts after relevant commands/events.
- [x] Keep the schema compatible with existing merged fields.
- [x] Add tests for voice-note and message snapshot updates after worker command paths.

Note: the Rust host implementation and tests already satisfied this task in the merged baseline; this slice verified them with the workspace Cargo test suite and added the Python adapter/manager coverage.

## Task 7: Verification and PR Prep

**Files:**
- Modify docs only if the runtime contract changes beyond current docs.

- [x] Run focused Python tests after each task.
- [x] Run `cargo fmt --manifest-path src/Cargo.toml --all --check`.
- [x] Run `cargo test --manifest-path src/Cargo.toml --workspace --locked`.
- [x] Run `uv run python scripts/quality.py gate`.
- [x] Run `uv run pytest -q`.
- [ ] Commit and push once the full gate passes.
- [ ] Open a single PR with commits grouped by snapshot model, Python bridge, Rust contract, and tests.
