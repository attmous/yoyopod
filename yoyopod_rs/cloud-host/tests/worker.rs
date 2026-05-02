use std::io::Cursor;
use std::path::PathBuf;
use std::sync::{Arc, Mutex};
use std::time::{SystemTime, UNIX_EPOCH};

use anyhow::Result;
use serde_json::{json, Value};
use yoyopod_cloud_host::config::CloudHostConfig;
use yoyopod_cloud_host::host::CloudHost;
use yoyopod_cloud_host::mqtt::{CloudMqttBackend, MqttRuntimeEvent};
use yoyopod_cloud_host::protocol::{EnvelopeKind, WorkerEnvelope};
use yoyopod_cloud_host::worker::run_host_loop;

#[test]
fn worker_publishes_python_compatible_mqtt_events_and_acks() {
    let shared = Arc::new(Mutex::new(FakeMqttState::default()));
    let backend = FakeMqttBackend::new(shared.clone());
    let host = CloudHost::new("config", provisioned_config("publish-events"), backend);
    let input = Cursor::new(format!(
        "{}{}{}",
        command(
            "cloud.publish_heartbeat",
            json!({"firmware_version": "test-fw"})
        ),
        command(
            "cloud.ack",
            json!({"command_id": "cmd-1", "ok": false, "reason": "invalid_command"})
        ),
        command("worker.stop", json!({})),
    ));
    let mut output = Vec::new();

    run_host_loop(
        host,
        input,
        &mut output,
        std::time::Duration::from_millis(1),
    )
    .expect("worker loop");

    let published = &shared.lock().expect("fake mqtt state").published;
    assert_eq!(published.len(), 2);
    assert_eq!(published[0].0, "yoyopod/device-123/evt");
    assert_eq!(published[0].2, 1);
    let heartbeat: Value = serde_json::from_str(&published[0].1).expect("heartbeat json");
    assert_eq!(heartbeat["type"], "heartbeat");
    assert_eq!(heartbeat["payload"]["firmware_version"], "test-fw");
    assert!(heartbeat["ts"].as_u64().is_some());

    assert_eq!(published[1].0, "yoyopod/device-123/ack");
    let ack: Value = serde_json::from_str(&published[1].1).expect("ack json");
    assert_eq!(ack["command_id"], "cmd-1");
    assert_eq!(ack["status"], "nack");
    assert_eq!(ack["reason"], "invalid_command");

    let output = String::from_utf8(output).expect("worker utf8 output");
    assert!(output.contains(r#""type":"cloud.ready""#));
    assert!(output.contains(r#""type":"cloud.snapshot""#));
    assert!(output.contains(r#""type":"cloud.stopped""#));
}

#[test]
fn worker_surfaces_backend_commands_as_cloud_command_events() {
    let shared = Arc::new(Mutex::new(FakeMqttState {
        events: vec![MqttRuntimeEvent::Command(json!({
            "command": "fetch_config",
            "commandId": "cmd-2"
        }))],
        ..FakeMqttState::default()
    }));
    let backend = FakeMqttBackend::new(shared);
    let host = CloudHost::new("config", provisioned_config("backend-commands"), backend);
    let input = Cursor::new(command("worker.stop", json!({})));
    let mut output = Vec::new();

    run_host_loop(
        host,
        input,
        &mut output,
        std::time::Duration::from_millis(1),
    )
    .expect("worker loop");

    let output = String::from_utf8(output).expect("worker utf8 output");
    assert!(output.contains(r#""type":"cloud.command""#));
    assert!(output.contains(r#""command":"fetch_config""#));
    assert!(output.contains(r#""last_command_type":"fetch_config""#));
}

#[test]
fn worker_queues_publish_commands_until_mqtt_connected() {
    let shared = Arc::new(Mutex::new(FakeMqttState {
        connect_on_start: false,
        events: vec![MqttRuntimeEvent::Connected],
        ..FakeMqttState::default()
    }));
    let backend = FakeMqttBackend::new(shared.clone());
    let host = CloudHost::new(
        "config",
        provisioned_config("queue-until-connected"),
        backend,
    );
    let input = Cursor::new(format!(
        "{}{}",
        command(
            "cloud.publish_heartbeat",
            json!({"firmware_version": "test-fw"})
        ),
        command("worker.stop", json!({})),
    ));
    let mut output = Vec::new();

    run_host_loop(
        host,
        input,
        &mut output,
        std::time::Duration::from_millis(1),
    )
    .expect("worker loop");

    let published = &shared.lock().expect("fake mqtt state").published;
    assert_eq!(published.len(), 1);
    assert_eq!(published[0].0, "yoyopod/device-123/evt");
    let heartbeat: Value = serde_json::from_str(&published[0].1).expect("heartbeat json");
    assert_eq!(heartbeat["type"], "heartbeat");
    assert_eq!(heartbeat["payload"]["firmware_version"], "test-fw");
}

struct FakeMqttState {
    published: Vec<(String, String, u8)>,
    events: Vec<MqttRuntimeEvent>,
    connected: bool,
    connect_on_start: bool,
}

impl Default for FakeMqttState {
    fn default() -> Self {
        Self {
            published: Vec::new(),
            events: Vec::new(),
            connected: false,
            connect_on_start: true,
        }
    }
}

struct FakeMqttBackend {
    state: Arc<Mutex<FakeMqttState>>,
}

impl FakeMqttBackend {
    fn new(state: Arc<Mutex<FakeMqttState>>) -> Self {
        Self { state }
    }
}

impl CloudMqttBackend for FakeMqttBackend {
    fn start(&mut self, _config: &CloudHostConfig) -> Result<()> {
        let mut state = self.state.lock().expect("fake state");
        state.connected = state.connect_on_start;
        Ok(())
    }

    fn stop(&mut self) {
        self.state.lock().expect("fake state").connected = false;
    }

    fn is_connected(&self) -> bool {
        self.state.lock().expect("fake state").connected
    }

    fn publish(&mut self, topic: &str, payload: &str, qos: u8) -> Result<bool> {
        self.state.lock().expect("fake state").published.push((
            topic.to_string(),
            payload.to_string(),
            qos,
        ));
        Ok(true)
    }

    fn drain_events(&mut self) -> Vec<MqttRuntimeEvent> {
        std::mem::take(&mut self.state.lock().expect("fake state").events)
    }
}

fn provisioned_config(test_name: &str) -> CloudHostConfig {
    CloudHostConfig {
        mqtt_broker_host: "mqtt.example.test".to_string(),
        mqtt_broker_port: 1883,
        device_id: "device-123".to_string(),
        device_secret: "secret-456".to_string(),
        runtime_root: temp_dir(test_name).to_string_lossy().to_string(),
        ..CloudHostConfig::default()
    }
}

fn temp_dir(test_name: &str) -> PathBuf {
    let unique = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("time")
        .as_nanos();
    std::env::temp_dir().join(format!("yoyopod-cloud-host-worker-{test_name}-{unique}"))
}

fn command(message_type: &str, payload: Value) -> String {
    let envelope = WorkerEnvelope {
        schema_version: 1,
        kind: EnvelopeKind::Command,
        message_type: message_type.to_string(),
        request_id: None,
        timestamp_ms: 0,
        deadline_ms: 0,
        payload,
    };
    String::from_utf8(envelope.encode().expect("encode command")).expect("utf8 command")
}
