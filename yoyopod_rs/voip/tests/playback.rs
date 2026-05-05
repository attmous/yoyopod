use yoyopod_voip::playback::VoiceNotePlayback;

#[test]
fn playback_command_uses_aplay_quiet_mode_for_wav() {
    assert_eq!(
        VoiceNotePlayback::command_for("/tmp/note.wav"),
        vec![
            "aplay".to_string(),
            "-q".to_string(),
            "/tmp/note.wav".to_string()
        ]
    );
}

#[test]
fn playback_command_uses_ffplay_for_container_notes() {
    assert_eq!(
        VoiceNotePlayback::command_for("/tmp/note.mka"),
        vec![
            "ffplay".to_string(),
            "-nodisp".to_string(),
            "-autoexit".to_string(),
            "-loglevel".to_string(),
            "error".to_string(),
            "-af".to_string(),
            "volume=12.0dB".to_string(),
            "/tmp/note.mka".to_string(),
        ]
    );
}
