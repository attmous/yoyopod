//! Retain ownership until native and local resource release is proven.
use super::*;
use crate::worker::RecoveryStatus;
impl RuntimeLoop {
    pub(in crate::runtime_loop) fn confirm_call_cleanup(&mut self, io: &mut impl LoopIo) {
        if !self.calls.recovering.is_empty() {
            return;
        }
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

    pub(in crate::runtime_loop) fn recover_call_worker(
        &mut self,
        io: &mut impl LoopIo,
        domain: WorkerDomain,
    ) {
        if self.shutdown_requested || self.calls.recovering.contains(&domain) {
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
        if domain == WorkerDomain::Network {
            self.calls.native_guard.quarantine();
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
        self.calls.recovering.insert(domain);
        let status = io.recover_worker(domain);
        self.finish_worker_recovery(io, domain, status);
    }

    pub(in crate::runtime_loop) fn poll_call_recoveries(&mut self, io: &mut impl LoopIo) {
        if self.shutdown_requested {
            return;
        }
        for domain in self.calls.recovering.clone() {
            let status = io.poll_worker_recovery(domain);
            self.finish_worker_recovery(io, domain, status);
        }
    }

    fn finish_worker_recovery(
        &mut self,
        io: &mut impl LoopIo,
        domain: WorkerDomain,
        status: Result<RecoveryStatus, String>,
    ) {
        match status {
            Ok(RecoveryStatus::Pending) => return,
            Err(reason) => {
                self.calls.recovering.remove(&domain);
                self.state.mark_worker(
                    domain,
                    WorkerState::Degraded,
                    format!("call recovery failed: {reason}"),
                );
                return;
            }
            Ok(RecoveryStatus::Ready) => {
                self.calls.recovering.remove(&domain);
            }
        }
        let generation = *self.calls.generations.get(&domain).unwrap_or(&1);
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
