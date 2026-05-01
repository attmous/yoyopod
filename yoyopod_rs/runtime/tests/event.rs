use serde_json::{json, Value};
use yoyopod_runtime::event::{
    commands_for_event, runtime_event_from_worker, RuntimeCommand, RuntimeEvent,
};
use yoyopod_runtime::protocol::{EnvelopeKind, WorkerEnvelope};
use yoyopod_runtime::state::{CallState, RuntimeState, WorkerDomain, WorkerState};

#[test]
fn media_snapshot_event_updates_state() {
    let event = runtime_event_from_worker(
        WorkerDomain::Media,
        event_envelope(
            "media.snapshot",
            json!({
                "playback_state": "playing"
            }),
        ),
    )
    .expect("event");
    let mut state = RuntimeState::default();
    event.apply(&mut state);

    assert_eq!(state.media.playback_state, "playing");
}

#[test]
fn network_snapshot_event_updates_status_snapshot() {
    let event = runtime_event_from_worker(
        WorkerDomain::Network,
        event_envelope(
            "network.snapshot",
            json!({
                "app_state": {
                    "network_enabled": true,
                    "signal_bars": 3,
                    "connection_type": "4g",
                    "connected": true,
                    "gps_has_fix": true
                }
            }),
        ),
    )
    .expect("event");
    let mut state = RuntimeState::default();

    event.apply(&mut state);

    let network = &state.ui_snapshot_payload()["network"];
    assert_eq!(network["enabled"], true);
    assert_eq!(network["connected"], true);
    assert_eq!(network["connection_type"], "4g");
    assert_eq!(network["signal_strength"], 3);
    assert_eq!(network["gps_has_fix"], true);
}

#[test]
fn network_snapshot_result_updates_status_snapshot() {
    let event = runtime_event_from_worker(
        WorkerDomain::Network,
        envelope(
            EnvelopeKind::Result,
            "network.health",
            json!({
                "snapshot": {
                    "enabled": true,
                    "connected": false,
                    "connection_type": "4g",
                    "signal": {"bars": 2},
                    "gps_has_fix": false
                }
            }),
        ),
    )
    .expect("event");
    let mut state = RuntimeState::default();

    event.apply(&mut state);

    let network = &state.ui_snapshot_payload()["network"];
    assert_eq!(network["enabled"], true);
    assert_eq!(network["connected"], false);
    assert_eq!(network["connection_type"], "4g");
    assert_eq!(network["signal_strength"], 2);
    assert_eq!(network["gps_has_fix"], false);
}

#[test]
fn worker_ready_event_marks_worker_running() {
    let event = runtime_event_from_worker(
        WorkerDomain::Media,
        event_envelope("media.ready", json!({"capabilities": ["playback"]})),
    )
    .expect("event");
    let mut state = RuntimeState::default();

    event.apply(&mut state);

    assert_eq!(state.media_worker.state, WorkerState::Running);
    assert_eq!(state.media_worker.last_reason, "ready");
}

#[test]
fn worker_error_marks_worker_degraded() {
    let event = runtime_event_from_worker(
        WorkerDomain::Voip,
        envelope(
            EnvelopeKind::Error,
            "voip.error",
            json!({"code": "backend", "message": "registration failed"}),
        ),
    )
    .expect("event");
    let mut state = RuntimeState::default();

    event.apply(&mut state);

    assert_eq!(state.voip_worker.state, WorkerState::Degraded);
    assert_eq!(state.voip_worker.last_reason, "registration failed");
}

#[test]
fn health_only_worker_domains_decode_ready_and_error_events() {
    for (domain, ready_type, error_type) in [
        (WorkerDomain::Network, "network.ready", "network.error"),
        (WorkerDomain::Power, "power.ready", "power.error"),
        (WorkerDomain::Voice, "voice.ready", "voice.error"),
    ] {
        let ready = runtime_event_from_worker(
            domain,
            event_envelope(ready_type, json!({"capabilities": []})),
        )
        .expect("ready event");
        let mut state = RuntimeState::default();

        ready.apply(&mut state);

        assert_eq!(
            state.status_payload()["workers"][domain.as_str()]["state"],
            "running"
        );

        let error = runtime_event_from_worker(
            domain,
            envelope(
                EnvelopeKind::Error,
                error_type,
                json!({"message": "worker failed"}),
            ),
        )
        .expect("error event");

        error.apply(&mut state);

        assert_eq!(
            state.status_payload()["workers"][domain.as_str()]["state"],
            "degraded"
        );
        assert_eq!(
            state.status_payload()["workers"][domain.as_str()]["last_reason"],
            "worker failed"
        );
    }
}

#[test]
fn ui_screen_changed_updates_state() {
    let event = runtime_event_from_worker(
        WorkerDomain::Ui,
        event_envelope("ui.screen_changed", json!({"screen": "listen"})),
    )
    .expect("event");
    let mut state = RuntimeState::default();

    event.apply(&mut state);

    assert_eq!(state.current_screen, "listen");
}

#[test]
fn result_and_unknown_events_are_ignored() {
    let mut state = RuntimeState::default();

    let result = runtime_event_from_worker(
        WorkerDomain::Media,
        envelope(
            EnvelopeKind::Result,
            "media.play",
            json!({"accepted": true}),
        ),
    )
    .expect("event");
    result.apply(&mut state);

    let unknown = runtime_event_from_worker(
        WorkerDomain::Ui,
        event_envelope("ui.unhandled", json!({"ignored": true})),
    )
    .expect("event");
    unknown.apply(&mut state);

    assert_eq!(state, RuntimeState::default());
    assert!(commands_for_event(&state, &result).is_empty());
    assert!(commands_for_event(&state, &unknown).is_empty());
}

#[test]
fn wrong_domain_ui_intent_is_ignored_and_produces_no_commands() {
    let event = runtime_event_from_worker(
        WorkerDomain::Media,
        ui_intent("runtime", "shutdown", json!({})),
    )
    .expect("event");

    assert_eq!(event, RuntimeEvent::Ignored);
    assert!(commands_for_event(&RuntimeState::default(), &event).is_empty());
}

#[test]
fn wrong_domain_media_snapshot_does_not_mutate_media_state() {
    let event = runtime_event_from_worker(
        WorkerDomain::Ui,
        event_envelope("media.snapshot", json!({"playback_state": "playing"})),
    )
    .expect("event");
    let mut state = RuntimeState::default();

    event.apply(&mut state);

    assert_eq!(event, RuntimeEvent::Ignored);
    assert_eq!(state.media.playback_state, "stopped");
}

#[test]
fn wrong_domain_voip_snapshot_does_not_route_media_pause() {
    let event = runtime_event_from_worker(
        WorkerDomain::Media,
        event_envelope("voip.snapshot", json!({"call_state": "incoming"})),
    )
    .expect("event");
    let mut state = RuntimeState::default();
    state.apply_media_snapshot(&json!({"playback_state": "playing"}));

    assert_eq!(event, RuntimeEvent::Ignored);
    assert!(commands_for_event(&state, &event).is_empty());
}

#[test]
fn runtime_shutdown_intent_decodes_to_shutdown_event() {
    let event = runtime_event_from_worker(
        WorkerDomain::Ui,
        ui_intent("runtime", "shutdown", json!({})),
    )
    .expect("event");

    assert_eq!(event, RuntimeEvent::Shutdown);
    assert_eq!(
        commands_for_event(&RuntimeState::default(), &event),
        vec![RuntimeCommand::Shutdown]
    );
}

#[test]
fn worker_exited_event_marks_worker_stopped() {
    let event = runtime_event_from_worker(
        WorkerDomain::Media,
        event_envelope("worker.exited", json!({"reason": "process_exited"})),
    )
    .expect("event");
    let mut state = RuntimeState::default();
    state.mark_worker(WorkerDomain::Media, WorkerState::Running, "ready");

    event.apply(&mut state);

    assert_eq!(state.media_worker.state, WorkerState::Stopped);
    assert_eq!(state.media_worker.last_reason, "process_exited");
}

#[test]
fn ui_play_pause_intent_routes_to_media_pause_when_playing() {
    let event = runtime_event_from_worker(
        WorkerDomain::Ui,
        ui_intent("music", "play_pause", json!({})),
    )
    .expect("event");
    let mut state = RuntimeState::default();
    state.apply_media_snapshot(&json!({"playback_state": "playing"}));

    let commands = commands_for_event(&state, &event);

    assert_eq!(
        commands,
        vec![worker_command(
            WorkerDomain::Media,
            "media.pause",
            json!({})
        )]
    );
}

#[test]
fn ui_play_pause_intent_routes_to_media_resume_when_paused() {
    let event = runtime_event_from_worker(
        WorkerDomain::Ui,
        ui_intent("music", "play_pause", json!({})),
    )
    .expect("event");
    let mut state = RuntimeState::default();
    state.apply_media_snapshot(&json!({"playback_state": "paused"}));

    let commands = commands_for_event(&state, &event);

    assert_eq!(
        commands,
        vec![worker_command(
            WorkerDomain::Media,
            "media.resume",
            json!({})
        )]
    );
}

#[test]
fn ui_play_pause_intent_routes_to_media_play_when_stopped() {
    let event = runtime_event_from_worker(
        WorkerDomain::Ui,
        ui_intent("music", "play_pause", json!({})),
    )
    .expect("event");
    let state = RuntimeState::default();

    let commands = commands_for_event(&state, &event);

    assert_eq!(
        commands,
        vec![worker_command(WorkerDomain::Media, "media.play", json!({}))]
    );
}

#[test]
fn ui_music_shuffle_all_intent_routes_to_media_shuffle_all() {
    let event = runtime_event_from_worker(
        WorkerDomain::Ui,
        ui_intent("music", "shuffle_all", json!({})),
    )
    .expect("event");

    let commands = commands_for_event(&RuntimeState::default(), &event);

    assert_eq!(
        commands,
        vec![worker_command(
            WorkerDomain::Media,
            "media.shuffle_all",
            json!({})
        )]
    );
}

#[test]
fn worker_command_routes_with_protocol_envelope() {
    let event = runtime_event_from_worker(
        WorkerDomain::Ui,
        ui_intent("music", "shuffle_all", json!({})),
    )
    .expect("event");

    let commands = commands_for_event(&RuntimeState::default(), &event);
    let [RuntimeCommand::WorkerCommand { domain, envelope }] = commands.as_slice() else {
        panic!("expected one worker command");
    };

    assert_eq!(*domain, WorkerDomain::Media);
    assert_eq!(envelope.kind, EnvelopeKind::Command);
    assert_eq!(envelope.message_type, "media.shuffle_all");
    assert_eq!(envelope.payload, json!({}));
}

#[test]
fn ui_music_load_playlist_intent_routes_id_to_media_path() {
    let event = runtime_event_from_worker(
        WorkerDomain::Ui,
        ui_intent(
            "music",
            "load_playlist",
            json!({"id": "/music/sleep.m3u", "title": "Sleep"}),
        ),
    )
    .expect("event");

    let commands = commands_for_event(&RuntimeState::default(), &event);

    assert_eq!(
        commands,
        vec![worker_command(
            WorkerDomain::Media,
            "media.load_playlist",
            json!({"path": "/music/sleep.m3u"})
        )]
    );
}

#[test]
fn ui_music_load_playlist_intent_falls_back_to_payload_path() {
    let event = runtime_event_from_worker(
        WorkerDomain::Ui,
        ui_intent(
            "music",
            "load_playlist",
            json!({"path": "/music/fallback.m3u"}),
        ),
    )
    .expect("event");

    let commands = commands_for_event(&RuntimeState::default(), &event);

    assert_eq!(
        commands,
        vec![worker_command(
            WorkerDomain::Media,
            "media.load_playlist",
            json!({"path": "/music/fallback.m3u"})
        )]
    );
}

#[test]
fn ui_music_play_recent_track_intent_routes_id_to_track_uri() {
    let event = runtime_event_from_worker(
        WorkerDomain::Ui,
        ui_intent(
            "music",
            "play_recent_track",
            json!({"id": "file:///music/song.mp3", "title": "Song"}),
        ),
    )
    .expect("event");

    let commands = commands_for_event(&RuntimeState::default(), &event);

    assert_eq!(
        commands,
        vec![worker_command(
            WorkerDomain::Media,
            "media.play_recent_track",
            json!({"track_uri": "file:///music/song.mp3"})
        )]
    );
}

#[test]
fn ui_music_play_recent_track_intent_falls_back_to_payload_track_uri() {
    let event = runtime_event_from_worker(
        WorkerDomain::Ui,
        ui_intent(
            "music",
            "play_recent_track",
            json!({"track_uri": "file:///music/fallback.mp3"}),
        ),
    )
    .expect("event");

    let commands = commands_for_event(&RuntimeState::default(), &event);

    assert_eq!(
        commands,
        vec![worker_command(
            WorkerDomain::Media,
            "media.play_recent_track",
            json!({"track_uri": "file:///music/fallback.mp3"})
        )]
    );
}

#[test]
fn ui_music_next_previous_intents_route_to_media_transport_commands() {
    let next = runtime_event_from_worker(WorkerDomain::Ui, ui_intent("music", "next", json!({})))
        .expect("event");
    let previous =
        runtime_event_from_worker(WorkerDomain::Ui, ui_intent("music", "previous", json!({})))
            .expect("event");
    let state = RuntimeState::default();

    assert_eq!(
        commands_for_event(&state, &next),
        vec![worker_command(
            WorkerDomain::Media,
            "media.next_track",
            json!({})
        )]
    );
    assert_eq!(
        commands_for_event(&state, &previous),
        vec![worker_command(
            WorkerDomain::Media,
            "media.previous_track",
            json!({})
        )]
    );
}

#[test]
fn ui_call_start_intent_routes_id_to_voip_dial_uri() {
    let event = runtime_event_from_worker(
        WorkerDomain::Ui,
        ui_intent(
            "call",
            "start",
            json!({"id": "sip:mama@example.test", "name": "Mama"}),
        ),
    )
    .expect("event");

    let commands = commands_for_event(&RuntimeState::default(), &event);

    assert_eq!(
        commands,
        vec![worker_command(
            WorkerDomain::Voip,
            "voip.dial",
            json!({"uri": "sip:mama@example.test"})
        )]
    );
}

#[test]
fn ui_call_start_intent_accepts_sip_address_fallback() {
    let event = runtime_event_from_worker(
        WorkerDomain::Ui,
        ui_intent(
            "call",
            "start",
            json!({"sip_address": "sip:dad@example.test", "name": "Dad"}),
        ),
    )
    .expect("event");

    let commands = commands_for_event(&RuntimeState::default(), &event);

    assert_eq!(
        commands,
        vec![worker_command(
            WorkerDomain::Voip,
            "voip.dial",
            json!({"uri": "sip:dad@example.test"})
        )]
    );
}

#[test]
fn ui_call_control_intents_route_to_voip_commands() {
    let answer =
        runtime_event_from_worker(WorkerDomain::Ui, ui_intent("call", "answer", json!({})))
            .expect("event");
    let reject =
        runtime_event_from_worker(WorkerDomain::Ui, ui_intent("call", "reject", json!({})))
            .expect("event");
    let hangup =
        runtime_event_from_worker(WorkerDomain::Ui, ui_intent("call", "hangup", json!({})))
            .expect("event");
    let state = RuntimeState::default();

    assert_eq!(
        commands_for_event(&state, &answer),
        vec![worker_command(WorkerDomain::Voip, "voip.answer", json!({}))]
    );
    assert_eq!(
        commands_for_event(&state, &reject),
        vec![worker_command(WorkerDomain::Voip, "voip.reject", json!({}))]
    );
    assert_eq!(
        commands_for_event(&state, &hangup),
        vec![worker_command(WorkerDomain::Voip, "voip.hangup", json!({}))]
    );
}

#[test]
fn ui_call_toggle_mute_routes_inverse_mute_state() {
    let event = runtime_event_from_worker(
        WorkerDomain::Ui,
        ui_intent("call", "toggle_mute", json!({})),
    )
    .expect("event");
    let mut state = RuntimeState::default();
    state.apply_voip_snapshot(&json!({"muted": true}));

    let commands = commands_for_event(&state, &event);

    assert_eq!(
        commands,
        vec![worker_command(
            WorkerDomain::Voip,
            "voip.set_mute",
            json!({"muted": false})
        )]
    );
}

#[test]
fn runtime_shutdown_intent_routes_to_shutdown_command() {
    let event = runtime_event_from_worker(
        WorkerDomain::Ui,
        ui_intent("runtime", "shutdown", json!({})),
    )
    .expect("event");

    let commands = commands_for_event(&RuntimeState::default(), &event);

    assert_eq!(commands, vec![RuntimeCommand::Shutdown]);
}

#[test]
fn hub_select_input_routes_to_voip_answer_when_call_is_incoming() {
    let event = runtime_event_from_worker(
        WorkerDomain::Ui,
        event_envelope(
            "ui.input",
            json!({
                "action": "select",
                "method": "button"
            }),
        ),
    )
    .expect("event");
    let mut state = RuntimeState::default();
    state.apply_voip_snapshot(&json!({"call_state": "incoming"}));

    let commands = commands_for_event(&state, &event);

    assert_eq!(
        commands,
        vec![worker_command(WorkerDomain::Voip, "voip.answer", json!({}))]
    );
}

#[test]
fn incoming_call_routes_media_pause_when_music_is_playing() {
    let event = runtime_event_from_worker(
        WorkerDomain::Voip,
        event_envelope(
            "voip.snapshot",
            json!({
                "call_state": "incoming"
            }),
        ),
    )
    .expect("event");
    let mut state = RuntimeState::default();
    state.apply_media_snapshot(&json!({"playback_state": "playing"}));

    let commands = commands_for_event(&state, &event);

    assert_eq!(
        commands,
        vec![worker_command(
            WorkerDomain::Media,
            "media.pause",
            json!({})
        )]
    );
}

#[test]
fn active_raw_voip_snapshot_routes_media_pause_when_music_is_playing() {
    let event = runtime_event_from_worker(
        WorkerDomain::Voip,
        event_envelope(
            "voip.snapshot",
            json!({
                "call_state": "streams_running"
            }),
        ),
    )
    .expect("event");
    let mut state = RuntimeState::default();
    state.apply_media_snapshot(&json!({"playback_state": "playing"}));

    let commands = commands_for_event(&state, &event);

    assert_eq!(
        commands,
        vec![worker_command(
            WorkerDomain::Media,
            "media.pause",
            json!({})
        )]
    );
}

#[test]
fn outgoing_raw_voip_snapshot_routes_media_pause_when_music_is_playing() {
    let event = runtime_event_from_worker(
        WorkerDomain::Voip,
        event_envelope(
            "voip.snapshot",
            json!({
                "call_state": "outgoing_init"
            }),
        ),
    )
    .expect("event");
    let mut state = RuntimeState::default();
    state.apply_media_snapshot(&json!({"playback_state": "playing"}));

    let commands = commands_for_event(&state, &event);

    assert_eq!(
        commands,
        vec![worker_command(
            WorkerDomain::Media,
            "media.pause",
            json!({})
        )]
    );
}

#[test]
fn idle_voip_snapshot_does_not_pause_music() {
    let event = runtime_event_from_worker(
        WorkerDomain::Voip,
        event_envelope(
            "voip.snapshot",
            json!({
                "call_state": "released"
            }),
        ),
    )
    .expect("event");
    let mut state = RuntimeState::default();
    state.apply_media_snapshot(&json!({"playback_state": "playing"}));

    assert_eq!(commands_for_event(&state, &event), Vec::new());
}

#[test]
fn voip_snapshot_event_apply_uses_runtime_state_normalization() {
    let event = runtime_event_from_worker(
        WorkerDomain::Voip,
        event_envelope(
            "voip.snapshot",
            json!({
                "call_state": "streams_running"
            }),
        ),
    )
    .expect("event");
    let mut state = RuntimeState::default();

    event.apply(&mut state);

    assert_eq!(state.call.state, CallState::Active);
}

fn event_envelope(message_type: &str, payload: Value) -> WorkerEnvelope {
    envelope(EnvelopeKind::Event, message_type, payload)
}

fn ui_intent(domain: &str, action: &str, payload: Value) -> WorkerEnvelope {
    event_envelope(
        "ui.intent",
        json!({
            "domain": domain,
            "action": action,
            "payload": payload,
        }),
    )
}

fn envelope(kind: EnvelopeKind, message_type: &str, payload: Value) -> WorkerEnvelope {
    WorkerEnvelope {
        schema_version: 1,
        kind,
        message_type: message_type.to_string(),
        request_id: None,
        timestamp_ms: 0,
        deadline_ms: 0,
        payload,
    }
}

fn worker_command(domain: WorkerDomain, message_type: &str, payload: Value) -> RuntimeCommand {
    RuntimeCommand::WorkerCommand {
        domain,
        envelope: WorkerEnvelope::command(message_type, None, payload),
    }
}
