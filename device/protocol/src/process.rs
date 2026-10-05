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
    verify_audio_credentials()?;
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

/// Runs before native startup or helper dispatch. The supervisor supplies the
/// expected owner; no audio child is allowed to run with inherited privileges.
pub fn verify_audio_credentials() -> std::io::Result<()> {
    #[cfg(target_os = "linux")]
    if let Ok(owner) = std::env::var("YOYOPOD_AUDIO_OWNER_UID") {
        let owner = owner.parse::<u32>().map_err(std::io::Error::other)?;
        let status = std::fs::read_to_string("/proc/self/status")?;
        let fields: std::collections::HashMap<_, _> = status
            .lines()
            .filter_map(|line| line.split_once(':'))
            .collect();
        let uids: Vec<_> = fields
            .get("Uid")
            .ok_or_else(|| std::io::Error::other("missing UIDs"))?
            .split_whitespace()
            .collect();
        let expected = owner.to_string();
        let valid = owner != 0
            && uids.len() == 4
            && uids.iter().all(|uid| *uid == expected)
            && fields
                .get("NoNewPrivs")
                .is_some_and(|value| value.trim() == "1")
            && ["CapInh", "CapPrm", "CapEff", "CapAmb"].iter().all(|key| {
                fields
                    .get(key)
                    .is_some_and(|value| u64::from_str_radix(value.trim(), 16) == Ok(0))
            });
        if !valid {
            return Err(std::io::Error::other(
                "audio post-exec credentials are not the required zero-capability NNP owner",
            ));
        }
        if std::env::args().nth(1).as_deref() == Some("--audio-credential-proof") {
            println!("{status}");
            std::process::exit(0);
        }
    }
    Ok(())
}

pub fn verify_network_credentials() -> std::io::Result<()> {
    #[cfg(target_os = "linux")]
    if let Ok(expected) = std::env::var("YOYOPOD_NETWORK_CREDENTIALS") {
        let expected: serde_json::Value =
            serde_json::from_str(&expected).map_err(std::io::Error::other)?;
        let status = std::fs::read_to_string("/proc/self/status")?;
        let fields: std::collections::HashMap<_, _> = status
            .lines()
            .filter_map(|line| line.split_once(':'))
            .collect();
        for (field, key, count) in [("Uid", "uid", 4), ("Gid", "gid", 4)] {
            let values = fields
                .get(field)
                .ok_or_else(|| std::io::Error::other("missing Network credentials"))?
                .split_whitespace()
                .collect::<Vec<_>>();
            let expected = expected[key]
                .as_u64()
                .ok_or_else(|| std::io::Error::other("invalid Network owner"))?
                .to_string();
            if values.len() != count || values.iter().any(|v| *v != expected) {
                return Err(std::io::Error::other("Network owner credentials changed"));
            }
        }
        let groups = fields
            .get("Groups")
            .ok_or_else(|| std::io::Error::other("missing groups"))?
            .split_whitespace()
            .map(str::parse::<u32>)
            .collect::<Result<Vec<_>, _>>()
            .map_err(std::io::Error::other)?;
        let expected_groups: Vec<u32> =
            serde_json::from_value(expected["groups"].clone()).map_err(std::io::Error::other)?;
        let cap = expected["cap"]
            .as_u64()
            .ok_or_else(|| std::io::Error::other("missing cap"))?;
        if groups != expected_groups
            || fields.get("NoNewPrivs").is_none_or(|v| v.trim() != "0")
            || ["CapInh", "CapPrm", "CapEff", "CapAmb"].iter().any(|key| {
                fields
                    .get(key)
                    .is_none_or(|v| u64::from_str_radix(v.trim(), 16) != Ok(cap))
            })
        {
            return Err(std::io::Error::other(
                "Network groups/capabilities/NNP contract changed",
            ));
        }
    }
    Ok(())
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
