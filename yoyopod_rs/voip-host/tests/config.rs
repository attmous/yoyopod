use serde_json::json;
use yoyopod_voip_host::config::VoipConfig;

#[test]
fn config_from_payload_accepts_python_voip_config_shape() {
    let payload = json!({
        "sip_server": "sip.example.com",
        "sip_username": "alice",
        "sip_password": "secret",
        "sip_identity": "sip:alice@example.com",
        "transport": "tcp",
        "iterate_interval_ms": 20,
        "playback_dev_id": "ALSA: wm8960-soundcard",
        "ringer_dev_id": "ALSA: wm8960-soundcard",
        "capture_dev_id": "ALSA: wm8960-soundcard",
        "media_dev_id": "ALSA: wm8960-soundcard",
        "mic_gain": 80,
        "output_volume": 100
    });

    let config = VoipConfig::from_payload(&payload).expect("config");

    assert_eq!(config.sip_server, "sip.example.com");
    assert_eq!(config.sip_identity, "sip:alice@example.com");
    assert_eq!(config.iterate_interval_ms, 20);
    assert_eq!(config.transport, "tcp");
}

#[test]
fn config_rejects_missing_identity() {
    let payload = json!({"sip_server":"sip.example.com"});

    let error = VoipConfig::from_payload(&payload).expect_err("must reject");

    assert!(error.to_string().contains("sip_identity"));
}
