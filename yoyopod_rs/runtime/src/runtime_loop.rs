use std::collections::HashMap;
use std::time::Instant;

use serde_json::json;

use crate::event::{commands_for_event, runtime_event_from_worker, RuntimeCommand};
use crate::protocol::WorkerEnvelope;
use crate::state::{RuntimeState, WorkerDomain, WorkerState};
use crate::worker::{WorkerProtocolError, WorkerSupervisor};

const WORKER_DOMAINS: [WorkerDomain; 6] = [
    WorkerDomain::Ui,
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
        self.send_tick(io);

        processed
    }

    fn dispatch_command(&mut self, io: &mut impl LoopIo, command: RuntimeCommand) {
        match command {
            RuntimeCommand::WorkerCommand { domain, envelope } => {
                let _ = io.send_worker_envelope(domain, envelope);
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
}

fn protocol_error_reason(error: &WorkerProtocolError) -> String {
    if error.raw_line.is_empty() {
        format!("protocol error: {}", error.message)
    } else {
        format!("protocol error: {} ({})", error.message, error.raw_line)
    }
}
