use anyhow::Result;

#[cfg(feature = "native-liblinphone")]
fn main() -> Result<()> {
    use clap::Parser;
    use yoyopod_voip::{host::VoipHost, liblinphone::LiblinphoneBackend, worker};

    #[derive(Debug, Parser)]
    #[command(name = "yoyopod-voip-host")]
    #[command(about = "YoYoPod Rust VoIP host")]
    struct Args {}

    let _args = Args::parse();
    let stdin = std::io::BufReader::new(std::io::stdin());
    let mut stdout = std::io::stdout();
    let mut stderr = std::io::stderr();
    let mut host = VoipHost::default();
    let mut backend = LiblinphoneBackend::new();
    worker::run_worker(stdin, &mut stdout, &mut stderr, &mut host, &mut backend)
}

#[cfg(not(feature = "native-liblinphone"))]
fn main() -> Result<()> {
    anyhow::bail!("yoyopod-voip-host production binary requires the native-liblinphone feature")
}
