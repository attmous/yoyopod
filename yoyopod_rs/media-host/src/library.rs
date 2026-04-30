use std::fs;
use std::path::{Path, PathBuf};

use anyhow::Result;
use rand::seq::SliceRandom;
use serde::{Deserialize, Serialize};

const AUDIO_EXTENSIONS: [&str; 6] = [".mp3", ".flac", ".ogg", ".wav", ".m4a", ".opus"];
const LEGACY_PLAYLIST_SCHEMES: [&str; 1] = ["m3u:"];
const LEGACY_TRACK_SCHEMES: [&str; 2] = ["local:", "file:"];

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct LocalLibraryItem {
    pub key: String,
    pub title: String,
    pub subtitle: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct PlaylistEntry {
    pub uri: String,
    pub name: String,
    pub track_count: usize,
}

#[derive(Debug, Clone)]
pub struct LocalMusicLibrary {
    music_dir: PathBuf,
}

impl LocalMusicLibrary {
    pub fn new(music_dir: impl Into<PathBuf>) -> Self {
        Self {
            music_dir: music_dir.into(),
        }
    }

    pub fn is_local_track_uri(&self, uri: &str) -> bool {
        if LEGACY_TRACK_SCHEMES
            .iter()
            .any(|scheme| uri.starts_with(scheme))
        {
            return true;
        }
        Path::new(uri).starts_with(&self.music_dir)
    }

    pub fn is_local_playlist_uri(&self, uri: &str) -> bool {
        if LEGACY_PLAYLIST_SCHEMES
            .iter()
            .any(|scheme| uri.starts_with(scheme))
        {
            return true;
        }
        let path = Path::new(uri);
        path.extension()
            .and_then(|value| value.to_str())
            .map(|value| value.eq_ignore_ascii_case("m3u"))
            .unwrap_or(false)
            && path.starts_with(&self.music_dir)
    }

    pub fn menu_items(&self) -> Vec<LocalLibraryItem> {
        vec![
            LocalLibraryItem {
                key: "playlists".to_string(),
                title: "Playlists".to_string(),
                subtitle: "Saved mixes".to_string(),
            },
            LocalLibraryItem {
                key: "recent".to_string(),
                title: "Recent".to_string(),
                subtitle: "Played lately".to_string(),
            },
            LocalLibraryItem {
                key: "shuffle".to_string(),
                title: "Shuffle".to_string(),
                subtitle: "Start something fun".to_string(),
            },
        ]
    }

    pub fn list_playlists(&self, fetch_track_counts: bool) -> Result<Vec<PlaylistEntry>> {
        let mut playlists = Vec::new();
        if !self.music_dir.is_dir() {
            return Ok(playlists);
        }

        let mut paths = Vec::new();
        collect_files_with_extension(&self.music_dir, "m3u", &mut paths)?;
        paths.sort();

        for path in paths {
            let track_count = if fetch_track_counts {
                count_playlist_tracks(&path)?
            } else {
                0
            };
            playlists.push(PlaylistEntry {
                uri: path.display().to_string(),
                name: path
                    .file_stem()
                    .and_then(|value| value.to_str())
                    .unwrap_or_default()
                    .to_string(),
                track_count,
            });
        }
        Ok(playlists)
    }

    pub fn playlist_count(&self) -> Result<usize> {
        Ok(self.list_playlists(false)?.len())
    }

    pub fn collect_local_track_uris(&self) -> Result<Vec<String>> {
        let mut tracks_by_extension: Vec<Vec<String>> =
            AUDIO_EXTENSIONS.iter().map(|_| Vec::new()).collect();
        if !self.music_dir.is_dir() {
            return Ok(Vec::new());
        }

        collect_track_uris(&self.music_dir, &mut tracks_by_extension)?;

        Ok(tracks_by_extension.into_iter().flatten().collect())
    }

    pub fn shuffle_track_uris(&self) -> Result<Vec<String>> {
        let mut track_uris = self.collect_local_track_uris()?;
        track_uris.shuffle(&mut rand::thread_rng());
        Ok(track_uris)
    }
}

fn collect_files_with_extension(
    root: &Path,
    extension: &str,
    output: &mut Vec<PathBuf>,
) -> Result<()> {
    let mut entries = fs::read_dir(root)?.collect::<std::io::Result<Vec<_>>>()?;
    entries.sort_by_key(|entry| entry.file_name());

    for entry in entries {
        let path = entry.path();
        if path.is_dir() {
            collect_files_with_extension(&path, extension, output)?;
            continue;
        }
        if path
            .extension()
            .and_then(|value| value.to_str())
            .map(|value| value.eq_ignore_ascii_case(extension))
            .unwrap_or(false)
        {
            output.push(path);
        }
    }

    Ok(())
}

fn collect_track_uris(root: &Path, tracks_by_extension: &mut [Vec<String>]) -> Result<()> {
    let mut entries = fs::read_dir(root)?.collect::<std::io::Result<Vec<_>>>()?;
    entries.sort_by_key(|entry| entry.file_name());

    for entry in entries {
        let path = entry.path();
        if path.is_dir() {
            collect_track_uris(&path, tracks_by_extension)?;
            continue;
        }
        let extension = path
            .extension()
            .and_then(|value| value.to_str())
            .map(|value| format!(".{}", value.to_ascii_lowercase()));
        let Some(extension) = extension else {
            continue;
        };
        if let Some(index) = AUDIO_EXTENSIONS
            .iter()
            .position(|value| *value == extension)
        {
            tracks_by_extension[index].push(path.display().to_string());
        }
    }

    Ok(())
}

fn count_playlist_tracks(path: &Path) -> Result<usize> {
    let contents = fs::read_to_string(path)?;
    Ok(contents
        .lines()
        .filter(|line| {
            let trimmed = line.trim();
            !trimmed.is_empty() && !trimmed.starts_with('#')
        })
        .count())
}
