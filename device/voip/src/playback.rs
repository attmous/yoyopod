use std::path::Path;
use std::process::{Child, Command, Stdio};
use std::time::Instant;

#[derive(Default)]
pub struct VoiceNotePlayback {
    current: Option<Child>,
    current_file_path: String,
    duration_ms: i32,
    elapsed_before_run_ms: u64,
    run_started_at: Option<Instant>,
    paused: bool,
    published_bucket: u64,
}

impl std::fmt::Debug for VoiceNotePlayback {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("VoiceNotePlayback")
            .field("playing", &self.is_playing())
            .field("paused", &self.is_paused())
            .field("current_file_path", &self.current_file_path)
            .finish()
    }
}

impl VoiceNotePlayback {
    pub fn command_for(file_path: &str) -> Vec<String> {
        if is_wav(file_path) {
            return vec!["aplay".to_string(), "-q".to_string(), file_path.to_string()];
        }
        vec![
            "ffplay".to_string(),
            "-nodisp".to_string(),
            "-autoexit".to_string(),
            "-loglevel".to_string(),
            "error".to_string(),
            "-af".to_string(),
            "volume=12.0dB".to_string(),
            file_path.to_string(),
        ]
    }

    pub fn play(&mut self, file_path: &str, duration_ms: i32) -> Result<(), String> {
        let file_path = file_path.trim();
        if file_path.is_empty() {
            return Err("voice-note playback requires file_path".to_string());
        }
        self.stop();
        let command = Self::command_for(file_path);
        let child = Command::new(&command[0])
            .args(&command[1..])
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()
            .map_err(|error| format!("failed to start voice-note playback: {error}"))?;
        self.current = Some(child);
        self.current_file_path = file_path.to_string();
        self.duration_ms = duration_ms.max(0);
        self.elapsed_before_run_ms = 0;
        self.run_started_at = Some(Instant::now());
        self.paused = false;
        self.published_bucket = 0;
        Ok(())
    }

    pub fn pause(&mut self) -> Result<(), String> {
        if self.current.is_none() || self.paused {
            return Ok(());
        }
        let pid = self
            .current
            .as_ref()
            .map(std::process::Child::id)
            .unwrap_or(0);
        pause_process(pid)?;
        self.elapsed_before_run_ms = self.elapsed_ms() as u64;
        self.run_started_at = None;
        self.paused = true;
        Ok(())
    }

    pub fn resume(&mut self) -> Result<(), String> {
        if self.current.is_none() || !self.paused {
            return Ok(());
        }
        let pid = self
            .current
            .as_ref()
            .map(std::process::Child::id)
            .unwrap_or(0);
        resume_process(pid)?;
        self.run_started_at = Some(Instant::now());
        self.paused = false;
        Ok(())
    }

    pub fn refresh(&mut self) -> bool {
        let Some(child) = self.current.as_mut() else {
            return false;
        };
        match child.try_wait() {
            Ok(Some(_)) => {
                self.reset();
                true
            }
            Ok(None) => {
                let bucket = (self.elapsed_ms() as u64) / 100;
                if bucket == self.published_bucket {
                    return false;
                }
                self.published_bucket = bucket;
                true
            }
            Err(_) => false,
        }
    }

    pub fn stop(&mut self) {
        if let Some(mut child) = self.current.take() {
            let _ = child.kill();
            let _ = child.wait();
        }
        self.reset();
    }

    pub fn is_playing(&self) -> bool {
        self.current.is_some() && !self.paused
    }

    pub fn is_paused(&self) -> bool {
        self.current.is_some() && self.paused
    }

    pub fn elapsed_ms(&self) -> i32 {
        let running_ms = self
            .run_started_at
            .map(|started| started.elapsed().as_millis() as u64)
            .unwrap_or_default();
        let elapsed = self.elapsed_before_run_ms.saturating_add(running_ms);
        elapsed.min(self.duration_ms.max(0) as u64) as i32
    }

    fn reset(&mut self) {
        self.current = None;
        self.current_file_path.clear();
        self.duration_ms = 0;
        self.elapsed_before_run_ms = 0;
        self.run_started_at = None;
        self.paused = false;
        self.published_bucket = 0;
    }

    pub fn payload(&self) -> serde_json::Value {
        let elapsed_ms = self.elapsed_ms();
        let progress_permille = if self.duration_ms > 0 {
            (i64::from(elapsed_ms) * 1_000 / i64::from(self.duration_ms)).clamp(0, 1_000) as i32
        } else {
            0
        };
        serde_json::json!({
            "playing": self.is_playing(),
            "paused": self.is_paused(),
            "file_path": self.current_file_path,
            "elapsed_ms": elapsed_ms,
            "duration_ms": self.duration_ms,
            "progress_permille": progress_permille,
        })
    }
}

impl Drop for VoiceNotePlayback {
    fn drop(&mut self) {
        self.stop();
    }
}

fn is_wav(file_path: &str) -> bool {
    Path::new(file_path)
        .extension()
        .and_then(|extension| extension.to_str())
        .is_some_and(|extension| extension.eq_ignore_ascii_case("wav"))
}

#[cfg(unix)]
fn pause_process(pid: u32) -> Result<(), String> {
    let result = unsafe { libc::kill(pid as libc::pid_t, libc::SIGSTOP) };
    if result == 0 {
        Ok(())
    } else {
        Err(format!(
            "failed to pause voice-note playback: {}",
            std::io::Error::last_os_error()
        ))
    }
}

#[cfg(not(unix))]
fn pause_process(_pid: u32) -> Result<(), String> {
    Err("voice-note pause is only supported on the device runtime".to_string())
}

#[cfg(unix)]
fn resume_process(pid: u32) -> Result<(), String> {
    let result = unsafe { libc::kill(pid as libc::pid_t, libc::SIGCONT) };
    if result == 0 {
        Ok(())
    } else {
        Err(format!(
            "failed to resume voice-note playback: {}",
            std::io::Error::last_os_error()
        ))
    }
}

#[cfg(not(unix))]
fn resume_process(_pid: u32) -> Result<(), String> {
    Err("voice-note resume is only supported on the device runtime".to_string())
}
