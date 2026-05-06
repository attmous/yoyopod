use yoyopod_voip::history::{CallHistoryEntry, CallHistoryStore};

#[test]
fn call_history_records_terminal_call_and_marks_seen() {
    let mut store = CallHistoryStore::memory(20);
    store.record(CallHistoryEntry {
        session_id: "call-1".to_string(),
        peer_sip_address: "sip:mom@example.com".to_string(),
        direction: "incoming".to_string(),
        outcome: "missed".to_string(),
        duration_seconds: 0,
        seen: false,
    });

    assert_eq!(store.unseen_count(), 1);
    store.mark_seen("sip:mom@example.com");
    assert_eq!(store.unseen_count(), 0);
}

#[test]
fn call_history_marks_all_seen_for_empty_peer_filter() {
    let mut store = CallHistoryStore::memory(20);
    store.record(CallHistoryEntry {
        session_id: "call-1".to_string(),
        peer_sip_address: "sip:mom@example.com".to_string(),
        direction: "incoming".to_string(),
        outcome: "missed".to_string(),
        duration_seconds: 0,
        seen: false,
    });
    store.record(CallHistoryEntry {
        session_id: "call-2".to_string(),
        peer_sip_address: "sip:dad@example.com".to_string(),
        direction: "incoming".to_string(),
        outcome: "missed".to_string(),
        duration_seconds: 0,
        seen: false,
    });

    store.mark_seen("");

    assert_eq!(store.unseen_count(), 0);
}
