use yoyopod_voip_host::events::{
    call_state_payload, registration_payload, CallState, MessageDeliveryState, MessageDirection,
    MessageKind, RegistrationState,
};

#[test]
fn maps_native_registration_values_to_python_values() {
    assert_eq!(RegistrationState::from_native(1).as_protocol(), "progress");
    assert_eq!(RegistrationState::from_native(2).as_protocol(), "ok");
    assert_eq!(RegistrationState::from_native(4).as_protocol(), "failed");
    assert_eq!(RegistrationState::from_native(99).as_protocol(), "none");
}

#[test]
fn maps_native_call_values_to_python_values() {
    assert_eq!(CallState::from_native(1).as_protocol(), "incoming");
    assert_eq!(CallState::from_native(7).as_protocol(), "streams_running");
    assert_eq!(CallState::from_native(11).as_protocol(), "released");
    assert_eq!(CallState::from_native(99).as_protocol(), "idle");
}

#[test]
fn released_error_end_are_terminal() {
    assert!(CallState::Released.is_terminal());
    assert!(CallState::Error.is_terminal());
    assert!(CallState::End.is_terminal());
    assert!(!CallState::Connected.is_terminal());
}

#[test]
fn maps_native_message_values_to_python_values() {
    assert_eq!(MessageKind::from_native(1).as_protocol(), "text");
    assert_eq!(MessageKind::from_native(2).as_protocol(), "voice_note");
    assert_eq!(MessageDirection::from_native(1).as_protocol(), "incoming");
    assert_eq!(MessageDirection::from_native(2).as_protocol(), "outgoing");
    assert_eq!(MessageDeliveryState::from_native(1).as_protocol(), "queued");
    assert_eq!(
        MessageDeliveryState::from_native(4).as_protocol(),
        "delivered"
    );
    assert_eq!(
        MessageDeliveryState::from_native(99).as_protocol(),
        "failed"
    );
}

#[test]
fn event_payload_helpers_match_worker_protocol() {
    assert_eq!(
        registration_payload(RegistrationState::Ok, ""),
        serde_json::json!({"state": "ok", "reason": ""})
    );
    assert_eq!(
        call_state_payload("call-1", CallState::StreamsRunning),
        serde_json::json!({"call_id": "call-1", "state": "streams_running"})
    );
}
