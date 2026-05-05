use yoyopod_voip::messages::{
    is_terminal_delivery_state, MessageRecord, MessageSessionState, OutboundMessageIds,
};

#[test]
fn outbound_message_ids_translate_backend_ids_until_terminal_delivery() {
    let mut ids = OutboundMessageIds::default();

    ids.remember("backend-msg-1", "client-msg-1", "voip text message")
        .expect("remember id");

    assert_eq!(ids.len(), 1);
    assert_eq!(ids.translate("backend-msg-1", false), "client-msg-1");
    assert_eq!(ids.len(), 1);
    assert_eq!(ids.translate("backend-msg-1", true), "client-msg-1");
    assert_eq!(ids.len(), 0);
    assert_eq!(ids.translate("backend-msg-1", true), "backend-msg-1");
}

#[test]
fn last_message_snapshots_keep_runtime_facts_for_payloads() {
    let record = MessageRecord {
        message_id: "msg-1".to_string(),
        peer_sip_address: "sip:bob@example.com".to_string(),
        sender_sip_address: "sip:bob@example.com".to_string(),
        recipient_sip_address: "sip:alice@example.com".to_string(),
        kind: "text".to_string(),
        direction: "incoming".to_string(),
        delivery_state: "delivered".to_string(),
        text: "hello".to_string(),
        local_file_path: "".to_string(),
        mime_type: "".to_string(),
        duration_ms: 0,
        unread: true,
    };

    let received = MessageSessionState::received(&record);
    assert_eq!(received.payload()["message_id"], "msg-1");
    assert_eq!(received.payload()["kind"], "text");
    assert_eq!(received.payload()["direction"], "incoming");
    assert_eq!(received.payload()["delivery_state"], "delivered");

    let failed = MessageSessionState::failed("msg-1", "peer offline");
    assert_eq!(failed.payload()["delivery_state"], "failed");
    assert_eq!(failed.payload()["error"], "peer offline");
}

#[test]
fn terminal_delivery_states_match_worker_cleanup_contract() {
    assert!(is_terminal_delivery_state("delivered"));
    assert!(is_terminal_delivery_state("failed"));
    assert!(!is_terminal_delivery_state("sent"));
    assert!(!is_terminal_delivery_state("pending"));
}
