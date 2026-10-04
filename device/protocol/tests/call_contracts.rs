use yoyopod_protocol::call::*;
use yoyopod_protocol::ui::{ListItemSnapshot, SettingsIntent, UiIntent};
#[test]
fn old_contact_has_no_priority_grant() {
    let item: ListItemSnapshot =
        serde_json::from_value(serde_json::json!({"id":"dad","title":"Dad"})).unwrap();
    assert!(!item.priority);
    assert!(item.can_call);
}
#[test]
fn targeted_action_round_trips() {
    let command = CallCommand {
        key: SessionKey {
            transport: CallTransport::Sip,
            generation: 2,
            call_id: "incoming-7".into(),
        },
        action: CallAction::Reject(RejectReason::Busy),
    };
    assert_eq!(
        serde_json::from_value::<CallCommand>(serde_json::to_value(&command).unwrap()).unwrap(),
        command
    );
}
#[test]
fn invalid_session_actions_are_rejected() {
    for key in [
        serde_json::json!({"transport":"sip","generation":2}),
        serde_json::json!({"transport":"sip","generation":2,"call_id":" "}),
        serde_json::json!({"transport":"sip","call_id":"a"}),
        serde_json::json!({"transport":"invalid","generation":2,"call_id":"a"}),
    ] {
        assert!(serde_json::from_value::<CallCommand>(
            serde_json::json!({"key":key,"action":"answer"})
        )
        .is_err());
    }
}
#[test]
fn settings_intents_round_trip() {
    for intent in [
        SettingsIntent::DeviceModeSet(DeviceMode::Silent),
        SettingsIntent::DeviceModeSet(DeviceMode::DoNotDisturb),
        SettingsIntent::ContactPrioritySet(ContactPrioritySet {
            contact_id: "dad".into(),
            priority: true,
        }),
        SettingsIntent::ContactPrioritySet(ContactPrioritySet {
            contact_id: "dad".into(),
            priority: false,
        }),
    ] {
        let intent = UiIntent::Settings(intent);
        assert_eq!(
            UiIntent::from_event_payload(&intent.to_event_payload()).unwrap(),
            intent
        );
    }
}

#[test]
fn legacy_snapshots_default_to_inactive_session_and_normal_mode() {
    let snapshot =
        yoyopod_protocol::ui::RuntimeSnapshot::from_payload(&serde_json::json!({})).unwrap();
    assert_eq!(snapshot.settings.device_mode, DeviceMode::Normal);
    assert!(snapshot.call.session.is_none());
    assert!(snapshot.call.session_phase.is_none());
    assert!(!snapshot.call.accept_enabled);
    assert!(!snapshot.call.alert_audible);
    let key = serde_json::json!({"transport":"sip","generation":2,"call_id":"a"});
    for action in [
        serde_json::json!("bogus"),
        serde_json::json!({"reject":"bogus"}),
    ] {
        assert!(serde_json::from_value::<CallCommand>(
            serde_json::json!({"key":key,"action":action})
        )
        .is_err());
    }
}
