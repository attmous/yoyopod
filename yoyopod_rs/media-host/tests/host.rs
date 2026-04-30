use std::collections::VecDeque;
use std::fs;
use std::path::PathBuf;
use std::sync::{Arc, Mutex};
use std::time::Duration;
use std::time::{SystemTime, UNIX_EPOCH};

use anyhow::{anyhow, Result};
use serde_json::{json, Value};
use yoyopod_media_host::config::MediaConfig;
use yoyopod_media_host::events::MediaRuntimeEvent;
use yoyopod_media_host::host::{
    MediaHost, MediaRuntime, MediaRuntimeFactory, MpvIpcTransport, MpvProcessController,
    MpvRuntime, MpvRuntimeStartupPolicy, PlaybackState, Track,
};

#[derive(Debug, Default, Clone)]
struct FakeRuntimeFactory {
    shared: Arc<Mutex<FakeRuntimeShared>>,
}

#[derive(Debug, Default)]
struct FakeRuntimeShared {
    commands: Vec<String>,
    started: usize,
    stopped: usize,
    connected: bool,
    current_track: Option<Track>,
    playback_state: PlaybackState,
    time_position_ms: i64,
    events: VecDeque<MediaRuntimeEvent>,
}

struct FakeRuntime {
    shared: Arc<Mutex<FakeRuntimeShared>>,
}

impl MediaRuntime for FakeRuntime {
    fn start(&mut self) -> anyhow::Result<()> {
        let mut shared = self.shared.lock().expect("shared");
        shared.started += 1;
        shared.connected = true;
        Ok(())
    }

    fn stop(&mut self) -> anyhow::Result<()> {
        let mut shared = self.shared.lock().expect("shared");
        shared.stopped += 1;
        shared.connected = false;
        Ok(())
    }

    fn is_connected(&self) -> bool {
        self.shared.lock().expect("shared").connected
    }

    fn play(&mut self) -> anyhow::Result<()> {
        self.shared
            .lock()
            .expect("shared")
            .commands
            .push("play".to_string());
        Ok(())
    }

    fn pause(&mut self) -> anyhow::Result<()> {
        self.shared
            .lock()
            .expect("shared")
            .commands
            .push("pause".to_string());
        Ok(())
    }

    fn stop_playback(&mut self) -> anyhow::Result<()> {
        self.shared
            .lock()
            .expect("shared")
            .commands
            .push("stop".to_string());
        Ok(())
    }

    fn next_track(&mut self) -> anyhow::Result<()> {
        self.shared
            .lock()
            .expect("shared")
            .commands
            .push("next".to_string());
        Ok(())
    }

    fn previous_track(&mut self) -> anyhow::Result<()> {
        self.shared
            .lock()
            .expect("shared")
            .commands
            .push("previous".to_string());
        Ok(())
    }

    fn set_volume(&mut self, volume: i32) -> anyhow::Result<()> {
        self.shared
            .lock()
            .expect("shared")
            .commands
            .push(format!("volume:{volume}"));
        Ok(())
    }

    fn get_volume(&mut self) -> anyhow::Result<Option<i32>> {
        Ok(Some(100))
    }

    fn set_audio_device(&mut self, device: &str) -> anyhow::Result<()> {
        self.shared
            .lock()
            .expect("shared")
            .commands
            .push(format!("device:{device}"));
        Ok(())
    }

    fn load_tracks(&mut self, uris: &[String]) -> anyhow::Result<()> {
        self.shared
            .lock()
            .expect("shared")
            .commands
            .push(format!("load_tracks:{}", uris.len()));
        Ok(())
    }

    fn load_playlist_file(&mut self, path: &str) -> anyhow::Result<()> {
        self.shared
            .lock()
            .expect("shared")
            .commands
            .push(format!("load_playlist:{path}"));
        Ok(())
    }

    fn drain_events(&mut self) -> anyhow::Result<Vec<MediaRuntimeEvent>> {
        let mut shared = self.shared.lock().expect("shared");
        Ok(shared.events.drain(..).collect())
    }

    fn current_track(&self) -> Option<Track> {
        self.shared.lock().expect("shared").current_track.clone()
    }

    fn playback_state(&self) -> PlaybackState {
        self.shared.lock().expect("shared").playback_state
    }

    fn time_position_ms(&self) -> i64 {
        self.shared.lock().expect("shared").time_position_ms
    }
}

impl MediaRuntimeFactory for FakeRuntimeFactory {
    fn build(&self, _config: &MediaConfig) -> anyhow::Result<Box<dyn MediaRuntime>> {
        Ok(Box::new(FakeRuntime {
            shared: Arc::clone(&self.shared),
        }))
    }
}

#[derive(Debug, Default)]
struct FakeMpvProcessState {
    spawn_calls: usize,
    stop_calls: usize,
    alive: bool,
}

#[derive(Debug, Default)]
struct FakeMpvProcess {
    shared: Arc<Mutex<FakeMpvProcessState>>,
}

impl MpvProcessController for FakeMpvProcess {
    fn spawn(&mut self) -> std::io::Result<()> {
        let mut shared = self.shared.lock().expect("process state");
        shared.spawn_calls += 1;
        shared.alive = true;
        Ok(())
    }

    fn stop(&mut self) -> std::io::Result<()> {
        let mut shared = self.shared.lock().expect("process state");
        shared.stop_calls += 1;
        shared.alive = false;
        Ok(())
    }

    fn is_alive(&self) -> bool {
        self.shared.lock().expect("process state").alive
    }
}

#[derive(Debug)]
struct FakeMpvIpcState {
    connect_calls: usize,
    disconnect_calls: usize,
    observe_calls: Vec<(String, i64)>,
    connected: bool,
}

#[derive(Debug)]
struct FakeMpvIpc {
    connect_results: VecDeque<Result<()>>,
    shared: Arc<Mutex<FakeMpvIpcState>>,
}

impl FakeMpvIpc {
    fn new(connect_results: Vec<Result<()>>) -> Self {
        Self {
            connect_results: connect_results.into(),
            shared: Arc::new(Mutex::new(FakeMpvIpcState {
                connect_calls: 0,
                disconnect_calls: 0,
                observe_calls: Vec::new(),
                connected: false,
            })),
        }
    }
}

impl MpvIpcTransport for FakeMpvIpc {
    fn connect(&mut self) -> Result<()> {
        let mut shared = self.shared.lock().expect("ipc state");
        shared.connect_calls += 1;
        let result = self.connect_results.pop_front().unwrap_or_else(|| Ok(()));
        shared.connected = result.is_ok();
        result
    }

    fn connected(&self) -> bool {
        self.shared.lock().expect("ipc state").connected
    }

    fn disconnect(&mut self) {
        let mut shared = self.shared.lock().expect("ipc state");
        shared.disconnect_calls += 1;
        shared.connected = false;
    }

    fn send_command(&mut self, args: &[Value], _timeout: Duration) -> Result<Value> {
        let command = args.first().and_then(Value::as_str).unwrap_or_default();
        let property = args.get(1).and_then(Value::as_str).unwrap_or_default();
        match (command, property) {
            ("get_property", "path") => Ok(json!({"error": "success", "data": Value::Null})),
            ("get_property", "metadata") => Ok(json!({"error": "success", "data": {}})),
            ("get_property", "duration") => Ok(json!({"error": "success", "data": Value::Null})),
            ("get_property", "media-title") => Ok(json!({"error": "success", "data": Value::Null})),
            ("get_property", "time-pos") => Ok(json!({"error": "success", "data": Value::Null})),
            _ => Ok(json!({"error": "success"})),
        }
    }

    fn observe_property(&mut self, name: &str, observe_id: i64) -> Result<()> {
        self.shared
            .lock()
            .expect("ipc state")
            .observe_calls
            .push((name.to_string(), observe_id));
        Ok(())
    }

    fn drain_events(&mut self) -> Result<Vec<Value>> {
        Ok(Vec::new())
    }
}

fn config() -> MediaConfig {
    let fixture_root = temp_dir("media-host");
    fs::create_dir_all(&fixture_root).expect("fixture root");
    fs::create_dir_all(fixture_root.join("Music")).expect("music dir");
    MediaConfig {
        music_dir: fixture_root.join("Music").display().to_string(),
        mpv_socket: "/tmp/yoyopod-mpv.sock".to_string(),
        mpv_binary: "mpv".to_string(),
        alsa_device: "default".to_string(),
        default_volume: 100,
        recent_tracks_file: fixture_root
            .join("recent_tracks.json")
            .display()
            .to_string(),
        remote_cache_dir: fixture_root.join("remote_cache").display().to_string(),
        remote_cache_max_bytes: 1024,
    }
}

fn temp_dir(test_name: &str) -> PathBuf {
    let unique = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("system time")
        .as_nanos();
    std::env::temp_dir().join(format!("yoyopod-media-host-{test_name}-{unique}"))
}

#[test]
fn start_builds_runtime_and_reports_connected_health() {
    let factory = FakeRuntimeFactory::default();
    let mut host = MediaHost::with_factory(Box::new(factory.clone()));
    host.configure(config());

    host.start_backend().expect("start");

    let shared = factory.shared.lock().expect("shared");
    assert_eq!(shared.started, 1);
    drop(shared);

    let health = host.health_payload();
    assert_eq!(health["configured"], true);
    assert_eq!(health["connected"], true);
    assert_eq!(health["backend_state"], "connected");
}

#[test]
fn drain_runtime_events_updates_track_and_playback_snapshot() {
    let factory = FakeRuntimeFactory::default();
    let mut host = MediaHost::with_factory(Box::new(factory.clone()));
    host.configure(config());
    host.start_backend().expect("start");

    {
        let mut shared = factory.shared.lock().expect("shared");
        let current_track = Track {
            uri: "/music/alpha.ogg".to_string(),
            name: "Alpha".to_string(),
            artists: vec!["Artist".to_string()],
            album: "Sampler".to_string(),
            length_ms: 12_500,
            track_no: Some(3),
        };
        shared.current_track = Some(current_track.clone());
        shared.playback_state = PlaybackState::Playing;
        shared.time_position_ms = 8_000;
        shared
            .events
            .push_back(MediaRuntimeEvent::TrackChanged(Some(current_track)));
        shared
            .events
            .push_back(MediaRuntimeEvent::PlaybackStateChanged(
                PlaybackState::Playing,
            ));
    }

    let events = host.drain_runtime_events().expect("events");

    assert_eq!(events.len(), 2);
    let snapshot = host.snapshot_payload();
    assert_eq!(snapshot["playback_state"], "playing");
    assert_eq!(snapshot["time_position_ms"], 8000);
    assert_eq!(snapshot["current_track"]["name"], "Alpha");
}

#[test]
fn transport_commands_delegate_to_runtime() {
    let factory = FakeRuntimeFactory::default();
    let mut host = MediaHost::with_factory(Box::new(factory.clone()));
    host.configure(config());

    host.play().expect("play");
    host.pause().expect("pause");
    host.load_tracks(&["/music/a.ogg".to_string(), "/music/b.ogg".to_string()])
        .expect("load tracks");
    host.set_audio_device("alsa/default").expect("device");

    let shared = factory.shared.lock().expect("shared");
    assert_eq!(shared.started, 1);
    assert_eq!(
        shared.commands,
        vec![
            "play".to_string(),
            "pause".to_string(),
            "load_tracks:2".to_string(),
            "device:alsa/default".to_string(),
        ]
    );
}

#[test]
fn shuffle_all_delegates_local_tracks_to_runtime() {
    let config = config();
    let music_dir = PathBuf::from(&config.music_dir);
    fs::write(music_dir.join("alpha.mp3"), b"a").expect("alpha");
    fs::write(music_dir.join("beta.flac"), b"b").expect("beta");

    let factory = FakeRuntimeFactory::default();
    let mut host = MediaHost::with_factory(Box::new(factory.clone()));
    host.configure(config);

    host.shuffle_all().expect("shuffle");

    let shared = factory.shared.lock().expect("shared");
    assert_eq!(shared.started, 1);
    assert_eq!(shared.commands, vec!["load_tracks:2".to_string()]);
}

#[test]
fn runtime_track_change_records_recent_local_track() {
    let config = config();
    let music_dir = PathBuf::from(&config.music_dir);
    let track_uri = music_dir.join("alpha.mp3");
    fs::write(&track_uri, b"a").expect("alpha");

    let factory = FakeRuntimeFactory::default();
    let mut host = MediaHost::with_factory(Box::new(factory.clone()));
    host.configure(config);
    host.start_backend().expect("start");

    {
        let mut shared = factory.shared.lock().expect("shared");
        let current_track = Track {
            uri: track_uri.display().to_string(),
            name: "Alpha".to_string(),
            artists: vec!["Artist".to_string()],
            album: "Sampler".to_string(),
            length_ms: 12_500,
            track_no: Some(3),
        };
        shared.current_track = Some(current_track.clone());
        shared
            .events
            .push_back(MediaRuntimeEvent::TrackChanged(Some(current_track)));
    }

    host.drain_runtime_events().expect("events");
    let recents = host.list_recent_tracks(None).expect("recent tracks");

    assert_eq!(recents.len(), 1);
    assert_eq!(recents[0].title, "Alpha");
}

#[test]
fn mpv_runtime_retries_connect_until_ipc_socket_is_ready() {
    let process = FakeMpvProcess::default();
    let ipc = FakeMpvIpc::new(vec![
        Err(anyhow!("No such file or directory (os error 2)")),
        Err(anyhow!("No such file or directory (os error 2)")),
        Ok(()),
    ]);
    let process_state = Arc::clone(&process.shared);
    let ipc_state = Arc::clone(&ipc.shared);
    let mut runtime = MpvRuntime::with_clients(
        Box::new(process),
        Box::new(ipc),
        MpvRuntimeStartupPolicy {
            connect_timeout: Duration::from_millis(50),
            connect_delay: Duration::from_millis(1),
        },
    );

    runtime.start().expect("start");

    assert!(runtime.is_connected());
    let process = process_state.lock().expect("process state");
    assert_eq!(process.spawn_calls, 1);
    assert_eq!(process.stop_calls, 0);
    let ipc = ipc_state.lock().expect("ipc state");
    assert_eq!(ipc.connect_calls, 3);
    assert_eq!(ipc.observe_calls.len(), 7);
}
