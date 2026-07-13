//! `yoyopod target mode {status, activate}`
//!
//! Round 1 implementation: status prints the active service and any
//! conflicting services; activate stops the inactive lane and starts the
//! requested one. This is a simplified port of remote_mode.py that
//! covers the common-case workflow. Edge cases (OTA timers, prod
//! rollback service interleave) come back in later rounds.

use anyhow::Result;

use crate::cli::{ModeActivateArgs, ModeCommand};
use crate::deploy_config::{resolve_lane, RawConfig};
use crate::paths::LanePaths;
use crate::quoting::shell_quote;
use crate::ssh::{run_remote, RemoteWorkdir};

use super::{maybe_dry_run, TargetContext};

pub fn run(
    ctx: &TargetContext,
    base: &RawConfig,
    local: &RawConfig,
    cmd: ModeCommand,
) -> Result<i32> {
    let lane = resolve_lane(base, local);
    match cmd {
        ModeCommand::Status => status(ctx, &lane),
        ModeCommand::Activate(args) => activate(ctx, &lane, args),
    }
}

fn status(ctx: &TargetContext, lane: &LanePaths) -> Result<i32> {
    let cmd = build_status(lane);
    if let Some(code) = maybe_dry_run(ctx, "mode-status", &cmd) {
        return Ok(code);
    }
    run_remote(&ctx.conn, &cmd, false, RemoteWorkdir::None)
}

fn activate(ctx: &TargetContext, lane: &LanePaths, args: ModeActivateArgs) -> Result<i32> {
    let cmd = build_activate(lane, &args.lane);
    if let Some(code) = maybe_dry_run(ctx, "mode-activate", &cmd) {
        return Ok(code);
    }
    run_remote(&ctx.conn, &cmd, false, RemoteWorkdir::None)
}

pub fn build_status(lane: &LanePaths) -> String {
    let dev = shell_quote(&lane.dev_service);
    let prod = shell_quote(&lane.prod_service);
    let legacy = shell_quote(&lane.legacy_slot_service);
    [
        "echo '=== active lane ===' ".to_string(),
        format!(
            "dev_state=\"$(systemctl is-active {dev} 2>/dev/null || true)\"; \
             prod_state=\"$(systemctl is-active {prod} 2>/dev/null || true)\"; \
             echo \"dev: ${{dev_state:-unknown}}\"; \
             echo \"prod: ${{prod_state:-unknown}}\""
        ),
        "echo '=== legacy/conflict services ===' ".to_string(),
        format!(
            "for unit in {legacy} ; do \
             state=\"$(systemctl is-active \"$unit\" 2>/dev/null || true)\"; \
             echo \"$unit: ${{state:-unknown}}\"; \
             done"
        ),
        "echo '=== runtime processes ===' ".to_string(),
        "ps aux | grep -E 'yoyopod-(runtime|[a-z-]+-host)' | grep -v grep || true".to_string(),
    ]
    .join(" && ")
}

pub fn build_activate(lane: &LanePaths, which: &str) -> String {
    let dev = shell_quote(&lane.dev_service);
    let prod = shell_quote(&lane.prod_service);
    let (start, stop) = if which == "dev" {
        (dev.clone(), prod.clone())
    } else {
        (prod.clone(), dev.clone())
    };
    [
        format!("sudo systemctl stop {stop} >/dev/null 2>&1 || true"),
        format!("sudo systemctl reset-failed {start} >/dev/null 2>&1 || true"),
        format!("sudo systemctl start {start}"),
        format!("sudo systemctl is-active {start}"),
        format!("echo \"activated {start}; stopped {stop}\""),
    ]
    .join(" && ")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn status_mentions_both_lanes() {
        let lane = LanePaths::default();
        let s = build_status(&lane);
        assert!(s.contains("yoyopod-dev.service"));
        assert!(s.contains("yoyopod-prod.service"));
        assert!(!s.contains("|| echo unknown"));
        assert!(s.contains("[a-z-]+-host"));
    }

    #[test]
    fn activate_dev_stops_prod() {
        let lane = LanePaths::default();
        let s = build_activate(&lane, "dev");
        // unit names are shell-safe identifiers; shell-escape leaves them unquoted
        assert!(s.contains("sudo systemctl stop yoyopod-prod.service"));
        assert!(s.contains("sudo systemctl start yoyopod-dev.service"));
    }

    #[test]
    fn activate_prod_stops_dev() {
        let lane = LanePaths::default();
        let s = build_activate(&lane, "prod");
        assert!(s.contains("sudo systemctl stop yoyopod-dev.service"));
        assert!(s.contains("sudo systemctl start yoyopod-prod.service"));
    }
}
