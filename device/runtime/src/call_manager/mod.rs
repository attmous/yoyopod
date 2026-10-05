//! Pure call ownership, admission, and lifecycle policy. Effects are executed by runtime.
pub mod effects;
pub mod identity;
pub mod native_guard;
mod policy;
#[cfg(test)]
mod tests;
pub use yoyopod_protocol::call::*;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ContactIdentity {
    pub contact_id: String,
    pub name: String,
    pub sip_address: String,
    pub phone_number: String,
    pub priority: bool,
}
pub struct CallContext {
    pub contacts: Vec<ContactIdentity>,
    pub shutdown: bool,
}
pub enum CallManagerEvent {
    RingtoneStarted {
        key: SessionKey,
        ok: bool,
    },
    RingtoneStopped {
        key: SessionKey,
        ok: bool,
    },
    Offer(CallOffer),
    Update(CallUpdate),
    RequestOutgoing {
        key: SessionKey,
        contact_id: String,
        address: String,
    },
    UserAction(CallCommand),
    AudioPrepared {
        key: SessionKey,
        ok: bool,
    },
    CommandFinished {
        key: SessionKey,
        request_id: String,
        ok: bool,
    },
    CleanupConfirmed(SessionKey),
    WorkerExited {
        transport: CallTransport,
        generation: u64,
    },
    SetMode(DeviceMode),
    Tick,
    Shutdown,
}
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum CallEffect {
    AcceptedUpdate(CallUpdate),
    Transport(CallCommand),
    Dial {
        key: SessionKey,
        address: String,
    },
    PrepareAudio(InterruptForCall),
    StartRingtone(RingtoneRequest),
    StopRingtone(RingtoneRequest),
    WakeDisplay(SessionKey),
    Publish,
    RestoreUi(SessionKey),
    RecoverTransport {
        transport: CallTransport,
        generation: u64,
    },
}
#[derive(Debug, Clone)]
struct Owned {
    key: SessionKey,
    contact: ContactIdentity,
    answer_dispatched: bool,
    phase: CallPhase,
    incoming: bool,
    address: String,
    deadline: u64,
    ring_deadline: u64,
    queued_answer: bool,
    pending: bool,
    acknowledgements: Vec<String>,
}
#[derive(Debug, Clone)]
pub struct CallManager {
    mode: DeviceMode,
    operation_timeout_ms: u64,
    ring_duration_ms: u64,
    owned: Option<Owned>,
    terminal: Vec<SessionKey>,
    sequences: Vec<(SessionKey, u64)>,
    generations: Vec<(CallTransport, u64)>,
    watermarks: [[u64; 2]; 2],
    audible: bool,
    activity_generation: u64,
    shutdown: bool,
    ring_start_pending: bool,
    ring_stop_pending: bool,
    answer_after_stop: bool,
    ringtone_deadline: u64,
}
impl CallManager {
    pub fn new(mode: DeviceMode, operation_timeout_ms: u64, ring_duration_ms: u64) -> Self {
        Self {
            mode,
            operation_timeout_ms,
            ring_duration_ms,
            owned: None,
            terminal: vec![],
            sequences: vec![],
            generations: vec![],
            watermarks: [[0; 2]; 2],
            audible: false,
            activity_generation: 0,
            shutdown: false,
            ring_start_pending: false,
            ring_stop_pending: false,
            answer_after_stop: false,
            ringtone_deadline: 0,
        }
    }
    pub fn session(&self) -> Option<&SessionKey> {
        self.owned.as_ref().map(|s| &s.key)
    }
    /// Stable identity captured at admission; directory changes cannot retarget a call.
    pub fn admitted_identity(&self) -> Option<&ContactIdentity> {
        self.owned.as_ref().map(|s| &s.contact)
    }
    pub fn phase(&self) -> Option<CallPhase> {
        self.owned.as_ref().map(|s| s.phase.clone())
    }
    pub fn mode(&self) -> DeviceMode {
        self.mode.clone()
    }
    pub fn alert_audible(&self) -> bool {
        self.audible
    }
    pub fn incoming(&self) -> bool {
        self.owned.as_ref().is_some_and(|s| s.incoming)
    }
    pub fn accept_enabled(&self) -> bool {
        self.owned.as_ref().is_some_and(|s| {
            s.incoming
                && !s.queued_answer
                && matches!(s.phase, CallPhase::Preparing | CallPhase::Ringing)
        })
    }
    pub fn remaining_ring_ms(&self, now_ms: u64) -> u64 {
        self.owned
            .as_ref()
            .map_or(0, |s| s.ring_deadline.saturating_sub(now_ms))
    }
    fn current_generation(&mut self, key: &SessionKey) -> bool {
        if call_ordinal(&key.transport, &key.call_id).is_none() {
            return false;
        }
        if let Some((_, generation)) = self
            .generations
            .iter_mut()
            .find(|(t, _)| *t == key.transport)
        {
            if key.generation < *generation {
                return false;
            }
            if key.generation == *generation {
                return true;
            }
            *generation = key.generation;
        } else {
            self.generations
                .push((key.transport.clone(), key.generation));
        }
        self.watermarks[usize::from(key.transport == CallTransport::Sip)] = [0; 2];
        self.terminal
            .retain(|k| k.transport != key.transport || k.generation >= key.generation);
        self.sequences
            .retain(|(k, _)| k.transport != key.transport || k.generation >= key.generation);
        true
    }
    fn reserve_key(&mut self, key: &SessionKey) -> bool {
        if !self.current_generation(key) {
            return false;
        }
        let (namespace, serial) =
            call_ordinal(&key.transport, &key.call_id).expect("validated identity");
        let watermark =
            &mut self.watermarks[usize::from(key.transport == CallTransport::Sip)][namespace];
        if serial <= *watermark || self.sequences.len() >= MAX_LIVE_CALLS * 2 {
            return false;
        }
        *watermark = serial;
        self.sequences.push((key.clone(), 0));
        true
    }
    fn reject(&mut self, key: SessionKey, reason: RejectReason) -> Vec<CallEffect> {
        self.terminal.push(key.clone());
        vec![CallEffect::Transport(CallCommand {
            key,
            action: CallAction::Reject(reason),
        })]
    }
    fn stop_ring(&mut self, effects: &mut Vec<CallEffect>) {
        if self.audible {
            if let Some(s) = &self.owned {
                effects.push(CallEffect::StopRingtone(RingtoneRequest {
                    key: s.key.clone(),
                    operation_generation: 0,
                    lease_ms: 0,
                }));
            }
            self.audible = false;
            self.ring_stop_pending = true;
        }
    }
    fn ending(&mut self, now: u64, action: Option<CallAction>, effects: &mut Vec<CallEffect>) {
        self.stop_ring(effects);
        if let Some(s) = &mut self.owned {
            if matches!(s.phase, CallPhase::Ending | CallPhase::Ended) {
                return;
            }
            s.phase = CallPhase::Ending;
            s.deadline = now.saturating_add(self.operation_timeout_ms);
            s.pending = action.is_some();
            self.terminal.push(s.key.clone());
            if let Some(action) = action {
                effects.push(CallEffect::Transport(CallCommand {
                    key: s.key.clone(),
                    action,
                }));
            }
            effects.push(CallEffect::Publish);
        }
    }
    /// `now_ms` must be monotonic. Runtime correlates opaque command request IDs
    /// before forwarding acknowledgements and confirms cleanup only after all
    /// audio and transport resources have been reconciled.
    pub fn handle(
        &mut self,
        event: CallManagerEvent,
        context: &CallContext,
        now_ms: u64,
    ) -> Vec<CallEffect> {
        let mut effects = vec![];
        match event {
            CallManagerEvent::RingtoneStarted { key, ok } => {
                if self.session() != Some(&key) || !self.ring_start_pending {
                    return effects;
                }
                self.ring_start_pending = false;
                if !ok {
                    self.ending(now_ms, Some(CallAction::Hangup), &mut effects);
                }
            }
            CallManagerEvent::RingtoneStopped { key, ok } => {
                if self.session() != Some(&key) || !self.ring_stop_pending {
                    return effects;
                }
                self.ring_stop_pending = false;
                self.ring_start_pending = false;
                if !ok {
                    self.answer_after_stop = false;
                    self.ending(now_ms, Some(CallAction::Hangup), &mut effects);
                } else if self.answer_after_stop && self.phase() == Some(CallPhase::Answering) {
                    self.answer_after_stop = false;
                    self.dispatch_answer(&mut effects);
                } else if self.phase() == Some(CallPhase::Ringing) && policy::audible(&self.mode) {
                    self.audible = true;
                    self.ring_start_pending = true;
                    effects.push(CallEffect::StartRingtone(RingtoneRequest {
                        key,
                        operation_generation: 0,
                        lease_ms: 0,
                    }));
                }
            }

            CallManagerEvent::Offer(offer) => {
                if !self.reserve_key(&offer.key)
                    || self.terminal.contains(&offer.key)
                    || self.session() == Some(&offer.key)
                {
                    return effects;
                }
                let contact = identity::match_contact(
                    offer.key.transport.clone(),
                    &offer.address,
                    &context.contacts,
                );
                let Some(contact) = contact else {
                    return self.reject(offer.key, RejectReason::Unapproved);
                };
                if self.owned.is_some()
                    || context.shutdown
                    || self.shutdown
                    || !policy::admits(&self.mode, contact)
                {
                    return self.reject(offer.key, RejectReason::Busy);
                }
                self.admit(
                    offer.key,
                    offer.address,
                    contact.clone(),
                    true,
                    now_ms,
                    &mut effects,
                );
            }
            CallManagerEvent::RequestOutgoing {
                key,
                contact_id,
                address,
            } => {
                if !self.reserve_key(&key)
                    || self.terminal.contains(&key)
                    || self.session() == Some(&key)
                {
                    return effects;
                }
                let contact =
                    identity::match_contact(key.transport.clone(), &address, &context.contacts)
                        .filter(|c| c.contact_id == contact_id);
                let Some(contact) = contact else {
                    return self.reject(key, RejectReason::Unapproved);
                };
                if self.owned.is_some() || context.shutdown || self.shutdown {
                    return self.reject(key, RejectReason::Busy);
                }
                self.admit(key, address, contact.clone(), false, now_ms, &mut effects);
            }
            CallManagerEvent::AudioPrepared { key, ok } => {
                if self.session() != Some(&key) || self.phase() != Some(CallPhase::Preparing) {
                    return effects;
                }
                if !ok {
                    self.ending(now_ms, Some(CallAction::Hangup), &mut effects);
                } else {
                    let s = self.owned.as_mut().unwrap();
                    if s.incoming {
                        s.phase = CallPhase::Ringing;
                        if s.queued_answer {
                            self.answer(now_ms, &mut effects);
                        } else if policy::audible(&self.mode) {
                            self.audible = true;
                            self.ring_start_pending = true;
                            effects.push(CallEffect::StartRingtone(RingtoneRequest {
                                key,
                                operation_generation: 0,
                                lease_ms: 0,
                            }));
                        }
                    } else {
                        s.phase = CallPhase::Outgoing;
                        s.pending = true;
                        s.deadline = now_ms.saturating_add(self.operation_timeout_ms);
                        effects.push(CallEffect::Dial {
                            key,
                            address: s.address.clone(),
                        });
                    }
                    effects.push(CallEffect::Publish);
                }
            }
            CallManagerEvent::UserAction(command) => {
                if self.session() != Some(&command.key) {
                    return effects;
                }
                match command.action {
                    CallAction::Answer if self.phase() == Some(CallPhase::Preparing) => {
                        self.owned.as_mut().unwrap().queued_answer = true;
                    }
                    CallAction::Answer if self.phase() == Some(CallPhase::Ringing) => {
                        self.answer(now_ms, &mut effects)
                    }
                    CallAction::Reject(reason) => {
                        self.ending(now_ms, Some(CallAction::Reject(reason)), &mut effects)
                    }
                    CallAction::Hangup => {
                        self.ending(now_ms, Some(CallAction::Hangup), &mut effects)
                    }
                    CallAction::SetMute(_) if self.phase() == Some(CallPhase::Active) => {
                        effects.push(CallEffect::Transport(command))
                    }
                    _ => {}
                }
            }
            CallManagerEvent::Update(update) => {
                if !self.current_generation(&update.key) {
                    return effects;
                }
                if let Some((_, sequence)) =
                    self.sequences.iter_mut().find(|(k, _)| *k == update.key)
                {
                    if update.sequence <= *sequence {
                        return effects;
                    }
                    *sequence = update.sequence;
                } else {
                    return effects; // An update cannot allocate/recreate an identity.
                }
                if self.terminal.contains(&update.key) && update.phase != CallPhase::Ended {
                    return effects;
                }
                effects.push(CallEffect::AcceptedUpdate(update.clone()));
                if self.session() != Some(&update.key) {
                    if update.phase == CallPhase::Ended {
                        self.sequences.retain(|(key, _)| *key != update.key);
                        self.terminal.retain(|key| *key != update.key);
                    }
                    return effects;
                }
                if update.phase == CallPhase::Ended {
                    self.ending(now_ms, None, &mut effects);
                } else if update.phase == CallPhase::Active
                    && matches!(
                        self.phase(),
                        Some(CallPhase::Answering | CallPhase::Outgoing)
                    )
                {
                    self.stop_ring(&mut effects);
                    let s = self.owned.as_mut().unwrap();
                    s.phase = CallPhase::Active;
                    s.pending = false;
                    effects.push(CallEffect::Publish);
                }
            }
            CallManagerEvent::CommandFinished {
                key,
                request_id,
                ok,
            } => {
                if let Some(s) = &mut self.owned {
                    if s.key != key || !s.pending || s.acknowledgements.contains(&request_id) {
                        return effects;
                    }
                    s.acknowledgements.push(request_id);
                    s.pending = false;
                    if !ok {
                        self.ending(now_ms, Some(CallAction::Hangup), &mut effects);
                    }
                }
            }
            CallManagerEvent::CleanupConfirmed(key) => {
                if self.session() == Some(&key)
                    && self.phase() == Some(CallPhase::Ending)
                    && !self.ring_stop_pending
                {
                    self.stop_ring(&mut effects);
                    self.owned = None;
                    self.sequences.retain(|(candidate, _)| *candidate != key);
                    self.terminal.retain(|candidate| *candidate != key);
                    self.ring_start_pending = false;
                    self.ring_stop_pending = false;
                    self.answer_after_stop = false;
                    effects.push(CallEffect::RestoreUi(key));
                    effects.push(CallEffect::Publish);
                }
            }
            CallManagerEvent::WorkerExited {
                transport,
                generation,
            } => {
                if self
                    .owned
                    .as_ref()
                    .is_some_and(|s| s.key.transport == transport && s.key.generation == generation)
                {
                    self.ending(now_ms, None, &mut effects);
                }
                if let Some((_, latest)) =
                    self.generations.iter_mut().find(|(t, _)| *t == transport)
                {
                    *latest = (*latest).max(generation.saturating_add(1));
                } else {
                    self.generations
                        .push((transport.clone(), generation.saturating_add(1)));
                }
                self.terminal
                    .retain(|k| k.transport != transport || k.generation > generation);
                self.sequences
                    .retain(|(k, _)| k.transport != transport || k.generation > generation);
            }
            CallManagerEvent::SetMode(mode) => {
                self.mode = mode;
                if self.mode == DeviceMode::DoNotDisturb
                    && self.owned.as_ref().is_some_and(|s| {
                        s.incoming
                            && !s.contact.priority
                            && !s.answer_dispatched
                            && matches!(
                                s.phase,
                                CallPhase::Preparing | CallPhase::Ringing | CallPhase::Answering
                            )
                    })
                {
                    self.answer_after_stop = false;
                    self.ending(
                        now_ms,
                        Some(CallAction::Reject(RejectReason::Busy)),
                        &mut effects,
                    );
                    if effects
                        .iter()
                        .any(|effect| matches!(effect, CallEffect::StopRingtone(_)))
                    {
                        self.ringtone_deadline = now_ms.saturating_add(self.operation_timeout_ms);
                    }
                    return effects;
                }
                if !policy::audible(&self.mode) {
                    self.stop_ring(&mut effects);
                } else if self.phase() == Some(CallPhase::Ringing)
                    && !self.audible
                    && !self.ring_stop_pending
                {
                    self.audible = true;
                    self.ring_start_pending = true;
                    effects.push(CallEffect::StartRingtone(RingtoneRequest {
                        key: self.session().unwrap().clone(),
                        operation_generation: 0,
                        lease_ms: 0,
                    }));
                }
                effects.push(CallEffect::Publish);
            }
            CallManagerEvent::Tick => {
                if let Some(s) = &self.owned {
                    let phase = s.phase.clone();
                    let key = s.key.clone();
                    if phase == CallPhase::Ending && now_ms >= s.deadline {
                        effects.push(CallEffect::RecoverTransport {
                            transport: key.transport,
                            generation: key.generation,
                        });
                        self.owned.as_mut().unwrap().deadline =
                            now_ms.saturating_add(self.operation_timeout_ms);
                    } else if (self.ring_start_pending || self.ring_stop_pending)
                        && now_ms >= self.ringtone_deadline
                    {
                        self.ending(now_ms, Some(CallAction::Hangup), &mut effects);
                    } else if s.incoming
                        && !s.queued_answer
                        && matches!(phase, CallPhase::Preparing | CallPhase::Ringing)
                        && now_ms >= s.ring_deadline
                    {
                        self.ending(
                            now_ms,
                            Some(CallAction::Reject(RejectReason::Timeout)),
                            &mut effects,
                        );
                    } else if matches!(
                        phase,
                        CallPhase::Preparing | CallPhase::Answering | CallPhase::Outgoing
                    ) && now_ms >= s.deadline
                    {
                        self.ending(now_ms, Some(CallAction::Hangup), &mut effects);
                    }
                }
            }
            CallManagerEvent::Shutdown => {
                self.shutdown = true;
                self.ending(now_ms, Some(CallAction::Hangup), &mut effects);
            }
        }
        if effects.iter().any(|effect| {
            matches!(
                effect,
                CallEffect::StartRingtone(_) | CallEffect::StopRingtone(_)
            )
        }) {
            self.ringtone_deadline = now_ms.saturating_add(self.operation_timeout_ms);
        }
        effects
    }
    fn admit(
        &mut self,
        key: SessionKey,
        address: String,
        contact: ContactIdentity,
        incoming: bool,
        now: u64,
        effects: &mut Vec<CallEffect>,
    ) {
        self.activity_generation = self.activity_generation.saturating_add(1);
        self.owned = Some(Owned {
            key: key.clone(),
            contact,
            answer_dispatched: false,
            phase: CallPhase::Preparing,
            incoming,
            address,
            deadline: now.saturating_add(self.operation_timeout_ms),
            ring_deadline: now.saturating_add(self.ring_duration_ms),
            queued_answer: false,
            pending: false,
            acknowledgements: vec![],
        });
        effects.push(CallEffect::WakeDisplay(key.clone()));
        effects.push(CallEffect::Publish);
        effects.push(CallEffect::PrepareAudio(InterruptForCall {
            key,
            activity_generation: self.activity_generation,
            voice_activity_generation: 0,
        }));
    }
    fn answer(&mut self, now: u64, effects: &mut Vec<CallEffect>) {
        self.stop_ring(effects);
        let s = self.owned.as_mut().unwrap();
        s.phase = CallPhase::Answering;
        s.pending = true;
        s.deadline = now.saturating_add(self.operation_timeout_ms);
        self.answer_after_stop = self.ring_stop_pending;
        if !self.answer_after_stop {
            self.dispatch_answer(effects);
        }
        effects.push(CallEffect::Publish);
    }
    fn dispatch_answer(&mut self, effects: &mut Vec<CallEffect>) {
        let s = self.owned.as_mut().unwrap();
        s.answer_dispatched = true;
        effects.push(CallEffect::Transport(CallCommand {
            key: s.key.clone(),
            action: CallAction::Answer,
        }));
    }
}
