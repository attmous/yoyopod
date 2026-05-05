use serde_json::json;
use yoyopod_ui_host::input::InputAction;
use yoyopod_ui_host::runtime::{
    ListItemSnapshot, RuntimeSnapshot, UiIntent, UiRuntime, UiScreen, UiView,
};
use yoyopod_ui_host::screens::ScreenModel;

#[test]
fn default_snapshot_starts_on_hub() {
    let mut runtime = UiRuntime::default();

    runtime.apply_snapshot(RuntimeSnapshot::default());

    assert_eq!(runtime.active_screen(), UiScreen::Hub);
    assert_eq!(runtime.focus_index(), 0);
    assert!(runtime.take_intents().is_empty());
}

#[test]
fn runtime_snapshot_app_state_selects_current_route_when_not_preempted() {
    let mut runtime = UiRuntime::default();
    let mut snapshot = RuntimeSnapshot::default();
    snapshot.app_state = "playlists".to_string();

    runtime.apply_snapshot(snapshot);

    assert_eq!(runtime.active_screen(), UiScreen::Playlists);
    assert!(runtime.stack().is_empty());
}

#[test]
fn runtime_snapshot_preemption_overrides_app_state_route() {
    let mut runtime = UiRuntime::default();
    let mut snapshot = RuntimeSnapshot::default();
    snapshot.app_state = "playlists".to_string();
    snapshot.call.state = "incoming".to_string();

    runtime.apply_snapshot(snapshot);

    assert_eq!(runtime.active_screen(), UiScreen::IncomingCall);
}

#[test]
fn hub_advance_cycles_focus_through_cards() {
    let mut runtime = UiRuntime::default();
    runtime.apply_snapshot(RuntimeSnapshot::default());

    runtime.handle_input(InputAction::Advance);
    runtime.handle_input(InputAction::Advance);
    runtime.handle_input(InputAction::Advance);
    runtime.handle_input(InputAction::Advance);

    assert_eq!(runtime.active_screen(), UiScreen::Hub);
    assert_eq!(runtime.focus_index(), 0);
}

#[test]
fn hub_select_pushes_listen_and_back_returns_home() {
    let mut runtime = UiRuntime::default();
    runtime.apply_snapshot(RuntimeSnapshot::default());

    runtime.handle_input(InputAction::Select);
    assert_eq!(runtime.active_screen(), UiScreen::Listen);
    assert_eq!(runtime.stack(), &[UiScreen::Hub]);

    runtime.handle_input(InputAction::Back);
    assert_eq!(runtime.active_screen(), UiScreen::Hub);
    assert!(runtime.stack().is_empty());
}

#[test]
fn hub_select_opens_focused_route() {
    let routes = [
        UiScreen::Listen,
        UiScreen::Talk,
        UiScreen::Ask,
        UiScreen::Power,
    ];

    for (advance_count, expected_screen) in routes.into_iter().enumerate() {
        let mut runtime = UiRuntime::default();
        runtime.apply_snapshot(RuntimeSnapshot::default());
        for _ in 0..advance_count {
            runtime.handle_input(InputAction::Advance);
        }

        runtime.handle_input(InputAction::Select);

        assert_eq!(runtime.active_screen(), expected_screen);
    }
}

#[test]
fn listen_and_talk_routes_cover_full_one_button_tree() {
    let mut runtime = UiRuntime::default();
    runtime.apply_snapshot(RuntimeSnapshot::default());

    runtime.handle_input(InputAction::Select);
    assert_eq!(runtime.active_screen(), UiScreen::Listen);
    runtime.handle_input(InputAction::Advance);
    runtime.handle_input(InputAction::Select);
    assert_eq!(runtime.active_screen(), UiScreen::RecentTracks);

    runtime.handle_input(InputAction::Back);
    runtime.handle_input(InputAction::Back);
    runtime.handle_input(InputAction::Advance);
    runtime.handle_input(InputAction::Select);
    assert_eq!(runtime.active_screen(), UiScreen::Talk);
    runtime.handle_input(InputAction::Advance);
    runtime.handle_input(InputAction::Advance);
    runtime.handle_input(InputAction::Select);
    assert_eq!(runtime.active_screen(), UiScreen::VoiceNote);
}

#[test]
fn listen_select_order_matches_python_lvgl_menu() {
    let mut runtime = UiRuntime::default();
    runtime.apply_snapshot(RuntimeSnapshot::default());

    runtime.handle_input(InputAction::Select);
    assert_eq!(runtime.active_screen(), UiScreen::Listen);

    let view = runtime.active_view();
    let item_titles: Vec<&str> = view.items.iter().map(|item| item.title.as_str()).collect();
    assert_eq!(item_titles, vec!["Playlists", "Recent", "Shuffle All"]);

    runtime.handle_input(InputAction::Select);
    assert_eq!(runtime.active_screen(), UiScreen::Playlists);

    runtime.handle_input(InputAction::Back);
    assert_eq!(runtime.active_screen(), UiScreen::Listen);
    runtime.handle_input(InputAction::Advance);
    runtime.handle_input(InputAction::Select);
    assert_eq!(runtime.active_screen(), UiScreen::RecentTracks);
}

#[test]
fn setup_pages_cycle_with_python_one_button_flow() {
    let mut runtime = UiRuntime::default();
    runtime.apply_snapshot(RuntimeSnapshot::default());

    for _ in 0..3 {
        runtime.handle_input(InputAction::Advance);
    }
    runtime.handle_input(InputAction::Select);

    assert_eq!(runtime.active_screen(), UiScreen::Power);
    match runtime.active_screen_model() {
        ScreenModel::Power(model) => {
            assert_eq!(model.title, "Power");
            assert_eq!(model.icon_key, "battery");
            assert_eq!(model.chrome.footer, "Tap page / Hold back");
            assert_eq!(model.current_page_index, 0);
            assert_eq!(model.total_pages, 4);
            assert!(model.rows.iter().any(|row| row.title == "Battery: 100%"));
        }
        other => panic!("expected setup power model, got {other:?}"),
    }

    runtime.handle_input(InputAction::Advance);
    match runtime.active_screen_model() {
        ScreenModel::Power(model) => {
            assert_eq!(model.title, "Time");
            assert_eq!(model.icon_key, "clock");
            assert_eq!(model.current_page_index, 1);
            assert!(model.rows.iter().any(|row| row.title == "RTC: Unknown"));
        }
        other => panic!("expected setup time model, got {other:?}"),
    }

    runtime.handle_input(InputAction::Advance);
    match runtime.active_screen_model() {
        ScreenModel::Power(model) => {
            assert_eq!(model.title, "Care");
            assert_eq!(model.icon_key, "care");
            assert_eq!(model.current_page_index, 2);
        }
        other => panic!("expected setup care model, got {other:?}"),
    }

    runtime.handle_input(InputAction::Advance);
    match runtime.active_screen_model() {
        ScreenModel::Power(model) => {
            assert_eq!(model.title, "Voice");
            assert_eq!(model.icon_key, "voice_note");
            assert_eq!(model.current_page_index, 3);
            assert!(model
                .rows
                .iter()
                .any(|row| row.title == "Voice Cmds: Unknown"));
        }
        other => panic!("expected setup voice model, got {other:?}"),
    }

    runtime.handle_input(InputAction::Select);
    match runtime.active_screen_model() {
        ScreenModel::Power(model) => {
            assert_eq!(model.title, "Power");
            assert_eq!(model.current_page_index, 0);
        }
        other => panic!("expected setup power model after wrap, got {other:?}"),
    }

    runtime.handle_input(InputAction::Back);
    assert_eq!(runtime.active_screen(), UiScreen::Hub);
}

#[test]
fn setup_pages_include_network_and_gps_when_runtime_projects_rows() {
    let mut runtime = UiRuntime::default();
    let mut snapshot = RuntimeSnapshot::default();
    snapshot.network.enabled = true;
    snapshot.power.pages = vec![
        yoyopod_ui_host::runtime::PowerPageSnapshot {
            title: "Power".to_string(),
            icon_key: "battery".to_string(),
            rows: vec!["Battery: 88%".to_string()],
        },
        yoyopod_ui_host::runtime::PowerPageSnapshot {
            title: "Network".to_string(),
            icon_key: "signal".to_string(),
            rows: vec![
                "Status: Registered".to_string(),
                "Carrier: Telekom.de".to_string(),
            ],
        },
        yoyopod_ui_host::runtime::PowerPageSnapshot {
            title: "GPS".to_string(),
            icon_key: "care".to_string(),
            rows: vec!["Fix: Searching".to_string()],
        },
        yoyopod_ui_host::runtime::PowerPageSnapshot {
            title: "Time".to_string(),
            icon_key: "clock".to_string(),
            rows: vec!["RTC: Unknown".to_string()],
        },
        yoyopod_ui_host::runtime::PowerPageSnapshot {
            title: "Care".to_string(),
            icon_key: "care".to_string(),
            rows: vec!["Watchdog: Off".to_string()],
        },
        yoyopod_ui_host::runtime::PowerPageSnapshot {
            title: "Voice".to_string(),
            icon_key: "voice_note".to_string(),
            rows: vec!["Voice Cmds: Unknown".to_string()],
        },
    ];
    runtime.apply_snapshot(snapshot);

    runtime.handle_input(InputAction::Advance);
    runtime.handle_input(InputAction::Advance);
    runtime.handle_input(InputAction::Advance);
    runtime.handle_input(InputAction::Select);
    assert_eq!(runtime.active_screen(), UiScreen::Power);

    runtime.handle_input(InputAction::Advance);
    match runtime.active_screen_model() {
        ScreenModel::Power(model) => {
            assert_eq!(model.title, "Network");
            assert_eq!(model.icon_key, "signal");
            assert_eq!(model.total_pages, 6);
            assert_eq!(model.rows[0].title, "Status: Registered");
        }
        other => panic!("expected setup network model, got {other:?}"),
    }

    runtime.handle_input(InputAction::Advance);
    match runtime.active_screen_model() {
        ScreenModel::Power(model) => {
            assert_eq!(model.title, "GPS");
            assert_eq!(model.icon_key, "care");
            assert_eq!(model.rows[0].title, "Fix: Searching");
        }
        other => panic!("expected setup gps model, got {other:?}"),
    }
}

#[test]
fn incoming_call_snapshot_preempts_current_screen() {
    let mut runtime = UiRuntime::default();
    runtime.apply_snapshot(RuntimeSnapshot::default());
    runtime.handle_input(InputAction::Select);
    assert_eq!(runtime.active_screen(), UiScreen::Listen);

    let mut snapshot = RuntimeSnapshot::default();
    snapshot.call.state = "incoming".to_string();
    snapshot.call.peer_name = "Mama".to_string();
    snapshot.call.peer_address = "sip:mama@example.com".to_string();
    runtime.apply_snapshot(snapshot);

    assert_eq!(runtime.active_screen(), UiScreen::IncomingCall);
    assert_eq!(runtime.active_view().title, "Mama");
}

#[test]
fn incoming_call_preempts_current_screen_and_idle_returns() {
    let mut runtime = UiRuntime::default();
    runtime.apply_snapshot(RuntimeSnapshot::default());
    runtime.handle_input(InputAction::Select);
    assert_eq!(runtime.active_screen(), UiScreen::Listen);

    let mut snapshot = RuntimeSnapshot::default();
    snapshot.call.state = "incoming".to_string();
    runtime.apply_snapshot(snapshot.clone());
    assert_eq!(runtime.active_screen(), UiScreen::IncomingCall);

    snapshot.call.state = "idle".to_string();
    runtime.apply_snapshot(snapshot);
    assert_eq!(runtime.active_screen(), UiScreen::Listen);
}

#[test]
fn loading_and_error_overlays_preempt_runtime_routes() {
    let mut runtime = UiRuntime::default();
    runtime.apply_snapshot(RuntimeSnapshot::default());
    runtime.handle_input(InputAction::Advance);
    runtime.handle_input(InputAction::Select);
    assert_eq!(runtime.active_screen(), UiScreen::Talk);

    let mut snapshot = RuntimeSnapshot::default();
    snapshot.overlay.loading = true;
    snapshot.overlay.message = "Syncing".to_string();
    runtime.apply_snapshot(snapshot.clone());
    assert_eq!(runtime.active_screen(), UiScreen::Loading);

    snapshot.overlay.loading = false;
    runtime.apply_snapshot(snapshot.clone());
    assert_eq!(runtime.active_screen(), UiScreen::Talk);

    snapshot.overlay.error = "Network down".to_string();
    runtime.apply_snapshot(snapshot.clone());
    assert_eq!(runtime.active_screen(), UiScreen::Error);

    snapshot.overlay.error.clear();
    runtime.apply_snapshot(snapshot);
    assert_eq!(runtime.active_screen(), UiScreen::Talk);
}

#[test]
fn incoming_call_select_emits_answer_intent() {
    let mut runtime = UiRuntime::default();
    let mut snapshot = RuntimeSnapshot::default();
    snapshot.call.state = "incoming".to_string();
    runtime.apply_snapshot(snapshot);

    runtime.handle_input(InputAction::Select);

    assert_eq!(
        runtime.take_intents(),
        vec![UiIntent::new("call", "answer")]
    );
    assert_eq!(runtime.active_screen(), UiScreen::IncomingCall);
}

#[test]
fn recent_track_select_emits_play_recent_track_intent() {
    let mut runtime = UiRuntime::default();
    let mut snapshot = RuntimeSnapshot::default();
    snapshot.music.recent_tracks = vec![ListItemSnapshot::new(
        "file:///music/song.mp3",
        "Little Song",
        "YoYo",
        "track",
    )];
    runtime.apply_snapshot(snapshot);

    runtime.handle_input(InputAction::Select);
    runtime.handle_input(InputAction::Advance);
    runtime.handle_input(InputAction::Select);
    runtime.handle_input(InputAction::Select);

    assert_eq!(runtime.active_screen(), UiScreen::NowPlaying);
    assert_eq!(
        runtime.take_intents(),
        vec![UiIntent::with_payload(
            "music",
            "play_recent_track",
            json!({"id": "file:///music/song.mp3", "title": "Little Song"}),
        )]
    );
}

#[test]
fn contacts_open_talk_action_picker_before_dialing() {
    let mut runtime = UiRuntime::default();
    let mut snapshot = RuntimeSnapshot::default();
    snapshot.app_state = "contacts".to_string();
    snapshot.call.contacts = vec![ListItemSnapshot::new(
        "sip:mama@example.test",
        "Mama",
        "",
        "mono:MA",
    )];
    runtime.apply_snapshot(snapshot);

    runtime.handle_input(InputAction::Select);

    assert_eq!(runtime.active_screen(), UiScreen::TalkContact);
    assert!(runtime.take_intents().is_empty());
    let view = runtime.active_view();
    assert_eq!(view.title, "Mama");
    let action_titles = view
        .items
        .iter()
        .map(|item| item.title.as_str())
        .collect::<Vec<_>>();
    assert_eq!(action_titles, vec!["Call", "Voice Note"]);

    runtime.handle_input(InputAction::Select);

    assert_eq!(
        runtime.take_intents(),
        vec![UiIntent::with_payload(
            "call",
            "start",
            json!({"id": "sip:mama@example.test", "name": "Mama"}),
        )]
    );
}

#[test]
fn talk_contact_adds_play_note_when_latest_voice_note_exists() {
    let mut runtime = UiRuntime::default();
    let mut snapshot = RuntimeSnapshot::default();
    snapshot.app_state = "contacts".to_string();
    snapshot.call.contacts = vec![ListItemSnapshot::new(
        "sip:mama@example.test",
        "Mama",
        "",
        "mono:MA",
    )];
    snapshot.call.latest_voice_note_by_contact.insert(
        "sip:mama@example.test".to_string(),
        yoyopod_ui_host::runtime::VoiceNoteSummarySnapshot {
            local_file_path: "/tmp/mama-note.wav".to_string(),
            unread: true,
            ..Default::default()
        },
    );
    runtime.apply_snapshot(snapshot);

    runtime.handle_input(InputAction::Select);

    let view = runtime.active_view();
    let action_titles = view
        .items
        .iter()
        .map(|item| item.title.as_str())
        .collect::<Vec<_>>();
    assert_eq!(action_titles, vec!["Call", "Voice Note", "Play Note"]);

    runtime.handle_input(InputAction::Advance);
    runtime.handle_input(InputAction::Advance);
    runtime.handle_input(InputAction::Select);

    assert_eq!(
        runtime.take_intents(),
        vec![UiIntent::with_payload(
            "voice",
            "play_latest",
            json!({
                "id": "sip:mama@example.test",
                "recipient_name": "Mama",
                "file_path": "/tmp/mama-note.wav"
            }),
        )]
    );
}

#[test]
fn voice_note_review_actions_emit_send_play_and_discard() {
    let mut runtime = UiRuntime::default();
    let mut snapshot = RuntimeSnapshot::default();
    snapshot.app_state = "voice_note".to_string();
    snapshot.call.contacts = vec![ListItemSnapshot::new(
        "sip:mama@example.test",
        "Mama",
        "",
        "mono:MA",
    )];
    snapshot.voice.phase = "review".to_string();
    runtime.apply_snapshot(snapshot);

    runtime.handle_input(InputAction::Select);
    assert_eq!(
        runtime.take_intents(),
        vec![UiIntent::with_payload(
            "voice",
            "send",
            json!({
                "id": "sip:mama@example.test",
                "recipient_address": "sip:mama@example.test",
                "recipient_name": "Mama"
            }),
        )]
    );

    runtime.handle_input(InputAction::Advance);
    runtime.handle_input(InputAction::Select);
    assert_eq!(runtime.take_intents(), vec![UiIntent::new("voice", "play")]);

    runtime.handle_input(InputAction::Advance);
    runtime.handle_input(InputAction::Select);
    assert_eq!(
        runtime.take_intents(),
        vec![UiIntent::new("voice", "discard")]
    );
}

#[test]
fn voice_note_ready_uses_hold_passthrough_for_recording() {
    let mut runtime = UiRuntime::default();
    let mut snapshot = RuntimeSnapshot::default();
    snapshot.app_state = "voice_note".to_string();
    snapshot.call.contacts = vec![ListItemSnapshot::new(
        "sip:mama@example.test",
        "Mama",
        "",
        "mono:MA",
    )];
    runtime.apply_snapshot(snapshot);

    assert!(runtime.wants_ptt_passthrough());
    runtime.handle_input(InputAction::PttPress);

    assert_eq!(
        runtime.take_intents(),
        vec![UiIntent::with_payload(
            "voice",
            "capture_start",
            json!({
                "id": "sip:mama@example.test",
                "recipient_address": "sip:mama@example.test",
                "recipient_name": "Mama"
            }),
        )]
    );
}

#[test]
fn ask_select_emits_ask_start_intent_not_voice_note_capture() {
    let mut runtime = UiRuntime::default();
    let mut snapshot = RuntimeSnapshot::default();
    snapshot.app_state = "ask".to_string();
    runtime.apply_snapshot(snapshot);

    runtime.handle_input(InputAction::Select);

    assert_eq!(
        runtime.take_intents(),
        vec![UiIntent::new("voice", "ask_start")]
    );
}

#[test]
fn ask_ptt_press_release_uses_ask_intents() {
    let mut runtime = UiRuntime::default();
    let mut snapshot = RuntimeSnapshot::default();
    snapshot.app_state = "ask".to_string();
    runtime.apply_snapshot(snapshot);

    runtime.handle_input(InputAction::PttPress);
    runtime.handle_input(InputAction::PttRelease);

    assert_eq!(
        runtime.take_intents(),
        vec![
            UiIntent::new("voice", "ask_start"),
            UiIntent::new("voice", "ask_stop")
        ]
    );
}

#[test]
fn required_screens_have_view_models() {
    let snapshot = RuntimeSnapshot::default();
    let screens = [
        UiScreen::Hub,
        UiScreen::Listen,
        UiScreen::Playlists,
        UiScreen::RecentTracks,
        UiScreen::NowPlaying,
        UiScreen::Ask,
        UiScreen::Talk,
        UiScreen::Contacts,
        UiScreen::CallHistory,
        UiScreen::TalkContact,
        UiScreen::VoiceNote,
        UiScreen::IncomingCall,
        UiScreen::OutgoingCall,
        UiScreen::InCall,
        UiScreen::Power,
        UiScreen::Loading,
        UiScreen::Error,
    ];

    for screen in screens {
        let view = UiRuntime::view_for_screen(screen, &snapshot, 0);
        assert_eq!(view.screen, screen);
        assert!(
            !view.title.trim().is_empty(),
            "{} needs a readable title",
            screen.as_str()
        );
    }
}

#[test]
fn active_screen_model_derives_hub_model_from_runtime_snapshot() {
    let mut runtime = UiRuntime::default();
    let snapshot = RuntimeSnapshot::default();

    runtime.apply_snapshot(snapshot);

    match runtime.active_screen_model() {
        ScreenModel::Hub(model) => {
            assert_eq!(model.cards.len(), 4);
            assert_eq!(model.selected_index, 0);
            assert_eq!(model.chrome.footer, "Tap = Next | 2x Tap = Open");
            assert_eq!(model.chrome.status.battery_percent, 100);
        }
        other => panic!("expected hub model, got {other:?}"),
    }
}

#[test]
fn typed_chrome_status_matches_preserved_busy_state_semantics() {
    for busy_state in ["incoming", "outgoing", "active"] {
        let mut snapshot = RuntimeSnapshot::default();
        snapshot.call.state = busy_state.to_string();

        let model = UiRuntime::screen_model_for_screen(UiScreen::Hub, &snapshot, 0);
        assert_eq!(
            chrome_voip_state(&model),
            Some(2),
            "{busy_state} should be busy"
        );
    }

    for idle_like_state in ["idle", "ringing", "ended"] {
        let mut snapshot = RuntimeSnapshot::default();
        snapshot.call.state = idle_like_state.to_string();

        let model = UiRuntime::screen_model_for_screen(UiScreen::Hub, &snapshot, 0);
        assert_eq!(
            chrome_voip_state(&model),
            Some(1),
            "{idle_like_state} should match the preserved non-busy status"
        );
    }
}

#[test]
fn active_screen_model_derives_incoming_call_from_preempted_route() {
    let mut runtime = UiRuntime::default();
    runtime.apply_snapshot(RuntimeSnapshot::default());
    runtime.handle_input(InputAction::Select);

    let mut snapshot = RuntimeSnapshot::default();
    snapshot.call.state = "incoming".to_string();
    snapshot.call.peer_name = "Mama".to_string();
    snapshot.call.peer_address = "sip:mama@example.com".to_string();

    runtime.apply_snapshot(snapshot);

    match runtime.active_screen_model() {
        ScreenModel::IncomingCall(model) => {
            assert_eq!(model.title, "Mama");
            assert_eq!(model.subtitle, "sip:mama@example.com");
            assert_eq!(model.chrome.status.voip_state, 2);
        }
        other => panic!("expected incoming call model, got {other:?}"),
    }
}

#[test]
fn required_screens_have_typed_models() {
    let snapshot = RuntimeSnapshot::default();
    let screens = [
        UiScreen::Hub,
        UiScreen::Listen,
        UiScreen::Playlists,
        UiScreen::RecentTracks,
        UiScreen::NowPlaying,
        UiScreen::Ask,
        UiScreen::Talk,
        UiScreen::Contacts,
        UiScreen::CallHistory,
        UiScreen::TalkContact,
        UiScreen::VoiceNote,
        UiScreen::IncomingCall,
        UiScreen::OutgoingCall,
        UiScreen::InCall,
        UiScreen::Power,
        UiScreen::Loading,
        UiScreen::Error,
    ];

    for screen in screens {
        let model = UiRuntime::screen_model_for_screen(screen, &snapshot, 0);
        assert_eq!(model.screen(), screen);
    }
}

#[test]
fn typed_models_stay_in_sync_with_view_builders() {
    let mut list_snapshot = RuntimeSnapshot::default();
    list_snapshot.music.title = "Little Song".to_string();
    list_snapshot.music.artist = "YoYo".to_string();
    list_snapshot.music.playing = true;
    list_snapshot.music.progress_permille = 432;
    list_snapshot.music.playlists = vec![
        ListItemSnapshot::new("playlist-1", "Bedtime", "Soft songs", "playlist"),
        ListItemSnapshot::new("playlist-2", "Dance", "Fast songs", "playlist"),
    ];
    list_snapshot.music.recent_tracks = vec![
        ListItemSnapshot::new("track-1", "Moon", "YoYo", "track"),
        ListItemSnapshot::new("track-2", "Sun", "YoYo", "track"),
    ];
    list_snapshot.call.contacts = vec![
        ListItemSnapshot::new("contact-1", "Mama", "Home", "contact"),
        ListItemSnapshot::new("contact-2", "Baba", "Mobile", "contact"),
    ];
    list_snapshot.call.history = vec![
        ListItemSnapshot::new("history-1", "Grandma", "Yesterday", "history"),
        ListItemSnapshot::new("history-2", "Grandpa", "Today", "history"),
    ];
    list_snapshot.call.peer_name = "Mama".to_string();
    list_snapshot.call.peer_address = "sip:mama@example.com".to_string();
    list_snapshot.call.duration_text = "00:42".to_string();
    list_snapshot.call.muted = true;
    list_snapshot.voice.headline = "Ask".to_string();
    list_snapshot.voice.body = "How high is the moon?".to_string();
    list_snapshot.voice.capture_in_flight = true;
    list_snapshot.power.battery_percent = 67;
    list_snapshot.power.charging = true;
    list_snapshot.power.rows = vec!["Battery healthy".to_string(), "USB-C connected".to_string()];
    list_snapshot.overlay.message = "Syncing".to_string();
    list_snapshot.overlay.error = "Network down".to_string();

    let cases = vec![
        (UiScreen::Hub, RuntimeSnapshot::default(), 2usize),
        (UiScreen::Listen, list_snapshot.clone(), 2usize),
        (UiScreen::Playlists, list_snapshot.clone(), 1usize),
        (UiScreen::RecentTracks, list_snapshot.clone(), 1usize),
        (UiScreen::NowPlaying, list_snapshot.clone(), 0usize),
        (UiScreen::Ask, list_snapshot.clone(), 0usize),
        (UiScreen::Talk, list_snapshot.clone(), 2usize),
        (UiScreen::Contacts, list_snapshot.clone(), 1usize),
        (UiScreen::CallHistory, list_snapshot.clone(), 1usize),
        (UiScreen::TalkContact, list_snapshot.clone(), 1usize),
        (UiScreen::VoiceNote, list_snapshot.clone(), 0usize),
        (
            UiScreen::IncomingCall,
            with_call_state(&list_snapshot, "incoming"),
            0usize,
        ),
        (
            UiScreen::OutgoingCall,
            with_call_state(&list_snapshot, "outgoing"),
            0usize,
        ),
        (
            UiScreen::InCall,
            with_call_state(&list_snapshot, "active"),
            0usize,
        ),
        (UiScreen::Power, list_snapshot.clone(), 1usize),
        (UiScreen::Loading, with_loading(&list_snapshot), 0usize),
        (UiScreen::Error, list_snapshot.clone(), 0usize),
    ];

    for (screen, snapshot, focus_index) in cases {
        let view = UiRuntime::view_for_screen(screen, &snapshot, focus_index);
        let model = UiRuntime::screen_model_for_screen(screen, &snapshot, focus_index);

        assert_eq!(
            model.screen(),
            view.screen,
            "{} variant drifted",
            screen.as_str()
        );
        assert_eq!(
            parity_projection_for_model(&model),
            parity_projection_for_view(&view),
            "{} model/view builders drifted",
            screen.as_str()
        );
    }
}

#[derive(Debug, PartialEq, Eq)]
struct ParityRow {
    id: String,
    title: String,
    subtitle: String,
    icon_key: String,
    selected: bool,
}

#[derive(Debug, PartialEq, Eq)]
struct ScreenParityProjection {
    title: String,
    subtitle: String,
    footer: String,
    focus_index: usize,
    rows: Vec<ParityRow>,
}

fn chrome_voip_state(model: &ScreenModel) -> Option<i32> {
    match model {
        ScreenModel::Hub(model) => Some(model.chrome.status.voip_state),
        ScreenModel::Listen(model)
        | ScreenModel::Playlists(model)
        | ScreenModel::RecentTracks(model)
        | ScreenModel::Talk(model)
        | ScreenModel::Contacts(model)
        | ScreenModel::CallHistory(model) => Some(model.chrome.status.voip_state),
        ScreenModel::NowPlaying(model) => Some(model.chrome.status.voip_state),
        ScreenModel::Ask(model) => Some(model.chrome.status.voip_state),
        ScreenModel::TalkContact(model) | ScreenModel::VoiceNote(model) => {
            Some(model.chrome.status.voip_state)
        }
        ScreenModel::IncomingCall(model)
        | ScreenModel::OutgoingCall(model)
        | ScreenModel::InCall(model) => Some(model.chrome.status.voip_state),
        ScreenModel::Power(model) => Some(model.chrome.status.voip_state),
        ScreenModel::Loading(model) | ScreenModel::Error(model) => {
            Some(model.chrome.status.voip_state)
        }
    }
}

fn parity_projection_for_view(view: &UiView) -> ScreenParityProjection {
    ScreenParityProjection {
        title: view.title.clone(),
        subtitle: view.subtitle.clone(),
        footer: view.footer.clone(),
        focus_index: view.focus_index,
        rows: view
            .items
            .iter()
            .enumerate()
            .map(|(index, item)| ParityRow {
                id: item.id.clone(),
                title: item.title.clone(),
                subtitle: item.subtitle.clone(),
                icon_key: item.icon_key.clone(),
                selected: view.screen != UiScreen::Power && index == view.focus_index,
            })
            .collect(),
    }
}

fn parity_projection_for_model(model: &ScreenModel) -> ScreenParityProjection {
    match model {
        ScreenModel::Hub(model) => {
            let rows: Vec<ParityRow> = model
                .cards
                .iter()
                .enumerate()
                .map(|(index, card)| ParityRow {
                    id: card.key.clone(),
                    title: card.title.clone(),
                    subtitle: card.subtitle.clone(),
                    icon_key: card.key.clone(),
                    selected: index == model.selected_index,
                })
                .collect();
            let focused = model
                .cards
                .get(model.selected_index)
                .or_else(|| model.cards.first());

            ScreenParityProjection {
                title: focused
                    .map(|card| card.title.clone())
                    .unwrap_or_else(|| "Listen".to_string()),
                subtitle: focused
                    .map(|card| card.subtitle.clone())
                    .unwrap_or_default(),
                footer: model.chrome.footer.clone(),
                focus_index: model.selected_index,
                rows,
            }
        }
        ScreenModel::Listen(model)
        | ScreenModel::Playlists(model)
        | ScreenModel::RecentTracks(model)
        | ScreenModel::Talk(model)
        | ScreenModel::Contacts(model)
        | ScreenModel::CallHistory(model) => ScreenParityProjection {
            title: model.title.clone(),
            subtitle: model.subtitle.clone(),
            footer: model.chrome.footer.clone(),
            focus_index: model.rows.iter().position(|row| row.selected).unwrap_or(0),
            rows: model
                .rows
                .iter()
                .map(|row| ParityRow {
                    id: row.id.clone(),
                    title: row.title.clone(),
                    subtitle: row.subtitle.clone(),
                    icon_key: row.icon_key.clone(),
                    selected: row.selected,
                })
                .collect(),
        },
        ScreenModel::NowPlaying(model) => ScreenParityProjection {
            title: model.title.clone(),
            subtitle: model.artist.clone(),
            footer: model.chrome.footer.clone(),
            focus_index: 0,
            rows: Vec::new(),
        },
        ScreenModel::Ask(model) => ScreenParityProjection {
            title: model.title.clone(),
            subtitle: model.subtitle.clone(),
            footer: model.chrome.footer.clone(),
            focus_index: 0,
            rows: Vec::new(),
        },
        ScreenModel::TalkContact(model) | ScreenModel::VoiceNote(model) => ScreenParityProjection {
            title: model.contact_name.clone(),
            subtitle: model.status.clone(),
            footer: model.chrome.footer.clone(),
            focus_index: model.selected_index,
            rows: if model.layout_kind == 1 {
                Vec::new()
            } else {
                model
                    .buttons
                    .iter()
                    .enumerate()
                    .map(|(index, button)| ParityRow {
                        id: if matches!(model.buttons.first(), Some(first) if first.title == "Call")
                        {
                            format!("talk_action_{index}")
                        } else {
                            format!("voice_note_action_{index}")
                        },
                        title: button.title.clone(),
                        subtitle: String::new(),
                        icon_key: button.icon_key.clone(),
                        selected: index == model.selected_index,
                    })
                    .collect()
            },
        },
        ScreenModel::IncomingCall(model)
        | ScreenModel::OutgoingCall(model)
        | ScreenModel::InCall(model) => ScreenParityProjection {
            title: model.title.clone(),
            subtitle: model.subtitle.clone(),
            footer: model.chrome.footer.clone(),
            focus_index: 0,
            rows: Vec::new(),
        },
        ScreenModel::Power(model) => ScreenParityProjection {
            title: model.title.clone(),
            subtitle: model.subtitle.clone(),
            footer: model.chrome.footer.clone(),
            focus_index: model.current_page_index,
            rows: model
                .rows
                .iter()
                .map(|row| ParityRow {
                    id: row.id.clone(),
                    title: row.title.clone(),
                    subtitle: row.subtitle.clone(),
                    icon_key: row.icon_key.clone(),
                    selected: row.selected,
                })
                .collect(),
        },
        ScreenModel::Loading(model) | ScreenModel::Error(model) => ScreenParityProjection {
            title: model.title.clone(),
            subtitle: model.subtitle.clone(),
            footer: model.chrome.footer.clone(),
            focus_index: 0,
            rows: Vec::new(),
        },
    }
}

fn with_call_state(snapshot: &RuntimeSnapshot, state: &str) -> RuntimeSnapshot {
    let mut snapshot = snapshot.clone();
    snapshot.call.state = state.to_string();
    snapshot
}

fn with_loading(snapshot: &RuntimeSnapshot) -> RuntimeSnapshot {
    let mut snapshot = snapshot.clone();
    snapshot.overlay.loading = true;
    snapshot
}
