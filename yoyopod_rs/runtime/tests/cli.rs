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
fn cli_test_is_registered_in_bazel_runtime_tests() {
    let build_file = include_str!("../BUILD.bazel");

    assert!(build_file.contains("\"cli\""));
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
