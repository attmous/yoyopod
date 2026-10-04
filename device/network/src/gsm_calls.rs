//! Logical GSM session identities are independent of modem object paths and numbers.
use yoyopod_protocol::call::{CallDirection, CallOffer, CallPhase, CallUpdate, SessionKey};

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum CallManagerWireEvent {
    Offer(CallOffer),
    Update(CallUpdate),
}

// Test-first scaffold: implemented after the isolated Linux RED run.
pub struct GsmCallRegistry;

impl GsmCallRegistry {
    pub fn new(_generation: u64) -> Self { Self }
    pub fn observe(&mut self, _object_path: &str, _direction: CallDirection,
        _phase: CallPhase, _number: &str) -> Vec<CallManagerWireEvent> { Vec::new() }
    pub fn path_for(&self, _key: &SessionKey) -> Option<&str> { None }
    pub fn remove(&mut self, _key: &SessionKey) -> Option<String> { None }
    pub fn register_outgoing(&mut self, _key: &SessionKey, _path: &str) -> anyhow::Result<()> { Ok(()) }
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
