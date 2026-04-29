use std::os::raw::c_char;
use std::path::PathBuf;

use serde_json::json;
use yoyopod_voip_host::config::VoipConfig;
use yoyopod_voip_host::host::{BackendEvent, MessageRecord};
use yoyopod_voip_host::shim::{
    native_event_to_backend_event, resolve_shim_path, NativeEvent, StartAudioSettings,
};

#[test]
fn explicit_path_wins() {
    let path = resolve_shim_path(Some("/tmp/libshim.so")).expect("path");
    assert_eq!(path, PathBuf::from("/tmp/libshim.so"));
}

#[test]
fn start_audio_settings_forward_configured_gain_and_volume() {
    let config = VoipConfig::from_payload(&json!({
        "sip_server": "sip.example.com",
        "sip_identity": "sip:alice@example.com",
        "mic_gain": 42,
        "output_volume": 73
    }))
    .expect("config");

    let settings = StartAudioSettings::from_config(&config);

    assert_eq!(settings.audio_enabled, 1);
    assert_eq!(settings.mic_gain, 42);
    assert_eq!(settings.output_volume, 73);
}

#[test]
fn native_message_event_maps_to_backend_message_record() {
    let mut event = NativeEvent {
        event_type: 5,
        message_kind: 1,
        message_direction: 1,
        message_delivery_state: 4,
        duration_ms: 1200,
        unread: 1,
        ..Default::default()
    };
    write_c_string(&mut event.message_id, "msg-1");
    write_c_string(&mut event.peer_sip_address, "sip:bob@example.com");
    write_c_string(&mut event.sender_sip_address, "sip:bob@example.com");
    write_c_string(&mut event.recipient_sip_address, "sip:alice@example.com");
    write_c_string(&mut event.text, "hello");
    write_c_string(&mut event.mime_type, "text/plain");

    let backend_event = native_event_to_backend_event(&event).expect("backend event");

    assert_eq!(
        backend_event,
        BackendEvent::MessageReceived {
            message: MessageRecord {
                message_id: "msg-1".to_string(),
                peer_sip_address: "sip:bob@example.com".to_string(),
                sender_sip_address: "sip:bob@example.com".to_string(),
                recipient_sip_address: "sip:alice@example.com".to_string(),
                kind: "text".to_string(),
                direction: "incoming".to_string(),
                delivery_state: "delivered".to_string(),
                text: "hello".to_string(),
                local_file_path: "".to_string(),
                mime_type: "text/plain".to_string(),
                duration_ms: 1200,
                unread: true,
            }
        }
    );
}

#[test]
fn native_message_delivery_events_map_to_backend_events() {
    let mut delivery = NativeEvent {
        event_type: 6,
        message_delivery_state: 5,
        ..Default::default()
    };
    write_c_string(&mut delivery.message_id, "msg-1");
    write_c_string(&mut delivery.local_file_path, "/tmp/msg.wav");
    write_c_string(&mut delivery.reason, "peer offline");

    assert_eq!(
        native_event_to_backend_event(&delivery),
        Some(BackendEvent::MessageDeliveryChanged {
            message_id: "msg-1".to_string(),
            delivery_state: "failed".to_string(),
            local_file_path: "/tmp/msg.wav".to_string(),
            error: "peer offline".to_string(),
        })
    );

    let mut failed = NativeEvent {
        event_type: 8,
        ..Default::default()
    };
    write_c_string(&mut failed.message_id, "msg-2");
    write_c_string(&mut failed.reason, "send failed");

    assert_eq!(
        native_event_to_backend_event(&failed),
        Some(BackendEvent::MessageFailed {
            message_id: "msg-2".to_string(),
            reason: "send failed".to_string(),
        })
    );
}

fn write_c_string<const N: usize>(buffer: &mut [c_char; N], value: &str) {
    for (slot, byte) in buffer.iter_mut().zip(value.bytes()) {
        *slot = byte as c_char;
    }
}
