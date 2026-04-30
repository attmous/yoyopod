use serde_json::json;
use yoyopod_media_host::host::MediaHost;
use yoyopod_media_host::protocol::{EnvelopeKind, WorkerEnvelope, SUPPORTED_SCHEMA_VERSION};
use yoyopod_media_host::worker::{handle_command, run_io, LoopAction};

#[test]
fn run_emits_ready_event_before_processing_input() {
    let input = std::io::Cursor::new(Vec::<u8>::new());
    let mut output = Vec::new();
    let mut errors = Vec::new();

    run_io(input, &mut output, &mut errors).expect("worker run");

    let stdout = String::from_utf8(output).expect("utf8");
    let stderr = String::from_utf8(errors).expect("utf8");

    assert!(stdout.contains("\"type\":\"media.ready\""));
    assert!(stderr.is_empty());
}

#[test]
fn health_command_reports_ready_and_unconfigured_state() {
    let mut host = MediaHost::default();
    let outcome = handle_command(
        WorkerEnvelope {
            schema_version: SUPPORTED_SCHEMA_VERSION,
            kind: EnvelopeKind::Command,
            message_type: "media.health".to_string(),
            request_id: Some("health-1".to_string()),
            timestamp_ms: 0,
            deadline_ms: 0,
            payload: json!({}),
        },
        &mut host,
    )
    .expect("media.health should be handled");

    assert!(matches!(outcome.action, LoopAction::Continue));
    assert_eq!(outcome.envelopes.len(), 1);
    assert_eq!(outcome.envelopes[0].kind, EnvelopeKind::Result);
    assert_eq!(outcome.envelopes[0].message_type, "media.health");
    assert_eq!(outcome.envelopes[0].request_id.as_deref(), Some("health-1"));
    assert_eq!(outcome.envelopes[0].payload["ready"], true);
    assert_eq!(outcome.envelopes[0].payload["configured"], false);
}

#[test]
fn configure_command_marks_host_configured() {
    let mut host = MediaHost::default();
    let outcome = handle_command(
        WorkerEnvelope {
            schema_version: SUPPORTED_SCHEMA_VERSION,
            kind: EnvelopeKind::Command,
            message_type: "media.configure".to_string(),
            request_id: Some("configure-1".to_string()),
            timestamp_ms: 0,
            deadline_ms: 0,
            payload: json!({
                "music_dir": "/srv/music",
                "mpv_socket": "/tmp/yoyopod-mpv.sock",
                "mpv_binary": "mpv",
                "alsa_device": "default",
                "default_volume": 100,
                "recent_tracks_file": "data/media/recent_tracks.json",
                "remote_cache_dir": "data/media/remote_cache",
                "remote_cache_max_bytes": 1048576
            }),
        },
        &mut host,
    )
    .expect("media.configure should be handled");

    assert!(matches!(outcome.action, LoopAction::Continue));
    assert_eq!(outcome.envelopes.len(), 2);
    assert_eq!(outcome.envelopes[0].kind, EnvelopeKind::Result);
    assert_eq!(outcome.envelopes[0].message_type, "media.configure");
    assert_eq!(outcome.envelopes[0].payload["configured"], true);
    assert_eq!(outcome.envelopes[1].message_type, "media.snapshot");
    assert_eq!(outcome.envelopes[1].payload["configured"], true);
    assert_eq!(outcome.envelopes[1].payload["music_dir"], "/srv/music");
}

#[test]
fn health_reflects_previous_configure_command() {
    let mut host = MediaHost::default();

    handle_command(
        WorkerEnvelope {
            schema_version: SUPPORTED_SCHEMA_VERSION,
            kind: EnvelopeKind::Command,
            message_type: "media.configure".to_string(),
            request_id: Some("configure-1".to_string()),
            timestamp_ms: 0,
            deadline_ms: 0,
            payload: json!({
                "music_dir": "/srv/music",
                "mpv_socket": "/tmp/yoyopod-mpv.sock",
                "mpv_binary": "mpv",
                "alsa_device": "default",
                "default_volume": 100,
                "recent_tracks_file": "data/media/recent_tracks.json",
                "remote_cache_dir": "data/media/remote_cache",
                "remote_cache_max_bytes": 1048576
            }),
        },
        &mut host,
    )
    .expect("configure");

    let outcome = handle_command(
        WorkerEnvelope {
            schema_version: SUPPORTED_SCHEMA_VERSION,
            kind: EnvelopeKind::Command,
            message_type: "media.health".to_string(),
            request_id: Some("health-2".to_string()),
            timestamp_ms: 0,
            deadline_ms: 0,
            payload: json!({}),
        },
        &mut host,
    )
    .expect("health");

    assert!(matches!(outcome.action, LoopAction::Continue));
    assert_eq!(outcome.envelopes[0].payload["configured"], true);
    assert_eq!(outcome.envelopes[0].payload["music_dir"], "/srv/music");
}

#[test]
fn worker_stop_uses_shutdown_path() {
    let mut host = MediaHost::default();
    let outcome = handle_command(
        WorkerEnvelope {
            schema_version: SUPPORTED_SCHEMA_VERSION,
            kind: EnvelopeKind::Command,
            message_type: "worker.stop".to_string(),
            request_id: Some("stop-1".to_string()),
            timestamp_ms: 0,
            deadline_ms: 0,
            payload: json!({}),
        },
        &mut host,
    )
    .expect("worker.stop should be handled");

    assert!(matches!(outcome.action, LoopAction::Shutdown));
    assert_eq!(outcome.envelopes.len(), 1);
    assert_eq!(outcome.envelopes[0].kind, EnvelopeKind::Result);
    assert_eq!(outcome.envelopes[0].payload["shutdown"], true);
}
