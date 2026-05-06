use std::io::{Cursor, Read};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::Duration;

use yoyopod_harness::{decode_envelopes, find_envelope};
use yoyopod_power::config::PowerWatchdogConfig;
use yoyopod_power::host::{PowerBackend, PowerControlCommand, PowerHost, PowerWatchdogCommand};
use yoyopod_power::snapshot::{BatterySnapshot, PowerStatusSnapshot};
use yoyopod_power::worker::{run_host_loop, run_host_loop_with_watchdog};

#[derive(Clone)]
struct FakeBackend {
    snapshot: PowerStatusSnapshot,
    refreshes: Arc<Mutex<usize>>,
    control_commands: Arc<Mutex<Vec<PowerControlCommand>>>,
    watchdog_commands: Arc<Mutex<Vec<PowerWatchdogCommand>>>,
}

impl PowerBackend for FakeBackend {
    fn refresh_snapshot(&mut self) -> PowerStatusSnapshot {
        *self.refreshes.lock().expect("refresh lock") += 1;
        self.snapshot.clone()
    }

    fn execute_control(
        &mut self,
        command: PowerControlCommand,
    ) -> Result<PowerStatusSnapshot, String> {
        self.control_commands
            .lock()
            .expect("control command lock")
            .push(command);
        Ok(self.refresh_snapshot())
    }

    fn execute_watchdog(&mut self, command: PowerWatchdogCommand) -> Result<(), String> {
        self.watchdog_commands
            .lock()
            .expect("watchdog command lock")
            .push(command);
        Ok(())
    }
}

#[test]
fn worker_emits_ready_and_initial_snapshot_then_stops() {
    let refreshes = Arc::new(Mutex::new(0));
    let backend = FakeBackend {
        snapshot: PowerStatusSnapshot {
            available: true,
            battery: BatterySnapshot {
                level_percent: Some(76.0),
                charging: Some(false),
                power_plugged: Some(false),
                ..BatterySnapshot::default()
            },
            ..PowerStatusSnapshot::default()
        },
        refreshes: Arc::clone(&refreshes),
        control_commands: Arc::new(Mutex::new(Vec::new())),
        watchdog_commands: Arc::new(Mutex::new(Vec::new())),
    };
    let host = PowerHost::new(backend);
    let input = Cursor::new(
        br#"{"schema_version":1,"kind":"command","type":"worker.stop","payload":{}}
"#
        .to_vec(),
    );
    let mut output = Vec::new();

    run_host_loop(host, input, &mut output, Duration::from_millis(1)).expect("worker loop");

    let envelopes = decode_envelopes(&output);

    assert_eq!(envelopes[0].message_type, "power.ready");
    assert_eq!(envelopes[1].message_type, "power.snapshot");
    assert_eq!(envelopes[1].payload["battery"]["level_percent"], 76.0);
    assert_eq!(
        envelopes.last().expect("stopped").message_type,
        "power.stopped"
    );
    assert_eq!(*refreshes.lock().expect("refresh lock"), 1);
}

#[test]
fn worker_routes_rtc_control_commands_and_emits_fresh_snapshots() {
    let refreshes = Arc::new(Mutex::new(0));
    let control_commands = Arc::new(Mutex::new(Vec::new()));
    let backend = FakeBackend {
        snapshot: PowerStatusSnapshot {
            available: true,
            battery: BatterySnapshot {
                level_percent: Some(64.0),
                charging: Some(true),
                power_plugged: Some(true),
                ..BatterySnapshot::default()
            },
            ..PowerStatusSnapshot::default()
        },
        refreshes: Arc::clone(&refreshes),
        control_commands: Arc::clone(&control_commands),
        watchdog_commands: Arc::new(Mutex::new(Vec::new())),
    };
    let host = PowerHost::new(backend);
    let input = Cursor::new(
        br#"{"schema_version":1,"kind":"command","type":"power.sync_time_to_rtc","payload":{}}
{"schema_version":1,"kind":"command","type":"power.sync_time_from_rtc","payload":{}}
{"schema_version":1,"kind":"command","type":"power.set_rtc_alarm","payload":{"when":"2026-05-05T07:30:00+00:00","repeat_mask":31}}
{"schema_version":1,"kind":"command","type":"power.disable_rtc_alarm","payload":{}}
{"schema_version":1,"kind":"command","type":"worker.stop","payload":{}}
"#
        .to_vec(),
    );
    let mut output = Vec::new();

    run_host_loop(host, input, &mut output, Duration::from_secs(60)).expect("worker loop");

    assert_eq!(
        *control_commands.lock().expect("control command lock"),
        vec![
            PowerControlCommand::SyncTimeToRtc,
            PowerControlCommand::SyncTimeFromRtc,
            PowerControlCommand::SetRtcAlarm {
                when: "2026-05-05T07:30:00+00:00".to_string(),
                repeat_mask: 31,
            },
            PowerControlCommand::DisableRtcAlarm,
        ]
    );
    assert_eq!(*refreshes.lock().expect("refresh lock"), 5);

    let envelopes = decode_envelopes(&output);

    for message_type in [
        "power.sync_time_to_rtc",
        "power.sync_time_from_rtc",
        "power.set_rtc_alarm",
        "power.disable_rtc_alarm",
    ] {
        let result = find_envelope(&envelopes, message_type);
        assert_eq!(result.kind, yoyopod_power::protocol::EnvelopeKind::Result);
        assert_eq!(result.payload["ok"], true);
        assert_eq!(result.payload["snapshot"]["battery"]["level_percent"], 64.0);
    }

    let snapshot_events = envelopes
        .iter()
        .filter(|envelope| envelope.message_type == "power.snapshot")
        .count();
    assert_eq!(snapshot_events, 5);
}

#[test]
fn worker_rejects_set_rtc_alarm_without_time() {
    let refreshes = Arc::new(Mutex::new(0));
    let control_commands = Arc::new(Mutex::new(Vec::new()));
    let backend = FakeBackend {
        snapshot: PowerStatusSnapshot::default(),
        refreshes: Arc::clone(&refreshes),
        control_commands: Arc::clone(&control_commands),
        watchdog_commands: Arc::new(Mutex::new(Vec::new())),
    };
    let host = PowerHost::new(backend);
    let input = Cursor::new(
        br#"{"schema_version":1,"kind":"command","type":"power.set_rtc_alarm","payload":{"repeat_mask":31}}
{"schema_version":1,"kind":"command","type":"worker.stop","payload":{}}
"#
        .to_vec(),
    );
    let mut output = Vec::new();

    run_host_loop(host, input, &mut output, Duration::from_secs(60)).expect("worker loop");

    assert!(control_commands
        .lock()
        .expect("control command lock")
        .is_empty());
    assert_eq!(*refreshes.lock().expect("refresh lock"), 1);

    let envelopes = decode_envelopes(&output);
    let error = find_envelope(&envelopes, "power.error");

    assert_eq!(error.payload["code"], "invalid_payload");
    assert!(error.payload["message"]
        .as_str()
        .expect("error message")
        .contains("when"));
}

#[test]
fn worker_enables_feeds_and_disables_watchdog_when_configured() {
    let watchdog_commands = Arc::new(Mutex::new(Vec::new()));
    let backend = FakeBackend {
        snapshot: PowerStatusSnapshot::default(),
        refreshes: Arc::new(Mutex::new(0)),
        control_commands: Arc::new(Mutex::new(Vec::new())),
        watchdog_commands: Arc::clone(&watchdog_commands),
    };
    let host = PowerHost::new(backend);
    let input = DelayedInput::new(
        br#"{"schema_version":1,"kind":"command","type":"worker.stop","payload":{}}
"#
        .to_vec(),
        Duration::from_millis(30),
    );
    let mut output = Vec::new();

    run_host_loop_with_watchdog(
        host,
        input,
        &mut output,
        Duration::from_secs(60),
        PowerWatchdogConfig {
            enabled: true,
            timeout_seconds: 60,
            feed_interval_seconds: 0.005,
            i2c_bus: 1,
            i2c_address: 0x57,
            command_timeout_seconds: 5.0,
        },
    )
    .expect("worker loop");

    let commands = watchdog_commands.lock().expect("watchdog command lock");
    assert_eq!(
        commands.first(),
        Some(&PowerWatchdogCommand::Enable {
            timeout_seconds: 60
        })
    );
    assert!(commands.contains(&PowerWatchdogCommand::Feed));
    assert_eq!(commands.last(), Some(&PowerWatchdogCommand::Disable));
}

#[test]
fn worker_suppresses_watchdog_disable_for_pending_system_poweroff() {
    let watchdog_commands = Arc::new(Mutex::new(Vec::new()));
    let backend = FakeBackend {
        snapshot: PowerStatusSnapshot::default(),
        refreshes: Arc::new(Mutex::new(0)),
        control_commands: Arc::new(Mutex::new(Vec::new())),
        watchdog_commands: Arc::clone(&watchdog_commands),
    };
    let host = PowerHost::new(backend);
    let input = Cursor::new(
        br#"{"schema_version":1,"kind":"command","type":"power.watchdog_suppress","payload":{"reason":"pending_system_poweroff"}}
{"schema_version":1,"kind":"command","type":"worker.stop","payload":{}}
"#
        .to_vec(),
    );
    let mut output = Vec::new();

    run_host_loop_with_watchdog(
        host,
        input,
        &mut output,
        Duration::from_secs(60),
        PowerWatchdogConfig {
            enabled: true,
            timeout_seconds: 60,
            feed_interval_seconds: 15.0,
            i2c_bus: 1,
            i2c_address: 0x57,
            command_timeout_seconds: 5.0,
        },
    )
    .expect("worker loop");

    assert_eq!(
        *watchdog_commands.lock().expect("watchdog command lock"),
        vec![PowerWatchdogCommand::Enable {
            timeout_seconds: 60
        }]
    );
}

struct DelayedInput {
    payload: Cursor<Vec<u8>>,
    delay: Duration,
    delayed: bool,
}

impl DelayedInput {
    fn new(payload: Vec<u8>, delay: Duration) -> Self {
        Self {
            payload: Cursor::new(payload),
            delay,
            delayed: false,
        }
    }
}

impl Read for DelayedInput {
    fn read(&mut self, buffer: &mut [u8]) -> std::io::Result<usize> {
        if !self.delayed {
            self.delayed = true;
            thread::sleep(self.delay);
        }
        self.payload.read(buffer)
    }
}
