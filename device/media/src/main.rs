use anyhow::Result;
use clap::Parser;

#[derive(Debug, Parser)]
#[command(name = "yoyopod-media-host")]
#[command(about = "yoyopod Rust media host")]
struct Args {}

fn main() -> Result<()> {
    yoyopod_protocol::process::dispatch_audio_helper(&["mpv"])?;
    let _args = Args::parse();
    yoyopod_media::worker::run()
}
