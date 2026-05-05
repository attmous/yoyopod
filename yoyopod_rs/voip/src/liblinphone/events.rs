use std::collections::VecDeque;
use std::sync::Mutex;

use crate::host::{BackendEvent, MessageRecord};

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum LiblinphoneEvent {
    RegistrationChanged {
        state: String,
        reason: String,
    },
    IncomingCall {
        call_id: String,
        from_uri: String,
    },
    CallStateChanged {
        call_id: String,
        state: String,
    },
    BackendStopped {
        reason: String,
    },
    MessageReceived {
        message: MessageRecord,
    },
    MessageDeliveryChanged {
        message_id: String,
        delivery_state: String,
        local_file_path: String,
        error: String,
    },
    MessageDownloadCompleted {
        message_id: String,
        local_file_path: String,
        mime_type: String,
    },
    MessageFailed {
        message_id: String,
        reason: String,
    },
}

impl LiblinphoneEvent {
    pub fn into_backend_event(self) -> BackendEvent {
        match self {
            Self::RegistrationChanged { state, reason } => {
                BackendEvent::RegistrationChanged { state, reason }
            }
            Self::IncomingCall { call_id, from_uri } => {
                BackendEvent::IncomingCall { call_id, from_uri }
            }
            Self::CallStateChanged { call_id, state } => {
                BackendEvent::CallStateChanged { call_id, state }
            }
            Self::BackendStopped { reason } => BackendEvent::BackendStopped { reason },
            Self::MessageReceived { message } => BackendEvent::MessageReceived { message },
            Self::MessageDeliveryChanged {
                message_id,
                delivery_state,
                local_file_path,
                error,
            } => BackendEvent::MessageDeliveryChanged {
                message_id,
                delivery_state,
                local_file_path,
                error,
            },
            Self::MessageDownloadCompleted {
                message_id,
                local_file_path,
                mime_type,
            } => BackendEvent::MessageDownloadCompleted {
                message_id,
                local_file_path,
                mime_type,
            },
            Self::MessageFailed { message_id, reason } => {
                BackendEvent::MessageFailed { message_id, reason }
            }
        }
    }
}

#[derive(Debug, Default)]
pub struct EventQueue {
    inner: Mutex<VecDeque<LiblinphoneEvent>>,
}

impl EventQueue {
    pub fn push(&self, event: LiblinphoneEvent) {
        if let Ok(mut events) = self.inner.lock() {
            events.push_back(event);
        }
    }

    pub fn drain_backend_events(&self) -> Vec<BackendEvent> {
        let Ok(mut events) = self.inner.lock() else {
            return Vec::new();
        };
        events
            .drain(..)
            .map(LiblinphoneEvent::into_backend_event)
            .collect()
    }
}
