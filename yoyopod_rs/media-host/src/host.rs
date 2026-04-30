use std::time::Duration;

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
    fn stop_playback(&mut self) -> Result<()>;
    fn next_track(&mut self) -> Result<()>;
    fn previous_track(&mut self) -> Result<()>;
    fn set_volume(&mut self, volume: i32) -> Result<()>;
    fn get_volume(&mut self) -> Result<Option<i32>>;
    fn set_audio_device(&mut self, device: &str) -> Result<()>;
    fn load_tracks(&mut self, uris: &[String]) -> Result<()>;
    fn load_playlist_file(&mut self, path: &str) -> Result<()>;
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

    pub fn configure(&mut self, config: MediaConfig) {
        self.library = Some(LocalMusicLibrary::new(&config.music_dir));
        self.recent_store = RecentTrackStore::open(&config.recent_tracks_file, 50);
        self.remote_cache = Some(RemotePlaybackCache::new(
            &config.remote_cache_dir,
            config.remote_cache_max_bytes,
        ));
        self.remote_media_library = Some(RemoteMediaLibrary::new(&config.music_dir));
        self.config = Some(config);
        self.backend_state = "configured".to_string();
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

    pub fn pause(&mut self) -> Result<()> {
        self.ensure_runtime_started()?;
        self.runtime_mut()?.pause()
    }

    pub fn resume(&mut self) -> Result<()> {
        self.ensure_runtime_started()?;
        self.runtime_mut()?.play()
    }

    pub fn stop_playback(&mut self) -> Result<()> {
        self.ensure_runtime_started()?;
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
        self.ensure_runtime_started()?;
        self.runtime_mut()?.set_volume(volume)
    }

    pub fn set_audio_device(&mut self, device: &str) -> Result<()> {
        self.ensure_runtime_started()?;
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
        &self,
        request: &MediaImportRequest,
        cached_path: &std::path::Path,
    ) -> Result<std::path::PathBuf> {
        self.remote_media_library
            .as_ref()
            .ok_or_else(|| anyhow!("media host is not configured"))?
            .persist_asset(request, cached_path)
            .map_err(|error| anyhow!(error))
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
            "playlists": self.list_playlists(false).unwrap_or_default(),
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

pub struct MpvRuntime {
    process: MpvProcess,
    ipc: MpvIpcClient,
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
    pub fn new(config: MediaConfig) -> Self {
        let socket_path = config.mpv_socket.clone();
        Self {
            process: MpvProcess::new(config),
            ipc: MpvIpcClient::new(socket_path),
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
                if self.playback_state != PlaybackState::Playing {
                    self.playback_state = PlaybackState::Playing;
                    events.push(MediaRuntimeEvent::PlaybackStateChanged(
                        PlaybackState::Playing,
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
    fn start(&mut self) -> Result<()> {
        if self.connected {
            return Ok(());
        }
        self.process.spawn()?;
        self.ipc.connect()?;
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
        self.command(&[json!("set_property"), json!("pause"), json!(false)])
    }

    fn pause(&mut self) -> Result<()> {
        self.command(&[json!("set_property"), json!("pause"), json!(true)])
    }

    fn stop_playback(&mut self) -> Result<()> {
        self.command(&[json!("stop")])
    }

    fn next_track(&mut self) -> Result<()> {
        self.command(&[json!("playlist-next")])
    }

    fn previous_track(&mut self) -> Result<()> {
        self.command(&[json!("playlist-prev")])
    }

    fn set_volume(&mut self, volume: i32) -> Result<()> {
        self.command(&[
            json!("set_property"),
            json!("volume"),
            json!(volume.clamp(0, 100)),
        ])
    }

    fn get_volume(&mut self) -> Result<Option<i32>> {
        Ok(self
            .get_property("volume")?
            .and_then(|value| value.as_i64().map(|value| value as i32)))
    }

    fn set_audio_device(&mut self, device: &str) -> Result<()> {
        self.command(&[json!("set_property"), json!("audio-device"), json!(device)])
    }

    fn load_tracks(&mut self, uris: &[String]) -> Result<()> {
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
        self.command(&[json!("loadlist"), json!(path), json!("replace")])
    }

    fn drain_events(&mut self) -> Result<Vec<MediaRuntimeEvent>> {
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
