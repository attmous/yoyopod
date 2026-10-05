//! Trusted, offline maintenance; physical reset is explicitly attested by the operator.
use std::path::Path;

pub fn recover(path: &Path, legacy_attested: bool) -> Result<String, String> {
    if unsafe { libc::geteuid() } != 0 {
        return Err("cold recovery requires root maintenance".into());
    }
    for unit in [
        "yoyopod-dev.service",
        "yoyopod-prod.service",
        "yoyopod.service",
        "ModemManager.service",
    ] {
        let result = std::process::Command::new("/usr/bin/systemctl")
            .args(["show", "--property=ActiveState", "--value", unit])
            .output()
            .map_err(|e| e.to_string())?;
        let value = String::from_utf8(result.stdout).map_err(|e| e.to_string())?;
        if !result.status.success() || value.trim() != "inactive" {
            return Err(format!("{unit} must be verified inactive"));
        }
    }
    for entry in std::fs::read_dir("/sys/class/tty").map_err(|e| e.to_string())? {
        let name = entry.map_err(|e| e.to_string())?.file_name();
        if name.to_string_lossy().starts_with("ttyUSB") {
            return Err("disconnect the physically power-reset modem before recovery".into());
        }
    }
    // The modem's control function can exist without a tty interface.
    for entry in std::fs::read_dir("/dev").map_err(|e| e.to_string())? {
        if entry
            .map_err(|e| e.to_string())?
            .file_name()
            .to_string_lossy()
            .starts_with("cdc-wdm")
        {
            return Err("modem control device still present".into());
        }
    }
    prove_stopped_resources()?;
    let boot =
        std::fs::read_to_string("/proc/sys/kernel/random/boot_id").map_err(|e| e.to_string())?;
    let receipt = crate::call_manager::native_guard::retire_after_cold_reset(
        path,
        boot.trim(),
        legacy_attested,
    )?;
    Ok(format!("Cold recovery recorded in {}. Reconnect the modem before starting the selected runtime lane.", receipt.display()))
}

fn prove_stopped_resources() -> Result<(), String> {
    for entry in std::fs::read_dir("/proc").map_err(|e| e.to_string())? {
        let entry = entry.map_err(|e| e.to_string())?;
        let Ok(pid) = entry.file_name().to_string_lossy().parse::<u32>() else {
            continue;
        };
        let proc = entry.path();
        match std::fs::read_link(proc.join("exe")) {
            Ok(exe) => {
                let name = exe.file_name().unwrap_or_default().to_string_lossy();
                if pid != std::process::id()
                    && (name.starts_with("yoyopod-") || name == "ModemManager")
                {
                    return Err(format!(
                        "old runtime/worker/native owner still running: {pid}"
                    ));
                }
            }
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
                // Kernel threads/zombies have no executable and no user descriptors.
                let status = match std::fs::read_to_string(proc.join("status")) {
                    Ok(status) => status,
                    Err(e) if e.kind() == std::io::ErrorKind::NotFound => continue,
                    Err(e) => return Err(e.to_string()),
                };
                if !status
                    .lines()
                    .any(|line| line == "Kthread:\t1" || line.starts_with("State:\tZ"))
                {
                    return Err(format!("incomplete executable proof for {pid}"));
                }
            }
            Err(e) => return Err(format!("incomplete process proof: {e}")),
        }
        let descriptors = match std::fs::read_dir(proc.join("fd")) {
            Ok(descriptors) => descriptors,
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => continue,
            Err(e) => return Err(format!("incomplete resource proof: {e}")),
        };
        for descriptor in descriptors {
            match std::fs::read_link(descriptor.map_err(|e| e.to_string())?.path()) {
                Ok(target) => {
                    let target = target.to_string_lossy();
                    if target.starts_with("/dev/snd/pcm")
                        || target.starts_with("/dev/ttyUSB")
                        || target.starts_with("/dev/cdc-wdm")
                    {
                        return Err(format!("audio/modem resource remains open in {pid}"));
                    }
                }
                Err(e) if e.kind() == std::io::ErrorKind::NotFound => {}
                Err(e) => return Err(format!("incomplete descriptor proof: {e}")),
            }
        }
    }
    Ok(())
}
