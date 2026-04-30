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
}

struct WorkerProcess {
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
        command
            .args(&spec.argv[1..])
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
                child,
                stdin,
                messages,
                pending_messages: VecDeque::new(),
                protocol_errors,
                exit_reported: false,
            },
        );
        true
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
        let Some(worker) = self.workers.get_mut(&domain) else {
            return false;
        };

        let deadline = Instant::now() + timeout;
        let mut preserved = VecDeque::new();

        while let Some(message) = worker.pending_messages.pop_front() {
            if message.message_type == ready_type {
                prepend_pending(worker, preserved);
                return true;
            }
            preserve_ready_backlog(&mut preserved, message);
        }

        while Instant::now() < deadline {
            while let Ok(message) = worker.messages.try_recv() {
                if message.message_type == ready_type {
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

fn all_worker_domains() -> [WorkerDomain; 6] {
    [
        WorkerDomain::Ui,
        WorkerDomain::Media,
        WorkerDomain::Voip,
        WorkerDomain::Network,
        WorkerDomain::Power,
        WorkerDomain::Voice,
    ]
}
