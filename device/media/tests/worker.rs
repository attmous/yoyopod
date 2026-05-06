use std::fs;
use std::path::PathBuf;
use std::time::{SystemTime, UNIX_EPOCH};

use serde_json::json;
use yoyopod_harness::decode_envelopes;
use yoyopod_media::host::MediaHost;
use yoyopod_media::protocol::{EnvelopeKind, WorkerEnvelope, SUPPORTED_SCHEMA_VERSION};
use yoyopod_media::worker::{handle_command, run_io, LoopAction};

fn temp_dir(test_name: &str) -> PathBuf {
    let unique = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("system time")
        .as_nanos();
    std::env::temp_dir().join(format!("yoyopod-media-worker-{test_name}-{unique}"))
}

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
fn command_failures_preserve_request_id() {
    let input = std::io::Cursor::new(
        br#"{"schema_version":1,"kind":"command","type":"media.load_playlist","request_id":"playlist-1","payload":{}}
"#
        .to_vec(),
    );
    let mut output = Vec::new();
    let mut errors = Vec::new();

    run_io(input, &mut output, &mut errors).expect("worker run");

    let envelopes = decode_envelopes(&output);
    assert!(
        envelopes.len() >= 2,
        "expected ready event and command error"
    );
    let command_error = &envelopes[1];
    assert_eq!(command_error.kind, EnvelopeKind::Error);
    assert_eq!(command_error.request_id.as_deref(), Some("playlist-1"));
    assert_eq!(command_error.payload["code"], "command_failed");
    assert_eq!(
        command_error.payload["message"],
        "media.load_playlist requires path"
    );
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

#[test]
fn list_playlists_command_reads_local_library_from_configured_music_dir() {
    let music_dir = temp_dir("playlists");
    fs::create_dir_all(&music_dir).expect("music dir");
    fs::write(music_dir.join("set-a.m3u"), "#EXTM3U\ntrack-a.mp3\n").expect("playlist");
    let recent_tracks_file = music_dir.join("recent_tracks.json");
    let remote_cache_dir = music_dir.join("remote_cache");

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
                "music_dir": music_dir.display().to_string(),
                "mpv_socket": "/tmp/yoyopod-mpv.sock",
                "mpv_binary": "mpv",
                "alsa_device": "default",
                "default_volume": 100,
                "recent_tracks_file": recent_tracks_file.display().to_string(),
                "remote_cache_dir": remote_cache_dir.display().to_string(),
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
            message_type: "media.list_playlists".to_string(),
            request_id: Some("playlists-1".to_string()),
            timestamp_ms: 0,
            deadline_ms: 0,
            payload: json!({"fetch_track_counts": true}),
        },
        &mut host,
    )
    .expect("list playlists");

    assert_eq!(outcome.envelopes.len(), 1);
    assert_eq!(outcome.envelopes[0].payload["count"], 1);
    assert_eq!(
        outcome.envelopes[0].payload["playlists"][0]["name"],
        "set-a"
    );
    assert_eq!(
        outcome.envelopes[0].payload["playlists"][0]["track_count"],
        1
    );
}

#[test]
fn import_remote_asset_command_persists_dashboard_upload() {
    let music_dir = temp_dir("import-remote");
    fs::create_dir_all(&music_dir).expect("music dir");
    let cached_path = music_dir.join("cache-track.mp3");
    fs::write(&cached_path, b"audio").expect("cached asset");
    let recent_tracks_file = music_dir.join("recent_tracks.json");
    let remote_cache_dir = music_dir.join("remote_cache");

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
                "music_dir": music_dir.display().to_string(),
                "mpv_socket": "/tmp/yoyopod-mpv.sock",
                "mpv_binary": "mpv",
                "alsa_device": "default",
                "default_volume": 100,
                "recent_tracks_file": recent_tracks_file.display().to_string(),
                "remote_cache_dir": remote_cache_dir.display().to_string(),
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
            message_type: "media.import_remote_asset".to_string(),
            request_id: Some("import-1".to_string()),
            timestamp_ms: 0,
            deadline_ms: 0,
            payload: json!({
                "track_id": "track-42",
                "cached_path": cached_path.display().to_string(),
                "title": "Track Forty Two"
            }),
        },
        &mut host,
    )
    .expect("import remote asset");

    let imported_path = outcome.envelopes[0].payload["path"]
        .as_str()
        .expect("path payload");
    assert!(imported_path.ends_with("Track-Forty-Two-track-42.mp3"));
    assert!(music_dir.join("Dashboard Uploads.m3u").exists());
}
