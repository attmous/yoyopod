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
    resources: Option<Resources>,
    generations: HashMap<WorkerDomain, u64>,
    startup: HashMap<WorkerDomain, Vec<WorkerEnvelope>>,
    recoveries: HashMap<WorkerDomain, u8>,
    native_owner: Option<String>,
    serial: u64,
    voice_enabled: bool,
    shutdown_deadline: Option<u64>,
}
impl Default for CallIntegration {
    fn default() -> Self {
        Self {
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
            native_owner: None,
            serial: 0,
            voice_enabled: true,
            shutdown_deadline: None,
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
                        && self
                            .calls
                            .resources
                            .as_ref()
                            .is_some_and(|r| r.recovery_quarantined)
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

    pub(super) fn intercept_call_message(
        &mut self,
        io: &mut impl LoopIo,
        domain: WorkerDomain,
        envelope: &WorkerEnvelope,
    ) -> bool {
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
                            if self.manager.session() == Some(&update.key) {
                                // GSM Ended is emitted after native terminal proof AND local PCM join.
                                // SIP Ended retains refs; its distinct Released fact is required.
                                if update.phase == CallPhase::Ended
                                    && domain == WorkerDomain::Network
                                {
                                    if let Some(r) = self.calls.resources.as_mut() {
                                        r.native_released = true;
                                    }
                                }
                                self.state.call.muted = update.muted;
                                self.state.call.duration_text = format!(
                                    "{}:{:02}",
                                    update.duration_seconds / 60,
                                    update.duration_seconds % 60
                                );
                            }
                            self.handle_call(io, CallManagerEvent::Update(update));
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
                    if domain == WorkerDomain::Network && envelope.kind == EnvelopeKind::Event =>
                {
                    if envelope.payload["generation"].as_u64()
                        == self.calls.generations.get(&domain).copied()
                    {
                        self.calls.native_owner =
                            envelope.payload["native_owner"].as_str().map(str::to_owned);
                        if let Some(r) = self.calls.resources.as_mut() {
                            if r.interruption.key.transport == CallTransport::Gsm
                                && !r.recovery_quarantined
                                && r.native_owner.is_some()
                                && r.native_owner == self.calls.native_owner
                                && envelope.payload["native_calls_quiescent"] == true
                                && envelope.payload["audio_released"] == true
                            {
                                r.native_released = true;
                            }
                        }
                        self.confirm_call_cleanup(io);
                    }
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
        let stale = start
            && envelope.payload["voice_activity_generation"].as_u64()
                != Some(self.state.voice.activity_generation);
        let blocked = legacy_call
            || stale
            || (start && (self.manager.session().is_some() || self.shutdown_requested));
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
        if self.manager.session().is_some() || self.shutdown_requested {
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
            &self.state.call_context(self.shutdown_requested),
            self.now_ms,
        );
        // Publish policy immediately, before any effect can synchronously fail and recurse.
        self.project_call();
        self.send_runtime_snapshot_patches(io, &before);
        for effect in effects {
            self.execute_call_effect(io, effect);
        }
        self.confirm_call_cleanup(io);
    }

    fn project_call(&mut self) {
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

    fn execute_call_effect(&mut self, io: &mut impl LoopIo, effect: CallEffect) {
        let command = match effect {
            CallEffect::PrepareAudio(mut request) => {
                if self.manager.session() != Some(&request.key)
                    || self.manager.phase() != Some(CallPhase::Preparing)
                {
                    return;
                }
                request.voice_activity_generation = self.state.voice.invalidate_for_call();
                self.state.focus_prompt_request_id = None;
                self.calls.resources = Some(Resources {
                    interruption: request.clone(),
                    media_prepared: false,
                    voip_prepared: false,
                    speech_cancelled: !self.calls.voice_enabled,
                    route_ready: false,
                    native_released: false,
                    alert_stopped: true,
                    releases_started: false,
                    media_released: false,
                    voip_released: false,
                    native_owner: self.calls.native_owner.clone(),
                    recovery_quarantined: false,
                });
                // This signal is bookkeeping only; raw offers never populate history.
                if request.key.transport == CallTransport::Sip && self.manager.incoming() {
                    let admit = self.call_operations.command(
                        &request.key,
                        OperationPurpose::Admit,
                        WorkerDomain::Voip,
                        "call.admit",
                        json!({"key": request.key}),
                        self.now_ms,
                    );
                    self.dispatch_command(io, admit);
                }
                let commands = [
                    self.call_operations
                        .interrupt(&request, WorkerDomain::Media, self.now_ms),
                    self.call_operations
                        .interrupt(&request, WorkerDomain::Voip, self.now_ms),
                    self.call_operations.command(
                        &request.key,
                        OperationPurpose::AlertRoute,
                        WorkerDomain::Media,
                        "media.set_alert_output",
                        self.state.audio_route.clone(),
                        self.now_ms,
                    ),
                ];
                for command in commands {
                    self.dispatch_command(io, command);
                }
                if self.calls.voice_enabled {
                    let cancel = self.call_operations.command(
                        &request.key,
                        OperationPurpose::CancelSpeech,
                        WorkerDomain::Voice,
                        "voice.cancel",
                        json!({}),
                        self.now_ms,
                    );
                    self.dispatch_command(io, cancel);
                }
                return;
            }
            CallEffect::StartRingtone(mut request) => {
                if self.manager.session() != Some(&request.key) {
                    return;
                }
                request.lease_ms = self.manager.remaining_ring_ms(self.now_ms);
                if request.lease_ms == 0 {
                    self.handle_call(io, CallManagerEvent::Tick);
                    return;
                }
                request.operation_generation = self.call_operations.next_alert(&request.key);
                if let Some(r) = self.calls.resources.as_mut() {
                    r.alert_stopped = false;
                }
                self.call_operations.command(
                    &request.key,
                    OperationPurpose::StartRingtone(request.operation_generation),
                    WorkerDomain::Media,
                    "media.ringtone_start",
                    json!(request),
                    self.now_ms,
                )
            }
            CallEffect::StopRingtone(mut request) => {
                let Some(epoch) = self.call_operations.stop_alert(&request.key) else {
                    return;
                };
                request.operation_generation = epoch;
                self.call_operations.command(
                    &request.key,
                    OperationPurpose::StopRingtone(epoch),
                    WorkerDomain::Media,
                    "media.ringtone_stop",
                    json!(request),
                    self.now_ms,
                )
            }
            CallEffect::Transport(command) => {
                let domain = domain_for(&command.key.transport);
                if !self.valid_key(domain, &command.key) {
                    return;
                }
                let purpose = if self.manager.session() == Some(&command.key) {
                    OperationPurpose::Native(command.action.clone())
                } else {
                    OperationPurpose::Secondary(command.action.clone(), 0)
                };
                self.call_operations.command(
                    &command.key,
                    purpose,
                    domain,
                    "call.action",
                    json!(command),
                    self.now_ms,
                )
            }
            CallEffect::Dial { key, address } => {
                if self.manager.session() != Some(&key)
                    || self.manager.phase() != Some(CallPhase::Outgoing)
                {
                    return;
                }
                self.call_operations.command(
                    &key,
                    OperationPurpose::Dial,
                    domain_for(&key.transport),
                    "call.dial",
                    json!({"key": key, "address": address}),
                    self.now_ms,
                )
            }
            CallEffect::WakeDisplay(key) => {
                if self.manager.session() != Some(&key) {
                    return;
                }
                RuntimeCommand::WorkerCommand {
                    domain: WorkerDomain::Ui,
                    envelope: UiCommand::SetBacklight {
                        brightness: self.state.display_brightness,
                    }
                    .into_envelope(),
                }
            }
            CallEffect::RecoverTransport {
                transport,
                generation,
            } => {
                let domain = domain_for(&transport);
                if self.calls.generations[&domain] != generation {
                    return;
                }
                RuntimeCommand::RecoverWorker { domain }
            }
            CallEffect::RestoreUi(key) => {
                self.call_operations.invalidate(&key);
                self.calls.resources = None;
                self.calls.recoveries.clear();
                return;
            }
            CallEffect::Publish => return,
        };
        self.dispatch_command(io, command);
    }

    pub(super) fn finish_call_operation(
        &mut self,
        io: &mut impl LoopIo,
        operation: PendingOperation,
        ok: bool,
        payload: &Value,
    ) {
        if !self.call_operations.is_current(&operation) {
            return;
        }
        if let OperationPurpose::Secondary(action, attempt) = &operation.purpose {
            if !ok && *attempt < 1 && self.valid_key(operation.domain, &operation.key) {
                let command = CallCommand {
                    key: operation.key.clone(),
                    action: action.clone(),
                };
                let retry = self.call_operations.command(
                    &operation.key,
                    OperationPurpose::Secondary(action.clone(), attempt + 1),
                    operation.domain,
                    "call.action",
                    json!(command),
                    self.now_ms,
                );
                self.dispatch_command(io, retry);
            } else if !ok {
                self.state.mark_worker(
                    operation.domain,
                    WorkerState::Degraded,
                    "secondary call rejection failed; primary retained",
                );
            }
            return;
        }
        if self.manager.session() != Some(&operation.key) {
            return;
        }
        match operation.purpose {
            OperationPurpose::PrepareMedia
            | OperationPurpose::PrepareVoip
            | OperationPurpose::CancelSpeech
            | OperationPurpose::AlertRoute => {
                if ok {
                    if let Some(r) = self.calls.resources.as_mut() {
                        match operation.purpose {
                            OperationPurpose::PrepareMedia => {
                                r.media_prepared = true;
                                if matches!(
                                    self.state.media.playback_state.as_str(),
                                    "playing" | "paused"
                                ) {
                                    self.state.media.playback_state = "paused".into();
                                }
                            }
                            OperationPurpose::PrepareVoip => {
                                r.voip_prepared = true;
                                if let Some(path) = payload["draft_path"].as_str() {
                                    self.state.voice.interrupted_draft_path = Some(path.to_owned());
                                }
                            }
                            OperationPurpose::CancelSpeech => r.speech_cancelled = true,
                            OperationPurpose::AlertRoute => r.route_ready = true,
                            _ => {}
                        }
                    }
                    if self.calls.resources.as_ref().is_some_and(|r| {
                        r.media_prepared && r.voip_prepared && r.speech_cancelled && r.route_ready
                    }) {
                        self.handle_call(
                            io,
                            CallManagerEvent::AudioPrepared {
                                key: operation.key,
                                ok: true,
                            },
                        );
                    }
                } else {
                    self.end_for_audio_failure(io);
                    self.recover_call_worker(io, operation.domain);
                }
            }
            OperationPurpose::StartRingtone(_) => {
                self.handle_call(
                    io,
                    CallManagerEvent::RingtoneStarted {
                        key: operation.key,
                        ok,
                    },
                );
                if !ok {
                    self.recover_call_worker(io, WorkerDomain::Media);
                }
            }
            OperationPurpose::StopRingtone(_) => {
                if let Some(r) = self.calls.resources.as_mut() {
                    r.alert_stopped = ok;
                }
                self.handle_call(
                    io,
                    CallManagerEvent::RingtoneStopped {
                        key: operation.key,
                        ok,
                    },
                );
                if !ok {
                    self.recover_call_worker(io, WorkerDomain::Media);
                }
            }
            OperationPurpose::ReleaseMedia | OperationPurpose::ReleaseVoip => {
                if let Some(r) = self.calls.resources.as_mut() {
                    if operation.purpose == OperationPurpose::ReleaseMedia {
                        r.media_released = ok;
                    } else {
                        r.voip_released = ok;
                    }
                }
                if !ok {
                    self.recover_call_worker(io, operation.domain);
                }
            }
            OperationPurpose::Admit if !ok => self.end_for_audio_failure(io),
            _ => {
                if let Some(event) =
                    crate::call_manager::effects::CallOperationLedger::native_event(&operation, ok)
                {
                    self.handle_call(io, event);
                }
            }
        }
        self.confirm_call_cleanup(io);
    }

    fn end_for_audio_failure(&mut self, io: &mut impl LoopIo) {
        if let Some(key) = self.manager.session().cloned() {
            self.handle_call(
                io,
                CallManagerEvent::UserAction(CallCommand {
                    key,
                    action: CallAction::Hangup,
                }),
            );
        }
    }

    pub(super) fn confirm_call_cleanup(&mut self, io: &mut impl LoopIo) {
        if self.manager.phase() != Some(CallPhase::Ending) {
            return;
        }
        let Some(r) = self.calls.resources.as_mut() else {
            return;
        };
        if !r.native_released
            || !r.alert_stopped
            || !r.media_prepared
            || !r.voip_prepared
            || !r.speech_cancelled
        {
            return;
        }
        if !r.releases_started {
            r.releases_started = true;
            let request = r.interruption.clone();
            let mut commands = Vec::new();
            if !r.media_released {
                commands.push(self.call_operations.command(
                    &request.key,
                    OperationPurpose::ReleaseMedia,
                    WorkerDomain::Media,
                    "media.release_call",
                    json!(request),
                    self.now_ms,
                ));
            }
            if !r.voip_released {
                commands.push(self.call_operations.command(
                    &request.key,
                    OperationPurpose::ReleaseVoip,
                    WorkerDomain::Voip,
                    "voip.release_call",
                    json!(request),
                    self.now_ms,
                ));
            }
            for command in commands {
                self.dispatch_command(io, command);
            }
        } else if r.media_released && r.voip_released {
            let key = r.interruption.key.clone();
            self.handle_call(io, CallManagerEvent::CleanupConfirmed(key));
        }
    }

    pub(super) fn recover_call_worker(&mut self, io: &mut impl LoopIo, domain: WorkerDomain) {
        if self.shutdown_requested {
            return;
        }
        let attempts = self.calls.recoveries.entry(domain).or_default();
        if *attempts >= 2 {
            self.state.mark_worker(
                domain,
                WorkerState::Degraded,
                "call recovery requires intervention",
            );
            return;
        }
        *attempts += 1;
        let generation = *self.calls.generations.get(&domain).unwrap_or(&1);
        if domain == WorkerDomain::Network {
            if let Some(r) = self
                .calls
                .resources
                .as_mut()
                .filter(|r| r.interruption.key.transport == CallTransport::Gsm)
            {
                // MM authorization/dispatch can outlive its client with no proved total deadline.
                // Preserve uncertainty in the replacement's startup gate as well as this owner.
                r.recovery_quarantined = true;
                r.native_released = false;
            }
        }
        self.call_operations.invalidate_domain(domain);
        if let Err(reason) = io.recover_worker(domain) {
            self.state.mark_worker(
                domain,
                WorkerState::Degraded,
                format!("call recovery failed: {reason}"),
            );
            return;
        }
        self.calls.generations.insert(
            domain,
            generation
                .checked_add(1)
                .expect("worker generation exhausted"),
        );
        self.configure_call_worker(io, domain);
        if let Some(r) = self.calls.resources.as_mut() {
            r.releases_started = false;
            if domain == WorkerDomain::Media {
                r.media_prepared = false;
                r.media_released = false;
                r.route_ready = false;
                r.alert_stopped = true;
            } else if domain == WorkerDomain::Voip {
                r.voip_prepared = false;
                r.voip_released = false;
                // Successful supervisor recovery joined all old native/helper processes.
                if r.interruption.key.transport == CallTransport::Sip {
                    r.native_released = true;
                }
            } else if domain == WorkerDomain::Voice {
                r.speech_cancelled = false;
            }
            let request = r.interruption.clone();
            if matches!(domain, WorkerDomain::Media | WorkerDomain::Voip) {
                let interrupt = self
                    .call_operations
                    .interrupt(&request, domain, self.now_ms);
                self.dispatch_command(io, interrupt);
            }
            if domain == WorkerDomain::Media {
                for command in crate::event::commands_for_event(
                    &self.state,
                    &RuntimeEvent::AudioRouteLocal(self.state.audio_route.clone()),
                ) {
                    if matches!(&command, RuntimeCommand::WorkerCommand { domain: WorkerDomain::Media, envelope }
                        if envelope.message_type != "media.set_alert_output")
                    {
                        self.dispatch_command(io, command);
                    }
                }
                self.handle_call(
                    io,
                    CallManagerEvent::RingtoneStopped {
                        key: request.key.clone(),
                        ok: true,
                    },
                );
                let route = self.call_operations.command(
                    &request.key,
                    OperationPurpose::AlertRoute,
                    domain,
                    "media.set_alert_output",
                    self.state.audio_route.clone(),
                    self.now_ms,
                );
                self.dispatch_command(io, route);
            } else if domain == WorkerDomain::Voip {
                self.dispatch_command(
                    io,
                    RuntimeCommand::WorkerCommand {
                        domain,
                        envelope: WorkerEnvelope::command(
                            "voip.set_audio_devices",
                            None,
                            self.state.audio_route.clone(),
                        ),
                    },
                );
            } else if domain == WorkerDomain::Voice {
                let cancel = self.call_operations.command(
                    &request.key,
                    OperationPurpose::CancelSpeech,
                    domain,
                    "voice.cancel",
                    json!({}),
                    self.now_ms,
                );
                self.dispatch_command(io, cancel);
            }
        }
    }
}
