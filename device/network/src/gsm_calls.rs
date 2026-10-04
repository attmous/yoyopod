//! Logical GSM session identities are independent of modem object paths and numbers.
use yoyopod_protocol::call::{CallDirection, CallOffer, CallPhase, CallTransport, CallUpdate, SessionKey};

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum CallManagerWireEvent {
    Offer(CallOffer),
    Update(CallUpdate),
}

pub struct GsmCallRegistry {
    generation: u64,
    next_id: u64,
    calls: Vec<(String, SessionKey, Option<CallUpdate>)>,
}

impl GsmCallRegistry {
    pub fn new(generation: u64) -> Self { Self { generation, next_id: 0, calls: Vec::new() } }
    pub fn observe(&mut self, object_path: &str, direction: CallDirection,
        phase: CallPhase, number: &str) -> Vec<CallManagerWireEvent> {
        let mut events = Vec::new();
        let index = self.calls.iter().position(|(path, _, _)| path == object_path).unwrap_or_else(|| {
            self.next_id += 1;
            let key = SessionKey { transport: CallTransport::Gsm, generation: self.generation,
                call_id: format!("gsm-{}", self.next_id) };
            if direction == CallDirection::Incoming && phase == CallPhase::Ringing {
                events.push(CallManagerWireEvent::Offer(CallOffer { key: key.clone(), address: number.into() }));
            }
            self.calls.push((object_path.into(), key, None));
            self.calls.len() - 1
        });
        let (_, key, previous) = &mut self.calls[index];
        if previous.as_ref().is_some_and(|old| old.direction == direction && old.phase == phase && old.address == number) {
            return events;
        }
        let update = CallUpdate { key: key.clone(), direction, phase, address: number.into(),
            sequence: previous.as_ref().map_or(1, |old| old.sequence + 1), duration_seconds: 0, muted: false };
        *previous = Some(update.clone());
        events.push(CallManagerWireEvent::Update(update));
        events
    }
    pub fn path_for(&self, key: &SessionKey) -> Option<&str> {
        self.calls.iter().find(|(_, candidate, _)| candidate == key).map(|(path, _, _)| path.as_str())
    }
    pub fn remove(&mut self, key: &SessionKey) -> Option<String> {
        let index = self.calls.iter().position(|(_, candidate, _)| candidate == key)?;
        Some(self.calls.remove(index).0)
    }
    pub fn register_outgoing(&mut self, key: &SessionKey, path: &str) -> anyhow::Result<()> {
        anyhow::ensure!(key.transport == CallTransport::Gsm && key.generation == self.generation && !key.call_id.trim().is_empty(), "Invalid GSM session generation");
        anyhow::ensure!(!self.calls.iter().any(|(candidate, existing, _)| candidate == path || existing == key), "GSM session already registered");
        self.calls.push((path.into(), key.clone(), None));
        Ok(())
    }
    pub fn tracked(&self) -> Vec<(String, SessionKey)> {
        self.calls.iter().map(|(path, key, _)| (path.clone(), key.clone())).collect()
    }
    pub fn latest(&self, key: &SessionKey) -> Option<&CallUpdate> {
        self.calls.iter().find(|(_, candidate, _)| candidate == key).and_then(|(_, _, update)| update.as_ref())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use yoyopod_protocol::call::CallTransport;

    fn offer(events: &[CallManagerWireEvent]) -> &CallOffer {
        events.iter().find_map(|event| match event { CallManagerWireEvent::Offer(offer) => Some(offer), _ => None }).expect("initial incoming offer")
    }
    fn update(events: &[CallManagerWireEvent]) -> &CallUpdate {
        events.iter().find_map(|event| match event { CallManagerWireEvent::Update(update) => Some(update), _ => None }).expect("session update")
    }
    fn outgoing(generation: u64) -> SessionKey {
        SessionKey { transport: CallTransport::Gsm, generation, call_id: "runtime-outgoing".into() }
    }

    #[test]
    fn gsm_same_number_objects_get_distinct_keys_and_one_offer_each() {
        let mut registry = GsmCallRegistry::new(9);
        let a = registry.observe("/call/1", CallDirection::Incoming, CallPhase::Ringing, "+49123456789");
        let b = registry.observe("/call/2", CallDirection::Incoming, CallPhase::Ringing, "+49123456789");
        assert_ne!(offer(&a).key, offer(&b).key);
        assert_eq!(registry.path_for(&offer(&a).key), Some("/call/1"));
        assert_eq!(registry.path_for(&offer(&b).key), Some("/call/2"));
        assert!(registry.observe("/call/1", CallDirection::Incoming, CallPhase::Ringing, "+49123456789").is_empty());
    }

    #[test]
    fn gsm_number_arriving_late_updates_same_key_without_reoffering() {
        let mut registry = GsmCallRegistry::new(9);
        let first = registry.observe("/call/1", CallDirection::Incoming, CallPhase::Ringing, "");
        assert_eq!(offer(&first).address, "");
        let identified = registry.observe("/call/1", CallDirection::Incoming, CallPhase::Ringing, "+49123456789");
        assert!(identified.iter().all(|event| matches!(event, CallManagerWireEvent::Update(_))));
        assert_eq!(update(&identified).key, offer(&first).key);
        assert_eq!(update(&identified).address, "+49123456789");
        assert!(update(&identified).sequence > update(&first).sequence);
        let ended = registry.observe("/call/1", CallDirection::Incoming, CallPhase::Ended, "+49123456789");
        assert!(update(&ended).sequence > update(&identified).sequence);
    }

    #[test]
    fn gsm_removal_and_generation_fence_do_not_target_another_object() {
        let mut registry = GsmCallRegistry::new(9);
        let a = registry.observe("/call/1", CallDirection::Incoming, CallPhase::Ringing, "");
        let key = offer(&a).key.clone();
        let mut old = key.clone(); old.generation = 8;
        assert_eq!(registry.path_for(&old), None);
        assert_eq!(registry.remove(&old), None);
        assert_eq!(registry.remove(&key).as_deref(), Some("/call/1"));
        assert_eq!(registry.path_for(&key), None);
        assert_eq!(registry.remove(&key), None);
        let replacement = registry.observe("/call/1", CallDirection::Incoming, CallPhase::Ringing, "");
        assert_ne!(offer(&replacement).key, key);
        assert_eq!(registry.path_for(&outgoing(9)), None);
    }

    #[test]
    fn gsm_outgoing_registration_preserves_preallocated_identity_and_rejects_old_generation() {
        let mut registry = GsmCallRegistry::new(9);
        assert!(registry.register_outgoing(&outgoing(8), "/call/1").is_err());
        registry.register_outgoing(&outgoing(9), "/call/1").unwrap();
        let events = registry.observe("/call/1", CallDirection::Outgoing, CallPhase::Outgoing, "+49123456789");
        assert_eq!(update(&events).key, outgoing(9));
        assert!(events.iter().all(|event| matches!(event, CallManagerWireEvent::Update(_))));
        assert!(registry.register_outgoing(&outgoing(9), "/call/2").is_err());
    }

    #[test]
    fn gsm_unsolicited_active_session_is_a_fact_not_an_admission_offer() {
        let mut registry = GsmCallRegistry::new(9);
        let events = registry.observe("/call/1", CallDirection::Incoming, CallPhase::Active, "+49123456789");
        assert_eq!(update(&events).phase, CallPhase::Active);
        assert!(events.iter().all(|event| matches!(event, CallManagerWireEvent::Update(_))));
    }
}
