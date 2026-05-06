use std::collections::VecDeque;
use std::os::raw::c_char;
use std::sync::Mutex;

const EVENT_QUEUE_CAPACITY: usize = 128;

pub const EVENT_REGISTRATION: i32 = 1;
pub const EVENT_CALL_STATE: i32 = 2;
pub const EVENT_INCOMING_CALL: i32 = 3;
pub const EVENT_BACKEND_STOPPED: i32 = 4;
pub const EVENT_MESSAGE_RECEIVED: i32 = 5;
pub const EVENT_MESSAGE_DELIVERY_CHANGED: i32 = 6;
pub const EVENT_MESSAGE_DOWNLOAD_COMPLETED: i32 = 7;
pub const EVENT_MESSAGE_FAILED: i32 = 8;

pub const REGISTRATION_NONE: i32 = 0;
pub const REGISTRATION_PROGRESS: i32 = 1;
pub const REGISTRATION_OK: i32 = 2;
pub const REGISTRATION_CLEARED: i32 = 3;
pub const REGISTRATION_FAILED: i32 = 4;

pub const CALL_IDLE: i32 = 0;
pub const CALL_INCOMING: i32 = 1;
pub const CALL_OUTGOING_INIT: i32 = 2;
pub const CALL_OUTGOING_PROGRESS: i32 = 3;
pub const CALL_OUTGOING_RINGING: i32 = 4;
pub const CALL_OUTGOING_EARLY_MEDIA: i32 = 5;
pub const CALL_CONNECTED: i32 = 6;
pub const CALL_STREAMS_RUNNING: i32 = 7;
pub const CALL_PAUSED: i32 = 8;
pub const CALL_PAUSED_BY_REMOTE: i32 = 9;
pub const CALL_UPDATED_BY_REMOTE: i32 = 10;
pub const CALL_RELEASED: i32 = 11;
pub const CALL_ERROR: i32 = 12;
pub const CALL_END: i32 = 13;

pub const MESSAGE_KIND_TEXT: i32 = 1;
pub const MESSAGE_KIND_VOICE_NOTE: i32 = 2;

pub const MESSAGE_DIRECTION_INCOMING: i32 = 1;
pub const MESSAGE_DIRECTION_OUTGOING: i32 = 2;

pub const MESSAGE_DELIVERY_QUEUED: i32 = 1;
pub const MESSAGE_DELIVERY_SENDING: i32 = 2;
pub const MESSAGE_DELIVERY_SENT: i32 = 3;
pub const MESSAGE_DELIVERY_DELIVERED: i32 = 4;
pub const MESSAGE_DELIVERY_FAILED: i32 = 5;

#[repr(C)]
#[derive(Clone, Copy)]
pub struct YoyopodLiblinphoneEvent {
    pub event_type: i32,
    pub registration_state: i32,
    pub call_state: i32,
    pub message_kind: i32,
    pub message_direction: i32,
    pub message_delivery_state: i32,
    pub duration_ms: i32,
    pub unread: i32,
    pub message_id: [c_char; 128],
    pub peer_sip_address: [c_char; 256],
    pub sender_sip_address: [c_char; 256],
    pub recipient_sip_address: [c_char; 256],
    pub local_file_path: [c_char; 512],
    pub mime_type: [c_char; 128],
    pub text: [c_char; 1024],
    pub reason: [c_char; 256],
}

impl Default for YoyopodLiblinphoneEvent {
    fn default() -> Self {
        Self {
            event_type: 0,
            registration_state: 0,
            call_state: 0,
            message_kind: 0,
            message_direction: 0,
            message_delivery_state: 0,
            duration_ms: 0,
            unread: 0,
            message_id: [0; 128],
            peer_sip_address: [0; 256],
            sender_sip_address: [0; 256],
            recipient_sip_address: [0; 256],
            local_file_path: [0; 512],
            mime_type: [0; 128],
            text: [0; 1024],
            reason: [0; 256],
        }
    }
}

#[derive(Default)]
pub struct EventQueue {
    inner: Mutex<VecDeque<YoyopodLiblinphoneEvent>>,
}

impl EventQueue {
    pub fn push(&self, event: YoyopodLiblinphoneEvent) {
        if let Ok(mut events) = self.inner.lock() {
            if events.len() >= EVENT_QUEUE_CAPACITY {
                events.pop_front();
            }
            events.push_back(event);
        }
    }

    pub fn pop(&self) -> Option<YoyopodLiblinphoneEvent> {
        self.inner
            .lock()
            .ok()
            .and_then(|mut events| events.pop_front())
    }
}
