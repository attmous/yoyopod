use crate::calls::CallSession;
use crate::lifecycle::LifecycleState;
use crate::messages::MessageSessionState;
use crate::voice_notes::VoiceNoteSession;
use serde_json::json;

pub struct RuntimeSnapshot<'a> {
    pub configured: bool,
    pub registered: bool,
    pub registration_state: &'a str,
    pub lifecycle: &'a LifecycleState,
    pub call: &'a CallSession,
    pub voice_note: &'a VoiceNoteSession,
    pub last_message: Option<&'a MessageSessionState>,
    pub pending_outbound_messages: usize,
}

impl RuntimeSnapshot<'_> {
    pub fn payload(&self) -> serde_json::Value {
        let last_message = self
            .last_message
            .map(MessageSessionState::payload)
            .unwrap_or(serde_json::Value::Null);

        json!({
            "configured": self.configured,
            "registered": self.registered,
            "registration_state": self.registration_state,
            "lifecycle": self.lifecycle.payload(self.registered),
            "call_state": self.call.state(),
            "active_call_id": self.call.active_call_id(),
            "active_call_peer": self.call.active_peer(),
            "muted": self.call.muted(),
            "call_session": self.call.session_payload(),
            "pending_outbound_messages": self.pending_outbound_messages,
            "voice_note": self.voice_note.payload(),
            "last_message": last_message,
        })
    }
}
