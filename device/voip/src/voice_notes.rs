use serde_json::json;

const SAVED_PREFIX: &str = ".yoyopod-interrupted-";

pub fn is_saved_draft_path(path: &str) -> bool {
    std::path::Path::new(path)
        .file_name()
        .and_then(|s| s.to_str())
        .is_some_and(|name| name.starts_with(SAVED_PREFIX))
}

/// Reserve a never-overwritten file on the same filesystem. Wall-clock rollback
/// and recorder path reuse cannot retarget a displayed draft or an HTTP upload.
pub fn preserve_interrupted_wav(source: &str) -> Result<String, String> {
    use std::sync::atomic::{AtomicU64, Ordering};
    static NEXT: AtomicU64 = AtomicU64::new(0);
    let parent = std::path::Path::new(source)
        .parent()
        .ok_or("draft has no parent")?;
    for _ in 0..1024 {
        let path = parent.join(format!(
            "{SAVED_PREFIX}{}-{}.wav",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        let mut output = match std::fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&path)
        {
            Ok(file) => file,
            Err(e) if e.kind() == std::io::ErrorKind::AlreadyExists => continue,
            Err(e) => return Err(e.to_string()),
        };
        let result = std::fs::File::open(source)
            .and_then(|mut input| std::io::copy(&mut input, &mut output))
            .and_then(|_| output.sync_all());
        if let Err(e) = result {
            let _ = std::fs::remove_file(&path);
            return Err(e.to_string());
        }
        return Ok(path.to_string_lossy().into_owned());
    }
    Err("could not reserve unique interrupted recording".into())
}

/// Check closed RIFF/WAVE chunks without reading the captured audio into RAM.
pub fn usable_wav(path: &str) -> bool {
    use std::io::{Read, Seek, SeekFrom};
    let Ok(mut file) = std::fs::File::open(path) else {
        return false;
    };
    let Ok(metadata) = file.metadata() else {
        return false;
    };
    let mut header = [0u8; 12];
    if file.read_exact(&mut header).is_err() || &header[..4] != b"RIFF" || &header[8..] != b"WAVE" {
        return false;
    }
    let mut offset = 12u64;
    let mut format = false;
    while offset.saturating_add(8) <= metadata.len() {
        let mut chunk = [0u8; 8];
        if file.read_exact(&mut chunk).is_err() {
            return false;
        }
        let length = u32::from_le_bytes(chunk[4..].try_into().expect("four bytes")) as u64;
        offset += 8;
        if offset.saturating_add(length) > metadata.len() {
            return false;
        }
        if &chunk[..4] == b"fmt " {
            format = length >= 16;
        }
        if &chunk[..4] == b"data" {
            return format && length >= 2;
        }
        offset = offset.saturating_add(length + length % 2);
        if file.seek(SeekFrom::Start(offset)).is_err() {
            return false;
        }
    }
    false
}

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
