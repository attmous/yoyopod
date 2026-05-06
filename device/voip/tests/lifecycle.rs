use yoyopod_voip::lifecycle::LifecycleState;

#[test]
fn lifecycle_state_records_recovery_and_drains_events() {
    let mut lifecycle = LifecycleState::default();

    assert_eq!(lifecycle.state(), "unconfigured");
    assert_eq!(lifecycle.reason(), "");
    assert!(!lifecycle.backend_available(false));

    lifecycle.record("configured", "configured", false);
    lifecycle.mark_recovery_pending();
    lifecycle.record("failed", "backend missing", false);
    lifecycle.record("registered", "registered", true);

    assert_eq!(lifecycle.state(), "registered");
    assert_eq!(lifecycle.reason(), "registered");
    assert!(lifecycle.backend_available(true));

    let events = lifecycle.take_events();
    assert_eq!(events.len(), 3);
    assert_eq!(events[0].state, "configured");
    assert_eq!(events[1].previous_state, "configured");
    assert_eq!(events[1].reason, "backend missing");
    assert!(events[2].recovered);
    assert!(lifecycle.take_events().is_empty());
}
