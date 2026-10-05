use std::collections::HashMap;
use std::fs;
use std::path::Path;
use std::process::Command;
use std::time::{Instant, SystemTime, UNIX_EPOCH};

use serde_json::{json, Value};
use yoyopod_protocol::ui::UiCommand;

use crate::call_manager::effects::CallOperationLedger;
use crate::call_manager::{CallManager, CallManagerEvent};
use crate::event::{commands_for_event, runtime_event_from_worker, RuntimeCommand};
use crate::protocol::{EnvelopeKind, WorkerEnvelope};
use crate::state::{RuntimeState, WorkerDomain, WorkerState};
use crate::worker::{RecoveryStatus, WorkerProtocolError, WorkerSupervisor};
mod calls;

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

#[derive(Debug, Clone)]
struct PendingWorkerCommand {
    command_id: String,
    command_type: String,
    deadline: Instant,
}

pub trait LoopIo {
    /// Pending is scheduling only; Ready proves old resources gone and replacement ready.
    fn recover_worker(&mut self, domain: WorkerDomain) -> Result<RecoveryStatus, String>;
    fn poll_worker_recovery(&mut self, domain: WorkerDomain) -> Result<RecoveryStatus, String>;
    fn drain_worker_messages(&mut self) -> Vec<(WorkerDomain, WorkerEnvelope)>;
    fn drain_worker_protocol_errors(&mut self) -> Vec<(WorkerDomain, WorkerProtocolError)>;
    fn send_worker_envelope(&mut self, domain: WorkerDomain, envelope: WorkerEnvelope) -> bool;
    fn write_power_shutdown_state(&mut self, path: &str, payload: &Value) -> Result<(), String>;
    fn request_system_shutdown(&mut self, command: &str) -> Result<(), String>;
    fn append_app_log(&mut self, log_file: &str, line: &str) -> Result<(), String>;
}

#[derive(Debug, Clone)]
pub struct RuntimeLoop {
    state: RuntimeState,
    shutdown_requested: bool,
    pending_worker_commands: HashMap<(WorkerDomain, String), PendingWorkerCommand>,
    manager: CallManager,
    call_operations: CallOperationLedger,
    calls: calls::CallIntegration,
    clock_origin: Instant,
    now_ms: u64,
}

impl RuntimeLoop {
    pub fn new(mut state: RuntimeState) -> Self {
        let manager = CallManager::new(
            state.settings.device_mode.clone(),
            8_000,
            state.call_ring_duration_ms,
        );
        let (native_guard, error) = crate::call_manager::native_guard::NativeOperationGuard::load(
            &state.native_call_guard_file,
        );
        if let Some(error) = error {
            state.mark_worker(WorkerDomain::Network, WorkerState::Degraded, error);
        }
        let mut calls = calls::CallIntegration::default();
        calls.native_guard = native_guard;
        Self {
            state,
            shutdown_requested: false,
            pending_worker_commands: HashMap::new(),
            manager,
            call_operations: Default::default(),
            calls,
            clock_origin: Instant::now(),
            now_ms: 0,
        }
    }

    pub fn state(&self) -> &RuntimeState {
        &self.state
    }

    pub fn shutdown_requested(&self) -> bool {
        self.shutdown_requested
    }

    pub fn run_once(&mut self, io: &mut impl LoopIo) -> usize {
        self.run_once_at(io, self.clock_origin.elapsed().as_millis() as u64)
    }

    pub fn run_once_at(&mut self, io: &mut impl LoopIo, now_ms: u64) -> usize {
        self.now_ms = self.now_ms.max(now_ms);
        self.process_pending_power_shutdown(io);
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
            if self.intercept_call_message(io, domain, &envelope) {
                processed += 1;
                continue;
            }
            self.resolve_correlated_worker_result(io, domain, &envelope);
            let Some(event) = runtime_event_from_worker(domain, envelope) else {
                continue;
            };
            if self.intercept_call_event(io, &event) {
                processed += 1;
                continue;
            }

            for command in commands_for_event(&self.state, &event) {
                self.dispatch_command(io, command);
            }

            let before = self.state.clone();
            event.apply(&mut self.state);
            self.project_call();
            if self.manager.mode() != self.state.settings.device_mode {
                self.handle_call(
                    io,
                    CallManagerEvent::SetMode(self.state.settings.device_mode.clone()),
                );
            }
            if self.state != before {
                self.send_runtime_snapshot_patches(io, &before);
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
        self.poll_call_recoveries(io);
        self.expire_correlated_worker_commands(io);
        for operation in self.call_operations.expired(self.now_ms) {
            self.finish_call_operation(io, operation, false, &json!({}));
        }
        self.handle_call(io, CallManagerEvent::Tick);
        self.confirm_call_cleanup(io);
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
        self.begin_shutdown(io, self.now_ms);
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
        if self.block_call_conflicting_command(io, &command) {
            return;
        }
        match command {
            RuntimeCommand::WorkerCommand { domain, envelope } => {
                let id = envelope.request_id.clone();
                if domain == WorkerDomain::Network
                    && matches!(envelope.message_type.as_str(), "call.action" | "call.dial")
                    && !self.guard_native_dispatch(&envelope)
                {
                    if let Some(operation) =
                        id.and_then(|id| self.call_operations.take(domain, &id))
                    {
                        self.finish_call_operation(io, operation, false, &json!({}));
                    }
                    return;
                }
                if !io.send_worker_envelope(domain, envelope) {
                    if let Some(operation) =
                        id.and_then(|id| self.call_operations.take(domain, &id))
                    {
                        self.finish_call_operation(io, operation, false, &json!({}));
                    }
                }
            }
            RuntimeCommand::RequestCall(action) => self.request_outgoing(io, action),
            RuntimeCommand::RecoverWorker { domain } => self.recover_call_worker(io, domain),
            RuntimeCommand::CorrelatedWorkerCommand {
                domain,
                mut envelope,
                command_id,
                command_type,
                timeout_ms,
            } => {
                envelope.request_id = Some(command_id.clone());
                if io.send_worker_envelope(domain, envelope) {
                    self.pending_worker_commands.insert(
                        (domain, command_id.clone()),
                        PendingWorkerCommand {
                            command_id,
                            command_type,
                            deadline: Instant::now() + std::time::Duration::from_millis(timeout_ms),
                        },
                    );
                } else {
                    self.send_command_ack(
                        io,
                        &command_id,
                        &command_type,
                        false,
                        Some("worker_dispatch_failed"),
                    );
                }
            }
            RuntimeCommand::AppendAppLog { line } => {
                let _ = io.append_app_log(&self.state.app_log_file, &line);
            }
            RuntimeCommand::Shutdown => {
                self.begin_shutdown(io, self.now_ms);
            }
        }
    }

    fn resolve_correlated_worker_result(
        &mut self,
        io: &mut impl LoopIo,
        domain: WorkerDomain,
        envelope: &WorkerEnvelope,
    ) {
        if !matches!(envelope.kind, EnvelopeKind::Result | EnvelopeKind::Error) {
            return;
        }
        let Some(request_id) = envelope.request_id.as_ref() else {
            return;
        };
        let Some(pending) = self
            .pending_worker_commands
            .remove(&(domain, request_id.clone()))
        else {
            return;
        };
        let succeeded = envelope.kind == EnvelopeKind::Result;
        let reason = (!succeeded).then(|| safe_worker_error_code(&envelope.payload));
        self.send_command_ack(
            io,
            &pending.command_id,
            &pending.command_type,
            succeeded,
            reason.as_deref(),
        );
    }

    fn expire_correlated_worker_commands(&mut self, io: &mut impl LoopIo) {
        let now = Instant::now();
        let expired = self
            .pending_worker_commands
            .iter()
            .filter(|(_, pending)| pending.deadline <= now)
            .map(|(key, _)| key.clone())
            .collect::<Vec<_>>();
        for key in expired {
            if let Some(pending) = self.pending_worker_commands.remove(&key) {
                self.send_command_ack(
                    io,
                    &pending.command_id,
                    &pending.command_type,
                    false,
                    Some("worker_timeout"),
                );
            }
        }
    }

    fn send_command_ack(
        &self,
        io: &mut impl LoopIo,
        command_id: &str,
        command_type: &str,
        ok: bool,
        reason: Option<&str>,
    ) {
        let mut payload = json!({
            "command_id": command_id,
            "ok": ok,
            "payload": {"command": command_type},
        });
        if let Some(reason) = reason {
            payload["reason"] = json!(reason);
        }
        let _ = io.send_worker_envelope(
            WorkerDomain::Cloud,
            WorkerEnvelope::command("cloud.ack", None, payload),
        );
    }

    fn send_runtime_snapshot_patches(&self, io: &mut impl LoopIo, before: &RuntimeState) {
        for patch in self.state.ui_snapshot_patches_since(before) {
            let envelope = UiCommand::RuntimePatch(patch).into_envelope();
            let _ = io.send_worker_envelope(WorkerDomain::Ui, envelope);
        }
    }

    fn send_tick(&self, io: &mut impl LoopIo) {
        let _ = io.send_worker_envelope(WorkerDomain::Ui, UiCommand::Tick.into_envelope());
    }
}

fn safe_worker_error_code(payload: &Value) -> String {
    payload
        .get("code")
        .and_then(Value::as_str)
        .filter(|code| {
            !code.is_empty()
                && code.len() <= 64
                && code
                    .bytes()
                    .all(|byte| byte.is_ascii_lowercase() || byte.is_ascii_digit() || byte == b'_')
        })
        .unwrap_or("worker_failed")
        .to_string()
}

impl LoopIo for WorkerSupervisor {
    fn recover_worker(&mut self, domain: WorkerDomain) -> Result<RecoveryStatus, String> {
        WorkerSupervisor::recover_worker(self, domain)
    }
    fn poll_worker_recovery(&mut self, domain: WorkerDomain) -> Result<RecoveryStatus, String> {
        self.poll_recovery(domain)
    }
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

    fn append_app_log(&mut self, log_file: &str, line: &str) -> Result<(), String> {
        crate::logging::log_marker(log_file, line).map_err(|error| error.to_string())
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

#[cfg(test)]
mod tests {
    use super::*;
    use yoyopod_protocol::ui::RuntimeSnapshotPatch;

    fn assert_no_local_call_interruption(sent: &[(WorkerDomain, WorkerEnvelope)]) {
        for (domain, envelope) in sent {
            assert!(!matches!(
                envelope.message_type.as_str(),
                "media.pause"
                    | "media.interrupt_for_call"
                    | "media.ringtone_start"
                    | "voip.interrupt_for_call"
                    | "voice.cancel"
                    | "voice.cancel_focus_prompt"
                    | "ui.set_backlight"
            ));
            if *domain == WorkerDomain::Ui {
                assert_ne!(
                    envelope
                        .payload
                        .pointer("/call/state")
                        .and_then(Value::as_str),
                    Some("incoming")
                );
            }
        }
    }

    #[test]
    fn settings_priority_write_has_its_own_request_id() {
        let mut runtime = RuntimeLoop::new(RuntimeState::default());
        let event = crate::event::RuntimeEvent::UiIntent(yoyopod_protocol::ui::UiIntent::Settings(yoyopod_protocol::ui::SettingsIntent::ContactPrioritySet(yoyopod_protocol::call::ContactPrioritySet { contact_id: "b".into(), priority: true })));
        let mut io = FakeLoopIo::default();
        for command in commands_for_event(runtime.state(), &event) { runtime.dispatch_command(&mut io, command); }
        let command = io.sent.iter().find(|(_, envelope)| envelope.message_type == "cloud.contact_priority_set").unwrap();
        assert!(command.1.request_id.is_some(), "UI priority writes need dedicated correlation");
        assert!(io.sent.iter().all(|(_, envelope)| envelope.message_type != "cloud.ack"));
    }

    #[test]
    fn managed_unknown_offers_reject_without_local_interruption() {
        for (domain, transport) in [(WorkerDomain::Voip, "sip"), (WorkerDomain::Network, "gsm")] {
            let mut runtime = RuntimeLoop::new(RuntimeState::default());
            let mut io = FakeLoopIo::default();
            io.messages.push((
                domain,
                WorkerEnvelope::event(
                    "call.offer",
                    json!({
                        "key":{"transport":transport,"generation":1,"call_id":"unknown"},
                        "address":"withheld"
                    }),
                ),
            ));
            runtime.run_once(&mut io);
            assert_no_local_call_interruption(&io.sent);
            assert!(
                io.sent
                    .iter()
                    .any(|(sent_domain, envelope)| *sent_domain == domain
                        && envelope.message_type == "call.action"
                        && envelope.payload["action"]["reject"] == "unapproved"),
                "raw unknown offer requires an isolated rejection"
            );
        }
    }

    fn ui_runtime_patch_command(envelope: WorkerEnvelope) -> Option<UiCommand> {
        let Ok(command) = UiCommand::from_envelope(envelope) else {
            return None;
        };
        matches!(command, UiCommand::RuntimePatch(_)).then_some(command)
    }

    #[derive(Default)]
    pub(super) struct FakeLoopIo {
        pub(super) messages: Vec<(WorkerDomain, WorkerEnvelope)>,
        protocol_errors: Vec<(WorkerDomain, WorkerProtocolError)>,
        pub(super) sent: Vec<(WorkerDomain, WorkerEnvelope)>,
        app_log: Vec<(String, String)>,
        pub(super) recovered: Vec<WorkerDomain>,
        pub(super) recovery_pending: bool,
        pub(super) recovery_polls: usize,
        pub(super) fail_send: Vec<String>,
        pub(super) system_shutdowns: Vec<String>,
    }

    impl LoopIo for FakeLoopIo {
        fn recover_worker(&mut self, domain: WorkerDomain) -> Result<RecoveryStatus, String> {
            self.recovered.push(domain);
            Ok(if self.recovery_pending {
                RecoveryStatus::Pending
            } else {
                RecoveryStatus::Ready
            })
        }
        fn poll_worker_recovery(&mut self, _: WorkerDomain) -> Result<RecoveryStatus, String> {
            self.recovery_polls += 1;
            Ok(if self.recovery_pending {
                RecoveryStatus::Pending
            } else {
                RecoveryStatus::Ready
            })
        }
        fn drain_worker_messages(&mut self) -> Vec<(WorkerDomain, WorkerEnvelope)> {
            std::mem::take(&mut self.messages)
        }

        fn drain_worker_protocol_errors(&mut self) -> Vec<(WorkerDomain, WorkerProtocolError)> {
            std::mem::take(&mut self.protocol_errors)
        }

        fn send_worker_envelope(&mut self, domain: WorkerDomain, envelope: WorkerEnvelope) -> bool {
            let ok = !self.fail_send.contains(&envelope.message_type);
            self.sent.push((domain, envelope));
            ok
        }

        fn write_power_shutdown_state(
            &mut self,
            _path: &str,
            _payload: &Value,
        ) -> Result<(), String> {
            Ok(())
        }

        fn request_system_shutdown(&mut self, command: &str) -> Result<(), String> {
            self.system_shutdowns.push(command.to_owned());
            Ok(())
        }

        fn append_app_log(&mut self, log_file: &str, line: &str) -> Result<(), String> {
            self.app_log.push((log_file.to_string(), line.to_string()));
            Ok(())
        }
    }

    #[test]
    fn state_change_sends_domain_runtime_patch() {
        let mut io = FakeLoopIo {
            messages: vec![(
                WorkerDomain::Media,
                WorkerEnvelope::event(
                    "media.snapshot",
                    json!({
                        "playback_state": "playing",
                        "current_track": {
                            "title": "Patch Song",
                            "artist": "Patch Artist",
                        },
                    }),
                ),
            )],
            ..FakeLoopIo::default()
        };
        let mut runtime = RuntimeLoop::new(RuntimeState::default());

        runtime.run_once(&mut io);

        let ui_patches = io
            .sent
            .iter()
            .filter(|(domain, _)| *domain == WorkerDomain::Ui)
            .filter_map(|(_, envelope)| ui_runtime_patch_command(envelope.clone()))
            .collect::<Vec<_>>();

        assert_eq!(ui_patches.len(), 1);
        let UiCommand::RuntimePatch(RuntimeSnapshotPatch::Music(music)) = &ui_patches[0] else {
            panic!("expected music runtime patch");
        };
        assert!(music.playing);
        assert_eq!(music.title, "Patch Song");
    }

    #[test]
    fn ui_screenshot_captured_event_appends_app_log_line() {
        let mut io = FakeLoopIo {
            messages: vec![(
                WorkerDomain::Ui,
                WorkerEnvelope::event(
                    "ui.screenshot_captured",
                    json!({
                        "path": "/tmp/yoyopod_screenshot.png",
                        "ok": true,
                        "method": "lvgl_readback",
                    }),
                ),
            )],
            ..FakeLoopIo::default()
        };
        let mut state = RuntimeState::default();
        state.configure_app_log_file("logs/custom.log");
        let mut runtime = RuntimeLoop::new(state);

        runtime.run_once(&mut io);

        assert_eq!(
            io.app_log,
            vec![(
                "logs/custom.log".to_string(),
                "Saved screenshot via LVGL readback -> /tmp/yoyopod_screenshot.png".to_string(),
            )]
        );
    }

    #[test]
    fn failed_screenshot_capture_appends_failure_line() {
        let mut io = FakeLoopIo {
            messages: vec![(
                WorkerDomain::Ui,
                WorkerEnvelope::event(
                    "ui.screenshot_captured",
                    json!({
                        "path": "/tmp/yoyopod_screenshot.png",
                        "ok": false,
                        "detail": "LVGL display not initialized",
                    }),
                ),
            )],
            ..FakeLoopIo::default()
        };
        let mut runtime = RuntimeLoop::new(RuntimeState::default());

        runtime.run_once(&mut io);

        assert_eq!(
            io.app_log,
            vec![(
                "logs/yoyopod.log".to_string(),
                "Screenshot capture failed: LVGL display not initialized".to_string(),
            )]
        );
    }

    #[test]
    fn worker_health_only_change_does_not_send_ui_patch() {
        let mut io = FakeLoopIo {
            messages: vec![(
                WorkerDomain::Cloud,
                WorkerEnvelope::event("cloud.ready", json!({})),
            )],
            ..FakeLoopIo::default()
        };
        let mut runtime = RuntimeLoop::new(RuntimeState::default());

        runtime.run_once(&mut io);

        assert!(!io.sent.iter().any(|(domain, envelope)| {
            *domain == WorkerDomain::Ui && ui_runtime_patch_command(envelope.clone()).is_some()
        }));
    }

    #[test]
    fn cloud_phone_contacts_preserve_gsm_targets_without_becoming_sip_targets() {
        let mut runtime = RuntimeLoop::new(RuntimeState::default());
        let mut io = FakeLoopIo {
            messages: vec![(
                WorkerDomain::Cloud,
                WorkerEnvelope::event(
                    "cloud.config",
                    json!({"config": {"contacts": {"entries": [
                        {"id": "dad", "name": "Dad", "sip_address": "sip:dad@example.test", "can_call": true},
                        {"id": "mama", "name": "Mama", "phone_number": "+4912345678", "sip_address": null, "can_call": true},
                        {"id": "mahmoud", "name": "Mahmoud", "phone_number": "+4912345679", "sip_address": "  ", "can_call": true},
                        {"id": "blocked", "name": "Blocked", "sip_address": "sip:blocked@example.test", "can_call": false}
                    ]}}}),
                ),
            )],
            ..FakeLoopIo::default()
        };
        runtime.run_once(&mut io);
        let contacts = &runtime.state.ui_snapshot().call.contacts;
        assert_eq!(contacts.len(), 4);
        assert!(!contacts[3].can_call);
        assert!(runtime
            .state
            .approved_call_target(
                "sip:blocked@example.test",
                yoyopod_protocol::ui::CallMethod::Sip
            )
            .is_none());
        assert!(!contacts[0].communication_unavailable);
        assert_eq!(contacts[0].id, "sip:dad@example.test");
        assert_eq!(contacts[1].id, "mama");
        assert_eq!(contacts[1].title, "Mama");
        assert!(!contacts[1].communication_unavailable);
        assert!(contacts[1].sip_target().is_none());
        assert_eq!(contacts[1].phone_number, "+4912345678");
        assert_eq!(contacts[2].id, "mahmoud");
        assert!(!contacts[2].communication_unavailable);
        assert!(contacts[2].sip_target().is_none());
    }

    #[test]
    fn cloud_contacts_replace_live_call_targets_and_deleted_contacts() {
        let mut runtime = RuntimeLoop::new(RuntimeState::default());
        let contact = json!({"id": "contact-one", "name": "Nana", "sip_address": "sip:nana@example.com",
            "can_call": true, "can_receive": true, "is_primary": true, "aliases": ["grandma"]});
        let mut io = FakeLoopIo {
            messages: vec![(
                WorkerDomain::Cloud,
                WorkerEnvelope::event(
                    "cloud.config",
                    json!({"config": {"config_version": 1, "contacts": {"entries": [contact]}}}),
                ),
            )],
            ..FakeLoopIo::default()
        };
        runtime.run_once(&mut io);
        assert_eq!(runtime.state.call.contacts[0].title, "Nana");
        assert_eq!(runtime.state.call.contacts[0].id, "sip:nana@example.com");
        assert_eq!(runtime.state.call.contacts[0].aliases, vec!["grandma"]);
        assert!(io.sent.iter().any(|(domain, envelope)| {
            *domain == WorkerDomain::Ui && ui_runtime_patch_command(envelope.clone()).is_some()
        }));
        io.messages.push((
            WorkerDomain::Cloud,
            WorkerEnvelope::event(
                "cloud.config",
                json!({"config": {"config_version": 2, "contacts": {"entries": []}}}),
            ),
        ));
        runtime.run_once(&mut io);
        assert!(runtime.state.call.contacts.is_empty());
    }

    #[test]
    fn cloud_command_is_acked_only_after_worker_result() {
        let mut io = FakeLoopIo {
            messages: vec![(
                WorkerDomain::Cloud,
                WorkerEnvelope::event(
                    "cloud.command",
                    json!({
                        "command": {
                            "commandId": "wifi-command-1",
                            "command": "wifi_scan",
                            "payload": {}
                        }
                    }),
                ),
            )],
            ..FakeLoopIo::default()
        };
        let mut runtime = RuntimeLoop::new(RuntimeState::default());

        runtime.run_once(&mut io);

        assert!(io.sent.iter().any(|(domain, envelope)| {
            *domain == WorkerDomain::Network
                && envelope.message_type == "wifi_scan"
                && envelope.request_id.as_deref() == Some("wifi-command-1")
        }));
        assert!(!io.sent.iter().any(|(domain, envelope)| {
            *domain == WorkerDomain::Cloud && envelope.message_type == "cloud.ack"
        }));

        io.sent.clear();
        io.messages.push((
            WorkerDomain::Network,
            WorkerEnvelope::result(
                "wifi_state",
                Some("wifi-command-1".to_string()),
                json!({"state": {"status": "ready"}}),
            ),
        ));
        runtime.run_once(&mut io);

        let ack = io
            .sent
            .iter()
            .find(|(domain, envelope)| {
                *domain == WorkerDomain::Cloud && envelope.message_type == "cloud.ack"
            })
            .map(|(_, envelope)| envelope)
            .expect("worker result should produce cloud ACK");
        assert_eq!(ack.payload["command_id"], "wifi-command-1");
        assert_eq!(ack.payload["ok"], true);
        assert_eq!(ack.payload["payload"], json!({"command": "wifi_scan"}));
    }

    #[test]
    fn worker_error_produces_bounded_nack_without_error_message() {
        let mut runtime = RuntimeLoop::new(RuntimeState::default());
        let mut io = FakeLoopIo::default();
        runtime.dispatch_command(
            &mut io,
            RuntimeCommand::CorrelatedWorkerCommand {
                domain: WorkerDomain::Network,
                envelope: WorkerEnvelope::command("wifi_scan", None, json!({})),
                command_id: "wifi-command-2".to_string(),
                command_type: "wifi_scan".to_string(),
                timeout_ms: 10_000,
            },
        );
        io.sent.clear();
        io.messages.push((
            WorkerDomain::Network,
            WorkerEnvelope::error(
                "wifi_error",
                Some("wifi-command-2".to_string()),
                "wifi_scan_failed",
                "sensitive device detail must not cross the boundary",
            ),
        ));

        runtime.run_once(&mut io);

        let ack = io
            .sent
            .iter()
            .find(|(domain, envelope)| {
                *domain == WorkerDomain::Cloud && envelope.message_type == "cloud.ack"
            })
            .map(|(_, envelope)| envelope)
            .expect("worker error should produce cloud NACK");
        assert_eq!(ack.payload["ok"], false);
        assert_eq!(ack.payload["reason"], "wifi_scan_failed");
        assert!(!serde_json::to_string(ack)
            .expect("ACK should serialize")
            .contains("sensitive device detail"));
    }

    #[test]
    fn location_command_failures_nack_without_degrading_the_network_worker() {
        for code in [
            "gps_fix_timeout",
            "gsm_call_in_progress",
            "gps_disabled",
            "network_disabled",
        ] {
            let mut state = RuntimeState::default();
            state.mark_worker(WorkerDomain::Network, WorkerState::Running, "ready");
            let mut runtime = RuntimeLoop::new(state);
            let mut io = FakeLoopIo::default();
            runtime.dispatch_command(
                &mut io,
                RuntimeCommand::CorrelatedWorkerCommand {
                    domain: WorkerDomain::Network,
                    envelope: WorkerEnvelope::command("network.request_location", None, json!({})),
                    command_id: "location-1".into(),
                    command_type: "request_location".into(),
                    timeout_ms: 95_000,
                },
            );
            io.sent.clear();
            io.messages.push((
                WorkerDomain::Network,
                WorkerEnvelope::error(
                    "network.error",
                    Some("location-1".into()),
                    code,
                    "No location available",
                ),
            ));
            runtime.run_once(&mut io);
            assert_eq!(
                runtime.state().network_worker.state,
                WorkerState::Running,
                "command failure {code} must not degrade the worker"
            );
            assert_eq!(runtime.state().network_worker.last_reason, "ready");
            let acks: Vec<_> = io
                .sent
                .iter()
                .filter(|(domain, envelope)| {
                    *domain == WorkerDomain::Cloud && envelope.message_type == "cloud.ack"
                })
                .collect();
            assert_eq!(acks.len(), 1);
            assert_eq!(acks[0].1.payload["command_id"], "location-1");
            assert_eq!(acks[0].1.payload["ok"], false);
            assert_eq!(acks[0].1.payload["reason"], code);
            assert!(runtime.pending_worker_commands.is_empty());
        }
    }

    #[test]
    fn late_location_error_preserves_health_without_duplicate_nack() {
        let mut state = RuntimeState::default();
        state.mark_worker(WorkerDomain::Network, WorkerState::Running, "ready");
        let mut runtime = RuntimeLoop::new(state);
        let mut io = FakeLoopIo::default();
        runtime.dispatch_command(
            &mut io,
            RuntimeCommand::CorrelatedWorkerCommand {
                domain: WorkerDomain::Network,
                envelope: WorkerEnvelope::command("network.request_location", None, json!({})),
                command_id: "late-location".into(),
                command_type: "request_location".into(),
                timeout_ms: 0,
            },
        );
        runtime.run_once(&mut io);
        assert!(runtime.pending_worker_commands.is_empty());
        io.sent.clear();
        io.messages.push((
            WorkerDomain::Network,
            WorkerEnvelope::error(
                "network.error",
                Some("late-location".into()),
                "gps_fix_timeout",
                "No fix",
            ),
        ));
        runtime.run_once(&mut io);
        assert_eq!(runtime.state().network_worker.state, WorkerState::Running);
        assert!(!io
            .sent
            .iter()
            .any(|(domain, envelope)| *domain == WorkerDomain::Cloud
                && envelope.message_type == "cloud.ack"));

        // A real worker fault without command correlation still degrades it.
        io.messages.push((
            WorkerDomain::Network,
            WorkerEnvelope::error(
                "network.error",
                None,
                "input_read_failed",
                "Worker input failed",
            ),
        ));
        runtime.run_once(&mut io);
        assert_eq!(runtime.state().network_worker.state, WorkerState::Degraded);
        assert_eq!(
            runtime.state().network_worker.last_reason,
            "Worker input failed"
        );
    }

    #[test]
    fn protocol_fault_is_not_hidden_by_a_correlated_location_error() {
        let mut state = RuntimeState::default();
        state.mark_worker(WorkerDomain::Network, WorkerState::Running, "ready");
        let mut runtime = RuntimeLoop::new(state);
        let mut io = FakeLoopIo::default();
        io.protocol_errors.push((
            WorkerDomain::Network,
            WorkerProtocolError {
                raw_line: "broken envelope".into(),
                message: "invalid JSON".into(),
            },
        ));
        io.messages.push((
            WorkerDomain::Network,
            WorkerEnvelope::error(
                "network.error",
                Some("location".into()),
                "gps_fix_timeout",
                "No fix",
            ),
        ));
        runtime.run_once(&mut io);
        assert_eq!(runtime.state().network_worker.state, WorkerState::Degraded);
        assert_eq!(runtime.state().network_worker.protocol_errors, 1);
        assert!(runtime
            .state()
            .network_worker
            .last_reason
            .contains("protocol error"));
    }

    #[test]
    fn correlated_worker_timeout_produces_nack() {
        let mut runtime = RuntimeLoop::new(RuntimeState::default());
        let mut io = FakeLoopIo::default();
        runtime.dispatch_command(
            &mut io,
            RuntimeCommand::CorrelatedWorkerCommand {
                domain: WorkerDomain::Network,
                envelope: WorkerEnvelope::command("wifi_refresh", None, json!({})),
                command_id: "wifi-command-timeout".to_string(),
                command_type: "wifi_refresh".to_string(),
                timeout_ms: 0,
            },
        );
        io.sent.clear();

        runtime.run_once(&mut io);

        assert!(io.sent.iter().any(|(domain, envelope)| {
            *domain == WorkerDomain::Cloud
                && envelope.message_type == "cloud.ack"
                && envelope.payload["command_id"] == "wifi-command-timeout"
                && envelope.payload["reason"] == "worker_timeout"
        }));
    }
}
