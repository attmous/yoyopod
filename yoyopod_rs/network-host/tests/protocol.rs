use yoyopod_network_host::protocol::{ready_event, stopped_event};

#[test]
fn ready_event_uses_network_ready_type() {
    let message = ready_event("config");

    assert_eq!(message.kind, "event");
    assert_eq!(message.r#type, "network.ready");
    assert_eq!(message.payload["config_dir"], "config");
}

#[test]
fn stopped_event_uses_network_stopped_type() {
    let message = stopped_event("shutdown");

    assert_eq!(message.kind, "event");
    assert_eq!(message.r#type, "network.stopped");
    assert_eq!(message.payload["reason"], "shutdown");
}
