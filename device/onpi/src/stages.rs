//! Validation stages: each assembles checks, prints the summary, and
//! returns the process exit code (0 pass, 1 fail, 2 blocked).

use std::path::Path;

use crate::checks;
use crate::report::{exit_code, print_summary};
use crate::ui_host;

pub fn smoke(config_dir: &Path, hardware: &str, display_hold_seconds: f64) -> i32 {
    let results = vec![
        checks::environment_check(),
        checks::runtime_dry_run_check(config_dir, None),
        ui_host::ui_smoke_check(&checks::default_ui_worker(), hardware, display_hold_seconds),
    ];
    print_summary("smoke", &results);
    exit_code(&results)
}

pub fn deploy(config_dir: &Path) -> i32 {
    let results = vec![
        checks::config_files_check(config_dir),
        checks::worker_binaries_check(),
        checks::systemd_units_check(),
        checks::runtime_paths_check(&checks::RuntimePaths::default()),
    ];
    print_summary("deploy", &results);
    exit_code(&results)
}

pub fn stability(config_dir: &Path, cycles: u32, hold_seconds: f64, idle_seconds: f64) -> i32 {
    let results = vec![
        checks::runtime_dry_run_check(config_dir, None),
        ui_host::ui_navigation_check(
            &checks::default_ui_worker(),
            cycles,
            hold_seconds,
            idle_seconds,
            hold_seconds,
        ),
    ];
    print_summary("stability", &results);
    exit_code(&results)
}

#[allow(clippy::too_many_arguments)]
pub fn navigation(
    config_dir: &Path,
    cycles: u32,
    hold_seconds: f64,
    idle_seconds: f64,
    tail_idle_seconds: f64,
) -> i32 {
    let results = vec![
        checks::runtime_dry_run_check(config_dir, None),
        ui_host::ui_navigation_check(
            &checks::default_ui_worker(),
            cycles,
            hold_seconds,
            idle_seconds,
            tail_idle_seconds,
        ),
    ];
    print_summary("navigation", &results);
    exit_code(&results)
}

pub fn lvgl(config_dir: &Path, cycles: u32, hold_seconds: f64, idle_seconds: f64) -> i32 {
    let results = vec![
        checks::runtime_dry_run_check(config_dir, None),
        ui_host::ui_navigation_check(
            &checks::default_ui_worker(),
            cycles,
            hold_seconds,
            idle_seconds,
            hold_seconds,
        ),
    ];
    print_summary("lvgl", &results);
    exit_code(&results)
}

pub fn voip_stub() -> i32 {
    eprintln!(
        "validate voip: not yet ported to Rust (Round 2 follow-up).\n\
         See docs/ROADMAP.md. Until then, verify SIP registration manually:\n\
           journalctl -u yoyopod-dev.service | grep -i -E 'sip|regist'"
    );
    2
}

pub fn cloud_voice_stub() -> i32 {
    eprintln!(
        "validate cloud-voice: not yet ported to Rust (Round 2 follow-up).\n\
         See docs/ROADMAP.md. Until then, exercise the voice path manually\n\
         on-device and watch the speech worker logs."
    );
    2
}
