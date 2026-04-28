mod framebuffer;
mod hardware;
mod hub;
mod input;
mod lvgl_bridge;
mod protocol;
mod render;
mod runtime;
mod screens;
mod whisplay_panel;
mod worker;

use anyhow::Result;
use clap::{Parser, ValueEnum};

#[derive(Debug, Clone, Copy, ValueEnum)]
enum HardwareMode {
    Mock,
    Whisplay,
}

#[derive(Debug, Parser)]
#[command(name = "yoyopod-ui-host")]
#[command(about = "Whisplay Rust UI host")]
struct Args {
    #[arg(long, value_enum, default_value_t = HardwareMode::Mock)]
    hardware: HardwareMode,
}

fn main() -> Result<()> {
    let args = Args::parse();
    match args.hardware {
        HardwareMode::Mock => {
            let display = hardware::mock::MockDisplay::new(240, 280);
            let button = hardware::mock::MockButton::new();
            let stdin = std::io::stdin();
            let mut stdout = std::io::stdout();
            let mut stderr = std::io::stderr();
            worker::run_worker(stdin, &mut stdout, &mut stderr, display, button)
        }
        HardwareMode::Whisplay => {
            #[cfg(all(target_os = "linux", feature = "whisplay-hardware"))]
            {
                let (display, button) = hardware::whisplay::open_from_env()?;
                let stdin = std::io::stdin();
                let mut stdout = std::io::stdout();
                let mut stderr = std::io::stderr();
                return worker::run_worker(stdin, &mut stdout, &mut stderr, display, button);
            }
            #[cfg(not(all(target_os = "linux", feature = "whisplay-hardware")))]
            {
                anyhow::bail!(
                    "whisplay hardware mode requires Linux and the whisplay-hardware feature"
                );
            }
        }
    }
}
