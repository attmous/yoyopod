use super::*;
fn key(id: &str) -> SessionKey {
    SessionKey {
        transport: CallTransport::Sip,
        generation: 1,
        call_id: format!(
            "runtime-outgoing-{}",
            id.bytes().fold(0u64, |n, byte| n * 128 + u64::from(byte))
        ),
    }
}

#[test]
fn sustained_retirement_keeps_bounded_state_and_replayed_keys_dead() {
    let mut manager = CallManager::new(DeviceMode::Normal, 8_000, 30_000);
    for serial in 1..=10_000 {
        let key = SessionKey {
            transport: CallTransport::Sip,
            generation: 1,
            call_id: format!("sip-incoming-{serial}"),
        };
        manager.handle(
            CallManagerEvent::Offer(CallOffer {
                key: key.clone(),
                address: "unknown".into(),
            }),
            &context(false),
            serial,
        );
        manager.handle(
            CallManagerEvent::Update(CallUpdate {
                key: key.clone(),
                direction: CallDirection::Incoming,
                phase: CallPhase::Ended,
                address: "unknown".into(),
                duration_seconds: 0,
                muted: false,
                sequence: 1,
            }),
            &context(false),
            serial,
        );
        assert!(
            manager.terminal.len() <= 1 && manager.sequences.len() <= 1,
            "retired identity memory grew"
        );
        assert!(manager
            .handle(
                CallManagerEvent::Offer(CallOffer {
                    key: key.clone(),
                    address: "sip:dad@example.test".into()
                }),
                &context(false),
                serial
            )
            .is_empty());
        assert!(manager
            .handle(
                CallManagerEvent::UserAction(CallCommand {
                    key,
                    action: CallAction::Answer
                }),
                &context(false),
                serial
            )
            .is_empty());
        assert!(manager.session().is_none());
    }
}
fn context(priority: bool) -> CallContext {
    CallContext {
        shutdown: false,
        contacts: vec![ContactIdentity {
            contact_id: "dad".into(),
            name: "Dad".into(),
            sip_address: "sip:dad@example.test".into(),
            phone_number: "+49123456789".into(),
            priority,
        }],
    }
}
fn offer(id: &str) -> CallManagerEvent {
    CallManagerEvent::Offer(CallOffer {
        key: key(id),
        address: "sip:dad@example.test".into(),
    })
}
#[test]
fn unknown_offer_has_only_targeted_rejection() {
    let mut manager = CallManager::new(DeviceMode::Normal, 8_000, 30_000);
    let effects = manager.handle(
        CallManagerEvent::Offer(CallOffer {
            key: key("a"),
            address: "sip:stranger@example.test".into(),
        }),
        &context(false),
        0,
    );
    assert_eq!(
        effects,
        vec![CallEffect::Transport(CallCommand {
            key: key("a"),
            action: CallAction::Reject(RejectReason::Unapproved)
        })]
    );
    assert!(manager.session().is_none());
}
#[test]
fn dnd_priority_offer_wakes_without_ringtone() {
    let mut manager = CallManager::new(DeviceMode::DoNotDisturb, 8_000, 30_000);
    let mut effects = manager.handle(offer("a"), &context(true), 0);
    effects.extend(manager.handle(
        CallManagerEvent::AudioPrepared {
            key: key("a"),
            ok: true,
        },
        &context(true),
        10,
    ));
    assert!(effects.contains(&CallEffect::WakeDisplay(key("a"))));
    assert!(!effects
        .iter()
        .any(|e| matches!(e, CallEffect::StartRingtone(_))));
    assert_eq!(manager.phase(), Some(CallPhase::Ringing));
}
fn prepared(mode: DeviceMode) -> CallManager {
    let mut m = CallManager::new(mode, 8_000, 30_000);
    m.handle(offer("a"), &context(true), 0);
    m.handle(
        CallManagerEvent::AudioPrepared {
            key: key("a"),
            ok: true,
        },
        &context(true),
        1,
    );
    m
}
fn action(m: &mut CallManager, action: CallAction) -> Vec<CallEffect> {
    m.handle(
        CallManagerEvent::UserAction(CallCommand {
            key: key("a"),
            action,
        }),
        &context(true),
        2,
    )
}
fn update(phase: CallPhase, sequence: u64) -> CallManagerEvent {
    CallManagerEvent::Update(CallUpdate {
        key: key("a"),
        direction: CallDirection::Incoming,
        phase,
        address: "sip:dad@example.test".into(),
        duration_seconds: 0,
        muted: false,
        sequence,
    })
}
macro_rules! mode_test {
    ($name:ident,$mode:expr,$priority:expr,$admitted:expr,$audible:expr) => {
        #[test]
        fn $name() {
            let mut m = CallManager::new($mode, 8_000, 30_000);
            let e = m.handle(offer("a"), &context($priority), 0);
            assert_eq!(m.session().is_some(), $admitted);
            if $admitted {
                m.handle(
                    CallManagerEvent::AudioPrepared {
                        key: key("a"),
                        ok: true,
                    },
                    &context($priority),
                    1,
                );
                assert_eq!(m.alert_audible(), $audible);
            } else {
                assert_eq!(e.len(), 1);
            }
        }
    };
}
mode_test!(normal_ordinary, DeviceMode::Normal, false, true, true);
mode_test!(normal_priority, DeviceMode::Normal, true, true, true);
mode_test!(silent_ordinary, DeviceMode::Silent, false, true, false);
mode_test!(silent_priority, DeviceMode::Silent, true, true, false);
mode_test!(dnd_ordinary, DeviceMode::DoNotDisturb, false, false, false);
mode_test!(dnd_priority, DeviceMode::DoNotDisturb, true, true, false);
#[test]
fn answer_queued_during_preparation() {
    let mut m = CallManager::new(DeviceMode::Silent, 8_000, 30_000);
    m.handle(offer("a"), &context(false), 0);
    assert!(action(&mut m, CallAction::Answer).is_empty());
    let e = m.handle(
        CallManagerEvent::AudioPrepared {
            key: key("a"),
            ok: true,
        },
        &context(false),
        3,
    );
    assert!(e.contains(&CallEffect::Transport(CallCommand {
        key: key("a"),
        action: CallAction::Answer
    })));
    assert_eq!(m.phase(), Some(CallPhase::Answering));
}
#[test]
fn answer_waits_for_ringtone_release() {
    let mut m = prepared(DeviceMode::Normal);
    let e = action(&mut m, CallAction::Answer);
    assert!(!e.iter().any(|e| matches!(e, CallEffect::Transport(_))));
    let e = m.handle(
        CallManagerEvent::RingtoneStopped {
            key: key("a"),
            ok: true,
        },
        &context(true),
        3,
    );
    assert!(e.contains(&CallEffect::Transport(CallCommand {
        key: key("a"),
        action: CallAction::Answer
    })));
    assert!(m
        .handle(
            CallManagerEvent::RingtoneStopped {
                key: key("a"),
                ok: true
            },
            &context(true),
            4
        )
        .is_empty());
}
#[test]
fn duplicate_cancel() {
    let mut m = prepared(DeviceMode::Silent);
    assert!(!action(&mut m, CallAction::Reject(RejectReason::Cancelled)).is_empty());
    assert!(action(&mut m, CallAction::Reject(RejectReason::Cancelled)).is_empty());
    assert_eq!(m.session(), Some(&key("a")));
}
#[test]
fn remote_ended_before_answer_ack() {
    let mut m = prepared(DeviceMode::Silent);
    action(&mut m, CallAction::Answer);
    m.handle(update(CallPhase::Ended, 1), &context(true), 3);
    m.handle(
        CallManagerEvent::CommandFinished {
            key: key("a"),
            request_id: "answer".into(),
            ok: true,
        },
        &context(true),
        4,
    );
    assert_eq!(m.phase(), Some(CallPhase::Ending));
    m.handle(update(CallPhase::Active, 2), &context(true), 5);
    assert_eq!(m.phase(), Some(CallPhase::Ending));
}
#[test]
fn rejected_withheld_cannot_be_reoffered() {
    let mut m = CallManager::new(DeviceMode::Normal, 8_000, 30_000);
    m.handle(
        CallManagerEvent::Offer(CallOffer {
            key: key("a"),
            address: "".into(),
        }),
        &context(true),
        0,
    );
    assert!(m.handle(offer("a"), &context(true), 1).is_empty());
    assert!(m
        .handle(update(CallPhase::Active, 1), &context(true), 2)
        .is_empty());
    assert!(m.session().is_none());
}
#[test]
fn stale_generation_and_sequence() {
    let mut m = prepared(DeviceMode::Silent);
    action(&mut m, CallAction::Answer);
    m.handle(update(CallPhase::Active, 2), &context(true), 3);
    assert!(m
        .handle(update(CallPhase::Ended, 1), &context(true), 4)
        .is_empty());
    let mut stale = key("old");
    stale.generation = 0;
    assert!(m
        .handle(
            CallManagerEvent::Offer(CallOffer {
                key: stale,
                address: "sip:dad@example.test".into()
            }),
            &context(true),
            5
        )
        .is_empty());
    assert_eq!(m.phase(), Some(CallPhase::Active));
}
#[test]
fn ring_timeout() {
    let mut m = prepared(DeviceMode::Silent);
    m.handle(CallManagerEvent::Tick, &context(true), 30_000);
    assert_eq!(m.phase(), Some(CallPhase::Ending));
    assert_eq!(m.session(), Some(&key("a")));
}
#[test]
fn eight_second_operation_timeout() {
    let mut m = CallManager::new(DeviceMode::Normal, 8_000, 30_000);
    m.handle(offer("a"), &context(true), 0);
    assert!(m
        .handle(CallManagerEvent::Tick, &context(true), 7999)
        .is_empty());
    m.handle(CallManagerEvent::Tick, &context(true), 8000);
    assert_eq!(m.phase(), Some(CallPhase::Ending));
    let e = m.handle(CallManagerEvent::Tick, &context(true), 16000);
    assert!(e
        .iter()
        .any(|e| matches!(e, CallEffect::RecoverTransport { .. })));
    assert!(m.session().is_some());
}
fn in_phase(phase: CallPhase) -> CallManager {
    let mut m = CallManager::new(DeviceMode::Silent, 8_000, 30_000);
    m.handle(offer("a"), &context(true), 0);
    if phase != CallPhase::Preparing {
        m.handle(
            CallManagerEvent::AudioPrepared {
                key: key("a"),
                ok: true,
            },
            &context(true),
            1,
        );
    }
    if matches!(phase, CallPhase::Answering | CallPhase::Active) {
        action(&mut m, CallAction::Answer);
    }
    if phase == CallPhase::Active {
        m.handle(update(CallPhase::Active, 1), &context(true), 3);
    }
    if phase == CallPhase::Ending {
        action(&mut m, CallAction::Hangup);
    }
    if phase == CallPhase::Outgoing {
        m = CallManager::new(DeviceMode::Silent, 8_000, 30_000);
        m.handle(
            CallManagerEvent::RequestOutgoing {
                key: key("a"),
                contact_id: "dad".into(),
                address: "sip:dad@example.test".into(),
            },
            &context(true),
            0,
        );
        m.handle(
            CallManagerEvent::AudioPrepared {
                key: key("a"),
                ok: true,
            },
            &context(true),
            1,
        );
    }
    m
}
#[test]
fn cross_transport_second_offers_in_every_owned_phase() {
    for phase in [
        CallPhase::Preparing,
        CallPhase::Ringing,
        CallPhase::Answering,
        CallPhase::Outgoing,
        CallPhase::Active,
        CallPhase::Ending,
    ] {
        let mut m = in_phase(phase);
        let mut other = key("b");
        other.transport = CallTransport::Gsm;
        let e = m.handle(
            CallManagerEvent::Offer(CallOffer {
                key: other.clone(),
                address: "+49123456789".into(),
            }),
            &context(true),
            4,
        );
        assert_eq!(
            e,
            vec![CallEffect::Transport(CallCommand {
                key: other,
                action: CallAction::Reject(RejectReason::Busy)
            })]
        );
        assert_eq!(m.session(), Some(&key("a")));
    }
}
#[test]
fn mode_change_in_each_phase() {
    for phase in [
        CallPhase::Preparing,
        CallPhase::Ringing,
        CallPhase::Answering,
        CallPhase::Outgoing,
        CallPhase::Active,
        CallPhase::Ending,
    ] {
        let mut m = in_phase(phase.clone());
        m.handle(
            CallManagerEvent::SetMode(DeviceMode::DoNotDisturb),
            &context(false),
            4,
        );
        assert_eq!(m.phase(), Some(phase));
        assert_eq!(m.session(), Some(&key("a")));
        assert!(!m.alert_audible());
    }
}
#[test]
fn shutdown_retains_ownership_until_cleanup() {
    let mut m = prepared(DeviceMode::Silent);
    m.handle(CallManagerEvent::Shutdown, &context(true), 3);
    assert_eq!(m.phase(), Some(CallPhase::Ending));
    m.handle(
        CallManagerEvent::CleanupConfirmed(key("a")),
        &context(true),
        4,
    );
    assert!(m.session().is_none());
    let e = m.handle(offer("b"), &context(true), 5);
    assert_eq!(e.len(), 1);
    assert!(m.session().is_none());
}
#[test]
fn worker_exit_keeps_cleanup_barrier() {
    let mut m = prepared(DeviceMode::Silent);
    m.handle(
        CallManagerEvent::WorkerExited {
            transport: CallTransport::Sip,
            generation: 1,
        },
        &context(true),
        3,
    );
    assert_eq!(m.phase(), Some(CallPhase::Ending));
    assert_eq!(m.session(), Some(&key("a")));
}
#[test]
fn outgoing_reserves_before_dial() {
    let mut m = CallManager::new(DeviceMode::Normal, 8_000, 30_000);
    let e = m.handle(
        CallManagerEvent::RequestOutgoing {
            key: key("a"),
            contact_id: "dad".into(),
            address: "sip:dad@example.test".into(),
        },
        &context(true),
        0,
    );
    assert_eq!(m.phase(), Some(CallPhase::Preparing));
    assert!(!e.iter().any(|e| matches!(e, CallEffect::Dial { .. })));
    let e = m.handle(
        CallManagerEvent::AudioPrepared {
            key: key("a"),
            ok: true,
        },
        &context(true),
        1,
    );
    assert!(e.iter().any(|e| matches!(e, CallEffect::Dial { .. })));
    m.handle(
        CallManagerEvent::CommandFinished {
            key: key("a"),
            request_id: "dial".into(),
            ok: true,
        },
        &context(true),
        2,
    );
    assert_eq!(m.phase(), Some(CallPhase::Outgoing));
}
#[test]
fn phone_formatting_only_equivalence() {
    let c = context(false);
    assert!(
        identity::match_contact(CallTransport::Gsm, "+49 (123) 456-789", &c.contacts).is_some()
    );
    for value in ["123456789", "0049123456789", "+123456789", "", "withheld"] {
        assert!(identity::match_contact(CallTransport::Gsm, value, &c.contacts).is_none());
    }
}
#[test]
fn sip_host_case_normalized_user_case_retained() {
    let c = context(false);
    assert!(
        identity::match_contact(CallTransport::Sip, "sip:dad@EXAMPLE.TEST", &c.contacts).is_some()
    );
    assert!(
        identity::match_contact(CallTransport::Sip, "sip:Dad@example.test", &c.contacts).is_none()
    );
}
#[test]
fn explicit_sip_and_sips_handling() {
    let mut c = context(false);
    assert!(identity::match_contact(CallTransport::Sip, "dad@example.test", &c.contacts).is_none());
    assert!(
        identity::match_contact(CallTransport::Sip, "sips:dad@example.test", &c.contacts).is_none()
    );
    c.contacts[0].sip_address = "sips:dad@example.test".into();
    assert!(
        identity::match_contact(CallTransport::Sip, "sips:dad@example.test", &c.contacts).is_some()
    );
}
#[test]
fn malformed_empty_identities() {
    let c = context(false);
    for value in [
        "",
        "sip:@example.test",
        "sip:dad@",
        "sip:dad@@example.test",
        "sip:dad@example.test;foo=1",
        "sip:dad@exa mple.test",
    ] {
        assert!(identity::match_contact(CallTransport::Sip, value, &c.contacts).is_none());
    }
}
#[test]
fn duplicate_address_rejects_as_ambiguous() {
    let mut c = context(false);
    let mut duplicate = c.contacts[0].clone();
    duplicate.contact_id = "other".into();
    c.contacts.push(duplicate);
    assert!(
        identity::match_contact(CallTransport::Sip, "sip:dad@example.test", &c.contacts).is_none()
    );
    assert!(identity::match_contact(CallTransport::Gsm, "+49123456789", &c.contacts).is_none());
}
#[test]
fn mode_toggle_waits_for_stop_before_restart_or_answer() {
    let mut m = prepared(DeviceMode::Normal);
    m.handle(
        CallManagerEvent::SetMode(DeviceMode::Silent),
        &context(true),
        2,
    );
    let e = m.handle(
        CallManagerEvent::SetMode(DeviceMode::Normal),
        &context(true),
        3,
    );
    assert!(!e.iter().any(|e| matches!(e, CallEffect::StartRingtone(_))));
    assert!(!action(&mut m, CallAction::Answer)
        .iter()
        .any(|e| matches!(e, CallEffect::Transport(_))));
    let e = m.handle(
        CallManagerEvent::RingtoneStopped {
            key: key("a"),
            ok: true,
        },
        &context(true),
        4,
    );
    assert!(e.iter().any(|e| matches!(e, CallEffect::Transport(_))));
    assert!(!e.iter().any(|e| matches!(e, CallEffect::StartRingtone(_))));
}
#[test]
fn cleanup_waits_for_ringtone_stop() {
    let mut m = prepared(DeviceMode::Normal);
    action(&mut m, CallAction::Hangup);
    assert!(m
        .handle(
            CallManagerEvent::CleanupConfirmed(key("a")),
            &context(true),
            3
        )
        .is_empty());
    m.handle(
        CallManagerEvent::RingtoneStopped {
            key: key("a"),
            ok: true,
        },
        &context(true),
        4,
    );
    m.handle(
        CallManagerEvent::CleanupConfirmed(key("a")),
        &context(true),
        5,
    );
    assert!(m.session().is_none());
}
#[test]
fn ringtone_operation_timeout_ends_without_releasing_owner() {
    let mut m = prepared(DeviceMode::Normal);
    m.handle(CallManagerEvent::Tick, &context(true), 8001);
    assert_eq!(m.phase(), Some(CallPhase::Ending));
    assert!(m.session().is_some());
}
#[test]
fn generation_advance_retires_old_tombstones() {
    let mut m = CallManager::new(DeviceMode::Normal, 8_000, 30_000);
    m.handle(
        CallManagerEvent::Offer(CallOffer {
            key: key("a"),
            address: "".into(),
        }),
        &context(true),
        0,
    );
    let mut next = key("b");
    next.generation = 2;
    m.handle(
        CallManagerEvent::Offer(CallOffer {
            key: next,
            address: "".into(),
        }),
        &context(true),
        1,
    );
    assert!(m.terminal.iter().all(|k| k.generation == 2));
    assert!(m.handle(offer("a"), &context(true), 2).is_empty());
}
#[test]
fn native_active_before_ack_stays_active() {
    let mut m = prepared(DeviceMode::Silent);
    action(&mut m, CallAction::Answer);
    m.handle(update(CallPhase::Active, 1), &context(true), 3);
    assert!(m
        .handle(
            CallManagerEvent::CommandFinished {
                key: key("a"),
                request_id: "answer".into(),
                ok: false
            },
            &context(true),
            4
        )
        .is_empty());
    assert_eq!(m.phase(), Some(CallPhase::Active));
}
#[test]
fn successful_hangup_ack_does_not_release_cleanup() {
    let mut m = prepared(DeviceMode::Silent);
    action(&mut m, CallAction::Hangup);
    m.handle(
        CallManagerEvent::CommandFinished {
            key: key("a"),
            request_id: "hangup".into(),
            ok: true,
        },
        &context(true),
        3,
    );
    assert_eq!(m.phase(), Some(CallPhase::Ending));
    assert!(m.session().is_some());
}
#[test]
fn ringtone_failures_retain_cleanup_owner() {
    let mut m = prepared(DeviceMode::Normal);
    m.handle(
        CallManagerEvent::RingtoneStarted {
            key: key("a"),
            ok: false,
        },
        &context(true),
        3,
    );
    assert_eq!(m.phase(), Some(CallPhase::Ending));
    assert!(m.session().is_some());
    m.handle(
        CallManagerEvent::RingtoneStopped {
            key: key("a"),
            ok: false,
        },
        &context(true),
        4,
    );
    assert_eq!(m.phase(), Some(CallPhase::Ending));
    assert!(m.session().is_some());
}
#[test]
fn stop_completion_retires_late_start_result() {
    let mut m = prepared(DeviceMode::Normal);
    action(&mut m, CallAction::Answer);
    m.handle(
        CallManagerEvent::RingtoneStopped {
            key: key("a"),
            ok: true,
        },
        &context(true),
        3,
    );
    assert!(m
        .handle(
            CallManagerEvent::RingtoneStarted {
                key: key("a"),
                ok: false
            },
            &context(true),
            4
        )
        .is_empty());
    assert_eq!(m.phase(), Some(CallPhase::Answering));
}
fn ordinary_preparing() -> CallManager {
    let mut m = CallManager::new(DeviceMode::Normal, 8_000, 30_000);
    m.handle(offer("a"), &context(false), 0);
    m
}
fn busy(key: SessionKey) -> CallEffect {
    CallEffect::Transport(CallCommand {
        key,
        action: CallAction::Reject(RejectReason::Busy),
    })
}
#[test]
fn dnd_ordinary_preparing_terminates_busy() {
    let mut m = ordinary_preparing();
    let e = m.handle(
        CallManagerEvent::SetMode(DeviceMode::DoNotDisturb),
        &context(false),
        1,
    );
    assert_eq!(e, vec![busy(key("a")), CallEffect::Publish]);
    assert_eq!(m.phase(), Some(CallPhase::Ending));
    assert_eq!(m.session(), Some(&key("a")));
}
#[test]
fn dnd_ordinary_ringing_terminates_busy() {
    let mut m = ordinary_preparing();
    m.handle(
        CallManagerEvent::AudioPrepared {
            key: key("a"),
            ok: true,
        },
        &context(false),
        1,
    );
    let e = m.handle(
        CallManagerEvent::SetMode(DeviceMode::DoNotDisturb),
        &context(false),
        2,
    );
    assert_eq!(
        e,
        vec![
            CallEffect::StopRingtone(RingtoneRequest {
                key: key("a"),
                operation_generation: 0,
                lease_ms: 0,
            }),
            busy(key("a")),
            CallEffect::Publish
        ]
    );
    assert_eq!(m.phase(), Some(CallPhase::Ending));
}
#[test]
fn dnd_cancels_queued_answer_before_preparation_finishes() {
    let mut m = ordinary_preparing();
    action(&mut m, CallAction::Answer);
    m.handle(
        CallManagerEvent::SetMode(DeviceMode::DoNotDisturb),
        &context(false),
        3,
    );
    assert!(m
        .handle(
            CallManagerEvent::AudioPrepared {
                key: key("a"),
                ok: true
            },
            &context(false),
            4
        )
        .is_empty());
    assert_eq!(m.phase(), Some(CallPhase::Ending));
}
#[test]
fn dnd_cancels_answer_waiting_for_ringtone_release() {
    let mut m = ordinary_preparing();
    m.handle(
        CallManagerEvent::AudioPrepared {
            key: key("a"),
            ok: true,
        },
        &context(false),
        1,
    );
    action(&mut m, CallAction::Answer);
    let e = m.handle(
        CallManagerEvent::SetMode(DeviceMode::DoNotDisturb),
        &context(false),
        3,
    );
    assert_eq!(e, vec![busy(key("a")), CallEffect::Publish]);
    assert!(m
        .handle(
            CallManagerEvent::RingtoneStopped {
                key: key("a"),
                ok: true
            },
            &context(false),
            4
        )
        .is_empty());
    assert_eq!(m.phase(), Some(CallPhase::Ending));
}
#[test]
fn dnd_keeps_already_dispatched_ordinary_answer() {
    let mut m = CallManager::new(DeviceMode::Silent, 8_000, 30_000);
    m.handle(offer("a"), &context(false), 0);
    m.handle(
        CallManagerEvent::AudioPrepared {
            key: key("a"),
            ok: true,
        },
        &context(false),
        1,
    );
    action(&mut m, CallAction::Answer);
    assert_eq!(
        m.handle(
            CallManagerEvent::SetMode(DeviceMode::DoNotDisturb),
            &context(false),
            3
        ),
        vec![CallEffect::Publish]
    );
    assert_eq!(m.phase(), Some(CallPhase::Answering));
}
#[test]
fn dnd_uses_admitted_priority_despite_directory_edits() {
    let mut ordinary = ordinary_preparing();
    ordinary.handle(
        CallManagerEvent::SetMode(DeviceMode::DoNotDisturb),
        &context(true),
        1,
    );
    assert_eq!(ordinary.phase(), Some(CallPhase::Ending));
    let mut priority = CallManager::new(DeviceMode::Normal, 8_000, 30_000);
    priority.handle(offer("a"), &context(true), 0);
    priority.handle(
        CallManagerEvent::SetMode(DeviceMode::DoNotDisturb),
        &context(false),
        1,
    );
    assert_eq!(priority.phase(), Some(CallPhase::Preparing));
}
#[test]
fn known_dnd_offer_has_only_busy_rejection() {
    let mut m = CallManager::new(DeviceMode::DoNotDisturb, 8_000, 30_000);
    assert_eq!(
        m.handle(offer("a"), &context(false), 0),
        vec![busy(key("a"))]
    );
    assert!(m.session().is_none());
}
#[test]
fn known_shutdown_offer_has_only_busy_rejection() {
    let mut m = CallManager::new(DeviceMode::Normal, 8_000, 30_000);
    let mut c = context(false);
    c.shutdown = true;
    assert_eq!(m.handle(offer("a"), &c, 0), vec![busy(key("a"))]);
    m.handle(CallManagerEvent::Shutdown, &context(false), 1);
    assert_eq!(
        m.handle(offer("b"), &context(false), 2),
        vec![busy(key("b"))]
    );
}
#[test]
fn known_second_ordinary_dnd_offer_has_only_busy_rejection() {
    let mut m = CallManager::new(DeviceMode::DoNotDisturb, 8_000, 30_000);
    m.handle(offer("a"), &context(true), 0);
    assert_eq!(
        m.handle(offer("b"), &context(false), 1),
        vec![busy(key("b"))]
    );
    assert_eq!(m.session(), Some(&key("a")));
}
#[test]
fn unknown_shutdown_offer_still_has_only_unapproved_rejection() {
    let mut m = CallManager::new(DeviceMode::DoNotDisturb, 8_000, 30_000);
    let mut c = context(false);
    c.shutdown = true;
    let e = m.handle(
        CallManagerEvent::Offer(CallOffer {
            key: key("a"),
            address: "sip:stranger@example.test".into(),
        }),
        &c,
        0,
    );
    assert_eq!(
        e,
        vec![CallEffect::Transport(CallCommand {
            key: key("a"),
            action: CallAction::Reject(RejectReason::Unapproved)
        })]
    );
}
#[test]
fn canonical_national_numbers_match_without_country_guessing() {
    let mut c = context(false);
    c.contacts[0].phone_number = "0123456".into();
    assert!(identity::match_contact(CallTransport::Gsm, "(012) 34-56", &c.contacts).is_some());
    for value in ["123456", "+49123456", "0049123456"] {
        assert!(identity::match_contact(CallTransport::Gsm, value, &c.contacts).is_none());
    }
    c.contacts[0].phone_number = "123".into();
    assert!(identity::match_contact(CallTransport::Gsm, "123", &c.contacts).is_some());
}
#[test]
fn malformed_phone_numbers_are_not_identities() {
    let mut c = context(false);
    for value in ["", "+", "() - .", "++123", "12+34", "12x34"] {
        c.contacts[0].phone_number = value.into();
        assert!(identity::match_contact(CallTransport::Gsm, value, &c.contacts).is_none());
    }
}
#[test]
fn admitted_identity_is_stable_snapshot() {
    let mut m = ordinary_preparing();
    let original = m.admitted_identity().unwrap().clone();
    let mut edited = context(true);
    edited.contacts[0].name = "Changed".into();
    edited.contacts[0].sip_address = "sip:other@example.test".into();
    m.handle(CallManagerEvent::SetMode(DeviceMode::Silent), &edited, 1);
    assert_eq!(m.admitted_identity(), Some(&original));
}
#[test]
fn dnd_preserves_active_ordinary_and_outgoing() {
    let mut active = CallManager::new(DeviceMode::Silent, 8_000, 30_000);
    active.handle(offer("a"), &context(false), 0);
    active.handle(
        CallManagerEvent::AudioPrepared {
            key: key("a"),
            ok: true,
        },
        &context(false),
        1,
    );
    action(&mut active, CallAction::Answer);
    active.handle(update(CallPhase::Active, 1), &context(false), 3);
    assert_eq!(
        active.handle(
            CallManagerEvent::SetMode(DeviceMode::DoNotDisturb),
            &context(false),
            4
        ),
        vec![CallEffect::Publish]
    );
    assert_eq!(active.phase(), Some(CallPhase::Active));
    let mut outgoing = CallManager::new(DeviceMode::Normal, 8_000, 30_000);
    outgoing.handle(
        CallManagerEvent::RequestOutgoing {
            key: key("a"),
            contact_id: "dad".into(),
            address: "sip:dad@example.test".into(),
        },
        &context(false),
        0,
    );
    assert_eq!(
        outgoing.handle(
            CallManagerEvent::SetMode(DeviceMode::DoNotDisturb),
            &context(false),
            1
        ),
        vec![CallEffect::Publish]
    );
    assert_eq!(outgoing.phase(), Some(CallPhase::Preparing));
}
#[test]
fn silent_stops_and_normal_restarts_pending_ordinary_alert() {
    let mut m = ordinary_preparing();
    m.handle(
        CallManagerEvent::AudioPrepared {
            key: key("a"),
            ok: true,
        },
        &context(false),
        1,
    );
    let e = m.handle(
        CallManagerEvent::SetMode(DeviceMode::Silent),
        &context(false),
        2,
    );
    assert_eq!(
        e,
        vec![
            CallEffect::StopRingtone(RingtoneRequest {
                key: key("a"),
                operation_generation: 0,
                lease_ms: 0,
            }),
            CallEffect::Publish
        ]
    );
    m.handle(
        CallManagerEvent::RingtoneStopped {
            key: key("a"),
            ok: true,
        },
        &context(false),
        3,
    );
    let e = m.handle(
        CallManagerEvent::SetMode(DeviceMode::Normal),
        &context(false),
        4,
    );
    assert_eq!(
        e,
        vec![
            CallEffect::StartRingtone(RingtoneRequest {
                key: key("a"),
                operation_generation: 0,
                lease_ms: 0,
            }),
            CallEffect::Publish
        ]
    );
    assert_eq!(m.phase(), Some(CallPhase::Ringing));
}
