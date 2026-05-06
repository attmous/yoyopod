use std::path::{Path, PathBuf};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use serde_json::json;
use yoyopod_runtime::protocol::{EnvelopeKind, WorkerEnvelope, SUPPORTED_SCHEMA_VERSION};
use yoyopod_runtime::state::WorkerDomain;
use yoyopod_runtime::worker::{
    command_envelope, record_worker_stdout_line, WorkerProtocolError, WorkerSpec, WorkerSupervisor,
    MAX_PRESERVED_READY_MESSAGES,
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
fn wait_for_ready_preserves_non_ready_messages_for_later_drain() {
    let mut supervisor = WorkerSupervisor::default();
    assert!(supervisor.start(stdout_lines_worker_spec(
        WorkerDomain::Ui,
        &[
            r#"{"schema_version":1,"kind":"event","type":"ui.input","payload":{"key":"select"}}"#,
            r#"{"schema_version":1,"kind":"event","type":"ui.ready","payload":{}}"#,
        ],
    )));

    assert!(supervisor.wait_for_ready(WorkerDomain::Ui, "ui.ready", Duration::from_secs(5)));
    let messages = supervisor.drain_messages(WorkerDomain::Ui, 8);

    assert_eq!(messages.len(), 1);
    assert_eq!(messages[0].message_type, "ui.input");
    supervisor.stop_all(Duration::from_millis(100));
}

#[test]
fn wait_for_ready_caps_preserved_messages_and_keeps_latest_before_ready() {
    let mut lines = Vec::new();
    for index in 0..(MAX_PRESERVED_READY_MESSAGES + 5) {
        lines.push(format!(
            r#"{{"schema_version":1,"kind":"event","type":"ui.input","payload":{{"index":{index}}}}}"#
        ));
    }
    lines.push(r#"{"schema_version":1,"kind":"event","type":"ui.ready","payload":{}}"#.to_string());
    let line_refs = lines.iter().map(String::as_str).collect::<Vec<_>>();

    let mut supervisor = WorkerSupervisor::default();
    assert!(supervisor.start(stdout_lines_worker_spec(WorkerDomain::Ui, &line_refs)));

    assert!(supervisor.wait_for_ready(WorkerDomain::Ui, "ui.ready", Duration::from_secs(5)));
    let messages = supervisor.drain_messages(WorkerDomain::Ui, MAX_PRESERVED_READY_MESSAGES + 10);

    assert_eq!(messages.len(), MAX_PRESERVED_READY_MESSAGES);
    assert_eq!(messages[0].payload["index"], json!(5));
    assert_eq!(
        messages[MAX_PRESERVED_READY_MESSAGES - 1].payload["index"],
        json!(MAX_PRESERVED_READY_MESSAGES + 4)
    );
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
fn worker_supervisor_drains_invalid_utf8_stdout_as_protocol_error() {
    let mut supervisor = WorkerSupervisor::default();
    assert!(supervisor.start(invalid_utf8_stdout_worker_spec(WorkerDomain::Network)));

    let errors = wait_for_protocol_error(&mut supervisor, WorkerDomain::Network);

    assert_eq!(errors.len(), 1);
    assert_eq!(errors[0].raw_line, "<invalid utf8>");
    assert!(errors[0].message.contains("invalid UTF-8 worker stdout"));
    supervisor.stop_all(Duration::from_millis(100));
}

#[test]
fn worker_supervisor_reports_silent_child_exit_once() {
    let mut supervisor = WorkerSupervisor::default();
    assert!(supervisor.start(silent_exit_worker_spec(WorkerDomain::Media)));

    let messages = wait_for_message(&mut supervisor, WorkerDomain::Media);

    assert_eq!(messages.len(), 1);
    assert_eq!(messages[0].kind, EnvelopeKind::Event);
    assert_eq!(messages[0].message_type, "worker.exited");
    assert!(messages[0].payload["reason"]
        .as_str()
        .is_some_and(|reason| reason.contains("exited")));
    assert!(supervisor.drain_messages(WorkerDomain::Media, 8).is_empty());
    assert!(!supervisor.send_command(WorkerDomain::Media, "media.play", json!({})));
    supervisor.stop_all(Duration::from_millis(100));
}

#[test]
fn stop_all_sends_generic_worker_stop_to_managed_worker() {
    let output_path = temp_file_path("worker-stop");
    let mut supervisor = WorkerSupervisor::default();
    assert!(supervisor.start(stdin_capture_worker_spec(WorkerDomain::Media, &output_path)));

    supervisor.stop_all(Duration::from_secs(1));

    let written = std::fs::read_to_string(&output_path).expect("captured worker stdin");
    assert!(written.contains(r#""type":"worker.stop""#));
    assert!(!written.contains(r#""type":"media.stop""#));
    let _ = std::fs::remove_file(output_path);
}

#[test]
fn send_envelope_rejects_non_command_without_writing_to_stdin() {
    let output_path = temp_file_path("non-command");
    let mut supervisor = WorkerSupervisor::default();
    assert!(supervisor.start(stdin_capture_worker_spec(WorkerDomain::Media, &output_path)));

    assert!(!supervisor.send_envelope(
        WorkerDomain::Media,
        WorkerEnvelope {
            schema_version: SUPPORTED_SCHEMA_VERSION,
            kind: EnvelopeKind::Event,
            message_type: "media.snapshot".to_string(),
            request_id: None,
            timestamp_ms: 0,
            deadline_ms: 0,
            payload: json!({}),
        }
    ));
    std::thread::sleep(Duration::from_millis(100));

    assert!(!output_path.exists());
    supervisor.stop_all(Duration::from_millis(100));
    let _ = std::fs::remove_file(output_path);
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
    stdout_lines_worker_spec(domain, &[line])
}

fn stdout_lines_worker_spec(domain: WorkerDomain, lines: &[&str]) -> WorkerSpec {
    if cfg!(windows) {
        let commands = lines
            .iter()
            .map(|line| format!("Write-Output '{}'", line.replace('\'', "''")))
            .collect::<Vec<_>>()
            .join("; ");
        WorkerSpec::new(
            domain,
            "powershell",
            [
                "-NoProfile".to_string(),
                "-Command".to_string(),
                format!("{commands}; Start-Sleep -Seconds 5"),
            ],
        )
    } else {
        let script = lines
            .iter()
            .map(|line| format!("printf '%s\\n' '{}'", line.replace('\'', "'\\''")))
            .collect::<Vec<_>>()
            .join("; ");
        WorkerSpec::new(
            domain,
            "sh",
            ["-c".to_string(), format!("{script}; sleep 5")],
        )
    }
}

fn invalid_utf8_stdout_worker_spec(domain: WorkerDomain) -> WorkerSpec {
    if cfg!(windows) {
        WorkerSpec::new(
            domain,
            "powershell",
            [
                "-NoProfile".to_string(),
                "-Command".to_string(),
                "[Console]::OpenStandardOutput().Write([byte[]](255,10),0,2); Start-Sleep -Seconds 5"
                    .to_string(),
            ],
        )
    } else {
        WorkerSpec::new(
            domain,
            "sh",
            ["-c".to_string(), "printf '\\377\\n'; sleep 5".to_string()],
        )
    }
}

fn silent_exit_worker_spec(domain: WorkerDomain) -> WorkerSpec {
    if cfg!(windows) {
        WorkerSpec::new(
            domain,
            "powershell",
            [
                "-NoProfile".to_string(),
                "-Command".to_string(),
                "exit 0".to_string(),
            ],
        )
    } else {
        WorkerSpec::new(domain, "sh", ["-c".to_string(), "exit 0".to_string()])
    }
}

fn stdin_capture_worker_spec(domain: WorkerDomain, output_path: &Path) -> WorkerSpec {
    if cfg!(windows) {
        WorkerSpec::new(
            domain,
            "powershell",
            [
                "-NoProfile".to_string(),
                "-Command".to_string(),
                format!(
                    "$line = [Console]::In.ReadLine(); Set-Content -LiteralPath '{}' -Value $line",
                    powershell_single_quote(output_path)
                ),
            ],
        )
    } else {
        WorkerSpec::new(
            domain,
            "sh",
            [
                "-c".to_string(),
                format!(
                    "IFS= read -r line; printf '%s' \"$line\" > '{}'",
                    shell_single_quote(output_path)
                ),
            ],
        )
    }
}

fn temp_file_path(test_name: &str) -> PathBuf {
    let unique = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("time")
        .as_nanos();
    std::env::temp_dir().join(format!("yoyopod-runtime-worker-{test_name}-{unique}.txt"))
}

fn shell_single_quote(path: &Path) -> String {
    path.to_string_lossy().replace('\'', "'\\''")
}

fn powershell_single_quote(path: &Path) -> String {
    path.to_string_lossy().replace('\'', "''")
}
