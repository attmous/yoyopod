use std::fs;
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

use clap::CommandFactory;
use yoyopod_runtime::cli::{run, Args};
use yoyopod_runtime::logging::{
    append_marker_to_log, remove_pid_file, startup_marker, write_pid_file,
};

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

fn write(path: &Path, contents: &str) {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).expect("parent dir");
    }
    fs::write(path, contents).expect("write file");
}
