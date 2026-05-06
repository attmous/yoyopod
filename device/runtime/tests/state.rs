use serde::Deserialize;
use serde_json::json;
use yoyopod_runtime::state::{CallState, RuntimeState, WorkerDomain, WorkerState};

#[test]
fn media_snapshot_updates_ui_payload() {
    let mut state = RuntimeState::default();

    state.apply_media_snapshot(&json!({
        "connected": true,
        "playback_state": "playing",
        "current_track": {
            "uri": "file:///music/song.mp3",
            "name": "Little Song",
            "artists": ["YoYo"]
        },
        "playlists": [{"uri":"playlist://sleep","name":"Sleep","track_count": 3}],
        "recent_tracks": [{"uri":"file:///music/song.mp3","title":"Little Song","artist":"YoYo"}]
    }));

    let payload = state.ui_snapshot_payload();

    assert_eq!(payload["music"]["playing"], true);
    assert_eq!(payload["music"]["title"], "Little Song");
    assert_eq!(payload["music"]["artist"], "YoYo");
    assert_eq!(payload["music"]["playlists"][0]["title"], "Sleep");
    assert_eq!(payload["music"]["playlists"][0]["subtitle"], "3 tracks");
}

#[test]
fn media_snapshot_derives_progress_from_current_host_shape() {
    let mut state = RuntimeState::default();

    state.apply_media_snapshot(&json!({
        "connected": true,
        "playback_state": "playing",
        "time_position_ms": 30_000,
        "current_track": {
            "uri": "file:///music/song.mp3",
            "name": "Little Song",
            "artists": ["YoYo"],
            "length_ms": 120_000
        },
        "playlists": [{"uri": "playlist://single", "name": "Single", "track_count": 1}]
    }));

    let payload = state.ui_snapshot_payload();
    assert_eq!(payload["music"]["progress_permille"], 250);
    assert_eq!(payload["music"]["playlists"][0]["subtitle"], "1 track");
}

#[test]
fn media_snapshot_clamps_derived_progress() {
    let mut state = RuntimeState::default();

    state.apply_media_snapshot(&json!({
        "time_position_ms": 130_000,
        "current_track": {
            "name": "Long Song",
            "length_ms": 120_000
        }
    }));

    assert_eq!(
        state.ui_snapshot_payload()["music"]["progress_permille"],
        1000
    );
}

#[test]
fn media_snapshot_resets_progress_when_length_is_not_positive() {
    let mut state = RuntimeState::default();

    state.apply_media_snapshot(&json!({
        "time_position_ms": 60_000,
        "current_track": {
            "name": "First Song",
            "length_ms": 120_000
        }
    }));
    assert_eq!(
        state.ui_snapshot_payload()["music"]["progress_permille"],
        500
    );

    state.apply_media_snapshot(&json!({
        "time_position_ms": 30_000,
        "current_track": {
            "name": "Unknown Length",
            "length_ms": 0
        }
    }));

    assert_eq!(state.ui_snapshot_payload()["music"]["progress_permille"], 0);
}

#[test]
fn media_snapshot_preserves_explicit_progress_when_length_is_not_positive() {
    let mut state = RuntimeState::default();

    state.apply_media_snapshot(&json!({
        "progress_permille": 321,
        "time_position_ms": 30_000,
        "current_track": {
            "name": "Unknown Length",
            "length_ms": -1
        }
    }));

    assert_eq!(
        state.ui_snapshot_payload()["music"]["progress_permille"],
        321
    );
}

#[test]
fn voip_snapshot_updates_call_and_status_payloads() {
    let mut state = RuntimeState::default();

    state.apply_voip_snapshot(&json!({
        "registered": true,
        "registration_state": "ok",
        "call_state": "incoming",
        "active_call_peer": "sip:mama@example.test",
        "muted": true
    }));

    assert_eq!(state.call.state, CallState::Incoming);
    assert_eq!(state.call.peer_address, "sip:mama@example.test");
    assert_eq!(state.call.peer_name, "sip:mama@example.test");

    let ui = state.ui_snapshot_payload();
    assert_eq!(ui["call"]["state"], "incoming");
    assert_eq!(ui["call"]["muted"], true);

    let status = state.status_payload();
    assert_eq!(status["voip"]["registered"], true);
}

#[test]
fn voip_snapshot_preserves_current_host_ui_details() {
    let mut state = RuntimeState::default();

    state.apply_voip_snapshot(&json!({
        "call_state": "streams_running",
        "active_call_peer": "sip:mama@example.test",
        "call_session": {
            "active": true,
            "peer_sip_address": "sip:mama@example.test",
            "duration_seconds": 75
        },
        "recent_call_history": [{
            "peer_sip_address": "sip:dad@example.test",
            "direction": "incoming",
            "outcome": "missed",
            "duration_seconds": 0,
            "seen": false
        }]
    }));

    let ui = state.ui_snapshot_payload();
    assert_eq!(ui["call"]["peer_address"], "sip:mama@example.test");
    assert_eq!(ui["call"]["peer_name"], "sip:mama@example.test");
    assert_eq!(ui["call"]["duration_text"], "01:15");
    assert_eq!(ui["call"]["history"][0]["id"], "sip:dad@example.test");
    assert_eq!(ui["call"]["history"][0]["title"], "sip:dad@example.test");
    assert_eq!(ui["call"]["history"][0]["subtitle"], "Missed call");
}

#[test]
fn voip_snapshot_projects_contacts_into_ui_payload() {
    let mut state = RuntimeState::default();

    state.apply_voip_snapshot(&json!({
        "contacts": [{
            "id": "sip:mama@example.test",
            "title": "Mama",
            "subtitle": "sip:mama@example.test",
            "icon_key": "person"
        }]
    }));

    let ui = state.ui_snapshot_payload();
    assert_eq!(ui["call"]["contacts"][0]["id"], "sip:mama@example.test");
    assert_eq!(ui["call"]["contacts"][0]["title"], "Mama");
    assert_eq!(
        ui["call"]["contacts"][0]["subtitle"],
        "sip:mama@example.test"
    );
    assert_eq!(ui["call"]["contacts"][0]["icon_key"], "person");
}

#[test]
fn seeded_people_contacts_are_available_before_voip_snapshots() {
    let mut state = RuntimeState::default();

    state.seed_contacts(vec![yoyopod_runtime::state::ListItem {
        id: "sip:mama@example.test".to_string(),
        title: "Mama".to_string(),
        subtitle: String::new(),
        icon_key: "mono:MA".to_string(),
        aliases: Vec::new(),
    }]);

    let ui = state.ui_snapshot_payload();
    assert_eq!(ui["call"]["contacts"][0]["id"], "sip:mama@example.test");
    assert_eq!(ui["call"]["contacts"][0]["title"], "Mama");
    assert_eq!(ui["call"]["contacts"][0]["subtitle"], "");
    assert_eq!(ui["call"]["contacts"][0]["icon_key"], "mono:MA");
}

#[test]
fn voip_snapshot_projects_voice_note_flow_to_ui_payload() {
    let mut state = RuntimeState::default();

    state.apply_voip_snapshot(&json!({
        "voice_note": {
            "state": "recorded",
            "file_path": "/tmp/note.wav",
            "duration_ms": 1400,
            "mime_type": "audio/wav",
            "message_id": "note-1"
        },
        "voice_note_playback": {
            "playing": true,
            "file_path": "/tmp/note.wav"
        }
    }));

    let ui = state.ui_snapshot_payload();
    assert_eq!(ui["voice"]["phase"], "review");
    assert_eq!(ui["voice"]["body"], "Playing preview");
    assert_eq!(ui["voice"]["capture_in_flight"], false);
    assert_eq!(state.voice.file_path, "/tmp/note.wav");
    assert_eq!(state.voice.duration_ms, 1400);
    assert!(state.voice.playback_active);
}

#[test]
fn voip_snapshot_projects_latest_voice_notes_for_talk_contact_actions() {
    let mut state = RuntimeState::default();

    state.apply_voip_snapshot(&json!({
        "unread_voice_notes_by_contact": {
            "sip:mama@example.test": 1
        },
        "latest_voice_note_by_contact": {
            "sip:mama@example.test": {
                "message_id": "note-1",
                "direction": "incoming",
                "delivery_state": "delivered",
                "local_file_path": "/tmp/mama-note.wav",
                "duration_ms": 900,
                "unread": true,
                "display_name": "Mama"
            }
        }
    }));

    let ui = state.ui_snapshot_payload();
    assert_eq!(
        ui["call"]["unread_voice_notes_by_contact"]["sip:mama@example.test"],
        1
    );
    assert_eq!(
        ui["call"]["latest_voice_note_by_contact"]["sip:mama@example.test"]["local_file_path"],
        "/tmp/mama-note.wav"
    );
    assert_eq!(
        ui["call"]["latest_voice_note_by_contact"]["sip:mama@example.test"]["duration_ms"],
        900
    );
}

#[test]
fn network_snapshot_updates_status_bar_payload_and_power_row() {
    let mut state = RuntimeState::default();

    state.apply_network_snapshot(&json!({
        "app_state": {
            "network_enabled": true,
            "signal_bars": 4,
            "connection_type": "4g",
            "connected": true,
            "gps_has_fix": true
        }
    }));

    let ui = state.ui_snapshot_payload();
    assert_eq!(ui["network"]["enabled"], true);
    assert_eq!(ui["network"]["connected"], true);
    assert_eq!(ui["network"]["connection_type"], "4g");
    assert_eq!(ui["network"]["signal_strength"], 4);
    assert_eq!(ui["network"]["gps_has_fix"], true);
    assert_eq!(ui["power"]["rows"][2], "Network connected");
}

#[test]
fn power_snapshot_updates_status_bar_payload_and_setup_page() {
    let mut state = RuntimeState::default();

    state.apply_power_snapshot(&json!({
        "available": true,
        "source": "pisugar",
        "device": {
            "model": "PiSugar 3",
            "firmware_version": "1.8.7"
        },
        "battery": {
            "level_percent": 42.8,
            "voltage_volts": 4.02,
            "charging": false,
            "power_plugged": true,
            "temperature_celsius": 30.4
        },
        "rtc": {
            "time": "2026-05-04T12:30:00+00:00",
            "alarm_enabled": false
        },
        "shutdown": {
            "safe_shutdown_level_percent": 8.0,
            "safe_shutdown_delay_seconds": 15
        }
    }));

    let ui = state.ui_snapshot_payload();

    assert_eq!(ui["power"]["battery_percent"], 43);
    assert_eq!(ui["power"]["charging"], false);
    assert_eq!(ui["power"]["power_available"], true);
    assert_eq!(ui["power"]["rows"][0], "Battery 43%");
    assert_eq!(ui["power"]["rows"][1], "Plugged");

    let pages = ui["power"]["pages"].as_array().expect("setup pages");
    assert_eq!(pages[0]["title"], "Power");
    assert_eq!(pages[0]["rows"][0], "Model: PiSugar 3");
    assert_eq!(pages[0]["rows"][1], "Battery: 43%");
    assert_eq!(pages[0]["rows"][2], "Charging: Idle");
    assert_eq!(pages[0]["rows"][3], "External: Plugged");
    assert_eq!(pages[0]["rows"][4], "Voltage: 4.02V 30C");

    let status = state.status_payload();
    assert_eq!(status["power"]["available"], true);
    assert_eq!(status["power"]["battery_percent"], 43);
}

#[test]
fn cloud_snapshot_updates_runtime_status_payload() {
    let mut state = RuntimeState::default();

    state.apply_cloud_snapshot(&json!({
        "device_id": "device-123",
        "provisioning_state": "provisioned",
        "cloud_state": "ready",
        "mqtt_connected": true,
        "last_error_summary": ""
    }));

    let ui = state.ui_snapshot_payload();
    assert_eq!(ui["cloud"]["provisioning_state"], "provisioned");
    assert_eq!(ui["cloud"]["cloud_state"], "ready");
    assert_eq!(ui["cloud"]["mqtt_connected"], true);

    let status = state.status_payload();
    assert_eq!(status["cloud"]["cloud_state"], "ready");
    assert_eq!(status["cloud"]["mqtt_connected"], true);
}

#[test]
fn network_setup_projection_feeds_setup_pages() {
    let mut state = RuntimeState::default();

    state.apply_network_snapshot(&json!({
        "app_state": {
            "network_enabled": true,
            "signal_bars": 3,
            "connection_type": "4g",
            "connected": false,
            "gps_has_fix": false
        },
        "views": {
            "setup": {
                "network_enabled": true,
                "network_rows": [
                    ["Status", "Registered"],
                    ["Carrier", "Telekom.de"],
                    ["Type", "4G"],
                    ["Signal", "3/4"],
                    ["PPP", "Down"]
                ],
                "gps_rows": [
                    ["Fix", "Searching"],
                    ["Lat", "--"],
                    ["Lng", "--"],
                    ["Alt", "--"],
                    ["Speed", "--"]
                ]
            }
        }
    }));

    let ui = state.ui_snapshot_payload();
    let pages = ui["power"]["pages"].as_array().expect("setup pages");

    assert_eq!(pages.len(), 6);
    assert_eq!(pages[0]["title"], "Power");
    assert_eq!(pages[1]["title"], "Network");
    assert_eq!(pages[1]["icon_key"], "signal");
    assert_eq!(pages[1]["rows"][0], "Status: Registered");
    assert_eq!(pages[1]["rows"][1], "Carrier: Telekom.de");
    assert_eq!(pages[2]["title"], "GPS");
    assert_eq!(pages[2]["rows"][0], "Fix: Searching");
    assert_eq!(pages[5]["title"], "Voice");
    assert_eq!(pages[5]["icon_key"], "voice_note");
}

#[test]
fn ui_snapshot_uses_available_state_for_power_rows() {
    let mut state = RuntimeState::default();

    state.apply_voip_snapshot(&json!({
        "registered": true,
        "registration_state": "ok"
    }));

    let payload = state.ui_snapshot_payload();
    let rows = payload["power"]["rows"].as_array().expect("power rows");

    assert_eq!(rows[0], "Battery 100%");
    assert_eq!(rows[1], "On battery");
    assert_eq!(rows[2], "Network offline");
    assert_eq!(rows[3], "VoIP ready");
}

#[test]
fn ui_snapshot_hub_cards_keep_lvgl_python_subtitles_hidden() {
    let mut state = RuntimeState::default();

    state.apply_media_snapshot(&json!({
        "playback_state": "playing",
        "current_track": {"name": "Little Song"}
    }));
    state.apply_voip_snapshot(&json!({
        "call_state": "incoming",
        "contacts": [{
            "id": "sip:mama@example.test",
            "title": "Mama",
            "subtitle": "sip:mama@example.test",
            "icon_key": "person"
        }]
    }));

    let payload = state.ui_snapshot_payload();
    let cards = payload["hub"]["cards"].as_array().expect("hub cards");

    assert_eq!(cards[0]["subtitle"], "");
    assert_eq!(cards[1]["subtitle"], "");
    assert_eq!(cards[2]["subtitle"], "");
    assert_eq!(cards[3]["subtitle"], "");
    assert_eq!(cards[0]["accent"], 0x00FF88);
    assert_eq!(cards[1]["accent"], 0x00D4FF);
    assert_eq!(cards[2]["accent"], 0xFFD000);
    assert_eq!(cards[3]["accent"], 0x9CA3AF);
}

#[test]
fn voip_snapshot_normalizes_current_worker_call_states() {
    let mut state = RuntimeState::default();

    state.apply_voip_snapshot(&json!({"call_state": "streams_running"}));
    assert_eq!(state.call.state, CallState::Active);
    assert_eq!(state.ui_snapshot_payload()["call"]["state"], "active");

    state.apply_voip_snapshot(&json!({"call_state": "outgoing_init"}));
    assert_eq!(state.call.state, CallState::Outgoing);
    assert_eq!(state.ui_snapshot_payload()["call"]["state"], "outgoing");

    state.apply_voip_snapshot(&json!({"call_state": "outgoing_custom"}));
    assert_eq!(state.call.state, CallState::Outgoing);
    assert_eq!(state.ui_snapshot_payload()["call"]["state"], "outgoing");

    state.apply_voip_snapshot(&json!({"call_state": "released"}));
    assert_eq!(state.call.state, CallState::Idle);
    assert_eq!(state.ui_snapshot_payload()["call"]["state"], "idle");
}

#[test]
fn worker_state_is_visible_in_status() {
    let mut state = RuntimeState::default();

    state.mark_worker(WorkerDomain::Media, WorkerState::Degraded, "process_exited");

    let status = state.status_payload();
    assert_eq!(status["workers"]["media"]["state"], "degraded");
    assert_eq!(status["workers"]["media"]["last_reason"], "process_exited");
}

#[test]
fn ui_snapshot_payload_decodes_into_ui_host_compatible_shape() {
    let mut state = RuntimeState::default();

    state.apply_media_snapshot(&json!({
        "playback_state": "playing",
        "time_position_ms": 30_000,
        "current_track": {
            "name": "Little Song",
            "artists": ["YoYo"],
            "length_ms": 120_000
        },
        "playlists": [{"uri": "playlist://sleep", "name": "Sleep", "track_count": 3}]
    }));
    state.apply_voip_snapshot(&json!({
        "call_state": "streams_running",
        "active_call_peer": "sip:mama@example.test",
        "call_session": {"duration_seconds": 75},
        "recent_call_history": [{
            "peer_sip_address": "sip:dad@example.test",
            "direction": "incoming",
            "outcome": "missed",
            "duration_seconds": 0,
            "seen": false
        }]
    }));

    let snapshot: UiRuntimeSnapshot =
        serde_json::from_value(state.ui_snapshot_payload()).expect("ui snapshot schema");

    assert_eq!(snapshot.app_state, "hub");
    assert_eq!(snapshot.hub.cards[0].key, "listen");
    assert_eq!(snapshot.music.title, "Little Song");
    assert_eq!(snapshot.music.progress_permille, 250);
    assert_eq!(snapshot.music.playlists[0].subtitle, "3 tracks");
    assert_eq!(snapshot.call.state, "active");
    assert_eq!(snapshot.call.peer_name, "sip:mama@example.test");
    assert_eq!(snapshot.call.duration_text, "01:15");
    assert_eq!(snapshot.call.history[0].title, "sip:dad@example.test");
    assert_eq!(snapshot.voice.phase, "idle");
    assert!(snapshot.power.power_available);
    assert!(!snapshot.network.connected);
    assert_eq!(snapshot.network.connection_type, "none");
    assert!(!snapshot.overlay.loading);
}

#[derive(Debug, Deserialize)]
struct UiRuntimeSnapshot {
    app_state: String,
    hub: UiHubSnapshot,
    music: UiMusicSnapshot,
    call: UiCallSnapshot,
    voice: UiVoiceSnapshot,
    power: UiPowerSnapshot,
    network: UiNetworkSnapshot,
    overlay: UiOverlaySnapshot,
}

#[derive(Debug, Deserialize)]
struct UiHubSnapshot {
    cards: Vec<UiHubCardSnapshot>,
}

#[derive(Debug, Deserialize)]
struct UiHubCardSnapshot {
    key: String,
}

#[derive(Debug, Deserialize)]
struct UiMusicSnapshot {
    title: String,
    progress_permille: i32,
    playlists: Vec<UiListItemSnapshot>,
}

#[derive(Debug, Deserialize)]
struct UiCallSnapshot {
    state: String,
    peer_name: String,
    duration_text: String,
    history: Vec<UiListItemSnapshot>,
}

#[derive(Debug, Deserialize)]
struct UiVoiceSnapshot {
    phase: String,
}

#[derive(Debug, Deserialize)]
struct UiPowerSnapshot {
    power_available: bool,
}

#[derive(Debug, Deserialize)]
struct UiNetworkSnapshot {
    connected: bool,
    connection_type: String,
}

#[derive(Debug, Deserialize)]
struct UiOverlaySnapshot {
    loading: bool,
}

#[derive(Debug, Deserialize)]
struct UiListItemSnapshot {
    title: String,
    subtitle: String,
}
