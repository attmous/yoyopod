use serde_json::json;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct VoiceNoteSession {
    state: String,
    file_path: String,
    duration_ms: i32,
    capture_level_permille: i32,
    mime_type: String,
    message_id: String,
}

impl Default for VoiceNoteSession {
    fn default() -> Self {
        Self {
            state: "idle".to_string(),
            file_path: String::new(),
            duration_ms: 0,
            capture_level_permille: 0,
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
        self.capture_level_permille = 0;
        self.mime_type = "audio/wav".to_string();
        self.message_id.clear();
    }

    pub fn finish_recording(&mut self, duration_ms: i32) {
        self.state = "recorded".to_string();
        self.duration_ms = duration_ms.max(0);
        self.capture_level_permille = 0;
    }

    pub fn is_recording(&self) -> bool {
        self.state == "recording"
    }

    pub fn recorded_duration_ms(&self) -> Option<i32> {
        (self.state == "recorded").then_some(self.duration_ms)
    }

    pub fn update_recording_metrics(
        &mut self,
        duration_ms: i32,
        capture_level_permille: i32,
    ) -> bool {
        if !self.is_recording() {
            return false;
        }
        let duration_ms = duration_ms.max(0);
        let capture_level_permille = capture_level_permille.clamp(0, 1000);
        // The backend is polled at audio cadence. Publish UI metrics at 10 Hz
        // so live feedback stays smooth without flooding the runtime pipe.
        let changed = self.duration_ms / 100 != duration_ms / 100;
        if changed {
            self.duration_ms = duration_ms;
            self.capture_level_permille = capture_level_permille;
        }
        changed
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
            "capture_level_permille": self.capture_level_permille,
            "mime_type": self.mime_type,
            "message_id": self.message_id,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn recording_metrics_are_clamped_and_published_at_ten_hertz() {
        let mut session = VoiceNoteSession::default();
        session.start_recording("/tmp/live.wav");

        assert!(!session.update_recording_metrics(99, 500));
        assert!(session.update_recording_metrics(100, 1_200));
        let payload = session.payload();
        assert_eq!(payload["duration_ms"], 100);
        assert_eq!(payload["capture_level_permille"], 1_000);

        session.finish_recording(123);
        let payload = session.payload();
        assert_eq!(payload["state"], "recorded");
        assert_eq!(payload["capture_level_permille"], 0);
        assert_eq!(session.recorded_duration_ms(), Some(123));
    }
}
