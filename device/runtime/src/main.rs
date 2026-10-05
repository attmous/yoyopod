use clap::Parser;
use yoyopod_runtime::cli::{run, Args};

fn main() -> anyhow::Result<()> {
    #[cfg(target_os = "linux")]
    if yoyopod_runtime::network_owner::dispatch_internal()? {
        return Ok(());
    }
    let output = run(Args::parse())?;
    if !output.is_empty() {
        println!("{output}");
    }
    Ok(())
}
