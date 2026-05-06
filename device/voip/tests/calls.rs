use yoyopod_voip::calls::CallSession;

#[test]
fn call_session_owns_active_call_peer_and_mute_reset() {
    let mut session = CallSession::default();

    assert_eq!(session.state(), "idle");
    assert_eq!(session.active_call_id(), None);
    assert_eq!(session.active_peer(), "");
    assert!(!session.muted());

    session.start_outgoing("call-1", "sip:bob@example.com");
    session.set_muted(true);
    session.apply_call_state("call-1", "streams_running");

    assert_eq!(session.state(), "streams_running");
    assert_eq!(session.active_call_id(), Some("call-1"));
    assert_eq!(session.active_peer(), "sip:bob@example.com");
    assert!(session.muted());

    session.apply_call_state("call-1", "released");

    assert_eq!(session.state(), "released");
    assert_eq!(session.active_call_id(), None);
    assert_eq!(session.active_peer(), "");
    assert!(!session.muted());
}

#[test]
fn incoming_call_and_explicit_terminal_actions_clear_session() {
    let mut session = CallSession::default();

    session.incoming("call-2", "sip:alice@example.com");
    session.set_muted(true);

    assert_eq!(session.state(), "incoming");
    assert_eq!(session.active_call_id(), Some("call-2"));
    assert_eq!(session.active_peer(), "sip:alice@example.com");

    session.clear_with_state("released");

    assert_eq!(session.state(), "released");
    assert_eq!(session.active_call_id(), None);
    assert_eq!(session.active_peer(), "");
    assert!(!session.muted());
}
