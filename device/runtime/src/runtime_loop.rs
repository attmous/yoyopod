use std::collections::HashMap;
use std::fs;
use std::path::Path;
use std::process::Command;
use std::time::{Instant, SystemTime, UNIX_EPOCH};

use serde_json::{json, Value};

use crate::event::{commands_for_event, runtime_event_from_worker, RuntimeCommand};
use crate::protocol::WorkerEnvelope;
use crate::state::{RuntimeState, WorkerDomain, WorkerState};
use crate::worker::{WorkerProtocolError, WorkerSupervisor};

const WORKER_DOMAINS: [WorkerDomain; 7] = [
    WorkerDomain::Ui,
    WorkerDomain::Cloud,
    WorkerDomain::Media,
    WorkerDomain::Voip,
    WorkerDomain::Network,
    WorkerDomain::Power,
    WorkerDomain::Voice,
];
const DRAIN_LIMIT_PER_DOMAIN: usize = 64;

pub trait LoopIo {
    fn drain_worker_messages(&mut self) -> Vec<(WorkerDomain, WorkerEnvelope)>;
    fn drain_worker_protocol_errors(&mut self) -> Vec<(WorkerDomain, WorkerProtocolError)>;
    fn send_worker_envelope(&mut self, domain: WorkerDomain, envelope: WorkerEnvelope) -> bool;
    fn write_power_shutdown_state(&mut self, path: &str, payload: &Value) -> Result<(), String>;
    fn request_system_shutdown(&mut self, command: &str) -> Result<(), String>;
}

#[derive(Debug, Clone)]
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
        let mut processed = 0;
        let mut protocol_faults = HashMap::<WorkerDomain, String>::new();

        for (domain, error) in io.drain_worker_protocol_errors() {
            let reason = protocol_error_reason(&error);
            self.state
                .record_worker_protocol_error(domain, reason.clone());
            protocol_faults.insert(domain, reason);
        }

        for (domain, envelope) in io.drain_worker_messages() {
            let Some(event) = runtime_event_from_worker(domain, envelope) else {
                continue;
            };

            for command in commands_for_event(&self.state, &event) {
                self.dispatch_command(io, command);
            }

            let before = self.state.clone();
            event.apply(&mut self.state);
            if self.state != before {
                self.send_runtime_snapshot(io);
            }

            processed += 1;
        }

        for (domain, reason) in protocol_faults {
            self.state
                .mark_worker(domain, WorkerState::Degraded, reason);
        }

        self.state.loop_iterations += 1;
        self.state.last_loop_duration_ms = started.elapsed().as_millis() as u64;
        self.process_pending_power_shutdown(io);
        self.send_tick(io);

        processed
    }

    fn process_pending_power_shutdown(&mut self, io: &mut impl LoopIo) {
        let now_seconds = current_epoch_seconds();
        if !self.state.power_shutdown_due(now_seconds) {
            return;
        }

        let state_file = self.state.power.safety.config.shutdown_state_file.clone();
        let command = self.state.power.safety.config.shutdown_command.clone();
        let payload = self.state.power_shutdown_state_payload(now_seconds);
        let _ = io.send_worker_envelope(
            WorkerDomain::Power,
            WorkerEnvelope::command(
                "power.watchdog_suppress",
                None,
                json!({"reason": "pending_system_poweroff"}),
            ),
        );
        let _ = io.write_power_shutdown_state(&state_file, &payload);
        let _ = io.request_system_shutdown(&command);
        self.state.mark_power_shutdown_completed();
        self.shutdown_requested = true;
    }

    fn dispatch_command(&mut self, io: &mut impl LoopIo, command: RuntimeCommand) {
        match command {
            RuntimeCommand::WorkerCommand { domain, envelope } => {
                let _ = io.send_worker_envelope(domain, envelope);
            }
            RuntimeCommand::WorkerCommandWithAck {
                domain,
                envelope,
                success_ack,
                failure_ack,
            } => {
                let ack = if io.send_worker_envelope(domain, envelope) {
                    success_ack
                } else {
                    failure_ack
                };
                let _ = io.send_worker_envelope(WorkerDomain::Cloud, ack);
            }
            RuntimeCommand::Shutdown => {
                self.shutdown_requested = true;
            }
        }
    }

    fn send_runtime_snapshot(&self, io: &mut impl LoopIo) {
        let envelope = WorkerEnvelope::command(
            "ui.runtime_snapshot",
            None,
            self.state.ui_snapshot_payload(),
        );
        let _ = io.send_worker_envelope(WorkerDomain::Ui, envelope);
    }

    fn send_tick(&self, io: &mut impl LoopIo) {
        let envelope = WorkerEnvelope::command("ui.tick", None, json!({"renderer": "auto"}));
        let _ = io.send_worker_envelope(WorkerDomain::Ui, envelope);
    }
}

impl LoopIo for WorkerSupervisor {
    fn drain_worker_messages(&mut self) -> Vec<(WorkerDomain, WorkerEnvelope)> {
        WORKER_DOMAINS
            .into_iter()
            .flat_map(|domain| {
                self.drain_messages(domain, DRAIN_LIMIT_PER_DOMAIN)
                    .into_iter()
                    .map(move |envelope| (domain, envelope))
            })
            .collect()
    }

    fn drain_worker_protocol_errors(&mut self) -> Vec<(WorkerDomain, WorkerProtocolError)> {
        WORKER_DOMAINS
            .into_iter()
            .flat_map(|domain| {
                self.drain_protocol_errors(domain, DRAIN_LIMIT_PER_DOMAIN)
                    .into_iter()
                    .map(move |error| (domain, error))
            })
            .collect()
    }

    fn send_worker_envelope(&mut self, domain: WorkerDomain, envelope: WorkerEnvelope) -> bool {
        self.send_envelope(domain, envelope)
    }

    fn write_power_shutdown_state(&mut self, path: &str, payload: &Value) -> Result<(), String> {
        write_shutdown_state_file(path, payload)
    }

    fn request_system_shutdown(&mut self, command: &str) -> Result<(), String> {
        run_shutdown_command(command)
    }
}

fn protocol_error_reason(error: &WorkerProtocolError) -> String {
    if error.raw_line.is_empty() {
        format!("protocol error: {}", error.message)
    } else {
        format!("protocol error: {} ({})", error.message, error.raw_line)
    }
}

fn write_shutdown_state_file(path: &str, payload: &Value) -> Result<(), String> {
    let path = Path::new(path);
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(|error| error.to_string())?;
    }
    let contents = serde_json::to_string_pretty(payload).map_err(|error| error.to_string())?;
    fs::write(path, contents).map_err(|error| error.to_string())
}

fn run_shutdown_command(command: &str) -> Result<(), String> {
    let command = command.trim();
    if command.is_empty() {
        return Err("shutdown command is empty".to_string());
    }

    let status = shutdown_process(command)
        .status()
        .map_err(|error| error.to_string())?;
    if status.success() {
        Ok(())
    } else {
        Err(format!(
            "shutdown command exited with {}",
            status
                .code()
                .map(|code| code.to_string())
                .unwrap_or_else(|| "signal".to_string())
        ))
    }
}

#[cfg(windows)]
fn shutdown_process(command: &str) -> Command {
    let mut process = Command::new("cmd");
    process.args(["/C", command]);
    process
}

#[cfg(not(windows))]
fn shutdown_process(command: &str) -> Command {
    let mut process = Command::new("sh");
    process.args(["-c", command]);
    process
}

fn current_epoch_seconds() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_secs())
        .unwrap_or_default()
}
