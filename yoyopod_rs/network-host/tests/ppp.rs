use std::cell::RefCell;
use std::collections::VecDeque;
use std::io;
use std::path::PathBuf;
use std::rc::Rc;
use std::time::Duration;

use yoyopod_network_host::ppp::{
    build_pppd_command, resolve_pppd_binary_with, should_manage_default_route, LinkWaitOutcome,
    PppCommandError, PppLaunchConfig, PppLifecycle, PppLinkProbe, PppProcessHandle,
    ShutdownOutcome, Sleeper,
};

#[derive(Debug)]
struct FakeProcess {
    pid: u32,
    alive: Rc<RefCell<VecDeque<bool>>>,
    terminate_calls: usize,
    kill_calls: usize,
}

impl FakeProcess {
    fn new(pid: u32, alive_states: impl IntoIterator<Item = bool>) -> Self {
        Self {
            pid,
            alive: Rc::new(RefCell::new(alive_states.into_iter().collect())),
            terminate_calls: 0,
            kill_calls: 0,
        }
    }
}

impl PppProcessHandle for FakeProcess {
    fn pid(&self) -> u32 {
        self.pid
    }

    fn is_running(&mut self) -> bool {
        let mut alive = self.alive.borrow_mut();
        match alive.len() {
            0 => false,
            1 => alive[0],
            _ => alive.pop_front().unwrap_or(false),
        }
    }

    fn terminate(&mut self) -> io::Result<()> {
        self.terminate_calls += 1;
        Ok(())
    }

    fn kill(&mut self) -> io::Result<()> {
        self.kill_calls += 1;
        self.alive.borrow_mut().clear();
        self.alive.borrow_mut().push_back(false);
        Ok(())
    }
}

#[derive(Debug)]
struct FakeLinkProbe {
    states: VecDeque<bool>,
}

impl FakeLinkProbe {
    fn new(states: impl IntoIterator<Item = bool>) -> Self {
        Self {
            states: states.into_iter().collect(),
        }
    }
}

impl PppLinkProbe for FakeLinkProbe {
    fn ppp0_exists(&mut self) -> bool {
        match self.states.len() {
            0 => false,
            1 => self.states[0],
            _ => self.states.pop_front().unwrap_or(false),
        }
    }
}

#[derive(Debug, Default)]
struct FakeSleeper {
    calls: Vec<Duration>,
}

impl Sleeper for FakeSleeper {
    fn sleep(&mut self, duration: Duration) {
        self.calls.push(duration);
    }
}

#[test]
fn resolve_pppd_binary_uses_usr_sbin_fallback_when_path_omits_pppd() {
    let resolved = resolve_pppd_binary_with(
        |candidate| match candidate {
            "/usr/sbin/pppd" => Some(PathBuf::from("/usr/sbin/pppd")),
            _ => None,
        },
        |_| false,
    );

    assert_eq!(resolved, Some(PathBuf::from("/usr/sbin/pppd")));
}

#[test]
fn build_pppd_command_wraps_with_sudo_for_non_root_launches() {
    let argv = build_pppd_command(&PppLaunchConfig {
        serial_port: "/dev/ttyUSB3".to_string(),
        baud_rate: 115_200,
        pppd_path: PathBuf::from("/usr/sbin/pppd"),
        sudo_path: Some(PathBuf::from("/usr/bin/sudo")),
        is_root: false,
        manage_default_route: true,
    })
    .expect("command should build");

    assert_eq!(argv[0], "/usr/bin/sudo");
    assert_eq!(argv[1], "-n");
    assert_eq!(argv[2], "/usr/sbin/pppd");
    assert!(argv.iter().any(|arg| arg == "defaultroute"));
    assert!(argv.iter().any(|arg| arg == "usepeerdns"));
    assert!(argv
        .iter()
        .any(|arg| arg == "chat -v '' AT OK 'ATD*99#' CONNECT"));
}

#[test]
fn build_pppd_command_fails_for_non_root_launch_without_sudo() {
    let error = build_pppd_command(&PppLaunchConfig {
        serial_port: "/dev/ttyUSB3".to_string(),
        baud_rate: 115_200,
        pppd_path: PathBuf::from("/usr/sbin/pppd"),
        sudo_path: None,
        is_root: false,
        manage_default_route: true,
    })
    .expect_err("sudo should be required");

    assert!(matches!(error, PppCommandError::MissingSudo));
}

#[test]
fn build_pppd_command_skips_default_route_and_peer_dns_when_wifi_owns_uplink() {
    let argv = build_pppd_command(&PppLaunchConfig {
        serial_port: "/dev/ttyUSB3".to_string(),
        baud_rate: 115_200,
        pppd_path: PathBuf::from("/usr/sbin/pppd"),
        sudo_path: None,
        is_root: true,
        manage_default_route: false,
    })
    .expect("command should build");

    assert!(!argv.iter().any(|arg| arg == "defaultroute"));
    assert!(!argv.iter().any(|arg| arg == "usepeerdns"));
}

#[test]
fn non_ppp_default_route_suppresses_default_route_management() {
    let route_output =
        "default via 192.168.178.1 dev wlan0 proto dhcp src 192.168.178.85 metric 50\n";

    assert!(!should_manage_default_route(route_output));
}

#[test]
fn existing_ppp_default_route_keeps_default_route_management() {
    let route_output = "default via 10.64.64.64 dev ppp0\n";

    assert!(should_manage_default_route(route_output));
}

#[test]
fn lifecycle_wait_for_link_returns_up_when_ppp_interface_appears() {
    let process = FakeProcess::new(42, [true, true, true]);
    let link_probe = FakeLinkProbe::new([false, true]);
    let sleeper = FakeSleeper::default();
    let mut lifecycle = PppLifecycle::with_process(process, link_probe, sleeper);

    let outcome = lifecycle.wait_for_link(Duration::from_secs(3), Duration::from_secs(1));

    assert_eq!(outcome, LinkWaitOutcome::LinkUp);
}

#[test]
fn lifecycle_wait_for_link_reports_process_exit_before_interface_is_ready() {
    let process = FakeProcess::new(42, [true, false]);
    let link_probe = FakeLinkProbe::new([false, false]);
    let sleeper = FakeSleeper::default();
    let mut lifecycle = PppLifecycle::with_process(process, link_probe, sleeper);

    let outcome = lifecycle.wait_for_link(Duration::from_secs(3), Duration::from_secs(1));

    assert_eq!(outcome, LinkWaitOutcome::ProcessExited);
}

#[test]
fn lifecycle_shutdown_escalates_to_kill_when_process_stays_alive() {
    let process = FakeProcess::new(42, [true, true, true, true]);
    let link_probe = FakeLinkProbe::new([]);
    let sleeper = FakeSleeper::default();
    let mut lifecycle = PppLifecycle::with_process(process, link_probe, sleeper);

    let outcome = lifecycle
        .shutdown(Duration::from_secs(2), Duration::from_secs(1))
        .expect("shutdown should not error");

    assert_eq!(outcome, ShutdownOutcome::Killed);
    assert!(!lifecycle.is_alive());
}

#[test]
fn lifecycle_respawn_replaces_previous_process_after_shutdown() {
    let old_process = FakeProcess::new(42, [true, false]);
    let link_probe = FakeLinkProbe::new([]);
    let sleeper = FakeSleeper::default();
    let mut lifecycle = PppLifecycle::with_process(old_process, link_probe, sleeper);

    lifecycle
        .respawn(Duration::from_secs(1), Duration::from_millis(100), || {
            Ok(FakeProcess::new(77, [true]))
        })
        .expect("respawn should succeed");

    assert!(lifecycle.is_alive());
    assert_eq!(lifecycle.current_pid(), Some(77));
}
