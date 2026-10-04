//! Small shared worker subprocess lifecycle boundary; no hardware policy.

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
