use serde::{Deserialize, Serialize};
use serde_json::Value;
use thiserror::Error;

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct VoipConfig {
    #[serde(default = "default_sip_server")]
    pub sip_server: String,
    #[serde(default)]
    pub sip_username: String,
    #[serde(default)]
    pub sip_password: String,
    #[serde(default)]
    pub sip_password_ha1: String,
    #[serde(default)]
    pub sip_identity: String,
    #[serde(default)]
    pub factory_config_path: String,
    #[serde(default = "default_transport")]
    pub transport: String,
    #[serde(default)]
    pub stun_server: String,
    #[serde(default)]
    pub conference_factory_uri: String,
    #[serde(default)]
    pub file_transfer_server_url: String,
    #[serde(default)]
    pub lime_server_url: String,
    #[serde(default = "default_iterate_interval_ms")]
    pub iterate_interval_ms: u64,
    #[serde(default)]
    pub message_store_dir: String,
    #[serde(default)]
    pub voice_note_store_dir: String,
    #[serde(default)]
    pub auto_download_incoming_voice_recordings: bool,
    #[serde(default = "default_audio_device")]
    pub playback_dev_id: String,
    #[serde(default = "default_audio_device")]
    pub ringer_dev_id: String,
    #[serde(default = "default_audio_device")]
    pub capture_dev_id: String,
    #[serde(default = "default_audio_device")]
    pub media_dev_id: String,
    #[serde(default = "default_mic_gain")]
    pub mic_gain: i32,
    #[serde(default = "default_output_volume")]
    pub output_volume: i32,
}

#[derive(Debug, Error)]
pub enum ConfigError {
    #[error("invalid voip config payload: {0}")]
    InvalidPayload(#[from] serde_json::Error),
    #[error("sip_server is required when a SIP identity is configured")]
    MissingSipServer,
}

impl VoipConfig {
    pub fn from_payload(payload: &Value) -> Result<Self, ConfigError> {
        let config: Self = serde_json::from_value(payload.clone())?;
        config.validate()?;
        Ok(config)
    }

    pub fn validate(&self) -> Result<(), ConfigError> {
        if self.has_sip_account() && self.sip_server.trim().is_empty() {
            return Err(ConfigError::MissingSipServer);
        }
        Ok(())
    }

    pub fn has_sip_account(&self) -> bool {
        !self.sip_identity.trim().is_empty()
    }
}

fn default_sip_server() -> String {
    "sip.linphone.org".to_string()
}

fn default_transport() -> String {
    "tcp".to_string()
}

fn default_iterate_interval_ms() -> u64 {
    20
}

fn default_audio_device() -> String {
    "ALSA: wm8960-soundcard".to_string()
}

fn default_mic_gain() -> i32 {
    80
}

fn default_output_volume() -> i32 {
    100
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn local_first_config_does_not_require_a_sip_identity() {
        let config = VoipConfig::from_payload(&json!({
            "voice_note_store_dir": "data/communication/voice_notes"
        }))
        .expect("local recording config should be valid without SIP credentials");

        assert!(!config.has_sip_account());
    }

    #[test]
    fn configured_sip_identity_still_requires_a_server() {
        let error = VoipConfig::from_payload(&json!({
            "sip_identity": "sip:yoyopod@example.test",
            "sip_server": ""
        }))
        .expect_err("SIP registration cannot proceed without its server");

        assert!(matches!(error, ConfigError::MissingSipServer));
    }
}
