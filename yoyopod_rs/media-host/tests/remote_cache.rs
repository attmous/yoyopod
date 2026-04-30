use std::fs;
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};
use std::time::{SystemTime, UNIX_EPOCH};

use yoyopod_media_host::remote_cache::{
    CachedPlaybackAsset, RemoteAssetDownloader, RemotePlaybackCache,
};

fn temp_dir(test_name: &str) -> PathBuf {
    let unique = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("system time")
        .as_nanos();
    std::env::temp_dir().join(format!("yoyopod-media-cache-{test_name}-{unique}"))
}

#[derive(Debug, Default, Clone)]
struct FakeDownloader {
    calls: Arc<Mutex<Vec<String>>>,
}

impl RemoteAssetDownloader for FakeDownloader {
    fn download(
        &self,
        media_url: &str,
        target_path: &Path,
        _checksum_sha256: Option<&str>,
    ) -> Result<(), String> {
        self.calls
            .lock()
            .expect("calls")
            .push(media_url.to_string());
        fs::write(target_path, format!("downloaded:{media_url}")).map_err(|error| error.to_string())
    }
}

#[test]
fn prepare_downloads_asset_once_and_reuses_cache_hit() {
    let root = temp_dir("prepare");
    let downloader = FakeDownloader::default();
    let cache =
        RemotePlaybackCache::with_downloader(&root, 64 * 1024 * 1024, Box::new(downloader.clone()));

    let first = cache
        .prepare(
            "track-1",
            "https://media.example.test/track-1.mp3",
            None,
            ".mp3",
        )
        .expect("first prepare");
    let second = cache
        .prepare(
            "track-1",
            "https://media.example.test/track-1.mp3",
            None,
            ".mp3",
        )
        .expect("second prepare");

    assert_eq!(
        downloader.calls.lock().expect("calls").as_slice(),
        &["https://media.example.test/track-1.mp3".to_string()]
    );
    assert_eq!(
        first,
        CachedPlaybackAsset {
            path: second.path.clone(),
            cache_hit: false,
        }
    );
    assert_eq!(second.cache_hit, true);
}

#[test]
fn prepare_prunes_oldest_unprotected_file_when_cache_exceeds_limit() {
    let root = temp_dir("prune");
    fs::create_dir_all(&root).expect("cache root");
    fs::write(root.join("stale.mp3"), vec![0u8; 33 * 1024 * 1024]).expect("stale");

    let downloader = FakeDownloader::default();
    let cache = RemotePlaybackCache::with_downloader(&root, 32 * 1024 * 1024, Box::new(downloader));
    let prepared = cache
        .prepare(
            "track-2",
            "https://media.example.test/track-2.mp3",
            None,
            ".mp3",
        )
        .expect("prepare");

    assert!(Path::new(&prepared.path).exists());
    assert!(!root.join("stale.mp3").exists());
}
