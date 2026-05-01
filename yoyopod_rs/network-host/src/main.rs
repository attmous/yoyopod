use anyhow::Result;
use clap::Parser;

#[derive(Debug, Parser)]
#[command(name = "yoyopod-network-host")]
#[command(about = "YoYoPod Rust Network Host")]
struct Args {
    #[arg(long, default_value = "config")]
    config_dir: String,
}

fn main() -> Result<()> {
    let args = Args::parse();
    yoyopod_network_host::worker::run(&args.config_dir)
}
