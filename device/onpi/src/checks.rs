//! Individual validation checks shared by the stages.
//!
//! Ports the deleted `yoyopod_cli/pi/validate/` checks to Rust, adjusted
//! for the Rust-only runtime: the Python-era virtualenv and console-script
//! entrypoint checks are gone; the entrypoint contract is now "the CI-built
//! worker binaries exist and are executable".

use std::path::{Path, PathBuf};
use std::process::Command;
use std::time::Duration;

use crate::proc::run_with_timeout;
use crate::report::CheckResult;

const DRY_RUN_TIMEOUT: Duration = Duration::from_secs(10);

/// The eight CI-built worker binaries, as repo-relative paths.
pub const WORKER_BINARIES: [&str; 8] = [
    "device/runtime/build/yoyopod-runtime",
    "device/ui/build/yoyopod-ui-host",
    "device/cloud/build/yoyopod-cloud-host",
    "device/media/build/yoyopod-media-host",
    "device/voip/build/yoyopod-voip-host",
    "device/network/build/yoyopod-network-host",
    "device/power/build/yoyopod-power-host",
    "device/speech/build/yoyopod-speech-host",
];

fn binary_name(name: &str) -> String {
    if cfg!(windows) {
        format!("{name}.exe")
    } else {
        name.to_string()
    }
}

/// Resolve a repo-relative path, preferring the slot layout (`app/<path>`)
/// when it exists. Prod slots nest the checkout under `app/`.
pub fn slot_aware_path(relative: &Path) -> PathBuf {
    let slot_candidate = Path::new("app").join(relative);
    if slot_candidate.exists() {
        return slot_candidate;
    }
    relative.to_path_buf()
}

pub fn default_runtime_worker() -> PathBuf {
    slot_aware_path(&Path::new("device/runtime/build").join(binary_name("yoyopod-runtime")))
}

pub fn default_ui_worker() -> PathBuf {
    slot_aware_path(&Path::new("device/ui/build").join(binary_name("yoyopod-ui-host")))
}

/// Capture the execution environment. Pass on ARM Linux, warn elsewhere.
pub fn environment_check() -> CheckResult {
    let os = std::env::consts::OS;
    let arch = std::env::consts::ARCH;
    let details = format!(
        "os={os}, arch={arch}, validator={}",
        env!("CARGO_PKG_VERSION")
    );
    if os == "linux" && (arch.contains("arm") || arch.contains("aarch")) {
        CheckResult::pass("environment", details)
    } else {
        CheckResult::warn("environment", details)
    }
}

/// Run the Rust runtime's config/load path without starting hardware workers.
pub fn runtime_dry_run_check(config_dir: &Path, worker: Option<&Path>) -> CheckResult {
    let default_worker = default_runtime_worker();
    let runtime_worker = worker.unwrap_or(&default_worker);
    if !runtime_worker.exists() {
        return CheckResult::fail(
            "rust-runtime",
            format!(
                "missing Rust runtime binary at {}",
                runtime_worker.display()
            ),
        );
    }

    let mut command = Command::new(runtime_worker);
    command.arg("--config-dir").arg(config_dir).arg("--dry-run");
    let output = match run_with_timeout(&mut command, DRY_RUN_TIMEOUT) {
        Ok(output) => output,
        Err(error) => return CheckResult::fail("rust-runtime", error.to_string()),
    };

    if output.timed_out {
        return CheckResult::fail(
            "rust-runtime",
            format!("dry-run timed out after {}s", DRY_RUN_TIMEOUT.as_secs()),
        );
    }
    if output.exit_code != Some(0) {
        let mut details = output.stderr.trim().to_string();
        if details.is_empty() {
            details = output.stdout.trim().to_string();
        }
        if details.is_empty() {
            details = format!("dry-run exited {:?}", output.exit_code);
        }
        return CheckResult::fail("rust-runtime", details);
    }

    let payload: serde_json::Value = match serde_json::from_str(&output.stdout) {
        Ok(payload) => payload,
        Err(error) => {
            return CheckResult::fail(
                "rust-runtime",
                format!("dry-run did not emit JSON config: {error}"),
            );
        }
    };
    let configured_workers = payload
        .get("worker_paths")
        .and_then(|paths| paths.as_object())
        .map(|paths| paths.len())
        .unwrap_or(0);
    CheckResult::pass(
        "rust-runtime",
        format!(
            "binary={}, dry_run=ok, worker_paths={configured_workers}",
            runtime_worker.display()
        ),
    )
}

/// Repo-relative config files the runtime requires.
pub fn required_config_files(config_dir: &Path) -> Vec<PathBuf> {
    [
        "app/core.yaml",
        "audio/music.yaml",
        "device/hardware.yaml",
        "voice/assistant.yaml",
        "communication/calling.yaml",
        "communication/messaging.yaml",
        "communication/integrations/liblinphone_factory.conf",
        "people/directory.yaml",
        "people/contacts.seed.yaml",
    ]
    .iter()
    .map(|suffix| config_dir.join(suffix))
    .collect()
}

/// Validate that the tracked runtime config files are present.
pub fn config_files_check(config_dir: &Path) -> CheckResult {
    let required = required_config_files(config_dir);
    let missing: Vec<String> = required
        .iter()
        .filter(|path| !path.exists())
        .map(|path| path.display().to_string())
        .collect();
    if !missing.is_empty() {
        return CheckResult::fail(
            "config",
            format!("missing required config files: {}", missing.join(", ")),
        );
    }
    CheckResult::pass(
        "config",
        required
            .iter()
            .map(|path| path.display().to_string())
            .collect::<Vec<_>>()
            .join(", "),
    )
}

#[cfg(unix)]
fn is_executable(path: &Path) -> bool {
    use std::os::unix::fs::PermissionsExt;
    std::fs::metadata(path)
        .map(|meta| meta.permissions().mode() & 0o111 != 0)
        .unwrap_or(false)
}

#[cfg(not(unix))]
fn is_executable(path: &Path) -> bool {
    path.exists()
}

/// Validate that every CI-built worker binary is present and executable.
pub fn worker_binaries_check() -> CheckResult {
    let mut missing: Vec<String> = Vec::new();
    let mut found: Vec<String> = Vec::new();
    for relative in WORKER_BINARIES {
        let path = slot_aware_path(Path::new(relative));
        if path.exists() && is_executable(&path) {
            found.push(path.display().to_string());
        } else {
            missing.push(path.display().to_string());
        }
    }
    if !missing.is_empty() {
        return CheckResult::fail(
            "worker_binaries",
            format!(
                "missing or non-executable CI-built binaries: {}. Deploy the \
                 yoyopod-rust-device-arm64-<sha> artifact for this commit; do \
                 not build Rust binaries on the Pi.",
                missing.join(", ")
            ),
        );
    }
    CheckResult::pass("worker_binaries", found.join(", "))
}

/// Validate that the systemd lane units are present in the checkout.
pub fn systemd_units_check() -> CheckResult {
    let units = [
        "deploy/systemd/yoyopod-dev.service",
        "deploy/systemd/yoyopod-prod.service",
    ];
    let missing: Vec<&str> = units
        .iter()
        .copied()
        .filter(|unit| !slot_aware_path(Path::new(unit)).exists())
        .collect();
    if !missing.is_empty() {
        return CheckResult::fail(
            "systemd_units",
            format!("missing systemd unit files: {}", missing.join(", ")),
        );
    }
    CheckResult::pass("systemd_units", units.join(", "))
}

/// Runtime file paths whose parents must be reachable and writable.
pub struct RuntimePaths {
    pub log_file: PathBuf,
    pub error_log_file: PathBuf,
    pub pid_file: PathBuf,
    pub screenshot_path: PathBuf,
}

impl Default for RuntimePaths {
    fn default() -> Self {
        // Mirrors the tracked deploy contract (deploy/pi-deploy.yaml).
        Self {
            log_file: PathBuf::from("logs/yoyopod.log"),
            error_log_file: PathBuf::from("logs/yoyopod_errors.log"),
            pid_file: PathBuf::from("/opt/yoyopod-dev/state/yoyopod.pid"),
            screenshot_path: PathBuf::from("/tmp/yoyopod_screenshot.png"),
        }
    }
}

fn nearest_existing_parent(path: &Path) -> PathBuf {
    let mut candidate = if path.is_dir() {
        path.to_path_buf()
    } else {
        path.parent().map(Path::to_path_buf).unwrap_or_default()
    };
    while !candidate.as_os_str().is_empty() && !candidate.exists() {
        match candidate.parent() {
            Some(parent) => candidate = parent.to_path_buf(),
            None => break,
        }
    }
    if candidate.as_os_str().is_empty() {
        PathBuf::from(".")
    } else {
        candidate
    }
}

fn is_writable_dir(dir: &Path) -> bool {
    let probe = dir.join(format!(".yoyopod-validate-probe-{}", std::process::id()));
    match std::fs::File::create(&probe) {
        Ok(_) => {
            let _ = std::fs::remove_file(&probe);
            true
        }
        Err(_) => false,
    }
}

/// Validate that runtime file parents are reachable and writable.
pub fn runtime_paths_check(paths: &RuntimePaths) -> CheckResult {
    let path_map = [
        ("log", &paths.log_file),
        ("error_log", &paths.error_log_file),
        ("pid", &paths.pid_file),
        ("screenshot", &paths.screenshot_path),
    ];

    let mut details: Vec<String> = Vec::new();
    let mut failures: Vec<String> = Vec::new();
    for (name, path) in path_map {
        let parent = nearest_existing_parent(path);
        details.push(format!("{name}_parent={}", parent.display()));
        if !is_writable_dir(&parent) {
            failures.push(format!("{name}_parent_not_writable={}", parent.display()));
        }
    }

    if !failures.is_empty() {
        return CheckResult::fail("runtime_paths", failures.join(", "));
    }
    CheckResult::pass("runtime_paths", details.join(", "))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::report::CheckStatus;

    #[test]
    fn required_config_files_are_rooted_at_config_dir() {
        let files = required_config_files(Path::new("config"));
        assert_eq!(files.len(), 9);
        assert!(files.iter().all(|path| path.starts_with("config")));
        assert!(files
            .iter()
            .any(|path| path.ends_with("communication/integrations/liblinphone_factory.conf")));
    }

    #[test]
    fn nearest_existing_parent_walks_up() {
        let missing = Path::new("definitely/not/a/real/path/file.log");
        let parent = nearest_existing_parent(missing);
        assert!(parent.exists());
    }

    #[test]
    fn environment_check_reports_os_and_arch() {
        let result = environment_check();
        assert_eq!(result.name, "environment");
        assert!(result.details.contains("os="));
        assert!(result.details.contains("arch="));
    }

    #[test]
    fn runtime_dry_run_fails_on_missing_binary() {
        let result = runtime_dry_run_check(Path::new("config"), Some(Path::new("no/such/binary")));
        assert_eq!(result.status, CheckStatus::Fail);
        assert!(result.details.contains("missing Rust runtime binary"));
    }
}
