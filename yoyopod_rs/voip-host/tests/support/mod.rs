use serde_json::json;
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};
use yoyopod_voip_host::config::VoipConfig;
use yoyopod_voip_host::host::{BackendEvent, CallBackend};

pub fn config() -> VoipConfig {
    VoipConfig::from_payload(&json!({
        "sip_server": "sip.example.com",
        "sip_identity": "sip:alice@example.com"
    }))
    .expect("config")
}

#[allow(dead_code)]
pub fn config_with_message_store(store_dir: &Path) -> VoipConfig {
    VoipConfig::from_payload(&json!({
        "sip_server": "sip.example.com",
        "sip_identity": "sip:alice@example.com",
        "message_store_dir": store_dir.to_string_lossy()
    }))
    .expect("config")
}

#[allow(dead_code)]
pub fn temp_store_dir(test_name: &str) -> PathBuf {
    let unique = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("system time")
        .as_nanos();
    std::env::temp_dir().join(format!("yoyopod-{test_name}-{unique}"))
}

#[derive(Default)]
pub struct FakeBackend {
    pub calls: Vec<String>,
    pub events: Vec<BackendEvent>,
    pub start_results: Vec<Result<(), String>>,
    pub stop_calls: usize,
}

impl CallBackend for FakeBackend {
    fn start(&mut self, _config: &VoipConfig) -> Result<(), String> {
        if !self.start_results.is_empty() {
            return self.start_results.remove(0);
        }
        self.calls.push("start".to_string());
        Ok(())
    }

    fn stop(&mut self) {
        self.stop_calls += 1;
        self.calls.push("stop".to_string());
    }

    fn iterate(&mut self) -> Result<Vec<BackendEvent>, String> {
        Ok(std::mem::take(&mut self.events))
    }

    fn make_call(&mut self, sip_address: &str) -> Result<String, String> {
        self.calls.push(format!("dial:{sip_address}"));
        Ok("call-outgoing".to_string())
    }

    fn answer_call(&mut self) -> Result<(), String> {
        self.calls.push("answer".to_string());
        Ok(())
    }

    fn reject_call(&mut self) -> Result<(), String> {
        self.calls.push("reject".to_string());
        Ok(())
    }

    fn hangup(&mut self) -> Result<(), String> {
        self.calls.push("hangup".to_string());
        Ok(())
    }

    fn set_muted(&mut self, muted: bool) -> Result<(), String> {
        self.calls.push(format!("mute:{muted}"));
        Ok(())
    }

    fn send_text_message(&mut self, sip_address: &str, text: &str) -> Result<String, String> {
        self.calls.push(format!("text:{sip_address}:{text}"));
        Ok("backend-msg-1".to_string())
    }

    fn start_voice_recording(&mut self, file_path: &str) -> Result<(), String> {
        self.calls.push(format!("record:{file_path}"));
        Ok(())
    }

    fn stop_voice_recording(&mut self) -> Result<i32, String> {
        self.calls.push("stop_recording".to_string());
        Ok(1250)
    }

    fn cancel_voice_recording(&mut self) -> Result<(), String> {
        self.calls.push("cancel_recording".to_string());
        Ok(())
    }

    fn send_voice_note(
        &mut self,
        sip_address: &str,
        file_path: &str,
        duration_ms: i32,
        mime_type: &str,
    ) -> Result<String, String> {
        self.calls.push(format!(
            "voice:{sip_address}:{file_path}:{duration_ms}:{mime_type}"
        ));
        Ok("backend-vn-1".to_string())
    }
}
