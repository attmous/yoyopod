//! `yoyopod-on-pi` — on-Pi companion binary for the Rust operator CLI.
//!
//! Cross-compiled by CI into the `yoyopod-rust-device-arm64-<sha>` bundle
//! and executed on the Pi by `yoyopod target validate` over SSH. Round 2
//! of the CLI rebuild starts with the `validate` stages; Round 4+
//! diagnostics (`voip`, `power`, `network`) join this binary later.

use std::path::PathBuf;

use clap::{Args, Parser, Subcommand};

mod checks;
mod proc;
mod report;
mod stages;
mod ui_host;

#[derive(Debug, Parser)]
#[command(
    name = "yoyopod-on-pi",
    about = "YoYoPod on-Pi companion: staged hardware validation.",
    version
)]
struct Cli {
    #[command(subcommand)]
    command: Command,
}

#[derive(Debug, Subcommand)]
enum Command {
    /// Staged validation of the deployed checkout on this device.
    #[command(subcommand)]
    Validate(ValidateStage),
}

#[derive(Debug, Subcommand)]
enum ValidateStage {
    /// Environment + runtime dry-run + one UI snapshot render.
    Smoke(SmokeArgs),
    /// Deploy-readiness: config files, worker binaries, units, paths.
    Deploy(DeployArgs),
    /// Repeated navigation + idle soak through the UI worker protocol.
    Stability(SoakArgs),
    /// One-button navigation across the main screen set.
    Navigation(NavigationArgs),
    /// UI/LVGL navigation soak (same driver as stability).
    Lvgl(SoakArgs),
    /// SIP registration check (not yet ported — exits 2).
    Voip,
    /// Cloud STT/TTS worker check (not yet ported — exits 2).
    CloudVoice,
}

#[derive(Debug, Args)]
struct SmokeArgs {
    /// Configuration directory to use.
    #[arg(long, default_value = "config")]
    config_dir: PathBuf,

    /// UI hardware backend to validate against.
    #[arg(long, default_value = "whisplay", value_parser = ["whisplay", "mock"])]
    hardware: String,

    /// How long to keep the rendered snapshot visible.
    #[arg(long, default_value_t = 0.5)]
    display_hold_seconds: f64,
}

#[derive(Debug, Args)]
struct DeployArgs {
    /// Configuration directory to validate.
    #[arg(long, default_value = "config")]
    config_dir: PathBuf,
}

#[derive(Debug, Args)]
struct SoakArgs {
    /// Configuration directory to use.
    #[arg(long, default_value = "config")]
    config_dir: PathBuf,

    /// How many full transition cycles to run.
    #[arg(long, default_value_t = 2)]
    cycles: u32,

    /// How long to keep each screen active during the soak.
    #[arg(long, default_value_t = 0.2)]
    hold_seconds: f64,

    /// How long to idle after each full navigation cycle.
    #[arg(long, default_value_t = 1.0)]
    idle_seconds: f64,
}

#[derive(Debug, Args)]
struct NavigationArgs {
    /// Configuration directory to use.
    #[arg(long, default_value = "config")]
    config_dir: PathBuf,

    /// How many full navigation cycles to run.
    #[arg(long, default_value_t = 2)]
    cycles: u32,

    /// How long to pump after each simulated click or route change.
    #[arg(long, default_value_t = 0.35)]
    hold_seconds: f64,

    /// How long to leave each exercised screen idle before the next action.
    #[arg(long, default_value_t = 3.0)]
    idle_seconds: f64,

    /// Final idle dwell on the hub after all navigation cycles complete.
    #[arg(long, default_value_t = 10.0)]
    tail_idle_seconds: f64,
}

fn main() {
    let cli = Cli::parse();
    let code = match cli.command {
        Command::Validate(stage) => match stage {
            ValidateStage::Smoke(args) => {
                stages::smoke(&args.config_dir, &args.hardware, args.display_hold_seconds)
            }
            ValidateStage::Deploy(args) => stages::deploy(&args.config_dir),
            ValidateStage::Stability(args) => stages::stability(
                &args.config_dir,
                args.cycles,
                args.hold_seconds,
                args.idle_seconds,
            ),
            ValidateStage::Navigation(args) => stages::navigation(
                &args.config_dir,
                args.cycles,
                args.hold_seconds,
                args.idle_seconds,
                args.tail_idle_seconds,
            ),
            ValidateStage::Lvgl(args) => stages::lvgl(
                &args.config_dir,
                args.cycles,
                args.hold_seconds,
                args.idle_seconds,
            ),
            ValidateStage::Voip => stages::voip_stub(),
            ValidateStage::CloudVoice => stages::cloud_voice_stub(),
        },
    };
    std::process::exit(code);
}
