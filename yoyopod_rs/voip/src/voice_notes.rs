use serde_json::json;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct VoiceNoteSession {
    state: String,
    file_path: String,
    duration_ms: i32,
    mime_type: String,
    message_id: String,
}

impl Default for VoiceNoteSession {
    fn default() -> Self {
        Self {
            state: "idle".to_string(),
            file_path: String::new(),
            duration_ms: 0,
            mime_type: String::new(),
            message_id: String::new(),
        }
    }
}

impl VoiceNoteSession {
    pub fn reset(&mut self) {
        *self = Self::default();
    }

    pub fn start_recording(&mut self, file_path: &str) {
        self.state = "recording".to_string();
        self.file_path = file_path.to_string();
        self.duration_ms = 0;
        self.mime_type = "audio/wav".to_string();
        self.message_id.clear();
    }

    pub fn finish_recording(&mut self, duration_ms: i32) {
        self.state = "recorded".to_string();
        self.duration_ms = duration_ms;
    }

    pub fn start_sending(
        &mut self,
        file_path: &str,
        duration_ms: i32,
        mime_type: &str,
        message_id: &str,
    ) {
        self.state = "sending".to_string();
        self.file_path = file_path.to_string();
        self.duration_ms = duration_ms;
        self.mime_type = mime_type.to_string();
        self.message_id = message_id.to_string();
    }

    pub fn apply_delivery(
        &mut self,
        message_id: &str,
        delivery_state: &str,
        _local_file_path: &str,
    ) {
        if self.message_id != message_id {
            return;
        }
        self.state = match delivery_state {
            "failed" => "failed",
            "sent" | "delivered" => "sent",
            _ => "sending",
        }
        .to_string();
    }

    pub fn apply_download(&mut self, message_id: &str, local_file_path: &str, mime_type: &str) {
        if self.message_id != message_id {
            return;
        }
        self.file_path = local_file_path.to_string();
        self.mime_type = mime_type.to_string();
    }

    pub fn fail(&mut self, message_id: &str) {
        if self.message_id == message_id {
            self.state = "failed".to_string();
        }
    }

    pub fn payload(&self) -> serde_json::Value {
        json!({
            "state": self.state,
            "file_path": self.file_path,
            "duration_ms": self.duration_ms,
            "mime_type": self.mime_type,
            "message_id": self.message_id,
        })
    }
}
