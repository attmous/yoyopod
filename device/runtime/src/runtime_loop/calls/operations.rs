//! Translate policy effects and resolve typed operation results.
use super::*;
impl RuntimeLoop {
    pub(in crate::runtime_loop) fn execute_call_effect(
        &mut self,
        io: &mut impl LoopIo,
        effect: CallEffect,
    ) {
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
                if !self.calls.resources.as_ref().is_some_and(|r| r.route_ready) {
                    self.calls.pending_alert = Some(request);
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
                if self.calls.pending_alert.take().is_some() {
                    self.handle_call(
                        io,
                        CallManagerEvent::RingtoneStopped {
                            key: request.key,
                            ok: true,
                        },
                    );
                    return;
                }
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
                self.calls.pending_alert = None;
                self.clear_native_guard();
                self.calls.recoveries.clear();
                return;
            }
            CallEffect::Publish => return,
        };
        self.dispatch_command(io, command);
    }

    pub(in crate::runtime_loop) fn finish_call_operation(
        &mut self,
        io: &mut impl LoopIo,
        operation: PendingOperation,
        ok: bool,
        payload: &Value,
    ) {
        let before = self.state.clone();
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
                    if operation.purpose == OperationPurpose::AlertRoute {
                        if let Some(request) = self.calls.pending_alert.take() {
                            if self.manager.phase() == Some(CallPhase::Ringing)
                                && self.manager.alert_audible()
                            {
                                self.execute_call_effect(io, CallEffect::StartRingtone(request));
                            }
                        }
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
            OperationPurpose::Native(CallAction::SetMute(muted))
                if ok && self.manager.phase() == Some(CallPhase::Active) =>
            {
                self.state.call.muted = muted;
            }
            _ => {
                if let Some(event) =
                    crate::call_manager::effects::CallOperationLedger::native_event(&operation, ok)
                {
                    self.handle_call(io, event);
                }
            }
        }
        self.confirm_call_cleanup(io);
        self.send_runtime_snapshot_patches(io, &before);
    }

    pub(in crate::runtime_loop) fn end_for_audio_failure(&mut self, io: &mut impl LoopIo) {
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
}
