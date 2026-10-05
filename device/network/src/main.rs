use anyhow::Result;
use clap::Parser;

#[derive(Debug, Parser)]
#[command(name = "yoyopod-network-host")]
#[command(about = "yoyopod Rust Network Host")]
struct Args {
    #[arg(long, default_value = "config")]
    config_dir: String,
    #[arg(long, hide = true)]
    gsm_audio_relay_parent: Option<u32>,
    #[arg(long, hide = true, value_parser = ["capture", "playback"])]
    gsm_audio_relay: Option<String>,
    #[arg(long, hide = true)]
    gsm_audio_sample_rate: Option<u32>,
}

fn main() -> Result<()> {
    yoyopod_protocol::process::verify_network_credentials()?;
    let args = Args::parse();
    if let Some(relay) = args.gsm_audio_relay.as_deref() {
        return yoyopod_network::gsm_audio_helper::run(
            args.gsm_audio_relay_parent
                .ok_or_else(|| anyhow::anyhow!("Missing audio relay parent"))?,
            relay,
            args.gsm_audio_sample_rate
                .ok_or_else(|| anyhow::anyhow!("Missing PCM format"))?,
        );
    }
    anyhow::ensure!(
        args.gsm_audio_relay_parent.is_none() && args.gsm_audio_sample_rate.is_none(),
        "Incomplete audio relay arguments"
    );
    yoyopod_network::worker::run(&args.config_dir)
}
