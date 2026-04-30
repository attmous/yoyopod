use serde::{Deserialize, Serialize};
use serde_json::Value;
use thiserror::Error;

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct MediaConfig {
    #[serde(default = "default_music_dir")]
    pub music_dir: String,
    #[serde(default = "default_mpv_socket")]
    pub mpv_socket: String,
    #[serde(default = "default_mpv_binary")]
    pub mpv_binary: String,
    #[serde(default = "default_alsa_device")]
    pub alsa_device: String,
    #[serde(default = "default_volume")]
    pub default_volume: i32,
    #[serde(default = "default_recent_tracks_file")]
    pub recent_tracks_file: String,
    #[serde(default = "default_remote_cache_dir")]
    pub remote_cache_dir: String,
    #[serde(default = "default_remote_cache_max_bytes")]
    pub remote_cache_max_bytes: u64,
}

#[derive(Debug, Error)]
pub enum ConfigError {
    #[error("invalid media config payload: {0}")]
    InvalidPayload(#[from] serde_json::Error),
    #[error("music_dir is required for Rust media host configuration")]
    MissingMusicDir,
}

impl MediaConfig {
    pub fn from_payload(payload: &Value) -> Result<Self, ConfigError> {
        let config: Self = serde_json::from_value(payload.clone())?;
        config.validate()?;
        Ok(config)
    }

    pub fn validate(&self) -> Result<(), ConfigError> {
        if self.music_dir.trim().is_empty() {
            return Err(ConfigError::MissingMusicDir);
        }
        Ok(())
    }
}

fn default_music_dir() -> String {
    "/home/pi/Music".to_string()
}

fn default_mpv_socket() -> String {
    if cfg!(target_os = "windows") {
        r"\\.\pipe\yoyopod-mpv".to_string()
    } else {
        "/tmp/yoyopod-mpv.sock".to_string()
    }
}

fn default_mpv_binary() -> String {
    "mpv".to_string()
}

fn default_alsa_device() -> String {
    "default".to_string()
}

fn default_volume() -> i32 {
    100
}

fn default_recent_tracks_file() -> String {
    "data/media/recent_tracks.json".to_string()
}

fn default_remote_cache_dir() -> String {
    "data/media/remote_cache".to_string()
}

fn default_remote_cache_max_bytes() -> u64 {
    536_870_912
}
