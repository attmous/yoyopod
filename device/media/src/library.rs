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
    pub tracks: Vec<PlaylistTrackEntry>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct PlaylistTrackEntry {
    pub uri: String,
    pub title: String,
    pub subtitle: String,
}

#[derive(Debug, Clone)]
pub struct LocalMusicLibrary {
    music_dir: PathBuf,
    playlists: Vec<PlaylistEntry>,
}

impl LocalMusicLibrary {
    pub fn new(music_dir: impl Into<PathBuf>) -> Self {
        Self {
            music_dir: music_dir.into(),
            playlists: Vec::new(),
        }
    }

    pub fn open(music_dir: impl Into<PathBuf>) -> Result<Self> {
        let mut library = Self::new(music_dir);
        library.refresh()?;
        Ok(library)
    }

    pub fn refresh(&mut self) -> Result<()> {
        self.playlists = scan_playlists(&self.music_dir)?;
        Ok(())
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
        Ok(self
            .playlists
            .iter()
            .cloned()
            .map(|mut playlist| {
                if !fetch_track_counts {
                    playlist.track_count = 0;
                    playlist.tracks.clear();
                }
                playlist
            })
            .collect())
    }

    pub fn playlist_count(&self) -> Result<usize> {
        Ok(self.playlists.len())
    }

    pub fn playlist(&self, uri: &str) -> Option<&PlaylistEntry> {
        self.playlists.iter().find(|playlist| playlist.uri == uri)
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

fn scan_playlists(music_dir: &Path) -> Result<Vec<PlaylistEntry>> {
    let mut playlists = Vec::new();
    if !music_dir.is_dir() {
        return Ok(playlists);
    }

    let music_root = fs::canonicalize(music_dir)?;
    let mut paths = Vec::new();
    collect_files_with_extension(&music_root, "m3u", &mut paths)?;
    paths.sort();

    for path in paths {
        let tracks = read_playlist_tracks(&path, &music_root)?;
        playlists.push(PlaylistEntry {
            uri: path.display().to_string(),
            name: path
                .file_stem()
                .and_then(|value| value.to_str())
                .unwrap_or_default()
                .to_string(),
            track_count: tracks.len(),
            tracks,
        });
    }
    Ok(playlists)
}

fn read_playlist_tracks(path: &Path, music_root: &Path) -> Result<Vec<PlaylistTrackEntry>> {
    let contents = fs::read_to_string(path)?;
    let playlist_dir = path.parent().unwrap_or(music_root);
    let mut tracks = Vec::new();
    let mut pending_extinf: Option<(String, String)> = None;

    for line in contents.lines() {
        let trimmed = line.trim().trim_start_matches('\u{feff}');
        if trimmed.is_empty() {
            continue;
        }
        if let Some(value) = trimmed.strip_prefix("#EXTINF:") {
            pending_extinf = parse_extinf(value);
            continue;
        }
        if trimmed.starts_with('#') {
            continue;
        }

        let entry_path = Path::new(trimmed);
        let resolved = if entry_path.is_absolute() {
            entry_path.to_path_buf()
        } else {
            playlist_dir.join(entry_path)
        };
        let Ok(canonical) = fs::canonicalize(&resolved) else {
            pending_extinf = None;
            continue;
        };
        if !canonical.starts_with(music_root) || !canonical.is_file() {
            pending_extinf = None;
            continue;
        }

        let fallback_title = compact_file_title(
            canonical
                .file_stem()
                .and_then(|value| value.to_str())
                .unwrap_or("Unknown Track"),
        );
        let (extended_title, subtitle) = pending_extinf
            .take()
            .unwrap_or_else(|| (fallback_title.clone(), "--:--".to_string()));
        let title = if extended_title.chars().count() <= 28 {
            extended_title
        } else {
            fallback_title
        };
        tracks.push(PlaylistTrackEntry {
            uri: canonical.display().to_string(),
            title,
            subtitle,
        });
    }

    Ok(tracks)
}

fn parse_extinf(value: &str) -> Option<(String, String)> {
    let (seconds, title) = value.split_once(',')?;
    let title = title.trim();
    if title.is_empty() {
        return None;
    }
    let seconds = seconds.trim().parse::<i64>().ok().unwrap_or(-1);
    let subtitle = if seconds > 0 {
        format_duration(seconds)
    } else {
        "--:--".to_string()
    };
    Some((title.to_string(), subtitle))
}

fn format_duration(seconds: i64) -> String {
    format!("{}:{:02}", seconds / 60, seconds % 60)
}

fn compact_file_title(title: &str) -> String {
    title
        .split_once(" - ")
        .filter(|(prefix, _)| {
            !prefix.is_empty() && prefix.chars().all(|value| value.is_ascii_digit())
        })
        .map(|(_, title)| title.to_string())
        .unwrap_or_else(|| title.to_string())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::{SystemTime, UNIX_EPOCH};

    fn temp_music_dir() -> PathBuf {
        let suffix = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("clock")
            .as_nanos();
        std::env::temp_dir().join(format!("yoyopod-media-library-{suffix}"))
    }

    #[test]
    fn catalog_exposes_track_counts_and_resolved_tracks() {
        let root = temp_music_dir();
        let album = root.join("Open Classics");
        fs::create_dir_all(&album).unwrap();
        fs::write(album.join("01 - Chaconne.mp3"), b"audio").unwrap();
        fs::write(album.join("02 - March.mp3"), b"audio").unwrap();
        fs::write(
            root.join("Open Classics.m3u"),
            "#EXTM3U\n#EXTINF:332,Chaconne\nOpen Classics/01 - Chaconne.mp3\nOpen Classics/02 - March.mp3\n",
        )
        .unwrap();

        let library = LocalMusicLibrary::open(&root).unwrap();
        let playlists = library.list_playlists(true).unwrap();
        assert_eq!(playlists.len(), 1);
        assert_eq!(playlists[0].track_count, 2);
        assert_eq!(playlists[0].tracks[0].title, "Chaconne");
        assert_eq!(playlists[0].tracks[0].subtitle, "5:32");
        assert_eq!(playlists[0].tracks[1].title, "March");
        assert_eq!(playlists[0].tracks[1].subtitle, "--:--");
        assert!(
            Path::new(&playlists[0].tracks[0].uri).starts_with(fs::canonicalize(&root).unwrap())
        );

        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn unknown_extinf_duration_stays_unknown_and_long_titles_use_the_filename() {
        let root = temp_music_dir();
        fs::create_dir_all(&root).unwrap();
        fs::write(root.join("01 - Chaconne.mp3"), b"audio").unwrap();
        fs::write(
            root.join("Holst.m3u"),
            "#EXTM3U\n#EXTINF:-1,Gustav Holst - First Suite in E-flat - I. Chaconne\n01 - Chaconne.mp3\n",
        )
        .unwrap();

        let library = LocalMusicLibrary::open(&root).unwrap();
        let track = &library.list_playlists(true).unwrap()[0].tracks[0];
        assert_eq!(track.title, "Chaconne");
        assert_eq!(track.subtitle, "--:--");

        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn catalog_ignores_missing_and_outside_tracks() {
        let root = temp_music_dir();
        let outside = temp_music_dir();
        fs::create_dir_all(&root).unwrap();
        fs::create_dir_all(&outside).unwrap();
        let outside_track = outside.join("outside.mp3");
        fs::write(&outside_track, b"audio").unwrap();
        fs::write(
            root.join("Safe.m3u"),
            format!("missing.mp3\n{}\n", outside_track.display()),
        )
        .unwrap();

        let library = LocalMusicLibrary::open(&root).unwrap();
        let playlists = library.list_playlists(true).unwrap();
        assert_eq!(playlists[0].track_count, 0);
        assert!(playlists[0].tracks.is_empty());

        fs::remove_dir_all(root).unwrap();
        fs::remove_dir_all(outside).unwrap();
    }
}
