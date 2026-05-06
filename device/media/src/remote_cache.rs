use std::fs;
use std::io::{Read, Write};
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};

use filetime::{set_file_mtime, FileTime};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct CachedPlaybackAsset {
    pub path: String,
    pub cache_hit: bool,
}

pub trait RemoteAssetDownloader: Send + Sync {
    fn download(
        &self,
        media_url: &str,
        target_path: &Path,
        checksum_sha256: Option<&str>,
    ) -> Result<(), String>;
}

#[derive(Debug, Default)]
struct HttpRemoteAssetDownloader;

impl RemoteAssetDownloader for HttpRemoteAssetDownloader {
    fn download(
        &self,
        media_url: &str,
        target_path: &Path,
        checksum_sha256: Option<&str>,
    ) -> Result<(), String> {
        if let Some(parent) = target_path.parent() {
            fs::create_dir_all(parent).map_err(|error| error.to_string())?;
        }
        let request = ureq::get(media_url).set("User-Agent", "YoYoPod/remote-playback-cache");
        let response = request.call().map_err(|error| error.to_string())?;
        let mut reader = response.into_reader();
        let mut handle = fs::File::create(target_path).map_err(|error| error.to_string())?;
        let mut hash = Sha256::new();
        let mut buffer = [0u8; 64 * 1024];

        loop {
            let count = reader
                .read(&mut buffer)
                .map_err(|error| error.to_string())?;
            if count == 0 {
                break;
            }
            handle
                .write_all(&buffer[..count])
                .map_err(|error| error.to_string())?;
            hash.update(&buffer[..count]);
        }

        if let Some(expected) = checksum_sha256 {
            let actual = format!("{:x}", hash.finalize());
            if actual != expected {
                let _ = fs::remove_file(target_path);
                return Err("checksum_mismatch".to_string());
            }
        }

        Ok(())
    }
}

pub struct RemotePlaybackCache {
    root: PathBuf,
    max_bytes: u64,
    downloader: Box<dyn RemoteAssetDownloader>,
    prune_lock: Arc<Mutex<()>>,
}

impl RemotePlaybackCache {
    pub fn new(root: impl Into<PathBuf>, max_bytes: u64) -> Self {
        Self::with_downloader(root, max_bytes, Box::new(HttpRemoteAssetDownloader))
    }

    pub fn with_downloader(
        root: impl Into<PathBuf>,
        max_bytes: u64,
        downloader: Box<dyn RemoteAssetDownloader>,
    ) -> Self {
        let root = root.into();
        let _ = fs::create_dir_all(&root);
        Self {
            root,
            max_bytes: max_bytes.max(32 * 1024 * 1024),
            downloader,
            prune_lock: Arc::new(Mutex::new(())),
        }
    }

    pub fn prepare(
        &self,
        track_id: &str,
        media_url: &str,
        checksum_sha256: Option<&str>,
        extension: &str,
    ) -> Result<CachedPlaybackAsset, String> {
        let checksum_suffix = checksum_sha256.unwrap_or("nochecksum");
        let target_path = self.target_path_for(track_id, checksum_suffix, extension)?;

        if target_path.exists() {
            let _ = set_file_mtime(&target_path, FileTime::now());
            self.prune(std::slice::from_ref(&target_path))?;
            return Ok(CachedPlaybackAsset {
                path: target_path.display().to_string(),
                cache_hit: true,
            });
        }

        self.downloader
            .download(media_url, &target_path, checksum_sha256)?;
        self.prune(std::slice::from_ref(&target_path))?;
        Ok(CachedPlaybackAsset {
            path: target_path.display().to_string(),
            cache_hit: false,
        })
    }

    fn prune(&self, protected_paths: &[PathBuf]) -> Result<(), String> {
        let _guard = self
            .prune_lock
            .lock()
            .map_err(|_| "prune_lock".to_string())?;
        let protected = protected_paths
            .iter()
            .map(|path| path.canonicalize().unwrap_or_else(|_| path.clone()))
            .collect::<Vec<_>>();

        let mut files = fs::read_dir(&self.root)
            .map_err(|error| error.to_string())?
            .collect::<std::io::Result<Vec<_>>>()
            .map_err(|error| error.to_string())?
            .into_iter()
            .filter_map(|entry| {
                let path = entry.path();
                let stat = entry.metadata().ok()?;
                if !stat.is_file() {
                    return None;
                }
                let modified = stat.modified().ok()?;
                Some((path, modified, stat.len()))
            })
            .collect::<Vec<_>>();
        files.sort_by_key(|(_, modified, _)| *modified);

        let mut total_size = files.iter().map(|(_, _, size)| *size).sum::<u64>();
        for (path, _modified, size) in files {
            if total_size <= self.max_bytes {
                break;
            }
            let resolved = path.canonicalize().unwrap_or_else(|_| path.clone());
            if protected.iter().any(|protected| protected == &resolved) {
                continue;
            }
            if fs::remove_file(&path).is_ok() {
                total_size = total_size.saturating_sub(size);
            }
        }

        Ok(())
    }

    fn target_path_for(
        &self,
        track_id: &str,
        checksum_suffix: &str,
        extension: &str,
    ) -> Result<PathBuf, String> {
        let safe_track_id = sanitize_filename_component(track_id);
        let safe_checksum =
            sanitize_filename_component(&checksum_suffix[..checksum_suffix.len().min(16)]);
        let safe_extension = sanitize_extension(extension);
        let target_path = self
            .root
            .join(format!("{safe_track_id}-{safe_checksum}{safe_extension}"));

        let resolved_root = self
            .root
            .canonicalize()
            .unwrap_or_else(|_| self.root.clone());
        let resolved_target = target_path
            .parent()
            .unwrap_or(&self.root)
            .canonicalize()
            .unwrap_or_else(|_| target_path.parent().unwrap_or(&self.root).to_path_buf());
        if resolved_target != resolved_root {
            return Err("unsafe_cache_path".to_string());
        }
        Ok(target_path)
    }
}

fn sanitize_filename_component(value: &str) -> String {
    let normalized = value
        .trim()
        .chars()
        .map(|char| {
            if char.is_ascii_alphanumeric() || matches!(char, '.' | '_' | '-') {
                char
            } else {
                '-'
            }
        })
        .collect::<String>();
    normalized
        .trim_matches(&['.', '-'][..])
        .to_string()
        .if_empty("track")
}

fn sanitize_extension(value: &str) -> String {
    let mut normalized = value
        .trim()
        .chars()
        .filter(|char| char.is_ascii_alphanumeric() || *char == '.')
        .collect::<String>();
    if normalized.is_empty() {
        normalized = ".mp3".to_string();
    } else if !normalized.starts_with('.') {
        normalized = format!(".{normalized}");
    }
    normalized.chars().take(16).collect()
}

trait StringExt {
    fn if_empty(self, fallback: &str) -> String;
}

impl StringExt for String {
    fn if_empty(self, fallback: &str) -> String {
        if self.is_empty() {
            fallback.to_string()
        } else {
            self
        }
    }
}
