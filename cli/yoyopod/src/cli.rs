//! Top-level clap arg tree.

use clap::{Args, Parser, Subcommand};

#[derive(Debug, Parser)]
#[command(
    name = "yoyopod",
    about = "YoYoPod operator CLI: dev-machine to Pi orchestration.",
    version
)]
pub struct Cli {
    /// Verbose logging.
    #[arg(long, global = true)]
    pub verbose: bool,

    /// Print the SSH command that would run, without executing it.
    /// (Applies to target subcommands that build an SSH pipeline.)
    #[arg(long, global = true)]
    pub dry_run: bool,

    #[command(subcommand)]
    pub command: Command,
}

#[derive(Debug, Subcommand)]
pub enum Command {
    /// Dev-machine to Pi commands.
    Target(TargetArgs),
}

#[derive(Debug, Args)]
pub struct TargetArgs {
    /// SSH host or alias.
    #[arg(long, env = "YOYOPOD_PI_HOST", global = true)]
    pub host: Option<String>,

    /// SSH user (optional).
    #[arg(long, env = "YOYOPOD_PI_USER", global = true)]
    pub user: Option<String>,

    /// Project directory on the Pi.
    #[arg(long, env = "YOYOPOD_PI_PROJECT_DIR", global = true)]
    pub project_dir: Option<String>,

    /// Git branch to target.
    #[arg(long, env = "YOYOPOD_PI_BRANCH", global = true)]
    pub branch: Option<String>,

    #[command(subcommand)]
    pub command: TargetCommand,
}

#[derive(Debug, Subcommand)]
pub enum TargetCommand {
    /// Show repo SHA, processes, and log tail on the Pi.
    Status,
    /// Restart the YoYoPod dev runtime service on the Pi.
    Restart,
    /// Tail yoyopod logs on the Pi.
    Logs(LogsArgs),
    /// Capture a screenshot from the Pi's display and copy it locally.
    Screenshot(ScreenshotArgs),
    /// Open deploy/pi-deploy.local.yaml in $EDITOR.
    #[command(subcommand)]
    Config(ConfigCommand),
    /// Show or switch the active lane (dev/prod).
    #[command(subcommand)]
    Mode(ModeCommand),
    /// Push, fetch CI artifact, sync Pi, install binaries, restart and verify.
    Deploy(DeployArgs),
    /// Run staged on-Pi validation (deploy, smoke, stability + optional soaks).
    Validate(ValidateArgs),
}

#[derive(Debug, Args)]
pub struct LogsArgs {
    /// Number of lines to tail.
    #[arg(long, default_value_t = 50)]
    pub lines: u32,

    /// Follow log output.
    #[arg(long, short = 'f')]
    pub follow: bool,

    /// Tail the error log.
    #[arg(long)]
    pub errors: bool,

    /// Grep filter applied to the output.
    #[arg(long, default_value = "")]
    pub filter: String,
}

#[derive(Debug, Args)]
pub struct ScreenshotArgs {
    /// Local file path. Default: logs/screenshots/<timestamp>.png
    #[arg(long, default_value = "")]
    pub out: String,

    /// Use LVGL readback (SIGUSR1) instead of shadow buffer (SIGUSR2).
    #[arg(long)]
    pub readback: bool,
}

#[derive(Debug, Subcommand)]
pub enum ConfigCommand {
    /// Open deploy/pi-deploy.local.yaml in $EDITOR.
    Edit,
}

#[derive(Debug, Subcommand)]
pub enum ModeCommand {
    /// Show active lane and conflicts.
    Status,
    /// Activate dev or prod lane.
    Activate(ModeActivateArgs),
}

#[derive(Debug, Args)]
pub struct ModeActivateArgs {
    /// Lane to activate.
    #[arg(value_parser = ["dev", "prod"])]
    pub lane: String,
}

#[derive(Debug, Args)]
pub struct DeployArgs {
    /// Pin deploy to a specific commit on the target branch (must be reachable from origin/<branch>).
    #[arg(long, default_value = "")]
    pub sha: String,

    /// Remove dev lane native build dirs before rebuilding.
    #[arg(long)]
    pub clean_native: bool,

    /// If the CI run for this commit is queued or in-progress, wait until it
    /// finishes (timeout: 30 minutes).
    #[arg(long)]
    pub wait_for_ci: bool,
}

#[derive(Debug, Args)]
pub struct ValidateArgs {
    /// Pin validation to a specific commit (must be reachable from origin/<branch>).
    #[arg(long, default_value = "")]
    pub sha: String,

    /// (Not yet ported — Round 2 follow-up.) SIP registration check.
    #[arg(long)]
    pub with_voip: bool,

    /// Add the UI/LVGL navigation soak stage.
    #[arg(long)]
    pub with_lvgl_soak: bool,

    /// Add the full one-button navigation stage.
    #[arg(long)]
    pub with_navigation: bool,

    /// (Returns with Round 4+ diagnostics.) Standalone rust-ui-host probe.
    #[arg(long)]
    pub with_rust_ui_host: bool,
}
