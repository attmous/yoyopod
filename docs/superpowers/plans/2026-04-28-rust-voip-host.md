# Rust VoIP Host Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a calls-only Rust VoIP Host that owns liblinphone backend execution while Python keeps `VoIPManager`, `CallRuntime`, call/music coordination, contacts, history, and UI state.

**Architecture:** The Rust VoIP Host is a supervised worker process that speaks the same NDJSON envelope style as the existing worker runtime. Python adds a `RustHostBackend` implementing the current `VoIPBackend` protocol, translates Python calls into worker commands, and translates worker events back into existing `VoIPEvent` dataclasses. Rust initially binds the existing C liblinphone shim through `libloading` instead of binding liblinphone directly.

**Tech Stack:** Rust 2021 workspace under `src/`, `serde`, `serde_json`, `libloading`, `thiserror`, `anyhow`, Python 3.12, existing `WorkerSupervisor`, pytest, GitHub Actions ARM64 runner, Raspberry Pi Zero 2W.

---

## Scope Check

This plan implements the first Rust VoIP slice only:

- Rust host skeleton and worker protocol.
- Rust liblinphone shim wrapper.
- Rust call registration/control/event flow.
- Python `RustHostBackend` adapter.
- Opt-in runtime selection.
- CI artifact and hardware validation path.

This plan does not implement text messages, voice notes, contacts, call history, UI screens, `VoIPManager` in Rust, or direct liblinphone Rust bindings.

## Required Execution Rules

- New production Rust sources go under top-level `src/`.
- Do not add `src/rust/`.
- Do not build Rust binaries on the Raspberry Pi Zero 2W.
- Pi validation uses the GitHub Actions artifact for the exact commit.
- Before every commit and every push run:

```bash
uv run python scripts/quality.py gate
uv run pytest -q
```

- For Rust changes also run:

```bash
cargo fmt --manifest-path src/Cargo.toml
cargo test --manifest-path src/Cargo.toml --workspace --locked
```

## File Structure

- Modify: `src/Cargo.toml` - add `crates/voip-host`.
- Create: `src/crates/voip-host/Cargo.toml` - Rust VoIP Host crate manifest.
- Create: `src/crates/voip-host/src/main.rs` - process entrypoint and stdin/stdout loop.
- Create: `src/crates/voip-host/src/protocol.rs` - worker envelope, commands, events.
- Create: `src/crates/voip-host/src/config.rs` - Rust config shape matching Python `VoIPConfig`.
- Create: `src/crates/voip-host/src/shim.rs` - dynamic binding to `libyoyopod_liblinphone_shim.so`.
- Create: `src/crates/voip-host/src/events.rs` - native numeric event mapping.
- Create: `src/crates/voip-host/src/host.rs` - command handling, host state, iterate cadence.
- Create: `yoyopod/backends/voip/rust_host.py` - Python `VoIPBackend` adapter over `WorkerSupervisor`.
- Create: `tests/backends/test_rust_host_voip.py` - Python adapter tests.
- Modify: `yoyopod/core/bootstrap/managers_boot.py` - choose Rust host backend by env flag.
- Test: `tests/core/test_bootstrap.py` - backend selection and flag conflict.
- Modify: `.github/workflows/ci.yml` - build/upload `yoyopod-voip-host-<sha>`.
- Modify: `docs/hardware/DEPLOYED_PI_DEPENDENCIES.md` or `docs/RUST_UI_HOST.md` only if needed to mention the new artifact.

## Task 1: Add Rust VoIP Host Crate Skeleton

**Files:**
- Modify: `src/Cargo.toml`
- Create: `src/crates/voip-host/Cargo.toml`
- Create: `src/crates/voip-host/src/main.rs`
- Create: `src/crates/voip-host/src/protocol.rs`

- [ ] **Step 1: Write failing protocol tests**

Create `src/crates/voip-host/src/protocol.rs`:

```rust
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use thiserror::Error;

pub const SUPPORTED_SCHEMA_VERSION: u16 = 1;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum EnvelopeKind {
    Command,
    Event,
    Result,
    Error,
    Heartbeat,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct WorkerEnvelope {
    #[serde(default = "default_schema_version")]
    pub schema_version: u16,
    pub kind: EnvelopeKind,
    #[serde(rename = "type")]
    pub message_type: String,
    #[serde(default)]
    pub request_id: Option<String>,
    #[serde(default)]
    pub timestamp_ms: u64,
    #[serde(default)]
    pub deadline_ms: u64,
    #[serde(default = "empty_payload")]
    pub payload: Value,
}

#[derive(Debug, Error)]
pub enum ProtocolError {
    #[error("invalid JSON worker envelope: {0}")]
    InvalidJson(#[from] serde_json::Error),
    #[error("unsupported schema_version {actual}; expected {expected}")]
    UnsupportedSchema { actual: u16, expected: u16 },
    #[error("invalid worker envelope: {0}")]
    InvalidEnvelope(String),
}

fn default_schema_version() -> u16 {
    SUPPORTED_SCHEMA_VERSION
}

fn empty_payload() -> Value {
    json!({})
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn decode_accepts_voip_health_command() {
        let raw = br#"{"schema_version":1,"kind":"command","type":"voip.health","request_id":"r1","payload":{}}"#;

        let envelope = WorkerEnvelope::decode(raw).expect("decode");

        assert_eq!(envelope.schema_version, SUPPORTED_SCHEMA_VERSION);
        assert_eq!(envelope.kind, EnvelopeKind::Command);
        assert_eq!(envelope.message_type, "voip.health");
        assert_eq!(envelope.request_id.as_deref(), Some("r1"));
    }

    #[test]
    fn encode_ready_event_has_newline() {
        let encoded = WorkerEnvelope::event("voip.ready", json!({"capabilities":["calls"]}))
            .encode()
            .expect("encode");

        assert!(encoded.ends_with(b"\n"));
        assert!(std::str::from_utf8(&encoded).unwrap().contains("\"type\":\"voip.ready\""));
    }

    #[test]
    fn rejects_array_payload() {
        let err = WorkerEnvelope::decode(br#"{"schema_version":1,"kind":"command","type":"voip.health","payload":[]}"#)
            .expect_err("payload must be rejected");

        assert!(err.to_string().contains("payload must be an object"));
    }
}
```

Run:

```bash
cargo test --manifest-path src/Cargo.toml -p yoyopod-voip-host protocol
```

Expected: fails because the crate is not in the workspace yet.

- [ ] **Step 2: Add the crate manifest**

Append the crate to `src/Cargo.toml`:

```toml
[workspace]
resolver = "2"
members = [
    "crates/ui-host",
    "crates/voip-host",
]
```

Create `src/crates/voip-host/Cargo.toml`:

```toml
[package]
name = "yoyopod-voip-host"
version = "0.1.0"
edition = "2021"
rust-version = "1.82"

[[bin]]
name = "yoyopod-voip-host"
path = "src/main.rs"

[dependencies]
anyhow = "1.0"
clap = { version = "4.5", features = ["derive"] }
libloading = "0.8"
serde = { version = "1.0", features = ["derive"] }
serde_json = "1.0"
thiserror = "2.0"
```

- [ ] **Step 3: Implement envelope methods**

Add to `protocol.rs`:

```rust
impl WorkerEnvelope {
    pub fn decode(line: &[u8]) -> Result<Self, ProtocolError> {
        let envelope: WorkerEnvelope = serde_json::from_slice(line)?;
        envelope.validate()?;
        Ok(envelope)
    }

    pub fn encode(&self) -> Result<Vec<u8>, ProtocolError> {
        self.validate()?;
        let mut encoded = serde_json::to_vec(self)?;
        encoded.push(b'\n');
        Ok(encoded)
    }

    pub fn event(message_type: impl Into<String>, payload: Value) -> Self {
        Self {
            schema_version: SUPPORTED_SCHEMA_VERSION,
            kind: EnvelopeKind::Event,
            message_type: message_type.into(),
            request_id: None,
            timestamp_ms: 0,
            deadline_ms: 0,
            payload,
        }
    }

    pub fn result(
        message_type: impl Into<String>,
        request_id: Option<String>,
        payload: Value,
    ) -> Self {
        Self {
            schema_version: SUPPORTED_SCHEMA_VERSION,
            kind: EnvelopeKind::Result,
            message_type: message_type.into(),
            request_id,
            timestamp_ms: 0,
            deadline_ms: 0,
            payload,
        }
    }

    pub fn error(
        message_type: impl Into<String>,
        request_id: Option<String>,
        code: impl Into<String>,
        message: impl Into<String>,
    ) -> Self {
        Self {
            schema_version: SUPPORTED_SCHEMA_VERSION,
            kind: EnvelopeKind::Error,
            message_type: message_type.into(),
            request_id,
            timestamp_ms: 0,
            deadline_ms: 0,
            payload: json!({
                "code": code.into(),
                "message": message.into(),
            }),
        }
    }

    pub fn validate(&self) -> Result<(), ProtocolError> {
        if self.schema_version != SUPPORTED_SCHEMA_VERSION {
            return Err(ProtocolError::UnsupportedSchema {
                actual: self.schema_version,
                expected: SUPPORTED_SCHEMA_VERSION,
            });
        }
        if self.message_type.trim().is_empty() {
            return Err(ProtocolError::InvalidEnvelope(
                "type must be a non-empty string".to_string(),
            ));
        }
        if !self.payload.is_object() {
            return Err(ProtocolError::InvalidEnvelope(
                "payload must be an object".to_string(),
            ));
        }
        Ok(())
    }
}
```

- [ ] **Step 4: Add a minimal process entrypoint**

Create `src/crates/voip-host/src/main.rs`:

```rust
use anyhow::Result;
use clap::Parser;
use serde_json::json;
use std::io::{self, BufRead, Write};

mod protocol;

use protocol::WorkerEnvelope;

#[derive(Debug, Parser)]
#[command(name = "yoyopod-voip-host")]
#[command(about = "YoYoPod Rust VoIP host")]
struct Args {
    #[arg(long, default_value = "")]
    shim_path: String,
}

fn main() -> Result<()> {
    let _args = Args::parse();
    write_envelope(&WorkerEnvelope::event(
        "voip.ready",
        json!({"capabilities":["calls"]}),
    ))?;

    let stdin = io::stdin();
    for line in stdin.lock().lines() {
        let line = line?;
        if line.trim().is_empty() {
            continue;
        }
        let envelope = match WorkerEnvelope::decode(line.as_bytes()) {
            Ok(envelope) => envelope,
            Err(error) => {
                write_envelope(&WorkerEnvelope::error(
                    "voip.error",
                    None,
                    "protocol_error",
                    error.to_string(),
                ))?;
                continue;
            }
        };

        if envelope.message_type == "voip.health" {
            write_envelope(&WorkerEnvelope::result(
                "voip.health",
                envelope.request_id,
                json!({"ready":true,"registered":false,"active_call_id":null}),
            ))?;
        } else if envelope.message_type == "voip.shutdown" {
            break;
        } else {
            write_envelope(&WorkerEnvelope::error(
                "voip.error",
                envelope.request_id,
                "unsupported_command",
                format!("unsupported command {}", envelope.message_type),
            ))?;
        }
    }
    Ok(())
}

fn write_envelope(envelope: &WorkerEnvelope) -> Result<()> {
    let encoded = envelope.encode()?;
    let mut stdout = io::stdout().lock();
    stdout.write_all(&encoded)?;
    stdout.flush()?;
    Ok(())
}
```

- [ ] **Step 5: Run Rust tests**

Run:

```bash
cargo fmt --manifest-path src/Cargo.toml
cargo test --manifest-path src/Cargo.toml -p yoyopod-voip-host --locked
cargo test --manifest-path src/Cargo.toml --workspace --locked
```

Expected: new protocol tests pass and existing UI host tests still pass.

- [ ] **Step 6: Run repo gates and commit**

Run:

```bash
uv run python scripts/quality.py gate
uv run pytest -q
```

Commit:

```bash
git add src
git commit -m "feat(voip): add rust voip host skeleton"
```

Expected: first commit introduces a buildable `yoyopod-voip-host` with health/shutdown only.

## Task 2: Add Rust Config, Event Mapping, And Host State

**Files:**
- Create: `src/crates/voip-host/src/config.rs`
- Create: `src/crates/voip-host/src/events.rs`
- Create: `src/crates/voip-host/src/host.rs`
- Modify: `src/crates/voip-host/src/main.rs`

- [ ] **Step 1: Add config mapping tests**

Create `src/crates/voip-host/src/config.rs`:

```rust
use serde::{Deserialize, Serialize};
use serde_json::Value;
use thiserror::Error;

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct VoipConfig {
    #[serde(default = "default_sip_server")]
    pub sip_server: String,
    #[serde(default)]
    pub sip_username: String,
    #[serde(default)]
    pub sip_password: String,
    #[serde(default)]
    pub sip_password_ha1: String,
    #[serde(default)]
    pub sip_identity: String,
    #[serde(default)]
    pub factory_config_path: String,
    #[serde(default = "default_transport")]
    pub transport: String,
    #[serde(default)]
    pub stun_server: String,
    #[serde(default)]
    pub conference_factory_uri: String,
    #[serde(default)]
    pub file_transfer_server_url: String,
    #[serde(default)]
    pub lime_server_url: String,
    #[serde(default = "default_iterate_interval_ms")]
    pub iterate_interval_ms: u64,
    #[serde(default)]
    pub voice_note_store_dir: String,
    #[serde(default)]
    pub auto_download_incoming_voice_recordings: bool,
    #[serde(default = "default_audio_device")]
    pub playback_dev_id: String,
    #[serde(default = "default_audio_device")]
    pub ringer_dev_id: String,
    #[serde(default = "default_audio_device")]
    pub capture_dev_id: String,
    #[serde(default = "default_audio_device")]
    pub media_dev_id: String,
    #[serde(default = "default_mic_gain")]
    pub mic_gain: i32,
    #[serde(default = "default_output_volume")]
    pub output_volume: i32,
}

#[derive(Debug, Error)]
pub enum ConfigError {
    #[error("invalid voip config payload: {0}")]
    InvalidPayload(#[from] serde_json::Error),
    #[error("sip_identity is required for Rust VoIP host registration")]
    MissingSipIdentity,
    #[error("sip_server is required for Rust VoIP host registration")]
    MissingSipServer,
}

fn default_sip_server() -> String {
    "sip.linphone.org".to_string()
}

fn default_transport() -> String {
    "tcp".to_string()
}

fn default_iterate_interval_ms() -> u64 {
    20
}

fn default_audio_device() -> String {
    "ALSA: wm8960-soundcard".to_string()
}

fn default_mic_gain() -> i32 {
    80
}

fn default_output_volume() -> i32 {
    100
}

impl VoipConfig {
    pub fn from_payload(payload: &Value) -> Result<Self, ConfigError> {
        let config: Self = serde_json::from_value(payload.clone())?;
        config.validate()?;
        Ok(config)
    }

    pub fn validate(&self) -> Result<(), ConfigError> {
        if self.sip_server.trim().is_empty() {
            return Err(ConfigError::MissingSipServer);
        }
        if self.sip_identity.trim().is_empty() {
            return Err(ConfigError::MissingSipIdentity);
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn config_from_payload_accepts_python_voip_config_shape() {
        let payload = json!({
            "sip_server": "sip.example.com",
            "sip_username": "alice",
            "sip_password": "secret",
            "sip_identity": "sip:alice@example.com",
            "transport": "tcp",
            "iterate_interval_ms": 20,
            "playback_dev_id": "ALSA: wm8960-soundcard",
            "ringer_dev_id": "ALSA: wm8960-soundcard",
            "capture_dev_id": "ALSA: wm8960-soundcard",
            "media_dev_id": "ALSA: wm8960-soundcard",
            "mic_gain": 80,
            "output_volume": 100
        });

        let config = VoipConfig::from_payload(&payload).expect("config");

        assert_eq!(config.sip_server, "sip.example.com");
        assert_eq!(config.sip_identity, "sip:alice@example.com");
        assert_eq!(config.iterate_interval_ms, 20);
    }

    #[test]
    fn config_rejects_missing_identity() {
        let payload = json!({"sip_server":"sip.example.com"});

        let error = VoipConfig::from_payload(&payload).expect_err("must reject");

        assert!(error.to_string().contains("sip_identity"));
    }
}
```

Run:

```bash
cargo test --manifest-path src/Cargo.toml -p yoyopod-voip-host config
```

Expected: passes after `mod config;` is added in `main.rs`.

- [ ] **Step 2: Add event mapping tests**

Create `src/crates/voip-host/src/events.rs`:

```rust
use serde_json::{json, Value};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RegistrationState {
    None,
    Progress,
    Ok,
    Cleared,
    Failed,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CallState {
    Idle,
    Incoming,
    OutgoingInit,
    OutgoingProgress,
    OutgoingRinging,
    OutgoingEarlyMedia,
    Connected,
    StreamsRunning,
    Paused,
    PausedByRemote,
    UpdatedByRemote,
    Released,
    Error,
    End,
}

impl RegistrationState {
    pub fn from_native(value: i32) -> Self {
        match value {
            1 => Self::Progress,
            2 => Self::Ok,
            3 => Self::Cleared,
            4 => Self::Failed,
            _ => Self::None,
        }
    }

    pub fn as_protocol(self) -> &'static str {
        match self {
            Self::None => "none",
            Self::Progress => "progress",
            Self::Ok => "ok",
            Self::Cleared => "cleared",
            Self::Failed => "failed",
        }
    }
}

impl CallState {
    pub fn from_native(value: i32) -> Self {
        match value {
            1 => Self::Incoming,
            2 => Self::OutgoingInit,
            3 => Self::OutgoingProgress,
            4 => Self::OutgoingRinging,
            5 => Self::OutgoingEarlyMedia,
            6 => Self::Connected,
            7 => Self::StreamsRunning,
            8 => Self::Paused,
            9 => Self::PausedByRemote,
            10 => Self::UpdatedByRemote,
            11 => Self::Released,
            12 => Self::Error,
            13 => Self::End,
            _ => Self::Idle,
        }
    }

    pub fn as_protocol(self) -> &'static str {
        match self {
            Self::Idle => "idle",
            Self::Incoming => "incoming",
            Self::OutgoingInit => "outgoing_init",
            Self::OutgoingProgress => "outgoing_progress",
            Self::OutgoingRinging => "outgoing_ringing",
            Self::OutgoingEarlyMedia => "outgoing_early_media",
            Self::Connected => "connected",
            Self::StreamsRunning => "streams_running",
            Self::Paused => "paused",
            Self::PausedByRemote => "paused_by_remote",
            Self::UpdatedByRemote => "updated_by_remote",
            Self::Released => "released",
            Self::Error => "error",
            Self::End => "end",
        }
    }

    pub fn is_terminal(self) -> bool {
        matches!(self, Self::Idle | Self::Released | Self::Error | Self::End)
    }
}

pub fn registration_payload(state: RegistrationState, reason: &str) -> Value {
    json!({"state": state.as_protocol(), "reason": reason})
}

pub fn call_state_payload(call_id: &str, state: CallState) -> Value {
    json!({"call_id": call_id, "state": state.as_protocol()})
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn maps_native_registration_values_to_python_values() {
        assert_eq!(RegistrationState::from_native(1).as_protocol(), "progress");
        assert_eq!(RegistrationState::from_native(2).as_protocol(), "ok");
        assert_eq!(RegistrationState::from_native(4).as_protocol(), "failed");
        assert_eq!(RegistrationState::from_native(99).as_protocol(), "none");
    }

    #[test]
    fn maps_native_call_values_to_python_values() {
        assert_eq!(CallState::from_native(1).as_protocol(), "incoming");
        assert_eq!(CallState::from_native(7).as_protocol(), "streams_running");
        assert_eq!(CallState::from_native(11).as_protocol(), "released");
        assert_eq!(CallState::from_native(99).as_protocol(), "idle");
    }

    #[test]
    fn released_error_end_are_terminal() {
        assert!(CallState::Released.is_terminal());
        assert!(CallState::Error.is_terminal());
        assert!(CallState::End.is_terminal());
        assert!(!CallState::Connected.is_terminal());
    }
}
```

Run:

```bash
cargo test --manifest-path src/Cargo.toml -p yoyopod-voip-host events
```

Expected: event mapping tests pass.

- [ ] **Step 3: Add host state tests**

Create `src/crates/voip-host/src/host.rs`:

```rust
use crate::config::VoipConfig;
use serde_json::json;

#[derive(Debug, Default)]
pub struct VoipHost {
    config: Option<VoipConfig>,
    registered: bool,
    active_call_id: Option<String>,
}

impl VoipHost {
    pub fn configure(&mut self, config: VoipConfig) {
        self.config = Some(config);
        self.registered = false;
        self.active_call_id = None;
    }

    pub fn mark_registered(&mut self, registered: bool) {
        self.registered = registered;
    }

    pub fn set_active_call_id(&mut self, call_id: Option<String>) {
        self.active_call_id = call_id;
    }

    pub fn health_payload(&self) -> serde_json::Value {
        json!({
            "configured": self.config.is_some(),
            "registered": self.registered,
            "active_call_id": self.active_call_id,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn config() -> VoipConfig {
        VoipConfig {
            sip_server: "sip.example.com".to_string(),
            sip_identity: "sip:alice@example.com".to_string(),
            ..serde_json::from_value(serde_json::json!({})).unwrap()
        }
    }

    #[test]
    fn health_reports_configured_registered_and_call_id() {
        let mut host = VoipHost::default();
        host.configure(config());
        host.mark_registered(true);
        host.set_active_call_id(Some("call-1".to_string()));

        let payload = host.health_payload();

        assert_eq!(payload["configured"], true);
        assert_eq!(payload["registered"], true);
        assert_eq!(payload["active_call_id"], "call-1");
    }
}
```

Run:

```bash
cargo test --manifest-path src/Cargo.toml -p yoyopod-voip-host host
```

Expected: host state test passes after adding `mod host;`.

- [ ] **Step 4: Wire modules into `main.rs`**

At the top of `main.rs`, use:

```rust
mod config;
mod events;
mod host;
mod protocol;
```

Extend command handling:

```rust
let mut host = host::VoipHost::default();

match envelope.message_type.as_str() {
    "voip.configure" => {
        let config = config::VoipConfig::from_payload(&envelope.payload)?;
        host.configure(config);
        write_envelope(&WorkerEnvelope::result(
            "voip.configure",
            envelope.request_id,
            json!({"configured": true}),
        ))?;
    }
    "voip.health" => {
        write_envelope(&WorkerEnvelope::result(
            "voip.health",
            envelope.request_id,
            host.health_payload(),
        ))?;
    }
    "voip.shutdown" => break,
    _ => {
        write_envelope(&WorkerEnvelope::error(
            "voip.error",
            envelope.request_id,
            "unsupported_command",
            format!("unsupported command {}", envelope.message_type),
        ))?;
    }
}
```

- [ ] **Step 5: Run Rust and repo gates, then commit**

Run:

```bash
cargo fmt --manifest-path src/Cargo.toml
cargo test --manifest-path src/Cargo.toml -p yoyopod-voip-host --locked
cargo test --manifest-path src/Cargo.toml --workspace --locked
uv run python scripts/quality.py gate
uv run pytest -q
```

Commit:

```bash
git add src
git commit -m "feat(voip): add rust voip host state model"
```

Expected: Rust host can accept configure/health/shutdown without liblinphone loaded.

## Task 3: Bind The Existing Liblinphone Shim In Rust

**Files:**
- Create: `src/crates/voip-host/src/shim.rs`
- Modify: `src/crates/voip-host/src/host.rs`
- Modify: `src/crates/voip-host/src/main.rs`

- [ ] **Step 1: Add shim path resolution tests**

Create `src/crates/voip-host/src/shim.rs`:

```rust
use libloading::{Library, Symbol};
use std::env;
use std::ffi::{CStr, CString};
use std::os::raw::{c_char, c_int};
use std::path::{Path, PathBuf};
use thiserror::Error;

#[repr(C)]
#[derive(Clone, Copy)]
pub struct NativeEvent {
    pub event_type: i32,
    pub registration_state: i32,
    pub call_state: i32,
    pub message_kind: i32,
    pub message_direction: i32,
    pub message_delivery_state: i32,
    pub duration_ms: i32,
    pub unread: i32,
    pub message_id: [c_char; 128],
    pub peer_sip_address: [c_char; 256],
    pub sender_sip_address: [c_char; 256],
    pub recipient_sip_address: [c_char; 256],
    pub local_file_path: [c_char; 512],
    pub mime_type: [c_char; 128],
    pub text: [c_char; 1024],
    pub reason: [c_char; 256],
}

#[derive(Debug, Error)]
pub enum ShimError {
    #[error("liblinphone shim path could not be resolved")]
    NotFound,
    #[error("liblinphone shim load failed: {0}")]
    Load(String),
    #[error("liblinphone shim call failed: {0}")]
    Call(String),
    #[error("string contains interior NUL: {0}")]
    InvalidCString(#[from] std::ffi::NulError),
}

pub fn resolve_shim_path(explicit_path: Option<&str>) -> Result<PathBuf, ShimError> {
    if let Some(path) = explicit_path.filter(|value| !value.trim().is_empty()) {
        return Ok(PathBuf::from(path));
    }
    if let Ok(path) = env::var("YOYOPOD_LIBLINPHONE_SHIM_PATH") {
        if !path.trim().is_empty() {
            return Ok(PathBuf::from(path));
        }
    }
    let repo_candidate = Path::new("yoyopod")
        .join("backends")
        .join("voip")
        .join("shim_native")
        .join("build")
        .join("libyoyopod_liblinphone_shim.so");
    if repo_candidate.exists() {
        return Ok(repo_candidate);
    }
    Err(ShimError::NotFound)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn explicit_path_wins() {
        let path = resolve_shim_path(Some("/tmp/libshim.so")).expect("path");
        assert_eq!(path, PathBuf::from("/tmp/libshim.so"));
    }
}
```

Run:

```bash
cargo test --manifest-path src/Cargo.toml -p yoyopod-voip-host shim
```

Expected: fails until `mod shim;` is added.

- [ ] **Step 2: Add dynamic symbols**

Add to `shim.rs`:

```rust
type InitFn = unsafe extern "C" fn() -> c_int;
type ShutdownFn = unsafe extern "C" fn();
type StopFn = unsafe extern "C" fn();
type IterateFn = unsafe extern "C" fn();
type PollEventFn = unsafe extern "C" fn(*mut NativeEvent) -> c_int;
type StartFn = unsafe extern "C" fn(
    *const c_char,
    *const c_char,
    *const c_char,
    *const c_char,
    *const c_char,
    *const c_char,
    *const c_char,
    *const c_char,
    *const c_char,
    *const c_char,
    *const c_char,
    i32,
    *const c_char,
    *const c_char,
    *const c_char,
    *const c_char,
    i32,
    i32,
    i32,
    *const c_char,
) -> c_int;
type SimpleCallFn = unsafe extern "C" fn() -> c_int;
type MakeCallFn = unsafe extern "C" fn(*const c_char) -> c_int;
type SetMutedFn = unsafe extern "C" fn(i32) -> c_int;
type LastErrorFn = unsafe extern "C" fn() -> *const c_char;

pub struct LiblinphoneShim {
    _library: Library,
    init: InitFn,
    shutdown: ShutdownFn,
    start: StartFn,
    stop: StopFn,
    iterate: IterateFn,
    poll_event: PollEventFn,
    make_call: MakeCallFn,
    answer_call: SimpleCallFn,
    reject_call: SimpleCallFn,
    hangup: SimpleCallFn,
    set_muted: SetMutedFn,
    last_error: LastErrorFn,
}

impl LiblinphoneShim {
    pub unsafe fn load(path: &Path) -> Result<Self, ShimError> {
        let library = Library::new(path).map_err(|error| ShimError::Load(error.to_string()))?;
        unsafe fn symbol<T: Copy>(library: &Library, name: &[u8]) -> Result<T, ShimError> {
            let symbol: Symbol<T> = library
                .get(name)
                .map_err(|error| ShimError::Load(error.to_string()))?;
            Ok(*symbol)
        }
        Ok(Self {
            init: symbol(&library, b"yoyopod_liblinphone_init\0")?,
            shutdown: symbol(&library, b"yoyopod_liblinphone_shutdown\0")?,
            start: symbol(&library, b"yoyopod_liblinphone_start\0")?,
            stop: symbol(&library, b"yoyopod_liblinphone_stop\0")?,
            iterate: symbol(&library, b"yoyopod_liblinphone_iterate\0")?,
            poll_event: symbol(&library, b"yoyopod_liblinphone_poll_event\0")?,
            make_call: symbol(&library, b"yoyopod_liblinphone_make_call\0")?,
            answer_call: symbol(&library, b"yoyopod_liblinphone_answer_call\0")?,
            reject_call: symbol(&library, b"yoyopod_liblinphone_reject_call\0")?,
            hangup: symbol(&library, b"yoyopod_liblinphone_hangup\0")?,
            set_muted: symbol(&library, b"yoyopod_liblinphone_set_muted\0")?,
            last_error: symbol(&library, b"yoyopod_liblinphone_last_error\0")?,
            _library: library,
        })
    }

    fn last_error(&self) -> String {
        unsafe {
            let raw = (self.last_error)();
            if raw.is_null() {
                return "unknown liblinphone shim error".to_string();
            }
            CStr::from_ptr(raw).to_string_lossy().into_owned()
        }
    }

    fn check(&self, code: c_int) -> Result<(), ShimError> {
        if code == 0 {
            Ok(())
        } else {
            Err(ShimError::Call(self.last_error()))
        }
    }
}
```

- [ ] **Step 3: Add safe call methods**

Add:

```rust
impl LiblinphoneShim {
    pub fn init(&self) -> Result<(), ShimError> {
        self.check(unsafe { (self.init)() })
    }

    pub fn shutdown(&self) {
        unsafe { (self.shutdown)() }
    }

    pub fn stop(&self) {
        unsafe { (self.stop)() }
    }

    pub fn iterate(&self) {
        unsafe { (self.iterate)() }
    }

    pub fn make_call(&self, sip_address: &str) -> Result<(), ShimError> {
        let sip_address = CString::new(sip_address)?;
        self.check(unsafe { (self.make_call)(sip_address.as_ptr()) })
    }

    pub fn answer_call(&self) -> Result<(), ShimError> {
        self.check(unsafe { (self.answer_call)() })
    }

    pub fn reject_call(&self) -> Result<(), ShimError> {
        self.check(unsafe { (self.reject_call)() })
    }

    pub fn hangup(&self) -> Result<(), ShimError> {
        self.check(unsafe { (self.hangup)() })
    }

    pub fn set_muted(&self, muted: bool) -> Result<(), ShimError> {
        self.check(unsafe { (self.set_muted)(if muted { 1 } else { 0 }) })
    }
}
```

Do not implement text or voice-note shim calls in this slice.

- [ ] **Step 4: Wire loading into CLI args**

In `main.rs`, keep the `--shim-path` arg and load only when `voip.configure` is followed by `voip.register`. The skeleton must still allow health tests without a shim.

Add:

```rust
let explicit_shim_path = if args.shim_path.trim().is_empty() {
    None
} else {
    Some(args.shim_path.clone())
};
```

Pass `explicit_shim_path.as_deref()` into host registration in Task 4.

- [ ] **Step 5: Run Rust and repo gates, then commit**

Run:

```bash
cargo fmt --manifest-path src/Cargo.toml
cargo test --manifest-path src/Cargo.toml -p yoyopod-voip-host --locked
cargo test --manifest-path src/Cargo.toml --workspace --locked
uv run python scripts/quality.py gate
uv run pytest -q
```

Commit:

```bash
git add src
git commit -m "feat(voip): bind rust host to liblinphone shim"
```

Expected: Rust can compile the dynamic shim wrapper without requiring the shim at test time.

## Task 4: Implement Rust Registration And Call Commands

**Files:**
- Modify: `src/crates/voip-host/src/host.rs`
- Modify: `src/crates/voip-host/src/main.rs`
- Modify: `src/crates/voip-host/src/shim.rs`

- [ ] **Step 1: Add host command tests with a fake backend trait**

In `host.rs`, introduce a small trait above `VoipHost`:

```rust
pub trait CallBackend {
    fn start(&mut self, config: &VoipConfig) -> Result<(), String>;
    fn stop(&mut self);
    fn iterate(&mut self) -> Result<Vec<BackendEvent>, String>;
    fn make_call(&mut self, sip_address: &str) -> Result<String, String>;
    fn answer_call(&mut self) -> Result<(), String>;
    fn reject_call(&mut self) -> Result<(), String>;
    fn hangup(&mut self) -> Result<(), String>;
    fn set_muted(&mut self, muted: bool) -> Result<(), String>;
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum BackendEvent {
    RegistrationChanged { state: String, reason: String },
    IncomingCall { call_id: String, from_uri: String },
    CallStateChanged { call_id: String, state: String },
    BackendStopped { reason: String },
}
```

Add tests:

```rust
#[cfg(test)]
mod command_tests {
    use super::*;
    use serde_json::json;

    #[derive(Default)]
    struct FakeBackend {
        calls: Vec<String>,
    }

    impl CallBackend for FakeBackend {
        fn start(&mut self, _config: &VoipConfig) -> Result<(), String> {
            self.calls.push("start".to_string());
            Ok(())
        }
        fn stop(&mut self) {
            self.calls.push("stop".to_string());
        }
        fn iterate(&mut self) -> Result<Vec<BackendEvent>, String> {
            Ok(vec![])
        }
        fn make_call(&mut self, sip_address: &str) -> Result<String, String> {
            self.calls.push(format!("dial:{sip_address}"));
            Ok("call-outgoing".to_string())
        }
        fn answer_call(&mut self) -> Result<(), String> {
            self.calls.push("answer".to_string());
            Ok(())
        }
        fn reject_call(&mut self) -> Result<(), String> {
            self.calls.push("reject".to_string());
            Ok(())
        }
        fn hangup(&mut self) -> Result<(), String> {
            self.calls.push("hangup".to_string());
            Ok(())
        }
        fn set_muted(&mut self, muted: bool) -> Result<(), String> {
            self.calls.push(format!("mute:{muted}"));
            Ok(())
        }
    }

    fn config() -> VoipConfig {
        VoipConfig::from_payload(&json!({
            "sip_server":"sip.example.com",
            "sip_identity":"sip:alice@example.com"
        }))
        .unwrap()
    }

    #[test]
    fn register_starts_backend_and_health_reports_registered() {
        let mut host = VoipHost::default();
        let mut backend = FakeBackend::default();
        host.configure(config());

        host.register(&mut backend).expect("register");

        assert_eq!(backend.calls, vec!["start"]);
        assert_eq!(host.health_payload()["registered"], true);
    }

    #[test]
    fn dial_sets_active_call_id() {
        let mut host = VoipHost::default();
        let mut backend = FakeBackend::default();
        host.configure(config());
        host.register(&mut backend).unwrap();

        host.dial(&mut backend, "sip:bob@example.com").expect("dial");

        assert_eq!(host.health_payload()["active_call_id"], "call-outgoing");
    }
}
```

Run:

```bash
cargo test --manifest-path src/Cargo.toml -p yoyopod-voip-host host::command_tests
```

Expected: fails until command methods exist.

- [ ] **Step 2: Implement command methods on `VoipHost`**

Add methods:

```rust
impl VoipHost {
    pub fn register<B: CallBackend>(&mut self, backend: &mut B) -> Result<(), String> {
        let config = self
            .config
            .as_ref()
            .ok_or_else(|| "voip host is not configured".to_string())?;
        backend.start(config)?;
        self.registered = true;
        Ok(())
    }

    pub fn unregister<B: CallBackend>(&mut self, backend: &mut B) {
        backend.stop();
        self.registered = false;
        self.active_call_id = None;
    }

    pub fn dial<B: CallBackend>(
        &mut self,
        backend: &mut B,
        sip_address: &str,
    ) -> Result<(), String> {
        let call_id = backend.make_call(sip_address)?;
        self.active_call_id = Some(call_id);
        Ok(())
    }

    pub fn answer<B: CallBackend>(&mut self, backend: &mut B) -> Result<(), String> {
        backend.answer_call()
    }

    pub fn reject<B: CallBackend>(&mut self, backend: &mut B) -> Result<(), String> {
        backend.reject_call()?;
        self.active_call_id = None;
        Ok(())
    }

    pub fn hangup<B: CallBackend>(&mut self, backend: &mut B) -> Result<(), String> {
        backend.hangup()?;
        self.active_call_id = None;
        Ok(())
    }

    pub fn set_muted<B: CallBackend>(
        &mut self,
        backend: &mut B,
        muted: bool,
    ) -> Result<(), String> {
        backend.set_muted(muted)
    }
}
```

- [ ] **Step 3: Implement `CallBackend` for the real shim**

In `shim.rs`, add:

```rust
use crate::config::VoipConfig;
use crate::host::{BackendEvent, CallBackend};

pub struct ShimBackend {
    shim: LiblinphoneShim,
    next_outgoing_call_id: u64,
}

impl ShimBackend {
    pub unsafe fn load(path: &Path) -> Result<Self, ShimError> {
        Ok(Self {
            shim: LiblinphoneShim::load(path)?,
            next_outgoing_call_id: 1,
        })
    }
}

impl CallBackend for ShimBackend {
    fn start(&mut self, config: &VoipConfig) -> Result<(), String> {
        self.shim.init().map_err(|error| error.to_string())?;
        self.shim
            .start(config)
            .map_err(|error| error.to_string())
    }

    fn stop(&mut self) {
        self.shim.stop();
        self.shim.shutdown();
    }

    fn iterate(&mut self) -> Result<Vec<BackendEvent>, String> {
        self.shim.iterate();
        self.shim.drain_events().map_err(|error| error.to_string())
    }

    fn make_call(&mut self, sip_address: &str) -> Result<String, String> {
        self.shim.make_call(sip_address).map_err(|error| error.to_string())?;
        let call_id = format!("outgoing-{}", self.next_outgoing_call_id);
        self.next_outgoing_call_id += 1;
        Ok(call_id)
    }

    fn answer_call(&mut self) -> Result<(), String> {
        self.shim.answer_call().map_err(|error| error.to_string())
    }

    fn reject_call(&mut self) -> Result<(), String> {
        self.shim.reject_call().map_err(|error| error.to_string())
    }

    fn hangup(&mut self) -> Result<(), String> {
        self.shim.hangup().map_err(|error| error.to_string())
    }

    fn set_muted(&mut self, muted: bool) -> Result<(), String> {
        self.shim.set_muted(muted).map_err(|error| error.to_string())
    }
}
```

Implement `LiblinphoneShim::start(config)` using the existing C function signature. Use `CString::new` for every string field and pass `0` for liblinphone software mic gain because Python currently returns neutral software gain.

- [ ] **Step 4: Add event draining from the shim**

In `shim.rs`, implement:

```rust
pub fn c_string<const N: usize>(buffer: &[c_char; N]) -> String {
    unsafe { CStr::from_ptr(buffer.as_ptr()) }
        .to_string_lossy()
        .into_owned()
}

impl LiblinphoneShim {
    pub fn drain_events(&self) -> Result<Vec<BackendEvent>, ShimError> {
        let mut events = Vec::new();
        loop {
            let mut event = NativeEvent::default();
            let has_event = unsafe { (self.poll_event)(&mut event as *mut NativeEvent) };
            if has_event == 0 {
                break;
            }
            match event.event_type {
                1 => events.push(BackendEvent::RegistrationChanged {
                    state: crate::events::RegistrationState::from_native(event.registration_state)
                        .as_protocol()
                        .to_string(),
                    reason: c_string(&event.reason),
                }),
                2 => events.push(BackendEvent::CallStateChanged {
                    call_id: c_string(&event.peer_sip_address),
                    state: crate::events::CallState::from_native(event.call_state)
                        .as_protocol()
                        .to_string(),
                }),
                3 => events.push(BackendEvent::IncomingCall {
                    call_id: c_string(&event.peer_sip_address),
                    from_uri: c_string(&event.peer_sip_address),
                }),
                4 => events.push(BackendEvent::BackendStopped {
                    reason: c_string(&event.reason),
                }),
                _ => {}
            }
        }
        Ok(events)
    }
}
```

Derive default for `NativeEvent` manually:

```rust
impl Default for NativeEvent {
    fn default() -> Self {
        unsafe { std::mem::zeroed() }
    }
}
```

- [ ] **Step 5: Wire register/dial/call commands in `main.rs`**

The command loop should create the backend lazily when `voip.register` arrives:

```rust
let mut backend: Option<shim::ShimBackend> = None;

match envelope.message_type.as_str() {
    "voip.register" => {
        if backend.is_none() {
            let path = shim::resolve_shim_path(explicit_shim_path.as_deref())?;
            backend = Some(unsafe { shim::ShimBackend::load(&path)? });
        }
        let backend_ref = backend.as_mut().expect("backend was just created");
        host.register(backend_ref)?;
        write_envelope(&WorkerEnvelope::result(
            "voip.register",
            envelope.request_id,
            json!({"registered": true}),
        ))?;
    }
    "voip.unregister" => {
        if let Some(backend_ref) = backend.as_mut() {
            host.unregister(backend_ref);
        }
        write_envelope(&WorkerEnvelope::result(
            "voip.unregister",
            envelope.request_id,
            json!({"registered": false}),
        ))?;
    }
    "voip.dial" => {
        let uri = envelope.payload["uri"].as_str().unwrap_or("").trim();
        if uri.is_empty() {
            write_envelope(&WorkerEnvelope::error("voip.error", envelope.request_id, "invalid_command", "voip.dial requires uri"))?;
        } else if let Some(backend_ref) = backend.as_mut() {
            host.dial(backend_ref, uri)?;
            write_envelope(&WorkerEnvelope::result("voip.dial", envelope.request_id, host.health_payload()))?;
        }
    }
    "voip.answer" => {
        if let Some(backend_ref) = backend.as_mut() {
            host.answer(backend_ref)?;
            write_envelope(&WorkerEnvelope::result("voip.answer", envelope.request_id, json!({"accepted": true})))?;
        }
    }
    "voip.reject" => {
        if let Some(backend_ref) = backend.as_mut() {
            host.reject(backend_ref)?;
            write_envelope(&WorkerEnvelope::result("voip.reject", envelope.request_id, json!({"rejected": true})))?;
        }
    }
    "voip.hangup" => {
        if let Some(backend_ref) = backend.as_mut() {
            host.hangup(backend_ref)?;
            write_envelope(&WorkerEnvelope::result("voip.hangup", envelope.request_id, json!({"hung_up": true})))?;
        }
    }
    "voip.set_mute" => {
        let muted = envelope.payload["muted"].as_bool().unwrap_or(false);
        if let Some(backend_ref) = backend.as_mut() {
            host.set_muted(backend_ref, muted)?;
            write_envelope(&WorkerEnvelope::result("voip.set_mute", envelope.request_id, json!({"muted": muted})))?;
        }
    }
    _ => {}
}
```

Use helper functions to keep `main.rs` readable if the match grows beyond one screen.

- [ ] **Step 6: Add nonblocking iterate between stdin polls**

Keep this simple for the first slice: after each handled command, call `backend.iterate()` and emit any pending events:

```rust
fn emit_backend_events(events: Vec<host::BackendEvent>) -> Result<()> {
    for event in events {
        match event {
            host::BackendEvent::RegistrationChanged { state, reason } => {
                write_envelope(&WorkerEnvelope::event(
                    "voip.registration_changed",
                    json!({"state": state, "reason": reason}),
                ))?;
            }
            host::BackendEvent::IncomingCall { call_id, from_uri } => {
                write_envelope(&WorkerEnvelope::event(
                    "voip.incoming_call",
                    json!({"call_id": call_id, "from_uri": from_uri}),
                ))?;
            }
            host::BackendEvent::CallStateChanged { call_id, state } => {
                write_envelope(&WorkerEnvelope::event(
                    "voip.call_state_changed",
                    json!({"call_id": call_id, "state": state}),
                ))?;
            }
            host::BackendEvent::BackendStopped { reason } => {
                write_envelope(&WorkerEnvelope::event(
                    "voip.backend_stopped",
                    json!({"reason": reason}),
                ))?;
            }
        }
    }
    Ok(())
}
```

The implementation plan for the next slice can replace command-coupled iterate with a timed loop if hardware validation shows registration/call events need stricter cadence.

- [ ] **Step 7: Run Rust and repo gates, then commit**

Run:

```bash
cargo fmt --manifest-path src/Cargo.toml
cargo test --manifest-path src/Cargo.toml -p yoyopod-voip-host --locked
cargo test --manifest-path src/Cargo.toml --workspace --locked
uv run python scripts/quality.py gate
uv run pytest -q
```

Commit:

```bash
git add src
git commit -m "feat(voip): handle rust call commands"
```

Expected: Rust host handles registration and call commands against the real shim API shape.

## Task 5: Add Python `RustHostBackend`

**Files:**
- Create: `yoyopod/backends/voip/rust_host.py`
- Create: `tests/backends/test_rust_host_voip.py`
- Modify: `yoyopod/backends/voip/__init__.py`

- [ ] **Step 1: Write failing adapter tests**

Create `tests/backends/test_rust_host_voip.py`:

```python
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from yoyopod.backends.voip.rust_host import RustHostBackend
from yoyopod.integrations.call.models import (
    BackendStopped,
    CallState,
    CallStateChanged,
    IncomingCallDetected,
    RegistrationState,
    RegistrationStateChanged,
    VoIPConfig,
)


class _FakeSupervisor:
    def __init__(self) -> None:
        self.registered: list[tuple[str, Any]] = []
        self.started: list[str] = []
        self.stopped: list[tuple[str, float]] = []
        self.sent: list[tuple[str, str, dict[str, Any]]] = []
        self.messages: list[Any] = []

    def register(self, domain: str, config: Any) -> None:
        self.registered.append((domain, config))

    def start(self, domain: str) -> bool:
        self.started.append(domain)
        return True

    def stop(self, domain: str, *, grace_seconds: float = 1.0) -> None:
        self.stopped.append((domain, grace_seconds))

    def drain_worker_messages(self, domain: str) -> list[Any]:
        assert domain == "voip"
        drained = list(self.messages)
        self.messages.clear()
        return drained

    def send_command(
        self,
        domain: str,
        *,
        type: str,
        payload: dict[str, Any] | None = None,
        request_id: str | None = None,
        timestamp_ms: int = 0,
        deadline_ms: int = 0,
    ) -> bool:
        self.sent.append((domain, type, payload or {}))
        return True


def _config() -> VoIPConfig:
    return VoIPConfig(sip_server="sip.example.com", sip_identity="sip:alice@example.com")


def _event(message_type: str, payload: dict[str, Any]) -> Any:
    return SimpleNamespace(kind="event", type=message_type, payload=payload)


def test_start_registers_worker_and_sends_configure_register() -> None:
    supervisor = _FakeSupervisor()
    backend = RustHostBackend(_config(), worker_supervisor=supervisor, worker_path="/bin/voip")

    assert backend.start() is True

    assert supervisor.registered[0][0] == "voip"
    assert supervisor.started == ["voip"]
    assert [item[1] for item in supervisor.sent] == ["voip.configure", "voip.register"]
    assert backend.running is True


def test_call_commands_send_worker_commands() -> None:
    supervisor = _FakeSupervisor()
    backend = RustHostBackend(_config(), worker_supervisor=supervisor, worker_path="/bin/voip")
    backend.start()
    supervisor.sent.clear()

    assert backend.make_call("sip:bob@example.com") is True
    assert backend.answer_call() is True
    assert backend.reject_call() is True
    assert backend.hangup() is True
    assert backend.mute() is True
    assert backend.unmute() is True

    assert [item[1] for item in supervisor.sent] == [
        "voip.dial",
        "voip.answer",
        "voip.reject",
        "voip.hangup",
        "voip.set_mute",
        "voip.set_mute",
    ]
    assert supervisor.sent[0][2] == {"uri": "sip:bob@example.com"}
    assert supervisor.sent[4][2] == {"muted": True}
    assert supervisor.sent[5][2] == {"muted": False}


def test_worker_events_translate_to_voip_events() -> None:
    supervisor = _FakeSupervisor()
    backend = RustHostBackend(_config(), worker_supervisor=supervisor, worker_path="/bin/voip")
    received: list[object] = []
    backend.on_event(received.append)

    backend.handle_worker_message(
        _event("voip.registration_changed", {"state": "ok", "reason": ""})
    )
    backend.handle_worker_message(
        _event("voip.incoming_call", {"call_id": "call-1", "from_uri": "sip:bob@example.com"})
    )
    backend.handle_worker_message(
        _event("voip.call_state_changed", {"call_id": "call-1", "state": "streams_running"})
    )
    backend.handle_worker_message(
        _event("voip.backend_stopped", {"reason": "iterate failed"})
    )

    assert isinstance(received[0], RegistrationStateChanged)
    assert received[0].state == RegistrationState.OK
    assert isinstance(received[1], IncomingCallDetected)
    assert received[1].caller_address == "sip:bob@example.com"
    assert isinstance(received[2], CallStateChanged)
    assert received[2].state == CallState.STREAMS_RUNNING
    assert isinstance(received[3], BackendStopped)
    assert received[3].reason == "iterate failed"


def test_iterate_is_noop_and_unsupported_messaging_fails() -> None:
    backend = RustHostBackend(_config(), worker_supervisor=_FakeSupervisor(), worker_path="/bin/voip")

    assert backend.iterate() == 0
    assert backend.get_iterate_metrics() is None
    assert backend.send_text_message("sip:bob@example.com", "hi") is None
    assert backend.start_voice_note_recording("/tmp/a.wav") is False
    assert backend.stop_voice_note_recording() is None
```

Run:

```bash
uv run pytest -q tests/backends/test_rust_host_voip.py
```

Expected: fails because `RustHostBackend` does not exist.

- [ ] **Step 2: Implement `RustHostBackend`**

Create `yoyopod/backends/voip/rust_host.py`:

```python
"""VoIPBackend adapter backed by the Rust VoIP Host worker."""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from typing import Any

from loguru import logger

from yoyopod.backends.voip.protocol import VoIPIterateMetrics
from yoyopod.core.workers import WorkerProcessConfig
from yoyopod.integrations.call.models import (
    BackendStopped,
    CallState,
    CallStateChanged,
    IncomingCallDetected,
    RegistrationState,
    RegistrationStateChanged,
    VoIPConfig,
    VoIPEvent,
)


class RustHostBackend:
    """Calls-only VoIPBackend adapter for the Rust VoIP Host."""

    def __init__(
        self,
        config: VoIPConfig,
        *,
        worker_supervisor: Any,
        worker_path: str,
        domain: str = "voip",
        env: dict[str, str] | None = None,
        cwd: str | None = None,
    ) -> None:
        self.config = config
        self.worker_supervisor = worker_supervisor
        self.worker_path = worker_path
        self.domain = domain
        self.env = env
        self.cwd = cwd
        self.running = False
        self.event_callbacks: list[Callable[[VoIPEvent], None]] = []

    def on_event(self, callback: Callable[[VoIPEvent], None]) -> None:
        self.event_callbacks.append(callback)

    def start(self) -> bool:
        register = getattr(self.worker_supervisor, "register", None)
        start = getattr(self.worker_supervisor, "start", None)
        if not callable(register) or not callable(start):
            logger.error("Rust VoIP Host supervisor is unavailable")
            return False
        register(
            self.domain,
            WorkerProcessConfig(
                name=self.domain,
                argv=[self.worker_path],
                cwd=self.cwd,
                env=self.env,
            ),
        )
        if not bool(start(self.domain)):
            return False
        if not self._send("voip.configure", dataclasses.asdict(self.config)):
            return False
        if not self._send("voip.register", {}):
            return False
        self.running = True
        return True

    def stop(self) -> None:
        self._send("voip.unregister", {})
        stop = getattr(self.worker_supervisor, "stop", None)
        if callable(stop):
            stop(self.domain, grace_seconds=1.0)
        self.running = False

    def iterate(self) -> int:
        return 0

    def get_iterate_metrics(self) -> VoIPIterateMetrics | None:
        return None

    def make_call(self, sip_address: str) -> bool:
        return self._send("voip.dial", {"uri": sip_address})

    def answer_call(self) -> bool:
        return self._send("voip.answer", {})

    def reject_call(self) -> bool:
        return self._send("voip.reject", {})

    def hangup(self) -> bool:
        return self._send("voip.hangup", {})

    def mute(self) -> bool:
        return self._send("voip.set_mute", {"muted": True})

    def unmute(self) -> bool:
        return self._send("voip.set_mute", {"muted": False})

    def send_text_message(self, sip_address: str, text: str) -> str | None:
        logger.warning("Rust VoIP Host does not support text messages in calls-only mode")
        return None

    def start_voice_note_recording(self, file_path: str) -> bool:
        logger.warning("Rust VoIP Host does not support voice notes in calls-only mode")
        return False

    def stop_voice_note_recording(self) -> int | None:
        return None

    def cancel_voice_note_recording(self) -> bool:
        return False

    def send_voice_note(
        self,
        sip_address: str,
        *,
        file_path: str,
        duration_ms: int,
        mime_type: str,
    ) -> str | None:
        return None

    def handle_worker_message(self, event: Any) -> None:
        if getattr(event, "type", "") == "voip.registration_changed":
            self._dispatch(
                RegistrationStateChanged(
                    state=_registration_state(str(event.payload.get("state", "none")))
                )
            )
            return
        if getattr(event, "type", "") == "voip.incoming_call":
            self._dispatch(
                IncomingCallDetected(
                    caller_address=str(event.payload.get("from_uri", ""))
                )
            )
            return
        if getattr(event, "type", "") == "voip.call_state_changed":
            self._dispatch(
                CallStateChanged(state=_call_state(str(event.payload.get("state", "idle"))))
            )
            return
        if getattr(event, "type", "") == "voip.backend_stopped":
            self.running = False
            self._dispatch(BackendStopped(reason=str(event.payload.get("reason", ""))))

    def _send(self, message_type: str, payload: dict[str, Any]) -> bool:
        send_command = getattr(self.worker_supervisor, "send_command", None)
        if not callable(send_command):
            return False
        return bool(send_command(self.domain, type=message_type, payload=payload))

    def _dispatch(self, event: VoIPEvent) -> None:
        for callback in list(self.event_callbacks):
            try:
                callback(event)
            except Exception:
                logger.exception("Rust VoIP Host callback raised for {}", type(event).__name__)


def _registration_state(value: str) -> RegistrationState:
    try:
        return RegistrationState(value)
    except ValueError:
        return RegistrationState.NONE


def _call_state(value: str) -> CallState:
    try:
        return CallState(value)
    except ValueError:
        return CallState.IDLE
```

- [ ] **Step 3: Export the backend lazily**

In `yoyopod/backends/voip/__init__.py`, add:

```python
if TYPE_CHECKING:
    from yoyopod.backends.voip.rust_host import RustHostBackend
```

Add to `_EXPORTS`:

```python
"RustHostBackend": ("yoyopod.backends.voip.rust_host", "RustHostBackend"),
```

Add to `__all__`:

```python
"RustHostBackend",
```

- [ ] **Step 4: Make adapter tests pass**

Run:

```bash
uv run pytest -q tests/backends/test_rust_host_voip.py
```

Expected: adapter tests pass.

- [ ] **Step 5: Run repo gates and commit**

Run:

```bash
uv run python scripts/quality.py gate
uv run pytest -q
```

Commit:

```bash
git add yoyopod/backends/voip tests/backends/test_rust_host_voip.py
git commit -m "feat(voip): add rust host backend adapter"
```

Expected: Python can use Rust-host-backed calls through the existing backend protocol.

## Task 6: Add Runtime Selection, Conflict Handling, And Worker Event Subscription

**Files:**
- Modify: `yoyopod/core/bootstrap/managers_boot.py`
- Modify: `yoyopod/core/bootstrap/callbacks_boot.py`
- Modify: `tests/core/test_bootstrap.py`

- [ ] **Step 1: Write failing boot selection tests**

Add to `tests/core/test_bootstrap.py`:

```python
def test_voip_rust_host_and_python_sidecar_flags_conflict(monkeypatch: pytest.MonkeyPatch) -> None:
    from yoyopod.core.bootstrap.managers_boot import _rust_voip_host_enabled, _voip_sidecar_enabled

    monkeypatch.setenv("YOYOPOD_RUST_VOIP_HOST", "1")
    monkeypatch.setenv("YOYOPOD_VOIP_SIDECAR", "1")

    assert _rust_voip_host_enabled() is True
    assert _voip_sidecar_enabled() is True


def test_rust_host_backend_receives_worker_supervisor(monkeypatch: pytest.MonkeyPatch) -> None:
    from yoyopod.core.bootstrap.managers_boot import _rust_voip_host_enabled

    monkeypatch.setenv("YOYOPOD_RUST_VOIP_HOST", "true")

    assert _rust_voip_host_enabled() is True
```

Run:

```bash
uv run pytest -q tests/core/test_bootstrap.py::test_voip_rust_host_and_python_sidecar_flags_conflict tests/core/test_bootstrap.py::test_rust_host_backend_receives_worker_supervisor
```

Expected: fails until `_rust_voip_host_enabled` exists.

- [ ] **Step 2: Add Rust host env helpers**

In `yoyopod/core/bootstrap/managers_boot.py`, add:

```python
def _rust_voip_host_enabled() -> bool:
    raw = os.environ.get("YOYOPOD_RUST_VOIP_HOST", "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _rust_voip_host_worker_path() -> str:
    return os.environ.get(
        "YOYOPOD_RUST_VOIP_HOST_WORKER",
        "src/crates/voip-host/build/yoyopod-voip-host",
    ).strip()
```

In `init_managers`, before backend selection:

```python
if _voip_sidecar_enabled() and _rust_voip_host_enabled():
    raise RuntimeError(
        "YOYOPOD_VOIP_SIDECAR and YOYOPOD_RUST_VOIP_HOST cannot both be enabled"
    )
```

Then select the Rust backend:

```python
if _rust_voip_host_enabled():
    self.logger.info("    YOYOPOD_RUST_VOIP_HOST=1 - using Rust VoIP Host backend")
    from yoyopod.backends.voip.rust_host import RustHostBackend

    sidecar_backed_backend = RustHostBackend(
        voip_config,
        worker_supervisor=self.app.worker_supervisor,
        worker_path=_rust_voip_host_worker_path(),
    )
    background_iterate_enabled = False
elif _voip_sidecar_enabled():
    ...
```

- [ ] **Step 3: Subscribe Rust backend to worker messages**

In `CallbacksBoot.setup_voip_callbacks`, after manager callback registration:

```python
backend = getattr(self.app.voip_manager, "backend", None)
handle_worker_message = getattr(backend, "handle_worker_message", None)
if callable(handle_worker_message):
    from yoyopod.core.events import WorkerMessageReceivedEvent

    self.app.bus.subscribe(WorkerMessageReceivedEvent, handle_worker_message)
```

`RustHostBackend.handle_worker_message` ignores non-`voip` domains by checking the event domain before processing:

```python
if getattr(event, "domain", self.domain) != self.domain:
    return
```

- [ ] **Step 4: Add an explicit domain check to the backend**

At the top of `RustHostBackend.handle_worker_message`:

```python
if getattr(event, "domain", self.domain) != self.domain:
    return
```

Update the fake test events to include `domain="voip"`:

```python
return SimpleNamespace(domain="voip", kind="event", type=message_type, payload=payload)
```

- [ ] **Step 5: Run boot and backend tests**

Run:

```bash
uv run pytest -q tests/backends/test_rust_host_voip.py tests/core/test_bootstrap.py
```

Expected: tests pass.

- [ ] **Step 6: Run repo gates and commit**

Run:

```bash
uv run python scripts/quality.py gate
uv run pytest -q
```

Commit:

```bash
git add yoyopod/core/bootstrap yoyopod/backends/voip/rust_host.py tests
git commit -m "feat(voip): wire rust voip host runtime selection"
```

Expected: Rust VoIP Host is opt-in and conflicts clearly with the old Python sidecar flag.

## Task 7: CI Artifact For Rust VoIP Host

**Files:**
- Modify: `.github/workflows/ci.yml`
- Modify: `skills/yoyopod-rust-artifact/SKILL.md`
- Modify: `docs/hardware/DEPLOYED_PI_DEPENDENCIES.md`

- [ ] **Step 1: Add CI build step**

In `.github/workflows/ci.yml`, extend the Rust job after UI host build:

```yaml
      - name: Build Rust VoIP host
        working-directory: src
        run: |
          set -euo pipefail
          cargo build --release -p yoyopod-voip-host --locked
          mkdir -p crates/voip-host/build
          cp target/release/yoyopod-voip-host crates/voip-host/build/yoyopod-voip-host

      - name: Upload Rust VoIP ARM64 host
        uses: actions/upload-artifact@v4
        with:
          name: yoyopod-voip-host-${{ github.sha }}
          path: src/crates/voip-host/build/yoyopod-voip-host
          if-no-files-found: error
```

Keep the existing UI artifact step unchanged.

- [ ] **Step 2: Update Rust artifact skill**

In `skills/yoyopod-rust-artifact/SKILL.md`, add this section:

````markdown
## Rust VoIP Host Artifact

The Rust VoIP Host artifact is:

```bash
yoyopod-voip-host-<sha>
```

Install it at:

```bash
/opt/yoyopod-dev/checkout/src/crates/voip-host/build/yoyopod-voip-host
```

Do not build `yoyopod-voip-host` on the Raspberry Pi Zero 2W.
````

- [ ] **Step 3: Update deployed dependency note**

In `docs/hardware/DEPLOYED_PI_DEPENDENCIES.md`, add a bullet under native/runtime artifacts:

```markdown
- `src/crates/voip-host/build/yoyopod-voip-host` - Rust VoIP Host calls-only worker, installed from GitHub Actions artifact.
```

- [ ] **Step 4: Run validation and commit**

Run:

```bash
cargo fmt --manifest-path src/Cargo.toml
cargo test --manifest-path src/Cargo.toml --workspace --locked
uv run python scripts/quality.py gate
uv run pytest -q
```

Commit:

```bash
git add .github/workflows/ci.yml skills/yoyopod-rust-artifact/SKILL.md docs/hardware/DEPLOYED_PI_DEPENDENCIES.md
git commit -m "ci: upload rust voip host artifact"
```

Expected: CI will build and upload both UI and VoIP Rust host artifacts.

## Task 8: Hardware Validation

**Files:**
- No production code changes unless validation finds a bug.
- Update PR description with the validation record.

- [ ] **Step 1: Run all local gates before push**

Run:

```bash
cargo fmt --manifest-path src/Cargo.toml
cargo test --manifest-path src/Cargo.toml --workspace --locked
uv run python scripts/quality.py gate
uv run pytest -q
```

Expected: all local checks pass.

- [ ] **Step 2: Push the branch**

Run:

```bash
git push -u origin codex/rust-voip-host
```

Expected: branch is available on GitHub.

- [ ] **Step 3: Wait for the exact CI artifact**

Use:

```bash
gh run list --workflow CI --branch codex/rust-voip-host --json databaseId,headSha,status,conclusion --limit 20
```

Expected: use only a successful run whose `headSha` equals local `git rev-parse HEAD`.

- [ ] **Step 4: Download and install the artifact**

Download:

```bash
mkdir -p .artifacts/rust-voip/<sha>
gh run download <run-id> --name yoyopod-voip-host-<sha> --dir .artifacts/rust-voip/<sha>
chmod +x .artifacts/rust-voip/<sha>/yoyopod-voip-host
```

Install on Pi:

```bash
ssh tifo@rpi-zero "mkdir -p /opt/yoyopod-dev/checkout/src/crates/voip-host/build"
scp .artifacts/rust-voip/<sha>/yoyopod-voip-host tifo@rpi-zero:/opt/yoyopod-dev/checkout/src/crates/voip-host/build/yoyopod-voip-host
ssh tifo@rpi-zero "chmod +x /opt/yoyopod-dev/checkout/src/crates/voip-host/build/yoyopod-voip-host"
```

- [ ] **Step 5: Sync Python checkout without target Rust build**

Run:

```bash
yoyopod remote mode activate dev
yoyopod remote sync --branch codex/rust-voip-host
```

Use `--clean-native` only if the liblinphone C shim or native build inputs changed.

- [ ] **Step 6: Start the dev service with Rust VoIP Host enabled**

On the Pi:

```bash
ssh tifo@rpi-zero "sudo systemctl stop yoyopod-dev.service || true"
ssh tifo@rpi-zero "cd /opt/yoyopod-dev/checkout && YOYOPOD_RUST_VOIP_HOST=1 YOYOPOD_RUST_VOIP_HOST_WORKER=src/crates/voip-host/build/yoyopod-voip-host /opt/yoyopod-dev/venv/bin/python yoyopod.py"
```

Expected startup log:

```text
YOYOPOD_RUST_VOIP_HOST=1 - using Rust VoIP Host backend
VoIP started successfully
```

- [ ] **Step 7: Validate registration and call flow**

Use the existing Pi VoIP validation commands where possible:

```bash
yoyopod pi validate voip
```

Expected:

- Rust host loads `libyoyopod_liblinphone_shim.so`.
- SIP registration reaches `ok`.
- Outgoing dial command reaches Rust.
- Incoming call event reaches Python as `IncomingCallDetected`.
- Answer, reject, hangup, mute, and unmute send worker commands.
- UI snapshots still show call state through the Rust UI Host.

- [ ] **Step 8: Record validation in PR body**

Record:

```text
Rust VoIP Host hardware validation:
- branch:
- commit:
- CI run:
- artifact: yoyopod-voip-host-<sha>
- Pi path: /opt/yoyopod-dev/checkout/src/crates/voip-host/build/yoyopod-voip-host
- registration:
- outgoing call:
- incoming call:
- answer/reject/hangup:
- mute/unmute:
- service shutdown:
```

Expected: reviewer can verify the exact Rust binary tested on hardware.

## Final Verification Before PR Ready

Run locally:

```bash
cargo fmt --manifest-path src/Cargo.toml
cargo test --manifest-path src/Cargo.toml --workspace --locked
uv run python scripts/quality.py gate
uv run pytest -q
```

Check:

```bash
git status --short
```

Expected: clean tree, all gates green, CI artifact validated on `rpi-zero`.
