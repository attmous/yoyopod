//! Small shared worker subprocess lifecycle boundary; no hardware policy.

/// Launch through the worker's private exec entrypoint. The resulting process
/// has its own process group and cannot survive death of its worker parent.
pub fn bound_command(argv: &[String]) -> std::io::Result<std::process::Command> {
    bound_command_with_lease(argv, None)
}

pub fn bound_command_with_lease(
    argv: &[String],
    lease_ms: Option<u64>,
) -> std::io::Result<std::process::Command> {
    if argv.is_empty() {
        return Err(std::io::Error::new(
            std::io::ErrorKind::InvalidInput,
            "empty audio command",
        ));
    }
    #[cfg(target_os = "linux")]
    {
        use std::os::unix::process::CommandExt;
        let mut command = std::process::Command::new(std::env::current_exe()?);
        command
            .arg("--owned-audio-parent")
            .arg(std::process::id().to_string())
            .arg(lease_ms.unwrap_or(0).to_string())
            .arg("--")
            .args(argv)
            .process_group(0);
        Ok(command)
    }
    #[cfg(not(target_os = "linux"))]
    {
        let _ = lease_ms;
        Err(std::io::Error::new(
            std::io::ErrorKind::Unsupported,
            "owned audio requires Linux",
        ))
    }
}

/// Called before normal worker argument parsing; never invokes a shell.
pub fn dispatch_audio_helper(allowed_programs: &[&str]) -> std::io::Result<()> {
    let mut args = std::env::args().skip(1);
    let mode = args.next();
    if !matches!(
        mode.as_deref(),
        Some("--owned-audio-parent" | "--owned-audio-watchdog")
    ) {
        return Ok(());
    }
    let parent = args
        .next()
        .and_then(|v| v.parse::<u32>().ok())
        .ok_or_else(|| std::io::Error::new(std::io::ErrorKind::InvalidInput, "missing parent"))?;
    let lease_ms = args
        .next()
        .and_then(|v| v.parse::<u64>().ok())
        .ok_or_else(|| std::io::Error::new(std::io::ErrorKind::InvalidInput, "missing lease"))?;
    #[cfg(not(target_os = "linux"))]
    let _ = lease_ms;
    bind_to_parent(parent)?;
    #[cfg(target_os = "linux")]
    if mode.as_deref() == Some("--owned-audio-watchdog") {
        if lease_ms == 0 {
            return Err(std::io::Error::new(
                std::io::ErrorKind::InvalidInput,
                "empty lease",
            ));
        }
        std::thread::sleep(std::time::Duration::from_millis(lease_ms));
        nix::sys::signal::kill(
            nix::unistd::Pid::from_raw(parent as i32),
            nix::sys::signal::Signal::SIGKILL,
        )
        .map_err(std::io::Error::from)?;
        std::process::exit(0);
    }
    if args.next().as_deref() != Some("--") {
        return Err(std::io::Error::new(
            std::io::ErrorKind::InvalidInput,
            "missing argv separator",
        ));
    }
    let program = args
        .next()
        .ok_or_else(|| std::io::Error::new(std::io::ErrorKind::InvalidInput, "missing program"))?;
    let name = std::path::Path::new(&program)
        .file_name()
        .and_then(|n| n.to_str())
        .unwrap_or_default();
    if !allowed_programs.contains(&name) {
        return Err(std::io::Error::new(
            std::io::ErrorKind::InvalidInput,
            "unsupported owned audio player",
        ));
    }
    #[cfg(target_os = "linux")]
    {
        use std::os::unix::process::CommandExt;
        if lease_ms > 0 {
            std::process::Command::new(std::env::current_exe()?)
                .arg("--owned-audio-watchdog")
                .arg(std::process::id().to_string())
                .arg(lease_ms.to_string())
                .stdin(std::process::Stdio::null())
                .stdout(std::process::Stdio::null())
                .stderr(std::process::Stdio::null())
                .spawn()?;
        }
        Err(std::process::Command::new(program).args(args).exec())
    }
    #[cfg(not(target_os = "linux"))]
    {
        let _ = program;
        unreachable!("parent binding rejects unsupported platforms")
    }
}

/// Arm parent death before exec, then verify the parent to close the spawn/arm race.
/// Linux preserves this signal across an ordinary non-setuid exec.
#[cfg(target_os = "linux")]
pub fn bind_to_parent(expected_parent: u32) -> std::io::Result<()> {
    use nix::sys::{prctl::set_pdeathsig, signal::Signal};
    use nix::unistd::getppid;
    set_pdeathsig(Signal::SIGKILL).map_err(std::io::Error::from)?;
    if expected_parent == 0 || getppid().as_raw() as u32 != expected_parent {
        return Err(std::io::Error::new(
            std::io::ErrorKind::BrokenPipe,
            "Worker exited before relay initialization",
        ));
    }
    Ok(())
}

#[cfg(not(target_os = "linux"))]
pub fn bind_to_parent(_expected_parent: u32) -> std::io::Result<()> {
    Err(std::io::Error::new(
        std::io::ErrorKind::Unsupported,
        "Parent-bound relays require Linux",
    ))
}
