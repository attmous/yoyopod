use std::io::{self, BufRead, Write};

use anyhow::Result;

use crate::protocol::{ready_event, stopped_event, WorkerEnvelope};

pub fn run(config_dir: &str) -> Result<()> {
    let stdin = io::stdin();
    let mut stdout = io::stdout().lock();

    write_envelope(&mut stdout, &ready_event(config_dir))?;

    for line in stdin.lock().lines() {
        let line = line?;
        if line.trim().is_empty() {
            continue;
        }

        if line.contains("\"type\":\"network.shutdown\"")
            || line.contains("\"type\":\"worker.stop\"")
        {
            write_envelope(&mut stdout, &stopped_event("shutdown"))?;
            break;
        }
    }

    Ok(())
}

fn write_envelope(output: &mut dyn Write, envelope: &WorkerEnvelope) -> Result<()> {
    writeln!(output, "{}", serde_json::to_string(envelope)?)?;
    output.flush()?;
    Ok(())
}
