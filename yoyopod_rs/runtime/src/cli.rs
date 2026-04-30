use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::thread;
use std::time::Duration;

use anyhow::{bail, Result};
use clap::Parser;
use serde_json::json;

use crate::config::RuntimeConfig;
use crate::logging::{
    log_marker, remove_pid_file, shutdown_marker, startup_marker, write_pid_file,
};
use crate::runtime_loop::RuntimeLoop;
use crate::state::{RuntimeState, WorkerDomain, WorkerState};
use crate::worker::{WorkerSpec, WorkerSupervisor};

#[derive(Debug, Clone, Parser)]
#[command(name = "yoyopod-runtime")]
#[command(about = "YoYoPod Rust top-level runtime host")]
pub struct Args {
    #[arg(long, default_value = "config")]
    pub config_dir: PathBuf,
    #[arg(long)]
    pub dry_run: bool,
    #[arg(long, default_value = "whisplay")]
    pub hardware: String,
}

pub fn run(args: Args) -> Result<String> {
    let config = RuntimeConfig::load(&args.config_dir)?;
    if args.dry_run {
        return Ok(serde_json::to_string_pretty(&config)?);
    }

    run_runtime(config, &args.hardware)?;
    Ok(String::new())
}

fn run_runtime(config: RuntimeConfig, hardware: &str) -> Result<()> {
    let pid = std::process::id();
    write_pid_file(&config.pid_file, pid)?;
    log_marker(
        &config.log_file,
        startup_marker(env!("CARGO_PKG_VERSION"), pid),
    )?;

    let result = run_runtime_inner(&config, hardware);

    let mut shutdown_result =
        log_marker(&config.log_file, shutdown_marker(pid)).map_err(Into::into);
    if let Err(error) = remove_pid_file(&config.pid_file) {
        shutdown_result = Err(error.into());
    }

    result.and(shutdown_result)
}

fn run_runtime_inner(config: &RuntimeConfig, hardware: &str) -> Result<()> {
    let shutdown = Arc::new(AtomicBool::new(false));
    let shutdown_handler = Arc::clone(&shutdown);
    ctrlc::set_handler(move || {
        shutdown_handler.store(true, Ordering::SeqCst);
    })?;

    let mut workers = WorkerSupervisor::default();
    let state = match start_workers(&mut workers, config, hardware) {
        Ok(state) => state,
        Err(error) => {
            workers.stop_all(Duration::from_secs(1));
            return Err(error);
        }
    };
    send_startup_commands(&mut workers, config);

    let mut runtime = RuntimeLoop::new(state);
    while !shutdown.load(Ordering::SeqCst) && !runtime.shutdown_requested() {
        runtime.run_once(&mut workers);
        thread::sleep(Duration::from_millis(20));
    }

    workers.stop_all(Duration::from_secs(1));
    Ok(())
}

fn start_workers(
    workers: &mut WorkerSupervisor,
    config: &RuntimeConfig,
    hardware: &str,
) -> Result<RuntimeState> {
    let mut state = RuntimeState::default();
    state.mark_worker(WorkerDomain::Ui, WorkerState::Starting, "starting");

    if !workers.start(WorkerSpec::new(
        WorkerDomain::Ui,
        config.worker_paths.ui.clone(),
        ["--hardware".to_string(), hardware.to_string()],
    )) {
        bail!("failed to start UI worker");
    }
    if !workers.wait_for_ready(WorkerDomain::Ui, "ui.ready", Duration::from_secs(5)) {
        bail!("timed out waiting for ui.ready");
    }
    state.mark_worker(WorkerDomain::Ui, WorkerState::Running, "ready");

    if workers.start(WorkerSpec::new(
        WorkerDomain::Media,
        config.worker_paths.media.clone(),
        Vec::<String>::new(),
    )) {
        state.mark_worker(WorkerDomain::Media, WorkerState::Starting, "starting");
        if workers.wait_for_ready(WorkerDomain::Media, "media.ready", Duration::from_secs(3)) {
            state.mark_worker(WorkerDomain::Media, WorkerState::Running, "ready");
        }
    } else {
        state.mark_worker(
            WorkerDomain::Media,
            WorkerState::Degraded,
            "failed to start",
        );
    }

    if workers.start(WorkerSpec::new(
        WorkerDomain::Voip,
        config.worker_paths.voip.clone(),
        Vec::<String>::new(),
    )) {
        state.mark_worker(WorkerDomain::Voip, WorkerState::Starting, "starting");
        if workers.wait_for_ready(WorkerDomain::Voip, "voip.ready", Duration::from_secs(3)) {
            state.mark_worker(WorkerDomain::Voip, WorkerState::Running, "ready");
        }
    } else {
        state.mark_worker(WorkerDomain::Voip, WorkerState::Degraded, "failed to start");
    }

    Ok(state)
}

fn send_startup_commands(workers: &mut WorkerSupervisor, config: &RuntimeConfig) {
    workers.send_command(
        WorkerDomain::Ui,
        "ui.set_backlight",
        json!({"brightness": config.ui.brightness}),
    );
    workers.send_command(
        WorkerDomain::Media,
        "media.configure",
        config.media.to_worker_payload(),
    );
    workers.send_command(WorkerDomain::Media, "media.start", json!({}));
    workers.send_command(
        WorkerDomain::Voip,
        "voip.configure",
        config.voip.to_worker_payload(),
    );
    workers.send_command(WorkerDomain::Voip, "voip.register", json!({}));
}
