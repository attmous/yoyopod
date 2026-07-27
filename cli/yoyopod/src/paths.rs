//! Path constants for dev-machine and Pi.
//!
//! Ports the dataclasses from the old paths.py — `PiPaths`, `LanePaths`,
//! `SlotPaths` — into Rust structs. The defaults are baked in; per-host
//! overrides are applied by `deploy_config::load_*`.

/// Default paths on the Pi (overridable via pi-deploy.local.yaml).
#[derive(Debug, Clone)]
pub struct PiPaths {
    pub project_dir: String,
    pub start_cmd: String,
    pub log_file: String,
    pub error_log_file: String,
    pub pid_file: String,
    pub screenshot_path: String,
    pub startup_marker: String,
    pub kill_processes: Vec<String>,
    pub rsync_exclude: Vec<String>,
}

impl Default for PiPaths {
    fn default() -> Self {
        Self {
            project_dir: "/opt/yoyopod-dev/checkout".to_string(),
            start_cmd: "device/runtime/build/yoyopod-runtime --config-dir config".to_string(),
            log_file: "logs/yoyopod.log".to_string(),
            error_log_file: "logs/yoyopod_errors.log".to_string(),
            pid_file: "/opt/yoyopod-dev/state/yoyopod.pid".to_string(),
            screenshot_path: "/tmp/yoyopod_screenshot.png".to_string(),
            startup_marker: "yoyopod Rust runtime starting".to_string(),
            kill_processes: vec!["yoyopod-runtime".to_string()],
            rsync_exclude: vec![
                ".git/".to_string(),
                ".cache/".to_string(),
                "__pycache__/".to_string(),
                "*.pyc".to_string(),
                ".venv/".to_string(),
                "build/".to_string(),
                "logs/".to_string(),
                "models/".to_string(),
                "node_modules/".to_string(),
                "*.egg-info/".to_string(),
            ],
        }
    }
}

/// Dev/prod lane roots and systemd unit names on the Pi.
#[derive(Debug, Clone)]
pub struct LanePaths {
    pub dev_root: String,
    pub dev_checkout: String,
    pub dev_state: String,
    pub dev_logs: String,
    pub prod_root: String,
    pub prod_service: String,
    pub prod_rollback_service: String,
    pub prod_ota_service: String,
    pub prod_ota_timer: String,
    pub dev_service: String,
    pub legacy_slot_service: String,
}

impl Default for LanePaths {
    fn default() -> Self {
        Self {
            dev_root: "/opt/yoyopod-dev".to_string(),
            dev_checkout: "/opt/yoyopod-dev/checkout".to_string(),
            dev_state: "/opt/yoyopod-dev/state".to_string(),
            dev_logs: "/opt/yoyopod-dev/logs".to_string(),
            prod_root: "/opt/yoyopod-prod".to_string(),
            prod_service: "yoyopod-prod.service".to_string(),
            prod_rollback_service: "yoyopod-prod-rollback.service".to_string(),
            prod_ota_service: "yoyopod-prod-ota.service".to_string(),
            prod_ota_timer: "yoyopod-prod-ota.timer".to_string(),
            dev_service: "yoyopod-dev.service".to_string(),
            legacy_slot_service: "yoyopod-slot.service".to_string(),
        }
    }
}

// SlotPaths returns in Round 3 when the slot-deploy commands come back.
