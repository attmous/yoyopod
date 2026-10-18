//! Tracing init for the CLI.

use tracing_subscriber::EnvFilter;

/// Initialize a global tracing subscriber.
///
/// `--verbose` toggles DEBUG vs. INFO. `RUST_LOG` env var overrides.
pub fn init(verbose: bool) {
    let default_level = if verbose { "debug" } else { "info" };
    let filter =
        EnvFilter::try_from_default_env().unwrap_or_else(|_| EnvFilter::new(default_level));
    let _ = tracing_subscriber::fmt()
        .with_env_filter(filter)
        .with_target(false)
        .with_writer(std::io::stderr)
        .try_init();
}
