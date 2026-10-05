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
    // Require no non-hub USB peripherals during this offline ceremony. A modem
    // may still be enumerated even when no serial/control driver is attached.
    for entry in std::fs::read_dir("/sys/bus/usb/devices").map_err(|e| e.to_string())? {
        let path = entry.map_err(|e| e.to_string())?.path();
        match std::fs::read_to_string(path.join("bDeviceClass")) {
            Ok(class) if class.trim() == "09" => {}
            Ok(_) => {
                return Err("disconnect all non-hub USB peripherals before cold recovery".into())
            }
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => {
                // USB interfaces do not have device descriptors.
                if path
                    .join("idVendor")
                    .try_exists()
                    .map_err(|e| e.to_string())?
                {
                    return Err("incomplete USB device proof".into());
                }
            }
            Err(e) => return Err(format!("incomplete USB device proof: {e}")),
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
        prove_process_resources(&entry.path(), pid)?;
    }
    Ok(())
}

fn prove_process_resources(proc: &Path, pid: u32) -> Result<(), String> {
    match std::fs::read_link(proc.join("exe")) {
        Ok(exe) => {
            let name = exe.file_name().unwrap_or_default().to_string_lossy();
            if pid != std::process::id() && (name.starts_with("yoyopod-") || name == "ModemManager")
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
                Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Ok(()),
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
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Ok(()),
        Err(e) => return Err(format!("incomplete resource proof: {e}")),
    };
    for descriptor in descriptors {
        match std::fs::read_link(descriptor.map_err(|e| e.to_string())?.path()) {
            Ok(target) => {
                let target = target.to_string_lossy();
                if target.starts_with("/dev/snd/")
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
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;
    use std::process::{Child, Command, Stdio};
    use std::time::{Duration, Instant};

    struct FixtureChild(Child);
    impl Drop for FixtureChild {
        fn drop(&mut self) {
            let _ = self.0.kill();
            let _ = self.0.wait();
        }
    }

    #[test]
    fn zombie_leader_with_live_resource_holder_cannot_prove_cold_recovery() {
        let dir = tempfile::tempdir().unwrap();
        let executable = dir.path().join("leader-exit");
        // A real pthread leader exit is isolated from Rust's multithreaded test
        // harness. This fixture opens only a temporary ordinary file, never PCM.
        let mut compiler = Command::new("cc")
            .args(["-x", "c", "-pthread", "-o"])
            .arg(&executable)
            .arg("-")
            .stdin(Stdio::piped())
            .spawn()
            .unwrap();
        compiler
            .stdin
            .take()
            .unwrap()
            .write_all(
                br#"
            #include <pthread.h>
            #include <fcntl.h>
            #include <unistd.h>
            #include <stdio.h>
            static int resource;
            static void *hold(void *unused) {
                char byte;
                if (read(0, &byte, 1) == 1 && fcntl(resource, F_GETFD) >= 0)
                    dprintf(1, "resource-open\n");
                sleep(60); return 0;
            }
            int main(int argc, char **argv) {
                if (argc != 2 || (resource = open(argv[1], O_RDONLY)) < 0) return 2;
                pthread_t thread;
                if (pthread_create(&thread, 0, hold, 0)) return 3;
                pthread_exit(0);
            }
        "#,
            )
            .unwrap();
        assert!(compiler.wait().unwrap().success());
        let resource = dir.path().join("test-resource");
        std::fs::write(&resource, b"ordinary test resource").unwrap();
        let mut child = FixtureChild(
            Command::new(&executable)
                .arg(&resource)
                .stdin(Stdio::piped())
                .stdout(Stdio::piped())
                .spawn()
                .unwrap(),
        );
        let proc = std::path::PathBuf::from(format!("/proc/{}", child.0.id()));
        let deadline = Instant::now() + Duration::from_secs(3);
        loop {
            let status = std::fs::read_to_string(proc.join("status")).unwrap();
            if status.lines().any(|line| line.starts_with("State:\tZ")) {
                break;
            }
            assert!(Instant::now() < deadline, "fixture leader did not exit");
            std::thread::sleep(Duration::from_millis(10));
        }
        let tasks: Vec<_> = std::fs::read_dir(proc.join("task"))
            .unwrap()
            .map(|task| task.unwrap().path())
            .collect();
        assert!(tasks.len() > 1, "fixture must retain a live sibling");
        child.0.stdin.as_mut().unwrap().write_all(b"?").unwrap();
        let mut held = String::new();
        std::io::BufRead::read_line(
            &mut std::io::BufReader::new(child.0.stdout.take().unwrap()),
            &mut held,
        )
        .unwrap();
        assert_eq!(
            held, "resource-open\n",
            "sibling must prove its descriptor remains valid after leader exit"
        );
        assert!(std::fs::read_link(proc.join("exe")).is_err());
        let proof = prove_process_resources(&proc, child.0.id());
        drop(child); // Always kill/reap the isolated group before asserting proof.
        assert!(
            proof.is_err(),
            "zombie leader is not whole-process resource absence: {proof:?}"
        );
    }
    #[test]
    fn zombie_leader_empty_fd_view_does_not_prove_thread_group_absence() {
        let dir = tempfile::tempdir().unwrap();
        std::fs::create_dir_all(dir.path().join("fd")).unwrap();
        std::fs::write(
            dir.path().join("status"),
            "State:\tZ (zombie)\nKthread:\t0\nThreads:\t2\n",
        )
        .unwrap();
        std::fs::create_dir_all(dir.path().join("task/10/fd")).unwrap();
        std::fs::create_dir_all(dir.path().join("task/11/fd")).unwrap();
        std::fs::write(
            dir.path().join("task/10/status"),
            "State:\tZ (zombie)\nKthread:\t0\n",
        )
        .unwrap();
        std::os::unix::fs::symlink("/usr/bin/resource-holder", dir.path().join("task/11/exe"))
            .unwrap();
        std::os::unix::fs::symlink("/dev/snd/test-fixture", dir.path().join("task/11/fd/3"))
            .unwrap();
        assert!(
            prove_process_resources(dir.path(), 10).is_err(),
            "readable leader-only view must not hide a sibling resource"
        );
    }
}
