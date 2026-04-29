use serde_json::json;
use yoyopod_ui_host::input::InputAction;
use yoyopod_ui_host::runtime::{ListItemSnapshot, RuntimeSnapshot, UiIntent, UiRuntime, UiScreen};

#[test]
fn default_snapshot_starts_on_hub() {
    let mut runtime = UiRuntime::default();

    runtime.apply_snapshot(RuntimeSnapshot::default());

    assert_eq!(runtime.active_screen(), UiScreen::Hub);
    assert_eq!(runtime.focus_index(), 0);
    assert!(runtime.take_intents().is_empty());
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
