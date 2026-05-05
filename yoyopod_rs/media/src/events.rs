use serde_json::Value;

use crate::models::{PlaybackState, Track};

#[derive(Debug, Clone, PartialEq)]
pub enum MediaRuntimeEvent {
    TrackChanged(Option<Track>),
    PlaybackStateChanged(PlaybackState),
    TimePositionChanged(i64),
    BackendAvailabilityChanged { connected: bool, reason: String },
}

#[derive(Debug, Clone, PartialEq)]
pub enum MpvEvent {
    FileLoaded,
    PlaybackRestart,
    Pause,
    Unpause,
    EndFile { reason: String },
    PropertyChange { name: String, data: Value },
}

impl MpvEvent {
    pub fn from_value(value: Value) -> Option<Self> {
        let object = value.as_object()?;
        let event_name = object.get("event")?.as_str()?;
        match event_name {
            "file-loaded" => Some(Self::FileLoaded),
            "playback-restart" => Some(Self::PlaybackRestart),
            "pause" => Some(Self::Pause),
            "unpause" => Some(Self::Unpause),
            "end-file" => Some(Self::EndFile {
                reason: object
                    .get("reason")
                    .and_then(Value::as_str)
                    .unwrap_or_default()
                    .to_string(),
            }),
            "property-change" => Some(Self::PropertyChange {
                name: object
                    .get("name")
                    .and_then(Value::as_str)
                    .unwrap_or_default()
                    .to_string(),
                data: object.get("data").cloned().unwrap_or(Value::Null),
            }),
            _ => None,
        }
    }
}
