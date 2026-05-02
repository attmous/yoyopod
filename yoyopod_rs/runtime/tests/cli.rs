use std::fs;
use std::path::{Path, PathBuf};
use std::sync::{Mutex, MutexGuard};
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use clap::CommandFactory;
use yoyopod_runtime::cli::{run, Args};
use yoyopod_runtime::logging::{
    append_marker_to_log, remove_pid_file, startup_marker, write_pid_file,
};

static ENV_LOCK: Mutex<()> = Mutex::new(());

#[test]
fn runtime_help_mentions_config_dir_and_dry_run() {
    let mut help = Vec::new();
    Args::command()
        .write_long_help(&mut help)
        .expect("render help");
    let help = String::from_utf8(help).expect("utf8 help");

    assert!(help.contains("--config-dir"));
    assert!(help.contains("--dry-run"));
    assert!(help.contains("--hardware"));
}

#[test]
fn dry_run_prints_redacted_config_and_does_not_start_workers() {
    let dir = temp_dir("dry-run");
    write(
        &dir.join("communication/calling.secrets.yaml"),
        r#"
secrets:
  sip_password: "top-secret"
  sip_password_ha1: "ha1-secret"
"#,
    );

    let output = run(Args {
        config_dir: dir.clone(),
        dry_run: true,
        hardware: "whisplay".to_string(),
    })
    .expect("dry run");

    assert!(output.contains("<redacted>"));
    assert!(!output.contains("top-secret"));
    assert!(!output.contains("ha1-secret"));
}

#[test]
fn pid_and_log_helpers_write_expected_runtime_files() {
    let dir = temp_dir("pid-log");
    let pid_file = dir.join("runtime.pid");
    let log_file = dir.join("logs/yoyopod.log");
    let pid = 4242;

    write_pid_file(&pid_file, pid).expect("write pid");
    append_marker_to_log(&log_file, startup_marker("0.1.0", pid)).expect("append log");

    assert_eq!(fs::read_to_string(&pid_file).expect("read pid"), "4242\n");
    let log = fs::read_to_string(&log_file).expect("read log");
    assert!(log.contains("YoYoPod starting"));
    assert!(log.contains("version=0.1.0"));
    assert!(log.contains("pid=4242"));

    remove_pid_file(&pid_file).expect("remove pid");
    assert!(!pid_file.exists());
}

#[cfg(unix)]
#[test]
fn pid_file_helper_replaces_unwritable_stale_file() {
    use std::os::unix::fs::PermissionsExt;

    let dir = temp_dir("stale-pid");
    let pid_file = dir.join("runtime.pid");
    fs::create_dir_all(&dir).expect("stale pid dir");
    fs::write(&pid_file, "stale\n").expect("seed stale pid");
    let mut permissions = fs::metadata(&pid_file)
        .expect("stale pid metadata")
        .permissions();
    permissions.set_mode(0o444);
    fs::set_permissions(&pid_file, permissions).expect("make stale pid unwritable");

    write_pid_file(&pid_file, 5150).expect("replace stale pid");

    assert_eq!(fs::read_to_string(&pid_file).expect("read pid"), "5150\n");
}

#[test]
fn startup_log_failure_removes_pid_file() {
    let dir = temp_dir("startup-log-failure");
    let config_dir = dir.join("config");
    let pid_file = dir.join("run/yoyopod.pid");
    let log_file = dir.join("log-dir");
    fs::create_dir_all(&log_file).expect("log dir");
    write(
        &config_dir.join("app/core.yaml"),
        &format!(
            r#"
logging:
  pid_file: "{}"
  file: "{}"
"#,
            yaml_path(&pid_file),
            yaml_path(&log_file)
        ),
    );

    let error = run(Args {
        config_dir,
        dry_run: false,
        hardware: "whisplay".to_string(),
    })
    .expect_err("directory log path must fail");

    let _ = error;
    assert!(!pid_file.exists());
}

#[test]
fn boot_sends_initial_runtime_snapshot_before_idle_loop() {
    let _guard = env_lock();
    let dir = temp_dir("initial-snapshot");
    let config_dir = dir.join("config");
    let ui_stdin = dir.join("ui-stdin.ndjson");
    let ui_worker = write_ui_worker_script(&dir, &ui_stdin);
    write(
        &config_dir.join("app/core.yaml"),
        &format!(
            r#"
logging:
  pid_file: "{}"
  file: "{}"
"#,
            yaml_path(&dir.join("run/yoyopod.pid")),
            yaml_path(&dir.join("logs/yoyopod.log"))
        ),
    );
    std::env::set_var("YOYOPOD_RUST_UI_HOST_WORKER", &ui_worker);

    let result = run(Args {
        config_dir,
        dry_run: false,
        hardware: "whisplay".to_string(),
    });
    std::env::remove_var("YOYOPOD_RUST_UI_HOST_WORKER");
    result.expect("runtime exits after UI shutdown intent");

    let captured = wait_for_file(&ui_stdin);
    let set_backlight = captured
        .find(r#""type":"ui.set_backlight""#)
        .expect("set backlight command");
    let snapshot = captured
        .find(r#""type":"ui.runtime_snapshot""#)
        .expect("initial runtime snapshot command");
    let tick = captured.find(r#""type":"ui.tick""#).expect("tick command");

    assert!(set_backlight < snapshot);
    assert!(snapshot < tick);
    assert!(captured.contains(r#""app_state":"hub""#));
}

#[test]
fn boot_marks_optional_media_ready_timeout_degraded_in_initial_snapshot() {
    let _guard = env_lock();
    let dir = temp_dir("media-timeout");
    let config_dir = dir.join("config");
    let ui_stdin = dir.join("ui-stdin.ndjson");
    let ui_worker = write_ui_worker_script(&dir, &ui_stdin);
    let media_worker = write_silent_worker_script(&dir, "media-worker");
    write(
        &config_dir.join("app/core.yaml"),
        &format!(
            r#"
logging:
  pid_file: "{}"
  file: "{}"
"#,
            yaml_path(&dir.join("run/yoyopod.pid")),
            yaml_path(&dir.join("logs/yoyopod.log"))
        ),
    );
    std::env::set_var("YOYOPOD_RUST_UI_HOST_WORKER", &ui_worker);
    std::env::set_var("YOYOPOD_RUST_MEDIA_HOST_WORKER", &media_worker);

    let result = run(Args {
        config_dir,
        dry_run: false,
        hardware: "whisplay".to_string(),
    });
    std::env::remove_var("YOYOPOD_RUST_UI_HOST_WORKER");
    std::env::remove_var("YOYOPOD_RUST_MEDIA_HOST_WORKER");
    result.expect("runtime exits after UI shutdown intent");

    let captured = wait_for_file(&ui_stdin);

    assert!(captured.contains(r#""media":{"last_reason":"timed out waiting for media.ready""#));
    assert!(captured.contains("timed out waiting for media.ready"));
    assert!(!captured.contains(r#""state":"starting""#));
}

#[test]
fn boot_starts_network_worker_and_projects_status_and_setup_pages() {
    let _guard = env_lock();
    let dir = temp_dir("network-worker");
    let config_dir = dir.join("config");
    let ui_stdin = dir.join("ui-stdin.ndjson");
    let network_args = dir.join("network-args.txt");
    let network_stdin = dir.join("network-stdin.ndjson");
    let ui_worker = write_ui_worker_script(&dir, &ui_stdin);
    let network_worker = write_network_worker_script(&dir, &network_args, &network_stdin);
    write(
        &config_dir.join("app/core.yaml"),
        &format!(
            r#"
logging:
  pid_file: "{}"
  file: "{}"
"#,
            yaml_path(&dir.join("run/yoyopod.pid")),
            yaml_path(&dir.join("logs/yoyopod.log"))
        ),
    );
    std::env::set_var("YOYOPOD_RUST_UI_HOST_WORKER", &ui_worker);
    std::env::set_var("YOYOPOD_RUST_NETWORK_HOST_WORKER", &network_worker);

    let result = run(Args {
        config_dir: config_dir.clone(),
        dry_run: false,
        hardware: "whisplay".to_string(),
    });
    std::env::remove_var("YOYOPOD_RUST_UI_HOST_WORKER");
    std::env::remove_var("YOYOPOD_RUST_NETWORK_HOST_WORKER");
    result.expect("runtime exits after UI shutdown intent");

    let captured_ui = wait_for_file(&ui_stdin);
    let captured_network_args = wait_for_file(&network_args);
    let captured_network_stdin = wait_for_file(&network_stdin);
    let normalized_network_args = captured_network_args.replace('\\', "/");

    assert!(captured_network_args.contains("--config-dir"));
    assert!(normalized_network_args.contains(&yaml_path(&config_dir)));
    assert!(captured_network_stdin.contains(r#""type":"network.health""#));
    assert!(captured_network_stdin.contains(r#""type":"network.query_gps""#));
    assert!(captured_ui.contains(r#""network":{"connected":true"#));
    assert!(captured_ui.contains(r#""enabled":true"#));
    assert!(captured_ui.contains(r#""signal_strength":3"#));
    assert!(captured_ui.contains(r#""gps_has_fix":true"#));
    assert!(captured_ui.contains(r#""title":"Network""#));
    assert!(captured_ui.contains(r#""title":"GPS""#));
    assert!(captured_ui.contains(r#"Carrier: Telekom.de"#));
    assert!(captured_ui.contains(r#"Fix: Yes"#));
}

#[test]
fn boot_starts_cloud_worker_and_sends_startup_telemetry_commands() {
    let _guard = env_lock();
    let dir = temp_dir("cloud-worker");
    let config_dir = dir.join("config");
    let ui_stdin = dir.join("ui-stdin.ndjson");
    let cloud_args = dir.join("cloud-args.txt");
    let cloud_stdin = dir.join("cloud-stdin.ndjson");
    let ui_worker = write_ui_worker_script(&dir, &ui_stdin);
    let cloud_worker = write_cloud_worker_script(&dir, &cloud_args, &cloud_stdin);
    write(
        &config_dir.join("app/core.yaml"),
        &format!(
            r#"
logging:
  pid_file: "{}"
  file: "{}"
"#,
            yaml_path(&dir.join("run/yoyopod.pid")),
            yaml_path(&dir.join("logs/yoyopod.log"))
        ),
    );
    std::env::set_var("YOYOPOD_RUST_UI_HOST_WORKER", &ui_worker);
    std::env::set_var("YOYOPOD_RUST_CLOUD_HOST_WORKER", &cloud_worker);

    let result = run(Args {
        config_dir: config_dir.clone(),
        dry_run: false,
        hardware: "whisplay".to_string(),
    });
    std::env::remove_var("YOYOPOD_RUST_UI_HOST_WORKER");
    std::env::remove_var("YOYOPOD_RUST_CLOUD_HOST_WORKER");
    result.expect("runtime exits after UI shutdown intent");

    let captured_ui = wait_for_file(&ui_stdin);
    let captured_cloud_args = wait_for_file(&cloud_args);
    let captured_cloud_stdin = wait_for_file(&cloud_stdin);
    let normalized_cloud_args = captured_cloud_args.replace('\\', "/");

    assert!(captured_cloud_args.contains("--config-dir"));
    assert!(normalized_cloud_args.contains(&yaml_path(&config_dir)));
    assert!(captured_cloud_stdin.contains(r#""type":"cloud.health""#));
    assert!(captured_cloud_stdin.contains(r#""type":"cloud.publish_heartbeat""#));
    assert!(captured_cloud_stdin.contains(r#""type":"cloud.publish_battery""#));
    assert!(captured_ui.contains(r#""cloud""#));
    assert!(captured_ui.contains(r#""state":"running""#));
}

fn temp_dir(test_name: &str) -> PathBuf {
    let unique = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("time")
        .as_nanos();
    std::env::temp_dir().join(format!("yoyopod-runtime-cli-{test_name}-{unique}"))
}

fn env_lock() -> MutexGuard<'static, ()> {
    ENV_LOCK.lock().expect("env lock")
}

fn write(path: &Path, contents: &str) {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).expect("parent dir");
    }
    fs::write(path, contents).expect("write file");
}

fn yaml_path(path: &Path) -> String {
    path.to_string_lossy().replace('\\', "/")
}

fn write_ui_worker_script(dir: &Path, stdin_path: &Path) -> PathBuf {
    if !cfg!(windows) {
        let script_path = dir.join("ui-worker.sh");
        write(
            &script_path,
            &format!(
                r#"#!/bin/sh
printf '%s\n' '{{"schema_version":1,"kind":"event","type":"ui.ready","payload":{{}}}}'
printf '%s\n' '{{"schema_version":1,"kind":"event","type":"ui.intent","payload":{{"domain":"runtime","action":"shutdown","payload":{{}}}}}}'
while IFS= read -r line; do
  printf '%s\n' "$line" >> {}
  case "$line" in
    *'"type":"ui.tick"'*) break ;;
  esac
done
"#,
                shell_single_quote(stdin_path)
            ),
        );
        make_executable(&script_path);
        return script_path;
    }

    let script_path = dir.join("ui-worker.ps1");
    write(
        &script_path,
        &format!(
            r#"
Write-Output '{{"schema_version":1,"kind":"event","type":"ui.ready","payload":{{}}}}'
Write-Output '{{"schema_version":1,"kind":"event","type":"ui.intent","payload":{{"domain":"runtime","action":"shutdown","payload":{{}}}}}}'
$lines = @()
while (($line = [Console]::In.ReadLine()) -ne $null) {{
  $lines += $line
  if ($line -match '"type":"ui.tick"') {{
    break
  }}
}}
Set-Content -LiteralPath '{}' -Value $lines
"#,
            stdin_path.to_string_lossy().replace('\'', "''")
        ),
    );
    let command_path = dir.join("ui-worker.cmd");
    write(
        &command_path,
        &format!(
            "@echo off\r\npowershell -NoProfile -ExecutionPolicy Bypass -File \"{}\"\r\n",
            script_path.to_string_lossy()
        ),
    );
    command_path
}

fn write_silent_worker_script(dir: &Path, name: &str) -> PathBuf {
    if !cfg!(windows) {
        let script_path = dir.join(format!("{name}.sh"));
        write(
            &script_path,
            r#"#!/bin/sh
sleep 10
"#,
        );
        make_executable(&script_path);
        return script_path;
    }

    let script_path = dir.join(format!("{name}.ps1"));
    write(
        &script_path,
        r#"
Start-Sleep -Seconds 10
"#,
    );
    let command_path = dir.join(format!("{name}.cmd"));
    write(
        &command_path,
        &format!(
            "@echo off\r\npowershell -NoProfile -ExecutionPolicy Bypass -File \"{}\"\r\n",
            script_path.to_string_lossy()
        ),
    );
    command_path
}

fn write_network_worker_script(dir: &Path, args_path: &Path, stdin_path: &Path) -> PathBuf {
    let ready = r#"{"schema_version":1,"kind":"event","type":"network.ready","payload":{"capabilities":["cellular","gps"]}}"#;
    let snapshot = r#"{"schema_version":1,"kind":"event","type":"network.snapshot","payload":{"enabled":true,"connected":true,"connection_type":"4g","signal":{"bars":3},"gps_has_fix":true,"app_state":{"network_enabled":true,"signal_bars":3,"connection_type":"4g","connected":true,"gps_has_fix":true},"views":{"setup":{"network_enabled":true,"network_rows":[["Status","Online"],["Carrier","Telekom.de"],["Type","4G"],["Signal","3/4"],["PPP","Up"]],"gps_rows":[["Fix","Yes"],["Lat","52.520000"],["Lng","13.405000"],["Alt","35.0m"],["Speed","0.0km/h"]]}}}}"#;

    if !cfg!(windows) {
        let script_path = dir.join("network-worker.sh");
        write(
            &script_path,
            &format!(
                r#"#!/bin/sh
printf '%s\n' "$@" > {}
printf '%s\n' '{}'
printf '%s\n' '{}'
while IFS= read -r line; do
  printf '%s\n' "$line" >> {}
  case "$line" in
    *'"type":"worker.stop"'*) break ;;
  esac
done
"#,
                shell_single_quote(args_path),
                ready,
                snapshot,
                shell_single_quote(stdin_path)
            ),
        );
        make_executable(&script_path);
        return script_path;
    }

    let script_path = dir.join("network-worker.ps1");
    write(
        &script_path,
        &format!(
            r#"
Set-Content -LiteralPath '{}' -Value ($args -join "`n")
Write-Output '{}'
Write-Output '{}'
$lines = @()
while (($line = [Console]::In.ReadLine()) -ne $null) {{
  $lines += $line
  if ($line -match '"type":"worker.stop"') {{
    break
  }}
}}
Set-Content -LiteralPath '{}' -Value $lines
"#,
            args_path.to_string_lossy().replace('\'', "''"),
            ready.replace('\'', "''"),
            snapshot.replace('\'', "''"),
            stdin_path.to_string_lossy().replace('\'', "''")
        ),
    );
    let command_path = dir.join("network-worker.cmd");
    write(
        &command_path,
        &format!(
            "@echo off\r\npowershell -NoProfile -ExecutionPolicy Bypass -File \"{}\" %*\r\n",
            script_path.to_string_lossy()
        ),
    );
    command_path
}

fn write_cloud_worker_script(dir: &Path, args_path: &Path, stdin_path: &Path) -> PathBuf {
    let ready = r#"{"schema_version":1,"kind":"event","type":"cloud.ready","payload":{"capabilities":["mqtt","telemetry"]}}"#;
    let snapshot = r#"{"schema_version":1,"kind":"event","type":"cloud.snapshot","payload":{"device_id":"device-123","provisioning_state":"provisioned","cloud_state":"ready","mqtt_connected":true,"mqtt_broker_host":"mqtt.example.test","mqtt_broker_port":1883,"mqtt_transport":"tcp","config_source":"none","config_version":0,"backend_reachable":null,"last_successful_sync":null,"last_error_summary":"","unapplied_keys":[],"last_command_type":"","updated_at_ms":1}}"#;

    if !cfg!(windows) {
        let script_path = dir.join("cloud-worker.sh");
        write(
            &script_path,
            &format!(
                r#"#!/bin/sh
printf '%s\n' "$@" > {}
printf '%s\n' '{}'
printf '%s\n' '{}'
while IFS= read -r line; do
  printf '%s\n' "$line" >> {}
  case "$line" in
    *'"type":"worker.stop"'*) break ;;
  esac
done
"#,
                shell_single_quote(args_path),
                ready,
                snapshot,
                shell_single_quote(stdin_path)
            ),
        );
        make_executable(&script_path);
        return script_path;
    }

    let script_path = dir.join("cloud-worker.ps1");
    write(
        &script_path,
        &format!(
            r#"
Set-Content -LiteralPath '{}' -Value ($args -join "`n")
Write-Output '{}'
Write-Output '{}'
$lines = @()
while (($line = [Console]::In.ReadLine()) -ne $null) {{
  $lines += $line
  if ($line -match '"type":"worker.stop"') {{
    break
  }}
}}
Set-Content -LiteralPath '{}' -Value $lines
"#,
            args_path.to_string_lossy().replace('\'', "''"),
            ready.replace('\'', "''"),
            snapshot.replace('\'', "''"),
            stdin_path.to_string_lossy().replace('\'', "''")
        ),
    );
    let command_path = dir.join("cloud-worker.cmd");
    write(
        &command_path,
        &format!(
            "@echo off\r\npowershell -NoProfile -ExecutionPolicy Bypass -File \"{}\" %*\r\n",
            script_path.to_string_lossy()
        ),
    );
    command_path
}

fn shell_single_quote(path: &Path) -> String {
    format!("'{}'", path.to_string_lossy().replace('\'', "'\\''"))
}

#[cfg(unix)]
fn make_executable(path: &Path) {
    use std::os::unix::fs::PermissionsExt;

    let mut permissions = fs::metadata(path).expect("script metadata").permissions();
    permissions.set_mode(0o755);
    fs::set_permissions(path, permissions).expect("chmod script");
}

#[cfg(not(unix))]
fn make_executable(_path: &Path) {}

fn wait_for_file(path: &Path) -> String {
    let deadline = std::time::Instant::now() + Duration::from_secs(5);
    while std::time::Instant::now() < deadline {
        if let Ok(contents) = fs::read_to_string(path) {
            if !contents.trim().is_empty() {
                return contents;
            }
        }
        std::thread::sleep(Duration::from_millis(20));
    }
    panic!("timed out waiting for {}", path.display());
}
