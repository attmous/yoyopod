use crate::mpv_process::{ProcessHandle, ProcessSpawner, StdProcessSpawner};
use yoyopod_protocol::call::RingtoneRequest;

pub struct RingtonePlayer {
    process: Option<Box<dyn ProcessHandle>>,
    session: Option<RingtoneRequest>,
    retired_generation: u64,
    lease_deadline_ms: u64,
    spawner: Box<dyn ProcessSpawner>,
}

impl Default for RingtonePlayer {
    fn default() -> Self {
        Self::new()
    }
}

impl RingtonePlayer {
    pub fn new() -> Self {
        Self::with_spawner(Box::new(StdProcessSpawner))
    }
    fn with_spawner(spawner: Box<dyn ProcessSpawner>) -> Self {
        Self {
            process: None,
            session: None,
            retired_generation: 0,
            lease_deadline_ms: 0,
            spawner,
        }
    }
    pub fn start(
        &mut self,
        request: &RingtoneRequest,
        output: &str,
        volume: u8,
        now_ms: u64,
        lease_ms: u64,
    ) -> Result<(), String> {
        if request.operation_generation <= self.retired_generation {
            return Err("retired ringtone operation".into());
        }
        if self.session.as_ref().is_some_and(|s| {
            s.key == request.key && s.operation_generation == request.operation_generation
        }) {
            return Ok(());
        }
        if self
            .session
            .as_ref()
            .is_some_and(|s| s.operation_generation >= request.operation_generation)
        {
            return Err("stale ringtone start".into());
        }
        self.shutdown()?;
        if lease_ms == 0 {
            return Err("ringtone requires finite lease".into());
        }
        if volume > 0 {
            let path = cached_wav()?;
            let command = vec![
                "mpv".into(),
                "--no-video".into(),
                "--no-config".into(),
                "--loop-file=inf".into(),
                format!("--length={:.3}", lease_ms as f64 / 1000.0),
                format!("--audio-device={output}"),
                format!("--volume={}", volume.min(100)),
                path,
            ];
            self.process = Some(
                self.spawner
                    .spawn_leased(&command, lease_ms)
                    .map_err(|e| e.to_string())?,
            );
        }
        self.session = Some(request.clone());
        self.lease_deadline_ms = now_ms.saturating_add(lease_ms);
        Ok(())
    }
    pub fn stop(&mut self, request: &RingtoneRequest) -> Result<(), String> {
        self.retired_generation = self.retired_generation.max(request.operation_generation);
        if self.session.as_ref().is_some_and(|s| {
            s.key == request.key && s.operation_generation == request.operation_generation
        }) {
            self.shutdown()?;
        }
        Ok(())
    }
    pub fn tick(&mut self, now_ms: u64) -> Result<(), String> {
        if self
            .process
            .as_ref()
            .is_some_and(|process| !process.is_alive())
        {
            self.shutdown()?;
            return Err("ringtone helper exited before lease expiry".into());
        }
        if self.session.is_some() && now_ms >= self.lease_deadline_ms {
            self.shutdown()?;
        }
        Ok(())
    }
    pub fn shutdown(&mut self) -> Result<(), String> {
        if let Some(process) = self.process.as_mut() {
            process.kill().map_err(|e| e.to_string())?;
        }
        self.process = None;
        if let Some(session) = self.session.take() {
            self.retired_generation = self.retired_generation.max(session.operation_generation);
        }
        Ok(())
    }
    pub fn active(&self) -> bool {
        self.session.is_some()
    }
    pub fn set_output(&mut self, output: &str, volume: u8, now_ms: u64) -> Result<(), String> {
        let Some(request) = self.session.clone() else {
            return Ok(());
        };
        let lease = self.lease_deadline_ms.saturating_sub(now_ms);
        if lease == 0 {
            return self.shutdown();
        }
        if let Some(process) = self.process.as_mut() {
            process.kill().map_err(|e| e.to_string())?;
        }
        self.process = None;
        self.session = None;
        self.start(&request, output, volume, now_ms, lease)
    }
}

impl Drop for RingtonePlayer {
    fn drop(&mut self) {
        let _ = self.shutdown();
    }
}

fn cached_wav() -> Result<String, String> {
    // Deterministic mono PCM: a soft 440 Hz pulse followed by silence.
    let path = std::env::temp_dir().join(format!("yoyopod-ring-v1-{}.wav", std::process::id()));
    if !path.exists() {
        let samples = 16_000u32;
        let data_len = samples * 2;
        let mut wav = Vec::with_capacity((44 + data_len) as usize);
        wav.extend(b"RIFF");
        wav.extend((36 + data_len).to_le_bytes());
        wav.extend(b"WAVEfmt ");
        wav.extend(16u32.to_le_bytes());
        wav.extend(1u16.to_le_bytes());
        wav.extend(1u16.to_le_bytes());
        wav.extend(16_000u32.to_le_bytes());
        wav.extend(32_000u32.to_le_bytes());
        wav.extend(2u16.to_le_bytes());
        wav.extend(16u16.to_le_bytes());
        wav.extend(b"data");
        wav.extend(data_len.to_le_bytes());
        for n in 0..samples {
            let envelope = if n < 6_400 {
                (n.min(6_400 - n).min(320) as f64) / 320.0
            } else {
                0.0
            };
            let sample =
                (envelope * 8_000.0 * (std::f64::consts::TAU * 440.0 * n as f64 / 16_000.0).sin())
                    as i16;
            wav.extend(sample.to_le_bytes());
        }
        std::fs::write(&path, wav).map_err(|e| e.to_string())?;
    }
    Ok(path.to_string_lossy().into_owned())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::{Arc, Mutex};
    use yoyopod_protocol::call::{CallTransport, SessionKey};
    struct FakeSpawner(Arc<Mutex<Vec<String>>>);
    struct FakeProcess(Arc<Mutex<Vec<String>>>);
    impl ProcessSpawner for FakeSpawner {
        fn spawn(&self, command: &[String]) -> std::io::Result<Box<dyn ProcessHandle>> {
            self.0.lock().unwrap().push(format!("spawn:{command:?}"));
            Ok(Box::new(FakeProcess(self.0.clone())))
        }
    }
    impl ProcessHandle for FakeProcess {
        fn id(&self) -> u32 {
            1
        }
        fn is_alive(&self) -> bool {
            true
        }
        fn kill(&mut self) -> std::io::Result<()> {
            self.0.lock().unwrap().push("kill+wait".into());
            Ok(())
        }
    }
    fn request(epoch: u64) -> RingtoneRequest {
        RingtoneRequest {
            key: SessionKey {
                transport: CallTransport::Sip,
                generation: 1,
                call_id: "a".into(),
            },
            operation_generation: epoch,
            lease_ms: 0,
        }
    }
    #[test]
    fn ringtone_retirement_lease_and_shutdown_release_only_owned_helper() {
        let log = Arc::new(Mutex::new(Vec::new()));
        let mut player = RingtonePlayer::with_spawner(Box::new(FakeSpawner(log.clone())));
        player.stop(&request(1)).unwrap();
        assert!(
            player
                .start(&request(1), "alsa/default", 40, 100, 300)
                .is_err(),
            "retired starts must be rejected"
        );
        player
            .start(&request(2), "alsa/default", 40, 100, 300)
            .unwrap();
        player.stop(&request(1)).unwrap();
        assert_eq!(log.lock().unwrap().len(), 1);
        player.tick(399).unwrap();
        assert_eq!(log.lock().unwrap().len(), 1);
        player.tick(400).unwrap();
        assert_eq!(log.lock().unwrap()[1], "kill+wait");
        player.stop(&request(2)).unwrap();
        player
            .start(&request(3), "alsa/default", 40, 500, 300)
            .unwrap();
        drop(player);
        assert_eq!(log.lock().unwrap()[3], "kill+wait");
        assert!(!log.lock().unwrap()[0].contains("input-ipc-server"));
    }
    #[test]
    fn zero_volume_creates_no_helper() {
        let log = Arc::new(Mutex::new(Vec::new()));
        let mut player = RingtonePlayer::with_spawner(Box::new(FakeSpawner(log.clone())));
        player
            .start(&request(1), "alsa/default", 0, 0, 300)
            .unwrap();
        player.tick(300).unwrap();
        assert!(log.lock().unwrap().is_empty());
    }

    #[test]
    fn route_update_preserves_lease_and_cannot_restart_stopped_alert() {
        let log = Arc::new(Mutex::new(Vec::new()));
        let mut player = RingtonePlayer::with_spawner(Box::new(FakeSpawner(log.clone())));
        player.start(&request(1), "alsa/old", 40, 100, 300).unwrap();
        player.set_output("alsa/new", 30, 200).unwrap();
        assert_eq!(log.lock().unwrap()[1], "kill+wait");
        assert!(log.lock().unwrap()[2].contains("alsa/new"));
        player.tick(400).unwrap();
        assert_eq!(log.lock().unwrap()[3], "kill+wait");
        player.set_output("alsa/third", 100, 500).unwrap();
        assert_eq!(log.lock().unwrap().len(), 4);
    }
}
