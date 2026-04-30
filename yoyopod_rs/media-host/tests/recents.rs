use std::path::PathBuf;
use std::time::{SystemTime, UNIX_EPOCH};

use yoyopod_media_host::models::Track;
use yoyopod_media_host::recents::RecentTrackStore;

fn temp_file(test_name: &str) -> PathBuf {
    let unique = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("system time")
        .as_nanos();
    std::env::temp_dir().join(format!("yoyopod-media-{test_name}-{unique}.json"))
}

fn track(uri: &str, name: &str) -> Track {
    Track {
        uri: uri.to_string(),
        name: name.to_string(),
        artists: vec!["Artist".to_string()],
        album: "Album".to_string(),
        length_ms: 1_000,
        track_no: Some(1),
    }
}

#[test]
fn recent_store_deduplicates_and_persists_entries() {
    let history_file = temp_file("recent-store");
    let mut store = RecentTrackStore::open(&history_file, 3);

    store
        .record_track(&track("/music/first.mp3", "First"))
        .expect("record first");
    store
        .record_track(&track("/music/second.flac", "Second"))
        .expect("record second");
    store
        .record_track(&track("/music/first.mp3", "First"))
        .expect("record duplicate");

    let reloaded = RecentTrackStore::open(&history_file, 3);
    let titles = reloaded
        .list_recent(None)
        .into_iter()
        .map(|entry| entry.title)
        .collect::<Vec<_>>();

    assert_eq!(titles, vec!["First".to_string(), "Second".to_string()]);
}

#[test]
fn recent_entry_subtitle_matches_python_contract() {
    let history_file = temp_file("recent-subtitle");
    let mut store = RecentTrackStore::open(&history_file, 3);
    store
        .record_track(&track("/music/alpha.mp3", "Alpha"))
        .expect("record alpha");

    let entry = store.list_recent(Some(1)).remove(0);
    assert_eq!(entry.subtitle(), "Artist - Album");
}
