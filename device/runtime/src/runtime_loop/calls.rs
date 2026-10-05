//! Runtime boundary for call policy, audio barriers, and supervised resource proof.
use super::{LoopIo, RuntimeLoop};
use crate::call_manager::effects::{domain_for, OperationPurpose, PendingOperation};
use crate::call_manager::{
    CallAction, CallCommand, CallEffect, CallManagerEvent, CallOffer, CallPhase, CallTransport,
    CallUpdate, InterruptForCall, SessionKey,
};
use crate::event::{RuntimeCommand, RuntimeEvent};
use crate::protocol::{EnvelopeKind, WorkerEnvelope};
use crate::state::{CallState, WorkerDomain, WorkerState};
use serde_json::{json, Value};
use std::collections::HashMap;
use yoyopod_protocol::ui::{CallIntent, CallMethod, ContactAction, UiCommand, UiIntent};
#[cfg(test)]
mod tests;

#[derive(Debug, Clone)]
struct Resources {
    interruption: InterruptForCall,
    media_prepared: bool,
    voip_prepared: bool,
    speech_cancelled: bool,
    route_ready: bool,
    native_released: bool,
    alert_stopped: bool,
    releases_started: bool,
    media_released: bool,
    voip_released: bool,
    native_owner: Option<String>,
    recovery_quarantined: bool,
}

#[derive(Debug, Clone)]
pub(super) struct CallIntegration {
    pub(super) native_guard: crate::call_manager::native_guard::NativeOperationGuard,
    resources: Option<Resources>,
    generations: HashMap<WorkerDomain, u64>,
    startup: HashMap<WorkerDomain, Vec<WorkerEnvelope>>,
    recoveries: HashMap<WorkerDomain, u8>,
    recovering: std::collections::HashSet<WorkerDomain>,
    native_owner: Option<String>,
    serial: u64,
    voice_enabled: bool,
    shutdown_deadline: Option<u64>,
    pending_alert: Option<crate::call_manager::RingtoneRequest>,
    ui_unavailable: bool,
}
impl Default for CallIntegration {
    fn default() -> Self {
        Self {
            native_guard: Default::default(),
            resources: None,
            generations: [
                (WorkerDomain::Voip, 1),
                (WorkerDomain::Network, 1),
                (WorkerDomain::Media, 1),
                (WorkerDomain::Voice, 1),
            ]
            .into(),
            startup: HashMap::new(),
            recoveries: HashMap::new(),
            recovering: Default::default(),
            native_owner: None,
            serial: 0,
            voice_enabled: true,
            shutdown_deadline: None,
            pending_alert: None,
            ui_unavailable: false,
        }
    }
}

impl RuntimeLoop {
    /// Establish generation fences and retain only configuration, never user actions.
    pub fn configure_workers(
        &mut self,
        io: &mut impl LoopIo,
        config: &crate::config::RuntimeConfig,
        generation: u64,
    ) {
        self.calls.voice_enabled = config.voice.worker_enabled;
        self.calls
            .generations
            .values_mut()
            .for_each(|value| *value = generation);
        self.calls.startup.insert(
            WorkerDomain::Media,
            vec![WorkerEnvelope::command(
                "media.configure",
                None,
                config.media.to_worker_payload(),
            )],
        );
        self.calls.startup.insert(
            WorkerDomain::Voip,
            vec![
                WorkerEnvelope::command("voip.configure", None, config.voip.to_worker_payload()),
                WorkerEnvelope::command("voip.register", None, json!({})),
            ],
        );
        self.calls.startup.insert(
            WorkerDomain::Network,
            vec![WorkerEnvelope::command(
                "network.configure",
                None,
                json!({}),
            )],
        );
        for domain in [
            WorkerDomain::Media,
            WorkerDomain::Voip,
            WorkerDomain::Network,
        ] {
            self.configure_call_worker(io, domain);
        }
        let mut payload = json!({});
        payload["voice_activity_generation"] = json!(self.state.voice.activity_generation);
        self.dispatch_command(
            io,
            RuntimeCommand::WorkerCommand {
                domain: WorkerDomain::Media,
                envelope: WorkerEnvelope::command("media.start", None, payload),
            },
        );
    }

    fn configure_call_worker(&mut self, io: &mut impl LoopIo, domain: WorkerDomain) {
        for mut envelope in self.calls.startup.get(&domain).cloned().unwrap_or_default() {
            if envelope.message_type.ends_with("configure") {
                envelope.payload["worker_generation"] = json!(self.calls.generations[&domain]);
                envelope.payload["recovery_quarantined"] = json!(
                    domain == WorkerDomain::Network
                        && (self.calls.native_guard.quarantined()
                            || self
                                .calls
                                .resources
                                .as_ref()
                                .is_some_and(|r| r.recovery_quarantined))
                );
                envelope.request_id = Some(format!(
                    "configure-{}-{}",
                    domain.as_str(),
                    self.calls.generations[&domain]
                ));
            }
            if !io.send_worker_envelope(domain, envelope) {
                self.state.mark_worker(
                    domain,
                    WorkerState::Degraded,
                    "recovery configuration dispatch failed",
                );
            }
        }
    }

    pub fn begin_shutdown(&mut self, io: &mut impl LoopIo, now_ms: u64) {
        self.now_ms = self.now_ms.max(now_ms);
        if self.calls.shutdown_deadline.is_none() {
            self.calls.shutdown_deadline = Some(self.now_ms.saturating_add(8_000));
            self.shutdown_requested = true;
            self.handle_call(io, CallManagerEvent::Shutdown);
        }
        // The caller performs a bounded drain; emergency power-off retains its own deadline.
        self.shutdown_requested = true;
    }

    pub fn shutdown_cleanup_pending(&self) -> bool {
        self.manager.session().is_some()
            && self
                .calls
                .shutdown_deadline
                .is_some_and(|d| self.now_ms < d)
    }

    fn valid_key(&self, domain: WorkerDomain, key: &SessionKey) -> bool {
        domain_for(&key.transport) == domain
            && self.calls.generations.get(&domain) == Some(&key.generation)
    }

    pub(super) fn guard_native_dispatch(&mut self, envelope: &WorkerEnvelope) -> bool {
        let Ok(key) = serde_json::from_value::<SessionKey>(envelope.payload["key"].clone()) else {
            return false;
        };
        let native_owner = self
            .calls
            .resources
            .as_ref()
            .filter(|r| r.interruption.key == key)
            .map(|r| r.native_owner.as_deref())
            .unwrap_or(self.calls.native_owner.as_deref());
        match self.calls.native_guard.before_dispatch(&key, native_owner) {
            Ok(()) => true,
            Err(error) => {
                self.state.mark_worker(
                    WorkerDomain::Network,
                    WorkerState::Degraded,
                    format!("native call dispatch blocked: {error}"),
                );
                false
            }
        }
    }

    fn clear_native_guard(&mut self) {
        if let Err(error) = self
            .calls
            .native_guard
            .clear_if_released(self.manager.session().is_none() && self.calls.resources.is_none())
        {
            self.calls.native_guard.quarantine();
            self.state
                .mark_worker(WorkerDomain::Network, WorkerState::Degraded, error);
        }
    }

    pub(super) fn intercept_call_message(
        &mut self,
        io: &mut impl LoopIo,
        domain: WorkerDomain,
        envelope: &WorkerEnvelope,
    ) -> bool {
        if domain == WorkerDomain::Ui
            && envelope.message_type == "ui.error"
            && envelope.payload["code"] == "worker_error"
        {
            // This code is emitted only on fatal handle_app_event failure, before exit.
            self.calls.ui_unavailable = true;
            self.end_for_audio_failure(io);
        }
        if self.calls.recovering.contains(&domain) {
            // Messages already drained before retirement still belong to its old lifetime.
            return true;
        }
        if let Some((operation, ok)) = self.call_operations.result(domain, envelope) {
            self.finish_call_operation(io, operation, ok, &envelope.payload);
            return true;
        }
        // Never let stale call results consume cloud correlation or alter generic state.
        if envelope.message_type.starts_with("call.") {
            match envelope.message_type.as_str() {
                "call.offer" if envelope.kind == EnvelopeKind::Event => {
                    if let Ok(offer) = serde_json::from_value::<CallOffer>(envelope.payload.clone())
                    {
                        if self.valid_key(domain, &offer.key) {
                            self.handle_call(io, CallManagerEvent::Offer(offer));
                        }
                    }
                }
                "call.update" if envelope.kind == EnvelopeKind::Event => {
                    if let Ok(update) =
                        serde_json::from_value::<CallUpdate>(envelope.payload.clone())
                    {
                        if self.valid_key(domain, &update.key) {
                            self.handle_call(io, CallManagerEvent::Update(update));
                            self.clear_native_guard();
                        }
                    }
                }
                "call.cleanup"
                    if domain == WorkerDomain::Voip && envelope.kind == EnvelopeKind::Event =>
                {
                    if let Ok(key) =
                        serde_json::from_value::<SessionKey>(envelope.payload["key"].clone())
                    {
                        if self.valid_key(domain, &key)
                            && self.manager.session() == Some(&key)
                            && envelope.payload["released"] == true
                        {
                            if let Some(r) = self.calls.resources.as_mut() {
                                r.native_released = true;
                            }
                            self.confirm_call_cleanup(io);
                        }
                    }
                }
                "call.reconciled"
                    if domain == WorkerDomain::Network
                        && envelope.kind == EnvelopeKind::Event
                        && envelope.payload["generation"].as_u64()
                            == self.calls.generations.get(&domain).copied() =>
                {
                    self.calls.native_owner =
                        envelope.payload["native_owner"].as_str().map(str::to_owned);
                    // A pre-dispatch empty-cache observation can be queued behind a new
                    // outgoing request. Only the exact key's terminal fact releases it.
                    // Recovery uncertainty survives even same-owner empty observations.
                }
                _ => {}
            }
            return true;
        }
        // Also consume retired typed audio acks; their request IDs cannot become generic ACKs.
        envelope
            .request_id
            .as_deref()
            .is_some_and(|id| id.starts_with("managed-"))
            && matches!(envelope.kind, EnvelopeKind::Result | EnvelopeKind::Error)
    }

    pub(super) fn intercept_call_event(
        &mut self,
        io: &mut impl LoopIo,
        event: &RuntimeEvent,
    ) -> bool {
        match event {
            RuntimeEvent::WorkerReady {
                domain: WorkerDomain::Ui,
            } => {
                self.calls.ui_unavailable = false;
                false
            }
            RuntimeEvent::WorkerExited {
                domain: WorkerDomain::Ui,
                ..
            } => {
                self.calls.ui_unavailable = true;
                self.end_for_audio_failure(io);
                false
            }
            RuntimeEvent::AudioRouteLocal(route) if self.manager.session().is_some() => {
                let before = self.state.clone();
                self.state.apply_audio_route_local(route);
                for command in crate::event::commands_for_event(&self.state, event) {
                    if !matches!(&command,RuntimeCommand::WorkerCommand{envelope,..} if envelope.message_type=="media.set_alert_output")
                    {
                        self.dispatch_command(io, command);
                    }
                }
                if let Some(r) = self.calls.resources.as_mut() {
                    r.route_ready = false;
                    let command = self.call_operations.command(
                        &r.interruption.key,
                        OperationPurpose::AlertRoute,
                        WorkerDomain::Media,
                        "media.set_alert_output",
                        self.state.audio_route.clone(),
                        self.now_ms,
                    );
                    self.dispatch_command(io, command);
                }
                self.send_runtime_snapshot_patches(io, &before);
                true
            }
            RuntimeEvent::UiIntent(UiIntent::Call(CallIntent::Session(command))) => {
                self.handle_call(io, CallManagerEvent::UserAction(command.clone()));
                true
            }
            RuntimeEvent::UiIntent(UiIntent::Call(CallIntent::Start(action))) => {
                self.request_outgoing(io, action.clone());
                true
            }
            RuntimeEvent::UiIntent(UiIntent::Call(_)) => true,
            RuntimeEvent::WorkerExited { domain, .. } => {
                if self.calls.resources.is_some()
                    && matches!(
                        domain,
                        WorkerDomain::Media
                            | WorkerDomain::Voip
                            | WorkerDomain::Network
                            | WorkerDomain::Voice
                    )
                {
                    let responsible = self
                        .manager
                        .session()
                        .is_some_and(|key| domain_for(&key.transport) == *domain)
                        || matches!(domain, WorkerDomain::Media | WorkerDomain::Voip)
                        || (*domain == WorkerDomain::Voice && self.calls.voice_enabled);
                    if responsible {
                        self.end_for_audio_failure(io);
                        self.recover_call_worker(io, *domain);
                    }
                }
                false
            }
            RuntimeEvent::UiIntent(UiIntent::Music(_) | UiIntent::Voice(_))
            | RuntimeEvent::UiFocusChanged(_)
            | RuntimeEvent::VoiceTranscript(_)
            | RuntimeEvent::VoiceAskResult(_)
            | RuntimeEvent::VoiceSpeakResult(_)
            | RuntimeEvent::VoiceFocusPromptResult { .. }
                if self.manager.session().is_some() =>
            {
                true
            }
            _ => false,
        }
    }

    pub(super) fn block_call_conflicting_command(
        &mut self,
        io: &mut impl LoopIo,
        command: &RuntimeCommand,
    ) -> bool {
        let envelope = match command {
            RuntimeCommand::WorkerCommand { envelope, .. }
            | RuntimeCommand::CorrelatedWorkerCommand { envelope, .. } => envelope,
            _ => return false,
        };
        let legacy_call = matches!(
            envelope.message_type.as_str(),
            "voip.dial"
                | "gsm.dial"
                | "voip.answer"
                | "voip.reject"
                | "voip.hangup"
                | "voip.set_mute"
                | "gsm.answer"
                | "gsm.hangup"
                | "gsm.reject"
                | "gsm.set_mute"
        );
        let start = yoyopod_protocol::audio::is_audio_start(&envelope.message_type);
        let audio_test = matches!(
            envelope.message_type.as_str(),
            "audio_test_output" | "audio_test_input"
        );
        let stale = start
            && envelope.payload["voice_activity_generation"].as_u64()
                != Some(self.state.voice.activity_generation);
        let blocked = legacy_call
            || stale
            || ((start || audio_test)
                && (self.manager.session().is_some() || self.shutdown_requested));
        if blocked {
            if let RuntimeCommand::CorrelatedWorkerCommand {
                command_id,
                command_type,
                ..
            } = command
            {
                self.send_command_ack(io, command_id, command_type, false, Some("call_busy"));
            }
        }
        blocked
    }

    pub(super) fn request_outgoing(&mut self, io: &mut impl LoopIo, action: ContactAction) {
        if self.manager.session().is_some()
            || self.calls.ui_unavailable
            || self.shutdown_requested
            || self.calls.native_guard.blocked()
        {
            return;
        }
        let Some(address) = self
            .state
            .approved_call_target(&action.id, action.method)
            .map(str::to_owned)
        else {
            return;
        };
        if action.method == CallMethod::Gsm && !self.state.call.gsm_available {
            return;
        }
        let Some(contact) = self.state.call.contacts.iter().find(|c| c.id == action.id) else {
            return;
        };
        let contact_id = contact.contact_id.clone();
        let transport = if action.method == CallMethod::Gsm {
            CallTransport::Gsm
        } else {
            CallTransport::Sip
        };
        self.calls.serial = self
            .calls
            .serial
            .checked_add(1)
            .expect("outgoing counter exhausted");
        let key = SessionKey {
            generation: self.calls.generations[&domain_for(&transport)],
            transport,
            call_id: format!("runtime-outgoing-{}", self.calls.serial),
        };
        self.handle_call(
            io,
            CallManagerEvent::RequestOutgoing {
                key,
                contact_id,
                address,
            },
        );
    }

    pub(super) fn handle_call(&mut self, io: &mut impl LoopIo, event: CallManagerEvent) {
        let before = self.state.clone();
        let effects = self.manager.handle(
            event,
            &self.state.call_context(
                self.shutdown_requested
                    || self.calls.ui_unavailable
                    || (self.manager.session().is_none() && self.calls.native_guard.blocked()),
            ),
            self.now_ms,
        );
        // Publish policy immediately, before any effect can synchronously fail and recurse.
        self.project_call();
        self.send_runtime_snapshot_patches(io, &before);
        if before.call.state != self.state.call.state
            || before.call.session != self.state.call.session
        {
            self.dispatch_command(io,RuntimeCommand::WorkerCommand{domain:WorkerDomain::Cloud,
                envelope:WorkerEnvelope::command("cloud.publish_telemetry",None,json!({"topic_suffix":"call.state","qos":0,
                    "payload":{"entity":"call.state","value":self.state.call.state.as_str(),
                        "attrs":{"call_state":self.state.call.state.as_str(),"active_call_peer":self.state.call.peer_address,
                            "session":self.state.call.session},"ts":crate::runtime_loop::current_epoch_seconds()}}))});
        }
        for effect in effects {
            self.execute_call_effect(io, effect);
        }
        self.confirm_call_cleanup(io);
    }

    pub(super) fn project_call(&mut self) {
        if self.calls.native_guard.quarantined() {
            self.state.call.gsm_available = false;
            self.state.call.gsm_unavailable_reason = "native call recovery required".into();
            self.state.overlay.error = "native_call_recovery_required".into();
            self.state.overlay.code = "native_call_recovery_required".into();
            self.state.overlay.message = "Call recovery required".into();
        }
        self.state.call.session = self.manager.session().cloned();
        self.state.call.session_phase = self.manager.phase();
        self.state.call.accept_enabled = self.manager.accept_enabled();
        self.state.call.alert_audible = self.manager.alert_audible();
        if let Some(key) = self.manager.session() {
            self.state.call.method = if key.transport == CallTransport::Gsm {
                CallMethod::Gsm
            } else {
                CallMethod::Sip
            };
            self.state.call.state = match self.manager.phase() {
                Some(CallPhase::Active | CallPhase::Held) => CallState::Active,
                _ if self.manager.incoming() => CallState::Incoming,
                _ => CallState::Outgoing,
            };
            if let Some(contact) = self.manager.admitted_identity() {
                self.state.call.peer_name = contact.name.clone();
                self.state.call.peer_address = if key.transport == CallTransport::Gsm {
                    contact.phone_number.clone()
                } else {
                    contact.sip_address.clone()
                };
            }
        } else {
            self.state.call.state = CallState::Idle;
            self.state.call.peer_name.clear();
            self.state.call.peer_address.clear();
            self.state.call.duration_text.clear();
            self.state.call.muted = false;
        }
    }
}
mod operations;
mod recovery;
