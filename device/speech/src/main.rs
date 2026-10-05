use anyhow::Result;

fn main() -> Result<()> {
    yoyopod_protocol::process::verify_audio_credentials()?;
    yoyopod_speech::worker::run()
}
