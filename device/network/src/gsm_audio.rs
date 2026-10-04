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

use std::os::unix::process::CommandExt;

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

pub struct PreparedUsbPcm {
    receiver: Box<dyn serialport::SerialPort>,
    transmitter: Box<dyn serialport::SerialPort>,
    pub port: std::path::PathBuf,
    sample_rate: u32,
}

fn relay_command(kind: &str, sample_rate: u32) -> Result<Command> {
    let mut command = Command::new(std::env::current_exe()?);
    command.args([
        "--gsm-audio-relay-parent",
        &std::process::id().to_string(),
        "--gsm-audio-relay",
        kind,
        "--gsm-audio-sample-rate",
        &sample_rate.to_string(),
    ]);
    command.process_group(0).stderr(Stdio::inherit());
    Ok(command)
}
impl UsbPcmAudio {
    pub fn available() -> bool {
        interface_port("if04").is_some()
            && Path::new("/usr/bin/arecord").exists()
            && Path::new("/usr/bin/aplay").exists()
    }

    /// Prepare USB only. Never opens microphone/speaker or sends modem AT commands.
    pub fn prepare(sample_rate: u32) -> Result<PreparedUsbPcm> {
        anyhow::ensure!(Self::available(), "GSM USB PCM or ALSA tools unavailable");
        anyhow::ensure!(
            matches!(sample_rate, 8000 | 16000),
            "Explicit GSM PCM format required"
        );
        let port = interface_port("if04").context("No modem USB audio port")?;
        let receiver = serialport::new(&port, 921_600)
            .timeout(Duration::from_millis(100))
            .open()?;
        let transmitter = receiver.try_clone()?;
        Ok(PreparedUsbPcm {
            receiver,
            transmitter,
            port: std::fs::canonicalize(port)?,
            sample_rate,
        })
    }

    pub fn start(prepared: PreparedUsbPcm) -> Result<Self> {
        let PreparedUsbPcm {
            mut receiver,
            mut transmitter,
            sample_rate,
            ..
        } = prepared;
        let mut recording = relay_command("capture", sample_rate)?
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .spawn()
            .context("Open call microphone")?;
        let mut playback = match relay_command("playback", sample_rate)?
            .stdin(Stdio::piped())
            .stdout(Stdio::null())
            .spawn()
        {
            Ok(child) => child,
            Err(error) => {
                let _ = recording.kill();
                let _ = recording.wait();
                return Err(error.into());
            }
        };
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
    }
}
