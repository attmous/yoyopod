use clap::Parser;
use yoyopod_runtime::cli::{run, Args};

fn main() -> anyhow::Result<()> {
    let output = run(Args::parse())?;
    if !output.is_empty() {
        println!("{output}");
    }
    Ok(())
}
