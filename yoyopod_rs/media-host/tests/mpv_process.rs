use std::io;
use std::sync::{Arc, Mutex};

use yoyopod_media_host::config::MediaConfig;
use yoyopod_media_host::mpv_process::{MpvProcess, ProcessHandle, ProcessSpawner};

#[derive(Debug, Default, Clone)]
struct FakeSpawner {
    state: Arc<Mutex<FakeSpawnerState>>,
}

#[derive(Debug, Default)]
struct FakeSpawnerState {
    commands: Vec<Vec<String>>,
    kill_calls: usize,
    next_id: u32,
    alive: bool,
}

struct FakeHandle {
    state: Arc<Mutex<FakeSpawnerState>>,
    id: u32,
}

impl ProcessHandle for FakeHandle {
    fn id(&self) -> u32 {
        self.id
    }

    fn is_alive(&self) -> bool {
        self.state.lock().expect("state").alive
    }

    fn kill(&mut self) -> io::Result<()> {
        let mut state = self.state.lock().expect("state");
        state.kill_calls += 1;
        state.alive = false;
        Ok(())
    }
}

impl ProcessSpawner for FakeSpawner {
    fn spawn(&self, command: &[String]) -> io::Result<Box<dyn ProcessHandle>> {
        let mut state = self.state.lock().expect("state");
        state.commands.push(command.to_vec());
        state.next_id += 1;
        state.alive = true;
        Ok(Box::new(FakeHandle {
            state: Arc::clone(&self.state),
            id: state.next_id,
        }))
    }
}

fn config() -> MediaConfig {
    MediaConfig {
        music_dir: "/srv/music".to_string(),
        mpv_socket: "/tmp/yoyopod-mpv.sock".to_string(),
        mpv_binary: "mpv".to_string(),
        alsa_device: "default".to_string(),
        default_volume: 100,
        recent_tracks_file: "data/media/recent_tracks.json".to_string(),
        remote_cache_dir: "data/media/remote_cache".to_string(),
        remote_cache_max_bytes: 1024,
    }
}

#[test]
fn spawn_builds_expected_mpv_command() {
    let spawner = FakeSpawner::default();
    let mut process = MpvProcess::with_spawner(config(), Box::new(spawner.clone()));

    process.spawn().expect("spawn");

    let commands = spawner.state.lock().expect("state").commands.clone();
    assert_eq!(commands.len(), 1);
    assert_eq!(commands[0][0], "mpv");
    assert!(commands[0].contains(&"--idle".to_string()));
    assert!(commands[0].contains(&"--no-video".to_string()));
    assert!(commands[0].contains(&"--input-ipc-server=/tmp/yoyopod-mpv.sock".to_string()));
    assert!(commands[0].contains(&"--audio-device=alsa/default".to_string()));
}

#[test]
fn stop_kills_running_process() {
    let spawner = FakeSpawner::default();
    let mut process = MpvProcess::with_spawner(config(), Box::new(spawner.clone()));
    process.spawn().expect("spawn");

    process.stop().expect("stop");

    let state = spawner.state.lock().expect("state");
    assert_eq!(state.kill_calls, 1);
    assert!(!state.alive);
}

#[test]
fn respawn_kills_then_starts_new_process() {
    let spawner = FakeSpawner::default();
    let mut process = MpvProcess::with_spawner(config(), Box::new(spawner.clone()));
    process.spawn().expect("spawn");

    process.respawn().expect("respawn");

    let state = spawner.state.lock().expect("state");
    assert_eq!(state.kill_calls, 1);
    assert_eq!(state.commands.len(), 2);
    assert!(state.alive);
}
