use std::fs;
use std::path::{Path, PathBuf};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct MediaImportRequest {
    pub track_id: String,
    pub title: Option<String>,
    pub filename: Option<String>,
}

#[derive(Debug, Clone)]
pub struct RemoteMediaLibrary {
    music_dir: PathBuf,
}

impl RemoteMediaLibrary {
    pub fn new(music_dir: impl Into<PathBuf>) -> Self {
        Self {
            music_dir: music_dir.into(),
        }
    }

    pub fn persist_asset(
        &self,
        request: &MediaImportRequest,
        cached_path: &Path,
    ) -> Result<PathBuf, String> {
        let uploads_dir = self.music_dir.join("dashboard_uploads");
        fs::create_dir_all(&uploads_dir).map_err(|error| error.to_string())?;

        let preferred_name = request
            .filename
            .as_deref()
            .or(request.title.as_deref())
            .unwrap_or_default();
        let source_suffix = cached_path
            .extension()
            .and_then(|value| value.to_str())
            .map(|value| format!(".{value}"))
            .unwrap_or_else(|| ".mp3".to_string());
        let display_stem = safe_media_stem(preferred_name, &request.track_id);
        let unique_stem = safe_media_stem(&request.track_id, "track");
        let safe_name = if display_stem == unique_stem {
            format!("{display_stem}{}", safe_media_suffix(&source_suffix))
        } else {
            format!(
                "{display_stem}-{unique_stem}{}",
                safe_media_suffix(&source_suffix)
            )
        };
        let target_path = uploads_dir.join(safe_name);

        fs::copy(cached_path, &target_path).map_err(|error| error.to_string())?;
        self.append_dashboard_uploads_playlist(&target_path)?;
        Ok(target_path)
    }

    fn append_dashboard_uploads_playlist(&self, target_path: &Path) -> Result<(), String> {
        let playlist_path = self.music_dir.join("Dashboard Uploads.m3u");
        if let Some(parent) = playlist_path.parent() {
            fs::create_dir_all(parent).map_err(|error| error.to_string())?;
        }

        let entry = target_path.display().to_string();
        let mut existing_entries = if playlist_path.exists() {
            fs::read_to_string(&playlist_path)
                .map(|contents| {
                    contents
                        .lines()
                        .map(str::trim)
                        .filter(|line| !line.is_empty())
                        .map(ToString::to_string)
                        .collect::<Vec<_>>()
                })
                .unwrap_or_default()
        } else {
            Vec::new()
        };

        if existing_entries.iter().any(|value| value == &entry) {
            return Ok(());
        }

        existing_entries.push(entry);
        fs::write(&playlist_path, existing_entries.join("\n")).map_err(|error| error.to_string())
    }
}

fn safe_media_stem(value: &str, default_stem: &str) -> String {
    let source = if value.trim().is_empty() {
        default_stem
    } else {
        Path::new(value)
            .file_stem()
            .and_then(|stem| stem.to_str())
            .unwrap_or(default_stem)
    };
    let normalized = source
        .chars()
        .map(|char| {
            if char.is_ascii_alphanumeric() || matches!(char, '-' | '_') {
                char
            } else {
                '-'
            }
        })
        .collect::<String>()
        .trim_matches(&['.', '-', '_'][..])
        .to_string();
    if normalized.is_empty() {
        safe_media_stem(default_stem, "track")
    } else {
        normalized
    }
}

fn safe_media_suffix(suffix: &str) -> String {
    let normalized = suffix
        .chars()
        .filter(|char| char.is_ascii_alphanumeric() || *char == '.')
        .collect::<String>();
    let prefixed = if normalized.starts_with('.') {
        normalized
    } else {
        format!(".{normalized}")
    };
    prefixed.chars().take(16).collect()
}
