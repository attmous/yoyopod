use std::fs;
use std::path::PathBuf;
use std::time::{SystemTime, UNIX_EPOCH};

use yoyopod_media_host::library::LocalMusicLibrary;

fn temp_dir(test_name: &str) -> PathBuf {
    let unique = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("system time")
        .as_nanos();
    std::env::temp_dir().join(format!("yoyopod-media-{test_name}-{unique}"))
}

#[test]
fn list_playlists_counts_tracks_and_returns_sorted_names() {
    let music_dir = temp_dir("playlists");
    fs::create_dir_all(music_dir.join("sets")).expect("create music dir");
    fs::write(
        music_dir.join("sets/alpha.m3u"),
        "#EXTM3U\ntrack-a.mp3\ntrack-b.mp3\n",
    )
    .expect("write alpha");
    fs::write(music_dir.join("sets/beta.m3u"), "#EXTM3U\n#comment\n").expect("write beta");

    let library = LocalMusicLibrary::new(&music_dir);
    let playlists = library.list_playlists(true).expect("playlists");

    assert_eq!(playlists.len(), 2);
    assert_eq!(playlists[0].name, "alpha");
    assert_eq!(playlists[0].track_count, 2);
    assert_eq!(playlists[1].name, "beta");
    assert_eq!(playlists[1].track_count, 0);
}

#[test]
fn collect_local_track_uris_uses_extension_bucket_order() {
    let music_dir = temp_dir("track-order");
    fs::create_dir_all(music_dir.join("Albums")).expect("create albums");
    fs::create_dir_all(music_dir.join("Singles")).expect("create singles");
    fs::write(music_dir.join("Singles/alpha.mp3"), b"a").expect("write mp3");
    fs::write(music_dir.join("Albums/bravo.flac"), b"b").expect("write flac");
    fs::write(music_dir.join("charlie.opus"), b"c").expect("write opus");
    fs::write(music_dir.join("ignore.txt"), b"skip").expect("write ignore");

    let library = LocalMusicLibrary::new(&music_dir);
    let track_uris = library.collect_local_track_uris().expect("track uris");

    assert_eq!(
        track_uris,
        vec![
            music_dir
                .join("Singles")
                .join("alpha.mp3")
                .display()
                .to_string(),
            music_dir
                .join("Albums")
                .join("bravo.flac")
                .display()
                .to_string(),
            music_dir.join("charlie.opus").display().to_string(),
        ]
    );
}

#[test]
fn shuffle_track_uris_keeps_local_membership() {
    let music_dir = temp_dir("shuffle");
    fs::create_dir_all(&music_dir).expect("create music dir");
    fs::write(music_dir.join("alpha.mp3"), b"a").expect("write alpha");
    fs::write(music_dir.join("beta.flac"), b"b").expect("write beta");
    fs::write(music_dir.join("gamma.ogg"), b"c").expect("write gamma");

    let library = LocalMusicLibrary::new(&music_dir);
    let mut shuffled = library.shuffle_track_uris().expect("shuffle");
    let mut expected = vec![
        music_dir.join("alpha.mp3").display().to_string(),
        music_dir.join("beta.flac").display().to_string(),
        music_dir.join("gamma.ogg").display().to_string(),
    ];
    shuffled.sort();
    expected.sort();

    assert_eq!(shuffled, expected);
}
