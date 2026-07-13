//! `yoyopod target screenshot`

use std::path::PathBuf;
use std::process::Command;

use anyhow::{Context, Result};
use chrono::Local;

use crate::cli::ScreenshotArgs;
use crate::paths::PiPaths;
use crate::quoting::shell_quote;
use crate::repo::current_repo_root;
use crate::ssh::{run_remote_capture, RemoteWorkdir};

use super::TargetContext;

pub fn run(ctx: &TargetContext, args: ScreenshotArgs) -> Result<i32> {
    if ctx.dry_run {
        println!(
            "[dry-run target=screenshot]\nssh-host: {}\nout: {}\nreadback: {}",
            ctx.conn.ssh_target(),
            if args.out.is_empty() {
                "logs/screenshots/<timestamp>.png"
            } else {
                args.out.as_str()
            },
            args.readback
        );
        return Ok(0);
    }

    // 1) Confirm the runtime is alive and has installed signal handlers.
    let ready_cmd = build_ready_check(&ctx.pi, 30);
    let ready = run_remote_capture(&ctx.conn, &ready_cmd, RemoteWorkdir::None)?;
    if !ready.success() || ready.stdout.trim() != "READY" {
        eprintln!(
            "remote app not ready for screenshot capture; \
             wait for startup or restart before requesting one"
        );
        if !ready.stderr.trim().is_empty() {
            eprintln!("{}", ready.stderr.trim());
        }
        return Ok(1);
    }

    // 2) Clear stale screenshot file.
    let clear_cmd = build_clear(&ctx.pi);
    let clear = run_remote_capture(&ctx.conn, &clear_cmd, RemoteWorkdir::None)?;
    if !clear.success() {
        eprintln!("failed to clear previous screenshot on the Pi");
        if !clear.stderr.trim().is_empty() {
            eprintln!("{}", clear.stderr.trim());
        }
        return Ok(clear.status.code().unwrap_or(1));
    }

    // 3) Signal the runtime to capture.
    let signal_cmd = build_signal(&ctx.pi, args.readback);
    let sig = run_remote_capture(&ctx.conn, &signal_cmd, RemoteWorkdir::None)?;
    if !sig.success() {
        eprintln!("failed to trigger screenshot capture on the Pi");
        if !sig.stderr.trim().is_empty() {
            eprintln!("{}", sig.stderr.trim());
        }
        return Ok(sig.status.code().unwrap_or(1));
    }

    // 4) Wait for the PNG to appear.
    let wait_cmd = build_wait(&ctx.pi, 20);
    let wait = run_remote_capture(&ctx.conn, &wait_cmd, RemoteWorkdir::None)?;
    if !wait.success() || wait.stdout.trim() != "READY" {
        eprintln!(
            "screenshot was not created on the Pi within the timeout; \
             confirm the app is running and the signal handlers are installed"
        );
        if !wait.stderr.trim().is_empty() {
            eprintln!("{}", wait.stderr.trim());
        }
        return Ok(1);
    }

    // 5) scp the file back.
    let repo_root = current_repo_root()?;
    let local_target: PathBuf = if args.out.is_empty() {
        let ts = Local::now().format("%Y%m%d-%H%M%S");
        repo_root.join("logs/screenshots").join(format!("{ts}.png"))
    } else {
        PathBuf::from(&args.out)
    };
    if let Some(parent) = local_target.parent() {
        std::fs::create_dir_all(parent)
            .with_context(|| format!("create {}", parent.display()))?;
    }
    let scp_status = Command::new("scp")
        .arg(format!("{}:{}", ctx.conn.ssh_target(), ctx.pi.screenshot_path))
        .arg(&local_target)
        .status()
        .context("spawn scp")?;
    if !scp_status.success() {
        return Ok(scp_status.code().unwrap_or(1));
    }
    println!("screenshot saved to {}", local_target.display());
    Ok(0)
}

fn build_ready_check(pi: &PiPaths, attempts: u32) -> String {
    let pid = shell_quote(&pi.pid_file);
    format!(
        "for _ in $(seq 1 {attempts}); do \
         pid_value=\"$(cat {pid} 2>/dev/null || true)\"; \
         if test -n \"$pid_value\" && test -d \"/proc/${{pid_value}}\" && \
         test -r \"/proc/${{pid_value}}/status\"; then \
         sigcgt=\"$(awk '/^SigCgt:/ {{print $2}}' \"/proc/${{pid_value}}/status\")\"; \
         if test -n \"$sigcgt\"; then \
         mask=$((16#$sigcgt)); \
         if (( (mask & 0x200) != 0 && (mask & 0x800) != 0 )); then \
         echo READY; exit 0; \
         fi; \
         fi; \
         fi; \
         sleep 1; \
         done; \
         echo NOT_READY; exit 1"
    )
}

fn build_clear(pi: &PiPaths) -> String {
    // The runtime runs as root under systemd, so the previous PNG in sticky
    // /tmp may not be removable by the SSH user; fall back to sudo like
    // build_signal does.
    let path = shell_quote(&pi.screenshot_path);
    format!("rm -f {path} 2>/dev/null || sudo rm -f {path}")
}

fn build_signal(pi: &PiPaths, readback: bool) -> String {
    let sig = if readback { "USR1" } else { "USR2" };
    let pid = shell_quote(&pi.pid_file);
    format!(
        "pid_value=\"$(tr -d '\\n' < {pid})\" && \
         {{ kill -{sig} \"$pid_value\" 2>/dev/null || sudo kill -{sig} \"$pid_value\"; }}"
    )
}

fn build_wait(pi: &PiPaths, attempts: u32) -> String {
    let path = shell_quote(&pi.screenshot_path);
    format!(
        "for _ in $(seq 1 {attempts}); do \
         test -f {path} && echo READY && exit 0; \
         sleep 1; \
         done; \
         echo MISSING"
    )
}
