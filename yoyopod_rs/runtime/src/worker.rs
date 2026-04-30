use std::collections::HashMap;
use std::io::{BufRead, BufReader, Write};
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::mpsc::{self, Receiver, Sender};
use std::thread;
use std::time::{Duration, Instant};

use serde_json::{json, Value};

use crate::protocol::{WorkerEnvelope, SUPPORTED_SCHEMA_VERSION};
use crate::state::WorkerDomain;

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
    protocol_errors: Receiver<WorkerProtocolError>,
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
                protocol_errors,
            },
        );
        true
    }

    pub fn send_envelope(&mut self, domain: WorkerDomain, envelope: WorkerEnvelope) -> bool {
        let Some(worker) = self.workers.get_mut(&domain) else {
            return false;
        };
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
        drain_receiver(&worker.messages, limit)
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
            let message_type = format!("{}.stop", domain.as_str());
            let _ = self.send_command(domain, &message_type, json!({}));
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
    for line in BufReader::new(stdout).lines() {
        let Ok(line) = line else {
            break;
        };
        if line.trim().is_empty() {
            continue;
        }

        match WorkerEnvelope::decode(line.as_bytes()) {
            Ok(envelope) => {
                let _ = messages.send(envelope);
            }
            Err(error) => {
                let _ = protocol_errors.send(WorkerProtocolError {
                    raw_line: line,
                    message: error.to_string(),
                });
            }
        }
    }
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
