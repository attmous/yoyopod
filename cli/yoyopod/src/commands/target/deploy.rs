//! `yoyopod target deploy` — push, fetch CI artifact, sync Pi, install,
//! restart, verify. The flagship Round 1 command.
//!
//! This replaces the multi-step manual workflow that
//! `skills/yoyopod-rust-artifact/SKILL.md` used to document. The skill
//! doc is being rewritten in a later round.

use std::path::Path;
use std::process::Command;
use std::thread;
use std::time::{Duration, Instant};

use anyhow::{anyhow, Context, Result};

use crate::cli::DeployArgs;
use crate::deploy_config::{resolve_lane, RawConfig};
use crate::local::{run_local, run_local_capture};
use crate::quoting::shell_quote;
use crate::repo::current_repo_root;
use crate::ssh::{run_remote, run_remote_capture, RemoteWorkdir};

use super::ops;
use super::TargetContext;

const CI_POLL_INTERVAL_SECS: u64 = 20;
const CI_POLL_TIMEOUT_MINS: u64 = 30;
const WIFI_POLKIT_RULE_PATH: &str = "/etc/polkit-1/rules.d/90-yoyopod-wifi.rules";

pub fn run(
    ctx: &TargetContext,
    base: &RawConfig,
    local: &RawConfig,
    args: DeployArgs,
) -> Result<i32> {
    let lane = resolve_lane(base, local);
    let branch = ctx.conn.branch.clone();

    // 1) Local committed-code check + ensure HEAD is pushed.
    require_local_clean_tree()?;
    let resolved_sha = if args.sha.is_empty() {
        capture_head_sha()?
    } else {
        args.sha.clone()
    };
    require_branch_pushed(&branch)?;
    if args.sha.is_empty() {
        require_local_not_ahead(&branch)?;
    } else {
        require_sha_reachable(&branch, &resolved_sha)?;
    }

    // 2) Resolve CI run and fetch artifact tarball locally.
    let repo_root = current_repo_root()?;
    let artifact_name = format!("yoyopod-rust-device-arm64-{resolved_sha}");
    let tarball_name = format!("{artifact_name}.tar.gz");
    let local_artifact_dir = repo_root
        .join(".artifacts")
        .join("rust-device")
        .join(&resolved_sha);

    if ctx.dry_run {
        println!("[dry-run target=deploy]");
        println!("branch: {branch}");
        println!("sha: {resolved_sha}");
        println!("artifact: {artifact_name}");
        println!("local-artifact-dir: {}", local_artifact_dir.display());
        println!("would: ensure CI run for sha is successful, download {tarball_name}");
        let service_user = if ctx.conn.user.is_empty() {
            "the SSH-configured remote login user"
        } else {
            ctx.conn.user.as_str()
        };
        println!("would: install a Wi-Fi-only Polkit rule for service user {service_user}");
        println!(
            "would: ssh sync + extract + restart + verify on {}",
            ctx.conn.ssh_target()
        );
        return Ok(0);
    }

    let run_id = ensure_successful_ci_run(&branch, &resolved_sha, args.wait_for_ci)?;

    std::fs::create_dir_all(&local_artifact_dir)
        .with_context(|| format!("create {}", local_artifact_dir.display()))?;
    if local_artifact_dir.join(&tarball_name).exists() {
        eprintln!(
            "using existing local artifact: {}",
            local_artifact_dir.join(&tarball_name).display()
        );
    } else {
        download_artifact(&run_id, &artifact_name, &local_artifact_dir)?;
    }
    let local_tarball = local_artifact_dir.join(&tarball_name);
    if !local_tarball.exists() {
        return Err(anyhow!(
            "expected artifact tarball not present after download: {}",
            local_tarball.display()
        ));
    }
    let polkit_rule_name = format!("yoyopod-wifi-{resolved_sha}.rules");
    let local_polkit_rule = local_artifact_dir.join(&polkit_rule_name);
    let wifi_service_user = resolve_wifi_service_user(ctx)?;
    std::fs::write(
        &local_polkit_rule,
        render_wifi_polkit_rule(&wifi_service_user)?,
    )
    .with_context(|| format!("write {}", local_polkit_rule.display()))?;

    // 3) Pi-side: git fetch + checkout + reset to SHA + clean.
    let pi_cmd = build_pi_sync(&branch, &resolved_sha, args.clean_native);
    let rc = run_remote(&ctx.conn, &pi_cmd, true, RemoteWorkdir::Default)?;
    if rc != 0 {
        return Ok(rc);
    }

    // 4) scp tarball to /tmp on the Pi.
    let remote_tarball = format!("/tmp/{tarball_name}");
    let scp_status = Command::new("scp")
        .arg(&local_tarball)
        .arg(format!("{}:{}", ctx.conn.ssh_target(), remote_tarball))
        .status()
        .context("spawn scp for artifact upload")?;
    if !scp_status.success() {
        return Ok(scp_status.code().unwrap_or(1));
    }

    // Install a generated rule for the configured service user. It grants only
    // the NetworkManager actions required by Phase 1 Wi-Fi controls.
    let remote_polkit_rule = format!("/tmp/{polkit_rule_name}");
    let scp_status = Command::new("scp")
        .arg(&local_polkit_rule)
        .arg(format!("{}:{}", ctx.conn.ssh_target(), remote_polkit_rule))
        .status()
        .context("spawn scp for Wi-Fi Polkit rule upload")?;
    if !scp_status.success() {
        return Ok(scp_status.code().unwrap_or(1));
    }
    let install_polkit_cmd = format!(
        "sudo -n install -o root -g root -m 0644 {source} {destination} && rm -f {source}",
        source = shell_quote(&remote_polkit_rule),
        destination = shell_quote(WIFI_POLKIT_RULE_PATH),
    );
    let rc = run_remote(
        &ctx.conn,
        &install_polkit_cmd,
        false,
        RemoteWorkdir::Default,
    )?;
    if rc != 0 {
        return Ok(rc);
    }

    // 5) Extract + chmod on Pi.
    let extract_cmd = format!(
        "tar -xzf {tarball} && \
         chmod +x device/runtime/build/yoyopod-runtime device/ui/build/yoyopod-ui-host \
         device/media/build/yoyopod-media-host device/voip/build/yoyopod-voip-host \
         device/network/build/yoyopod-network-host device/cloud/build/yoyopod-cloud-host \
         device/power/build/yoyopod-power-host device/speech/build/yoyopod-speech-host \
         && {{ [ ! -f device/onpi/build/yoyopod-on-pi ] || chmod +x device/onpi/build/yoyopod-on-pi; }} \
         && rm -f {tarball}",
        tarball = shell_quote(&remote_tarball)
    );
    let rc = run_remote(&ctx.conn, &extract_cmd, false, RemoteWorkdir::Default)?;
    if rc != 0 {
        return Ok(rc);
    }

    // 6) Restart + verify startup.
    let restart_cmd = ops::build_restart(&ctx.pi, &lane);
    let rc = run_remote(&ctx.conn, &restart_cmd, false, RemoteWorkdir::Default)?;
    if rc != 0 {
        return Ok(rc);
    }

    println!(
        "deployed sha={resolved_sha} run={run_id} artifact={artifact_name} host={}",
        ctx.conn.ssh_target()
    );
    Ok(0)
}

fn validate_wifi_service_user(service_user: &str) -> Result<&str> {
    let service_user = service_user.trim();
    if service_user.is_empty()
        || !service_user
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || byte == b'_' || byte == b'-')
    {
        return Err(anyhow!(
            "configured service user contains characters that cannot be rendered safely"
        ));
    }
    Ok(service_user)
}

fn resolve_wifi_service_user(ctx: &TargetContext) -> Result<String> {
    if !ctx.conn.user.trim().is_empty() {
        return Ok(validate_wifi_service_user(&ctx.conn.user)?.to_string());
    }

    let output = run_remote_capture(&ctx.conn, "id -un", RemoteWorkdir::None)
        .context("resolve remote service user for Wi-Fi Polkit rule")?;
    if !output.success() {
        return Err(anyhow!(
            "could not resolve remote service user for Wi-Fi Polkit rule: {}",
            output.stderr.trim()
        ));
    }
    Ok(validate_wifi_service_user(&output.stdout)?.to_string())
}

fn render_wifi_polkit_rule(service_user: &str) -> Result<String> {
    let service_user = validate_wifi_service_user(service_user)?;
    Ok(format!(
        r#"// Generated by `yoyopod target deploy`; changes are replaced on deploy.
polkit.addRule(function(action, subject) {{
    if (subject.user === "{service_user}" &&
        (action.id === "org.freedesktop.NetworkManager.wifi.scan" ||
         action.id === "org.freedesktop.NetworkManager.settings.modify.system" ||
         action.id === "org.freedesktop.NetworkManager.network-control" ||
         action.id === "org.freedesktop.NetworkManager.checkpoint-rollback")) {{
        return polkit.Result.YES;
    }}
}});
"#
    ))
}

pub(super) fn require_local_clean_tree() -> Result<()> {
    require_git(
        &["git", "diff", "--quiet"],
        "Local worktree has uncommitted changes. Commit or stash them before `yoyopod target deploy`.",
    )?;
    require_git(
        &["git", "diff", "--cached", "--quiet"],
        "Local index has staged but uncommitted changes. Commit them before `yoyopod target deploy`.",
    )
}

fn capture_head_sha() -> Result<String> {
    let out = run_local_capture(["git", "rev-parse", "HEAD"])?;
    if !out.status.success() {
        return Err(anyhow!("git rev-parse HEAD failed: {}", out.stderr));
    }
    Ok(out.stdout.trim().to_string())
}

pub(super) fn require_branch_pushed(branch: &str) -> Result<()> {
    require_git(
        &["git", "fetch", "--quiet", "origin", branch],
        &format!("Failed to fetch `origin/{branch}` before deploy."),
    )?;
    let ref_arg = format!("origin/{branch}^{{commit}}");
    require_git(
        &["git", "rev-parse", "--verify", &ref_arg],
        &format!(
            "Branch `{branch}` is not available on origin. Push it before `yoyopod target deploy`."
        ),
    )
}

pub(super) fn require_local_not_ahead(branch: &str) -> Result<()> {
    // If a local branch with the same name exists, ensure it's not ahead of origin.
    let local_ref = format!("refs/heads/{branch}");
    let check = run_local_capture(["git", "show-ref", "--verify", "--quiet", local_ref.as_str()])?;
    if !check.status.success() {
        return Ok(());
    }
    let range = format!("origin/{branch}..{branch}");
    let ahead = run_local_capture(["git", "rev-list", "--count", range.as_str()])?;
    if !ahead.status.success() {
        return Err(anyhow!(
            "Failed to compare local `{branch}` against `origin/{branch}`: {}",
            ahead.stderr
        ));
    }
    if ahead.stdout.trim() != "0" {
        return Err(anyhow!(
            "Local branch `{branch}` has unpushed commits. Push it or pass --sha for a pushed commit."
        ));
    }
    Ok(())
}

pub(super) fn require_sha_reachable(branch: &str, sha: &str) -> Result<()> {
    let origin_branch = format!("origin/{branch}");
    require_git(
        &[
            "git",
            "merge-base",
            "--is-ancestor",
            sha,
            origin_branch.as_str(),
        ],
        &format!(
            "Commit `{sha}` is not reachable from `origin/{branch}`. Push it or choose a pushed SHA."
        ),
    )
}

fn require_git(argv: &[&str], err_msg: &str) -> Result<()> {
    let out = run_local_capture(argv.iter().copied())?;
    if out.status.success() {
        return Ok(());
    }
    let mut message = String::from(err_msg);
    if !out.stderr.trim().is_empty() {
        message.push_str("\n");
        message.push_str(out.stderr.trim());
    }
    Err(anyhow!(message))
}

fn ensure_successful_ci_run(branch: &str, sha: &str, wait: bool) -> Result<String> {
    let deadline = Instant::now() + Duration::from_secs(CI_POLL_TIMEOUT_MINS * 60);
    loop {
        let out = run_local_capture([
            "gh",
            "run",
            "list",
            "--workflow",
            "CI",
            "--branch",
            branch,
            "--json",
            "databaseId,headSha,status,conclusion",
            "--limit",
            "20",
        ])?;
        if !out.status.success() {
            return Err(anyhow!(
                "gh run list failed: {}\n(install/auth gh: https://cli.github.com/)",
                out.stderr.trim()
            ));
        }
        let runs: Vec<GhRun> = serde_json::from_str(&out.stdout)
            .or_else(|_| serde_yaml::from_str(&out.stdout))
            .context("parse gh run list output")?;
        let matching: Vec<&GhRun> = runs.iter().filter(|r| r.head_sha == sha).collect();
        if matching.is_empty() {
            if wait && Instant::now() < deadline {
                eprintln!(
                    "no CI run for sha {sha} on branch {branch} yet; polling again in {CI_POLL_INTERVAL_SECS}s"
                );
                thread::sleep(Duration::from_secs(CI_POLL_INTERVAL_SECS));
                continue;
            }
            return Err(anyhow!(
                "no CI run found for sha {sha} on branch {branch}. Push and wait, or use --wait-for-ci."
            ));
        }
        for r in &matching {
            if r.conclusion.as_deref() == Some("success") {
                return Ok(r.database_id.to_string());
            }
        }
        let any_in_progress = matching
            .iter()
            .any(|r| r.status == "in_progress" || r.status == "queued" || r.status == "pending");
        if any_in_progress && wait && Instant::now() < deadline {
            eprintln!(
                "CI run for sha {sha} is still {} ; polling again in {CI_POLL_INTERVAL_SECS}s",
                matching[0].status
            );
            thread::sleep(Duration::from_secs(CI_POLL_INTERVAL_SECS));
            continue;
        }
        let mut concluded: Vec<String> = matching
            .iter()
            .filter_map(|r| r.conclusion.clone())
            .collect();
        concluded.sort();
        concluded.dedup();
        return Err(anyhow!(
            "no successful CI run for sha {sha} on branch {branch} (statuses: {:?})",
            concluded
        ));
    }
}

fn download_artifact(run_id: &str, artifact_name: &str, dest: &Path) -> Result<()> {
    let dest_str = dest.to_string_lossy().to_string();
    let rc = run_local(
        [
            "gh",
            "run",
            "download",
            run_id,
            "--name",
            artifact_name,
            "--dir",
            &dest_str,
        ],
        "gh run download artifact",
    )?;
    if rc != 0 {
        return Err(anyhow!(
            "gh run download failed (run-id={run_id}, artifact={artifact_name})"
        ));
    }
    Ok(())
}

pub(super) fn build_pi_sync(branch: &str, sha: &str, clean_native: bool) -> String {
    let br = shell_quote(branch);
    let origin_br = shell_quote(&format!("origin/{branch}"));
    let mut steps = vec![
        "git fetch --prune origin".to_string(),
        "git clean -fd".to_string(),
        format!("git checkout --force -B {br} {origin_br}"),
    ];
    if !sha.is_empty() {
        let sh = shell_quote(sha);
        steps.push(format!("git merge-base --is-ancestor {sh} {origin_br}"));
        steps.push(format!("git reset --hard {sh}"));
    } else {
        steps.push(format!("git reset --hard {origin_br}"));
    }
    steps.push("git clean -fd".to_string());
    if clean_native {
        steps.push("rm -rf device/ui/native/lvgl/build || true".to_string());
    }
    steps.join(" && ")
}

#[derive(Debug, serde::Deserialize)]
struct GhRun {
    #[serde(rename = "databaseId")]
    database_id: u64,
    #[serde(rename = "headSha")]
    head_sha: String,
    status: String,
    #[serde(default)]
    conclusion: Option<String>,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn pi_sync_includes_branch() {
        // Path-like values ("feature/x", "origin/feature/x") contain only
        // whitelist characters and are left unquoted by shell-escape.
        let s = build_pi_sync("feature/x", "", false);
        assert!(s.contains("git fetch --prune origin"));
        assert!(s.contains("git checkout --force -B feature/x origin/feature/x"));
        assert!(s.contains("git reset --hard origin/feature/x"));
    }

    #[test]
    fn pi_sync_with_sha_uses_ancestor_then_reset() {
        let s = build_pi_sync("main", "abc123", false);
        assert!(s.contains("git merge-base --is-ancestor abc123 origin/main"));
        assert!(s.contains("git reset --hard abc123"));
    }

    #[test]
    fn pi_sync_branch_with_spaces_is_quoted() {
        let s = build_pi_sync("ux: hub redesign", "", false);
        // a branch with space chars goes through the quoting path
        assert!(s.contains("git checkout --force -B 'ux: hub redesign' 'origin/ux: hub redesign'"));
    }

    #[test]
    fn clean_native_appends_lvgl_rm() {
        let s = build_pi_sync("main", "", true);
        assert!(s.contains("rm -rf device/ui/native/lvgl/build"));
    }

    #[test]
    fn wifi_polkit_rule_grants_only_required_actions_to_service_user() {
        let rule = render_wifi_polkit_rule("raouf").expect("valid service user");

        assert!(rule.contains("subject.user === \"raouf\""));
        assert!(rule.contains("org.freedesktop.NetworkManager.wifi.scan"));
        assert!(rule.contains("org.freedesktop.NetworkManager.settings.modify.system"));
        assert!(rule.contains("org.freedesktop.NetworkManager.network-control"));
        assert!(rule.contains("org.freedesktop.NetworkManager.checkpoint-rollback"));
        assert_eq!(rule.matches("action.id ===").count(), 4);
    }

    #[test]
    fn wifi_polkit_rule_rejects_unsafe_service_user() {
        assert!(render_wifi_polkit_rule("raouf\" || true").is_err());
    }

    #[test]
    fn wifi_polkit_rule_normalizes_safe_service_user() {
        let rule = render_wifi_polkit_rule("  raouf  ").expect("valid service user");
        assert!(rule.contains("subject.user === \"raouf\""));
    }
}
