use super::*;
use crate::runtime_loop::tests::FakeLoopIo;
use crate::state::RuntimeState;

fn fixture(transport: CallTransport) -> (RuntimeLoop, FakeLoopIo, SessionKey) {
    let mut state = RuntimeState::default();
    state.media.playback_state = "playing".into();
    state.media.position_ms = 12_345;
    state.call.gsm_available = true;
    RuntimeEvent::ContactsUpdated(json!({"contacts":[{"id":"dad", "name":"Dad",
        "sip_address":"sip:dad@example.test", "phone_number":"+49123456789", "can_call":true}]}))
    .apply(&mut state);
    let key = SessionKey {
        transport,
        generation: 1,
        call_id: "a".into(),
    };
    (RuntimeLoop::new(state), FakeLoopIo::default(), key)
}
fn offer(runtime: &mut RuntimeLoop, io: &mut FakeLoopIo, key: &SessionKey, now: u64) {
    let address = if key.transport == CallTransport::Sip {
        "sip:dad@example.test"
    } else {
        "+49123456789"
    };
    io.messages.push((
        domain_for(&key.transport),
        WorkerEnvelope::event("call.offer", json!({"key":key,"address":address})),
    ));
    runtime.run_once_at(io, now);
}
fn respond(runtime: &mut RuntimeLoop, io: &mut FakeLoopIo, name: &str, now: u64) {
    let (domain, command) = io
        .sent
        .iter()
        .rev()
        .find(|(_, e)| e.message_type == name)
        .expect(name)
        .clone();
    let mut payload = command.payload;
    payload["ok"] = json!(true);
    payload["audio_released"] = json!(true);
    payload["released"] = json!(true);
    payload["accepted"] = json!(true);
    payload["cancelled"] = json!(false);
    let result_name = if name == "voice.cancel" {
        "voice.cancelled"
    } else if domain == WorkerDomain::Network {
        "call.result"
    } else {
        name
    };
    io.messages.push((
        domain,
        WorkerEnvelope::result(result_name, command.request_id, payload),
    ));
    runtime.run_once_at(io, now);
}
fn prepare(runtime: &mut RuntimeLoop, io: &mut FakeLoopIo, now: u64) {
    for name in [
        "media.interrupt_for_call",
        "voip.interrupt_for_call",
        "media.set_alert_output",
        "voice.cancel",
    ] {
        respond(runtime, io, name, now);
    }
}

#[test]
fn failed_copy_retains_correlated_draft_ownership_without_audio_readiness() {
    let (mut runtime, mut io, key) = fixture(CallTransport::Sip);
    runtime.state.voice.pending_voice_recipient =
        Some(yoyopod_protocol::ui::VoiceRecipientAction {
            id: "dad".into(),
            recipient_address: "sip:dad@example.test".into(),
            ..Default::default()
        });
    offer(&mut runtime, &mut io, &key, 0);
    let (_, command) = io
        .sent
        .iter()
        .rev()
        .find(|(_, e)| e.message_type == "voip.interrupt_for_call")
        .unwrap()
        .clone();
    let mut payload = command.payload;
    payload["audio_released"] = json!(false);
    payload["draft_recovery_source"] = json!("finalized-source.wav");
    payload["draft_duration_ms"] = json!(420);
    io.messages.push((
        WorkerDomain::Voip,
        WorkerEnvelope::result("voip.interrupt_for_call", command.request_id, payload),
    ));
    runtime.run_once_at(&mut io, 1);
    assert_eq!(
        runtime.state.voice.interrupted_draft_path.as_deref(),
        Some("finalized-source.wav")
    );
    let draft = runtime.state.voice.interrupted_draft.as_ref().unwrap();
    assert!(draft.needs_copy);
    assert_eq!(draft.duration_ms, 420);
    assert!(!runtime.calls.resources.as_ref().unwrap().voip_prepared);
    assert!(!io
        .sent
        .iter()
        .any(|(_, e)| e.message_type == "call.action" && e.payload["action"] == "answer"));
}
fn control(
    runtime: &mut RuntimeLoop,
    io: &mut FakeLoopIo,
    key: &SessionKey,
    action: CallAction,
    now: u64,
) {
    io.messages.push((
        WorkerDomain::Ui,
        WorkerEnvelope::event(
            "ui.intent",
            UiIntent::Call(CallIntent::Session(CallCommand {
                key: key.clone(),
                action,
            }))
            .to_event_payload(),
        ),
    ));
    runtime.run_once_at(io, now);
}
fn terminal(runtime: &mut RuntimeLoop, io: &mut FakeLoopIo, key: &SessionKey, now: u64) {
    io.messages.push((
        domain_for(&key.transport),
        WorkerEnvelope::event(
            "call.update",
            json!(CallUpdate {
                key: key.clone(),
                direction: crate::call_manager::CallDirection::Incoming,
                phase: CallPhase::Ended,
                address: String::new(),
                duration_seconds: 0,
                muted: false,
                sequence: 9,
            }),
        ),
    ));
    runtime.run_once_at(io, now);
}
fn release(runtime: &mut RuntimeLoop, io: &mut FakeLoopIo, key: &SessionKey, now: u64) {
    if key.transport == CallTransport::Sip {
        io.messages.push((
            WorkerDomain::Voip,
            WorkerEnvelope::event("call.cleanup", json!({"key":key,"released":true})),
        ));
        runtime.run_once_at(io, now);
    }
    respond(runtime, io, "media.release_call", now);
    respond(runtime, io, "voip.release_call", now);
}
fn native_count(io: &FakeLoopIo, action: &str) -> usize {
    io.sent
        .iter()
        .filter(|(_, e)| e.message_type == "call.action" && e.payload["action"] == action)
        .count()
}

#[test]
fn readiness_and_matching_stop_precede_native_answer_for_both_transports() {
    for transport in [CallTransport::Sip, CallTransport::Gsm] {
        let (mut runtime, mut io, key) = fixture(transport);
        offer(&mut runtime, &mut io, &key, 100);
        assert_eq!(runtime.state().call.session.as_ref(), Some(&key));
        assert!(runtime.state().call.accept_enabled);
        assert!(io
            .sent
            .iter()
            .any(|(_, e)| e.message_type == "ui.set_backlight"));
        assert!(!io
            .sent
            .iter()
            .any(|(_, e)| e.message_type == "media.ringtone_start"));
        for name in [
            "media.interrupt_for_call",
            "voip.interrupt_for_call",
            "media.set_alert_output",
        ] {
            respond(&mut runtime, &mut io, name, 200);
        }
        assert!(!io
            .sent
            .iter()
            .any(|(_, e)| e.message_type == "media.ringtone_start"));
        respond(&mut runtime, &mut io, "voice.cancel", 200);
        let start = io
            .sent
            .iter()
            .find(|(_, e)| e.message_type == "media.ringtone_start")
            .unwrap()
            .1
            .clone();
        assert_eq!(start.payload["lease_ms"], 29_900);
        control(&mut runtime, &mut io, &key, CallAction::Answer, 300);
        assert_eq!(native_count(&io, "answer"), 0);
        assert_eq!(runtime.state().call.state, CallState::Incoming);
        assert!(!runtime.state().call.accept_enabled);
        respond(&mut runtime, &mut io, "media.ringtone_start", 310); // retired completion
        assert_eq!(native_count(&io, "answer"), 0);
        respond(&mut runtime, &mut io, "media.ringtone_stop", 320);
        assert_eq!(native_count(&io, "answer"), 1);
        control(&mut runtime, &mut io, &key, CallAction::Answer, 330);
        assert_eq!(native_count(&io, "answer"), 1);
        respond(&mut runtime, &mut io, "call.action", 340);
        assert_eq!(
            runtime.state().call.state,
            CallState::Incoming,
            "ack is not Active proof"
        );
        terminal(&mut runtime, &mut io, &key, 400);
        release(&mut runtime, &mut io, &key, 410);
        assert!(runtime.state().call.session.is_none());
        assert_eq!(runtime.state().media.playback_state, "paused");
        assert_eq!(runtime.state().media.position_ms, 12_345);
        assert!(!io
            .sent
            .iter()
            .any(|(_, e)| e.message_type == "media.resume"));
    }
}

#[test]
fn preparing_accept_is_queued_and_original_audio_epoch_is_preserved() {
    let (mut runtime, mut io, key) = fixture(CallTransport::Sip);
    runtime.state.voice.activity_generation = 44;
    offer(&mut runtime, &mut io, &key, 0);
    let interrupt = &io
        .sent
        .iter()
        .find(|(_, e)| e.message_type == "voip.interrupt_for_call")
        .unwrap()
        .1;
    assert_eq!(interrupt.payload["activity_generation"], 1);
    assert_eq!(interrupt.payload["voice_activity_generation"], 45);
    control(&mut runtime, &mut io, &key, CallAction::Answer, 1);
    assert!(!runtime.state().call.accept_enabled);
    assert_eq!(native_count(&io, "answer"), 0);
    prepare(&mut runtime, &mut io, 2);
    assert_eq!(native_count(&io, "answer"), 1);
    assert!(!io
        .sent
        .iter()
        .any(|(_, e)| e.message_type == "media.ringtone_start"));
}

#[test]
fn remote_end_during_preparation_retains_owner_until_physical_release() {
    for transport in [CallTransport::Sip, CallTransport::Gsm] {
        let (mut runtime, mut io, key) = fixture(transport);
        runtime.manager = crate::call_manager::CallManager::new(
            yoyopod_protocol::call::DeviceMode::Normal,
            8_000,
            1_000,
        );
        offer(&mut runtime, &mut io, &key, 0);
        terminal(&mut runtime, &mut io, &key, 1);
        assert!(runtime.state().call.session.is_some());
        prepare(&mut runtime, &mut io, 2);
        assert!(!io
            .sent
            .iter()
            .any(|(_, e)| e.message_type == "media.ringtone_start"));
        release(&mut runtime, &mut io, &key, 3);
        assert!(runtime.state().call.session.is_none());
        assert_eq!(runtime.state().media.position_ms, 12_345);
        assert_eq!(runtime.state().media.playback_state, "paused");
    }
}

#[test]
fn old_displayed_intent_cannot_act_on_next_owned_session() {
    let (mut runtime, mut io, key) = fixture(CallTransport::Sip);
    offer(&mut runtime, &mut io, &key, 0);
    terminal(&mut runtime, &mut io, &key, 1);
    prepare(&mut runtime, &mut io, 2);
    release(&mut runtime, &mut io, &key, 3);
    let next = SessionKey {
        call_id: "b".into(),
        ..key.clone()
    };
    offer(&mut runtime, &mut io, &next, 4);
    let before = io.sent.len();
    for action in [
        CallAction::Answer,
        CallAction::Hangup,
        CallAction::SetMute(true),
    ] {
        control(&mut runtime, &mut io, &key, action, 5);
    }
    assert_eq!(runtime.state().call.session.as_ref(), Some(&next));
    assert!(!io.sent[before..]
        .iter()
        .any(|(_, e)| e.message_type == "call.action"));
}

#[test]
fn secondary_failure_never_recovers_primary_or_frees_gsm_handoff() {
    let (mut runtime, mut io, key) = fixture(CallTransport::Gsm);
    runtime.request_outgoing(
        &mut io,
        ContactAction {
            id: "sip:dad@example.test".into(),
            method: CallMethod::Gsm,
            ..Default::default()
        },
    );
    prepare(&mut runtime, &mut io, 1);
    let primary = runtime.state().call.session.clone().unwrap();
    assert!(io.sent.iter().any(|(_, e)| e.message_type == "call.dial"));
    io.fail_send.push("call.action".into());
    offer(
        &mut runtime,
        &mut io,
        &SessionKey {
            call_id: "b".into(),
            ..key
        },
        2,
    );
    assert_eq!(runtime.state().call.session.as_ref(), Some(&primary));
    assert!(io.recovered.is_empty());
    assert!(!io
        .sent
        .iter()
        .any(|(_, e)| e.message_type.contains("resume")));
    assert_eq!(
        io.sent
            .iter()
            .filter(|(_, e)| e.message_type == "call.action")
            .count(),
        2
    );
}

#[test]
fn gsm_recovery_empty_replacement_cache_never_clears_uncertain_owner() {
    let (mut runtime, mut io, key) = fixture(CallTransport::Gsm);
    runtime.calls.startup.insert(
        WorkerDomain::Network,
        vec![WorkerEnvelope::command(
            "network.configure",
            None,
            json!({}),
        )],
    );
    runtime.calls.native_owner = Some("bus/owner".into());
    offer(&mut runtime, &mut io, &key, 0);
    prepare(&mut runtime, &mut io, 1);
    io.messages.push((
        WorkerDomain::Network,
        WorkerEnvelope::event("worker.exited", json!({"reason":"killed"})),
    ));
    runtime.run_once_at(&mut io, 2);
    assert_eq!(io.recovered, vec![WorkerDomain::Network]);
    assert!(io
        .sent
        .iter()
        .any(|(_, e)| e.message_type == "network.configure"
            && e.payload["recovery_quarantined"] == true
            && e.payload["worker_generation"] == 2));
    for owner in [Value::Null, json!("other/owner"), json!("bus/owner")] {
        io.messages.push((WorkerDomain::Network,WorkerEnvelope::event("call.reconciled",json!({
            "generation":2,"native_owner":owner,"native_calls_quiescent":true,"audio_released":true}))));
        runtime.run_once_at(&mut io, 3);
        assert_eq!(runtime.state().call.session.as_ref(), Some(&key));
    }
    terminal(&mut runtime, &mut io, &key, 4); // stale old-generation Ended
    assert_eq!(runtime.state().call.session.as_ref(), Some(&key));
}

#[test]
fn audio_failure_recovers_responsible_domain_without_releasing_native_owner() {
    for domain in [WorkerDomain::Media, WorkerDomain::Voip, WorkerDomain::Voice] {
        let (mut runtime, mut io, key) = fixture(CallTransport::Gsm);
        offer(&mut runtime, &mut io, &key, 0);
        io.messages.push((
            domain,
            WorkerEnvelope::event("worker.exited", json!({"reason":"killed"})),
        ));
        runtime.run_once_at(&mut io, 1);
        assert_eq!(io.recovered, vec![domain]);
        assert_eq!(runtime.state().call.session.as_ref(), Some(&key));
        assert_eq!(native_count(&io, "hangup"), 1);
        assert!(!io
            .sent
            .iter()
            .any(|(_, e)| e.message_type == "media.start" || e.message_type == "media.resume"));
    }
}

#[test]
fn local_dispatch_failure_and_ack_timeout_keep_barrier_and_recover_audio() {
    let (mut runtime, mut io, key) = fixture(CallTransport::Gsm);
    io.fail_send.push("media.interrupt_for_call".into());
    offer(&mut runtime, &mut io, &key, 0);
    assert!(io.recovered.contains(&WorkerDomain::Media));
    assert_eq!(runtime.state().call.session.as_ref(), Some(&key));
    let (mut runtime, mut io, key) = fixture(CallTransport::Gsm);
    offer(&mut runtime, &mut io, &key, 0);
    runtime.run_once_at(&mut io, 8_000);
    assert!(io.recovered.contains(&WorkerDomain::Media));
    assert_eq!(runtime.state().call.session.as_ref(), Some(&key));
}

#[test]
fn shutdown_and_decision_timeout_never_resume_music() {
    for shutdown in [false, true] {
        let (mut runtime, mut io, key) = fixture(CallTransport::Sip);
        offer(&mut runtime, &mut io, &key, 0);
        prepare(&mut runtime, &mut io, 1);
        respond(&mut runtime, &mut io, "media.ringtone_start", 2);
        if shutdown {
            runtime.begin_shutdown(&mut io, 3);
        } else {
            runtime.run_once_at(&mut io, 30_000);
        }
        assert_eq!(runtime.state().call.session_phase, Some(CallPhase::Ending));
        assert!(runtime.state().call.session.is_some());
        let now = if shutdown { 4 } else { 30_001 };
        respond(&mut runtime, &mut io, "media.ringtone_stop", now);
        terminal(&mut runtime, &mut io, &key, now + 1);
        release(&mut runtime, &mut io, &key, now + 2);
        assert!(runtime.state().call.session.is_none());
        assert_eq!(runtime.state().media.playback_state, "paused");
        assert_eq!(runtime.state().media.position_ms, 12_345);
    }
}

#[test]
fn outgoing_permissions_and_audio_commands_are_enforced_at_dispatch() {
    let (mut runtime, mut io, key) = fixture(CallTransport::Sip);
    offer(&mut runtime, &mut io, &key, 0);
    let before = io.sent.len();
    for name in [
        "media.resume",
        "voip.start_voice_note_recording",
        "voip.dial",
    ] {
        runtime.dispatch_command(
            &mut io,
            RuntimeCommand::WorkerCommand {
                domain: WorkerDomain::Voip,
                envelope: WorkerEnvelope::command(
                    name,
                    None,
                    json!({"voice_activity_generation":runtime.state.voice.activity_generation}),
                ),
            },
        );
    }
    assert_eq!(io.sent.len(), before);
    assert_eq!(runtime.state().call.session.as_ref(), Some(&key));
}

#[test]
fn configured_modes_and_paused_or_stopped_music_survive_all_cleanup() {
    use crate::call_manager::DeviceMode;
    for mode in [DeviceMode::Silent, DeviceMode::DoNotDisturb] {
        let (mut runtime, mut io, key) = fixture(CallTransport::Sip);
        runtime.state.settings.device_mode = mode.clone();
        runtime = RuntimeLoop::new(runtime.state);
        offer(&mut runtime, &mut io, &key, 0);
        if mode == DeviceMode::DoNotDisturb {
            assert!(runtime.state().call.session.is_none());
            assert!(!io.sent.iter().any(|(_, e)| matches!(
                e.message_type.as_str(),
                "ui.set_backlight" | "media.interrupt_for_call" | "voice.cancel"
            )));
        } else {
            prepare(&mut runtime, &mut io, 1);
            assert!(runtime.state().call.session.is_some());
            assert!(!io
                .sent
                .iter()
                .any(|(_, e)| e.message_type == "media.ringtone_start"));
        }
    }
    for playback in ["paused", "stopped"] {
        let (mut runtime, mut io, key) = fixture(CallTransport::Gsm);
        runtime.state.media.playback_state = playback.into();
        offer(&mut runtime, &mut io, &key, 0);
        terminal(&mut runtime, &mut io, &key, 1);
        prepare(&mut runtime, &mut io, 2);
        release(&mut runtime, &mut io, &key, 3);
        assert_eq!(runtime.state().media.playback_state, playback);
        assert_eq!(runtime.state().media.position_ms, 12_345);
    }
}

#[test]
fn matching_stop_failure_recovers_media_before_cleanup_and_retired_reply_is_ignored() {
    let (mut runtime, mut io, key) = fixture(CallTransport::Gsm);
    offer(&mut runtime, &mut io, &key, 0);
    prepare(&mut runtime, &mut io, 1);
    respond(&mut runtime, &mut io, "media.ringtone_start", 2);
    control(&mut runtime, &mut io, &key, CallAction::Answer, 3);
    let stop = io
        .sent
        .iter()
        .rev()
        .find(|(_, e)| e.message_type == "media.ringtone_stop")
        .unwrap()
        .1
        .clone();
    io.messages.push((
        WorkerDomain::Media,
        WorkerEnvelope::error(
            "media.error",
            stop.request_id.clone(),
            "command_failed",
            "release failed",
        ),
    ));
    runtime.run_once_at(&mut io, 4);
    assert_eq!(io.recovered, vec![WorkerDomain::Media]);
    assert_eq!(native_count(&io, "answer"), 0);
    assert_eq!(runtime.state().call.session.as_ref(), Some(&key));
    io.messages.push((
        WorkerDomain::Media,
        WorkerEnvelope::result(
            "media.ringtone_stop",
            stop.request_id,
            json!({"key":key,"operation_generation":1,"ok":true}),
        ),
    ));
    runtime.run_once_at(&mut io, 5);
    assert_eq!(native_count(&io, "answer"), 0);
    terminal(&mut runtime, &mut io, &key, 6);
    respond(&mut runtime, &mut io, "media.interrupt_for_call", 7);
    respond(&mut runtime, &mut io, "media.set_alert_output", 8);
    release(&mut runtime, &mut io, &key, 9);
    assert!(runtime.state().call.session.is_none());
}

#[test]
fn failed_release_retries_only_unreleased_audio_resource() {
    let (mut runtime, mut io, key) = fixture(CallTransport::Gsm);
    offer(&mut runtime, &mut io, &key, 0);
    terminal(&mut runtime, &mut io, &key, 1);
    prepare(&mut runtime, &mut io, 2);
    respond(&mut runtime, &mut io, "media.release_call", 3);
    let command = io
        .sent
        .iter()
        .rev()
        .find(|(_, e)| e.message_type == "voip.release_call")
        .unwrap()
        .1
        .clone();
    io.messages.push((
        WorkerDomain::Voip,
        WorkerEnvelope::error("voip.error", command.request_id, "command_failed", "failed"),
    ));
    runtime.run_once_at(&mut io, 4);
    assert_eq!(io.recovered, vec![WorkerDomain::Voip]);
    respond(&mut runtime, &mut io, "voip.interrupt_for_call", 5);
    assert_eq!(
        io.sent
            .iter()
            .filter(|(_, e)| e.message_type == "media.release_call")
            .count(),
        1
    );
    respond(&mut runtime, &mut io, "voip.release_call", 6);
    assert!(runtime.state().call.session.is_none());
}

#[test]
fn runtime_outgoing_rechecks_permission_address_and_reserves_before_dial() {
    let (mut runtime, mut io, _) = fixture(CallTransport::Sip);
    let mut action = ContactAction {
        id: "unknown".into(),
        uri: "sip:dad@example.test".into(),
        ..Default::default()
    };
    runtime.request_outgoing(&mut io, action.clone());
    assert!(runtime.manager.session().is_none());
    action.id = "sip:dad@example.test".into();
    runtime.state.call.contacts[0].can_call = false;
    runtime.request_outgoing(&mut io, action.clone());
    assert!(runtime.manager.session().is_none());
    runtime.state.call.contacts[0].can_call = true;
    action.uri = "sip:attacker@example.test".into();
    runtime.request_outgoing(&mut io, action);
    let key = runtime.manager.session().cloned().unwrap();
    assert!(!io.sent.iter().any(|(_, e)| e.message_type == "call.dial"));
    prepare(&mut runtime, &mut io, 1);
    assert!(io.sent.iter().any(|(_, e)| e.message_type == "call.dial"
        && e.payload["key"] == json!(key)
        && e.payload["address"] == "sip:dad@example.test"));
}

#[test]
fn stale_stamped_audio_and_remote_resume_are_blocked_during_ownership() {
    let (mut runtime, mut io, key) = fixture(CallTransport::Sip);
    let stale = RuntimeCommand::WorkerCommand {
        domain: WorkerDomain::Media,
        envelope: WorkerEnvelope::command(
            "media.resume",
            None,
            json!({"voice_activity_generation":0}),
        ),
    };
    offer(&mut runtime, &mut io, &key, 0);
    io.messages.push((
        WorkerDomain::Cloud,
        WorkerEnvelope::event(
            "cloud.command",
            json!({"command":{"command":"resume","command_id":"remote-play"}}),
        ),
    ));
    runtime.run_once_at(&mut io, 1);
    assert!(io.sent.iter().any(|(_, e)| e.message_type == "cloud.ack"
        && e.payload["command_id"] == "remote-play"
        && e.payload["ok"] == false));
    terminal(&mut runtime, &mut io, &key, 2);
    prepare(&mut runtime, &mut io, 3);
    release(&mut runtime, &mut io, &key, 4);
    let before = io.sent.len();
    runtime.dispatch_command(&mut io, stale);
    assert_eq!(
        io.sent.len(),
        before,
        "a delayed old start cannot be restamped after call release"
    );
}

#[test]
fn persisted_native_dispatch_quarantines_both_transports_on_runtime_restart() {
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("native.json");
    let (mut runtime, mut io, _) = fixture(CallTransport::Gsm);
    runtime.state.native_call_guard_file = path.clone();
    runtime = RuntimeLoop::new(runtime.state);
    runtime.request_outgoing(
        &mut io,
        ContactAction {
            id: "sip:dad@example.test".into(),
            method: CallMethod::Gsm,
            ..Default::default()
        },
    );
    prepare(&mut runtime, &mut io, 1);
    assert!(path.exists(), "durable marker precedes native dial");
    assert!(io.sent.iter().any(|(_, e)| e.message_type == "call.dial"));
    let mut restarted = RuntimeLoop::new(runtime.state.clone());
    let mut replacement = FakeLoopIo::default();
    restarted.calls.startup.insert(
        WorkerDomain::Network,
        vec![WorkerEnvelope::command(
            "network.configure",
            None,
            json!({}),
        )],
    );
    restarted.configure_call_worker(&mut replacement, WorkerDomain::Network);
    assert!(replacement
        .sent
        .iter()
        .any(|(_, e)| e.message_type == "network.configure"
            && e.payload["recovery_quarantined"] == true));
    for transport in [CallTransport::Sip, CallTransport::Gsm] {
        let key = SessionKey {
            transport,
            generation: 1,
            call_id: "new".into(),
        };
        offer(&mut restarted, &mut replacement, &key, 2);
        assert!(restarted.manager.session().is_none());
    }
    assert!(!replacement.sent.iter().any(|(_, e)| matches!(
        e.message_type.as_str(),
        "media.interrupt_for_call" | "ui.set_backlight" | "call.dial"
    )));
    assert!(path.exists());
}

#[test]
fn dirty_marker_write_failure_prevents_the_actual_native_envelope() {
    let directory = tempfile::tempdir().unwrap();
    let blocker = directory.path().join("blocker");
    std::fs::write(&blocker, "file").unwrap();
    let (mut runtime, mut io, _) = fixture(CallTransport::Gsm);
    // Initially clean path; make the parent unwritable only after load.
    let path = directory.path().join("future/native.json");
    runtime.state.native_call_guard_file = path;
    runtime = RuntimeLoop::new(runtime.state);
    std::fs::write(directory.path().join("future"), "file").unwrap();
    runtime.request_outgoing(
        &mut io,
        ContactAction {
            id: "sip:dad@example.test".into(),
            method: CallMethod::Gsm,
            ..Default::default()
        },
    );
    prepare(&mut runtime, &mut io, 1);
    assert!(!io
        .sent
        .iter()
        .any(|(_, e)| e.message_type == "call.dial" || e.message_type == "call.action"));
    assert!(runtime.calls.native_guard.quarantined());
}

#[test]
fn latest_route_ack_controls_initial_alert_and_return_normal_lease() {
    let (mut runtime, mut io, key) = fixture(CallTransport::Sip);
    offer(&mut runtime, &mut io, &key, 0);
    let old = io
        .sent
        .iter()
        .find(|(_, e)| e.message_type == "media.set_alert_output")
        .unwrap()
        .1
        .clone();
    runtime.intercept_call_event(
        &mut io,
        &RuntimeEvent::AudioRouteLocal(json!({"media_device":"alsa/latest","alert_volume":37})),
    );
    for name in [
        "media.interrupt_for_call",
        "voip.interrupt_for_call",
        "voice.cancel",
    ] {
        respond(&mut runtime, &mut io, name, 1);
    }
    io.messages.push((
        WorkerDomain::Media,
        WorkerEnvelope::result("media.set_alert_output", old.request_id, json!({"ok":true})),
    ));
    runtime.run_once_at(&mut io, 2);
    assert!(!io
        .sent
        .iter()
        .any(|(_, e)| e.message_type == "media.ringtone_start"));
    respond(&mut runtime, &mut io, "media.set_alert_output", 3);
    respond(&mut runtime, &mut io, "media.ringtone_start", 4);
    runtime.handle_call(
        &mut io,
        CallManagerEvent::SetMode(crate::call_manager::DeviceMode::Silent),
    );
    respond(&mut runtime, &mut io, "media.ringtone_stop", 5);
    runtime.now_ms = 20_000;
    runtime.intercept_call_event(
        &mut io,
        &RuntimeEvent::AudioRouteLocal(json!({"media_device":"alsa/new","alert_volume":21})),
    );
    runtime.handle_call(
        &mut io,
        CallManagerEvent::SetMode(crate::call_manager::DeviceMode::Normal),
    );
    assert_eq!(
        io.sent
            .iter()
            .filter(|(_, e)| e.message_type == "media.ringtone_start")
            .count(),
        1
    );
    respond(&mut runtime, &mut io, "media.set_alert_output", 20_001);
    let start = &io
        .sent
        .iter()
        .rev()
        .find(|(_, e)| e.message_type == "media.ringtone_start")
        .unwrap()
        .1;
    assert_eq!(start.payload["lease_ms"], 9_999);
    assert_eq!(start.payload["operation_generation"], 2);
}

#[test]
fn queued_empty_scan_cannot_confirm_new_outgoing_cleanup() {
    let (mut runtime, mut io, _) = fixture(CallTransport::Gsm);
    runtime.calls.native_owner = Some("bus/owner".into());
    runtime.request_outgoing(
        &mut io,
        ContactAction {
            id: "sip:dad@example.test".into(),
            method: CallMethod::Gsm,
            ..Default::default()
        },
    );
    let key = runtime.manager.session().cloned().unwrap();
    prepare(&mut runtime, &mut io, 1);
    io.messages.push((WorkerDomain::Network,WorkerEnvelope::event("call.reconciled",json!({
        "generation":1,"native_owner":"bus/owner","native_calls_quiescent":true,"audio_released":true}))));
    runtime.run_once_at(&mut io, 2);
    control(&mut runtime, &mut io, &key, CallAction::Hangup, 3);
    respond(&mut runtime, &mut io, "call.action", 4);
    assert_eq!(runtime.manager.session(), Some(&key));
    assert!(!io
        .sent
        .iter()
        .any(|(_, e)| e.message_type == "media.release_call"));
}

#[test]
fn emergency_power_shutdown_does_not_wait_for_failed_native_cleanup() {
    let (mut runtime, mut io, key) = fixture(CallTransport::Gsm);
    offer(&mut runtime, &mut io, &key, 0);
    prepare(&mut runtime, &mut io, 1);
    io.fail_send.push("call.action".into());
    io.fail_send.push("media.ringtone_stop".into());
    runtime.state.power.safety.shutdown_pending = true;
    runtime.state.power.safety.shutdown_execute_at_seconds = 0;
    runtime.run_once_at(&mut io, 2);
    assert!(runtime.shutdown_requested());
    assert_eq!(runtime.manager.phase(), Some(CallPhase::Ending));
    assert_eq!(
        io.system_shutdowns.len(),
        1,
        "power deadline must dispatch shutdown in this loop"
    );
    assert!(
        io.recovered.is_empty(),
        "emergency shutdown must not wait for worker reconstruction"
    );
    assert_eq!(
        runtime.manager.session(),
        Some(&key),
        "failed cleanup never fabricates release"
    );
}

#[test]
fn already_due_power_preempts_worker_reconstruction() {
    let (mut runtime, mut io, key) = fixture(CallTransport::Sip);
    offer(&mut runtime, &mut io, &key, 0);
    io.messages.push((
        WorkerDomain::Voip,
        WorkerEnvelope::event("worker.exited", json!({"code":1})),
    ));
    runtime.state.power.safety.shutdown_pending = true;
    runtime.state.power.safety.shutdown_execute_at_seconds = 0;
    runtime.run_once_at(&mut io, 2);
    assert_eq!(io.system_shutdowns.len(), 1);
    assert!(
        io.recovered.is_empty(),
        "due power must precede worker recovery"
    );
}

#[test]
fn power_deadline_preempts_pending_recovery_without_resource_proof() {
    let (mut runtime, mut io, key) = fixture(CallTransport::Sip);
    offer(&mut runtime, &mut io, &key, 0);
    prepare(&mut runtime, &mut io, 1);
    io.recovery_pending = true;
    io.messages.push((
        WorkerDomain::Voip,
        WorkerEnvelope::event("worker.exited", json!({"code":1})),
    ));
    runtime.run_once_at(&mut io, 2);
    assert_eq!(io.recovered, vec![WorkerDomain::Voip]);
    assert_eq!(runtime.calls.generations[&WorkerDomain::Voip], 1);
    assert!(!runtime.calls.resources.as_ref().unwrap().native_released);
    let polls = io.recovery_polls;
    let sent = io.sent.len();
    runtime.state.power.safety.shutdown_pending = true;
    runtime.state.power.safety.shutdown_execute_at_seconds = 0;
    // A queued completion during shutdown must not reconstruct/configure/release.
    io.recovery_pending = false;
    runtime.run_once_at(&mut io, 3);
    assert_eq!(io.system_shutdowns.len(), 1);
    assert_eq!(io.recovery_polls, polls);
    assert_eq!(runtime.calls.generations[&WorkerDomain::Voip], 1);
    assert_eq!(runtime.manager.session(), Some(&key));
    assert!(!io.sent[sent..].iter().any(|(_, e)| matches!(
        e.message_type.as_str(),
        "voip.configure" | "voip.release_call" | "media.release_call"
    )));
}

#[test]
fn overdue_decoded_accept_never_answers_before_tick() {
    let mut late_answers = vec![];
    for transport in [CallTransport::Sip, CallTransport::Gsm] {
        for now in [30_000, 30_001] {
            for silent in [false, true] {
                let (mut runtime, mut io, key) = fixture(transport.clone());
                if silent {
                    runtime.state.settings.device_mode = yoyopod_protocol::call::DeviceMode::Silent;
                    runtime = RuntimeLoop::new(runtime.state);
                }
                offer(&mut runtime, &mut io, &key, 0);
                prepare(&mut runtime, &mut io, 1);
                if !silent {
                    respond(&mut runtime, &mut io, "media.ringtone_start", 2);
                }
                control(&mut runtime, &mut io, &key, CallAction::Answer, now);
                if !silent {
                    respond(&mut runtime, &mut io, "media.ringtone_stop", now);
                }
                if native_count(&io, "answer") != 0
                    || runtime.manager.phase() != Some(CallPhase::Ending)
                {
                    late_answers.push(format!("{transport:?} silent={silent} now={now}"));
                }
                assert_eq!(runtime.manager.session(), Some(&key));
            }
        }
    }
    assert!(
        late_answers.is_empty(),
        "late native answers: {late_answers:?}"
    );
}

#[test]
fn overdue_decoded_stop_cannot_complete_answer_operation() {
    let mut late_answers = vec![];
    for transport in [CallTransport::Sip, CallTransport::Gsm] {
        for now in [8_100, 8_101] {
            let (mut runtime, mut io, key) = fixture(transport.clone());
            offer(&mut runtime, &mut io, &key, 0);
            prepare(&mut runtime, &mut io, 1);
            respond(&mut runtime, &mut io, "media.ringtone_start", 2);
            control(&mut runtime, &mut io, &key, CallAction::Answer, 100);
            respond(&mut runtime, &mut io, "media.ringtone_stop", now);
            if native_count(&io, "answer") != 0
                || runtime.manager.phase() != Some(CallPhase::Ending)
            {
                late_answers.push(format!("{transport:?} now={now}"));
            }
            assert_eq!(runtime.manager.phase(), Some(CallPhase::Ending));
            assert_eq!(runtime.manager.session(), Some(&key));
        }
    }
    assert!(
        late_answers.is_empty(),
        "late native answers: {late_answers:?}"
    );
}

#[test]
fn queued_preparing_overdue_readiness_retains_cleanup_owner() {
    for transport in [CallTransport::Sip, CallTransport::Gsm] {
        for now in [8_000, 8_001, 30_000, 30_001] {
            let (mut runtime, mut io, key) = fixture(transport.clone());
            runtime.state.settings.device_mode = yoyopod_protocol::call::DeviceMode::Silent;
            runtime = RuntimeLoop::new(runtime.state);
            offer(&mut runtime, &mut io, &key, 0);
            control(&mut runtime, &mut io, &key, CallAction::Answer, 1);
            for name in [
                "media.interrupt_for_call",
                "voip.interrupt_for_call",
                "media.set_alert_output",
            ] {
                respond(&mut runtime, &mut io, name, 2);
            }
            respond(&mut runtime, &mut io, "voice.cancel", now);
            assert_eq!(native_count(&io, "answer"), 0, "{transport:?} now={now}");
            assert_eq!(runtime.manager.phase(), Some(CallPhase::Ending));
            assert_eq!(runtime.manager.session(), Some(&key));
            terminal(&mut runtime, &mut io, &key, now + 1);
            release(&mut runtime, &mut io, &key, now + 2);
            assert!(
                runtime.manager.session().is_none(),
                "late genuine proof must remain usable"
            );
        }
    }
}

#[test]
fn early_decision_stop_may_complete_after_original_decision_boundary() {
    for transport in [CallTransport::Sip, CallTransport::Gsm] {
        let (mut runtime, mut io, key) = fixture(transport);
        runtime.manager = crate::call_manager::CallManager::new(
            yoyopod_protocol::call::DeviceMode::Normal,
            8_000,
            1_000,
        );
        offer(&mut runtime, &mut io, &key, 0);
        prepare(&mut runtime, &mut io, 1);
        respond(&mut runtime, &mut io, "media.ringtone_start", 2);
        control(&mut runtime, &mut io, &key, CallAction::Answer, 999);
        assert_eq!(runtime.manager.phase(), Some(CallPhase::Answering));
        respond(&mut runtime, &mut io, "media.ringtone_stop", 1_001);
        assert_eq!(native_count(&io, "answer"), 1);
        assert_eq!(runtime.manager.phase(), Some(CallPhase::Answering));
    }
}

#[test]
fn decoded_offer_policy_matrix_preserves_rejected_activity() {
    use yoyopod_protocol::call::DeviceMode;
    for transport in [CallTransport::Sip, CallTransport::Gsm] {
        for mode in [
            DeviceMode::Normal,
            DeviceMode::Silent,
            DeviceMode::DoNotDisturb,
        ] {
            for priority in [false, true] {
                for can_call in [false, true] {
                    for identity in ["saved", "unknown", "withheld", "ambiguous"] {
                        for activity in [
                            "playing",
                            "paused",
                            "stopped",
                            "recording",
                            "assistant",
                            "voice_playback",
                        ] {
                            let (mut runtime, mut io, key) = fixture(transport.clone());
                            runtime.state.settings.device_mode = mode.clone();
                            runtime.state.media.playback_state =
                                if matches!(activity, "playing" | "paused" | "stopped") {
                                    activity.into()
                                } else {
                                    "stopped".into()
                                };
                            runtime.state.voice.phase = match activity {
                                "recording" => "recording",
                                "assistant" => "thinking",
                                _ => "idle",
                            }
                            .into();
                            runtime.state.voice.ask_capture_active = activity == "assistant";
                            runtime.state.voice.playback_active = activity == "voice_playback";
                            let previous_voice = runtime.state.voice.clone();
                            let previous_media = runtime.state.media.playback_state.clone();
                            let mut contact = json!({"id":"dad", "name":"Dad", "sip_address":"sip:dad@example.test", "phone_number":"+49123456789", "priority":priority, "can_call":can_call});
                            let mut contacts = vec![contact.clone()];
                            if identity == "ambiguous" {
                                contact["id"] = json!("duplicate");
                                contacts.push(contact);
                            }
                            RuntimeEvent::ContactsUpdated(json!({"contacts":contacts}))
                                .apply(&mut runtime.state);
                            runtime = RuntimeLoop::new(runtime.state);
                            let address = match identity {
                                "withheld" => "",
                                "unknown" => "stranger",
                                _ if transport == CallTransport::Sip => "sip:dad@example.test",
                                _ => "+49123456789",
                            };
                            io.messages.push((
                                domain_for(&transport),
                                WorkerEnvelope::event(
                                    "call.offer",
                                    json!({"key":key,"address":address}),
                                ),
                            ));
                            runtime.run_once_at(&mut io, 0);
                            let admitted = identity == "saved"
                                && (mode != DeviceMode::DoNotDisturb || priority);
                            assert_eq!(runtime.state().call.session.as_ref() == Some(&key), admitted, "{transport:?} {mode:?} priority={priority} permission={can_call} {identity} {activity}");
                            if admitted {
                                assert!(runtime.state().call.accept_enabled);
                                prepare(&mut runtime, &mut io, 1);
                                assert_eq!(
                                    io.sent
                                        .iter()
                                        .any(|(_, e)| e.message_type == "media.ringtone_start"),
                                    mode == DeviceMode::Normal
                                );
                                assert!(io
                                    .sent
                                    .iter()
                                    .any(|(_, e)| e.message_type == "voice.cancel"));
                                assert!(io
                                    .sent
                                    .iter()
                                    .any(|(_, e)| e.message_type == "voip.interrupt_for_call"));
                            } else {
                                assert_eq!(runtime.state().media.playback_state, previous_media);
                                assert_eq!(runtime.state().voice, previous_voice);
                                assert!(!io.sent.iter().any(|(_, e)| matches!(
                                    e.message_type.as_str(),
                                    "ui.set_backlight"
                                        | "media.interrupt_for_call"
                                        | "voip.interrupt_for_call"
                                        | "voice.cancel"
                                        | "media.ringtone_start"
                                )));
                                assert_eq!(native_count(&io, "answer"), 0);
                                assert!(io
                                    .sent
                                    .iter()
                                    .any(|(_, e)| e.message_type == "call.action"
                                        && e.payload["key"] == json!(key)));
                            }
                        }
                    }
                }
            }
        }
    }
}

#[test]
fn decoded_second_offer_and_remote_end_during_answer_preserve_primary() {
    for transport in [CallTransport::Sip, CallTransport::Gsm] {
        for second in [CallTransport::Sip, CallTransport::Gsm] {
            let (mut runtime, mut io, key) = fixture(transport.clone());
            offer(&mut runtime, &mut io, &key, 0);
            prepare(&mut runtime, &mut io, 1);
            respond(&mut runtime, &mut io, "media.ringtone_start", 2);
            control(&mut runtime, &mut io, &key, CallAction::Answer, 3);
            let secondary = SessionKey {
                transport: second,
                generation: 1,
                call_id: "b".into(),
            };
            offer(&mut runtime, &mut io, &secondary, 4);
            assert_eq!(runtime.manager.session(), Some(&key));
            assert!(io.sent.iter().any(|(_, e)| e.message_type == "call.action"
                && e.payload["key"] == json!(secondary)
                && e.payload["action"]
                    == json!(CallAction::Reject(
                        yoyopod_protocol::call::RejectReason::Busy
                    ))));
            terminal(&mut runtime, &mut io, &key, 5);
            respond(&mut runtime, &mut io, "media.ringtone_stop", 6);
            assert_eq!(native_count(&io, "answer"), 0);
            assert_eq!(runtime.manager.session(), Some(&key));
            release(&mut runtime, &mut io, &key, 7);
            assert!(runtime.manager.session().is_none());
        }
    }
}

#[test]
fn overdue_accept_and_final_readiness_batch_cannot_gain_new_window() {
    for transport in [CallTransport::Sip, CallTransport::Gsm] {
        for now in [30_000, 30_001] {
            for accept_first in [false, true] {
                let (mut runtime, mut io, key) = fixture(transport.clone());
                offer(&mut runtime, &mut io, &key, 0);
                for name in [
                    "media.interrupt_for_call",
                    "voip.interrupt_for_call",
                    "media.set_alert_output",
                ] {
                    respond(&mut runtime, &mut io, name, 1);
                }
                let (domain, command) = io
                    .sent
                    .iter()
                    .rev()
                    .find(|(_, e)| e.message_type == "voice.cancel")
                    .unwrap()
                    .clone();
                let mut payload = command.payload;
                payload["cancelled"] = json!(true);
                let readiness = (
                    domain,
                    WorkerEnvelope::result("voice.cancelled", command.request_id, payload),
                );
                let accept = (
                    WorkerDomain::Ui,
                    WorkerEnvelope::event(
                        "ui.intent",
                        UiIntent::Call(CallIntent::Session(CallCommand {
                            key: key.clone(),
                            action: CallAction::Answer,
                        }))
                        .to_event_payload(),
                    ),
                );
                if accept_first {
                    io.messages.extend([accept, readiness]);
                } else {
                    io.messages.extend([readiness, accept]);
                }
                runtime.run_once_at(&mut io, now);
                assert_eq!(native_count(&io, "answer"), 0);
                assert_eq!(runtime.manager.phase(), Some(CallPhase::Ending));
                assert_eq!(runtime.manager.session(), Some(&key));
            }
        }
    }
}

#[test]
fn original_decision_deadline_survives_mode_and_route_restart() {
    for transport in [CallTransport::Sip, CallTransport::Gsm] {
        for now in [30_000, 30_001] {
            let (mut runtime, mut io, key) = fixture(transport.clone());
            offer(&mut runtime, &mut io, &key, 0);
            prepare(&mut runtime, &mut io, 1);
            respond(&mut runtime, &mut io, "media.ringtone_start", 2);
            runtime.state.settings.device_mode = yoyopod_protocol::call::DeviceMode::Silent;
            runtime.handle_call(
                &mut io,
                CallManagerEvent::SetMode(yoyopod_protocol::call::DeviceMode::Silent),
            );
            respond(&mut runtime, &mut io, "media.ringtone_stop", 3);
            runtime.now_ms = 20_000;
            runtime.intercept_call_event(
                &mut io,
                &RuntimeEvent::AudioRouteLocal(
                    json!({"media_device":"alsa/latest","alert_volume":37}),
                ),
            );
            runtime.state.settings.device_mode = yoyopod_protocol::call::DeviceMode::Normal;
            runtime.handle_call(
                &mut io,
                CallManagerEvent::SetMode(yoyopod_protocol::call::DeviceMode::Normal),
            );
            respond(&mut runtime, &mut io, "media.set_alert_output", 20_001);
            let start = io
                .sent
                .iter()
                .rev()
                .find(|(_, e)| e.message_type == "media.ringtone_start")
                .unwrap();
            assert_eq!(start.1.payload["lease_ms"], 9_999);
            respond(&mut runtime, &mut io, "media.ringtone_start", 20_002);
            control(&mut runtime, &mut io, &key, CallAction::Answer, now);
            respond(&mut runtime, &mut io, "media.ringtone_stop", now);
            assert_eq!(native_count(&io, "answer"), 0);
            assert_eq!(runtime.manager.session(), Some(&key));
        }
    }
}

#[test]
fn early_queued_decision_may_finish_preparation_after_decision_window() {
    for transport in [CallTransport::Sip, CallTransport::Gsm] {
        let (mut runtime, mut io, key) = fixture(transport);
        runtime.manager = crate::call_manager::CallManager::new(
            yoyopod_protocol::call::DeviceMode::Silent,
            8_000,
            1_000,
        );
        runtime.state.settings.device_mode = yoyopod_protocol::call::DeviceMode::Silent;
        offer(&mut runtime, &mut io, &key, 0);
        control(&mut runtime, &mut io, &key, CallAction::Answer, 999);
        prepare(&mut runtime, &mut io, 1_001);
        assert_eq!(native_count(&io, "answer"), 1);
        assert_eq!(runtime.manager.phase(), Some(CallPhase::Answering));
    }
}
