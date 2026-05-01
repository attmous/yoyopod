use std::io;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::thread;
use std::time::Duration;

use thiserror::Error;

const PPPD_BINARY_CANDIDATES: [&str; 3] = ["pppd", "/usr/sbin/pppd", "/sbin/pppd"];
const SUDO_BINARY_CANDIDATES: [&str; 3] = ["sudo", "/usr/bin/sudo", "/bin/sudo"];
const CONNECT_CHAT_SCRIPT: &str = "chat -v '' AT OK 'ATD*99#' CONNECT";

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PppLaunchConfig {
    pub serial_port: String,
    pub baud_rate: u32,
    pub pppd_path: PathBuf,
    pub sudo_path: Option<PathBuf>,
    pub is_root: bool,
    pub manage_default_route: bool,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PppCommandPlan {
    pub argv: Vec<String>,
    pub manage_default_route: bool,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum LinkWaitOutcome {
    LinkUp,
    ProcessExited,
    TimedOut,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ShutdownOutcome {
    NoProcess,
    Graceful,
    Killed,
}

#[derive(Debug, Error, PartialEq, Eq)]
pub enum PppCommandError {
    #[error("pppd requires root privileges, but sudo was not found")]
    MissingSudo,
}

pub trait PppProcessHandle {
    fn pid(&self) -> u32;
    fn is_running(&mut self) -> bool;
    fn terminate(&mut self) -> io::Result<()>;
    fn kill(&mut self) -> io::Result<()>;
}

pub trait PppLinkProbe {
    fn ppp0_exists(&mut self) -> bool;
}

pub trait Sleeper {
    fn sleep(&mut self, duration: Duration);
}

#[derive(Debug, Default, Clone, Copy)]
pub struct ThreadSleeper;

impl Sleeper for ThreadSleeper {
    fn sleep(&mut self, duration: Duration) {
        thread::sleep(duration);
    }
}

#[derive(Debug, Clone)]
pub struct PathPppLinkProbe {
    path: PathBuf,
}

impl Default for PathPppLinkProbe {
    fn default() -> Self {
        Self {
            path: PathBuf::from("/sys/class/net/ppp0"),
        }
    }
}

impl PathPppLinkProbe {
    pub fn new(path: impl Into<PathBuf>) -> Self {
        Self { path: path.into() }
    }
}

impl PppLinkProbe for PathPppLinkProbe {
    fn ppp0_exists(&mut self) -> bool {
        self.path.exists()
    }
}

#[derive(Debug)]
pub struct PppLifecycle<P, L, S> {
    process: Option<P>,
    link_probe: L,
    sleeper: S,
}

impl<P, L, S> PppLifecycle<P, L, S> {
    pub fn new(link_probe: L, sleeper: S) -> Self {
        Self {
            process: None,
            link_probe,
            sleeper,
        }
    }

    pub fn with_process(process: P, link_probe: L, sleeper: S) -> Self {
        Self {
            process: Some(process),
            link_probe,
            sleeper,
        }
    }

    pub fn replace_process(&mut self, process: P) -> Option<P> {
        self.process.replace(process)
    }

    pub fn take_process(&mut self) -> Option<P> {
        self.process.take()
    }
}

impl<P, L, S> PppLifecycle<P, L, S>
where
    P: PppProcessHandle,
{
    pub fn current_pid(&self) -> Option<u32> {
        self.process.as_ref().map(PppProcessHandle::pid)
    }

    pub fn is_alive(&mut self) -> bool {
        self.process
            .as_mut()
            .is_some_and(PppProcessHandle::is_running)
    }
}

impl<P, L, S> PppLifecycle<P, L, S>
where
    P: PppProcessHandle,
    L: PppLinkProbe,
    S: Sleeper,
{
    pub fn wait_for_link(&mut self, timeout: Duration, poll_interval: Duration) -> LinkWaitOutcome {
        if self.process.is_none() {
            return LinkWaitOutcome::ProcessExited;
        }

        let mut elapsed = Duration::ZERO;
        loop {
            if !self.is_alive() {
                return LinkWaitOutcome::ProcessExited;
            }
            if self.link_probe.ppp0_exists() {
                return LinkWaitOutcome::LinkUp;
            }
            if elapsed >= timeout {
                return LinkWaitOutcome::TimedOut;
            }
            self.sleeper.sleep(poll_interval);
            elapsed = elapsed.saturating_add(poll_interval);
        }
    }

    pub fn shutdown(
        &mut self,
        grace_period: Duration,
        poll_interval: Duration,
    ) -> io::Result<ShutdownOutcome> {
        let Some(process) = self.process.as_mut() else {
            return Ok(ShutdownOutcome::NoProcess);
        };
        process.terminate()?;
        if !process.is_running() {
            self.process = None;
            return Ok(ShutdownOutcome::Graceful);
        }

        let mut elapsed = Duration::ZERO;
        while elapsed < grace_period {
            self.sleeper.sleep(poll_interval);
            elapsed = elapsed.saturating_add(poll_interval);
            if self
                .process
                .as_mut()
                .is_some_and(|process| !process.is_running())
            {
                self.process = None;
                return Ok(ShutdownOutcome::Graceful);
            }
        }

        if let Some(process) = self.process.as_mut() {
            process.kill()?;
        }
        self.process = None;
        Ok(ShutdownOutcome::Killed)
    }

    pub fn respawn<F>(
        &mut self,
        grace_period: Duration,
        poll_interval: Duration,
        spawn: F,
    ) -> io::Result<()>
    where
        F: FnOnce() -> io::Result<P>,
    {
        let _ = self.shutdown(grace_period, poll_interval)?;
        self.process = Some(spawn()?);
        Ok(())
    }
}

pub fn resolve_pppd_binary() -> Option<PathBuf> {
    resolve_pppd_binary_with(
        |candidate| which_path(candidate),
        |candidate| Path::new(candidate).exists(),
    )
}

pub fn resolve_sudo_binary() -> Option<PathBuf> {
    resolve_sudo_binary_with(
        |candidate| which_path(candidate),
        |candidate| Path::new(candidate).exists(),
    )
}

pub fn resolve_pppd_binary_with<F, G>(which: F, exists: G) -> Option<PathBuf>
where
    F: Fn(&str) -> Option<PathBuf>,
    G: Fn(&str) -> bool,
{
    resolve_binary_with(&PPPD_BINARY_CANDIDATES, which, exists)
}

pub fn resolve_sudo_binary_with<F, G>(which: F, exists: G) -> Option<PathBuf>
where
    F: Fn(&str) -> Option<PathBuf>,
    G: Fn(&str) -> bool,
{
    resolve_binary_with(&SUDO_BINARY_CANDIDATES, which, exists)
}

pub fn should_manage_default_route(route_output: &str) -> bool {
    for line in route_output.lines() {
        let tokens: Vec<_> = line.split_whitespace().collect();
        let Some(dev_index) = tokens.iter().position(|token| *token == "dev") else {
            continue;
        };
        let Some(interface) = tokens.get(dev_index + 1) else {
            continue;
        };
        if !interface.starts_with("ppp") {
            return false;
        }
    }
    true
}

pub fn should_manage_default_route_from_system() -> bool {
    let Ok(output) = Command::new("ip")
        .args(["-o", "route", "show", "default"])
        .output()
    else {
        return true;
    };
    if !output.status.success() {
        return true;
    }
    should_manage_default_route(&String::from_utf8_lossy(&output.stdout))
}

pub fn build_command_plan(config: &PppLaunchConfig) -> Result<PppCommandPlan, PppCommandError> {
    Ok(PppCommandPlan {
        argv: build_pppd_command(config)?,
        manage_default_route: config.manage_default_route,
    })
}

pub fn build_pppd_command(config: &PppLaunchConfig) -> Result<Vec<String>, PppCommandError> {
    let mut argv = Vec::new();
    if !config.is_root {
        let sudo_path = config
            .sudo_path
            .as_ref()
            .ok_or(PppCommandError::MissingSudo)?;
        argv.push(sudo_path.display().to_string());
        argv.push("-n".to_string());
    }

    argv.push(config.pppd_path.display().to_string());
    argv.extend([
        config.serial_port.clone(),
        config.baud_rate.to_string(),
        "nodetach".to_string(),
        "noauth".to_string(),
        "persist".to_string(),
        "connect".to_string(),
        CONNECT_CHAT_SCRIPT.to_string(),
    ]);

    if config.manage_default_route {
        argv.push("defaultroute".to_string());
        argv.push("usepeerdns".to_string());
    }

    Ok(argv)
}

fn resolve_binary_with<F, G>(candidates: &[&str], which: F, exists: G) -> Option<PathBuf>
where
    F: Fn(&str) -> Option<PathBuf>,
    G: Fn(&str) -> bool,
{
    for candidate in candidates {
        if let Some(resolved) = which(candidate) {
            return Some(resolved);
        }
        if candidate.starts_with('/') && exists(candidate) {
            return Some(PathBuf::from(candidate));
        }
    }
    None
}

fn which_path(candidate: &str) -> Option<PathBuf> {
    if candidate.contains('/') {
        return Path::new(candidate)
            .exists()
            .then(|| PathBuf::from(candidate));
    }

    let path = std::env::var_os("PATH")?;
    for directory in std::env::split_paths(&path) {
        let candidate_path = directory.join(candidate);
        if candidate_path.exists() {
            return Some(candidate_path);
        }
    }
    None
}
