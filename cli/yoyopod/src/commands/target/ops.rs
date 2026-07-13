//! `target {status, restart}` — runtime ops on the Pi via SSH.

use anyhow::Result;

use crate::deploy_config::{resolve_lane, RawConfig};
use crate::paths::{LanePaths, PiPaths};
use crate::quoting::shell_quote;
use crate::ssh::{run_remote, RemoteWorkdir};

use super::{maybe_dry_run, TargetContext};

pub fn status(ctx: &TargetContext) -> Result<i32> {
    let cmd = build_status(&ctx.pi);
    if let Some(code) = maybe_dry_run(ctx, "status", &cmd) {
        return Ok(code);
    }
    run_remote(&ctx.conn, &cmd, false, RemoteWorkdir::Default)
}

pub fn restart(ctx: &TargetContext, base: &RawConfig, local: &RawConfig) -> Result<i32> {
    let lane = resolve_lane(base, local);
    let cmd = build_restart(&ctx.pi, &lane);
    if let Some(code) = maybe_dry_run(ctx, "restart", &cmd) {
        return Ok(code);
    }
    run_remote(&ctx.conn, &cmd, false, RemoteWorkdir::Default)
}

pub fn build_status(pi: &PiPaths) -> String {
    let log = shell_quote(&pi.log_file);
    let pid = shell_quote(&pi.pid_file);
    format!(
        "echo '=== git ===' && git rev-parse HEAD && \
         echo '=== artifact ===' && \
         (cat device/runtime/build/ARTIFACT_SHA 2>/dev/null || echo 'no artifact SHA marker') && \
         echo '=== pid ===' && (cat {pid} 2>/dev/null || echo 'no pid file') && \
         echo '=== workers ===' && \
         (ps aux | grep -E 'yoyopod-(runtime|[a-z-]+-host)|[m]pv' | grep -v grep || true) && \
         echo '=== log tail ===' && (tail -n 20 {log} 2>/dev/null || echo 'no log file')"
    )
}

pub fn build_startup_verification(pi: &PiPaths, attempts: u32) -> String {
    let pid = shell_quote(&pi.pid_file);
    let log = shell_quote(&pi.log_file);
    let marker = shell_quote(&pi.startup_marker);
    [
        format!("for _ in $(seq 1 {attempts}); do test -f {pid} && break; sleep 1; done"),
        format!("test -f {pid}"),
        format!("pid=\"$(tr -d '\\n' < {pid})\""),
        "test -n \"$pid\"".to_string(),
        "test -d \"/proc/$pid\"".to_string(),
        format!(
            "for _ in $(seq 1 {attempts}); do \
             if test -f {log} && grep -F {marker} {log} | tail -n 1 | grep -F \"pid=$pid\" >/dev/null; \
             then break; fi; sleep 1; done"
        ),
        format!("grep -F {marker} {log} | tail -n 1 | grep -F \"pid=$pid\""),
    ]
    .join(" && ")
}

pub fn build_stale_runtime_cleanup() -> String {
    // The dev service runs as root: an unprivileged pkill matches its
    // strays but cannot signal them, which stranded a second runtime
    // alongside the fresh service (observed 2026-07-13: two UI hosts
    // interleaving frames on the panel). A dead runtime also leaves its
    // worker hosts reparented to init — sweep the whole family, sudo
    // first, unprivileged fallback where sudo is absent.
    r"sudo pkill -f '[y]oyopod-(runtime|[a-z-]+-host)' 2>/dev/null || pkill -f '[y]oyopod-(runtime|[a-z-]+-host)' || true".to_string()
}

pub fn build_restart(pi: &PiPaths, lane: &LanePaths) -> String {
    let pid = shell_quote(&pi.pid_file);
    let dev_service = shell_quote(&lane.dev_service);
    let selected_checkout_guard = "selected_checkout=\"$(pwd -P)\"; \
        dev_service_checkout=\"$(set -a; \
        [ -f /etc/default/yoyopod-dev ] && . /etc/default/yoyopod-dev; \
        printf \"%s\" \"${YOYOPOD_DEV_CHECKOUT:-/opt/yoyopod-dev/checkout}\")\"; \
        dev_service_checkout=\"$(cd \"$dev_service_checkout\" 2>/dev/null && \
        pwd -P || printf \"%s\" \"$dev_service_checkout\")\"";
    let cleanup = format!(
        "rm -f {pid} || sudo rm -f {pid} ; {}",
        build_stale_runtime_cleanup()
    );
    let managed_restart = format!(
        "{selected_checkout_guard}; \
         if ! systemctl cat {dev_service} >/dev/null 2>&1; then \
         echo 'target restart: dev lane service is not installed; run board bootstrap first' \
         >&2; exit 2; \
         fi; \
         if [ \"$selected_checkout\" != \"$dev_service_checkout\" ]; then \
         echo \"target restart: selected checkout $selected_checkout does not match \
         dev lane checkout $dev_service_checkout\" >&2; exit 2; \
         fi; \
         sudo systemctl stop {dev_service} >/dev/null 2>&1 || true; \
         {cleanup} ; \
         sudo systemctl reset-failed {dev_service} >/dev/null 2>&1 || true; \
         sudo systemctl start {dev_service} || exit $?"
    );
    [managed_restart, build_startup_verification(pi, 20)].join(" && ")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn stale_cleanup_escalates_to_sudo_and_sweeps_workers() {
        let cleanup = build_stale_runtime_cleanup();
        assert!(cleanup.starts_with("sudo pkill"));
        assert!(cleanup.contains("|| pkill"));
        assert!(cleanup.contains("[a-z-]+-host"));
        assert!(cleanup.ends_with("|| true"));
    }

    #[test]
    fn restart_includes_the_stale_sweep() {
        let restart = build_restart(&PiPaths::default(), &LanePaths::default());
        assert!(restart.contains("sudo pkill -f '[y]oyopod-(runtime|[a-z-]+-host)'"));
        assert!(restart.contains("sudo systemctl stop yoyopod-dev.service"));
    }

    #[test]
    fn status_reports_artifact_and_every_worker_host() {
        let status = build_status(&PiPaths::default());
        assert!(status.contains("device/runtime/build/ARTIFACT_SHA"));
        assert!(status.contains("[a-z-]+-host"));
    }
}
