use yoyopod_voip_host::calls::CallSession;
use yoyopod_voip_host::lifecycle::LifecycleState;
use yoyopod_voip_host::message_store::MessageStore;
use yoyopod_voip_host::messages::MessageSessionState;
use yoyopod_voip_host::runtime_snapshot::RuntimeSnapshot;
use yoyopod_voip_host::voice_notes::VoiceNoteSession;

#[test]
fn runtime_snapshot_composes_canonical_voip_payload() {
    let mut lifecycle = LifecycleState::default();
    lifecycle.record("registered", "registered", false);

    let mut call = CallSession::default();
    call.start_outgoing("call-1", "sip:bob@example.com");
    call.set_muted(true);

    let mut voice_note = VoiceNoteSession::default();
    voice_note.start_sending("/tmp/note.wav", 1250, "audio/wav", "client-vn-1");

    let last_message =
        MessageSessionState::delivery_changed("client-vn-1", "delivered", "/tmp/note.wav", "");
    let message_store = MessageStore::memory(200);

    let payload = RuntimeSnapshot {
        configured: true,
        registered: true,
        registration_state: "ok",
        lifecycle: &lifecycle,
        call: &call,
        voice_note: &voice_note,
        last_message: Some(&last_message),
        pending_outbound_messages: 1,
        message_store: &message_store,
    }
    .payload();

    assert_eq!(payload["configured"], true);
    assert_eq!(payload["registered"], true);
    assert_eq!(payload["registration_state"], "ok");
    assert_eq!(payload["lifecycle"]["state"], "registered");
    assert_eq!(payload["call_state"], "outgoing_init");
    assert_eq!(payload["active_call_id"], "call-1");
    assert_eq!(payload["active_call_peer"], "sip:bob@example.com");
    assert_eq!(payload["muted"], true);
    assert_eq!(payload["voice_note"]["message_id"], "client-vn-1");
    assert_eq!(payload["last_message"]["message_id"], "client-vn-1");
    assert_eq!(payload["pending_outbound_messages"], 1);
    assert_eq!(payload["unread_voice_notes"], 0);
    assert!(payload["latest_voice_note_by_contact"]
        .as_object()
        .expect("summary object")
        .is_empty());
}
