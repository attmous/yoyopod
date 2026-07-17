//! `yoyopod target ...` — dev-machine to Pi commands.
//!
//! Each subcommand resolves a `RemoteConnection` from CLI flags + env vars +
//! `deploy/pi-deploy{,.local}.yaml`, then builds an SSH command. The
//! global `--dry-run` flag causes commands to print the SSH command
//! string they would have run, without executing.

use anyhow::Result;

use crate::cli::{TargetArgs, TargetCommand};
use crate::deploy_config::{load_layered, resolve_connection, resolve_pi_paths, RemoteConnection};
use crate::paths::PiPaths;
use crate::repo::current_repo_root;
use crate::ssh::validate_connection;

mod config;
mod deploy;
mod logs;
mod mode;
mod ops;
mod screenshot;
mod validate;

/// Resolved bundle each subcommand needs.
pub struct TargetContext {
    pub conn: RemoteConnection,
    pub pi: PiPaths,
    pub dry_run: bool,
}

pub fn dispatch(args: TargetArgs, dry_run: bool) -> Result<i32> {
    // For `target config edit` we don't need a connection — it's purely
    // a local file operation. Handle it before touching the deploy YAML.
    if let TargetCommand::Config(cmd) = &args.command {
        return config::run(cmd);
    }

    let repo_root = current_repo_root()?;
    let (base, local) = load_layered(&repo_root)?;
    let pi = resolve_pi_paths(&base, &local);
    let conn = resolve_connection(
        args.host.as_deref(),
        args.user.as_deref(),
        args.project_dir.as_deref(),
        args.branch.as_deref(),
        &base,
        &local,
        &pi,
    );

    let ctx = TargetContext { conn, pi, dry_run };

    match args.command {
        TargetCommand::Config(_) => unreachable!("handled above"),
        TargetCommand::Status => {
            validate_connection(&ctx.conn)?;
            ops::status(&ctx)
        }
        TargetCommand::Restart => {
            validate_connection(&ctx.conn)?;
            ops::restart(&ctx, &base, &local)
        }
        TargetCommand::Logs(a) => {
            validate_connection(&ctx.conn)?;
            logs::run(&ctx, a)
        }
        TargetCommand::Screenshot(a) => {
            validate_connection(&ctx.conn)?;
            screenshot::run(&ctx, a)
        }
        TargetCommand::Mode(cmd) => {
            validate_connection(&ctx.conn)?;
            mode::run(&ctx, &base, &local, cmd)
        }
        TargetCommand::Deploy(a) => {
            validate_connection(&ctx.conn)?;
            deploy::run(&ctx, &base, &local, a)
        }
        TargetCommand::Validate(a) => {
            validate_connection(&ctx.conn)?;
            validate::run(&ctx, &base, &local, a)
        }
    }
}

/// Helper used across subcommands to log the SSH command string when
/// --dry-run is in effect, and skip execution.
pub fn maybe_dry_run(ctx: &TargetContext, label: &str, remote_command: &str) -> Option<i32> {
    if ctx.dry_run {
        println!("[dry-run target={label}]");
        println!("ssh-host: {}", ctx.conn.ssh_target());
        println!("ssh-dir:  {}", ctx.conn.project_dir);
        println!("ssh-cmd:  {remote_command}");
        Some(0)
    } else {
        None
    }
}
