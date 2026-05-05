use yoyopod_voip::host::BackendEvent;
use yoyopod_voip::liblinphone::{EventQueue, LiblinphoneEvent};

#[test]
fn liblinphone_event_queue_drains_fifo_backend_events() {
    let queue = EventQueue::default();
    queue.push(LiblinphoneEvent::RegistrationChanged {
        state: "ok".to_string(),
        reason: "registered".to_string(),
    });
    queue.push(LiblinphoneEvent::IncomingCall {
        call_id: "call-1".to_string(),
        from_uri: "sip:mom@example.com".to_string(),
    });

    let events = queue.drain_backend_events();

    assert_eq!(
        events,
        vec![
            BackendEvent::RegistrationChanged {
                state: "ok".to_string(),
                reason: "registered".to_string(),
            },
            BackendEvent::IncomingCall {
                call_id: "call-1".to_string(),
                from_uri: "sip:mom@example.com".to_string(),
            },
        ]
    );
    assert!(queue.drain_backend_events().is_empty());
}

#[test]
fn liblinphone_backend_type_is_host_runtime_backend() {
    #[cfg(feature = "native-liblinphone")]
    fn assert_backend<T: yoyopod_voip::host::VoipRuntimeBackend>() {}

    #[cfg(feature = "native-liblinphone")]
    assert_backend::<yoyopod_voip::liblinphone::LiblinphoneBackend>();
}
