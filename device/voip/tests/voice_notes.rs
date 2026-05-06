use yoyopod_voip::voice_notes::VoiceNoteSession;

#[test]
fn voice_note_session_tracks_record_send_and_delivery_state() {
    let mut session = VoiceNoteSession::default();

    assert_eq!(session.payload()["state"], "idle");

    session.start_recording("/tmp/note.wav");
    assert_eq!(session.payload()["state"], "recording");
    assert_eq!(session.payload()["file_path"], "/tmp/note.wav");
    assert_eq!(session.payload()["mime_type"], "audio/wav");

    session.finish_recording(1250);
    assert_eq!(session.payload()["state"], "recorded");
    assert_eq!(session.payload()["duration_ms"], 1250);

    session.start_sending("/tmp/note.wav", 1250, "audio/wav", "client-vn-1");
    assert_eq!(session.payload()["state"], "sending");
    assert_eq!(session.payload()["message_id"], "client-vn-1");

    session.apply_delivery("other", "failed", "/tmp/other.wav");
    assert_eq!(session.payload()["state"], "sending");

    session.apply_delivery("client-vn-1", "delivered", "/tmp/note.wav");
    assert_eq!(session.payload()["state"], "sent");
    assert_eq!(session.payload()["file_path"], "/tmp/note.wav");
}

#[test]
fn voice_note_session_resets_after_cancel_or_unregister() {
    let mut session = VoiceNoteSession::default();

    session.start_recording("/tmp/note.wav");
    session.reset();

    assert_eq!(session.payload()["state"], "idle");
    assert_eq!(session.payload()["file_path"], "");
    assert_eq!(session.payload()["duration_ms"], 0);
    assert_eq!(session.payload()["message_id"], "");
}
