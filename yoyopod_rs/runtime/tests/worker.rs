use std::time::{Duration, Instant};

use serde_json::json;
use yoyopod_runtime::protocol::{EnvelopeKind, WorkerEnvelope, SUPPORTED_SCHEMA_VERSION};
use yoyopod_runtime::state::WorkerDomain;
use yoyopod_runtime::worker::{
    command_envelope, record_worker_stdout_line, WorkerProtocolError, WorkerSpec, WorkerSupervisor,
};

#[test]
fn worker_spec_new_builds_argv() {
    let spec = WorkerSpec::new(
        WorkerDomain::Ui,
        "yoyopod-ui-host",
        ["--hardware".to_string(), "whisplay".to_string()],
    );

    assert_eq!(spec.domain, WorkerDomain::Ui);
    assert_eq!(spec.argv, vec!["yoyopod-ui-host", "--hardware", "whisplay"]);
}

#[test]
fn missing_domain_send_returns_false() {
    let mut supervisor = WorkerSupervisor::default();

    assert!(!supervisor.send_envelope(
        WorkerDomain::Media,
        command_envelope("media.play", json!({}))
    ));
    assert!(!supervisor.send_command(WorkerDomain::Media, "media.play", json!({})));
}

#[test]
fn command_envelope_uses_runtime_command_shape() {
    let envelope = command_envelope("ui.tick", json!({"renderer": "auto"}));

    assert_eq!(envelope.schema_version, SUPPORTED_SCHEMA_VERSION);
    assert_eq!(envelope.kind, EnvelopeKind::Command);
    assert_eq!(envelope.message_type, "ui.tick");
    assert_eq!(envelope.payload, json!({"renderer": "auto"}));
}

#[test]
fn worker_supervisor_drains_valid_stdout_envelope() {
    let mut supervisor = WorkerSupervisor::default();
    assert!(supervisor.start(stdout_worker_spec(
        WorkerDomain::Ui,
        r#"{"schema_version":1,"kind":"event","type":"ui.ready","payload":{}}"#,
    )));

    let messages = wait_for_message(&mut supervisor, WorkerDomain::Ui);

    assert_eq!(messages.len(), 1);
    assert_eq!(messages[0].kind, EnvelopeKind::Event);
    assert_eq!(messages[0].message_type, "ui.ready");
    supervisor.stop_all(Duration::from_millis(100));
}

#[test]
fn malformed_stdout_is_drainable_as_protocol_error() {
    let mut messages = Vec::<WorkerEnvelope>::new();
    let mut errors = Vec::<WorkerProtocolError>::new();

    record_worker_stdout_line("not-json", &mut messages, &mut errors);
    record_worker_stdout_line("", &mut messages, &mut errors);

    assert!(messages.is_empty());
    assert_eq!(errors.len(), 1);
    assert_eq!(errors[0].raw_line, "not-json");
    assert!(errors[0].message.contains("invalid JSON worker envelope"));
}

#[test]
fn worker_supervisor_drains_malformed_stdout_as_protocol_error() {
    let mut supervisor = WorkerSupervisor::default();
    assert!(supervisor.start(stdout_worker_spec(WorkerDomain::Voice, "not-json")));

    let errors = wait_for_protocol_error(&mut supervisor, WorkerDomain::Voice);

    assert_eq!(errors.len(), 1);
    assert_eq!(errors[0].raw_line, "not-json");
    supervisor.stop_all(Duration::from_millis(100));
}

#[test]
fn rejects_empty_or_duplicate_worker_start() {
    let mut supervisor = WorkerSupervisor::default();
    assert!(!supervisor.start(WorkerSpec {
        domain: WorkerDomain::Power,
        argv: Vec::new(),
    }));

    assert!(supervisor.start(stdout_worker_spec(
        WorkerDomain::Power,
        r#"{"schema_version":1,"kind":"event","type":"power.ready","payload":{}}"#,
    )));
    assert!(!supervisor.start(stdout_worker_spec(
        WorkerDomain::Power,
        r#"{"schema_version":1,"kind":"event","type":"power.ready","payload":{}}"#,
    )));
    supervisor.stop_all(Duration::from_millis(100));
}

#[test]
fn worker_test_is_registered_in_bazel_runtime_tests() {
    let build_file = std::fs::read_to_string(
        std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("BUILD.bazel"),
    )
    .expect("read runtime BUILD.bazel");

    assert!(build_file.contains("\"worker\""));
}

fn wait_for_message(
    supervisor: &mut WorkerSupervisor,
    domain: WorkerDomain,
) -> Vec<WorkerEnvelope> {
    let deadline = Instant::now() + Duration::from_secs(5);
    while Instant::now() < deadline {
        let messages = supervisor.drain_messages(domain, 8);
        if !messages.is_empty() {
            return messages;
        }
        std::thread::sleep(Duration::from_millis(20));
    }
    Vec::new()
}

fn wait_for_protocol_error(
    supervisor: &mut WorkerSupervisor,
    domain: WorkerDomain,
) -> Vec<WorkerProtocolError> {
    let deadline = Instant::now() + Duration::from_secs(5);
    while Instant::now() < deadline {
        let errors = supervisor.drain_protocol_errors(domain, 8);
        if !errors.is_empty() {
            return errors;
        }
        std::thread::sleep(Duration::from_millis(20));
    }
    Vec::new()
}

fn stdout_worker_spec(domain: WorkerDomain, line: &str) -> WorkerSpec {
    if cfg!(windows) {
        WorkerSpec::new(
            domain,
            "powershell",
            [
                "-NoProfile".to_string(),
                "-Command".to_string(),
                format!("Write-Output '{}'; Start-Sleep -Seconds 5", line),
            ],
        )
    } else {
        WorkerSpec::new(
            domain,
            "sh",
            [
                "-c".to_string(),
                format!("printf '%s\\n' '{}'; sleep 5", line.replace('\'', "'\\''")),
            ],
        )
    }
}
