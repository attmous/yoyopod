use std::path::Path;
use std::process::{Child, Command, Stdio};

pub struct VoiceNotePlayback {
    current: Option<Child>,
    current_file_path: String,
}

impl Default for VoiceNotePlayback {
    fn default() -> Self {
        Self {
            current: None,
            current_file_path: String::new(),
        }
    }
}

impl std::fmt::Debug for VoiceNotePlayback {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("VoiceNotePlayback")
            .field("playing", &self.is_playing())
            .field("current_file_path", &self.current_file_path)
            .finish()
    }
}

impl VoiceNotePlayback {
    pub fn command_for(file_path: &str) -> Vec<String> {
        if is_wav(file_path) {
            return vec!["aplay".to_string(), "-q".to_string(), file_path.to_string()];
        }
        vec![
            "ffplay".to_string(),
            "-nodisp".to_string(),
            "-autoexit".to_string(),
            "-loglevel".to_string(),
            "error".to_string(),
            "-af".to_string(),
            "volume=12.0dB".to_string(),
            file_path.to_string(),
        ]
    }

    pub fn play(&mut self, file_path: &str) -> Result<(), String> {
        let file_path = file_path.trim();
        if file_path.is_empty() {
            return Err("voice-note playback requires file_path".to_string());
        }
        self.stop();
        let command = Self::command_for(file_path);
        let child = Command::new(&command[0])
            .args(&command[1..])
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()
            .map_err(|error| format!("failed to start voice-note playback: {error}"))?;
        self.current = Some(child);
        self.current_file_path = file_path.to_string();
        Ok(())
    }

    pub fn stop(&mut self) {
        if let Some(mut child) = self.current.take() {
            let _ = child.kill();
            let _ = child.wait();
        }
        self.current_file_path.clear();
    }

    pub fn is_playing(&self) -> bool {
        self.current.is_some()
    }

    pub fn payload(&self) -> serde_json::Value {
        serde_json::json!({
            "playing": self.is_playing(),
            "file_path": self.current_file_path,
        })
    }
}

impl Drop for VoiceNotePlayback {
    fn drop(&mut self) {
        self.stop();
    }
}

fn is_wav(file_path: &str) -> bool {
    Path::new(file_path)
        .extension()
        .and_then(|extension| extension.to_str())
        .is_some_and(|extension| extension.eq_ignore_ascii_case("wav"))
}
