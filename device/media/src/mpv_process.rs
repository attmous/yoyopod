use std::fs;
use std::io;
use std::path::Path;
use std::process::{Child, Command, Stdio};

use crate::config::MediaConfig;

pub trait ProcessHandle: Send {
    fn id(&self) -> u32;
    fn is_alive(&self) -> bool;
    fn kill(&mut self) -> io::Result<()>;
}

pub trait ProcessSpawner: Send + Sync {
    fn spawn(&self, command: &[String]) -> io::Result<Box<dyn ProcessHandle>>;
}

struct StdProcessSpawner;

struct StdProcessHandle {
    id: u32,
    child: std::sync::Mutex<Child>,
}

impl ProcessHandle for StdProcessHandle {
    fn id(&self) -> u32 {
        self.id
    }

    fn is_alive(&self) -> bool {
        self.child
            .lock()
            .expect("child")
            .try_wait()
            .ok()
            .flatten()
            .is_none()
    }

    fn kill(&mut self) -> io::Result<()> {
        let mut child = self.child.lock().expect("child");
        if child.try_wait()?.is_none() {
            child.kill()?;
        }
        let _ = child.wait();
        Ok(())
    }
}

impl ProcessSpawner for StdProcessSpawner {
    fn spawn(&self, command: &[String]) -> io::Result<Box<dyn ProcessHandle>> {
        let mut args = command.iter();
        let program = args.next().ok_or_else(|| {
            io::Error::new(io::ErrorKind::InvalidInput, "mpv command must not be empty")
        })?;
        let mut child = Command::new(program);
        child.args(args);
        child.stdout(Stdio::null());
        child.stderr(Stdio::null());
        let child = child.spawn()?;
        let id = child.id();
        Ok(Box::new(StdProcessHandle {
            id,
            child: std::sync::Mutex::new(child),
        }))
    }
}

pub struct MpvProcess {
    config: MediaConfig,
    spawner: Box<dyn ProcessSpawner>,
    process: Option<Box<dyn ProcessHandle>>,
}

impl MpvProcess {
    pub fn new(config: MediaConfig) -> Self {
        Self::with_spawner(config, Box::new(StdProcessSpawner))
    }

    pub fn with_spawner(config: MediaConfig, spawner: Box<dyn ProcessSpawner>) -> Self {
        Self {
            config,
            spawner,
            process: None,
        }
    }

    pub fn command(&self) -> Vec<String> {
        vec![
            self.config.mpv_binary.clone(),
            "--idle".to_string(),
            "--no-video".to_string(),
            format!("--input-ipc-server={}", self.config.mpv_socket),
            format!("--audio-device=alsa/{}", self.config.alsa_device),
        ]
    }

    pub fn spawn(&mut self) -> io::Result<()> {
        if self.is_alive() {
            return Ok(());
        }
        self.clean_stale_socket();
        self.process = Some(self.spawner.spawn(&self.command())?);
        Ok(())
    }

    pub fn is_alive(&self) -> bool {
        self.process
            .as_ref()
            .map(|process| process.is_alive())
            .unwrap_or(false)
    }

    pub fn stop(&mut self) -> io::Result<()> {
        if let Some(mut process) = self.process.take() {
            process.kill()?;
        }
        self.clean_stale_socket();
        Ok(())
    }

    pub fn respawn(&mut self) -> io::Result<()> {
        self.stop()?;
        self.spawn()
    }

    fn clean_stale_socket(&self) {
        if self.config.mpv_socket.starts_with("\\\\.\\pipe\\") {
            return;
        }
        let path = Path::new(&self.config.mpv_socket);
        if path.exists() {
            let _ = fs::remove_file(path);
        }
    }
}
