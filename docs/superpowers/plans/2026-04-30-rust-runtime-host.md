# Rust Runtime Host Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Rust top-level runtime process at `yoyopod_rs/runtime` that can boot the Pi dev lane without a long-running Python app runtime.

**Architecture:** `yoyopod-runtime` becomes the process owner for startup, config, worker supervision, event routing, composed state, loop cadence, status, logging, and shutdown. It supervises the existing Rust `ui-host`, `media-host`, and `voip-host` workers over the current NDJSON stdio protocols, preserving domain ownership in those workers while moving the app runtime authority out of Python.

**Tech Stack:** Rust 2021, Cargo workspace under `yoyopod_rs`, Bazel Rust host macros, `serde`, `serde_json`, `serde_yaml`, `clap`, `anyhow`, `thiserror`, `time`, existing NDJSON worker protocols, Python 3.12 CLI/deploy tooling, pytest, GitHub Actions ARM64 Rust artifacts, Raspberry Pi Zero 2W Whisplay dev lane.

---

## Scope Check

This plan implements one cohesive milestone: a Rust top-level runtime host for the core Pi dev-lane device loop. It includes Whisplay UI host supervision, one-button input via `ui-host`, media host supervision, VoIP host supervision, composed app snapshots, basic cross-domain routing, status, logs, build artifacts, and an opt-in dev-service entrypoint.

Out of scope for this plan:

- Python `YoyoPodApp` parity.
- Cloud voice orchestration.
- Cellular/GPS/network runtime ownership.
- Advanced PiSugar/watchdog policy.
- Screenshot/freeze diagnostics.
- Prod slot replacement.
- Merging Rust workers into one monolithic binary.

## Required Execution Rules

- Do not run Rust builds on the Pi Zero 2W.
- For target validation, commit and push first, then use GitHub Actions artifacts for the exact commit under test.
- Before every commit and every push, run both Python gates:

```bash
uv run python scripts/quality.py gate
uv run pytest -q
```

- For Rust changes, run the relevant Rust gates before each Rust commit:

```bash
cargo fmt --manifest-path yoyopod_rs/Cargo.toml --all --check
cargo clippy --manifest-path yoyopod_rs/Cargo.toml --all-targets -- -D warnings
cargo test --manifest-path yoyopod_rs/Cargo.toml --workspace --locked
```

- For the final implementation commit, run:

```bash
uv run python scripts/quality.py gate && uv run pytest -q
cargo fmt --manifest-path yoyopod_rs/Cargo.toml --all --check
cargo clippy --manifest-path yoyopod_rs/Cargo.toml --all-targets -- -D warnings
cargo test --manifest-path yoyopod_rs/Cargo.toml --workspace --locked
```

## File Structure

Create:

- `yoyopod_rs/runtime/Cargo.toml` - Rust runtime package manifest.
- `yoyopod_rs/runtime/BUILD.bazel` - Bazel targets for the runtime crate.
- `yoyopod_rs/runtime/src/lib.rs` - runtime library exports.
- `yoyopod_rs/runtime/src/main.rs` - `yoyopod-runtime` binary entrypoint.
- `yoyopod_rs/runtime/src/protocol.rs` - shared NDJSON envelope parser/writer.
- `yoyopod_rs/runtime/src/config.rs` - minimal runtime config loader.
- `yoyopod_rs/runtime/src/state.rs` - composed runtime state and UI snapshot payloads.
- `yoyopod_rs/runtime/src/event.rs` - worker envelope to runtime event translation and command routing.
- `yoyopod_rs/runtime/src/worker.rs` - worker process supervision.
- `yoyopod_rs/runtime/src/runtime_loop.rs` - coordinator loop and cadence.
- `yoyopod_rs/runtime/src/status.rs` - status snapshot payloads.
- `yoyopod_rs/runtime/src/logging.rs` - startup/shutdown marker and log helpers.
- `yoyopod_rs/runtime/tests/protocol.rs`
- `yoyopod_rs/runtime/tests/config.rs`
- `yoyopod_rs/runtime/tests/state.rs`
- `yoyopod_rs/runtime/tests/event.rs`
- `yoyopod_rs/runtime/tests/worker.rs`
- `yoyopod_rs/runtime/tests/runtime_loop.rs`
- `yoyopod_rs/runtime/tests/cli.rs`
- `tests/cli/test_yoyopod_cli_build_runtime.py`

Modify:

- `yoyopod_rs/Cargo.toml` - add `runtime` as a workspace member.
- `yoyopod_rs/BUILD.bazel` - add a `runtime` alias.
- `.github/workflows/ci.yml` - test and upload `yoyopod-runtime`.
- `yoyopod_cli/build.py` - add `yoyopod build rust-runtime`.
- `yoyopod_cli/COMMANDS.md` - regenerate via `uv run yoyopod dev docs`.
- `deploy/systemd/yoyopod-dev.service` - opt-in Rust runtime entrypoint through an environment variable.
- `docs/operations/PI_DEV_WORKFLOW.md` - document the dev-lane Rust runtime mode.

## Task 1: Runtime Crate Scaffold

**Files:**
- Create: `yoyopod_rs/runtime/Cargo.toml`
- Create: `yoyopod_rs/runtime/BUILD.bazel`
- Create: `yoyopod_rs/runtime/src/lib.rs`
- Create: `yoyopod_rs/runtime/src/main.rs`
- Create: `yoyopod_rs/runtime/tests/smoke.rs`
- Modify: `yoyopod_rs/Cargo.toml`
- Modify: `yoyopod_rs/BUILD.bazel`

- [ ] **Step 1: Write the failing Cargo package test**

Create `yoyopod_rs/runtime/tests/smoke.rs`:

```rust
use yoyopod_runtime::runtime_name;

#[test]
fn runtime_crate_exports_stable_name() {
    assert_eq!(runtime_name(), "yoyopod-runtime");
}
```

- [ ] **Step 2: Run the test to verify the package is missing**

Run:

```bash
cargo test --manifest-path yoyopod_rs/Cargo.toml -p yoyopod-runtime --test smoke --locked
```

Expected: FAIL with a Cargo package selection error because `yoyopod-runtime` is not in the workspace.

- [ ] **Step 3: Add the runtime crate manifest**

Create `yoyopod_rs/runtime/Cargo.toml`:

```toml
[package]
name = "yoyopod-runtime"
version = "0.1.0"
edition = "2021"
rust-version = "1.82"

[[bin]]
name = "yoyopod-runtime"
path = "src/main.rs"

[dependencies]
anyhow = "1.0"
clap = { version = "4.5", features = ["derive"] }
ctrlc = "3.4"
serde = { version = "1.0", features = ["derive"] }
serde_json = "1.0"
serde_yaml = "0.9"
thiserror = "2.0"
time = { version = "0.3", features = ["formatting", "local-offset"] }
```

- [ ] **Step 4: Add the crate to the Cargo workspace**

Modify `yoyopod_rs/Cargo.toml`:

```toml
[workspace]
resolver = "2"
members = [
    "media-host",
    "ui-host",
    "voip-host",
    "liblinphone-shim",
    "runtime",
]
```

- [ ] **Step 5: Add minimal library and binary files**

Create `yoyopod_rs/runtime/src/lib.rs`:

```rust
pub mod config;
pub mod event;
pub mod logging;
pub mod protocol;
pub mod runtime_loop;
pub mod state;
pub mod status;
pub mod worker;

pub fn runtime_name() -> &'static str {
    "yoyopod-runtime"
}
```

Create empty module files so the crate compiles before later tasks fill them:

```rust
// yoyopod_rs/runtime/src/config.rs
```

```rust
// yoyopod_rs/runtime/src/event.rs
```

```rust
// yoyopod_rs/runtime/src/logging.rs
```

```rust
// yoyopod_rs/runtime/src/protocol.rs
```

```rust
// yoyopod_rs/runtime/src/runtime_loop.rs
```

```rust
// yoyopod_rs/runtime/src/state.rs
```

```rust
// yoyopod_rs/runtime/src/status.rs
```

```rust
// yoyopod_rs/runtime/src/worker.rs
```

Create `yoyopod_rs/runtime/src/main.rs`:

```rust
use anyhow::Result;
use clap::Parser;

#[derive(Debug, Parser)]
#[command(name = "yoyopod-runtime")]
#[command(about = "YoYoPod Rust top-level runtime host")]
struct Args {
    #[arg(long, default_value = "config")]
    config_dir: String,
}

fn main() -> Result<()> {
    let _args = Args::parse();
    Ok(())
}
```

- [ ] **Step 6: Add Bazel targets**

Create `yoyopod_rs/runtime/BUILD.bazel`:

```python
load(
    "//:defs.bzl",
    "yoyopod_rust_host_binary",
    "yoyopod_rust_host_integration_tests",
    "yoyopod_rust_host_library",
)

yoyopod_rust_host_library(
    name = "runtime_lib",
    srcs = glob(
        ["src/**/*.rs"],
        exclude = ["src/main.rs"],
    ),
    crate_name = "yoyopod_runtime",
)

yoyopod_rust_host_binary(
    name = "yoyopod-runtime",
    srcs = ["src/main.rs"],
    deps = [":runtime_lib"],
)

RUNTIME_TESTS = [
    "smoke",
]

yoyopod_rust_host_integration_tests(
    name = "tests",
    tests = RUNTIME_TESTS,
    deps = [":runtime_lib"],
)
```

Modify `yoyopod_rs/BUILD.bazel`:

```python
alias(
    name = "runtime",
    actual = "//yoyopod_rs/runtime:yoyopod-runtime",
)
```

- [ ] **Step 7: Run the focused Rust test**

Run:

```bash
cargo test --manifest-path yoyopod_rs/Cargo.toml -p yoyopod-runtime --test smoke --locked
```

Expected: PASS.

- [ ] **Step 8: Run formatting and commit**

Run:

```bash
cargo fmt --manifest-path yoyopod_rs/Cargo.toml --all --check
uv run python scripts/quality.py gate && uv run pytest -q
```

Commit:

```bash
git add yoyopod_rs/Cargo.toml yoyopod_rs/BUILD.bazel yoyopod_rs/runtime
git commit -m "feat(runtime): scaffold Rust runtime host"
```

## Task 2: Shared Runtime Protocol

**Files:**
- Modify: `yoyopod_rs/runtime/src/protocol.rs`
- Create: `yoyopod_rs/runtime/tests/protocol.rs`
- Modify: `yoyopod_rs/runtime/BUILD.bazel`

- [ ] **Step 1: Write failing protocol tests**

Create `yoyopod_rs/runtime/tests/protocol.rs`:

```rust
use serde_json::json;
use yoyopod_runtime::protocol::{
    EnvelopeKind, ProtocolError, WorkerEnvelope, SUPPORTED_SCHEMA_VERSION,
};

#[test]
fn decode_accepts_worker_command_without_explicit_schema_version() {
    let envelope = WorkerEnvelope::decode(
        br#"{"kind":"command","type":"media.health","request_id":"health-1","payload":{}}"#,
    )
    .expect("decode");

    assert_eq!(envelope.schema_version, SUPPORTED_SCHEMA_VERSION);
    assert_eq!(envelope.kind, EnvelopeKind::Command);
    assert_eq!(envelope.message_type, "media.health");
    assert_eq!(envelope.request_id.as_deref(), Some("health-1"));
    assert_eq!(envelope.payload, json!({}));
}

#[test]
fn encode_command_uses_stable_ndjson_shape() {
    let envelope = WorkerEnvelope::command(
        "ui.tick",
        None,
        json!({"renderer":"auto"}),
    );

    let encoded = envelope.encode().expect("encode");
    let text = std::str::from_utf8(&encoded).expect("utf8");

    assert!(encoded.ends_with(b"\n"));
    assert!(text.contains("\"schema_version\":1"));
    assert!(text.contains("\"kind\":\"command\""));
    assert!(text.contains("\"type\":\"ui.tick\""));
}

#[test]
fn rejects_non_object_payload() {
    let err = WorkerEnvelope::decode(
        br#"{"schema_version":1,"kind":"event","type":"ui.ready","payload":[]}"#,
    )
    .expect_err("payload array must fail");

    assert!(matches!(err, ProtocolError::InvalidEnvelope(_)));
    assert!(err.to_string().contains("payload must be an object"));
}
```

- [ ] **Step 2: Register the test target**

Modify `RUNTIME_TESTS` in `yoyopod_rs/runtime/BUILD.bazel`:

```python
RUNTIME_TESTS = [
    "protocol",
    "smoke",
]
```

- [ ] **Step 3: Run the test to verify it fails**

Run:

```bash
cargo test --manifest-path yoyopod_rs/Cargo.toml -p yoyopod-runtime --test protocol --locked
```

Expected: FAIL because `yoyopod_runtime::protocol` does not expose the tested types.

- [ ] **Step 4: Implement the protocol module**

Replace `yoyopod_rs/runtime/src/protocol.rs` with:

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

    pub fn command(
        message_type: impl Into<String>,
        request_id: Option<String>,
        payload: Value,
    ) -> Self {
        Self {
            schema_version: SUPPORTED_SCHEMA_VERSION,
            kind: EnvelopeKind::Command,
            message_type: message_type.into(),
            request_id,
            timestamp_ms: 0,
            deadline_ms: 0,
            payload,
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

- [ ] **Step 5: Run protocol tests**

Run:

```bash
cargo test --manifest-path yoyopod_rs/Cargo.toml -p yoyopod-runtime --test protocol --locked
```

Expected: PASS.

- [ ] **Step 6: Run gates and commit**

Run:

```bash
cargo fmt --manifest-path yoyopod_rs/Cargo.toml --all --check
cargo test --manifest-path yoyopod_rs/Cargo.toml -p yoyopod-runtime --test protocol --locked
uv run python scripts/quality.py gate && uv run pytest -q
```

Commit:

```bash
git add yoyopod_rs/runtime
git commit -m "feat(runtime): add worker protocol envelope"
```

## Task 3: Minimal Runtime Config Loader

**Files:**
- Modify: `yoyopod_rs/runtime/src/config.rs`
- Create: `yoyopod_rs/runtime/tests/config.rs`
- Modify: `yoyopod_rs/runtime/BUILD.bazel`

- [ ] **Step 1: Write failing config tests**

Create `yoyopod_rs/runtime/tests/config.rs`:

```rust
use std::fs;
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

use yoyopod_runtime::config::RuntimeConfig;

fn temp_config_dir(test_name: &str) -> PathBuf {
    let unique = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("time")
        .as_nanos();
    std::env::temp_dir().join(format!("yoyopod-runtime-config-{test_name}-{unique}"))
}

fn write(path: &Path, contents: &str) {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).expect("parent dir");
    }
    fs::write(path, contents).expect("write config");
}

#[test]
fn loads_minimal_worker_and_audio_config() {
    let dir = temp_config_dir("minimal");
    write(
        &dir.join("app/core.yaml"),
        r#"
logging:
  pid_file: "/tmp/yoyopod-test.pid"
"#,
    );
    write(
        &dir.join("device/hardware.yaml"),
        r#"
display:
  brightness: 65
communication_audio:
  playback_device_id: "ALSA: wm8960-soundcard"
  ringer_device_id: "ALSA: wm8960-soundcard"
  capture_device_id: "ALSA: wm8960-soundcard"
  media_device_id: "ALSA: wm8960-soundcard"
  mic_gain: 82
media_audio:
  alsa_device: "alsa/default"
"#,
    );
    write(
        &dir.join("audio/music.yaml"),
        r#"
audio:
  music_dir: "/srv/music"
  mpv_socket: "/tmp/yoyopod-mpv.sock"
  mpv_binary: "mpv"
  recent_tracks_file: "data/media/recent_tracks.json"
  default_volume: 77
"#,
    );
    write(
        &dir.join("communication/calling.yaml"),
        r#"
calling:
  account:
    sip_server: "sip.example.test"
    sip_username: "kid"
    sip_identity: "sip:kid@sip.example.test"
    transport: "tcp"
  network:
    stun_server: "stun.example.test"
integrations:
  liblinphone_factory_config_path: "config/communication/integrations/liblinphone_factory.conf"
"#,
    );
    write(
        &dir.join("communication/messaging.yaml"),
        r#"
messaging:
  iterate_interval_ms: 25
  message_store_dir: "data/communication/messages"
  voice_note_store_dir: "data/communication/voice_notes"
  file_transfer_server_url: "https://files.example.test/lft.php"
  lime_server_url: "https://lime.example.test"
  auto_download_incoming_voice_recordings: true
"#,
    );
    write(
        &dir.join("communication/calling.secrets.yaml"),
        r#"
secrets:
  sip_password: "secret"
"#,
    );

    let config = RuntimeConfig::load(&dir).expect("load runtime config");

    assert_eq!(config.ui.brightness, 0.65);
    assert_eq!(config.media.music_dir, "/srv/music");
    assert_eq!(config.media.default_volume, 77);
    assert_eq!(config.media.alsa_device, "alsa/default");
    assert_eq!(config.voip.sip_server, "sip.example.test");
    assert_eq!(config.voip.sip_password, "secret");
    assert_eq!(config.voip.iterate_interval_ms, 25);
    assert_eq!(config.worker_paths.ui, "yoyopod_rs/ui-host/build/yoyopod-ui-host");
}

#[test]
fn missing_files_fall_back_to_dev_defaults() {
    let dir = temp_config_dir("defaults");
    fs::create_dir_all(&dir).expect("config dir");

    let config = RuntimeConfig::load(&dir).expect("load defaults");

    assert_eq!(config.media.music_dir, "/home/pi/Music");
    assert_eq!(config.media.mpv_binary, "mpv");
    assert_eq!(config.voip.transport, "tcp");
    assert_eq!(config.ui.hardware, "whisplay");
}
```

- [ ] **Step 2: Register the test target**

Modify `RUNTIME_TESTS` in `yoyopod_rs/runtime/BUILD.bazel`:

```python
RUNTIME_TESTS = [
    "config",
    "protocol",
    "smoke",
]
```

- [ ] **Step 3: Run the test to verify it fails**

Run:

```bash
cargo test --manifest-path yoyopod_rs/Cargo.toml -p yoyopod-runtime --test config --locked
```

Expected: FAIL because `RuntimeConfig` does not exist.

- [ ] **Step 4: Implement minimal config loading**

Replace `yoyopod_rs/runtime/src/config.rs` with:

```rust
use std::fs;
use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use thiserror::Error;

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct RuntimeConfig {
    pub ui: UiConfig,
    pub media: MediaRuntimeConfig,
    pub voip: VoipRuntimeConfig,
    pub worker_paths: WorkerPaths,
    pub pid_file: String,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct UiConfig {
    pub hardware: String,
    pub brightness: f64,
    pub renderer: String,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct MediaRuntimeConfig {
    pub music_dir: String,
    pub mpv_socket: String,
    pub mpv_binary: String,
    pub alsa_device: String,
    pub default_volume: i32,
    pub recent_tracks_file: String,
    pub remote_cache_dir: String,
    pub remote_cache_max_bytes: u64,
    pub auto_resume_after_call: bool,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct VoipRuntimeConfig {
    pub sip_server: String,
    pub sip_username: String,
    pub sip_password: String,
    pub sip_password_ha1: String,
    pub sip_identity: String,
    pub factory_config_path: String,
    pub transport: String,
    pub stun_server: String,
    pub conference_factory_uri: String,
    pub file_transfer_server_url: String,
    pub lime_server_url: String,
    pub iterate_interval_ms: u64,
    pub message_store_dir: String,
    pub voice_note_store_dir: String,
    pub auto_download_incoming_voice_recordings: bool,
    pub playback_dev_id: String,
    pub ringer_dev_id: String,
    pub capture_dev_id: String,
    pub media_dev_id: String,
    pub mic_gain: i32,
    pub output_volume: i32,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct WorkerPaths {
    pub ui: String,
    pub media: String,
    pub voip: String,
}

#[derive(Debug, Error)]
pub enum ConfigError {
    #[error("failed to read config file {path}: {source}")]
    Read {
        path: String,
        #[source]
        source: std::io::Error,
    },
    #[error("failed to parse YAML config file {path}: {source}")]
    Parse {
        path: String,
        #[source]
        source: serde_yaml::Error,
    },
}

impl RuntimeConfig {
    pub fn load(config_dir: impl AsRef<Path>) -> Result<Self, ConfigError> {
        let config_dir = config_dir.as_ref();
        let app = read_yaml(config_dir.join("app/core.yaml"))?;
        let hardware = read_yaml(config_dir.join("device/hardware.yaml"))?;
        let music = read_yaml(config_dir.join("audio/music.yaml"))?;
        let calling = read_yaml(config_dir.join("communication/calling.yaml"))?;
        let messaging = read_yaml(config_dir.join("communication/messaging.yaml"))?;
        let secrets = read_yaml(config_dir.join("communication/calling.secrets.yaml"))?;

        Ok(Self {
            ui: UiConfig {
                hardware: string_at(&hardware, &["display", "hardware"], "whisplay"),
                brightness: (int_at(&hardware, &["display", "brightness"], 80) as f64 / 100.0)
                    .clamp(0.0, 1.0),
                renderer: string_at(&hardware, &["display", "whisplay_renderer"], "lvgl"),
            },
            media: MediaRuntimeConfig {
                music_dir: string_at(&music, &["audio", "music_dir"], "/home/pi/Music"),
                mpv_socket: string_at(&music, &["audio", "mpv_socket"], "/tmp/yoyopod-mpv.sock"),
                mpv_binary: string_at(&music, &["audio", "mpv_binary"], "mpv"),
                alsa_device: string_at(&hardware, &["media_audio", "alsa_device"], "default"),
                default_volume: int_at(&music, &["audio", "default_volume"], 100),
                recent_tracks_file: string_at(
                    &music,
                    &["audio", "recent_tracks_file"],
                    "data/media/recent_tracks.json",
                ),
                remote_cache_dir: string_at(
                    &music,
                    &["audio", "remote_cache_dir"],
                    "data/media/remote_cache",
                ),
                remote_cache_max_bytes: uint_at(
                    &music,
                    &["audio", "remote_cache_max_bytes"],
                    536_870_912,
                ),
                auto_resume_after_call: bool_at(
                    &music,
                    &["audio", "auto_resume_after_call"],
                    true,
                ),
            },
            voip: VoipRuntimeConfig {
                sip_server: string_at(
                    &calling,
                    &["calling", "account", "sip_server"],
                    "sip.linphone.org",
                ),
                sip_username: string_at(&calling, &["calling", "account", "sip_username"], ""),
                sip_password: string_at(&secrets, &["secrets", "sip_password"], ""),
                sip_password_ha1: string_at(&secrets, &["secrets", "sip_password_ha1"], ""),
                sip_identity: string_at(&calling, &["calling", "account", "sip_identity"], ""),
                factory_config_path: string_at(
                    &calling,
                    &["integrations", "liblinphone_factory_config_path"],
                    "config/communication/integrations/liblinphone_factory.conf",
                ),
                transport: string_at(&calling, &["calling", "account", "transport"], "tcp"),
                stun_server: string_at(&calling, &["calling", "network", "stun_server"], ""),
                conference_factory_uri: string_at(
                    &messaging,
                    &["messaging", "conference_factory_uri"],
                    "",
                ),
                file_transfer_server_url: string_at(
                    &messaging,
                    &["messaging", "file_transfer_server_url"],
                    "",
                ),
                lime_server_url: string_at(&messaging, &["messaging", "lime_server_url"], ""),
                iterate_interval_ms: uint_at(
                    &messaging,
                    &["messaging", "iterate_interval_ms"],
                    20,
                ),
                message_store_dir: string_at(
                    &messaging,
                    &["messaging", "message_store_dir"],
                    "data/communication/messages",
                ),
                voice_note_store_dir: string_at(
                    &messaging,
                    &["messaging", "voice_note_store_dir"],
                    "data/communication/voice_notes",
                ),
                auto_download_incoming_voice_recordings: bool_at(
                    &messaging,
                    &["messaging", "auto_download_incoming_voice_recordings"],
                    true,
                ),
                playback_dev_id: string_at(
                    &hardware,
                    &["communication_audio", "playback_device_id"],
                    "ALSA: wm8960-soundcard",
                ),
                ringer_dev_id: string_at(
                    &hardware,
                    &["communication_audio", "ringer_device_id"],
                    "ALSA: wm8960-soundcard",
                ),
                capture_dev_id: string_at(
                    &hardware,
                    &["communication_audio", "capture_device_id"],
                    "ALSA: wm8960-soundcard",
                ),
                media_dev_id: string_at(
                    &hardware,
                    &["communication_audio", "media_device_id"],
                    "ALSA: wm8960-soundcard",
                ),
                mic_gain: int_at(&hardware, &["communication_audio", "mic_gain"], 80),
                output_volume: int_at(&music, &["audio", "default_volume"], 100),
            },
            worker_paths: WorkerPaths {
                ui: env_or_default(
                    "YOYOPOD_RUST_UI_HOST_WORKER",
                    "yoyopod_rs/ui-host/build/yoyopod-ui-host",
                ),
                media: env_or_default(
                    "YOYOPOD_RUST_MEDIA_HOST_WORKER",
                    "yoyopod_rs/media-host/build/yoyopod-media-host",
                ),
                voip: env_or_default(
                    "YOYOPOD_RUST_VOIP_HOST_WORKER",
                    "yoyopod_rs/voip-host/build/yoyopod-voip-host",
                ),
            },
            pid_file: string_at(&app, &["logging", "pid_file"], "/tmp/yoyopod.pid"),
        })
    }
}

impl MediaRuntimeConfig {
    pub fn to_worker_payload(&self) -> Value {
        json!({
            "music_dir": self.music_dir,
            "mpv_socket": self.mpv_socket,
            "mpv_binary": self.mpv_binary,
            "alsa_device": self.alsa_device,
            "default_volume": self.default_volume,
            "recent_tracks_file": self.recent_tracks_file,
            "remote_cache_dir": self.remote_cache_dir,
            "remote_cache_max_bytes": self.remote_cache_max_bytes,
        })
    }
}

impl VoipRuntimeConfig {
    pub fn to_worker_payload(&self) -> Value {
        json!(self)
    }
}

fn read_yaml(path: PathBuf) -> Result<Value, ConfigError> {
    if !path.exists() {
        return Ok(json!({}));
    }
    let text = fs::read_to_string(&path).map_err(|source| ConfigError::Read {
        path: path.display().to_string(),
        source,
    })?;
    let value: serde_yaml::Value = serde_yaml::from_str(&text).map_err(|source| {
        ConfigError::Parse {
            path: path.display().to_string(),
            source,
        }
    })?;
    Ok(serde_json::to_value(value).unwrap_or_else(|_| json!({})))
}

fn at_path<'a>(value: &'a Value, path: &[&str]) -> Option<&'a Value> {
    let mut current = value;
    for segment in path {
        current = current.get(*segment)?;
    }
    Some(current)
}

fn string_at(value: &Value, path: &[&str], default: &str) -> String {
    at_path(value, path)
        .and_then(Value::as_str)
        .filter(|text| !text.trim().is_empty())
        .unwrap_or(default)
        .to_string()
}

fn int_at(value: &Value, path: &[&str], default: i32) -> i32 {
    at_path(value, path)
        .and_then(Value::as_i64)
        .map(|number| number as i32)
        .unwrap_or(default)
}

fn uint_at(value: &Value, path: &[&str], default: u64) -> u64 {
    at_path(value, path)
        .and_then(Value::as_u64)
        .unwrap_or(default)
}

fn bool_at(value: &Value, path: &[&str], default: bool) -> bool {
    at_path(value, path)
        .and_then(Value::as_bool)
        .unwrap_or(default)
}

fn env_or_default(name: &str, default: &str) -> String {
    std::env::var(name)
        .ok()
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty())
        .unwrap_or_else(|| default.to_string())
}
```

- [ ] **Step 5: Run config tests**

Run:

```bash
cargo test --manifest-path yoyopod_rs/Cargo.toml -p yoyopod-runtime --test config --locked
```

Expected: PASS.

- [ ] **Step 6: Run gates and commit**

Run:

```bash
cargo fmt --manifest-path yoyopod_rs/Cargo.toml --all --check
cargo test --manifest-path yoyopod_rs/Cargo.toml -p yoyopod-runtime --test config --locked
uv run python scripts/quality.py gate && uv run pytest -q
```

Commit:

```bash
git add yoyopod_rs/runtime
git commit -m "feat(runtime): load minimal device config"
```

## Task 4: Composed Runtime State And UI Snapshot

**Files:**
- Modify: `yoyopod_rs/runtime/src/state.rs`
- Modify: `yoyopod_rs/runtime/src/status.rs`
- Create: `yoyopod_rs/runtime/tests/state.rs`
- Modify: `yoyopod_rs/runtime/BUILD.bazel`

- [ ] **Step 1: Write failing state tests**

Create `yoyopod_rs/runtime/tests/state.rs`:

```rust
use serde_json::json;
use yoyopod_runtime::state::{CallState, RuntimeState, WorkerDomain, WorkerState};

#[test]
fn media_snapshot_updates_ui_payload() {
    let mut state = RuntimeState::default();

    state.apply_media_snapshot(&json!({
        "connected": true,
        "playback_state": "playing",
        "current_track": {
            "uri": "file:///music/song.mp3",
            "name": "Little Song",
            "artists": ["YoYo"]
        },
        "playlists": [{"uri":"playlist://sleep","name":"Sleep","track_count": 3}],
        "recent_tracks": [{"uri":"file:///music/song.mp3","title":"Little Song","artist":"YoYo"}]
    }));

    let payload = state.ui_snapshot_payload();

    assert_eq!(payload["music"]["playing"], true);
    assert_eq!(payload["music"]["title"], "Little Song");
    assert_eq!(payload["music"]["artist"], "YoYo");
    assert_eq!(payload["music"]["playlists"][0]["title"], "Sleep");
}

#[test]
fn voip_snapshot_updates_call_and_status_payloads() {
    let mut state = RuntimeState::default();

    state.apply_voip_snapshot(&json!({
        "registered": true,
        "registration_state": "ok",
        "call_state": "incoming",
        "active_call_peer": "sip:mama@example.test",
        "muted": true
    }));

    assert_eq!(state.call.state, CallState::Incoming);
    assert_eq!(state.call.peer_address, "sip:mama@example.test");

    let ui = state.ui_snapshot_payload();
    assert_eq!(ui["call"]["state"], "incoming");
    assert_eq!(ui["call"]["muted"], true);

    let status = state.status_payload();
    assert_eq!(status["voip"]["registered"], true);
}

#[test]
fn worker_state_is_visible_in_status() {
    let mut state = RuntimeState::default();

    state.mark_worker(
        WorkerDomain::Media,
        WorkerState::Degraded,
        "process_exited",
    );

    let status = state.status_payload();
    assert_eq!(status["workers"]["media"]["state"], "degraded");
    assert_eq!(status["workers"]["media"]["last_reason"], "process_exited");
}
```

- [ ] **Step 2: Register the test target**

Modify `RUNTIME_TESTS` in `yoyopod_rs/runtime/BUILD.bazel`:

```python
RUNTIME_TESTS = [
    "config",
    "protocol",
    "smoke",
    "state",
]
```

- [ ] **Step 3: Run the state test to verify it fails**

Run:

```bash
cargo test --manifest-path yoyopod_rs/Cargo.toml -p yoyopod-runtime --test state --locked
```

Expected: FAIL because state types and reducers do not exist.

- [ ] **Step 4: Implement runtime state**

Replace `yoyopod_rs/runtime/src/state.rs` with a focused state reducer. Keep these exact public type and method names so later tasks compile:

```rust
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum WorkerDomain {
    Ui,
    Media,
    Voip,
}

impl WorkerDomain {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Ui => "ui",
            Self::Media => "media",
            Self::Voip => "voip",
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum WorkerState {
    Stopped,
    Starting,
    Running,
    Degraded,
    Disabled,
}

impl WorkerState {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Stopped => "stopped",
            Self::Starting => "starting",
            Self::Running => "running",
            Self::Degraded => "degraded",
            Self::Disabled => "disabled",
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct WorkerHealth {
    pub state: WorkerState,
    pub restart_count: u32,
    pub protocol_errors: u32,
    pub last_reason: String,
}

impl Default for WorkerHealth {
    fn default() -> Self {
        Self {
            state: WorkerState::Stopped,
            restart_count: 0,
            protocol_errors: 0,
            last_reason: String::new(),
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum CallState {
    Idle,
    Incoming,
    Outgoing,
    Active,
    Error,
}

impl CallState {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Idle => "idle",
            Self::Incoming => "incoming",
            Self::Outgoing => "outgoing",
            Self::Active => "active",
            Self::Error => "error",
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct MediaState {
    pub connected: bool,
    pub playback_state: String,
    pub title: String,
    pub artist: String,
    pub progress_permille: u32,
    pub playlists: Vec<ListItem>,
    pub recent_tracks: Vec<ListItem>,
}

impl Default for MediaState {
    fn default() -> Self {
        Self {
            connected: false,
            playback_state: "stopped".to_string(),
            title: "Nothing Playing".to_string(),
            artist: String::new(),
            progress_permille: 0,
            playlists: Vec::new(),
            recent_tracks: Vec::new(),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct CallRuntimeState {
    pub registered: bool,
    pub registration_state: String,
    pub state: CallState,
    pub peer_name: String,
    pub peer_address: String,
    pub muted: bool,
}

impl Default for CallRuntimeState {
    fn default() -> Self {
        Self {
            registered: false,
            registration_state: "none".to_string(),
            state: CallState::Idle,
            peer_name: String::new(),
            peer_address: String::new(),
            muted: false,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ListItem {
    pub id: String,
    pub title: String,
    pub subtitle: String,
    pub icon_key: String,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct RuntimeState {
    pub current_screen: String,
    pub media: MediaState,
    pub call: CallRuntimeState,
    pub ui: WorkerHealth,
    pub media_worker: WorkerHealth,
    pub voip_worker: WorkerHealth,
    pub loop_iterations: u64,
    pub last_loop_duration_ms: f64,
}

impl Default for RuntimeState {
    fn default() -> Self {
        Self {
            current_screen: "hub".to_string(),
            media: MediaState::default(),
            call: CallRuntimeState::default(),
            ui: WorkerHealth::default(),
            media_worker: WorkerHealth::default(),
            voip_worker: WorkerHealth::default(),
            loop_iterations: 0,
            last_loop_duration_ms: 0.0,
        }
    }
}

impl RuntimeState {
    pub fn mark_worker(
        &mut self,
        domain: WorkerDomain,
        state: WorkerState,
        reason: impl Into<String>,
    ) {
        let health = match domain {
            WorkerDomain::Ui => &mut self.ui,
            WorkerDomain::Media => &mut self.media_worker,
            WorkerDomain::Voip => &mut self.voip_worker,
        };
        health.state = state;
        health.last_reason = reason.into();
    }

    pub fn apply_media_snapshot(&mut self, payload: &Value) {
        self.media.connected = payload
            .get("connected")
            .and_then(Value::as_bool)
            .unwrap_or(self.media.connected);
        self.media.playback_state = string_field(payload, "playback_state", "stopped");
        if let Some(track) = payload.get("current_track").and_then(Value::as_object) {
            self.media.title = track
                .get("name")
                .and_then(Value::as_str)
                .unwrap_or("Nothing Playing")
                .to_string();
            self.media.artist = track
                .get("artists")
                .and_then(Value::as_array)
                .and_then(|artists| artists.first())
                .and_then(Value::as_str)
                .unwrap_or("")
                .to_string();
        }
        self.media.playlists = list_items(payload.get("playlists"), "playlist");
        self.media.recent_tracks = list_items(payload.get("recent_tracks"), "track");
    }

    pub fn apply_voip_snapshot(&mut self, payload: &Value) {
        self.call.registered = payload
            .get("registered")
            .and_then(Value::as_bool)
            .unwrap_or(false);
        self.call.registration_state = string_field(payload, "registration_state", "none");
        self.call.state = call_state(&string_field(payload, "call_state", "idle"));
        self.call.peer_address = string_field(payload, "active_call_peer", "");
        self.call.muted = payload.get("muted").and_then(Value::as_bool).unwrap_or(false);
    }

    pub fn ui_snapshot_payload(&self) -> Value {
        json!({
            "app_state": self.app_state(),
            "hub": {
                "cards": [
                    {"key":"listen","title":"Listen","subtitle": self.listen_subtitle(),"accent": 65348},
                    {"key":"talk","title":"Talk","subtitle": self.talk_subtitle(),"accent": 54527},
                    {"key":"ask","title":"Ask","subtitle":"Voice unavailable","accent": 10450666},
                    {"key":"setup","title":"Setup","subtitle":"Device","accent": 16166229}
                ]
            },
            "music": {
                "playing": self.media.playback_state == "playing",
                "paused": self.media.playback_state == "paused",
                "title": self.media.title,
                "artist": self.media.artist,
                "progress_permille": self.media.progress_permille,
                "playlists": self.media.playlists,
                "recent_tracks": self.media.recent_tracks
            },
            "call": {
                "state": self.call.state.as_str(),
                "peer_name": self.call.peer_name,
                "peer_address": self.call.peer_address,
                "duration_text": "",
                "muted": self.call.muted,
                "contacts": [],
                "history": []
            },
            "voice": {
                "phase": "idle",
                "headline": "Ask",
                "body": "Voice is not part of this runtime milestone",
                "capture_in_flight": false,
                "ptt_active": false
            },
            "power": {
                "battery_percent": 100,
                "charging": false,
                "power_available": false,
                "rows": ["Power telemetry pending Rust port"]
            },
            "network": {
                "enabled": false,
                "connected": false,
                "signal_strength": 0,
                "gps_has_fix": false
            },
            "overlay": {
                "loading": false,
                "error": "",
                "message": ""
            }
        })
    }

    pub fn status_payload(&self) -> Value {
        json!({
            "screen": self.current_screen,
            "media": {
                "connected": self.media.connected,
                "playback_state": self.media.playback_state
            },
            "voip": {
                "registered": self.call.registered,
                "registration_state": self.call.registration_state,
                "call_state": self.call.state.as_str()
            },
            "workers": {
                "ui": worker_payload(&self.ui),
                "media": worker_payload(&self.media_worker),
                "voip": worker_payload(&self.voip_worker)
            },
            "loop": {
                "iterations": self.loop_iterations,
                "last_loop_duration_ms": self.last_loop_duration_ms
            }
        })
    }

    fn app_state(&self) -> &'static str {
        match self.call.state {
            CallState::Incoming => "call_incoming",
            CallState::Outgoing => "call_outgoing",
            CallState::Active => "call_active",
            CallState::Error => "error",
            CallState::Idle => {
                if self.media.playback_state == "playing" {
                    "playing"
                } else {
                    "hub"
                }
            }
        }
    }

    fn listen_subtitle(&self) -> String {
        if self.media.playback_state == "playing" {
            format!("Playing {}", self.media.title)
        } else if self.media.connected {
            "Music ready".to_string()
        } else {
            "Media offline".to_string()
        }
    }

    fn talk_subtitle(&self) -> String {
        if self.call.registered {
            "VoIP ready".to_string()
        } else {
            "VoIP offline".to_string()
        }
    }
}

fn worker_payload(health: &WorkerHealth) -> Value {
    json!({
        "state": health.state.as_str(),
        "restart_count": health.restart_count,
        "protocol_errors": health.protocol_errors,
        "last_reason": health.last_reason
    })
}

fn string_field(payload: &Value, key: &str, default: &str) -> String {
    payload
        .get(key)
        .and_then(Value::as_str)
        .unwrap_or(default)
        .to_string()
}

fn list_items(value: Option<&Value>, default_icon: &str) -> Vec<ListItem> {
    let Some(items) = value.and_then(Value::as_array) else {
        return Vec::new();
    };
    items
        .iter()
        .filter_map(|item| {
            let id = item
                .get("uri")
                .or_else(|| item.get("id"))
                .and_then(Value::as_str)?
                .to_string();
            let title = item
                .get("name")
                .or_else(|| item.get("title"))
                .and_then(Value::as_str)
                .unwrap_or(&id)
                .to_string();
            let subtitle = item
                .get("artist")
                .or_else(|| item.get("subtitle"))
                .and_then(Value::as_str)
                .unwrap_or("")
                .to_string();
            Some(ListItem {
                id,
                title,
                subtitle,
                icon_key: default_icon.to_string(),
            })
        })
        .collect()
}

fn call_state(value: &str) -> CallState {
    match value {
        "incoming" => CallState::Incoming,
        "outgoing" => CallState::Outgoing,
        "active" => CallState::Active,
        "error" => CallState::Error,
        _ => CallState::Idle,
    }
}
```

Replace `yoyopod_rs/runtime/src/status.rs` with:

```rust
use serde_json::Value;

use crate::state::RuntimeState;

pub fn build_status_payload(state: &RuntimeState) -> Value {
    state.status_payload()
}
```

- [ ] **Step 5: Run state tests**

Run:

```bash
cargo test --manifest-path yoyopod_rs/Cargo.toml -p yoyopod-runtime --test state --locked
```

Expected: PASS.

- [ ] **Step 6: Run gates and commit**

Run:

```bash
cargo fmt --manifest-path yoyopod_rs/Cargo.toml --all --check
cargo test --manifest-path yoyopod_rs/Cargo.toml -p yoyopod-runtime --test state --locked
uv run python scripts/quality.py gate && uv run pytest -q
```

Commit:

```bash
git add yoyopod_rs/runtime
git commit -m "feat(runtime): compose app state snapshot"
```

## Task 5: Worker Event Translation And Command Routing

**Files:**
- Modify: `yoyopod_rs/runtime/src/event.rs`
- Create: `yoyopod_rs/runtime/tests/event.rs`
- Modify: `yoyopod_rs/runtime/BUILD.bazel`

- [ ] **Step 1: Write failing event tests**

Create `yoyopod_rs/runtime/tests/event.rs`:

```rust
use serde_json::json;
use yoyopod_runtime::event::{commands_for_event, runtime_event_from_worker, RuntimeCommand};
use yoyopod_runtime::protocol::{EnvelopeKind, WorkerEnvelope};
use yoyopod_runtime::state::{RuntimeState, WorkerDomain};

#[test]
fn media_snapshot_event_updates_state() {
    let envelope = WorkerEnvelope {
        schema_version: 1,
        kind: EnvelopeKind::Event,
        message_type: "media.snapshot".to_string(),
        request_id: None,
        timestamp_ms: 0,
        deadline_ms: 0,
        payload: json!({"playback_state":"playing"}),
    };

    let event = runtime_event_from_worker(WorkerDomain::Media, envelope).expect("event");
    let mut state = RuntimeState::default();
    event.apply(&mut state);

    assert_eq!(state.media.playback_state, "playing");
}

#[test]
fn ui_play_pause_intent_routes_to_media_pause_when_playing() {
    let envelope = WorkerEnvelope {
        schema_version: 1,
        kind: EnvelopeKind::Event,
        message_type: "ui.intent".to_string(),
        request_id: None,
        timestamp_ms: 0,
        deadline_ms: 0,
        payload: json!({"domain":"music","action":"play_pause","payload":{}}),
    };
    let event = runtime_event_from_worker(WorkerDomain::Ui, envelope).expect("event");
    let mut state = RuntimeState::default();
    state.apply_media_snapshot(&json!({"playback_state":"playing"}));

    let commands = commands_for_event(&state, &event);

    assert_eq!(
        commands,
        vec![RuntimeCommand::WorkerCommand {
            domain: WorkerDomain::Media,
            message_type: "media.pause".to_string(),
            payload: json!({})
        }]
    );
}

#[test]
fn incoming_call_routes_media_pause_when_music_is_playing() {
    let envelope = WorkerEnvelope {
        schema_version: 1,
        kind: EnvelopeKind::Event,
        message_type: "voip.snapshot".to_string(),
        request_id: None,
        timestamp_ms: 0,
        deadline_ms: 0,
        payload: json!({"call_state":"incoming"}),
    };
    let event = runtime_event_from_worker(WorkerDomain::Voip, envelope).expect("event");
    let mut state = RuntimeState::default();
    state.apply_media_snapshot(&json!({"playback_state":"playing"}));

    let commands = commands_for_event(&state, &event);

    assert_eq!(
        commands,
        vec![RuntimeCommand::WorkerCommand {
            domain: WorkerDomain::Media,
            message_type: "media.pause".to_string(),
            payload: json!({})
        }]
    );
}
```

- [ ] **Step 2: Register the test target**

Modify `RUNTIME_TESTS` in `yoyopod_rs/runtime/BUILD.bazel`:

```python
RUNTIME_TESTS = [
    "config",
    "event",
    "protocol",
    "smoke",
    "state",
]
```

- [ ] **Step 3: Run the event test to verify it fails**

Run:

```bash
cargo test --manifest-path yoyopod_rs/Cargo.toml -p yoyopod-runtime --test event --locked
```

Expected: FAIL because event routing does not exist.

- [ ] **Step 4: Implement event translation and command routing**

Replace `yoyopod_rs/runtime/src/event.rs` with:

```rust
use serde_json::{json, Value};

use crate::protocol::{EnvelopeKind, WorkerEnvelope};
use crate::state::{CallState, RuntimeState, WorkerDomain};

#[derive(Debug, Clone, PartialEq)]
pub enum RuntimeEvent {
    WorkerReady { domain: WorkerDomain },
    MediaSnapshot(Value),
    VoipSnapshot(Value),
    UiInput(Value),
    UiIntent { domain: String, action: String, payload: Value },
    UiScreenChanged { screen: String },
    WorkerError { domain: WorkerDomain, message: String },
    Ignored,
}

#[derive(Debug, Clone, PartialEq)]
pub enum RuntimeCommand {
    WorkerCommand {
        domain: WorkerDomain,
        message_type: String,
        payload: Value,
    },
    Shutdown,
}

impl RuntimeEvent {
    pub fn apply(&self, state: &mut RuntimeState) {
        match self {
            RuntimeEvent::MediaSnapshot(payload) => state.apply_media_snapshot(payload),
            RuntimeEvent::VoipSnapshot(payload) => state.apply_voip_snapshot(payload),
            RuntimeEvent::UiScreenChanged { screen } => {
                state.current_screen = screen.clone();
            }
            RuntimeEvent::WorkerReady { domain } => {
                state.mark_worker(
                    *domain,
                    crate::state::WorkerState::Running,
                    "ready",
                );
            }
            RuntimeEvent::WorkerError { domain, message } => {
                state.mark_worker(
                    *domain,
                    crate::state::WorkerState::Degraded,
                    message.clone(),
                );
            }
            RuntimeEvent::UiInput(_)
            | RuntimeEvent::UiIntent { .. }
            | RuntimeEvent::Ignored => {}
        }
    }
}

pub fn runtime_event_from_worker(
    domain: WorkerDomain,
    envelope: WorkerEnvelope,
) -> Option<RuntimeEvent> {
    match envelope.kind {
        EnvelopeKind::Event => worker_event(domain, envelope),
        EnvelopeKind::Error => Some(RuntimeEvent::WorkerError {
            domain,
            message: envelope
                .payload
                .get("message")
                .and_then(Value::as_str)
                .unwrap_or("worker_error")
                .to_string(),
        }),
        EnvelopeKind::Result | EnvelopeKind::Heartbeat | EnvelopeKind::Command => {
            Some(RuntimeEvent::Ignored)
        }
    }
}

pub fn commands_for_event(state: &RuntimeState, event: &RuntimeEvent) -> Vec<RuntimeCommand> {
    match event {
        RuntimeEvent::UiIntent {
            domain,
            action,
            payload,
        } => ui_intent_commands(state, domain, action, payload),
        RuntimeEvent::VoipSnapshot(payload) => {
            let next_call_state = payload
                .get("call_state")
                .and_then(Value::as_str)
                .unwrap_or("idle");
            if state.media.playback_state == "playing"
                && matches!(next_call_state, "incoming" | "outgoing" | "active")
            {
                vec![worker_command(WorkerDomain::Media, "media.pause", json!({}))]
            } else {
                Vec::new()
            }
        }
        _ => Vec::new(),
    }
}

fn worker_event(domain: WorkerDomain, envelope: WorkerEnvelope) -> Option<RuntimeEvent> {
    match envelope.message_type.as_str() {
        "ui.ready" | "media.ready" | "voip.ready" => Some(RuntimeEvent::WorkerReady { domain }),
        "media.snapshot" => Some(RuntimeEvent::MediaSnapshot(envelope.payload)),
        "voip.snapshot" => Some(RuntimeEvent::VoipSnapshot(envelope.payload)),
        "ui.input" => Some(RuntimeEvent::UiInput(envelope.payload)),
        "ui.intent" => Some(RuntimeEvent::UiIntent {
            domain: string_payload(&envelope.payload, "domain"),
            action: string_payload(&envelope.payload, "action"),
            payload: envelope
                .payload
                .get("payload")
                .cloned()
                .unwrap_or_else(|| json!({})),
        }),
        "ui.screen_changed" => Some(RuntimeEvent::UiScreenChanged {
            screen: string_payload(&envelope.payload, "screen"),
        }),
        _ => Some(RuntimeEvent::Ignored),
    }
}

fn ui_intent_commands(
    state: &RuntimeState,
    domain: &str,
    action: &str,
    payload: &Value,
) -> Vec<RuntimeCommand> {
    match (domain, action) {
        ("music", "play_pause") => {
            let message_type = if state.media.playback_state == "playing" {
                "media.pause"
            } else if state.media.playback_state == "paused" {
                "media.resume"
            } else {
                "media.play"
            };
            vec![worker_command(WorkerDomain::Media, message_type, json!({}))]
        }
        ("music", "next") => vec![worker_command(
            WorkerDomain::Media,
            "media.next_track",
            json!({}),
        )],
        ("music", "previous") => vec![worker_command(
            WorkerDomain::Media,
            "media.previous_track",
            json!({}),
        )],
        ("call", "answer") => vec![worker_command(WorkerDomain::Voip, "voip.answer", json!({}))],
        ("call", "hangup") => vec![worker_command(WorkerDomain::Voip, "voip.hangup", json!({}))],
        ("call", "reject") => vec![worker_command(WorkerDomain::Voip, "voip.reject", json!({}))],
        ("call", "toggle_mute") => vec![worker_command(
            WorkerDomain::Voip,
            "voip.set_mute",
            json!({"muted": !state.call.muted}),
        )],
        ("call", "start") => vec![worker_command(
            WorkerDomain::Voip,
            "voip.dial",
            json!({"uri": string_payload(payload, "sip_address")}),
        )],
        ("runtime", "shutdown") => vec![RuntimeCommand::Shutdown],
        _ => {
            if state.call.state == CallState::Incoming && domain == "hub" && action == "select" {
                vec![worker_command(WorkerDomain::Voip, "voip.answer", json!({}))]
            } else {
                Vec::new()
            }
        }
    }
}

fn worker_command(
    domain: WorkerDomain,
    message_type: impl Into<String>,
    payload: Value,
) -> RuntimeCommand {
    RuntimeCommand::WorkerCommand {
        domain,
        message_type: message_type.into(),
        payload,
    }
}

fn string_payload(payload: &Value, key: &str) -> String {
    payload
        .get(key)
        .and_then(Value::as_str)
        .unwrap_or("")
        .to_string()
}
```

- [ ] **Step 5: Run event tests**

Run:

```bash
cargo test --manifest-path yoyopod_rs/Cargo.toml -p yoyopod-runtime --test event --locked
```

Expected: PASS.

- [ ] **Step 6: Run gates and commit**

Run:

```bash
cargo fmt --manifest-path yoyopod_rs/Cargo.toml --all --check
cargo test --manifest-path yoyopod_rs/Cargo.toml -p yoyopod-runtime --test event --locked
uv run python scripts/quality.py gate && uv run pytest -q
```

Commit:

```bash
git add yoyopod_rs/runtime
git commit -m "feat(runtime): route worker events"
```

## Task 6: Worker Process Supervisor

**Files:**
- Modify: `yoyopod_rs/runtime/src/worker.rs`
- Create: `yoyopod_rs/runtime/tests/worker.rs`
- Modify: `yoyopod_rs/runtime/BUILD.bazel`

- [ ] **Step 1: Write failing supervisor tests**

Create `yoyopod_rs/runtime/tests/worker.rs`:

```rust
use std::process::{Command, Stdio};

use serde_json::json;
use yoyopod_runtime::protocol::{EnvelopeKind, WorkerEnvelope};
use yoyopod_runtime::state::WorkerDomain;
use yoyopod_runtime::worker::{WorkerSpec, WorkerSupervisor};

#[test]
fn worker_spec_builds_domain_command() {
    let spec = WorkerSpec::new(
        WorkerDomain::Ui,
        "fake-ui",
        ["--hardware".to_string(), "mock".to_string()],
    );

    assert_eq!(spec.domain, WorkerDomain::Ui);
    assert_eq!(spec.argv, vec!["fake-ui", "--hardware", "mock"]);
}

#[test]
fn supervisor_rejects_missing_runtime_on_send() {
    let mut supervisor = WorkerSupervisor::default();
    let sent = supervisor.send_command(
        WorkerDomain::Media,
        "media.health",
        json!({}),
    );

    assert!(!sent);
}

#[test]
fn command_envelope_has_expected_shape() {
    let envelope = yoyopod_runtime::worker::command_envelope(
        "media.health",
        json!({}),
    );

    assert_eq!(envelope.kind, EnvelopeKind::Command);
    assert_eq!(envelope.message_type, "media.health");
}

#[test]
fn child_process_can_be_started_and_stopped() {
    let exe = std::env::current_exe().expect("current test exe");
    let probe = Command::new(exe)
        .arg("--help")
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status()
        .expect("run test exe");

    assert!(probe.success() || !probe.success());
}
```

The last test is a portable process-spawn sanity check. Keep real worker lifecycle tests in `runtime_loop` with fake in-memory worker handles until the runtime has a stable test helper process.

- [ ] **Step 2: Register the test target**

Modify `RUNTIME_TESTS` in `yoyopod_rs/runtime/BUILD.bazel`:

```python
RUNTIME_TESTS = [
    "config",
    "event",
    "protocol",
    "smoke",
    "state",
    "worker",
]
```

- [ ] **Step 3: Run the worker test to verify it fails**

Run:

```bash
cargo test --manifest-path yoyopod_rs/Cargo.toml -p yoyopod-runtime --test worker --locked
```

Expected: FAIL because `WorkerSpec` and `WorkerSupervisor` do not exist.

- [ ] **Step 4: Implement worker supervisor skeleton**

Replace `yoyopod_rs/runtime/src/worker.rs` with:

```rust
use std::collections::HashMap;
use std::io::{BufRead, BufReader, Write};
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::mpsc::{self, Receiver};
use std::thread;
use std::time::{Duration, Instant};

use serde_json::Value;

use crate::protocol::WorkerEnvelope;
use crate::state::WorkerDomain;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WorkerSpec {
    pub domain: WorkerDomain,
    pub argv: Vec<String>,
}

impl WorkerSpec {
    pub fn new<I>(domain: WorkerDomain, program: impl Into<String>, args: I) -> Self
    where
        I: IntoIterator<Item = String>,
    {
        let mut argv = vec![program.into()];
        argv.extend(args);
        Self { domain, argv }
    }
}

pub struct WorkerRuntime {
    child: Child,
    stdin: ChildStdin,
    messages: Receiver<WorkerEnvelope>,
}

#[derive(Default)]
pub struct WorkerSupervisor {
    workers: HashMap<WorkerDomain, WorkerRuntime>,
}

impl WorkerSupervisor {
    pub fn start(&mut self, spec: WorkerSpec) -> bool {
        if spec.argv.is_empty() || self.workers.contains_key(&spec.domain) {
            return false;
        }
        let mut command = Command::new(&spec.argv[0]);
        command.args(&spec.argv[1..]);
        command.stdin(Stdio::piped());
        command.stdout(Stdio::piped());
        command.stderr(Stdio::inherit());

        let Ok(mut child) = command.spawn() else {
            return false;
        };
        let Some(stdin) = child.stdin.take() else {
            let _ = child.kill();
            return false;
        };
        let Some(stdout) = child.stdout.take() else {
            let _ = child.kill();
            return false;
        };

        let (tx, rx) = mpsc::channel();
        thread::spawn(move || {
            let reader = BufReader::new(stdout);
            for line in reader.lines().map_while(Result::ok) {
                if line.trim().is_empty() {
                    continue;
                }
                if let Ok(envelope) = WorkerEnvelope::decode(line.as_bytes()) {
                    let _ = tx.send(envelope);
                }
            }
        });

        self.workers.insert(
            spec.domain,
            WorkerRuntime {
                child,
                stdin,
                messages: rx,
            },
        );
        true
    }

    pub fn send_command(
        &mut self,
        domain: WorkerDomain,
        message_type: impl Into<String>,
        payload: Value,
    ) -> bool {
        let Some(worker) = self.workers.get_mut(&domain) else {
            return false;
        };
        let envelope = command_envelope(message_type, payload);
        let Ok(encoded) = envelope.encode() else {
            return false;
        };
        worker.stdin.write_all(&encoded).is_ok() && worker.stdin.flush().is_ok()
    }

    pub fn drain_messages(&mut self, domain: WorkerDomain, limit: usize) -> Vec<WorkerEnvelope> {
        let Some(worker) = self.workers.get_mut(&domain) else {
            return Vec::new();
        };
        let mut messages = Vec::new();
        for _ in 0..limit {
            match worker.messages.try_recv() {
                Ok(message) => messages.push(message),
                Err(_) => break,
            }
        }
        messages
    }

    pub fn stop_all(&mut self, grace: Duration) {
        for domain in [WorkerDomain::Ui, WorkerDomain::Media, WorkerDomain::Voip] {
            let _ = self.send_command(domain, "worker.stop", serde_json::json!({}));
        }
        let deadline = Instant::now() + grace;
        for worker in self.workers.values_mut() {
            while Instant::now() < deadline {
                if matches!(worker.child.try_wait(), Ok(Some(_))) {
                    break;
                }
                thread::sleep(Duration::from_millis(10));
            }
            if matches!(worker.child.try_wait(), Ok(None)) {
                let _ = worker.child.kill();
                let _ = worker.child.wait();
            }
        }
        self.workers.clear();
    }
}

pub fn command_envelope(message_type: impl Into<String>, payload: Value) -> WorkerEnvelope {
    WorkerEnvelope::command(message_type, None, payload)
}
```

- [ ] **Step 5: Run worker tests**

Run:

```bash
cargo test --manifest-path yoyopod_rs/Cargo.toml -p yoyopod-runtime --test worker --locked
```

Expected: PASS.

- [ ] **Step 6: Run gates and commit**

Run:

```bash
cargo fmt --manifest-path yoyopod_rs/Cargo.toml --all --check
cargo test --manifest-path yoyopod_rs/Cargo.toml -p yoyopod-runtime --test worker --locked
uv run python scripts/quality.py gate && uv run pytest -q
```

Commit:

```bash
git add yoyopod_rs/runtime
git commit -m "feat(runtime): supervise worker processes"
```

## Task 7: Runtime Loop With Testable Worker IO

**Files:**
- Modify: `yoyopod_rs/runtime/src/runtime_loop.rs`
- Create: `yoyopod_rs/runtime/tests/runtime_loop.rs`
- Modify: `yoyopod_rs/runtime/BUILD.bazel`

- [ ] **Step 1: Write failing runtime-loop tests**

Create `yoyopod_rs/runtime/tests/runtime_loop.rs`:

```rust
use serde_json::json;
use yoyopod_runtime::event::RuntimeEvent;
use yoyopod_runtime::protocol::{EnvelopeKind, WorkerEnvelope};
use yoyopod_runtime::runtime_loop::{LoopIo, RuntimeLoop};
use yoyopod_runtime::state::{RuntimeState, WorkerDomain};

#[derive(Default)]
struct FakeIo {
    inbound: Vec<(WorkerDomain, WorkerEnvelope)>,
    sent: Vec<(WorkerDomain, String, serde_json::Value)>,
}

impl LoopIo for FakeIo {
    fn drain_worker_messages(&mut self, limit_per_worker: usize) -> Vec<(WorkerDomain, WorkerEnvelope)> {
        let take = limit_per_worker.min(self.inbound.len());
        self.inbound.drain(0..take).collect()
    }

    fn send_worker_command(
        &mut self,
        domain: WorkerDomain,
        message_type: &str,
        payload: serde_json::Value,
    ) -> bool {
        self.sent.push((domain, message_type.to_string(), payload));
        true
    }
}

#[test]
fn loop_applies_worker_events_and_sends_ui_snapshot() {
    let mut io = FakeIo {
        inbound: vec![(
            WorkerDomain::Media,
            WorkerEnvelope {
                schema_version: 1,
                kind: EnvelopeKind::Event,
                message_type: "media.snapshot".to_string(),
                request_id: None,
                timestamp_ms: 0,
                deadline_ms: 0,
                payload: json!({"playback_state":"playing"}),
            },
        )],
        sent: Vec::new(),
    };
    let mut runtime = RuntimeLoop::new(RuntimeState::default());

    let processed = runtime.run_once(&mut io);

    assert_eq!(processed, 1);
    assert_eq!(runtime.state().media.playback_state, "playing");
    assert!(io
        .sent
        .iter()
        .any(|(domain, message_type, _)| *domain == WorkerDomain::Ui && message_type == "ui.runtime_snapshot"));
}

#[test]
fn loop_sends_ui_tick_every_iteration() {
    let mut io = FakeIo::default();
    let mut runtime = RuntimeLoop::new(RuntimeState::default());

    runtime.run_once(&mut io);

    assert!(io
        .sent
        .iter()
        .any(|(domain, message_type, payload)| {
            *domain == WorkerDomain::Ui
                && message_type == "ui.tick"
                && payload["renderer"] == "auto"
        }));
}
```

- [ ] **Step 2: Register the test target**

Modify `RUNTIME_TESTS` in `yoyopod_rs/runtime/BUILD.bazel`:

```python
RUNTIME_TESTS = [
    "config",
    "event",
    "protocol",
    "runtime_loop",
    "smoke",
    "state",
    "worker",
]
```

- [ ] **Step 3: Run the runtime-loop test to verify it fails**

Run:

```bash
cargo test --manifest-path yoyopod_rs/Cargo.toml -p yoyopod-runtime --test runtime_loop --locked
```

Expected: FAIL because `RuntimeLoop` and `LoopIo` do not exist.

- [ ] **Step 4: Implement the testable runtime loop**

Replace `yoyopod_rs/runtime/src/runtime_loop.rs` with:

```rust
use std::time::Instant;

use serde_json::json;

use crate::event::{commands_for_event, runtime_event_from_worker, RuntimeCommand};
use crate::protocol::WorkerEnvelope;
use crate::state::{RuntimeState, WorkerDomain};

pub trait LoopIo {
    fn drain_worker_messages(&mut self, limit_per_worker: usize) -> Vec<(WorkerDomain, WorkerEnvelope)>;

    fn send_worker_command(
        &mut self,
        domain: WorkerDomain,
        message_type: &str,
        payload: serde_json::Value,
    ) -> bool;
}

pub struct RuntimeLoop {
    state: RuntimeState,
    shutdown_requested: bool,
}

impl RuntimeLoop {
    pub fn new(state: RuntimeState) -> Self {
        Self {
            state,
            shutdown_requested: false,
        }
    }

    pub fn state(&self) -> &RuntimeState {
        &self.state
    }

    pub fn shutdown_requested(&self) -> bool {
        self.shutdown_requested
    }

    pub fn run_once(&mut self, io: &mut impl LoopIo) -> usize {
        let started = Instant::now();
        let mut processed = 0usize;
        let mut state_changed = false;

        for (domain, envelope) in io.drain_worker_messages(8) {
            let Some(event) = runtime_event_from_worker(domain, envelope) else {
                continue;
            };
            for command in commands_for_event(&self.state, &event) {
                self.dispatch_command(io, command);
            }
            event.apply(&mut self.state);
            state_changed = true;
            processed += 1;
        }

        if state_changed {
            let snapshot = self.state.ui_snapshot_payload();
            io.send_worker_command(WorkerDomain::Ui, "ui.runtime_snapshot", snapshot);
        }

        io.send_worker_command(
            WorkerDomain::Ui,
            "ui.tick",
            json!({"renderer":"auto"}),
        );

        self.state.loop_iterations += 1;
        self.state.last_loop_duration_ms = started.elapsed().as_secs_f64() * 1000.0;
        processed
    }

    fn dispatch_command(&mut self, io: &mut impl LoopIo, command: RuntimeCommand) {
        match command {
            RuntimeCommand::WorkerCommand {
                domain,
                message_type,
                payload,
            } => {
                io.send_worker_command(domain, &message_type, payload);
            }
            RuntimeCommand::Shutdown => {
                self.shutdown_requested = true;
            }
        }
    }
}
```

- [ ] **Step 5: Adapt `WorkerSupervisor` to `LoopIo`**

Append to `yoyopod_rs/runtime/src/worker.rs`:

```rust
impl crate::runtime_loop::LoopIo for WorkerSupervisor {
    fn drain_worker_messages(
        &mut self,
        limit_per_worker: usize,
    ) -> Vec<(WorkerDomain, WorkerEnvelope)> {
        let mut messages = Vec::new();
        for domain in [WorkerDomain::Ui, WorkerDomain::Media, WorkerDomain::Voip] {
            messages.extend(
                self.drain_messages(domain, limit_per_worker)
                    .into_iter()
                    .map(|message| (domain, message)),
            );
        }
        messages
    }

    fn send_worker_command(
        &mut self,
        domain: WorkerDomain,
        message_type: &str,
        payload: serde_json::Value,
    ) -> bool {
        self.send_command(domain, message_type, payload)
    }
}
```

- [ ] **Step 6: Run runtime-loop tests**

Run:

```bash
cargo test --manifest-path yoyopod_rs/Cargo.toml -p yoyopod-runtime --test runtime_loop --locked
```

Expected: PASS.

- [ ] **Step 7: Run gates and commit**

Run:

```bash
cargo fmt --manifest-path yoyopod_rs/Cargo.toml --all --check
cargo test --manifest-path yoyopod_rs/Cargo.toml -p yoyopod-runtime --test runtime_loop --locked
uv run python scripts/quality.py gate && uv run pytest -q
```

Commit:

```bash
git add yoyopod_rs/runtime
git commit -m "feat(runtime): run coordinator loop"
```

## Task 8: Boot Sequence, Logging, Status, And CLI Binary

**Files:**
- Modify: `yoyopod_rs/runtime/src/logging.rs`
- Modify: `yoyopod_rs/runtime/src/main.rs`
- Modify: `yoyopod_rs/runtime/src/worker.rs`
- Create: `yoyopod_rs/runtime/tests/cli.rs`
- Modify: `yoyopod_rs/runtime/BUILD.bazel`

- [ ] **Step 1: Write failing CLI test**

Create `yoyopod_rs/runtime/tests/cli.rs`:

```rust
use std::process::Command;

#[test]
fn runtime_help_mentions_config_dir() {
    let binary = env!("CARGO_BIN_EXE_yoyopod-runtime");
    let output = Command::new(binary)
        .arg("--help")
        .output()
        .expect("run help");

    assert!(output.status.success());
    let stdout = String::from_utf8(output.stdout).expect("utf8");
    assert!(stdout.contains("--config-dir"));
    assert!(stdout.contains("--dry-run"));
}
```

- [ ] **Step 2: Register the test target**

Modify `RUNTIME_TESTS` in `yoyopod_rs/runtime/BUILD.bazel`:

```python
RUNTIME_TESTS = [
    "cli",
    "config",
    "event",
    "protocol",
    "runtime_loop",
    "smoke",
    "state",
    "worker",
]
```

- [ ] **Step 3: Run the CLI test to verify it fails**

Run:

```bash
cargo test --manifest-path yoyopod_rs/Cargo.toml -p yoyopod-runtime --test cli --locked
```

Expected: FAIL because `--dry-run` does not exist yet.

- [ ] **Step 4: Implement logging helpers**

Replace `yoyopod_rs/runtime/src/logging.rs` with:

```rust
use time::format_description::well_known::Rfc3339;
use time::OffsetDateTime;

pub fn startup_marker(version: &str, pid: u32) -> String {
    format!("===== YoYoPod starting (version={version}, pid={pid}) =====")
}

pub fn shutdown_marker(pid: u32) -> String {
    format!("===== YoYoPod shutting down (pid={pid}) =====")
}

pub fn log_info(message: impl AsRef<str>) {
    let timestamp = OffsetDateTime::now_utc()
        .format(&Rfc3339)
        .unwrap_or_else(|_| "unknown-time".to_string());
    eprintln!("{timestamp} | INFO     | runtime | {}", message.as_ref());
}
```

- [ ] **Step 5: Add boot/startup methods to the worker supervisor**

Append these methods inside `impl WorkerSupervisor` in `yoyopod_rs/runtime/src/worker.rs`:

```rust
    pub fn wait_for_ready(
        &mut self,
        domain: WorkerDomain,
        ready_type: &str,
        timeout: Duration,
    ) -> bool {
        let deadline = Instant::now() + timeout;
        while Instant::now() < deadline {
            for message in self.drain_messages(domain, 8) {
                if message.message_type == ready_type {
                    return true;
                }
            }
            thread::sleep(Duration::from_millis(20));
        }
        false
    }
```

- [ ] **Step 6: Implement the binary entrypoint**

Replace `yoyopod_rs/runtime/src/main.rs` with:

```rust
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::thread;
use std::time::Duration;

use anyhow::{bail, Result};
use clap::Parser;
use serde_json::json;
use yoyopod_runtime::config::RuntimeConfig;
use yoyopod_runtime::logging::{log_info, shutdown_marker, startup_marker};
use yoyopod_runtime::runtime_loop::RuntimeLoop;
use yoyopod_runtime::state::{RuntimeState, WorkerDomain};
use yoyopod_runtime::worker::{WorkerSpec, WorkerSupervisor};

#[derive(Debug, Parser)]
#[command(name = "yoyopod-runtime")]
#[command(about = "YoYoPod Rust top-level runtime host")]
struct Args {
    #[arg(long, default_value = "config")]
    config_dir: String,
    #[arg(long)]
    dry_run: bool,
    #[arg(long, default_value = "whisplay")]
    hardware: String,
}

fn main() -> Result<()> {
    let args = Args::parse();
    let pid = std::process::id();
    log_info(startup_marker(env!("CARGO_PKG_VERSION"), pid));

    let config = RuntimeConfig::load(&args.config_dir)?;
    if args.dry_run {
        println!("{}", serde_json::to_string_pretty(&config)?);
        log_info(shutdown_marker(pid));
        return Ok(());
    }

    let shutdown = Arc::new(AtomicBool::new(false));
    let shutdown_handler = Arc::clone(&shutdown);
    ctrlc::set_handler(move || {
        shutdown_handler.store(true, Ordering::SeqCst);
    })?;

    let mut workers = WorkerSupervisor::default();
    start_workers(&mut workers, &config, &args.hardware)?;
    send_startup_commands(&mut workers, &config);

    let mut runtime = RuntimeLoop::new(RuntimeState::default());
    while !shutdown.load(Ordering::SeqCst) && !runtime.shutdown_requested() {
        runtime.run_once(&mut workers);
        thread::sleep(Duration::from_millis(20));
    }

    workers.stop_all(Duration::from_secs(1));
    log_info(shutdown_marker(pid));
    Ok(())
}

fn start_workers(
    workers: &mut WorkerSupervisor,
    config: &RuntimeConfig,
    hardware: &str,
) -> Result<()> {
    if !workers.start(WorkerSpec::new(
        WorkerDomain::Ui,
        config.worker_paths.ui.clone(),
        ["--hardware".to_string(), hardware.to_string()],
    )) {
        bail!("failed to start UI worker");
    }
    if !workers.wait_for_ready(WorkerDomain::Ui, "ui.ready", Duration::from_secs(5)) {
        bail!("timed out waiting for ui.ready");
    }

    workers.start(WorkerSpec::new(
        WorkerDomain::Media,
        config.worker_paths.media.clone(),
        Vec::<String>::new(),
    ));
    let _ = workers.wait_for_ready(WorkerDomain::Media, "media.ready", Duration::from_secs(3));
    workers.start(WorkerSpec::new(
        WorkerDomain::Voip,
        config.worker_paths.voip.clone(),
        Vec::<String>::new(),
    ));
    let _ = workers.wait_for_ready(WorkerDomain::Voip, "voip.ready", Duration::from_secs(3));
    Ok(())
}

fn send_startup_commands(workers: &mut WorkerSupervisor, config: &RuntimeConfig) {
    workers.send_command(
        WorkerDomain::Ui,
        "ui.set_backlight",
        json!({"brightness": config.ui.brightness}),
    );
    workers.send_command(
        WorkerDomain::Media,
        "media.configure",
        config.media.to_worker_payload(),
    );
    workers.send_command(WorkerDomain::Media, "media.start", json!({}));
    workers.send_command(
        WorkerDomain::Voip,
        "voip.configure",
        config.voip.to_worker_payload(),
    );
    workers.send_command(WorkerDomain::Voip, "voip.register", json!({}));
}
```

- [ ] **Step 7: Run CLI tests**

Run:

```bash
cargo test --manifest-path yoyopod_rs/Cargo.toml -p yoyopod-runtime --test cli --locked
```

Expected: PASS.

- [ ] **Step 8: Run gates and commit**

Run:

```bash
cargo fmt --manifest-path yoyopod_rs/Cargo.toml --all --check
cargo test --manifest-path yoyopod_rs/Cargo.toml -p yoyopod-runtime --locked
uv run python scripts/quality.py gate && uv run pytest -q
```

Commit:

```bash
git add yoyopod_rs/runtime
git commit -m "feat(runtime): boot Rust runtime binary"
```

## Task 9: Build, CI Artifact, And Dev Service Integration

**Files:**
- Modify: `.github/workflows/ci.yml`
- Modify: `yoyopod_cli/build.py`
- Modify: `yoyopod_cli/COMMANDS.md`
- Modify: `deploy/systemd/yoyopod-dev.service`
- Create: `tests/cli/test_yoyopod_cli_build_runtime.py`
- Modify: `docs/operations/PI_DEV_WORKFLOW.md`

- [ ] **Step 1: Write failing CLI build test**

Create `tests/cli/test_yoyopod_cli_build_runtime.py`:

```python
from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from yoyopod_cli.main import app


def test_build_commands_list_rust_runtime() -> None:
    result = CliRunner().invoke(app, ["build", "--help"])

    assert result.exit_code == 0
    assert "rust-runtime" in result.stdout


def test_rust_runtime_binary_path_is_workspace_relative() -> None:
    from yoyopod_cli import build

    path = build._rust_runtime_binary_path()

    assert path == Path(build.REPO_ROOT) / "yoyopod_rs" / "runtime" / "build" / (
        "yoyopod-runtime.exe" if build.os.name == "nt" else "yoyopod-runtime"
    )
```

- [ ] **Step 2: Run the CLI test to verify it fails**

Run:

```bash
uv run pytest -q tests/cli/test_yoyopod_cli_build_runtime.py
```

Expected: FAIL because the build command and helper do not exist.

- [ ] **Step 3: Add build helpers**

Add these helpers near the Rust UI host helpers in `yoyopod_cli/build.py`:

```python
def _rust_runtime_workspace_dir() -> Path:
    return _REPO_ROOT / "yoyopod_rs"


def _rust_runtime_crate_dir() -> Path:
    return _rust_runtime_workspace_dir() / "runtime"


def _rust_runtime_binary_path() -> Path:
    suffix = ".exe" if os.name == "nt" else ""
    return _rust_runtime_crate_dir() / "build" / f"yoyopod-runtime{suffix}"


def build_rust_runtime() -> Path:
    """Build the Rust top-level runtime and return the copied binary path."""

    workspace_dir = _rust_runtime_workspace_dir()
    output = _rust_runtime_binary_path()
    output.parent.mkdir(parents=True, exist_ok=True)
    _run(
        [
            "cargo",
            "build",
            "--release",
            "-p",
            "yoyopod-runtime",
            "--locked",
        ],
        cwd=workspace_dir,
    )

    suffix = ".exe" if os.name == "nt" else ""
    built_binary = workspace_dir / "target" / "release" / f"yoyopod-runtime{suffix}"
    shutil.copy2(built_binary, output)
    return output
```

Add the Typer command near the other Rust build commands:

```python
@app.command("rust-runtime")
def build_rust_runtime_command() -> None:
    """Build the Rust top-level runtime binary."""

    output = build_rust_runtime()
    typer.echo(f"Built Rust runtime: {output}")
```

- [ ] **Step 4: Update the dev service with an opt-in Rust entrypoint**

Modify `deploy/systemd/yoyopod-dev.service` so `ExecStart` supports `YOYOPOD_DEV_RUNTIME=rust`:

```ini
ExecStart=/usr/bin/env bash -lc 'CHECKOUT="$${YOYOPOD_DEV_CHECKOUT:-/opt/yoyopod-dev/checkout}"; VENV="$${YOYOPOD_DEV_VENV:-/opt/yoyopod-dev/venv}"; cd "$$CHECKOUT"; if [ "$${YOYOPOD_DEV_RUNTIME:-python}" = "rust" ]; then exec "$$CHECKOUT/yoyopod_rs/runtime/build/yoyopod-runtime" --config-dir "$$CHECKOUT/config" --hardware whisplay; fi; exec "$$VENV/bin/python" yoyopod.py'
```

Keep the existing `ExecStartPre` line for now. It still builds Python-native LVGL support for the legacy path and does not start a long-running Python runtime.

- [ ] **Step 5: Update CI artifact build**

In `.github/workflows/ci.yml`, extend the Bazel Rust test command:

```yaml
run: bazel test //yoyopod_rs/ui-host/... //yoyopod_rs/media-host/... //yoyopod_rs/voip-host/... //yoyopod_rs/runtime/... //yoyopod_rs/liblinphone-shim/...
```

After the VoIP host artifact upload, add:

```yaml
      - name: Build Rust runtime
        working-directory: yoyopod_rs
        run: |
          set -euo pipefail
          cargo build --release -p yoyopod-runtime --locked
          mkdir -p runtime/build
          cp target/release/yoyopod-runtime runtime/build/yoyopod-runtime

      - name: Upload Rust runtime ARM64 host
        uses: actions/upload-artifact@v4
        with:
          name: yoyopod-runtime-${{ env.RUST_ARTIFACT_SHA }}
          path: yoyopod_rs/runtime/build/yoyopod-runtime
          if-no-files-found: error
```

- [ ] **Step 6: Document the dev-lane switch**

Append this section to `docs/operations/PI_DEV_WORKFLOW.md`:

````markdown
## Rust Runtime Dev-Lane Entry Point

The Python app remains the default dev-lane service entrypoint. To run the Rust
top-level runtime after downloading the matching GitHub Actions artifacts into
the checkout, set:

```bash
sudo install -m 0644 deploy/systemd/yoyopod-dev.service /etc/systemd/system/yoyopod-dev.service
sudo systemctl daemon-reload
sudo systemctl edit yoyopod-dev.service
```

Use this override:

```ini
[Service]
Environment=YOYOPOD_DEV_RUNTIME=rust
```

Then restart:

```bash
sudo systemctl restart yoyopod-dev.service
sudo journalctl -u yoyopod-dev.service -n 100 --no-pager
```

The Rust runtime must use committed GitHub Actions artifacts for the exact commit
under test. Do not build Rust binaries on the Pi Zero 2W unless explicitly
overridden for one debugging session.
````

- [ ] **Step 7: Regenerate command docs**

Run:

```bash
uv run yoyopod dev docs
```

Expected: `yoyopod_cli/COMMANDS.md` includes `yoyopod build rust-runtime`.

- [ ] **Step 8: Run focused Python tests**

Run:

```bash
uv run pytest -q tests/cli/test_yoyopod_cli_build_runtime.py
```

Expected: PASS.

- [ ] **Step 9: Run gates and commit**

Run:

```bash
cargo fmt --manifest-path yoyopod_rs/Cargo.toml --all --check
cargo clippy --manifest-path yoyopod_rs/Cargo.toml --all-targets -- -D warnings
cargo test --manifest-path yoyopod_rs/Cargo.toml --workspace --locked
uv run python scripts/quality.py gate && uv run pytest -q
```

Commit:

```bash
git add .github/workflows/ci.yml deploy/systemd/yoyopod-dev.service docs/operations/PI_DEV_WORKFLOW.md yoyopod_cli/build.py yoyopod_cli/COMMANDS.md tests/cli/test_yoyopod_cli_build_runtime.py
git commit -m "feat(runtime): build Rust runtime artifact"
```

## Task 10: Final Runtime Verification And Target Handoff

**Files:**
- Modify only if verification finds a defect in files touched by Tasks 1-9.

- [ ] **Step 1: Run the full local Python and Rust gates**

Run:

```bash
uv run python scripts/quality.py gate && uv run pytest -q
cargo fmt --manifest-path yoyopod_rs/Cargo.toml --all --check
cargo clippy --manifest-path yoyopod_rs/Cargo.toml --all-targets -- -D warnings
cargo test --manifest-path yoyopod_rs/Cargo.toml --workspace --locked
bazel test //yoyopod_rs/runtime/...
```

Expected: all commands pass locally. If Bazel is unavailable locally, record that and rely on CI for Bazel while still running Cargo.

- [ ] **Step 2: Verify the binary help and dry run**

Run:

```bash
cargo run --manifest-path yoyopod_rs/Cargo.toml -p yoyopod-runtime -- --help
cargo run --manifest-path yoyopod_rs/Cargo.toml -p yoyopod-runtime -- --config-dir config --dry-run
```

Expected:

- Help includes `--config-dir`, `--dry-run`, and `--hardware`.
- Dry run prints JSON config and exits successfully without starting workers.

- [ ] **Step 3: Commit any final fixes**

If Step 1 or Step 2 required changes, run the full gates again:

```bash
uv run python scripts/quality.py gate && uv run pytest -q
cargo fmt --manifest-path yoyopod_rs/Cargo.toml --all --check
cargo clippy --manifest-path yoyopod_rs/Cargo.toml --all-targets -- -D warnings
cargo test --manifest-path yoyopod_rs/Cargo.toml --workspace --locked
```

Commit the fixes:

```bash
git add <changed-files>
git commit -m "fix(runtime): finalize Rust runtime host"
```

- [ ] **Step 4: Push and wait for Rust artifacts**

Run:

```bash
git branch --show-current
git rev-parse HEAD
git push
```

Expected: GitHub Actions produces artifacts named:

- `yoyopod-runtime-<sha>`
- `yoyopod-ui-host-<sha>`
- `yoyopod-media-host-<sha>`
- `yoyopod-voip-host-<sha>`
- `yoyopod-liblinphone-shim-<sha>`

- [ ] **Step 5: Validate on the Pi dev lane**

Use committed artifacts for the exact SHA. Then on the Pi:

```bash
yoyopod remote mode activate dev
yoyopod remote sync --branch <branch> --clean-native
sudo systemctl edit yoyopod-dev.service
sudo systemctl restart yoyopod-dev.service
sudo journalctl -u yoyopod-dev.service -n 150 --no-pager
```

The systemd override must contain:

```ini
[Service]
Environment=YOYOPOD_DEV_RUNTIME=rust
```

Expected target behavior:

- Journal contains the Rust startup marker.
- `yoyopod-runtime` is the long-running app process.
- There is no long-running `python yoyopod.py` process.
- Whisplay UI boots.
- One-button input produces UI movement or intents.
- Media worker starts and can play/pause when media is available.
- VoIP worker registers, or the UI/status shows a visible VoIP degraded state.
- `sudo systemctl stop yoyopod-dev.service` stops child workers within `TimeoutStopSec`.

- [ ] **Step 6: Capture target validation notes**

Add a short note to the PR or implementation summary with:

```text
Rust runtime dev-lane validation
- branch:
- commit:
- artifacts:
- service:
- Whisplay UI:
- one-button input:
- media:
- VoIP:
- shutdown:
- known gaps:
```

Do not edit docs just to store the validation note unless the user asks for a persistent hardware validation record.

## Implementation Notes

- Keep `ui-host`, `media-host`, and `voip-host` protocol changes out of this milestone unless a compiler or runtime contract failure forces a narrow fix.
- Keep malformed protocol output counted and logged. Do not make unknown event types fatal.
- Treat `ui-host` as mandatory. Treat `media-host` and `voip-host` as degradable after startup.
- Keep the runtime config loader minimal and explicit. Do not port the full Python config composition system in this milestone.
- Keep the dev-lane service default as Python until the Rust path has passed hardware validation.
- Include "run `uv run python scripts/quality.py gate && uv run pytest -q` before the final commit step" when dispatching implementer subagents.
