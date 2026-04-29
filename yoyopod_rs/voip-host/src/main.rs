use anyhow::Result;
use clap::Parser;

#[derive(Debug, Parser)]
#[command(name = "yoyopod-voip-host")]
#[command(about = "YoYoPod Rust VoIP host")]
struct Args {
    #[arg(long, default_value = "")]
    shim_path: String,
}

fn main() -> Result<()> {
    let args = Args::parse();
    let explicit_shim_path = if args.shim_path.trim().is_empty() {
        None
    } else {
        Some(args.shim_path.as_str())
    };
    yoyopod_voip_host::worker::run(explicit_shim_path)
}
