use std::thread;
use std::time::{Duration, Instant};

use anyhow::{anyhow, Result};
use serde_json::{json, Map, Value};

use crate::config::MediaConfig;
use crate::events::{MediaRuntimeEvent, MpvEvent};
use crate::library::{LocalLibraryItem, LocalMusicLibrary, PlaylistEntry};
use crate::models::duration_ms;
use crate::mpv_ipc::MpvIpcClient;
use crate::mpv_process::MpvProcess;
use crate::recents::{RecentTrackEntry, RecentTrackStore};
use crate::remote_cache::{CachedPlaybackAsset, RemotePlaybackCache};
use crate::remote_media::{MediaImportRequest, RemoteMediaLibrary};

#[cfg(test)]
mod interruption_tests {
    use super::*;
    use std::sync::{Arc, Mutex};
    struct Process(Arc<Mutex<Vec<String>>>);
    impl MpvProcessController for Process {
        fn spawn(&mut self) -> std::io::Result<()> {
            self.0.lock().unwrap().push("spawn".into());
            Ok(())
        }
        fn stop(&mut self) -> std::io::Result<()> {
            self.0.lock().unwrap().push("kill+wait".into());
            Ok(())
        }
        fn is_alive(&self) -> bool {
            true
        }
    }
    struct Ipc(Arc<Mutex<Vec<Vec<Value>>>>, bool);
    impl MpvIpcTransport for Ipc {
        fn connect(&mut self) -> Result<()> {
            self.1 = true;
            Ok(())
        }
        fn connected(&self) -> bool {
            self.1
        }
        fn disconnect(&mut self) {
            self.1 = false;
        }
        fn send_command(&mut self, args: &[Value], _: Duration) -> Result<Value> {
            anyhow::ensure!(self.1, "IPC disconnected");
            self.0.lock().unwrap().push(args.to_vec());
            let data = match args.get(1).and_then(Value::as_str) {
                Some("playlist") => {
                    json!([{"filename":"a.mp3","current":true},{"filename":"b.mp3"}])
                }
                Some("time-pos") => json!(12.0),
                Some("path") => json!("a.mp3"),
                _ => Value::Null,
            };
            Ok(json!({"error":"success","data":data}))
        }
        fn observe_property(&mut self, _: &str, _: i64) -> Result<()> {
            Ok(())
        }
        fn drain_events(&mut self) -> Result<Vec<Value>> {
            Ok(vec![])
        }
    }
    #[test]
    fn call_suspension_releases_process_preserving_music_selection() {
        let log = Arc::new(Mutex::new(Vec::new()));
        let commands = Arc::new(Mutex::new(Vec::new()));
        let mut runtime = MpvRuntime::with_clients(
            Box::new(Process(log.clone())),
            Box::new(Ipc(commands.clone(), true)),
            Default::default(),
        );
        let track = Track {
            uri: "a.mp3".into(),
            name: "A".into(),
            ..Default::default()
        };
        runtime.current_track = Some(track.clone());
        runtime.cached_path = Some(track.uri.clone());
        runtime.cached_time_position_ms = 12_000;
        runtime.playback_state = PlaybackState::Playing;
        runtime.connected = true;
        runtime.suspend_for_call().unwrap();
        assert_eq!(
            *log.lock().unwrap(),
            vec!["kill+wait"],
            "pause must physically release ALSA owner"
        );
        assert_eq!(runtime.current_track(), Some(track));
        assert_eq!(runtime.time_position_ms(), 12_000);
        assert_eq!(runtime.playback_state(), PlaybackState::Paused);
        runtime.drain_events().unwrap();
        assert_eq!(*log.lock().unwrap(), vec!["kill+wait"]);
        assert_eq!(
            runtime.suspended.as_ref().unwrap().0,
            vec!["a.mp3", "b.mp3"]
        );
        commands.lock().unwrap().clear();
        runtime.set_audio_device("alsa/reconnected").unwrap();
        runtime.set_volume(42).unwrap();
        assert!(
            commands.lock().unwrap().is_empty(),
            "route update cannot reopen suspended audio"
        );
        runtime.play().unwrap();
        assert_eq!(*log.lock().unwrap(), vec!["kill+wait", "spawn"]);
        assert!(!commands.lock().unwrap().contains(&vec![
            json!("set_property"),
            json!("pause"),
            json!(false)
        ]));
        runtime.handle_raw_event(json!({"event":"file-loaded"}));
        let cmds = commands.lock().unwrap();
        let seek = cmds
            .iter()
            .position(|c| c.first() == Some(&json!("seek")))
            .unwrap();
        let unpause = cmds
            .iter()
            .position(|c| *c == vec![json!("set_property"), json!("pause"), json!(false)])
            .unwrap();
        assert!(
            seek < unpause,
            "seek retained position before releasing pause"
        );
        assert_eq!(runtime.time_position_ms(), 12_000);
    }
    fn suspended_runtime() -> (MpvRuntime, Arc<Mutex<Vec<Vec<Value>>>>) {
        let commands = Arc::new(Mutex::new(Vec::new()));
        let mut runtime = MpvRuntime::with_clients(
            Box::new(Process(Default::default())),
            Box::new(Ipc(commands.clone(), true)),
            Default::default(),
        );
        runtime.connected = true;
        runtime.suspend_for_call().unwrap();
        commands.lock().unwrap().clear();
        (runtime, commands)
    }
    #[test]
    fn suspended_stop_then_play_or_reselection_reconnects() {
        for select_new in [false, true] {
            let (mut runtime, _) = suspended_runtime();
            runtime.stop_playback().unwrap();
            let result = if select_new {
                runtime.load_tracks(&["new.mp3".into()])
            } else {
                runtime.play()
            };
            assert!(
                result.is_ok(),
                "explicit playback after Stop must reconnect: {result:?}"
            );
        }
    }
    #[test]
    fn newer_pause_stop_and_reselection_retire_pending_unpause() {
        for action in ["pause", "stop", "reselect"] {
            let (mut runtime, commands) = suspended_runtime();
            runtime.play().unwrap();
            match action {
                "pause" => runtime.pause().unwrap(),
                "stop" => runtime.stop_playback().unwrap(),
                _ => runtime.load_tracks(&["new.mp3".into()]).unwrap(),
            }
            commands.lock().unwrap().clear();
            runtime.handle_raw_event(json!({"event":"file-loaded"}));
            assert!(
                !commands
                    .lock()
                    .unwrap()
                    .iter()
                    .any(|c| (action != "pause" && c.first() == Some(&json!("seek")))
                        || *c == vec![json!("set_property"), json!("pause"), json!(false)]),
                "old reconstruction emitted commands after {action}"
            );
            if action == "pause" {
                assert_eq!(runtime.playback_state(), PlaybackState::Paused);
            }
        }
    }
    #[test]
    fn all_reselection_paths_apply_latest_route_and_volume_before_loading() {
        for action in ["tracks", "playlist", "playlist_track"] {
            let (mut runtime, commands) = suspended_runtime();
            runtime.set_audio_device("alsa/latest").unwrap();
            runtime.set_volume(23).unwrap();
            match action {
                "tracks" => runtime.load_tracks(&["new.mp3".into()]).unwrap(),
                "playlist" => runtime.load_playlist_file("new.m3u").unwrap(),
                _ => runtime.load_playlist_track("new.m3u", 1).unwrap(),
            }
            let commands = commands.lock().unwrap();
            let load = commands
                .iter()
                .position(|c| {
                    matches!(
                        c.first().and_then(Value::as_str),
                        Some("loadfile" | "loadlist")
                    )
                })
                .unwrap();
            for command in [
                vec![
                    json!("set_property"),
                    json!("audio-device"),
                    json!("alsa/latest"),
                ],
                vec![json!("set_property"), json!("volume"), json!(23)],
            ] {
                assert!(
                    commands[..load].contains(&command),
                    "latest setting missing before {action}: {command:?}"
                );
            }
        }
    }
}

pub use crate::models::{PlaybackState, Track};

const OBSERVE_MEDIA_TITLE: i64 = 1;
const OBSERVE_METADATA: i64 = 2;
const OBSERVE_PAUSE: i64 = 3;
const OBSERVE_IDLE_ACTIVE: i64 = 4;
const OBSERVE_DURATION: i64 = 5;
const OBSERVE_PATH: i64 = 6;
const OBSERVE_TIME_POS: i64 = 7;

pub trait MediaRuntime: Send {
    fn start(&mut self) -> Result<()>;
    fn stop(&mut self) -> Result<()>;
    fn is_connected(&self) -> bool;
    fn play(&mut self) -> Result<()>;
    fn pause(&mut self) -> Result<()>;
    fn suspend_for_call(&mut self) -> Result<()>;
    fn stop_playback(&mut self) -> Result<()>;
    fn next_track(&mut self) -> Result<()>;
    fn previous_track(&mut self) -> Result<()>;
    fn set_volume(&mut self, volume: i32) -> Result<()>;
    fn get_volume(&mut self) -> Result<Option<i32>>;
    fn set_audio_device(&mut self, device: &str) -> Result<()>;
    fn load_tracks(&mut self, uris: &[String]) -> Result<()>;
    fn load_playlist_file(&mut self, path: &str) -> Result<()>;
    fn load_playlist_track(&mut self, path: &str, track_index: usize) -> Result<()>;
    fn drain_events(&mut self) -> Result<Vec<MediaRuntimeEvent>>;
    fn current_track(&self) -> Option<Track>;
    fn playback_state(&self) -> PlaybackState;
    fn time_position_ms(&self) -> i64;
}

pub trait MediaRuntimeFactory: Send {
    fn build(&self, config: &MediaConfig) -> Result<Box<dyn MediaRuntime>>;
}

struct MpvRuntimeFactory;

impl MediaRuntimeFactory for MpvRuntimeFactory {
    fn build(&self, config: &MediaConfig) -> Result<Box<dyn MediaRuntime>> {
        Ok(Box::new(MpvRuntime::new(config.clone())))
    }
}

pub struct MediaHost {
    configured_output: Option<String>,
    pub(crate) alert_output: String,
    pub(crate) alert_volume: u8,
    pub(crate) audio_fence: yoyopod_protocol::audio::AudioCallFence,
    pub(crate) ringtone: crate::ringtone::RingtonePlayer,
    config: Option<MediaConfig>,
    commands_processed: u64,
    factory: Box<dyn MediaRuntimeFactory>,
    runtime: Option<Box<dyn MediaRuntime>>,
    library: Option<LocalMusicLibrary>,
    recent_store: RecentTrackStore,
    remote_cache: Option<RemotePlaybackCache>,
    remote_media_library: Option<RemoteMediaLibrary>,
    connected: bool,
    backend_state: String,
    current_track: Option<Track>,
    playback_state: PlaybackState,
    time_position_ms: i64,
}

impl Default for MediaHost {
    fn default() -> Self {
        Self::with_factory(Box::new(MpvRuntimeFactory))
    }
}

impl MediaHost {
    pub fn with_factory(factory: Box<dyn MediaRuntimeFactory>) -> Self {
        Self {
            configured_output: None,
            alert_output: "alsa/default".into(),
            alert_volume: 100,
            audio_fence: Default::default(),
            ringtone: Default::default(),
            config: None,
            commands_processed: 0,
            factory,
            runtime: None,
            library: None,
            recent_store: RecentTrackStore::default(),
            remote_cache: None,
            remote_media_library: None,
            connected: false,
            backend_state: "not_started".to_string(),
            current_track: None,
            playback_state: PlaybackState::Stopped,
            time_position_ms: 0,
        }
    }

    pub fn record_command(&mut self) {
        self.commands_processed = self.commands_processed.saturating_add(1);
    }

    pub fn configure(&mut self, config: MediaConfig) -> Result<()> {
        self.alert_output = format!("alsa/{}", config.alsa_device);
        self.library = Some(LocalMusicLibrary::open(&config.music_dir)?);
        self.recent_store = RecentTrackStore::open(&config.recent_tracks_file, 50);
        self.remote_cache = Some(RemotePlaybackCache::new(
            &config.remote_cache_dir,
            config.remote_cache_max_bytes,
        ));
        self.remote_media_library = Some(RemoteMediaLibrary::new(&config.music_dir));
        self.config = Some(config);
        self.backend_state = "configured".to_string();
        Ok(())
    }

    pub fn start_backend(&mut self) -> Result<()> {
        if self.runtime.is_some() && self.connected {
            return Ok(());
        }
        let config = self
            .config
            .clone()
            .ok_or_else(|| anyhow!("media host is not configured"))?;
        let mut runtime = self.factory.build(&config)?;
        runtime.start()?;
        if let Some(output) = &self.configured_output {
            runtime.set_audio_device(output)?;
        }
        runtime.set_volume(config.default_volume)?;
        self.connected = runtime.is_connected();
        self.backend_state = if self.connected {
            "connected".to_string()
        } else {
            "started".to_string()
        };
        self.current_track = runtime.current_track();
        self.playback_state = runtime.playback_state();
        self.time_position_ms = runtime.time_position_ms();
        self.runtime = Some(runtime);
        Ok(())
    }

    pub fn stop_backend(&mut self) -> Result<()> {
        self.ringtone.shutdown().map_err(anyhow::Error::msg)?;
        if let Some(mut runtime) = self.runtime.take() {
            runtime.stop()?;
        }
        self.connected = false;
        self.backend_state = if self.config.is_some() {
            "stopped".to_string()
        } else {
            "not_started".to_string()
        };
        self.current_track = None;
        self.playback_state = PlaybackState::Stopped;
        self.time_position_ms = 0;
        Ok(())
    }

    pub fn drain_runtime_events(&mut self) -> Result<Vec<MediaRuntimeEvent>> {
        self.ringtone
            .tick(crate::worker::now_ms())
            .map_err(anyhow::Error::msg)?;
        let Some(runtime) = self.runtime.as_mut() else {
            return Ok(Vec::new());
        };
        let events = runtime.drain_events()?;
        self.connected = runtime.is_connected();
        self.current_track = runtime.current_track();
        self.playback_state = runtime.playback_state();
        self.time_position_ms = runtime.time_position_ms();
        for event in &events {
            self.apply_runtime_event(event);
        }
        Ok(events)
    }

    pub fn play(&mut self) -> Result<()> {
        self.ensure_runtime_started()?;
        self.runtime_mut()?.play()
    }

    pub fn interrupt_for_call(
        &mut self,
        request: &yoyopod_protocol::call::InterruptForCall,
    ) -> Result<()> {
        self.audio_fence
            .interrupt(request)
            .map_err(anyhow::Error::msg)?;
        if let Some(runtime) = self.runtime.as_mut() {
            runtime.suspend_for_call()?;
            self.current_track = runtime.current_track();
            self.playback_state = runtime.playback_state();
            self.time_position_ms = runtime.time_position_ms();
            self.connected = false;
        }
        Ok(())
    }

    pub fn pause(&mut self) -> Result<()> {
        if self.runtime.is_none() {
            return Ok(());
        }
        self.runtime_mut()?.pause()
    }

    pub fn resume(&mut self) -> Result<()> {
        self.ensure_runtime_started()?;
        self.runtime_mut()?.play()
    }

    pub fn stop_playback(&mut self) -> Result<()> {
        if self.runtime.is_none() {
            return Ok(());
        }
        self.runtime_mut()?.stop_playback()
    }

    pub fn next_track(&mut self) -> Result<()> {
        self.ensure_runtime_started()?;
        self.runtime_mut()?.next_track()
    }

    pub fn previous_track(&mut self) -> Result<()> {
        self.ensure_runtime_started()?;
        self.runtime_mut()?.previous_track()
    }

    pub fn set_volume(&mut self, volume: i32) -> Result<()> {
        if let Some(config) = self.config.as_mut() {
            config.default_volume = volume.clamp(0, 100);
        }
        if self.runtime.is_none() {
            return Ok(());
        }
        self.runtime_mut()?.set_volume(volume)
    }

    pub fn set_audio_device(&mut self, device: &str) -> Result<()> {
        self.configured_output = Some(device.to_string());
        if self.runtime.is_none() {
            return Ok(());
        }
        self.runtime_mut()?.set_audio_device(device)
    }

    pub fn load_tracks(&mut self, uris: &[String]) -> Result<()> {
        self.ensure_runtime_started()?;
        self.runtime_mut()?.load_tracks(uris)
    }

    pub fn load_playlist_file(&mut self, path: &str) -> Result<()> {
        if let Some(library) = self.library.as_ref() {
            if !library.is_local_playlist_uri(path) {
                return Err(anyhow!(
                    "playlist uri is not local to the configured music directory"
                ));
            }
        }
        self.ensure_runtime_started()?;
        self.runtime_mut()?.load_playlist_file(path)
    }

    pub fn play_playlist_track(
        &mut self,
        path: &str,
        track_uri: &str,
        track_index: usize,
    ) -> Result<()> {
        let library = self
            .library
            .as_ref()
            .ok_or_else(|| anyhow!("media host is not configured"))?;
        let playlist = library
            .playlist(path)
            .ok_or_else(|| anyhow!("playlist is not in the local library"))?;
        if track_index >= playlist.tracks.len() {
            return Err(anyhow!(
                "playlist track index {track_index} is out of range for {} tracks",
                playlist.tracks.len()
            ));
        }
        if playlist.tracks[track_index].uri != track_uri {
            return Err(anyhow!(
                "playlist track selection is stale: index {track_index} no longer maps to {track_uri}"
            ));
        }
        self.ensure_runtime_started()?;
        self.runtime_mut()?.load_playlist_track(path, track_index)
    }

    pub fn shuffle_all(&mut self) -> Result<()> {
        let library = self
            .library
            .as_ref()
            .ok_or_else(|| anyhow!("media host is not configured"))?;
        let track_uris = library.shuffle_track_uris()?;
        if track_uris.is_empty() {
            return Err(anyhow!("shuffle requested but no local tracks were found"));
        }
        self.load_tracks(&track_uris)
    }

    pub fn play_recent_track(&mut self, track_uri: &str) -> Result<()> {
        let library = self
            .library
            .as_ref()
            .ok_or_else(|| anyhow!("media host is not configured"))?;
        if !library.is_local_track_uri(track_uri) {
            return Err(anyhow!(
                "track uri is not local to the configured music directory"
            ));
        }
        self.load_tracks(&[track_uri.to_string()])
    }

    pub fn list_playlists(&self, fetch_track_counts: bool) -> Result<Vec<PlaylistEntry>> {
        match self.library.as_ref() {
            Some(library) => library.list_playlists(fetch_track_counts),
            None => Ok(Vec::new()),
        }
    }

    pub fn playlist_count(&self) -> Result<usize> {
        match self.library.as_ref() {
            Some(library) => library.playlist_count(),
            None => Ok(0),
        }
    }

    pub fn list_recent_tracks(&self, limit: Option<usize>) -> Result<Vec<RecentTrackEntry>> {
        Ok(self.recent_store.list_recent(limit))
    }

    pub fn menu_items(&self) -> Vec<LocalLibraryItem> {
        self.library
            .as_ref()
            .map(LocalMusicLibrary::menu_items)
            .unwrap_or_default()
    }

    pub fn prepare_remote_playback_asset(
        &self,
        track_id: &str,
        media_url: &str,
        checksum_sha256: Option<&str>,
        extension: &str,
    ) -> Result<CachedPlaybackAsset> {
        self.remote_cache
            .as_ref()
            .ok_or_else(|| anyhow!("media host is not configured"))?
            .prepare(track_id, media_url, checksum_sha256, extension)
            .map_err(|error| anyhow!(error))
    }

    pub fn import_remote_media_asset(
        &mut self,
        request: &MediaImportRequest,
        cached_path: &std::path::Path,
    ) -> Result<std::path::PathBuf> {
        let path = self
            .remote_media_library
            .as_ref()
            .ok_or_else(|| anyhow!("media host is not configured"))?
            .persist_asset(request, cached_path)
            .map_err(|error| anyhow!(error))?;
        if let Some(library) = self.library.as_mut() {
            library.refresh()?;
        }
        Ok(path)
    }

    pub fn health_payload(&self) -> Value {
        let mut payload = self.snapshot_payload();
        if let Some(object) = payload.as_object_mut() {
            object.insert("ready".to_string(), json!(true));
            object.insert("command_count".to_string(), json!(self.commands_processed));
        }
        payload
    }

    pub fn snapshot_payload(&self) -> Value {
        json!({
            "configured": self.config.is_some(),
            "connected": self.connected,
            "backend_state": self.backend_state,
            "music_dir": self.config.as_ref().map(|config| config.music_dir.as_str()).unwrap_or(""),
            "mpv_socket": self.config.as_ref().map(|config| config.mpv_socket.as_str()).unwrap_or(""),
            "mpv_binary": self.config.as_ref().map(|config| config.mpv_binary.as_str()).unwrap_or(""),
            "alsa_device": self.config.as_ref().map(|config| config.alsa_device.as_str()).unwrap_or(""),
            "default_volume": self.config.as_ref().map(|config| config.default_volume).unwrap_or(0),
            "recent_tracks_file": self.config.as_ref().map(|config| config.recent_tracks_file.as_str()).unwrap_or(""),
            "remote_cache_dir": self.config.as_ref().map(|config| config.remote_cache_dir.as_str()).unwrap_or(""),
            "remote_cache_max_bytes": self.config.as_ref().map(|config| config.remote_cache_max_bytes).unwrap_or(0),
            "playlist_count": self.playlist_count().unwrap_or(0),
            "library_menu": self.menu_items(),
            "playlists": self.list_playlists(true).unwrap_or_default(),
            "recent_tracks": self.list_recent_tracks(None).unwrap_or_default(),
            "current_track": self.current_track.as_ref().map(track_json),
            "playback_state": self.playback_state.as_str(),
            "time_position_ms": self.time_position_ms,
        })
    }

    pub fn has_active_runtime(&self) -> bool {
        self.runtime.is_some()
    }

    fn ensure_runtime_started(&mut self) -> Result<()> {
        if self.runtime.is_none() {
            self.start_backend()?;
        }
        Ok(())
    }

    fn runtime_mut(&mut self) -> Result<&mut (dyn MediaRuntime + '_)> {
        match self.runtime.as_mut() {
            Some(runtime) => Ok(runtime.as_mut()),
            None => Err(anyhow!("media host runtime is not started")),
        }
    }

    fn apply_runtime_event(&mut self, event: &MediaRuntimeEvent) {
        match event {
            MediaRuntimeEvent::TrackChanged(track) => {
                self.current_track = track.clone();
                if let Some(track) = track {
                    self.record_recent_track_if_local(track);
                }
            }
            MediaRuntimeEvent::PlaybackStateChanged(state) => {
                self.playback_state = *state;
            }
            MediaRuntimeEvent::TimePositionChanged(value) => {
                self.time_position_ms = *value;
            }
            MediaRuntimeEvent::BackendAvailabilityChanged { connected, reason } => {
                self.connected = *connected;
                self.backend_state = if *connected {
                    "connected".to_string()
                } else {
                    format!("disconnected:{reason}")
                };
            }
        }
    }

    fn record_recent_track_if_local(&mut self, track: &Track) {
        let Some(library) = self.library.as_ref() else {
            return;
        };
        if !library.is_local_track_uri(&track.uri) {
            return;
        }
        let _ = self.recent_store.record_track(track);
    }
}

pub trait MpvProcessController: Send {
    fn spawn(&mut self) -> std::io::Result<()>;
    fn stop(&mut self) -> std::io::Result<()>;
    fn is_alive(&self) -> bool;
}

impl MpvProcessController for MpvProcess {
    fn spawn(&mut self) -> std::io::Result<()> {
        MpvProcess::spawn(self)
    }

    fn stop(&mut self) -> std::io::Result<()> {
        MpvProcess::stop(self)
    }

    fn is_alive(&self) -> bool {
        MpvProcess::is_alive(self)
    }
}

pub trait MpvIpcTransport: Send {
    fn connect(&mut self) -> Result<()>;
    fn connected(&self) -> bool;
    fn disconnect(&mut self);
    fn send_command(&mut self, args: &[Value], timeout: Duration) -> Result<Value>;
    fn observe_property(&mut self, name: &str, observe_id: i64) -> Result<()>;
    fn drain_events(&mut self) -> Result<Vec<Value>>;
}

impl MpvIpcTransport for MpvIpcClient {
    fn connect(&mut self) -> Result<()> {
        MpvIpcClient::connect(self)
    }

    fn connected(&self) -> bool {
        MpvIpcClient::connected(self)
    }

    fn disconnect(&mut self) {
        MpvIpcClient::disconnect(self)
    }

    fn send_command(&mut self, args: &[Value], timeout: Duration) -> Result<Value> {
        MpvIpcClient::send_command(self, args, timeout)
    }

    fn observe_property(&mut self, name: &str, observe_id: i64) -> Result<()> {
        MpvIpcClient::observe_property(self, name, observe_id)
    }

    fn drain_events(&mut self) -> Result<Vec<Value>> {
        MpvIpcClient::drain_events(self)
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct MpvRuntimeStartupPolicy {
    pub connect_timeout: Duration,
    pub connect_delay: Duration,
}

impl Default for MpvRuntimeStartupPolicy {
    fn default() -> Self {
        Self {
            connect_timeout: Duration::from_secs(10),
            connect_delay: Duration::from_millis(100),
        }
    }
}

pub struct MpvRuntime {
    requested_playback: PlaybackState,
    selected_volume: Option<i32>,
    selected_output: Option<String>,
    suspended: Option<(Vec<String>, usize, i64)>,
    resume_position: Option<(String, i64)>,
    process: Box<dyn MpvProcessController>,
    ipc: Box<dyn MpvIpcTransport>,
    startup: MpvRuntimeStartupPolicy,
    connected: bool,
    current_track: Option<Track>,
    playback_state: PlaybackState,
    cached_path: Option<String>,
    cached_metadata: Map<String, Value>,
    cached_duration: Option<Value>,
    cached_media_title: Option<String>,
    cached_time_position_ms: i64,
}

impl MpvRuntime {
    fn prepare_explicit_playback(&mut self) -> Result<()> {
        if !self.is_connected() {
            self.connected = false;
            self.start()?;
        }
        if let Some(volume) = self.selected_volume {
            self.command(&[json!("set_property"), json!("volume"), json!(volume)])?;
        }
        if let Some(output) = self.selected_output.clone() {
            self.command(&[json!("set_property"), json!("audio-device"), json!(output)])?;
        }
        Ok(())
    }
    fn prepare_explicit_load(&mut self) -> Result<()> {
        self.prepare_explicit_playback()?;
        self.suspended = None;
        self.resume_position = None;
        self.requested_playback = PlaybackState::Playing;
        Ok(())
    }
    pub fn new(config: MediaConfig) -> Self {
        let socket_path = config.mpv_socket.clone();
        Self::with_clients(
            Box::new(MpvProcess::new(config)),
            Box::new(MpvIpcClient::new(socket_path)),
            MpvRuntimeStartupPolicy::default(),
        )
    }

    pub fn with_clients(
        process: Box<dyn MpvProcessController>,
        ipc: Box<dyn MpvIpcTransport>,
        startup: MpvRuntimeStartupPolicy,
    ) -> Self {
        Self {
            requested_playback: PlaybackState::Stopped,
            suspended: None,
            resume_position: None,
            selected_volume: None,
            selected_output: None,
            process,
            ipc,
            startup,
            connected: false,
            current_track: None,
            playback_state: PlaybackState::Stopped,
            cached_path: None,
            cached_metadata: Map::new(),
            cached_duration: None,
            cached_media_title: None,
            cached_time_position_ms: 0,
        }
    }

    fn command(&mut self, args: &[Value]) -> Result<()> {
        let result = self.ipc.send_command(args, Duration::from_secs(1))?;
        match result.get("error").and_then(Value::as_str) {
            Some("success") => Ok(()),
            Some(error) => Err(anyhow!("mpv command failed: {error}")),
            None => Err(anyhow!("mpv response was missing error status")),
        }
    }

    fn get_property(&mut self, name: &str) -> Result<Option<Value>> {
        let result = self.ipc.send_command(
            &[json!("get_property"), json!(name)],
            Duration::from_secs(1),
        )?;
        if result.get("error").and_then(Value::as_str) == Some("success") {
            Ok(result.get("data").cloned())
        } else {
            Ok(None)
        }
    }

    fn observe_core_properties(&mut self) -> Result<()> {
        self.ipc
            .observe_property("media-title", OBSERVE_MEDIA_TITLE)?;
        self.ipc.observe_property("metadata", OBSERVE_METADATA)?;
        self.ipc.observe_property("pause", OBSERVE_PAUSE)?;
        self.ipc
            .observe_property("idle-active", OBSERVE_IDLE_ACTIVE)?;
        self.ipc.observe_property("duration", OBSERVE_DURATION)?;
        self.ipc.observe_property("path", OBSERVE_PATH)?;
        self.ipc.observe_property("time-pos", OBSERVE_TIME_POS)?;
        Ok(())
    }

    fn prime_track_cache(&mut self) -> Result<()> {
        self.cached_path = self
            .get_property("path")?
            .and_then(|value| value.as_str().map(ToString::to_string));
        self.cached_metadata = self
            .get_property("metadata")?
            .and_then(|value| value.as_object().cloned())
            .unwrap_or_default();
        self.cached_duration = self.get_property("duration")?;
        self.cached_media_title = self
            .get_property("media-title")?
            .and_then(|value| value.as_str().map(ToString::to_string));
        if let Some(time_pos) = self.get_property("time-pos")? {
            self.cached_time_position_ms = duration_ms(Some(&time_pos));
        }
        self.sync_track_from_cache();
        Ok(())
    }

    fn clear_track_cache(&mut self) {
        self.cached_path = None;
        self.cached_metadata.clear();
        self.cached_duration = None;
        self.cached_media_title = None;
        self.cached_time_position_ms = 0;
        self.current_track = None;
    }

    fn sync_track_from_cache(&mut self) {
        let Some(path) = self.cached_path.as_ref() else {
            return;
        };
        let mut metadata = self.cached_metadata.clone();
        if let Some(duration) = self.cached_duration.clone() {
            metadata.insert("duration".to_string(), duration);
        }
        if let Some(media_title) = self.cached_media_title.clone() {
            metadata
                .entry("title".to_string())
                .or_insert(Value::String(media_title));
        }
        self.current_track = Some(Track::from_mpv_metadata(path, &metadata));
    }

    fn handle_raw_event(&mut self, raw: Value) -> Vec<MediaRuntimeEvent> {
        let mut events = Vec::new();
        let Some(event) = MpvEvent::from_value(raw) else {
            return events;
        };
        if matches!(event, MpvEvent::FileLoaded)
            && self.requested_playback == PlaybackState::Stopped
        {
            return events;
        }
        if let Some((path, position)) = self.resume_position.clone() {
            if !matches!(event, MpvEvent::FileLoaded)
                || self
                    .get_property("path")
                    .ok()
                    .flatten()
                    .and_then(|v| v.as_str().map(str::to_owned))
                    .as_deref()
                    != Some(path.as_str())
            {
                return events;
            }
            if self
                .command(&[
                    json!("seek"),
                    json!(position as f64 / 1000.0),
                    json!("absolute+exact"),
                ])
                .is_err()
                || (self.requested_playback == PlaybackState::Playing
                    && self
                        .command(&[json!("set_property"), json!("pause"), json!(false)])
                        .is_err())
            {
                return events;
            }
            self.resume_position = None;
            let _ = self.prime_track_cache();
            self.cached_time_position_ms = position;
            self.playback_state = self.requested_playback;
            return vec![
                MediaRuntimeEvent::TrackChanged(self.current_track.clone()),
                MediaRuntimeEvent::PlaybackStateChanged(self.requested_playback),
                MediaRuntimeEvent::TimePositionChanged(position),
            ];
        }
        match event {
            MpvEvent::FileLoaded => {
                self.cached_time_position_ms = 0;
                if self.cached_path.is_none() {
                    let _ = self.prime_track_cache();
                }
                let previous_track = self.current_track.clone();
                self.sync_track_from_cache();
                if previous_track != self.current_track {
                    events.push(MediaRuntimeEvent::TrackChanged(self.current_track.clone()));
                }
                if self.playback_state != self.requested_playback {
                    self.playback_state = self.requested_playback;
                    events.push(MediaRuntimeEvent::PlaybackStateChanged(
                        self.requested_playback,
                    ));
                }
            }
            MpvEvent::PlaybackRestart => {}
            MpvEvent::Pause => {
                if self.playback_state != PlaybackState::Paused {
                    self.playback_state = PlaybackState::Paused;
                    events.push(MediaRuntimeEvent::PlaybackStateChanged(
                        PlaybackState::Paused,
                    ));
                }
            }
            MpvEvent::Unpause => {
                if self.playback_state != PlaybackState::Playing {
                    self.playback_state = PlaybackState::Playing;
                    events.push(MediaRuntimeEvent::PlaybackStateChanged(
                        PlaybackState::Playing,
                    ));
                }
            }
            MpvEvent::EndFile { reason } => {
                if reason != "eof" {
                    self.clear_track_cache();
                    if self.playback_state != PlaybackState::Stopped {
                        self.playback_state = PlaybackState::Stopped;
                        events.push(MediaRuntimeEvent::PlaybackStateChanged(
                            PlaybackState::Stopped,
                        ));
                    }
                    events.push(MediaRuntimeEvent::TrackChanged(None));
                }
            }
            MpvEvent::PropertyChange { name, data } => match name.as_str() {
                "path" => {
                    let previous_track = self.current_track.clone();
                    self.cached_path = data.as_str().map(ToString::to_string);
                    self.sync_track_from_cache();
                    if previous_track != self.current_track {
                        events.push(MediaRuntimeEvent::TrackChanged(self.current_track.clone()));
                    }
                }
                "metadata" => {
                    let previous_track = self.current_track.clone();
                    self.cached_metadata = data.as_object().cloned().unwrap_or_default();
                    self.sync_track_from_cache();
                    if previous_track != self.current_track {
                        events.push(MediaRuntimeEvent::TrackChanged(self.current_track.clone()));
                    }
                }
                "duration" => {
                    let previous_track = self.current_track.clone();
                    self.cached_duration = Some(data);
                    self.sync_track_from_cache();
                    if previous_track != self.current_track {
                        events.push(MediaRuntimeEvent::TrackChanged(self.current_track.clone()));
                    }
                }
                "media-title" => {
                    let previous_track = self.current_track.clone();
                    self.cached_media_title = data.as_str().map(ToString::to_string);
                    self.sync_track_from_cache();
                    if previous_track != self.current_track {
                        events.push(MediaRuntimeEvent::TrackChanged(self.current_track.clone()));
                    }
                }
                "time-pos" => {
                    let updated = duration_ms(Some(&data));
                    if updated != self.cached_time_position_ms {
                        self.cached_time_position_ms = updated;
                        events.push(MediaRuntimeEvent::TimePositionChanged(updated));
                    }
                }
                "pause" => {
                    let next = if data.as_bool().unwrap_or(false) {
                        PlaybackState::Paused
                    } else {
                        PlaybackState::Playing
                    };
                    if next != self.playback_state {
                        self.playback_state = next;
                        events.push(MediaRuntimeEvent::PlaybackStateChanged(next));
                    }
                }
                "idle-active" => {
                    if data.as_bool().unwrap_or(false) {
                        self.clear_track_cache();
                        if self.playback_state != PlaybackState::Stopped {
                            self.playback_state = PlaybackState::Stopped;
                            events.push(MediaRuntimeEvent::PlaybackStateChanged(
                                PlaybackState::Stopped,
                            ));
                        }
                        events.push(MediaRuntimeEvent::TrackChanged(None));
                    }
                }
                _ => {}
            },
        }
        events
    }
}

impl MediaRuntime for MpvRuntime {
    fn suspend_for_call(&mut self) -> Result<()> {
        if self.suspended.is_some() {
            return Ok(());
        }
        let playlist = self.get_property("playlist");
        let position = self.get_property("time-pos");
        // Always attempt physical release, including a failed IPC snapshot.
        self.ipc.disconnect();
        self.process.stop()?;
        self.connected = false;
        let playlist = playlist?.unwrap_or_else(|| json!([]));
        let items = playlist
            .as_array()
            .ok_or_else(|| anyhow!("invalid mpv playlist"))?;
        let index = items
            .iter()
            .position(|v| v["current"].as_bool() == Some(true))
            .unwrap_or(0);
        let mut paths: Vec<String> = items
            .iter()
            .filter_map(|v| v["filename"].as_str().map(str::to_owned))
            .collect();
        if paths.is_empty() {
            if let Some(path) = self.cached_path.clone() {
                paths.push(path);
            }
        }
        if let Some(seconds) = position?.and_then(|v| v.as_f64()) {
            self.cached_time_position_ms = (seconds * 1000.0) as i64;
        }
        self.suspended = Some((paths, index, self.cached_time_position_ms));
        if self.playback_state == PlaybackState::Playing {
            self.playback_state = PlaybackState::Paused;
        }
        Ok(())
    }
    fn start(&mut self) -> Result<()> {
        if self.connected {
            return Ok(());
        }
        self.process.spawn()?;
        let deadline = Instant::now() + self.startup.connect_timeout;
        let mut last_error = anyhow!("mpv IPC connect failed before the first attempt");
        loop {
            match self.ipc.connect() {
                Ok(()) => break,
                Err(error) => {
                    last_error = error;
                    if !self.process.is_alive() || Instant::now() >= deadline {
                        let _ = self.process.stop();
                        return Err(last_error);
                    }
                    thread::sleep(self.startup.connect_delay);
                }
            }
        }
        self.observe_core_properties()?;
        self.prime_track_cache()?;
        self.connected = true;
        Ok(())
    }

    fn stop(&mut self) -> Result<()> {
        self.connected = false;
        self.clear_track_cache();
        self.ipc.disconnect();
        self.process.stop()?;
        Ok(())
    }

    fn is_connected(&self) -> bool {
        self.connected && self.process.is_alive() && self.ipc.connected()
    }

    fn play(&mut self) -> Result<()> {
        self.prepare_explicit_playback()?;
        self.requested_playback = PlaybackState::Playing;
        if let Some((paths, index, position)) = self.suspended.clone() {
            self.start()?;
            if let Some(volume) = self.selected_volume {
                self.command(&[json!("set_property"), json!("volume"), json!(volume)])?;
            }
            if let Some(output) = self.selected_output.clone() {
                self.command(&[json!("set_property"), json!("audio-device"), json!(output)])?;
            }
            self.command(&[json!("set_property"), json!("pause"), json!(true)])?;
            for (i, path) in paths.iter().enumerate() {
                self.command(&[
                    json!("loadfile"),
                    json!(path),
                    json!(if i == 0 { "replace" } else { "append" }),
                ])?;
            }
            if !paths.is_empty() {
                self.command(&[json!("set_property"), json!("playlist-pos"), json!(index)])?;
                self.resume_position = Some((paths[index].clone(), position));
                self.suspended = None;
                return Ok(());
            }
            self.suspended = None;
        }
        self.command(&[json!("set_property"), json!("pause"), json!(false)])
    }

    fn pause(&mut self) -> Result<()> {
        self.requested_playback = PlaybackState::Paused;
        self.playback_state = PlaybackState::Paused;
        if self.suspended.is_some() {
            return Ok(());
        }
        self.command(&[json!("set_property"), json!("pause"), json!(true)])
    }

    fn stop_playback(&mut self) -> Result<()> {
        self.resume_position = None;
        self.requested_playback = PlaybackState::Stopped;
        if !self.is_connected() {
            self.suspended = None;
            self.clear_track_cache();
            self.playback_state = PlaybackState::Stopped;
            return Ok(());
        }
        self.command(&[json!("stop")])
    }

    fn next_track(&mut self) -> Result<()> {
        if let Some((paths, index, position)) = self.suspended.as_mut() {
            if !paths.is_empty() {
                *index = (*index + 1).min(paths.len() - 1);
            }
            *position = 0;
            return self.play();
        }
        self.command(&[json!("playlist-next")])
    }

    fn previous_track(&mut self) -> Result<()> {
        if let Some((_, index, position)) = self.suspended.as_mut() {
            *index = index.saturating_sub(1);
            *position = 0;
            return self.play();
        }
        self.command(&[json!("playlist-prev")])
    }

    fn set_volume(&mut self, volume: i32) -> Result<()> {
        self.selected_volume = Some(volume.clamp(0, 100));
        if self.suspended.is_some() {
            return Ok(());
        }
        self.command(&[
            json!("set_property"),
            json!("volume"),
            json!(volume.clamp(0, 100)),
        ])
    }

    fn get_volume(&mut self) -> Result<Option<i32>> {
        if self.suspended.is_some() {
            return Ok(self.selected_volume);
        }
        Ok(self
            .get_property("volume")?
            .and_then(|value| value.as_i64().map(|value| value as i32)))
    }

    fn set_audio_device(&mut self, device: &str) -> Result<()> {
        self.selected_output = Some(device.to_string());
        if self.suspended.is_some() {
            return Ok(());
        }
        self.command(&[json!("set_property"), json!("audio-device"), json!(device)])
    }

    fn load_tracks(&mut self, uris: &[String]) -> Result<()> {
        self.prepare_explicit_load()?;
        let Some((first, rest)) = uris.split_first() else {
            return Err(anyhow!("load_tracks requires at least one uri"));
        };
        self.command(&[json!("loadfile"), json!(first), json!("replace")])?;
        for uri in rest {
            self.command(&[json!("loadfile"), json!(uri), json!("append")])?;
        }
        self.command(&[json!("set_property"), json!("pause"), json!(false)])
    }

    fn load_playlist_file(&mut self, path: &str) -> Result<()> {
        self.prepare_explicit_load()?;
        self.command(&[json!("loadlist"), json!(path), json!("replace")])
    }

    fn load_playlist_track(&mut self, path: &str, track_index: usize) -> Result<()> {
        self.prepare_explicit_load()?;
        self.command(&[json!("loadlist"), json!(path), json!("replace")])?;
        self.command(&[
            json!("set_property"),
            json!("playlist-pos"),
            json!(track_index),
        ])?;
        self.command(&[json!("set_property"), json!("pause"), json!(false)])
    }

    fn drain_events(&mut self) -> Result<Vec<MediaRuntimeEvent>> {
        if self.suspended.is_some() {
            return Ok(Vec::new());
        }
        let mut events = Vec::new();
        for raw in self.ipc.drain_events()? {
            events.extend(self.handle_raw_event(raw));
        }
        let connected_now = self.process.is_alive() && self.ipc.connected();
        if self.connected != connected_now {
            self.connected = connected_now;
            events.push(MediaRuntimeEvent::BackendAvailabilityChanged {
                connected: connected_now,
                reason: if connected_now {
                    "connected".to_string()
                } else {
                    "connection_lost".to_string()
                },
            });
        }
        Ok(events)
    }

    fn current_track(&self) -> Option<Track> {
        self.current_track.clone()
    }

    fn playback_state(&self) -> PlaybackState {
        self.playback_state
    }

    fn time_position_ms(&self) -> i64 {
        self.cached_time_position_ms
    }
}

fn track_json(track: &Track) -> Value {
    json!({
        "uri": track.uri,
        "name": track.name,
        "artists": track.artists,
        "album": track.album,
        "length_ms": track.length_ms,
        "track_no": track.track_no,
    })
}
