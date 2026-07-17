//! Supervise a `yoyopod-ui-host` worker over the stdin/stdout envelope
//! protocol and run the UI smoke / navigation checks against it.
//!
//! Ports `rust_runtime.py` from the deleted Python validation suite. The
//! envelope encoding comes straight from `yoyopod-protocol`, so the
//! validator cannot drift from what the workers actually speak.

use std::io::{BufRead, BufReader, Write};
use std::path::Path;
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::mpsc::{Receiver, RecvTimeoutError};
use std::thread;
use std::time::{Duration, Instant};

use anyhow::{anyhow, bail, Context, Result};
use serde_json::Value;
use yoyopod_protocol::ui::{InputAction, RuntimeSnapshot, UiCommand};
use yoyopod_protocol::WorkerEnvelope;

use crate::report::CheckResult;

const EVENT_TIMEOUT: Duration = Duration::from_secs(15);
const MAX_EVENTS_PER_WAIT: usize = 32;
const TICK_INTERVAL: Duration = Duration::from_millis(500);

pub struct UiHostSupervisor {
    child: Child,
    stdin: ChildStdin,
    events: Receiver<String>,
}

impl UiHostSupervisor {
    /// Spawn the UI host worker and hand back a supervisor for it.
    pub fn spawn(worker: &Path, hardware: &str) -> Result<Self> {
        let mut child = Command::new(worker)
            .arg("--hardware")
            .arg(hardware)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::inherit())
            .spawn()
            .with_context(|| format!("spawn UI host {}", worker.display()))?;
        let stdin = child.stdin.take().expect("stdin is piped");
        let stdout = child.stdout.take().expect("stdout is piped");
        let (sender, events) = std::sync::mpsc::channel();
        thread::spawn(move || {
            let reader = BufReader::new(stdout);
            for line in reader.lines() {
                let Ok(line) = line else { break };
                if line.trim().is_empty() {
                    continue;
                }
                if sender.send(line).is_err() {
                    break;
                }
            }
        });
        Ok(Self {
            child,
            stdin,
            events,
        })
    }

    pub fn send(&mut self, command: UiCommand) -> Result<()> {
        let encoded = command
            .into_envelope()
            .encode()
            .context("encode UI command envelope")?;
        self.stdin
            .write_all(&encoded)
            .and_then(|()| self.stdin.flush())
            .context("write UI command to worker stdin")
    }

    /// Read the next envelope the worker emits, failing after `EVENT_TIMEOUT`.
    pub fn read_event(&mut self) -> Result<WorkerEnvelope> {
        let line = match self.events.recv_timeout(EVENT_TIMEOUT) {
            Ok(line) => line,
            Err(RecvTimeoutError::Timeout) => {
                bail!(
                    "UI host emitted no event within {}s",
                    EVENT_TIMEOUT.as_secs()
                )
            }
            Err(RecvTimeoutError::Disconnected) => bail!("UI host closed its stdout"),
        };
        WorkerEnvelope::decode(line.as_bytes())
            .map_err(|error| anyhow!("decode UI host envelope: {error}; line: {line}"))
    }

    pub fn stop(mut self) {
        let _ = self.send(UiCommand::Shutdown);
        let deadline = Instant::now() + Duration::from_secs(3);
        while Instant::now() < deadline {
            match self.child.try_wait() {
                Ok(Some(_)) => return,
                Ok(None) => thread::sleep(Duration::from_millis(50)),
                Err(_) => break,
            }
        }
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}

/// Read events until one of `event_types` arrives. `ui.error` fails fast.
fn read_until(supervisor: &mut UiHostSupervisor, event_types: &[&str]) -> Result<WorkerEnvelope> {
    for _ in 0..MAX_EVENTS_PER_WAIT {
        let event = supervisor.read_event()?;
        if event.message_type == "ui.error" {
            bail!("UI host error: {}", event.payload);
        }
        if event_types.contains(&event.message_type.as_str()) {
            return Ok(event);
        }
    }
    bail!("UI host did not emit any of {event_types:?}")
}

fn expect_ready(supervisor: &mut UiHostSupervisor) -> Result<()> {
    let event = supervisor.read_event()?;
    if event.message_type != "ui.ready" {
        bail!("expected ui.ready, got {}", event.message_type);
    }
    Ok(())
}

fn expect_screen(supervisor: &mut UiHostSupervisor, screen: &str) -> Result<String> {
    let event = read_until(supervisor, &["ui.screen_changed"])?;
    let observed = event
        .payload
        .get("screen")
        .and_then(Value::as_str)
        .unwrap_or_default()
        .to_string();
    if observed != screen {
        bail!(
            "expected Rust UI screen {screen}, got {}",
            if observed.is_empty() {
                event.payload.to_string()
            } else {
                observed
            }
        );
    }
    Ok(observed)
}

fn request_health(supervisor: &mut UiHostSupervisor) -> Result<Value> {
    supervisor.send(UiCommand::Health)?;
    let event = read_until(supervisor, &["ui.health"])?;
    Ok(event.payload)
}

fn require_healthy_ui(payload: &Value) -> Result<()> {
    let frames = payload.get("frames").and_then(Value::as_u64).unwrap_or(0);
    let renderer = payload
        .get("last_ui_renderer")
        .and_then(Value::as_str)
        .unwrap_or_default();
    let active_screen = payload
        .get("active_screen")
        .and_then(Value::as_str)
        .unwrap_or_default();
    if frames < 1 {
        bail!("UI host rendered no frames: {payload}");
    }
    if renderer != "lvgl" {
        bail!("UI host did not report LVGL renderer: {payload}");
    }
    if active_screen.is_empty() {
        bail!("UI host did not report an active screen: {payload}");
    }
    Ok(())
}

/// Keep the worker ticking for `seconds` of wall time.
fn pump_ticks(supervisor: &mut UiHostSupervisor, seconds: f64) -> Result<()> {
    if seconds <= 0.0 {
        return Ok(());
    }
    let deadline = Instant::now() + Duration::from_secs_f64(seconds);
    loop {
        let remaining = deadline.saturating_duration_since(Instant::now());
        if remaining.is_zero() {
            return Ok(());
        }
        thread::sleep(remaining.min(TICK_INTERVAL));
        supervisor.send(UiCommand::Tick)?;
    }
}

fn format_ui_health(worker: &Path, hardware: &str, payload: &Value) -> String {
    format!(
        "binary={}, hardware={hardware}, frames={}, button_events={}, \
         active_screen={}, last_ui_renderer={}",
        worker.display(),
        payload.get("frames").cloned().unwrap_or(Value::Null),
        payload.get("button_events").cloned().unwrap_or(Value::Null),
        payload.get("active_screen").cloned().unwrap_or(Value::Null),
        payload
            .get("last_ui_renderer")
            .cloned()
            .unwrap_or(Value::Null),
    )
}

/// Render one runtime snapshot through the UI host and require health.
pub fn ui_smoke_check(worker: &Path, hardware: &str, hold_seconds: f64) -> CheckResult {
    if !worker.exists() {
        return CheckResult::fail(
            "rust-ui",
            format!("missing Rust UI host binary at {}", worker.display()),
        );
    }
    let run = || -> Result<String> {
        let mut supervisor = UiHostSupervisor::spawn(worker, hardware)?;
        let outcome = (|| {
            expect_ready(&mut supervisor)?;
            supervisor.send(UiCommand::RuntimeSnapshot(RuntimeSnapshot::default()))?;
            read_until(&mut supervisor, &["ui.screen_changed"])?;
            pump_ticks(&mut supervisor, hold_seconds)?;
            let health = request_health(&mut supervisor)?;
            require_healthy_ui(&health)?;
            Ok(format_ui_health(worker, hardware, &health))
        })();
        supervisor.stop();
        outcome
    };
    match run() {
        Ok(details) => CheckResult::pass("rust-ui", details),
        Err(error) => CheckResult::fail("rust-ui", error.to_string()),
    }
}

/// Drive semantic one-button navigation through the worker protocol.
///
/// Focus the hub first, then for each cycle: select into the active card,
/// back out to the hub, and advance the hub selection. Cycle 0 lands on
/// `listen`; later cycles on `talk` — matching the hub card order the Python
/// suite validated and the Home idle/focused interaction contract.
pub fn ui_navigation_check(
    worker: &Path,
    cycles: u32,
    hold_seconds: f64,
    idle_seconds: f64,
    tail_idle_seconds: f64,
) -> CheckResult {
    if !worker.exists() {
        return CheckResult::fail(
            "rust-ui-navigation",
            format!("missing Rust UI host binary at {}", worker.display()),
        );
    }
    let run = || -> Result<String> {
        let mut supervisor = UiHostSupervisor::spawn(worker, "whisplay")?;
        let outcome = (|| {
            expect_ready(&mut supervisor)?;
            supervisor.send(UiCommand::RuntimeSnapshot(RuntimeSnapshot::default()))?;
            expect_screen(&mut supervisor, "hub")?;

            // Home starts idle: the first press reveals/focuses the deck, while
            // the following double-press opens the focused destination.
            supervisor.send(UiCommand::InputAction(InputAction::Advance))?;
            pump_ticks(&mut supervisor, hold_seconds)?;

            let mut visited = vec!["hub".to_string()];
            let mut expected_selected_screen = "listen";
            for _cycle in 0..cycles.max(1) {
                supervisor.send(UiCommand::InputAction(InputAction::Select))?;
                visited.push(expect_screen(&mut supervisor, expected_selected_screen)?);
                pump_ticks(&mut supervisor, hold_seconds)?;
                pump_ticks(&mut supervisor, idle_seconds)?;

                supervisor.send(UiCommand::InputAction(InputAction::Back))?;
                visited.push(expect_screen(&mut supervisor, "hub")?);
                pump_ticks(&mut supervisor, hold_seconds)?;

                supervisor.send(UiCommand::InputAction(InputAction::Advance))?;
                let health = request_health(&mut supervisor)?;
                require_healthy_ui(&health)?;
                expected_selected_screen = "talk";
                pump_ticks(&mut supervisor, hold_seconds)?;
            }

            pump_ticks(&mut supervisor, tail_idle_seconds)?;
            let health = request_health(&mut supervisor)?;
            require_healthy_ui(&health)?;
            Ok(format!(
                "binary={}, protocol=ui.runtime_snapshot/ui.input_action, \
                 visited={}, frames={}, active_screen={}",
                worker.display(),
                visited.join(","),
                health.get("frames").cloned().unwrap_or(Value::Null),
                health.get("active_screen").cloned().unwrap_or(Value::Null),
            ))
        })();
        supervisor.stop();
        outcome
    };
    match run() {
        Ok(details) => CheckResult::pass("rust-ui-navigation", details),
        Err(error) => CheckResult::fail("rust-ui-navigation", error.to_string()),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn healthy_payload_passes() {
        let payload = serde_json::json!({
            "frames": 12,
            "last_ui_renderer": "lvgl",
            "active_screen": "hub",
        });
        assert!(require_healthy_ui(&payload).is_ok());
    }

    #[test]
    fn zero_frames_fails() {
        let payload = serde_json::json!({
            "frames": 0,
            "last_ui_renderer": "lvgl",
            "active_screen": "hub",
        });
        assert!(require_healthy_ui(&payload).is_err());
    }

    #[test]
    fn non_lvgl_renderer_fails() {
        let payload = serde_json::json!({
            "frames": 4,
            "last_ui_renderer": "mock",
            "active_screen": "hub",
        });
        assert!(require_healthy_ui(&payload).is_err());
    }

    #[test]
    fn missing_active_screen_fails() {
        let payload = serde_json::json!({
            "frames": 4,
            "last_ui_renderer": "lvgl",
        });
        assert!(require_healthy_ui(&payload).is_err());
    }

    #[test]
    fn smoke_check_fails_fast_on_missing_binary() {
        let result = ui_smoke_check(Path::new("no/such/ui-host"), "whisplay", 0.1);
        assert!(result.details.contains("missing Rust UI host binary"));
    }
}
