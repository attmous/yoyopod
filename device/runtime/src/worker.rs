use std::collections::{HashMap, VecDeque};
use std::io::{BufRead, BufReader, Write};
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::mpsc::{self, Receiver, Sender};
use std::thread;
use std::time::{Duration, Instant};

use serde_json::{json, Value};

use crate::protocol::{EnvelopeKind, WorkerEnvelope, SUPPORTED_SCHEMA_VERSION};
use crate::state::WorkerDomain;

pub const MAX_PRESERVED_READY_MESSAGES: usize = 32;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WorkerSpec {
    pub domain: WorkerDomain,
    pub argv: Vec<String>,
}

impl WorkerSpec {
    pub fn new(
        domain: WorkerDomain,
        program: impl Into<String>,
        args: impl IntoIterator<Item = String>,
    ) -> Self {
        let mut argv = vec![program.into()];
        argv.extend(args);
        Self { domain, argv }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WorkerProtocolError {
    pub raw_line: String,
    pub message: String,
}

#[derive(Default)]
pub struct WorkerSupervisor {
    workers: HashMap<WorkerDomain, WorkerProcess>,
    specs: HashMap<WorkerDomain, WorkerSpec>,
}

struct WorkerProcess {
    lifetime_token: String,
    child: Child,
    stdin: ChildStdin,
    messages: Receiver<WorkerEnvelope>,
    pending_messages: VecDeque<WorkerEnvelope>,
    protocol_errors: Receiver<WorkerProtocolError>,
    exit_reported: bool,
}

impl WorkerSupervisor {
    pub fn start(&mut self, spec: WorkerSpec) -> bool {
        if spec.argv.is_empty() || self.workers.contains_key(&spec.domain) {
            return false;
        }

        let mut command = Command::new(&spec.argv[0]);
        let lifetime_token = format!(
            "{}-{}-{}",
            std::process::id(),
            spec.domain.as_str(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap_or_default()
                .as_nanos()
        );
        command
            .args(&spec.argv[1..])
            .env("YOYOPOD_WORKER_LIFETIME", &lifetime_token)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::inherit());

        let Ok(mut child) = command.spawn() else {
            return false;
        };
        let Some(stdin) = child.stdin.take() else {
            let _ = child.kill();
            let _ = child.wait();
            return false;
        };
        let Some(stdout) = child.stdout.take() else {
            let _ = child.kill();
            let _ = child.wait();
            return false;
        };

        let (message_tx, messages) = mpsc::channel();
        let (error_tx, protocol_errors) = mpsc::channel();
        thread::spawn(move || read_worker_stdout(stdout, message_tx, error_tx));

        self.workers.insert(
            spec.domain,
            WorkerProcess {
                lifetime_token,
                child,
                stdin,
                messages,
                pending_messages: VecDeque::new(),
                protocol_errors,
                exit_reported: false,
            },
        );
        self.specs.insert(spec.domain, spec);
        true
    }

    /// Reconstruct only this process. Old channels and user commands are discarded.
    pub fn restart(&mut self, domain: WorkerDomain) -> Result<(), String> {
        self.restart_with_reaper(domain, reap_owned_helpers)
    }

    fn restart_with_reaper(&mut self, domain: WorkerDomain, reap: impl FnOnce(&str) -> Result<(), String>) -> Result<(), String> {
        let spec = self
            .specs
            .get(&domain)
            .cloned()
            .ok_or("worker has no startup specification")?;
        if let Some(mut worker) = self.workers.remove(&domain) {
            if matches!(worker.child.try_wait(), Ok(None)) {
                worker.child.kill().map_err(|e| e.to_string())?;
            }
            worker.child.wait().map_err(|e| e.to_string())?;
            reap(&worker.lifetime_token)?;
        }
        if !self.start(spec) {
            return Err("replacement worker could not start".into());
        }
        let ready = format!("{}.ready", domain.as_str());
        if !self.wait_for_ready(domain, &ready, Duration::from_secs(3)) {
            return Err("replacement worker readiness timed out".into());
        }
        Ok(())
    }

    pub fn send_envelope(&mut self, domain: WorkerDomain, envelope: WorkerEnvelope) -> bool {
        if envelope.kind != EnvelopeKind::Command {
            return false;
        }
        let Some(worker) = self.workers.get_mut(&domain) else {
            return false;
        };
        if worker_has_exited(worker) {
            return false;
        }
        let Ok(encoded) = envelope.encode() else {
            return false;
        };

        worker.stdin.write_all(&encoded).is_ok() && worker.stdin.flush().is_ok()
    }

    pub fn send_command(
        &mut self,
        domain: WorkerDomain,
        message_type: &str,
        payload: Value,
    ) -> bool {
        self.send_envelope(domain, command_envelope(message_type, payload))
    }

    pub fn drain_messages(&mut self, domain: WorkerDomain, limit: usize) -> Vec<WorkerEnvelope> {
        let Some(worker) = self.workers.get_mut(&domain) else {
            return Vec::new();
        };
        drain_worker_messages(worker, limit)
    }

    pub fn drain_protocol_errors(
        &mut self,
        domain: WorkerDomain,
        limit: usize,
    ) -> Vec<WorkerProtocolError> {
        let Some(worker) = self.workers.get_mut(&domain) else {
            return Vec::new();
        };
        drain_receiver(&worker.protocol_errors, limit)
    }

    pub fn stop_all(&mut self, grace: Duration) {
        for domain in all_worker_domains() {
            let _ = self.send_command(domain, "worker.stop", json!({}));
        }

        let deadline = Instant::now() + grace;
        loop {
            let mut all_exited = true;
            for worker in self.workers.values_mut() {
                if matches!(worker.child.try_wait(), Ok(None)) {
                    all_exited = false;
                }
            }
            if all_exited || Instant::now() >= deadline {
                break;
            }
            thread::sleep(Duration::from_millis(10));
        }

        for worker in self.workers.values_mut() {
            if matches!(worker.child.try_wait(), Ok(None)) {
                let _ = worker.child.kill();
            }
            let _ = worker.child.wait();
        }
        self.workers.clear();
    }

    pub fn wait_for_ready(
        &mut self,
        domain: WorkerDomain,
        ready_type: &str,
        timeout: Duration,
    ) -> bool {
        self.wait_for_message(domain, timeout, |message| {
            message.message_type == ready_type
        })
    }

    pub fn wait_for_message(
        &mut self,
        domain: WorkerDomain,
        timeout: Duration,
        mut matches_message: impl FnMut(&WorkerEnvelope) -> bool,
    ) -> bool {
        let Some(worker) = self.workers.get_mut(&domain) else {
            return false;
        };

        let deadline = Instant::now() + timeout;
        let mut preserved = VecDeque::new();

        while let Some(message) = worker.pending_messages.pop_front() {
            if matches_message(&message) {
                prepend_pending(worker, preserved);
                return true;
            }
            preserve_ready_backlog(&mut preserved, message);
        }

        while Instant::now() < deadline {
            while let Ok(message) = worker.messages.try_recv() {
                if matches_message(&message) {
                    prepend_pending(worker, preserved);
                    return true;
                }
                preserve_ready_backlog(&mut preserved, message);
            }
            thread::sleep(Duration::from_millis(20));
        }

        prepend_pending(worker, preserved);
        false
    }
}

pub fn command_envelope(message_type: impl Into<String>, payload: Value) -> WorkerEnvelope {
    WorkerEnvelope {
        schema_version: SUPPORTED_SCHEMA_VERSION,
        kind: crate::protocol::EnvelopeKind::Command,
        message_type: message_type.into(),
        request_id: None,
        timestamp_ms: 0,
        deadline_ms: 0,
        payload,
    }
}

pub fn record_worker_stdout_line(
    line: &str,
    messages: &mut Vec<WorkerEnvelope>,
    protocol_errors: &mut Vec<WorkerProtocolError>,
) {
    let trimmed = line.trim_end_matches(['\r', '\n']);
    if trimmed.is_empty() {
        return;
    }

    match WorkerEnvelope::decode(trimmed.as_bytes()) {
        Ok(envelope) => messages.push(envelope),
        Err(error) => protocol_errors.push(WorkerProtocolError {
            raw_line: trimmed.to_string(),
            message: error.to_string(),
        }),
    }
}

fn read_worker_stdout(
    stdout: impl std::io::Read,
    messages: Sender<WorkerEnvelope>,
    protocol_errors: Sender<WorkerProtocolError>,
) {
    let mut reader = BufReader::new(stdout);
    let mut line = Vec::new();

    loop {
        line.clear();
        match reader.read_until(b'\n', &mut line) {
            Ok(0) => break,
            Ok(_) => record_worker_stdout_bytes(&line, &messages, &protocol_errors),
            Err(error) => {
                let _ = protocol_errors.send(WorkerProtocolError {
                    raw_line: "<read error>".to_string(),
                    message: format!("failed to read worker stdout: {error}"),
                });
                break;
            }
        }
    }
}

fn record_worker_stdout_bytes(
    line: &[u8],
    messages: &Sender<WorkerEnvelope>,
    protocol_errors: &Sender<WorkerProtocolError>,
) {
    let trimmed = trim_line_end(line);
    if trimmed.is_empty() {
        return;
    }

    let raw_line = match std::str::from_utf8(trimmed) {
        Ok(raw_line) => raw_line.to_string(),
        Err(error) => {
            let _ = protocol_errors.send(WorkerProtocolError {
                raw_line: "<invalid utf8>".to_string(),
                message: format!("invalid UTF-8 worker stdout: {error}"),
            });
            return;
        }
    };

    match WorkerEnvelope::decode(trimmed) {
        Ok(envelope) => {
            let _ = messages.send(envelope);
        }
        Err(error) => {
            let _ = protocol_errors.send(WorkerProtocolError {
                raw_line,
                message: error.to_string(),
            });
        }
    }
}

fn trim_line_end(mut line: &[u8]) -> &[u8] {
    while matches!(line.last(), Some(b'\r' | b'\n')) {
        line = &line[..line.len() - 1];
    }
    line
}

fn drain_receiver<T>(receiver: &Receiver<T>, limit: usize) -> Vec<T> {
    let mut drained = Vec::new();
    for _ in 0..limit {
        let Ok(item) = receiver.try_recv() else {
            break;
        };
        drained.push(item);
    }
    drained
}

fn drain_worker_messages(worker: &mut WorkerProcess, limit: usize) -> Vec<WorkerEnvelope> {
    let mut drained = Vec::new();
    for _ in 0..limit {
        if let Some(message) = worker.pending_messages.pop_front() {
            drained.push(message);
            continue;
        }
        let Ok(message) = worker.messages.try_recv() else {
            break;
        };
        drained.push(message);
    }
    if drained.len() < limit {
        if let Some(message) = worker_exit_message(worker) {
            drained.push(message);
        }
    }
    drained
}

fn worker_has_exited(worker: &mut WorkerProcess) -> bool {
    !matches!(worker.child.try_wait(), Ok(None))
}

fn worker_exit_message(worker: &mut WorkerProcess) -> Option<WorkerEnvelope> {
    if worker.exit_reported {
        return None;
    }

    let status = match worker.child.try_wait() {
        Ok(Some(status)) => status,
        Ok(None) | Err(_) => return None,
    };
    worker.exit_reported = true;
    Some(WorkerEnvelope {
        schema_version: SUPPORTED_SCHEMA_VERSION,
        kind: EnvelopeKind::Event,
        message_type: "worker.exited".to_string(),
        request_id: None,
        timestamp_ms: 0,
        deadline_ms: 0,
        payload: json!({"reason": format!("exited with {status}")}),
    })
}

fn prepend_pending(worker: &mut WorkerProcess, mut preserved: VecDeque<WorkerEnvelope>) {
    preserved.append(&mut worker.pending_messages);
    worker.pending_messages = preserved;
}

fn preserve_ready_backlog(backlog: &mut VecDeque<WorkerEnvelope>, message: WorkerEnvelope) {
    if backlog.len() == MAX_PRESERVED_READY_MESSAGES {
        let _ = backlog.pop_front();
    }
    backlog.push_back(message);
}

fn all_worker_domains() -> [WorkerDomain; 7] {
    [
        WorkerDomain::Ui,
        WorkerDomain::Cloud,
        WorkerDomain::Media,
        WorkerDomain::Voip,
        WorkerDomain::Network,
        WorkerDomain::Power,
        WorkerDomain::Voice,
    ]
}

/// Children inherit a supervisor-created lifetime token through helper exec.
/// It remains discoverable after reparenting, unlike a PPID-only census.
#[cfg(target_os = "linux")]
fn reap_owned_helpers(token: &str) -> Result<(), String> {
    let expected = format!("YOYOPOD_WORKER_LIFETIME={token}");
    let deadline = Instant::now() + Duration::from_secs(2);
    loop {
        let mut found = false;
        for entry in std::fs::read_dir("/proc")
            .map_err(|e| e.to_string())?
            .flatten()
        {
            let Some(pid) = entry
                .file_name()
                .to_str()
                .and_then(|s| s.parse::<u32>().ok())
            else {
                continue;
            };
            let Ok(environment) = std::fs::read(entry.path().join("environ")) else {
                continue;
            };
            if !environment
                .split(|b| *b == 0)
                .any(|item| item == expected.as_bytes())
            {
                continue;
            }
            found = true;
            // Fixed executable/argv, only a process with this exact inherited token.
            let _ = Command::new("/bin/kill")
                .args(["-KILL", "--", &pid.to_string()])
                .status();
        }
        if !found {
            return Ok(());
        }
        if Instant::now() >= deadline {
            return Err("old worker audio helpers did not release".into());
        }
        thread::sleep(Duration::from_millis(10));
    }
}

#[cfg(not(target_os = "linux"))]
fn reap_owned_helpers(_token: &str) -> Result<(), String> {
    Err("worker resource reconciliation requires Linux procfs".into())
}

#[cfg(all(test, target_os = "linux"))]
mod recovery_tests {
    use super::*;
    #[test]
    fn failed_reap_retains_worker_for_retry() {
        let mut supervisor = WorkerSupervisor::default();
        assert!(supervisor.start(WorkerSpec::new(WorkerDomain::Media, "/bin/sh", ["-c".into(), "sleep 60".into()])));
        let token = supervisor.workers[&WorkerDomain::Media].lifetime_token.clone();
        assert!(supervisor.restart_with_reaper(WorkerDomain::Media, |_| Err("injected census failure".into())).is_err());
        let mut retried = false;
        let result = supervisor.restart_with_reaper(WorkerDomain::Media, |seen| {
            assert_eq!(seen, token);
            retried = true;
            Err("still uncertain".into())
        });
        assert!(retried, "retry must reconcile the original lifetime again");
        assert!(result.is_err());
        supervisor.stop_all(Duration::ZERO);
    }
    #[test]
    fn recovery_reaps_orphan_audio_helper_before_restarting_worker() {
        let dir = tempfile::tempdir().unwrap();
        let marker = dir.path().join("started");
        let lease = dir.path().join("audio.lock");
        let quote =
            |p: &std::path::Path| format!("'{}'", p.display().to_string().replace('\'', "'\\''"));
        let script=format!("if [ ! -e {} ]; then touch {}; flock -n {} sleep 60 & fi; printf '%s\\n' '{{\"kind\":\"event\",\"type\":\"media.ready\",\"payload\":{{}}}}'; while read line; do :; done; wait",
            quote(&marker),quote(&marker),quote(&lease));
        let mut supervisor = WorkerSupervisor::default();
        assert!(supervisor.start(WorkerSpec::new(
            WorkerDomain::Media,
            "/bin/sh",
            ["-c".into(), script]
        )));
        assert!(supervisor.wait_for_ready(
            WorkerDomain::Media,
            "media.ready",
            Duration::from_secs(2)
        ));
        let deadline = Instant::now() + Duration::from_secs(2);
        loop {
            if !Command::new("flock")
                .arg("-n")
                .arg(&lease)
                .arg("true")
                .status()
                .unwrap()
                .success()
            {
                break;
            }
            assert!(
                Instant::now() < deadline,
                "helper must own resource before test kill"
            );
            thread::sleep(Duration::from_millis(10));
        }
        supervisor
            .workers
            .get_mut(&WorkerDomain::Media)
            .unwrap()
            .child
            .kill()
            .unwrap();
        supervisor
            .workers
            .get_mut(&WorkerDomain::Media)
            .unwrap()
            .child
            .wait()
            .unwrap();
        assert!(
            !Command::new("flock")
                .arg("-n")
                .arg(&lease)
                .arg("true")
                .status()
                .unwrap()
                .success(),
            "orphan intentionally survives worker death"
        );
        supervisor.restart(WorkerDomain::Media).unwrap();
        assert!(
            Command::new("flock")
                .arg("-n")
                .arg(&lease)
                .arg("true")
                .status()
                .unwrap()
                .success(),
            "recovery success requires old resource release"
        );
        supervisor.stop_all(Duration::from_millis(50));
    }
}
