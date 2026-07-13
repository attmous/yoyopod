//! `yoyopod target validate` — run staged on-Pi validation over SSH.
//!
//! Round 2 of the CLI rebuild. Mirrors the deleted `remote_validate.py`:
//! enforce the committed-code contract locally, sync the Pi checkout to
//! the pushed revision, verify the CI-built binaries are installed, then
//! run the `yoyopod-on-pi validate ...` stages shipped inside the
//! `yoyopod-rust-device-arm64-<sha>` artifact.
//!
//! Base stages: deploy, smoke, stability. `--with-lvgl-soak` and
//! `--with-navigation` add their soaks. The voip and cloud-voice stages
//! are not ported yet (Round 2 follow-up) and are rejected up front.

use anyhow::{bail, Result};

use crate::cli::ValidateArgs;
use crate::deploy_config::{resolve_lane, RawConfig};
use crate::paths::{LanePaths, PiPaths};
use crate::quoting::shell_quote;
use crate::ssh::{run_remote, RemoteWorkdir};

use super::deploy::{
    build_pi_sync, capture_head_sha, require_branch_pushed, require_local_clean_tree,
    require_local_not_ahead, require_sha_reachable, ARTIFACT_SHA_FILE,
};
use super::{maybe_dry_run, ops, TargetContext};

const ON_PI_BINARY: &str = "device/onpi/build/yoyopod-on-pi";

/// Binaries the base stages exercise; checked before any stage runs so a
/// half-deployed checkout fails loudly instead of mid-validation.
const REQUIRED_BINARIES: [&str; 9] = [
    "device/runtime/build/yoyopod-runtime",
    "device/ui/build/yoyopod-ui-host",
    "device/cloud/build/yoyopod-cloud-host",
    "device/media/build/yoyopod-media-host",
    "device/voip/build/yoyopod-voip-host",
    "device/network/build/yoyopod-network-host",
    "device/power/build/yoyopod-power-host",
    "device/speech/build/yoyopod-speech-host",
    ON_PI_BINARY,
];

pub fn run(
    ctx: &TargetContext,
    base: &RawConfig,
    local: &RawConfig,
    args: ValidateArgs,
) -> Result<i32> {
    if args.with_voip {
        bail!(
            "--with-voip: the VoIP validation stage has not been ported to Rust yet \
             (Round 2 follow-up; see docs/ROADMAP.md)."
        );
    }
    if args.with_rust_ui_host {
        bail!(
            "--with-rust-ui-host: the rust-ui-host diagnostic returns with the Round 4+ \
             diagnostics (see docs/ROADMAP.md)."
        );
    }

    let branch = ctx.conn.branch.clone();

    // Committed-code contract, fail-fast even in dry-run (matches deploy).
    require_local_clean_tree()?;
    require_branch_pushed(&branch)?;
    if args.sha.is_empty() {
        require_local_not_ahead(&branch)?;
    } else {
        require_sha_reachable(&branch, &args.sha)?;
    }
    let resolved_sha = if args.sha.is_empty() {
        capture_head_sha()?
    } else {
        args.sha.clone()
    };

    let lane = resolve_lane(base, local);
    let remote_cmd = build_validate_script(&branch, &resolved_sha, &args, &lane, &ctx.pi);
    if let Some(rc) = maybe_dry_run(ctx, "validate", &remote_cmd) {
        return Ok(rc);
    }
    run_remote(&ctx.conn, &remote_cmd, false, RemoteWorkdir::Default)
}

fn require_executable(path: &str) -> String {
    let quoted_path = shell_quote(path);
    let message = shell_quote(&format!(
        "Missing executable CI-built binary at {path}. Deploy the GitHub Actions \
         artifact yoyopod-rust-device-arm64-<sha> for this exact commit \
         (`yoyopod target deploy`) before Pi validation; do not build Rust \
         binaries on the Pi."
    ));
    format!("test -x {quoted_path} || (echo {message} >&2 && exit 1)")
}

fn require_artifact_sha(expected_sha: &str) -> String {
    let expected_sha = shell_quote(expected_sha);
    format!(
        "test -f {ARTIFACT_SHA_FILE} && \
         test \"$(tr -d '\\r\\n' < {ARTIFACT_SHA_FILE})\" = {expected_sha} || \
         (echo 'Installed worker artifact does not match the requested commit; run `yoyopod target deploy` first.' >&2 && exit 2)"
    )
}

fn build_service_isolation(lane: &LanePaths, pi: &PiPaths) -> String {
    let dev = shell_quote(&lane.dev_service);
    let prod = shell_quote(&lane.prod_service);
    let pid = shell_quote(&pi.pid_file);
    let verify = ops::build_startup_verification(pi, 20);
    let stale_cleanup = ops::build_stale_runtime_cleanup();
    format!(
        "if systemctl is-active --quiet {prod}; then \
         echo 'target validate: prod lane owns the hardware; activate dev first' >&2; exit 2; fi; \
         was_active=0; \
         if systemctl is-active --quiet {dev}; then was_active=1; fi; \
         restore_validation_service() {{ \
           rc=$?; trap - EXIT; \
           if [ \"$was_active\" -eq 1 ]; then \
             if sudo systemctl start {dev} && {verify}; then \
               echo 'target validate: restored dev service'; \
             else \
               restore_rc=$?; \
               echo 'target validate: failed to restore dev service' >&2; \
               if [ \"$rc\" -eq 0 ]; then rc=$restore_rc; fi; \
             fi; \
           fi; \
           exit \"$rc\"; \
         }}; \
         trap restore_validation_service EXIT; \
         if [ \"$was_active\" -eq 1 ]; then sudo systemctl stop {dev}; fi; \
         rm -f {pid} 2>/dev/null || sudo rm -f {pid}; \
         {stale_cleanup}"
    )
}

fn build_validate_script(
    branch: &str,
    expected_sha: &str,
    args: &ValidateArgs,
    lane: &LanePaths,
    pi: &PiPaths,
) -> String {
    // Stop the dev runtime before syncing or starting an isolated UI host. The
    // EXIT trap restores the service whether a stage passes or fails.
    let mut steps = vec![
        build_service_isolation(lane, pi),
        build_pi_sync(branch, expected_sha, false),
        require_artifact_sha(expected_sha),
    ];
    for binary in REQUIRED_BINARIES {
        steps.push(require_executable(binary));
    }
    let expected_env = format!(
        "YOYOPOD_EXPECTED_ARTIFACT_SHA={} ",
        shell_quote(expected_sha)
    );
    steps.push(format!("{expected_env}{ON_PI_BINARY} validate deploy"));
    steps.push(format!("{expected_env}{ON_PI_BINARY} validate smoke"));
    steps.push(format!("{expected_env}{ON_PI_BINARY} validate stability"));
    if args.with_lvgl_soak {
        steps.push(format!("{expected_env}{ON_PI_BINARY} validate lvgl"));
    }
    if args.with_navigation {
        steps.push(format!("{expected_env}{ON_PI_BINARY} validate navigation"));
    }
    steps.join(" && ")
}

#[cfg(test)]
mod tests {
    use super::*;

    fn base_args() -> ValidateArgs {
        ValidateArgs {
            sha: String::new(),
            with_voip: false,
            with_lvgl_soak: false,
            with_navigation: false,
            with_rust_ui_host: false,
        }
    }

    #[test]
    fn base_script_runs_deploy_smoke_stability() {
        let script = build_validate_script(
            "main",
            "abc123",
            &base_args(),
            &LanePaths::default(),
            &PiPaths::default(),
        );
        assert!(script.contains("git checkout --force -B main origin/main"));
        assert!(script.contains("device/onpi/build/yoyopod-on-pi validate deploy"));
        assert!(script.contains("device/onpi/build/yoyopod-on-pi validate smoke"));
        assert!(script.contains("device/onpi/build/yoyopod-on-pi validate stability"));
        assert!(!script.contains("validate lvgl"));
        assert!(!script.contains("validate navigation"));
    }

    #[test]
    fn script_checks_binaries_before_stages() {
        let script = build_validate_script(
            "main",
            "abc123",
            &base_args(),
            &LanePaths::default(),
            &PiPaths::default(),
        );
        let binary_check = script
            .find("test -x device/onpi/build/yoyopod-on-pi")
            .expect("on-pi binary check present");
        let first_stage = script
            .find("validate deploy")
            .expect("deploy stage present");
        assert!(binary_check < first_stage);
        assert!(script.contains("device/voip/build/yoyopod-voip-host"));
        assert!(script.contains("device/network/build/yoyopod-network-host"));
        assert!(script.contains("device/power/build/yoyopod-power-host"));
        assert!(script.contains("device/speech/build/yoyopod-speech-host"));
    }

    #[test]
    fn sha_pins_the_checkout() {
        let mut args = base_args();
        args.sha = "abc123".to_string();
        let script = build_validate_script(
            "main",
            "abc123",
            &args,
            &LanePaths::default(),
            &PiPaths::default(),
        );
        assert!(script.contains("git merge-base --is-ancestor abc123 origin/main"));
        assert!(script.contains("git reset --hard abc123"));
    }

    #[test]
    fn optional_stages_append_after_base() {
        let mut args = base_args();
        args.with_lvgl_soak = true;
        args.with_navigation = true;
        let script = build_validate_script(
            "main",
            "abc123",
            &args,
            &LanePaths::default(),
            &PiPaths::default(),
        );
        let stability = script.find("validate stability").unwrap();
        let lvgl = script.find("validate lvgl").unwrap();
        let navigation = script.find("validate navigation").unwrap();
        assert!(stability < lvgl);
        assert!(lvgl < navigation);
    }

    #[test]
    fn validation_isolates_hardware_and_restores_active_dev_service() {
        let script = build_validate_script(
            "main",
            "abc123",
            &base_args(),
            &LanePaths::default(),
            &PiPaths::default(),
        );
        assert!(script.contains("prod lane owns the hardware"));
        assert!(script.contains("sudo systemctl stop yoyopod-dev.service"));
        assert!(script.contains("trap restore_validation_service EXIT"));
        assert!(script.contains("sudo systemctl start yoyopod-dev.service"));
        assert!(script.contains("device/runtime/build/ARTIFACT_SHA"));
        assert!(script.contains("YOYOPOD_EXPECTED_ARTIFACT_SHA=abc123"));
    }
}
