use serde_json::json;
use yoyopod_media_host::config::MediaConfig;

#[test]
fn config_from_payload_accepts_python_media_config_shape() {
    let payload = json!({
        "music_dir": "/srv/music",
        "mpv_socket": "/tmp/yoyopod-mpv.sock",
        "mpv_binary": "mpv",
        "alsa_device": "default",
        "default_volume": 72,
        "recent_tracks_file": "data/media/recent_tracks.json",
        "remote_cache_dir": "data/media/remote_cache",
        "remote_cache_max_bytes": 1048576
    });

    let config = MediaConfig::from_payload(&payload).expect("config");

    assert_eq!(config.music_dir, "/srv/music");
    assert_eq!(config.mpv_socket, "/tmp/yoyopod-mpv.sock");
    assert_eq!(config.mpv_binary, "mpv");
    assert_eq!(config.alsa_device, "default");
    assert_eq!(config.default_volume, 72);
    assert_eq!(config.recent_tracks_file, "data/media/recent_tracks.json");
    assert_eq!(config.remote_cache_dir, "data/media/remote_cache");
    assert_eq!(config.remote_cache_max_bytes, 1048576);
}

#[test]
fn config_rejects_empty_music_dir() {
    let payload = json!({"music_dir": ""});

    let error = MediaConfig::from_payload(&payload).expect_err("must reject");

    assert!(error.to_string().contains("music_dir"));
}
