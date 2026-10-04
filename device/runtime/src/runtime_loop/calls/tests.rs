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
