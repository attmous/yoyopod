use std::fs;
use std::path::PathBuf;
use std::time::{SystemTime, UNIX_EPOCH};

use yoyopod_media_host::remote_media::{MediaImportRequest, RemoteMediaLibrary};

fn temp_dir(test_name: &str) -> PathBuf {
    let unique = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("system time")
        .as_nanos();
    std::env::temp_dir().join(format!("yoyopod-media-import-{test_name}-{unique}"))
}

#[test]
fn import_asset_persists_dashboard_upload_and_playlist_entry() {
    let music_dir = temp_dir("import");
    let cached_path = music_dir.join("cache-track.mp3");
    fs::create_dir_all(&music_dir).expect("music dir");
    fs::write(&cached_path, b"audio").expect("cached");

    let library = RemoteMediaLibrary::new(&music_dir);
    let imported = library
        .persist_asset(
            &MediaImportRequest {
                track_id: "track-7".to_string(),
                title: Some("Track Seven".to_string()),
                filename: None,
            },
            &cached_path,
        )
        .expect("import");

    assert!(imported.exists());
    assert!(imported.ends_with("Track-Seven-track-7.mp3"));
    let playlist = music_dir.join("Dashboard Uploads.m3u");
    assert!(playlist.exists());
    let playlist_text = fs::read_to_string(playlist).expect("playlist");
    assert!(playlist_text.contains(imported.display().to_string().as_str()));
}

#[test]
fn import_asset_keeps_distinct_files_for_shared_titles() {
    let music_dir = temp_dir("import-distinct");
    let cached_path = music_dir.join("cache-track.mp3");
    fs::create_dir_all(&music_dir).expect("music dir");
    fs::write(&cached_path, b"audio").expect("cached");

    let library = RemoteMediaLibrary::new(&music_dir);
    let first = library
        .persist_asset(
            &MediaImportRequest {
                track_id: "track-10".to_string(),
                title: Some("Shared Name".to_string()),
                filename: None,
            },
            &cached_path,
        )
        .expect("first import");
    let second = library
        .persist_asset(
            &MediaImportRequest {
                track_id: "track-11".to_string(),
                title: Some("Shared Name".to_string()),
                filename: None,
            },
            &cached_path,
        )
        .expect("second import");

    assert_ne!(first, second);
    assert!(first.ends_with("Shared-Name-track-10.mp3"));
    assert!(second.ends_with("Shared-Name-track-11.mp3"));
}
