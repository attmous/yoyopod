use std::io;
use std::process::{Child, Command, Stdio};
use std::time::Duration;

use crate::at::AtCommandSet;
use crate::config::NetworkHostConfig;
use crate::gps::GpsFix;
use crate::ppp::{
    build_command_plan, should_manage_default_route_from_system, LinkWaitOutcome, PathPppLinkProbe,
    PppCommandError, PppLaunchConfig, PppLifecycle, PppLinkProbe, PppProcessHandle,
    ShutdownOutcome, ThreadSleeper,
};
use crate::transport::{SerialLineTransport, TransportError};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ModemError {
    pub code: String,
    pub message: String,
    pub retryable: bool,
}

impl ModemError {
    pub fn fatal(code: impl Into<String>, message: impl Into<String>) -> Self {
        Self {
            code: code.into(),
            message: message.into(),
            retryable: false,
        }
    }

    pub fn retryable(code: impl Into<String>, message: impl Into<String>) -> Self {
        Self {
            code: code.into(),
            message: message.into(),
            retryable: true,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ModemRegistration {
    pub sim_ready: bool,
    pub registered: bool,
    pub carrier: String,
    pub network_type: String,
    pub signal_csq: Option<u8>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PppLink {
    pub interface: String,
    pub pid: Option<u32>,
    pub default_route_owned: bool,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum PppHealth {
    Up(PppLink),
    ProcessExited,
    InterfaceDown,
}

pub trait ModemController {
    fn open(&mut self) -> Result<(), ModemError>;
    fn close(&mut self) -> Result<(), ModemError>;
    fn probe(&mut self) -> Result<bool, ModemError>;
    fn initialize(&mut self, gps_enabled: bool) -> Result<ModemRegistration, ModemError>;
    fn start_ppp(&mut self, apn: Option<&str>, timeout_secs: u64) -> Result<PppLink, ModemError>;
    fn stop_ppp(&mut self) -> Result<(), ModemError>;
    fn ppp_health(&mut self) -> Result<PppHealth, ModemError>;
    fn query_gps(&mut self) -> Result<Option<GpsFix>, ModemError>;
    fn reset(&mut self) -> Result<(), ModemError>;
}

#[derive(Debug, Default, Clone, Copy)]
pub struct NoopModemController;

impl ModemController for NoopModemController {
    fn open(&mut self) -> Result<(), ModemError> {
        Ok(())
    }

    fn close(&mut self) -> Result<(), ModemError> {
        Ok(())
    }

    fn probe(&mut self) -> Result<bool, ModemError> {
        Err(ModemError::fatal(
            "modem_unavailable",
            "modem runtime is unavailable",
        ))
    }

    fn initialize(&mut self, _gps_enabled: bool) -> Result<ModemRegistration, ModemError> {
        Err(ModemError::fatal(
            "modem_unavailable",
            "modem runtime is unavailable",
        ))
    }

    fn start_ppp(&mut self, _apn: Option<&str>, _timeout_secs: u64) -> Result<PppLink, ModemError> {
        Err(ModemError::fatal(
            "modem_unavailable",
            "modem runtime is unavailable",
        ))
    }

    fn stop_ppp(&mut self) -> Result<(), ModemError> {
        Ok(())
    }

    fn ppp_health(&mut self) -> Result<PppHealth, ModemError> {
        Ok(PppHealth::ProcessExited)
    }

    fn query_gps(&mut self) -> Result<Option<GpsFix>, ModemError> {
        Ok(None)
    }

    fn reset(&mut self) -> Result<(), ModemError> {
        Ok(())
    }
}

#[derive(Debug)]
pub struct Sim7600ModemController {
    config: NetworkHostConfig,
    transport: SerialLineTransport,
    ppp: PppLifecycle<SystemPppProcess, PathPppLinkProbe, ThreadSleeper>,
    active_ppp: Option<PppLink>,
}

impl Sim7600ModemController {
    pub fn new(config: NetworkHostConfig) -> Self {
        Self {
            transport: SerialLineTransport::new(
                config.serial_port.clone(),
                config.baud_rate,
                Duration::from_secs(2),
            ),
            ppp: PppLifecycle::new(PathPppLinkProbe::default(), ThreadSleeper),
            active_ppp: None,
            config,
        }
    }

    fn at(&mut self) -> AtCommandSet<&mut SerialLineTransport> {
        AtCommandSet::new(&mut self.transport)
    }

    fn clear_ppp_state(&mut self) {
        self.active_ppp = None;
        let _ = self.ppp.take_process();
    }
}

impl ModemController for Sim7600ModemController {
    fn open(&mut self) -> Result<(), ModemError> {
        if self.transport.is_open() {
            return Ok(());
        }
        self.transport.open().map_err(map_transport_error)
    }

    fn close(&mut self) -> Result<(), ModemError> {
        let _ = self.stop_ppp();
        if self.transport.is_open() {
            let mut at = self.at();
            let _ = at.hangup();
        }
        self.transport.close();
        Ok(())
    }

    fn probe(&mut self) -> Result<bool, ModemError> {
        self.at().ping().map_err(map_transport_error)
    }

    fn initialize(&mut self, gps_enabled: bool) -> Result<ModemRegistration, ModemError> {
        let mut at = self.at();
        at.echo_off().map_err(map_transport_error)?;
        if !at.check_sim().map_err(map_transport_error)? {
            return Err(ModemError::fatal("sim_not_ready", "SIM not ready"));
        }

        let signal = at.get_signal_quality().map_err(map_transport_error)?;
        let carrier = at.get_carrier().map_err(map_transport_error)?;
        if !at.get_registration().map_err(map_transport_error)? {
            return Err(ModemError::retryable(
                "network_not_registered",
                "Not registered on network",
            ));
        }

        if gps_enabled {
            at.enable_gps()
                .map_err(map_transport_error)?
                .then_some(())
                .ok_or_else(|| ModemError::retryable("gps_enable_failed", "GPS enable failed"))?;
        }

        Ok(ModemRegistration {
            sim_ready: true,
            registered: true,
            carrier: carrier.carrier,
            network_type: carrier.network_type,
            signal_csq: Some(signal.csq),
        })
    }

    fn start_ppp(&mut self, apn: Option<&str>, timeout_secs: u64) -> Result<PppLink, ModemError> {
        if let Some(apn) = apn {
            self.at().configure_pdp(apn).map_err(map_transport_error)?;
        }

        let pppd_path = crate::ppp::resolve_pppd_binary()
            .ok_or_else(|| ModemError::fatal("pppd_not_found", "pppd binary not found"))?;
        let sudo_path = crate::ppp::resolve_sudo_binary();
        let plan = build_command_plan(&PppLaunchConfig {
            serial_port: self.config.ppp_port.clone(),
            baud_rate: self.config.baud_rate,
            pppd_path,
            sudo_path,
            is_root: is_running_as_root(),
            manage_default_route: should_manage_default_route_from_system(),
        })
        .map_err(map_ppp_command_error)?;

        let mut command = Command::new(&plan.argv[0]);
        if plan.argv.len() > 1 {
            command.args(&plan.argv[1..]);
        }
        let child = command
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()
            .map_err(map_io_error)?;

        let pid = child.id();
        self.ppp.replace_process(SystemPppProcess { child });
        match self.ppp.wait_for_link(
            Duration::from_secs(timeout_secs),
            Duration::from_millis(250),
        ) {
            LinkWaitOutcome::LinkUp => {
                let link = PppLink {
                    interface: "ppp0".to_string(),
                    pid: Some(pid),
                    default_route_owned: plan.manage_default_route,
                };
                self.active_ppp = Some(link.clone());
                Ok(link)
            }
            LinkWaitOutcome::ProcessExited => {
                self.clear_ppp_state();
                Err(ModemError::retryable(
                    "ppp_process_exited",
                    "PPP process exited",
                ))
            }
            LinkWaitOutcome::TimedOut => {
                let _ = self
                    .ppp
                    .shutdown(Duration::from_secs(1), Duration::from_millis(100));
                self.clear_ppp_state();
                Err(ModemError::retryable(
                    "ppp_negotiation_timeout",
                    "PPP negotiation timed out",
                ))
            }
        }
    }

    fn stop_ppp(&mut self) -> Result<(), ModemError> {
        match self
            .ppp
            .shutdown(Duration::from_secs(1), Duration::from_millis(100))
        {
            Ok(
                ShutdownOutcome::NoProcess | ShutdownOutcome::Graceful | ShutdownOutcome::Killed,
            ) => {
                self.clear_ppp_state();
                Ok(())
            }
            Err(error) => Err(map_io_error(error)),
        }
    }

    fn ppp_health(&mut self) -> Result<PppHealth, ModemError> {
        if !self.ppp.is_alive() {
            self.active_ppp = None;
            return Ok(PppHealth::ProcessExited);
        }

        let mut probe = PathPppLinkProbe::default();
        if !probe.ppp0_exists() {
            self.active_ppp = None;
            return Ok(PppHealth::InterfaceDown);
        }

        Ok(PppHealth::Up(self.active_ppp.clone().unwrap_or(PppLink {
            interface: "ppp0".to_string(),
            pid: self.ppp.current_pid(),
            default_route_owned: true,
        })))
    }

    fn query_gps(&mut self) -> Result<Option<GpsFix>, ModemError> {
        self.at().query_gps().map_err(map_transport_error)
    }

    fn reset(&mut self) -> Result<(), ModemError> {
        let _ = self.stop_ppp();
        if self.transport.is_open() {
            let mut at = self.at();
            let _ = at.radio_off();
            let _ = at.hangup();
        }
        self.transport.close();
        self.active_ppp = None;
        Ok(())
    }
}

#[derive(Debug)]
struct SystemPppProcess {
    child: Child,
}

impl PppProcessHandle for SystemPppProcess {
    fn pid(&self) -> u32 {
        self.child.id()
    }

    fn is_running(&mut self) -> bool {
        matches!(self.child.try_wait(), Ok(None))
    }

    fn terminate(&mut self) -> io::Result<()> {
        terminate_child(&mut self.child)
    }

    fn kill(&mut self) -> io::Result<()> {
        self.child.kill()
    }
}

#[cfg(unix)]
fn terminate_child(child: &mut Child) -> io::Result<()> {
    let status = Command::new("kill")
        .args(["-TERM", &child.id().to_string()])
        .status()?;
    if status.success() {
        Ok(())
    } else {
        Err(io::Error::other("failed to terminate pppd"))
    }
}

#[cfg(not(unix))]
fn terminate_child(child: &mut Child) -> io::Result<()> {
    child.kill()
}

fn map_transport_error(error: TransportError) -> ModemError {
    ModemError::retryable("transport_error", error.to_string())
}

fn map_io_error(error: io::Error) -> ModemError {
    ModemError::retryable("io_error", error.to_string())
}

fn map_ppp_command_error(error: PppCommandError) -> ModemError {
    match error {
        PppCommandError::MissingSudo => {
            ModemError::fatal("ppp_permission_error", error.to_string())
        }
    }
}

#[cfg(unix)]
fn is_running_as_root() -> bool {
    let Ok(output) = Command::new("id").arg("-u").output() else {
        return false;
    };
    output.status.success() && String::from_utf8_lossy(&output.stdout).trim() == "0"
}

#[cfg(not(unix))]
fn is_running_as_root() -> bool {
    false
}
