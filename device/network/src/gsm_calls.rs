//! Logical GSM session identities are independent of modem object paths and numbers.
use yoyopod_protocol::call::{
    CallDirection, CallOffer, CallPhase, CallTransport, CallUpdate, SessionKey,
};

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum CallManagerWireEvent {
    Offer(CallOffer),
    Update(CallUpdate),
}

pub struct GsmCallRegistry {
    generation: u64,
    next_id: u64,
    calls: Vec<(String, SessionKey, Option<CallUpdate>)>,
    used_ids: std::collections::HashSet<String>,
}

impl GsmCallRegistry {
    pub fn observe_audio(
        &mut self,
        key: &SessionKey,
        duration_seconds: u64,
        muted: bool,
    ) -> Option<CallUpdate> {
        let (_, _, update) = self
            .calls
            .iter_mut()
            .find(|(_, candidate, _)| candidate == key)?;
        let update = update.as_mut()?;
        if update.duration_seconds == duration_seconds && update.muted == muted {
            return None;
        }
        update.duration_seconds = duration_seconds;
        update.muted = muted;
        update.sequence += 1;
        Some(update.clone())
    }
    pub fn new(generation: u64) -> Self {
        Self {
            generation,
            next_id: 0,
            calls: Vec::new(),
            used_ids: Default::default(),
        }
    }
    pub fn observe(
        &mut self,
        object_path: &str,
        direction: CallDirection,
        phase: CallPhase,
        number: &str,
    ) -> Vec<CallManagerWireEvent> {
        let mut events = Vec::new();
        let index = self
            .calls
            .iter()
            .position(|(path, _, _)| path == object_path)
            .unwrap_or_else(|| {
                loop {
                    self.next_id += 1;
                    if self.used_ids.insert(format!("gsm-{}", self.next_id)) {
                        break;
                    }
                }
                let key = SessionKey {
                    transport: CallTransport::Gsm,
                    generation: self.generation,
                    call_id: format!("gsm-{}", self.next_id),
                };
                if direction == CallDirection::Incoming
                    && matches!(phase, CallPhase::Ringing | CallPhase::Waiting)
                {
                    events.push(CallManagerWireEvent::Offer(CallOffer {
                        key: key.clone(),
                        address: number.into(),
                    }));
                }
                self.calls.push((object_path.into(), key, None));
                self.calls.len() - 1
            });
        let (_, key, previous) = &mut self.calls[index];
        if previous.as_ref().is_some_and(|old| {
            old.direction == direction && old.phase == phase && old.address == number
        }) {
            return events;
        }
        let update = CallUpdate {
            key: key.clone(),
            direction,
            phase,
            address: number.into(),
            sequence: previous.as_ref().map_or(1, |old| old.sequence + 1),
            duration_seconds: previous.as_ref().map_or(0, |old| old.duration_seconds),
            muted: previous.as_ref().is_some_and(|old| old.muted),
        };
        *previous = Some(update.clone());
        events.push(CallManagerWireEvent::Update(update));
        events
    }
    pub fn path_for(&self, key: &SessionKey) -> Option<&str> {
        self.calls
            .iter()
            .find(|(_, candidate, _)| candidate == key)
            .map(|(path, _, _)| path.as_str())
    }
    pub fn remove(&mut self, key: &SessionKey) -> Option<String> {
        let index = self
            .calls
            .iter()
            .position(|(_, candidate, _)| candidate == key)?;
        Some(self.calls.remove(index).0)
    }
    pub fn register_outgoing(&mut self, key: &SessionKey, path: &str) -> anyhow::Result<()> {
        anyhow::ensure!(
            key.transport == CallTransport::Gsm
                && key.generation == self.generation
                && !key.call_id.trim().is_empty(),
            "Invalid GSM session generation"
        );
        anyhow::ensure!(
            !self
                .calls
                .iter()
                .any(|(candidate, existing, _)| candidate == path || existing == key),
            "GSM session already registered"
        );
        anyhow::ensure!(
            self.used_ids.insert(key.call_id.clone()),
            "GSM session key was already used"
        );
        self.calls.push((path.into(), key.clone(), None));
        Ok(())
    }
    pub fn tracked(&self) -> Vec<(String, SessionKey)> {
        self.calls
            .iter()
            .map(|(path, key, _)| (path.clone(), key.clone()))
            .collect()
    }
    pub fn latest(&self, key: &SessionKey) -> Option<&CallUpdate> {
        self.calls
            .iter()
            .find(|(_, candidate, _)| candidate == key)
            .and_then(|(_, _, update)| update.as_ref())
    }

    pub fn is_fresh_key(&self, key: &SessionKey) -> bool {
        key.transport == CallTransport::Gsm
            && key.generation == self.generation
            && !key.call_id.trim().is_empty()
            && !self.used_ids.contains(&key.call_id)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use yoyopod_protocol::call::CallTransport;

    #[test]
    fn gsm_outgoing_key_cannot_be_reused_after_removal() {
        let mut registry = GsmCallRegistry::new(9);
        let key = outgoing(9);
        registry.register_outgoing(&key, "/call/1").unwrap();
        registry.remove(&key);
        assert!(
            registry.register_outgoing(&key, "/call/2").is_err(),
            "late command could target replacement session"
        );
    }

    #[test]
    fn gsm_owned_mute_and_duration_are_sequenced_without_reoffering() {
        let mut registry = GsmCallRegistry::new(9);
        let events = registry.observe(
            "/call/1",
            CallDirection::Incoming,
            CallPhase::Ringing,
            "+49123456789",
        );
        let key = offer(&events).key.clone();
        let update = registry
            .observe_audio(&key, 3, true)
            .expect("audio metadata update");
        assert_eq!(update.duration_seconds, 3);
        assert!(update.muted);
        assert_eq!(update.sequence, 2);
        assert!(registry.observe_audio(&key, 3, true).is_none());
        let active = registry.observe(
            "/call/1",
            CallDirection::Incoming,
            CallPhase::Active,
            "+49123456789",
        );
        let CallManagerWireEvent::Update(active) = &active[0] else {
            panic!("update")
        };
        assert_eq!(active.duration_seconds, 3);
        assert!(active.muted);
        assert_eq!(active.sequence, 3);
    }

    #[test]
    fn gsm_waiting_offer_can_be_rejected_without_admitting_a_second_call() {
        let mut registry = GsmCallRegistry::new(7);
        let events = registry.observe(
            "/call/B",
            CallDirection::Incoming,
            CallPhase::Waiting,
            "+49123456789",
        );
        assert_eq!(offer(&events).key, update(&events).key);
        assert_eq!(update(&events).phase, CallPhase::Waiting);
    }

    fn offer(events: &[CallManagerWireEvent]) -> &CallOffer {
        events
            .iter()
            .find_map(|event| match event {
                CallManagerWireEvent::Offer(offer) => Some(offer),
                _ => None,
            })
            .expect("initial incoming offer")
    }
    fn update(events: &[CallManagerWireEvent]) -> &CallUpdate {
        events
            .iter()
            .find_map(|event| match event {
                CallManagerWireEvent::Update(update) => Some(update),
                _ => None,
            })
            .expect("session update")
    }
    fn outgoing(generation: u64) -> SessionKey {
        SessionKey {
            transport: CallTransport::Gsm,
            generation,
            call_id: "runtime-outgoing".into(),
        }
    }

    #[test]
    fn gsm_same_number_objects_get_distinct_keys_and_one_offer_each() {
        let mut registry = GsmCallRegistry::new(9);
        let a = registry.observe(
            "/call/1",
            CallDirection::Incoming,
            CallPhase::Ringing,
            "+49123456789",
        );
        let b = registry.observe(
            "/call/2",
            CallDirection::Incoming,
            CallPhase::Ringing,
            "+49123456789",
        );
        assert_ne!(offer(&a).key, offer(&b).key);
        assert_eq!(registry.path_for(&offer(&a).key), Some("/call/1"));
        assert_eq!(registry.path_for(&offer(&b).key), Some("/call/2"));
        assert!(registry
            .observe(
                "/call/1",
                CallDirection::Incoming,
                CallPhase::Ringing,
                "+49123456789"
            )
            .is_empty());
    }

    #[test]
    fn gsm_number_arriving_late_updates_same_key_without_reoffering() {
        let mut registry = GsmCallRegistry::new(9);
        let first = registry.observe("/call/1", CallDirection::Incoming, CallPhase::Ringing, "");
        assert_eq!(offer(&first).address, "");
        let identified = registry.observe(
            "/call/1",
            CallDirection::Incoming,
            CallPhase::Ringing,
            "+49123456789",
        );
        assert!(identified
            .iter()
            .all(|event| matches!(event, CallManagerWireEvent::Update(_))));
        assert_eq!(update(&identified).key, offer(&first).key);
        assert_eq!(update(&identified).address, "+49123456789");
        assert!(update(&identified).sequence > update(&first).sequence);
        let ended = registry.observe(
            "/call/1",
            CallDirection::Incoming,
            CallPhase::Ended,
            "+49123456789",
        );
        assert!(update(&ended).sequence > update(&identified).sequence);
    }

    #[test]
    fn gsm_removal_and_generation_fence_do_not_target_another_object() {
        let mut registry = GsmCallRegistry::new(9);
        let a = registry.observe("/call/1", CallDirection::Incoming, CallPhase::Ringing, "");
        let key = offer(&a).key.clone();
        let mut old = key.clone();
        old.generation = 8;
        assert_eq!(registry.path_for(&old), None);
        assert_eq!(registry.remove(&old), None);
        assert_eq!(registry.remove(&key).as_deref(), Some("/call/1"));
        assert_eq!(registry.path_for(&key), None);
        assert_eq!(registry.remove(&key), None);
        let replacement =
            registry.observe("/call/1", CallDirection::Incoming, CallPhase::Ringing, "");
        assert_ne!(offer(&replacement).key, key);
        assert_eq!(registry.path_for(&outgoing(9)), None);
    }

    #[test]
    fn gsm_outgoing_registration_preserves_preallocated_identity_and_rejects_old_generation() {
        let mut registry = GsmCallRegistry::new(9);
        assert!(registry.register_outgoing(&outgoing(8), "/call/1").is_err());
        registry.register_outgoing(&outgoing(9), "/call/1").unwrap();
        let events = registry.observe(
            "/call/1",
            CallDirection::Outgoing,
            CallPhase::Outgoing,
            "+49123456789",
        );
        assert_eq!(update(&events).key, outgoing(9));
        assert!(events
            .iter()
            .all(|event| matches!(event, CallManagerWireEvent::Update(_))));
        assert!(registry.register_outgoing(&outgoing(9), "/call/2").is_err());
    }

    #[test]
    fn gsm_unsolicited_active_session_is_a_fact_not_an_admission_offer() {
        let mut registry = GsmCallRegistry::new(9);
        let events = registry.observe(
            "/call/1",
            CallDirection::Incoming,
            CallPhase::Active,
            "+49123456789",
        );
        assert_eq!(update(&events).phase, CallPhase::Active);
        assert!(events
            .iter()
            .all(|event| matches!(event, CallManagerWireEvent::Update(_))));
    }
}
