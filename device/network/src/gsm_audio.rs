use std::io::{Read, Write};
use std::path::Path;
use std::process::{Child, Command, Stdio};
use std::sync::{
    atomic::{AtomicBool, Ordering},
    Arc,
};
use std::thread::{self, JoinHandle};
use std::time::Duration;

use anyhow::{bail, Context, Result};

use crate::transport::{LineTransport, SerialLineTransport};

/// SIM7600 USB PCM is signed 16-bit mono at 8 or 16 kHz. The modem's USB audio
/// interface is distinct from its AT and packet-data interfaces. ALSA's named
/// capture/playback routes preserve the device's existing audio selection.
pub struct UsbPcmAudio {
    stop: Arc<AtomicBool>,
    muted: Arc<AtomicBool>,
    recording: Child,
    playback: Child,
    threads: Vec<JoinHandle<()>>,
}

fn interface_port(interface: &str) -> Option<String> {
    let directory = Path::new("/dev/serial/by-id");
    std::fs::read_dir(directory)
        .ok()?
        .filter_map(Result::ok)
        .find_map(|entry| {
            let name = entry.file_name().to_string_lossy().into_owned();
            (name.contains("SimTech") && name.ends_with(&format!("-{interface}-port0")))
                .then(|| entry.path().display().to_string())
        })
}

fn pcm_command(command: &str) -> Result<String> {
    let at_port = interface_port("if02").context("No modem AT port")?;
    let mut transport = SerialLineTransport::new(at_port, 115_200, Duration::from_secs(2));
    transport.open()?;
    let response = transport.send_command(command, None)?;
    if !response.lines().any(|line| line.trim() == "OK") {
        bail!("USB call audio unavailable");
    }
    Ok(response)
}

impl UsbPcmAudio {
    pub fn available() -> bool {
        interface_port("if02").is_some()
            && interface_port("if04").is_some()
            && Path::new("/usr/bin/arecord").exists()
            && Path::new("/usr/bin/aplay").exists()
    }

    pub fn start() -> Result<Self> {
        let port = interface_port("if04").context("No modem USB audio port")?;
        let mut receiver = serialport::new(port, 921_600)
            .timeout(Duration::from_millis(100))
            .open()?;
        let mut transmitter = receiver.try_clone()?;
        let sample_rate = match pcm_command("AT+CPCMFRM?") {
            Ok(response) if response.lines().any(|line| line.starts_with("+CPCMFRM: 1")) => "16000",
            _ => "8000",
        };
        let mut recording = Command::new("/usr/bin/arecord")
            .args([
                "-q",
                "-D",
                "capture",
                "-t",
                "raw",
                "-f",
                "S16_LE",
                "-r",
                sample_rate,
                "-c",
                "1",
            ])
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .spawn()
            .context("Open call microphone")?;
        let mut playback = match Command::new("/usr/bin/aplay")
            .args([
                "-q",
                "-D",
                "playback",
                "-t",
                "raw",
                "-f",
                "S16_LE",
                "-r",
                sample_rate,
                "-c",
                "1",
            ])
            .stdin(Stdio::piped())
            .stderr(Stdio::null())
            .spawn()
        {
            Ok(child) => child,
            Err(error) => {
                let _ = recording.kill();
                let _ = recording.wait();
                return Err(error.into());
            }
        };
        if let Err(error) = pcm_command("AT+CPCMREG=1") {
            let _ = recording.kill();
            let _ = recording.wait();
            let _ = playback.kill();
            let _ = playback.wait();
            return Err(error);
        }
        let stop = Arc::new(AtomicBool::new(false));
        let muted = Arc::new(AtomicBool::new(false));
        let mut capture = recording
            .stdout
            .take()
            .context("Missing microphone stream")?;
        let mut output = playback.stdin.take().context("Missing speaker stream")?;
        let capture_stop = stop.clone();
        let capture_muted = muted.clone();
        let capture_thread = thread::spawn(move || {
            let mut samples = [0_u8; 320];
            while !capture_stop.load(Ordering::Relaxed) {
                let Ok(count) = capture.read(&mut samples) else {
                    break;
                };
                if count == 0 {
                    break;
                }
                if capture_muted.load(Ordering::Relaxed) {
                    samples[..count].fill(0);
                }
                if transmitter.write_all(&samples[..count]).is_err() {
                    break;
                }
            }
        });
        let playback_stop = stop.clone();
        let playback_thread = thread::spawn(move || {
            let mut samples = [0_u8; 320];
            while !playback_stop.load(Ordering::Relaxed) {
                match receiver.read(&mut samples) {
                    Ok(0) => {}
                    Ok(count) => {
                        if output.write_all(&samples[..count]).is_err() {
                            break;
                        }
                    }
                    Err(error) if error.kind() == std::io::ErrorKind::TimedOut => {}
                    Err(_) => break,
                }
            }
        });
        Ok(Self {
            stop,
            muted,
            recording,
            playback,
            threads: vec![capture_thread, playback_thread],
        })
    }

    pub fn set_mute(&self, muted: bool) {
        self.muted.store(muted, Ordering::Relaxed);
    }

    pub fn healthy(&mut self) -> Result<bool> {
        Ok(self.recording.try_wait()?.is_none()
            && self.playback.try_wait()?.is_none()
            && self.threads.iter().all(|thread| !thread.is_finished()))
    }
}

impl Drop for UsbPcmAudio {
    fn drop(&mut self) {
        self.stop.store(true, Ordering::Relaxed);
        let _ = self.recording.kill();
        let _ = self.recording.wait();
        let _ = self.playback.kill();
        let _ = self.playback.wait();
        for thread in self.threads.drain(..) {
            let _ = thread.join();
        }
        let _ = pcm_command("AT+CPCMREG=0");
    }
}
