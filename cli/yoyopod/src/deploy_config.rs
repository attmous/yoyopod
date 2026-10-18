//! Deploy YAML loader: base merged with optional local override.
//!
//! Ports `paths.py:load_pi_paths` / `load_lane_paths` (the subset Round 1
//! needs) and the lane-aware dev path resolution rules. Reads
//! `deploy/pi-deploy.yaml` as the base and `deploy/pi-deploy.local.yaml`
//! as the per-machine override. Last-key wins for top-level scalars; the
//! `lane:` section gets its own merge with sensible derived defaults.

use std::collections::BTreeMap;
use std::path::Path;

use anyhow::{Context, Result};
use serde::Deserialize;

use crate::paths::{LanePaths, PiPaths};

/// Raw YAML payload (lenient).
#[derive(Debug, Default, Deserialize)]
pub struct RawConfig {
    #[serde(default)]
    pub host: Option<String>,
    #[serde(default)]
    pub user: Option<String>,
    #[serde(default)]
    pub project_dir: Option<String>,
    #[serde(default)]
    pub branch: Option<String>,
    #[serde(default)]
    pub start_cmd: Option<String>,
    #[serde(default)]
    pub log_file: Option<String>,
    #[serde(default)]
    pub error_log_file: Option<String>,
    #[serde(default)]
    pub pid_file: Option<String>,
    #[serde(default)]
    pub screenshot_path: Option<String>,
    #[serde(default)]
    pub startup_marker: Option<String>,
    #[serde(default)]
    pub kill_processes: Option<Vec<String>>,
    #[serde(default)]
    pub rsync_exclude: Option<Vec<String>>,
    #[serde(default)]
    pub lane: BTreeMap<String, String>,
}

impl RawConfig {
    /// Load a YAML file. Returns an empty config if the file doesn't exist.
    pub fn load_optional(path: &Path) -> Result<Self> {
        if !path.exists() {
            return Ok(Self::default());
        }
        let text =
            std::fs::read_to_string(path).with_context(|| format!("read {}", path.display()))?;
        let parsed: Self = serde_yaml::from_str(&text)
            .with_context(|| format!("parse YAML at {}", path.display()))?;
        Ok(parsed)
    }
}

/// Connection details resolved from CLI flags + env vars + YAML defaults.
#[derive(Debug, Clone)]
pub struct RemoteConnection {
    pub host: String,
    pub user: String,
    pub project_dir: String,
    pub branch: String,
}

impl RemoteConnection {
    /// SSH target: `user@host` or just `host` if user is empty.
    pub fn ssh_target(&self) -> String {
        if self.user.is_empty() {
            self.host.clone()
        } else {
            format!("{}@{}", self.user, self.host)
        }
    }
}

fn coerce(value: Option<String>, default: &str) -> String {
    match value {
        Some(s) if !s.trim().is_empty() => s.trim().to_string(),
        _ => default.to_string(),
    }
}

/// Resolve `RemoteConnection` from CLI flags + YAML defaults.
/// CLI flag values (passed as non-empty `Option<String>`) win; falls
/// back to base/local YAML values.
pub fn resolve_connection(
    host_flag: Option<&str>,
    user_flag: Option<&str>,
    project_dir_flag: Option<&str>,
    branch_flag: Option<&str>,
    base: &RawConfig,
    local: &RawConfig,
    pi: &PiPaths,
) -> RemoteConnection {
    // local overrides base for connection-level scalars
    let yaml_host = local.host.clone().or_else(|| base.host.clone());
    let yaml_user = local.user.clone().or_else(|| base.user.clone());
    let yaml_branch = local.branch.clone().or_else(|| base.branch.clone());

    RemoteConnection {
        host: coerce(host_flag.map(str::to_owned).or(yaml_host), ""),
        user: coerce(user_flag.map(str::to_owned).or(yaml_user), ""),
        project_dir: coerce(project_dir_flag.map(str::to_owned), &pi.project_dir),
        branch: coerce(branch_flag.map(str::to_owned).or(yaml_branch), "main"),
    }
}

/// Resolve `LanePaths`, applying overrides from base+local YAML's `lane:` section.
pub fn resolve_lane(base: &RawConfig, local: &RawConfig) -> LanePaths {
    let mut lane = LanePaths::default();
    let pick = |key: &str, fallback: &str| -> String {
        if let Some(v) = local.lane.get(key) {
            if !v.trim().is_empty() {
                return v.trim().trim_end_matches('/').to_string();
            }
        }
        if let Some(v) = base.lane.get(key) {
            if !v.trim().is_empty() {
                return v.trim().trim_end_matches('/').to_string();
            }
        }
        fallback.to_string()
    };

    let dev_root = pick("dev_root", &lane.dev_root);
    let prod_root = pick("prod_root", &lane.prod_root);
    let local_dev_root = local
        .lane
        .get("dev_root")
        .is_some_and(|v| !v.trim().is_empty());

    let dev_subpath = |key: &str, suffix: &str| -> String {
        if let Some(v) = local.lane.get(key) {
            if !v.trim().is_empty() {
                return v.trim().to_string();
            }
        }
        if local_dev_root {
            return format!("{dev_root}/{suffix}");
        }
        if let Some(v) = base.lane.get(key) {
            if !v.trim().is_empty() {
                return v.trim().to_string();
            }
        }
        format!("{dev_root}/{suffix}")
    };

    lane.dev_checkout = dev_subpath("dev_checkout", "checkout");
    lane.dev_state = dev_subpath("dev_state", "state");
    lane.dev_logs = dev_subpath("dev_logs", "logs");
    lane.dev_root = dev_root;
    lane.prod_root = prod_root;
    lane.prod_service = pick("prod_service", &lane.prod_service);
    lane.prod_rollback_service = pick("prod_rollback_service", &lane.prod_rollback_service);
    lane.prod_ota_service = pick("prod_ota_service", &lane.prod_ota_service);
    lane.prod_ota_timer = pick("prod_ota_timer", &lane.prod_ota_timer);
    lane.dev_service = pick("dev_service", &lane.dev_service);
    lane.legacy_slot_service = pick("legacy_slot_service", &lane.legacy_slot_service);
    lane
}

/// Resolve `PiPaths` by applying base/local overrides on top of defaults.
pub fn resolve_pi_paths(base: &RawConfig, local: &RawConfig) -> PiPaths {
    let mut pi = PiPaths::default();
    let pick_str = |bv: &Option<String>, lv: &Option<String>, default: &str| -> String {
        if let Some(v) = lv {
            if !v.trim().is_empty() {
                return v.trim().to_string();
            }
        }
        if let Some(v) = bv {
            if !v.trim().is_empty() {
                return v.trim().to_string();
            }
        }
        default.to_string()
    };
    let pick_list =
        |bv: &Option<Vec<String>>, lv: &Option<Vec<String>>, default: &[String]| -> Vec<String> {
            if let Some(v) = lv {
                let normalized: Vec<String> = v
                    .iter()
                    .map(|s| s.trim().to_string())
                    .filter(|s| !s.is_empty())
                    .collect();
                if !normalized.is_empty() {
                    return normalized;
                }
            }
            if let Some(v) = bv {
                let normalized: Vec<String> = v
                    .iter()
                    .map(|s| s.trim().to_string())
                    .filter(|s| !s.is_empty())
                    .collect();
                if !normalized.is_empty() {
                    return normalized;
                }
            }
            default.to_vec()
        };

    let lane = resolve_lane(base, local);

    pi.project_dir = pick_str(&base.project_dir, &local.project_dir, &lane.dev_checkout);
    pi.start_cmd = pick_str(&base.start_cmd, &local.start_cmd, &pi.start_cmd);
    pi.log_file = pick_str(&base.log_file, &local.log_file, &pi.log_file);
    pi.error_log_file = pick_str(
        &base.error_log_file,
        &local.error_log_file,
        &pi.error_log_file,
    );
    let default_pid = format!("{}/yoyopod.pid", lane.dev_state.trim_end_matches('/'));
    pi.pid_file = pick_str(&base.pid_file, &local.pid_file, &default_pid);
    pi.screenshot_path = pick_str(
        &base.screenshot_path,
        &local.screenshot_path,
        &pi.screenshot_path,
    );
    pi.startup_marker = pick_str(
        &base.startup_marker,
        &local.startup_marker,
        &pi.startup_marker,
    );
    pi.kill_processes = pick_list(
        &base.kill_processes,
        &local.kill_processes,
        &pi.kill_processes,
    );
    pi.rsync_exclude = pick_list(&base.rsync_exclude, &local.rsync_exclude, &pi.rsync_exclude);
    pi
}

/// Convenience: load both YAML files relative to a repo root.
pub fn load_layered(repo_root: &Path) -> Result<(RawConfig, RawConfig)> {
    let base_path = repo_root.join("deploy/pi-deploy.yaml");
    let local_path = repo_root.join("deploy/pi-deploy.local.yaml");
    let base = RawConfig::load_optional(&base_path)?;
    let local = RawConfig::load_optional(&local_path)?;
    Ok((base, local))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;
    use tempfile::tempdir;

    fn write(dir: &Path, name: &str, body: &str) {
        fs::write(dir.join(name), body).unwrap();
    }

    #[test]
    fn missing_files_yield_defaults() {
        let tmp = tempdir().unwrap();
        // No yaml files at all.
        let (base, local) = (
            RawConfig::load_optional(&tmp.path().join("base.yaml")).unwrap(),
            RawConfig::load_optional(&tmp.path().join("local.yaml")).unwrap(),
        );
        let pi = resolve_pi_paths(&base, &local);
        assert_eq!(pi.project_dir, "/opt/yoyopod-dev/checkout");
        assert_eq!(pi.pid_file, "/opt/yoyopod-dev/state/yoyopod.pid");
        let lane = resolve_lane(&base, &local);
        assert_eq!(lane.dev_root, "/opt/yoyopod-dev");
        assert_eq!(lane.prod_service, "yoyopod-prod.service");
    }

    #[test]
    fn local_overrides_base_for_connection() {
        let tmp = tempdir().unwrap();
        write(
            tmp.path(),
            "base.yaml",
            "host: base-host\nuser: base-user\nbranch: dev\n",
        );
        write(tmp.path(), "local.yaml", "host: local-host\n");
        let base = RawConfig::load_optional(&tmp.path().join("base.yaml")).unwrap();
        let local = RawConfig::load_optional(&tmp.path().join("local.yaml")).unwrap();
        let pi = resolve_pi_paths(&base, &local);
        let conn = resolve_connection(None, None, None, None, &base, &local, &pi);
        assert_eq!(conn.host, "local-host");
        assert_eq!(conn.user, "base-user");
        assert_eq!(conn.branch, "dev");
    }

    #[test]
    fn cli_flag_overrides_yaml() {
        let tmp = tempdir().unwrap();
        write(tmp.path(), "base.yaml", "host: base-host\nbranch: main\n");
        let base = RawConfig::load_optional(&tmp.path().join("base.yaml")).unwrap();
        let local = RawConfig::default();
        let pi = resolve_pi_paths(&base, &local);
        let conn = resolve_connection(
            Some("flag-host"),
            None,
            None,
            Some("feature-branch"),
            &base,
            &local,
            &pi,
        );
        assert_eq!(conn.host, "flag-host");
        assert_eq!(conn.branch, "feature-branch");
    }

    #[test]
    fn lane_override_only_in_local() {
        let tmp = tempdir().unwrap();
        write(tmp.path(), "local.yaml", "lane:\n  dev_root: /srv/dev\n");
        let base = RawConfig::default();
        let local = RawConfig::load_optional(&tmp.path().join("local.yaml")).unwrap();
        let lane = resolve_lane(&base, &local);
        assert_eq!(lane.dev_root, "/srv/dev");
        // dev_checkout derives from dev_root
        assert_eq!(lane.dev_checkout, "/srv/dev/checkout");
        assert_eq!(lane.dev_state, "/srv/dev/state");
    }

    #[test]
    fn pid_file_derives_from_lane_dev_state_when_unset() {
        let tmp = tempdir().unwrap();
        write(tmp.path(), "local.yaml", "lane:\n  dev_root: /srv/dev\n");
        let base = RawConfig::default();
        let local = RawConfig::load_optional(&tmp.path().join("local.yaml")).unwrap();
        let pi = resolve_pi_paths(&base, &local);
        // pid_file should fall back to <dev_state>/yoyopod.pid since neither
        // base nor local set pid_file.
        // Note: the python rule was a bit more nuanced — it allowed the legacy
        // pid_file from base to win if base didn't set lane keys. Here we
        // simplify since Round 1 doesn't need that compatibility.
        assert!(pi.pid_file.ends_with("/yoyopod.pid"));
    }

    #[test]
    fn rsync_exclude_overrides_when_local_non_empty() {
        let tmp = tempdir().unwrap();
        write(
            tmp.path(),
            "local.yaml",
            "rsync_exclude:\n  - foo/\n  - bar/\n",
        );
        let base = RawConfig::default();
        let local = RawConfig::load_optional(&tmp.path().join("local.yaml")).unwrap();
        let pi = resolve_pi_paths(&base, &local);
        assert_eq!(
            pi.rsync_exclude,
            vec!["foo/".to_string(), "bar/".to_string()]
        );
    }
}
