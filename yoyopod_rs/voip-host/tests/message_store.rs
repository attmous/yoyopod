use std::fs;
use std::path::PathBuf;
use std::time::{SystemTime, UNIX_EPOCH};

use serde_json::Value;
use yoyopod_voip_host::message_store::MessageStore;
use yoyopod_voip_host::messages::MessageRecord;

fn temp_store_dir(test_name: &str) -> PathBuf {
    let unique = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("system time")
        .as_nanos();
    std::env::temp_dir().join(format!("yoyopod-{test_name}-{unique}"))
}

fn voice_note(
    id: &str,
    peer_sip_address: &str,
    direction: &str,
    delivery_state: &str,
    unread: bool,
    local_file_path: &str,
) -> MessageRecord {
    MessageRecord {
        message_id: id.to_string(),
        peer_sip_address: peer_sip_address.to_string(),
        sender_sip_address: if direction == "incoming" {
            peer_sip_address.to_string()
        } else {
            "sip:alice@example.com".to_string()
        },
        recipient_sip_address: if direction == "incoming" {
            "sip:alice@example.com".to_string()
        } else {
            peer_sip_address.to_string()
        },
        kind: "voice_note".to_string(),
        direction: direction.to_string(),
        delivery_state: delivery_state.to_string(),
        text: String::new(),
        local_file_path: local_file_path.to_string(),
        mime_type: "audio/wav".to_string(),
        duration_ms: 1250,
        unread,
    }
}

#[test]
fn message_store_persists_python_compatible_voice_note_summary() {
    let store_dir = temp_store_dir("message-summary");
    let mut store = MessageStore::open(&store_dir, 200);

    store
        .upsert(voice_note(
            "incoming-mom-1",
            "sip:mom@example.com",
            "incoming",
            "delivered",
            true,
            "/tmp/mom-1.wav",
        ))
        .expect("upsert incoming mom");
    store
        .upsert(voice_note(
            "incoming-dad-1",
            "sip:dad@example.com",
            "incoming",
            "delivered",
            true,
            "/tmp/dad-1.wav",
        ))
        .expect("upsert incoming dad");
    store
        .upsert(voice_note(
            "outgoing-mom-2",
            "sip:mom@example.com",
            "outgoing",
            "sent",
            false,
            "/tmp/mom-2.wav",
        ))
        .expect("upsert outgoing mom");

    let summary = store.summary_payload();

    assert_eq!(summary["unread_voice_notes"], 2);
    assert_eq!(
        summary["unread_voice_notes_by_contact"]["sip:mom@example.com"],
        1
    );
    assert_eq!(
        summary["unread_voice_notes_by_contact"]["sip:dad@example.com"],
        1
    );
    assert_eq!(
        summary["latest_voice_note_by_contact"]["sip:mom@example.com"]["message_id"],
        "outgoing-mom-2"
    );
    assert_eq!(
        summary["latest_voice_note_by_contact"]["sip:mom@example.com"]["direction"],
        "outgoing"
    );

    let payload: Value = serde_json::from_str(
        &fs::read_to_string(store_dir.join("messages.json")).expect("messages file"),
    )
    .expect("message store json");
    assert_eq!(payload["messages"][0]["id"], "outgoing-mom-2");
    assert_eq!(payload["messages"][0]["kind"], "voice_note");

    let loaded = MessageStore::open(&store_dir, 200);
    assert_eq!(loaded.summary_payload(), summary);
}

#[test]
fn message_store_normalizes_rcs_voice_note_text_envelope() {
    let store_dir = temp_store_dir("message-envelope");
    let mut store = MessageStore::open(&store_dir, 200);

    store
        .upsert(MessageRecord {
            message_id: "incoming-envelope-1".to_string(),
            peer_sip_address: "sip:mom@example.com".to_string(),
            sender_sip_address: "sip:mom@example.com".to_string(),
            recipient_sip_address: "sip:alice@example.com".to_string(),
            kind: "text".to_string(),
            direction: "incoming".to_string(),
            delivery_state: "delivered".to_string(),
            text: (r#"<?xml version="1.0" encoding="UTF-8"?>"#.to_string()
                + r#"<file xmlns="urn:gsma:params:xml:ns:rcs:rcs:fthttp" "#
                + r#"xmlns:am="urn:gsma:params:xml:ns:rcs:rcs:rram">"#
                + r#"<file-info type="file">"#
                + r#"<content-type>audio/ogg;voice-recording=yes</content-type>"#
                + r#"<am:playing-length>4046</am:playing-length>"#
                + r#"</file-info></file>"#),
            local_file_path: "/tmp/incoming-envelope.mka".to_string(),
            mime_type: "application/vnd.gsma.rcs-ft-http+xml".to_string(),
            duration_ms: 0,
            unread: true,
        })
        .expect("upsert RCS envelope");

    let summary = store.summary_payload();
    assert_eq!(summary["unread_voice_notes"], 1);
    assert_eq!(
        summary["latest_voice_note_by_contact"]["sip:mom@example.com"]["duration_ms"],
        4046
    );

    let payload: Value = serde_json::from_str(
        &fs::read_to_string(store_dir.join("messages.json")).expect("messages file"),
    )
    .expect("message store json");
    assert_eq!(payload["messages"][0]["kind"], "voice_note");
    assert_eq!(payload["messages"][0]["mime_type"], "audio/ogg");
    assert_eq!(payload["messages"][0]["duration_ms"], 4046);
    assert_eq!(payload["messages"][0]["text"], "");
}

#[test]
fn message_store_updates_delivery_downloads_and_mark_seen() {
    let store_dir = temp_store_dir("message-updates");
    let mut store = MessageStore::open(&store_dir, 200);

    store
        .upsert(voice_note(
            "incoming-mom-1",
            "sip:mom@example.com",
            "incoming",
            "delivered",
            true,
            "",
        ))
        .expect("upsert incoming");
    store
        .upsert(voice_note(
            "outgoing-mom-1",
            "sip:mom@example.com",
            "outgoing",
            "sending",
            false,
            "/tmp/outgoing.wav",
        ))
        .expect("upsert outgoing");

    store
        .update_delivery("outgoing-mom-1", "delivered", "/tmp/sent.wav")
        .expect("delivery update");
    store
        .update_download("incoming-mom-1", "/tmp/downloaded.wav", "audio/ogg")
        .expect("download update");
    store
        .mark_contact_seen("sip:mom@example.com")
        .expect("mark seen");

    let summary = store.summary_payload();
    assert_eq!(summary["unread_voice_notes"], 0);
    assert_eq!(
        summary["latest_voice_note_by_contact"]["sip:mom@example.com"]["delivery_state"],
        "delivered"
    );
    assert_eq!(
        summary["latest_voice_note_by_contact"]["sip:mom@example.com"]["local_file_path"],
        "/tmp/downloaded.wav"
    );
}
