use std::path::Path;

use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
pub struct Track {
    pub uri: String,
    pub name: String,
    pub artists: Vec<String>,
    pub album: String,
    pub length_ms: i64,
    pub track_no: Option<i32>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
#[serde(rename_all = "snake_case")]
pub enum PlaybackState {
    #[default]
    Stopped,
    Playing,
    Paused,
}

impl PlaybackState {
    pub fn as_str(&self) -> &'static str {
        match self {
            PlaybackState::Stopped => "stopped",
            PlaybackState::Playing => "playing",
            PlaybackState::Paused => "paused",
        }
    }
}

impl Track {
    pub fn from_mpv_metadata(path: &str, metadata: &Map<String, Value>) -> Self {
        let normalized = normalize_metadata(metadata);
        let path_obj = Path::new(path);
        let fallback_name = path_obj
            .file_stem()
            .and_then(|stem| stem.to_str())
            .unwrap_or(path)
            .to_string();

        let file_name = path_obj
            .file_name()
            .and_then(|name| name.to_str())
            .unwrap_or_default();
        let runtime_title = normalized
            .get("title")
            .and_then(Value::as_str)
            .unwrap_or_default();
        let title = if runtime_title.is_empty() || runtime_title == file_name {
            fallback_name
        } else {
            runtime_title.to_string()
        };

        let artists = artist_list(normalized.get("artist"));
        let album = normalized
            .get("album")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_string();
        let track_no = track_number(
            normalized
                .get("track")
                .or_else(|| normalized.get("track_no"))
                .or_else(|| normalized.get("tracknumber")),
        );

        Self {
            uri: path.to_string(),
            name: title,
            artists: if artists.is_empty() {
                vec!["Unknown".to_string()]
            } else {
                artists
            },
            album,
            length_ms: duration_ms(normalized.get("duration")),
            track_no,
        }
    }
}

pub fn duration_ms(value: Option<&Value>) -> i64 {
    let Some(value) = value else {
        return 0;
    };
    match value {
        Value::Number(number) => number
            .as_f64()
            .map(|seconds| (seconds.max(0.0) * 1000.0) as i64)
            .unwrap_or(0),
        Value::String(string) => string
            .parse::<f64>()
            .ok()
            .map(|seconds| (seconds.max(0.0) * 1000.0) as i64)
            .unwrap_or(0),
        _ => 0,
    }
}

fn normalize_metadata(metadata: &Map<String, Value>) -> Map<String, Value> {
    metadata
        .iter()
        .map(|(key, value)| (key.to_ascii_lowercase(), value.clone()))
        .collect()
}

fn artist_list(value: Option<&Value>) -> Vec<String> {
    let Some(value) = value else {
        return Vec::new();
    };
    match value {
        Value::String(string) if !string.is_empty() => vec![string.to_string()],
        Value::Array(values) => values
            .iter()
            .filter_map(Value::as_str)
            .filter(|value| !value.is_empty())
            .map(ToString::to_string)
            .collect(),
        _ => Vec::new(),
    }
}

fn track_number(value: Option<&Value>) -> Option<i32> {
    let value = value?;
    match value {
        Value::Number(number) => number.as_i64().map(|value| value as i32),
        Value::String(string) => string.parse::<i32>().ok(),
        _ => None,
    }
}
