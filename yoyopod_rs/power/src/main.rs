use anyhow::Result;
use clap::Parser;

#[derive(Debug, Parser)]
#[command(name = "yoyopod-power-host")]
#[command(about = "YoYoPod Rust Power Host")]
struct Args {
    #[arg(long, default_value = "config")]
    config_dir: String,
}

fn main() -> Result<()> {
    let args = Args::parse();
    yoyopod_power::worker::run(&args.config_dir)
}
