use std::io::{Read, Write};
use std::net::TcpStream;
use std::path::Path;
use std::process::Command;
use std::time::Duration;

use thiserror::Error;

use crate::config::{PowerHostConfig, PowerWatchdogConfig};
use crate::snapshot::{
    current_millis, BatterySnapshot, PowerDeviceSnapshot, PowerStatusSnapshot, RtcSnapshot,
    ShutdownSnapshot,
};

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum PowerControlCommand {
    SyncTimeToRtc,
    SyncTimeFromRtc,
    SetRtcAlarm { when: String, repeat_mask: i32 },
    DisableRtcAlarm,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum PowerWatchdogCommand {
    Enable { timeout_seconds: u64 },
    Feed,
    Disable,
}

impl PowerControlCommand {
    fn pisugar_command(&self) -> String {
        match self {
            Self::SyncTimeToRtc => "rtc_pi2rtc".to_string(),
            Self::SyncTimeFromRtc => "rtc_rtc2pi".to_string(),
            Self::SetRtcAlarm { when, repeat_mask } => {
                format!("rtc_alarm_set {} {}", when, repeat_mask)
            }
            Self::DisableRtcAlarm => "rtc_alarm_disable".to_string(),
        }
    }
}

pub trait PowerBackend {
    fn refresh_snapshot(&mut self) -> PowerStatusSnapshot;

    fn execute_control(
        &mut self,
        _command: PowerControlCommand,
    ) -> Result<PowerStatusSnapshot, String> {
        Err("power control unsupported".to_string())
    }

    fn execute_watchdog(&mut self, _command: PowerWatchdogCommand) -> Result<(), String> {
        Err("power watchdog unsupported".to_string())
    }
}

pub struct PowerHost<B: PowerBackend> {
    backend: B,
    snapshot: PowerStatusSnapshot,
}

impl<B: PowerBackend> PowerHost<B> {
    pub fn new(backend: B) -> Self {
        Self {
            backend,
            snapshot: PowerStatusSnapshot::default(),
        }
    }

    pub fn snapshot(&self) -> &PowerStatusSnapshot {
        &self.snapshot
    }

    pub fn refresh(&mut self) -> &PowerStatusSnapshot {
        self.snapshot = self.backend.refresh_snapshot();
        &self.snapshot
    }

    pub fn execute_control(
        &mut self,
        command: PowerControlCommand,
    ) -> Result<PowerStatusSnapshot, String> {
        let snapshot = self.backend.execute_control(command)?;
        self.snapshot = snapshot.clone();
        Ok(snapshot)
    }

    pub fn execute_watchdog(&mut self, command: PowerWatchdogCommand) -> Result<(), String> {
        self.backend.execute_watchdog(command)
    }
}

pub struct DisabledPowerBackend {
    reason: String,
}

impl DisabledPowerBackend {
    pub fn new(reason: impl Into<String>) -> Self {
        Self {
            reason: reason.into(),
        }
    }
}

impl PowerBackend for DisabledPowerBackend {
    fn refresh_snapshot(&mut self) -> PowerStatusSnapshot {
        PowerStatusSnapshot {
            available: false,
            checked_at_ms: current_millis(),
            error: self.reason.clone(),
            ..PowerStatusSnapshot::default()
        }
    }

    fn execute_control(
        &mut self,
        _command: PowerControlCommand,
    ) -> Result<PowerStatusSnapshot, String> {
        Err(self.reason.clone())
    }

    fn execute_watchdog(&mut self, _command: PowerWatchdogCommand) -> Result<(), String> {
        Err(self.reason.clone())
    }
}

pub struct PiSugarBackend {
    config: PowerHostConfig,
}

impl PiSugarBackend {
    pub fn new(config: PowerHostConfig) -> Self {
        Self { config }
    }

    fn get_snapshot(&self) -> PowerStatusSnapshot {
        if !self.config.enabled {
            return PowerStatusSnapshot {
                available: false,
                checked_at_ms: current_millis(),
                error: "power backend disabled".to_string(),
                ..PowerStatusSnapshot::default()
            };
        }
        if self.config.backend.trim() != "pisugar" {
            return PowerStatusSnapshot {
                available: false,
                checked_at_ms: current_millis(),
                error: format!("unsupported power backend {}", self.config.backend),
                ..PowerStatusSnapshot::default()
            };
        }

        let mut telemetry_success_count = 0;
        let mut errors = Vec::<String>::new();
        let device = PowerDeviceSnapshot {
            model: self.read_string(
                "get model",
                false,
                &mut telemetry_success_count,
                &mut errors,
            ),
            firmware_version: self.read_string(
                "get firmware_version",
                false,
                &mut telemetry_success_count,
                &mut errors,
            ),
        };
        let battery = BatterySnapshot {
            level_percent: self.read_float(
                "get battery",
                true,
                &mut telemetry_success_count,
                &mut errors,
            ),
            voltage_volts: self.read_float(
                "get battery_v",
                true,
                &mut telemetry_success_count,
                &mut errors,
            ),
            charging: self.read_bool(
                "get battery_charging",
                true,
                &mut telemetry_success_count,
                &mut errors,
            ),
            power_plugged: self.read_bool(
                "get battery_power_plugged",
                true,
                &mut telemetry_success_count,
                &mut errors,
            ),
            allow_charging: self.read_bool(
                "get battery_allow_charging",
                true,
                &mut telemetry_success_count,
                &mut errors,
            ),
            output_enabled: self.read_bool(
                "get battery_output_enabled",
                true,
                &mut telemetry_success_count,
                &mut errors,
            ),
            temperature_celsius: self.read_float(
                "get temperature",
                true,
                &mut telemetry_success_count,
                &mut errors,
            ),
        };
        let rtc = RtcSnapshot {
            time: self.read_string(
                "get rtc_time",
                true,
                &mut telemetry_success_count,
                &mut errors,
            ),
            alarm_enabled: self.read_bool(
                "get rtc_alarm_enabled",
                true,
                &mut telemetry_success_count,
                &mut errors,
            ),
            alarm_time: self.read_string(
                "get rtc_alarm_time",
                false,
                &mut telemetry_success_count,
                &mut errors,
            ),
            alarm_repeat_mask: self.read_i32(
                "get alarm_repeat",
                false,
                &mut telemetry_success_count,
                &mut errors,
            ),
            adjust_ppm: self.read_float(
                "get rtc_adjust_ppm",
                false,
                &mut telemetry_success_count,
                &mut errors,
            ),
        };
        let shutdown = ShutdownSnapshot {
            safe_shutdown_level_percent: self.read_float(
                "get safe_shutdown_level",
                false,
                &mut telemetry_success_count,
                &mut errors,
            ),
            safe_shutdown_delay_seconds: self.read_i32(
                "get safe_shutdown_delay",
                false,
                &mut telemetry_success_count,
                &mut errors,
            ),
        };

        PowerStatusSnapshot {
            available: telemetry_success_count > 0,
            checked_at_ms: current_millis(),
            source: "pisugar".to_string(),
            device,
            battery,
            rtc,
            shutdown,
            error: errors.join("; "),
        }
    }

    fn query(&self, command: &str) -> Result<String, PowerTransportError> {
        let response = self.send_command(command)?;
        extract_response_value(command, &response)
    }

    fn execute_control_command(&self, command: &str) -> Result<String, PowerTransportError> {
        let response = self.send_command(command)?.trim().to_string();
        if response.is_empty() {
            return Err(PowerTransportError::Transport(format!(
                "Empty response for {command:?}"
            )));
        }
        if response.to_ascii_lowercase().starts_with("error") {
            return Err(PowerTransportError::Transport(format!(
                "PiSugar command failed for {command:?}: {response}"
            )));
        }
        Ok(response)
    }

    fn read_string(
        &self,
        command: &str,
        counts_as_telemetry: bool,
        telemetry_success_count: &mut usize,
        errors: &mut Vec<String>,
    ) -> Option<String> {
        match self.query(command) {
            Ok(value) => {
                if counts_as_telemetry {
                    *telemetry_success_count += 1;
                }
                Some(value)
            }
            Err(error) => {
                errors.push(format!("{command}: {error}"));
                None
            }
        }
    }

    fn read_float(
        &self,
        command: &str,
        counts_as_telemetry: bool,
        telemetry_success_count: &mut usize,
        errors: &mut Vec<String>,
    ) -> Option<f64> {
        self.read_string(
            command,
            counts_as_telemetry,
            telemetry_success_count,
            errors,
        )
        .and_then(|value| match value.parse::<f64>() {
            Ok(parsed) => Some(parsed),
            Err(error) => {
                errors.push(format!("{command}: {error}"));
                None
            }
        })
    }

    fn read_i32(
        &self,
        command: &str,
        counts_as_telemetry: bool,
        telemetry_success_count: &mut usize,
        errors: &mut Vec<String>,
    ) -> Option<i32> {
        self.read_float(
            command,
            counts_as_telemetry,
            telemetry_success_count,
            errors,
        )
        .and_then(|value| i32::try_from(value as i64).ok())
    }

    fn read_bool(
        &self,
        command: &str,
        counts_as_telemetry: bool,
        telemetry_success_count: &mut usize,
        errors: &mut Vec<String>,
    ) -> Option<bool> {
        self.read_string(
            command,
            counts_as_telemetry,
            telemetry_success_count,
            errors,
        )
        .and_then(|value| match parse_bool(&value) {
            Some(parsed) => Some(parsed),
            None => {
                errors.push(format!("{command}: cannot coerce {value:?} to bool"));
                None
            }
        })
    }

    fn send_command(&self, command: &str) -> Result<String, PowerTransportError> {
        match self.config.transport.trim() {
            "socket" => send_unix_command(
                &self.config.socket_path,
                self.config.timeout_seconds,
                command,
            ),
            "tcp" => send_tcp_command(
                &self.config.tcp_host,
                self.config.tcp_port,
                self.config.timeout_seconds,
                command,
            ),
            _ => send_auto_command(&self.config, command),
        }
    }

    fn execute_watchdog_command(
        &self,
        command: PowerWatchdogCommand,
    ) -> Result<(), PowerTransportError> {
        let watchdog = PiSugarWatchdog::new(&self.config.watchdog);
        watchdog.execute(command)
    }
}

impl PowerBackend for PiSugarBackend {
    fn refresh_snapshot(&mut self) -> PowerStatusSnapshot {
        self.get_snapshot()
    }

    fn execute_control(
        &mut self,
        command: PowerControlCommand,
    ) -> Result<PowerStatusSnapshot, String> {
        self.execute_control_command(&command.pisugar_command())
            .map_err(|error| error.to_string())?;
        Ok(self.get_snapshot())
    }

    fn execute_watchdog(&mut self, command: PowerWatchdogCommand) -> Result<(), String> {
        self.execute_watchdog_command(command)
            .map_err(|error| error.to_string())
    }
}

struct PiSugarWatchdog<'a> {
    config: &'a PowerWatchdogConfig,
}

impl<'a> PiSugarWatchdog<'a> {
    const CONTROL_REGISTER: u8 = 0x06;
    const TIMEOUT_REGISTER: u8 = 0x07;
    const ENABLE_MASK: u8 = 0x80;
    const FEED_MASK: u8 = 0x20;

    fn new(config: &'a PowerWatchdogConfig) -> Self {
        Self { config }
    }

    fn execute(&self, command: PowerWatchdogCommand) -> Result<(), PowerTransportError> {
        match command {
            PowerWatchdogCommand::Enable { timeout_seconds } => {
                let timeout_value = coerce_watchdog_timeout(timeout_seconds)?;
                let control_value = self.read_register(Self::CONTROL_REGISTER)?;
                self.write_register(Self::TIMEOUT_REGISTER, timeout_value)?;
                self.write_register(
                    Self::CONTROL_REGISTER,
                    control_value | Self::ENABLE_MASK | Self::FEED_MASK,
                )
            }
            PowerWatchdogCommand::Feed => {
                let control_value = self.read_register(Self::CONTROL_REGISTER)?;
                self.write_register(
                    Self::CONTROL_REGISTER,
                    control_value | Self::ENABLE_MASK | Self::FEED_MASK,
                )
            }
            PowerWatchdogCommand::Disable => {
                let control_value = self.read_register(Self::CONTROL_REGISTER)?;
                self.write_register(
                    Self::CONTROL_REGISTER,
                    control_value & !Self::ENABLE_MASK & !Self::FEED_MASK,
                )
            }
        }
    }

    fn read_register(&self, register: u8) -> Result<u8, PowerTransportError> {
        let output = self.run_i2c_command(&[
            "i2cget".to_string(),
            "-y".to_string(),
            self.config.i2c_bus.to_string(),
            format!("0x{:x}", self.config.i2c_address),
            format!("0x{register:x}"),
        ])?;
        parse_watchdog_register(&output, register)
    }

    fn write_register(&self, register: u8, value: u8) -> Result<(), PowerTransportError> {
        self.run_i2c_command(&[
            "i2cset".to_string(),
            "-y".to_string(),
            self.config.i2c_bus.to_string(),
            format!("0x{:x}", self.config.i2c_address),
            format!("0x{register:x}"),
            format!("0x{value:x}"),
        ])?;
        Ok(())
    }

    fn run_i2c_command(&self, command: &[String]) -> Result<String, PowerTransportError> {
        let Some((program, args)) = command.split_first() else {
            return Err(PowerTransportError::Transport(
                "empty watchdog command".to_string(),
            ));
        };
        let output = Command::new(program).args(args).output().map_err(|error| {
            PowerTransportError::Transport(format!("watchdog command failed to start: {error}"))
        })?;
        if !output.status.success() {
            return Err(PowerTransportError::Transport(format!(
                "watchdog command failed ({}): {}; stderr={}",
                output
                    .status
                    .code()
                    .map(|code| code.to_string())
                    .unwrap_or_else(|| "signal".to_string()),
                command.join(" "),
                String::from_utf8_lossy(&output.stderr).trim()
            )));
        }
        Ok(String::from_utf8_lossy(&output.stdout).trim().to_string())
    }
}

#[derive(Debug, Error)]
enum PowerTransportError {
    #[error("{0}")]
    Transport(String),
}

fn send_auto_command(
    config: &PowerHostConfig,
    command: &str,
) -> Result<String, PowerTransportError> {
    let mut errors = Vec::new();
    match send_unix_command(&config.socket_path, config.timeout_seconds, command) {
        Ok(response) => return Ok(response),
        Err(error) => errors.push(error.to_string()),
    }
    match send_tcp_command(
        &config.tcp_host,
        config.tcp_port,
        config.timeout_seconds,
        command,
    ) {
        Ok(response) => Ok(response),
        Err(error) => {
            errors.push(error.to_string());
            Err(PowerTransportError::Transport(errors.join("; ")))
        }
    }
}

fn send_tcp_command(
    host: &str,
    port: u16,
    timeout_seconds: f64,
    command: &str,
) -> Result<String, PowerTransportError> {
    let timeout = timeout(timeout_seconds);
    let address = format!("{host}:{port}");
    let mut stream = TcpStream::connect(&address)
        .map_err(|error| PowerTransportError::Transport(format!("TCP {address}: {error}")))?;
    stream.set_read_timeout(Some(timeout)).ok();
    stream.set_write_timeout(Some(timeout)).ok();
    stream
        .write_all(format!("{}\n", command.trim()).as_bytes())
        .map_err(|error| PowerTransportError::Transport(format!("TCP write {address}: {error}")))?;
    let _ = stream.shutdown(std::net::Shutdown::Write);
    read_stream_response(stream)
}

#[cfg(unix)]
fn send_unix_command(
    socket_path: &str,
    timeout_seconds: f64,
    command: &str,
) -> Result<String, PowerTransportError> {
    use std::os::unix::net::UnixStream;

    let path = Path::new(socket_path);
    if !path.exists() {
        return Err(PowerTransportError::Transport(format!(
            "Unix socket not found: {}",
            path.display()
        )));
    }
    let timeout = timeout(timeout_seconds);
    let mut stream = UnixStream::connect(path).map_err(|error| {
        PowerTransportError::Transport(format!("Unix {}: {error}", path.display()))
    })?;
    stream.set_read_timeout(Some(timeout)).ok();
    stream.set_write_timeout(Some(timeout)).ok();
    stream
        .write_all(format!("{}\n", command.trim()).as_bytes())
        .map_err(|error| {
            PowerTransportError::Transport(format!("Unix write {}: {error}", path.display()))
        })?;
    let _ = stream.shutdown(std::net::Shutdown::Write);
    read_stream_response(stream)
}

#[cfg(not(unix))]
fn send_unix_command(
    socket_path: &str,
    _timeout_seconds: f64,
    _command: &str,
) -> Result<String, PowerTransportError> {
    let path = Path::new(socket_path);
    Err(PowerTransportError::Transport(format!(
        "Unix socket unsupported on this platform: {}",
        path.display()
    )))
}

fn read_stream_response(mut stream: impl Read) -> Result<String, PowerTransportError> {
    let mut response = String::new();
    stream
        .read_to_string(&mut response)
        .map_err(|error| PowerTransportError::Transport(format!("read response: {error}")))?;
    let response = response.trim().to_string();
    if response.is_empty() {
        Err(PowerTransportError::Transport(
            "No response from PiSugar server".to_string(),
        ))
    } else {
        Ok(response)
    }
}

fn extract_response_value(command: &str, response: &str) -> Result<String, PowerTransportError> {
    let Some(line) = response
        .lines()
        .map(str::trim)
        .rfind(|line| !line.is_empty())
    else {
        return Err(PowerTransportError::Transport(format!(
            "Empty response for {command:?}"
        )));
    };
    let value = line
        .split_once(':')
        .map(|(_, value)| value)
        .unwrap_or(line)
        .trim();
    if value.is_empty() {
        Err(PowerTransportError::Transport(format!(
            "Malformed response for {command:?}: {response:?}"
        )))
    } else {
        Ok(value.to_string())
    }
}

fn coerce_watchdog_timeout(timeout_seconds: u64) -> Result<u8, PowerTransportError> {
    if timeout_seconds == 0 {
        return Err(PowerTransportError::Transport(
            "Watchdog timeout must be positive".to_string(),
        ));
    }
    let units = timeout_seconds.div_ceil(2).clamp(1, 255);
    Ok(units as u8)
}

fn parse_watchdog_register(output: &str, register: u8) -> Result<u8, PowerTransportError> {
    let output = output.trim();
    let parsed = if let Some(hex) = output
        .strip_prefix("0x")
        .or_else(|| output.strip_prefix("0X"))
    {
        u8::from_str_radix(hex, 16)
    } else {
        output.parse::<u8>()
    };
    parsed.map_err(|error| {
        PowerTransportError::Transport(format!(
            "Unexpected i2cget output for register 0x{register:x}: {output:?}: {error}"
        ))
    })
}

fn parse_bool(value: &str) -> Option<bool> {
    match value.trim().to_ascii_lowercase().as_str() {
        "true" | "1" | "yes" | "on" => Some(true),
        "false" | "0" | "no" | "off" => Some(false),
        _ => None,
    }
}

fn timeout(timeout_seconds: f64) -> Duration {
    Duration::from_secs_f64(timeout_seconds.max(0.1))
}
