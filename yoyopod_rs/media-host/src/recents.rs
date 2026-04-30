use std::fs;
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

use serde::{Deserialize, Serialize};
use time::{format_description::well_known::Rfc3339, OffsetDateTime};

use crate::models::Track;

const DEFAULT_MAX_ENTRIES: usize = 50;

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct RecentTrackEntry {
    pub uri: String,
    pub title: String,
    pub artist: String,
    #[serde(default)]
    pub album: String,
    pub played_at: String,
}

#[derive(Debug, Default, Serialize, Deserialize)]
struct RecentTrackPayload {
    #[serde(default)]
    entries: Vec<RecentTrackEntry>,
}

#[derive(Debug, Clone)]
pub struct RecentTrackStore {
    history_file: Option<PathBuf>,
    max_entries: usize,
    entries: Vec<RecentTrackEntry>,
}

impl Default for RecentTrackStore {
    fn default() -> Self {
        Self::memory(DEFAULT_MAX_ENTRIES)
    }
}

impl RecentTrackEntry {
    pub fn subtitle(&self) -> String {
        if !self.artist.is_empty() && !self.album.is_empty() {
            return format!("{} - {}", self.artist, self.album);
        }
        if !self.artist.is_empty() {
            return self.artist.clone();
        }
        if !self.album.is_empty() {
            return self.album.clone();
        }
        "Played recently".to_string()
    }

    pub fn from_track(track: &Track) -> Self {
        Self {
            uri: track.uri.clone(),
            title: if track.name.is_empty() {
                "Unknown Track".to_string()
            } else {
                track.name.clone()
            },
            artist: if track.artists.is_empty() {
                "Unknown Artist".to_string()
            } else {
                track.artists.join(", ")
            },
            album: track.album.clone(),
            played_at: now_timestamp(),
        }
    }
}

impl RecentTrackStore {
    pub fn memory(max_entries: usize) -> Self {
        Self {
            history_file: None,
            max_entries: max_entries.max(1),
            entries: Vec::new(),
        }
    }

    pub fn open(history_file: impl AsRef<Path>, max_entries: usize) -> Self {
        let history_file = history_file.as_ref();
        if history_file.as_os_str().is_empty() {
            return Self::memory(max_entries);
        }

        let mut store = Self {
            history_file: Some(history_file.to_path_buf()),
            max_entries: max_entries.max(1),
            entries: Vec::new(),
        };
        store.load();
        store
    }

    pub fn record_track(&mut self, track: &Track) -> Result<(), String> {
        let entry = RecentTrackEntry::from_track(track);
        self.entries.retain(|item| item.uri != entry.uri);
        self.entries.insert(0, entry);
        self.entries.truncate(self.max_entries);
        self.save()
    }

    pub fn list_recent(&self, limit: Option<usize>) -> Vec<RecentTrackEntry> {
        match limit {
            Some(limit) => self.entries.iter().take(limit).cloned().collect(),
            None => self.entries.clone(),
        }
    }

    fn load(&mut self) {
        let Some(history_file) = &self.history_file else {
            self.entries.clear();
            return;
        };
        let Ok(contents) = fs::read_to_string(history_file) else {
            self.entries.clear();
            return;
        };
        match serde_json::from_str::<RecentTrackPayload>(&contents) {
            Ok(mut payload) => {
                payload.entries.truncate(self.max_entries);
                self.entries = payload.entries;
            }
            Err(_) => {
                self.entries.clear();
            }
        }
    }

    fn save(&self) -> Result<(), String> {
        let Some(history_file) = &self.history_file else {
            return Ok(());
        };
        if let Some(parent) = history_file.parent() {
            fs::create_dir_all(parent).map_err(|error| error.to_string())?;
        }
        let payload = RecentTrackPayload {
            entries: self
                .entries
                .iter()
                .take(self.max_entries)
                .cloned()
                .collect(),
        };
        let encoded = serde_json::to_string_pretty(&payload).map_err(|error| error.to_string())?;
        fs::write(history_file, encoded).map_err(|error| error.to_string())
    }
}

fn now_timestamp() -> String {
    OffsetDateTime::now_utc()
        .format(&Rfc3339)
        .unwrap_or_else(|_| fallback_timestamp())
}

fn fallback_timestamp() -> String {
    let seconds = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_secs())
        .unwrap_or_default();
    format!("1970-01-01T00:00:{:02}Z", seconds % 60)
}
