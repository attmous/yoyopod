use serde_json::{json, Value};

use crate::config::MediaConfig;

#[derive(Debug, Clone, Default)]
pub struct MediaHost {
    config: Option<MediaConfig>,
    commands_processed: u64,
}

impl MediaHost {
    pub fn record_command(&mut self) {
        self.commands_processed = self.commands_processed.saturating_add(1);
    }

    pub fn configure(&mut self, config: MediaConfig) {
        self.config = Some(config);
    }

    pub fn health_payload(&self) -> Value {
        let mut payload = self.snapshot_payload();
        if let Some(object) = payload.as_object_mut() {
            object.insert("ready".to_string(), json!(true));
            object.insert("command_count".to_string(), json!(self.commands_processed));
            object.insert("backend_state".to_string(), json!("not_started"));
        }
        payload
    }

    pub fn snapshot_payload(&self) -> Value {
        match self.config.as_ref() {
            Some(config) => json!({
                "configured": true,
                "music_dir": config.music_dir,
                "mpv_socket": config.mpv_socket,
                "mpv_binary": config.mpv_binary,
                "alsa_device": config.alsa_device,
                "default_volume": config.default_volume,
                "recent_tracks_file": config.recent_tracks_file,
                "remote_cache_dir": config.remote_cache_dir,
                "remote_cache_max_bytes": config.remote_cache_max_bytes,
            }),
            None => json!({
                "configured": false,
                "music_dir": "",
                "mpv_socket": "",
                "mpv_binary": "",
                "alsa_device": "",
                "default_volume": 0,
                "recent_tracks_file": "",
                "remote_cache_dir": "",
                "remote_cache_max_bytes": 0,
            }),
        }
    }
}
