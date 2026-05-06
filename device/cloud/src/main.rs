use anyhow::Result;
use clap::Parser;

#[derive(Debug, Parser)]
#[command(name = "yoyopod-cloud-host")]
#[command(about = "YoYoPod Rust Cloud Host")]
struct Args {
    #[arg(long, default_value = "config")]
    config_dir: String,
}

fn main() -> Result<()> {
    let args = Args::parse();
    yoyopod_cloud::worker::run(&args.config_dir)
}
