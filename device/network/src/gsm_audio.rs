use std::io::{self, Read, Write};
use std::path::Path;
use std::process::{Child, Command, Stdio};
use std::sync::{
    atomic::{AtomicBool, Ordering},
    Arc,
};
use std::thread::{self, JoinHandle};
use std::time::{Duration, Instant};

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
    threads: Vec<JoinHandle<Result<()>>>,
}

/// Serial writes can be short or briefly time out while USB queues drain.
/// Keep the unwritten suffix so retrying neither loses nor repeats PCM bytes.
fn write_pcm(
    output: &mut impl Write,
    samples: &[u8],
    stop: &AtomicBool,
    stall_timeout: Duration,
) -> io::Result<()> {
    let mut remaining = samples;
    let mut last_progress = Instant::now();
    while !remaining.is_empty() && !stop.load(Ordering::Relaxed) {
        match output.write(remaining) {
            Ok(0) => return Err(io::ErrorKind::WriteZero.into()),
            Ok(count) => {
                remaining = &remaining[count..];
                last_progress = Instant::now();
            }
            Err(error)
                if matches!(
                    error.kind(),
                    io::ErrorKind::Interrupted
                        | io::ErrorKind::TimedOut
                        | io::ErrorKind::WouldBlock
                ) =>
            {
                if last_progress.elapsed() >= stall_timeout {
                    return Err(error);
                }
                thread::sleep(Duration::from_millis(2));
            }
            Err(error) => return Err(error),
        }
    }
    Ok(())
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
                "--buffer-time=100000",
                "--period-time=20000",
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
            .stderr(Stdio::inherit())
            .spawn()
            .context("Open call microphone")?;
        let mut playback = match Command::new("/usr/bin/aplay")
            .args([
                "-q",
                "-D",
                "playback",
                "--buffer-time=100000",
                "--period-time=20000",
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
            .stderr(Stdio::inherit())
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
                let count = match capture.read(&mut samples) {
                    Ok(count) => count,
                    Err(error) if error.kind() == io::ErrorKind::Interrupted => continue,
                    Err(error) => return Err(error).context("Read GSM microphone samples"),
                };
                if count == 0 {
                    if capture_stop.load(Ordering::Relaxed) {
                        break;
                    }
                    bail!("GSM microphone stream ended");
                }
                if capture_muted.load(Ordering::Relaxed) {
                    samples[..count].fill(0);
                }
                write_pcm(
                    &mut transmitter,
                    &samples[..count],
                    &capture_stop,
                    Duration::from_secs(2),
                )
                .context("Write GSM microphone samples to USB")?;
            }
            Ok(())
        });
        let playback_stop = stop.clone();
        let playback_thread = thread::spawn(move || {
            let mut samples = [0_u8; 320];
            while !playback_stop.load(Ordering::Relaxed) {
                match receiver.read(&mut samples) {
                    Ok(0) => {}
                    Ok(count) => {
                        output
                            .write_all(&samples[..count])
                            .context("Write GSM speaker samples")?;
                    }
                    Err(error)
                        if matches!(
                            error.kind(),
                            io::ErrorKind::TimedOut
                                | io::ErrorKind::Interrupted
                                | io::ErrorKind::WouldBlock
                        ) => {}
                    Err(error) => return Err(error).context("Read GSM speaker samples from USB"),
                }
            }
            Ok(())
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
        if let Some(status) = self.recording.try_wait()? {
            bail!("GSM microphone process exited: {status}");
        }
        if let Some(status) = self.playback.try_wait()? {
            bail!("GSM speaker process exited: {status}");
        }
        if let Some(index) = self.threads.iter().position(|thread| thread.is_finished()) {
            self.threads
                .swap_remove(index)
                .join()
                .map_err(|_| anyhow::anyhow!("GSM audio bridge thread panicked"))??;
            return Ok(false);
        }
        Ok(true)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::VecDeque;

    struct InterruptedUsb {
        steps: VecDeque<io::Result<usize>>,
        written: Vec<u8>,
    }

    impl Write for InterruptedUsb {
        fn write(&mut self, samples: &[u8]) -> io::Result<usize> {
            let count = self.steps.pop_front().unwrap_or(Ok(samples.len()))?;
            self.written.extend_from_slice(&samples[..count]);
            Ok(count)
        }
        fn flush(&mut self) -> io::Result<()> {
            Ok(())
        }
    }

    #[test]
    fn pcm_survives_usb_timeouts_and_short_writes_without_repeating_samples() {
        let samples = [1, 2, 3, 4, 5, 6];
        let mut usb = InterruptedUsb {
            steps: VecDeque::from([
                Ok(1),
                Err(io::ErrorKind::TimedOut.into()),
                Err(io::ErrorKind::Interrupted.into()),
                Ok(2),
                Err(io::ErrorKind::WouldBlock.into()),
            ]),
            written: Vec::new(),
        };
        write_pcm(
            &mut usb,
            &samples,
            &AtomicBool::new(false),
            Duration::from_secs(1),
        )
        .unwrap();
        assert_eq!(usb.written, samples);
    }

    #[test]
    fn pcm_does_not_retry_disconnected_usb_or_stall_forever() {
        for kind in [io::ErrorKind::BrokenPipe, io::ErrorKind::TimedOut] {
            let mut usb = InterruptedUsb {
                steps: VecDeque::from([Err(kind.into()), Ok(2)]),
                written: Vec::new(),
            };
            let error =
                write_pcm(&mut usb, &[1, 2], &AtomicBool::new(false), Duration::ZERO).unwrap_err();
            assert_eq!(error.kind(), kind);
            assert!(usb.written.is_empty());
            assert_eq!(usb.steps.len(), 1);
        }
    }

    #[test]
    fn stopping_pcm_cancels_pending_microphone_output() {
        struct StopDuringWrite {
            stop: Arc<AtomicBool>,
            writes: usize,
        }
        impl Write for StopDuringWrite {
            fn write(&mut self, _: &[u8]) -> io::Result<usize> {
                self.writes += 1;
                self.stop.store(true, Ordering::Relaxed);
                Err(io::ErrorKind::TimedOut.into())
            }
            fn flush(&mut self) -> io::Result<()> {
                Ok(())
            }
        }
        let stop = Arc::new(AtomicBool::new(false));
        let mut output = StopDuringWrite {
            stop: stop.clone(),
            writes: 0,
        };
        write_pcm(&mut output, &[1, 2], &stop, Duration::from_secs(1)).unwrap();
        assert_eq!(output.writes, 1);
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
