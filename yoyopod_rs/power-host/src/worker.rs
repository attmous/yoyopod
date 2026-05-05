use std::io::{self, BufRead, BufReader, Read, Write};
use std::sync::mpsc::{self, RecvTimeoutError};
use std::time::{Duration, Instant};

use anyhow::Result;
use serde_json::Value;

use crate::config::{PowerHostConfig, PowerWatchdogConfig};
use crate::host::{
    DisabledPowerBackend, PiSugarBackend, PowerBackend, PowerControlCommand, PowerHost,
    PowerWatchdogCommand,
};
use crate::protocol::{
    control_result, ready_event, snapshot_event, snapshot_result, stopped_event, stopped_result,
    EnvelopeKind, WorkerEnvelope,
};
use yoyopod_worker::{emit, standard_error};

pub fn run(config_dir: &str) -> Result<()> {
    let stdin = io::stdin();
    let mut stdout = io::stdout();
    run_with_io(config_dir, stdin, &mut stdout)
}

pub fn run_with_io<R, W>(config_dir: &str, input: R, output: &mut W) -> Result<()>
where
    R: Read + Send + 'static,
    W: Write,
{
    let config = PowerHostConfig::load(config_dir)
        .unwrap_or_else(|_| PowerHostConfig::default_for_config_dir(config_dir));
    let poll_interval = Duration::from_secs_f64(config.poll_interval_seconds.max(0.1));
    let watchdog = config.watchdog.clone();
    if config.enabled && config.backend.trim() == "pisugar" {
        run_host_loop_with_watchdog(
            PowerHost::new(PiSugarBackend::new(config)),
            input,
            output,
            poll_interval,
            watchdog,
        )
    } else {
        let reason = if config.enabled {
            format!("unsupported power backend {}", config.backend)
        } else {
            "power backend disabled".to_string()
        };
        run_host_loop_with_watchdog(
            PowerHost::new(DisabledPowerBackend::new(reason)),
            input,
            output,
            poll_interval,
            watchdog,
        )
    }
}

pub fn run_host_loop<R, W, B>(
    host: PowerHost<B>,
    input: R,
    output: &mut W,
    poll_interval: Duration,
) -> Result<()>
where
    R: Read + Send + 'static,
    W: Write,
    B: PowerBackend,
{
    run_host_loop_with_watchdog(
        host,
        input,
        output,
        poll_interval,
        PowerWatchdogConfig::default(),
    )
}

pub fn run_host_loop_with_watchdog<R, W, B>(
    mut host: PowerHost<B>,
    input: R,
    output: &mut W,
    poll_interval: Duration,
    watchdog_config: PowerWatchdogConfig,
) -> Result<()>
where
    R: Read + Send + 'static,
    W: Write,
    B: PowerBackend,
{
    emit(output, &ready_event())?;
    host.refresh();
    emit(output, &snapshot_event(host.snapshot()))?;
    let mut watchdog = WatchdogRuntime::new(watchdog_config);
    watchdog.start(&mut host, output)?;

    let (stdin_tx, stdin_rx) = mpsc::channel();
    std::thread::spawn(move || {
        let reader = BufReader::new(input);
        for line in reader.lines() {
            if stdin_tx.send(line).is_err() {
                break;
            }
        }
    });

    let mut next_poll = Instant::now() + poll_interval;
    loop {
        let now = Instant::now();
        let next_deadline = watchdog
            .next_feed_at()
            .map(|deadline| deadline.min(next_poll))
            .unwrap_or(next_poll);
        let timeout = next_deadline
            .checked_duration_since(now)
            .unwrap_or_else(|| Duration::from_millis(0));
        match stdin_rx.recv_timeout(timeout) {
            Ok(Ok(line)) => {
                if line.trim().is_empty() {
                    continue;
                }
                let envelope = match WorkerEnvelope::decode(line.as_bytes()) {
                    Ok(envelope) => envelope,
                    Err(error) => {
                        emit(
                            output,
                            &standard_error(
                                "power",
                                None,
                                "protocol_error",
                                error.to_string(),
                                false,
                            ),
                        )?;
                        continue;
                    }
                };
                if envelope.kind != EnvelopeKind::Command {
                    emit(
                        output,
                        &standard_error(
                            "power",
                            envelope.request_id,
                            "invalid_kind",
                            "power worker accepts commands only",
                            false,
                        ),
                    )?;
                    continue;
                }
                match handle_command(&mut host, &mut watchdog, envelope) {
                    LoopControl::Continue(envelopes) => {
                        for envelope in envelopes {
                            emit(output, &envelope)?;
                        }
                    }
                    LoopControl::Shutdown(envelopes) => {
                        watchdog.disable_for_stop(&mut host, output)?;
                        for envelope in envelopes {
                            emit(output, &envelope)?;
                        }
                        emit(output, &stopped_event("shutdown"))?;
                        break;
                    }
                }
            }
            Ok(Err(error)) => {
                emit(output, &stopped_event("input_error"))?;
                return Err(error.into());
            }
            Err(RecvTimeoutError::Timeout) => {
                let now = Instant::now();
                if watchdog.feed_due(now) {
                    watchdog.feed(&mut host, output, now)?;
                }
                if now >= next_poll {
                    host.refresh();
                    emit(output, &snapshot_event(host.snapshot()))?;
                    next_poll = Instant::now() + poll_interval;
                }
            }
            Err(RecvTimeoutError::Disconnected) => {
                emit(output, &stopped_event("input_closed"))?;
                break;
            }
        }
    }

    Ok(())
}

struct WatchdogRuntime {
    config: PowerWatchdogConfig,
    active: bool,
    suppressed: bool,
    next_feed_at: Option<Instant>,
}

impl WatchdogRuntime {
    fn new(config: PowerWatchdogConfig) -> Self {
        Self {
            config,
            active: false,
            suppressed: false,
            next_feed_at: None,
        }
    }

    fn start<B: PowerBackend>(
        &mut self,
        host: &mut PowerHost<B>,
        output: &mut dyn Write,
    ) -> Result<()> {
        if !self.config.enabled {
            return Ok(());
        }
        self.enable(host, output, None, "power.watchdog_enable")
    }

    fn enable<B: PowerBackend>(
        &mut self,
        host: &mut PowerHost<B>,
        output: &mut dyn Write,
        request_id: Option<String>,
        message_type: &str,
    ) -> Result<()> {
        let timeout_seconds = self.config.timeout_seconds.max(1);
        match host.execute_watchdog(PowerWatchdogCommand::Enable { timeout_seconds }) {
            Ok(()) => {
                self.active = true;
                self.suppressed = false;
                self.next_feed_at = Some(Instant::now() + self.feed_interval());
                if request_id.is_some() {
                    emit(output, &watchdog_result(message_type, request_id, self))?;
                }
            }
            Err(message) => emit(
                output,
                &standard_error("power", request_id, "watchdog_failed", message, false),
            )?,
        }
        Ok(())
    }

    fn feed<B: PowerBackend>(
        &mut self,
        host: &mut PowerHost<B>,
        output: &mut dyn Write,
        now: Instant,
    ) -> Result<()> {
        if !self.active || self.suppressed {
            return Ok(());
        }
        match host.execute_watchdog(PowerWatchdogCommand::Feed) {
            Ok(()) => {
                self.next_feed_at = Some(now + self.feed_interval());
            }
            Err(message) => {
                self.next_feed_at = Some(now + self.feed_interval().min(Duration::from_secs(5)));
                emit(
                    output,
                    &standard_error("power", None, "watchdog_failed", message, false),
                )?;
            }
        }
        Ok(())
    }

    fn disable<B: PowerBackend>(
        &mut self,
        host: &mut PowerHost<B>,
        output: &mut dyn Write,
        request_id: Option<String>,
        message_type: &str,
    ) -> Result<()> {
        if !self.active {
            if request_id.is_some() {
                emit(output, &watchdog_result(message_type, request_id, self))?;
            }
            return Ok(());
        }
        match host.execute_watchdog(PowerWatchdogCommand::Disable) {
            Ok(()) => {
                self.active = false;
                self.suppressed = false;
                self.next_feed_at = None;
                if request_id.is_some() {
                    emit(output, &watchdog_result(message_type, request_id, self))?;
                }
            }
            Err(message) => emit(
                output,
                &standard_error("power", request_id, "watchdog_failed", message, false),
            )?,
        }
        Ok(())
    }

    fn disable_for_stop<B: PowerBackend>(
        &mut self,
        host: &mut PowerHost<B>,
        output: &mut dyn Write,
    ) -> Result<()> {
        if self.active && !self.suppressed {
            self.disable(host, output, None, "power.watchdog_disable")?;
        }
        Ok(())
    }

    fn suppress(&mut self) {
        if self.active {
            self.suppressed = true;
            self.next_feed_at = None;
        }
    }

    fn feed_due(&self, now: Instant) -> bool {
        self.active
            && !self.suppressed
            && self
                .next_feed_at
                .is_some_and(|next_feed_at| now >= next_feed_at)
    }

    fn next_feed_at(&self) -> Option<Instant> {
        if self.active && !self.suppressed {
            self.next_feed_at
        } else {
            None
        }
    }

    fn feed_interval(&self) -> Duration {
        Duration::from_secs_f64(self.config.feed_interval_seconds.max(0.001))
    }
}

enum LoopControl {
    Continue(Vec<WorkerEnvelope>),
    Shutdown(Vec<WorkerEnvelope>),
}

fn handle_command<B: PowerBackend>(
    host: &mut PowerHost<B>,
    watchdog: &mut WatchdogRuntime,
    envelope: WorkerEnvelope,
) -> LoopControl {
    let request_id = envelope.request_id.clone();
    match envelope.message_type.as_str() {
        "power.health" => LoopControl::Continue(vec![snapshot_result(request_id, host.snapshot())]),
        "power.refresh" => {
            host.refresh();
            LoopControl::Continue(vec![
                snapshot_result(request_id, host.snapshot()),
                snapshot_event(host.snapshot()),
            ])
        }
        "power.sync_time_to_rtc" => control_command(
            host,
            envelope.message_type,
            request_id,
            PowerControlCommand::SyncTimeToRtc,
        ),
        "power.sync_time_from_rtc" => control_command(
            host,
            envelope.message_type,
            request_id,
            PowerControlCommand::SyncTimeFromRtc,
        ),
        "power.set_rtc_alarm" => match set_alarm_command(&envelope.payload) {
            Ok(command) => control_command(host, envelope.message_type, request_id, command),
            Err(message) => LoopControl::Continue(vec![standard_error(
                "power",
                request_id,
                "invalid_payload",
                message,
                false,
            )]),
        },
        "power.disable_rtc_alarm" => control_command(
            host,
            envelope.message_type,
            request_id,
            PowerControlCommand::DisableRtcAlarm,
        ),
        "power.watchdog_enable" => {
            let mut output = Vec::new();
            let result = watchdog.enable(host, &mut output, request_id, "power.watchdog_enable");
            watchdog_command_result(result, output)
        }
        "power.watchdog_feed" => {
            let mut output = Vec::new();
            let now = Instant::now();
            let result = if watchdog.active && !watchdog.suppressed {
                watchdog.feed(host, &mut output, now).and_then(|()| {
                    emit(
                        &mut output,
                        &watchdog_result("power.watchdog_feed", request_id, watchdog),
                    )
                })
            } else {
                emit(
                    &mut output,
                    &watchdog_result("power.watchdog_feed", request_id, watchdog),
                )
            };
            watchdog_command_result(result, output)
        }
        "power.watchdog_disable" => {
            let mut output = Vec::new();
            let result = watchdog.disable(host, &mut output, request_id, "power.watchdog_disable");
            watchdog_command_result(result, output)
        }
        "power.watchdog_suppress" => {
            watchdog.suppress();
            LoopControl::Continue(vec![watchdog_result(
                "power.watchdog_suppress",
                request_id,
                watchdog,
            )])
        }
        "power.shutdown" | "worker.stop" => {
            LoopControl::Shutdown(vec![stopped_result(request_id, "shutdown")])
        }
        _ => LoopControl::Continue(vec![standard_error(
            "power",
            request_id,
            "unsupported_command",
            format!("unsupported command {}", envelope.message_type),
            false,
        )]),
    }
}

fn watchdog_command_result(result: Result<()>, output: Vec<u8>) -> LoopControl {
    let envelopes = String::from_utf8_lossy(&output)
        .lines()
        .filter_map(|line| WorkerEnvelope::decode(line.as_bytes()).ok())
        .collect::<Vec<_>>();
    match result {
        Ok(()) => LoopControl::Continue(envelopes),
        Err(error) => LoopControl::Continue(vec![standard_error(
            "power",
            None,
            "watchdog_failed",
            error.to_string(),
            false,
        )]),
    }
}

fn watchdog_result(
    message_type: impl Into<String>,
    request_id: Option<String>,
    watchdog: &WatchdogRuntime,
) -> WorkerEnvelope {
    WorkerEnvelope::result(
        message_type,
        request_id,
        serde_json::json!({
            "ok": true,
            "active": watchdog.active,
            "suppressed": watchdog.suppressed,
        }),
    )
}

fn control_command<B: PowerBackend>(
    host: &mut PowerHost<B>,
    message_type: String,
    request_id: Option<String>,
    command: PowerControlCommand,
) -> LoopControl {
    match host.execute_control(command) {
        Ok(snapshot) => LoopControl::Continue(vec![
            control_result(message_type, request_id, &snapshot),
            snapshot_event(&snapshot),
        ]),
        Err(message) => LoopControl::Continue(vec![standard_error(
            "power",
            request_id,
            "control_failed",
            message,
            false,
        )]),
    }
}

fn set_alarm_command(payload: &Value) -> Result<PowerControlCommand, String> {
    let when = payload
        .get("when")
        .or_else(|| payload.get("alarm_time"))
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .ok_or_else(|| "power.set_rtc_alarm requires when".to_string())?
        .to_string();
    let repeat_mask = payload
        .get("repeat_mask")
        .and_then(Value::as_i64)
        .unwrap_or(127);
    let repeat_mask = i32::try_from(repeat_mask)
        .map_err(|_| "power.set_rtc_alarm repeat_mask must fit in i32".to_string())?;

    Ok(PowerControlCommand::SetRtcAlarm { when, repeat_mask })
}
