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
use crate::quoting::shell_quote;
use crate::ssh::{run_remote, RemoteWorkdir};

use super::deploy::{
    build_pi_sync, require_branch_pushed, require_local_clean_tree, require_local_not_ahead,
    require_sha_reachable,
};
use super::{maybe_dry_run, TargetContext};

const ON_PI_BINARY: &str = "device/onpi/build/yoyopod-on-pi";

/// Binaries the base stages exercise; checked before any stage runs so a
/// half-deployed checkout fails loudly instead of mid-validation.
const REQUIRED_BINARIES: [&str; 5] = [
    "device/runtime/build/yoyopod-runtime",
    "device/ui/build/yoyopod-ui-host",
    "device/cloud/build/yoyopod-cloud-host",
    "device/media/build/yoyopod-media-host",
    ON_PI_BINARY,
];

pub fn run(ctx: &TargetContext, args: ValidateArgs) -> Result<i32> {
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

    let remote_cmd = build_validate_script(&branch, &args);
    if let Some(rc) = maybe_dry_run(ctx, "validate", &remote_cmd) {
        return Ok(rc);
    }
    run_remote(&ctx.conn, &remote_cmd, true, RemoteWorkdir::Default)
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

fn build_validate_script(branch: &str, args: &ValidateArgs) -> String {
    // Same checkout sync the old remote validate performed.
    let mut steps = vec![build_pi_sync(branch, &args.sha, false)];
    for binary in REQUIRED_BINARIES {
        steps.push(require_executable(binary));
    }
    steps.push(format!("{ON_PI_BINARY} validate deploy"));
    steps.push(format!("{ON_PI_BINARY} validate smoke"));
    steps.push(format!("{ON_PI_BINARY} validate stability"));
    if args.with_lvgl_soak {
        steps.push(format!("{ON_PI_BINARY} validate lvgl"));
    }
    if args.with_navigation {
        steps.push(format!("{ON_PI_BINARY} validate navigation"));
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
        let script = build_validate_script("main", &base_args());
        assert!(script.contains("git checkout --force -B main origin/main"));
        assert!(script.contains("device/onpi/build/yoyopod-on-pi validate deploy"));
        assert!(script.contains("device/onpi/build/yoyopod-on-pi validate smoke"));
        assert!(script.contains("device/onpi/build/yoyopod-on-pi validate stability"));
        assert!(!script.contains("validate lvgl"));
        assert!(!script.contains("validate navigation"));
    }

    #[test]
    fn script_checks_binaries_before_stages() {
        let script = build_validate_script("main", &base_args());
        let binary_check = script
            .find("test -x device/onpi/build/yoyopod-on-pi")
            .expect("on-pi binary check present");
        let first_stage = script
            .find("validate deploy")
            .expect("deploy stage present");
        assert!(binary_check < first_stage);
    }

    #[test]
    fn sha_pins_the_checkout() {
        let mut args = base_args();
        args.sha = "abc123".to_string();
        let script = build_validate_script("main", &args);
        assert!(script.contains("git merge-base --is-ancestor abc123 origin/main"));
        assert!(script.contains("git reset --hard abc123"));
    }

    #[test]
    fn optional_stages_append_after_base() {
        let mut args = base_args();
        args.with_lvgl_soak = true;
        args.with_navigation = true;
        let script = build_validate_script("main", &args);
        let stability = script.find("validate stability").unwrap();
        let lvgl = script.find("validate lvgl").unwrap();
        let navigation = script.find("validate navigation").unwrap();
        assert!(stability < lvgl);
        assert!(lvgl < navigation);
    }
}
