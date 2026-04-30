use anyhow::Result;
use clap::Parser;

#[derive(Debug, Parser)]
#[command(name = "yoyopod-media-host")]
#[command(about = "YoYoPod Rust media host")]
struct Args {}

fn main() -> Result<()> {
    let _args = Args::parse();
    yoyopod_media_host::worker::run()
}
