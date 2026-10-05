//! A complete procfs census and stable pidfds are required for resource proof.
use rustix::event::{poll, PollFd, PollFlags, Timespec};
use rustix::fd::OwnedFd;
use rustix::process::{pidfd_open, pidfd_send_signal, Pid, PidfdFlags, Signal};
use std::fs;
use std::time::{Duration, Instant};

trait ProcessHandle {
    fn exited(&self) -> Result<bool, String>;
    fn kill(&self) -> Result<(), String>;
}
impl ProcessHandle for OwnedFd {
    fn exited(&self) -> Result<bool, String> {
        let mut fds = [PollFd::new(self, PollFlags::IN)];
        poll(&mut fds, Some(&Timespec::default())).map_err(|e| e.to_string())?;
        let flags = fds[0].revents();
        if flags.intersects(PollFlags::NVAL | PollFlags::ERR) {
            return Err("pidfd poll failed".into());
        }
        Ok(flags.intersects(PollFlags::IN | PollFlags::HUP))
    }
    fn kill(&self) -> Result<(), String> {
        match pidfd_send_signal(self, Signal::KILL) {
            Ok(()) | Err(rustix::io::Errno::SRCH) => Ok(()),
            Err(e) => Err(e.to_string()),
        }
    }
}

// The handle was opened BEFORE reading environ. If the old process exited and
// its PID was reused during that read, this handle is now readable: ignore the
// new PID's bytes. All signalling and subsequent waiting use the original fd.
fn kill_if_owned(
    handle: &impl ProcessHandle,
    environment: std::io::Result<Vec<u8>>,
    expected: &[u8],
) -> Result<bool, String> {
    if handle.exited()? {
        return Ok(false);
    }
    let environment =
        environment.map_err(|e| format!("incomplete process environment census: {e}"))?;
    if !environment.split(|b| *b == 0).any(|item| item == expected) {
        return Ok(false);
    }
    handle.kill()?;
    Ok(true)
}

fn birth_tick(stat: &str) -> Result<u64, String> {
    // comm is parenthesized and may contain spaces or closing parentheses.
    stat.rsplit_once(") ")
        .and_then(|(_, rest)| rest.split_whitespace().nth(19))
        .ok_or("missing process starttime")?
        .parse::<u64>()
        .map_err(|e| e.to_string())
}

fn preexisting_or_gone(
    handle: &impl ProcessHandle,
    stat: std::io::Result<String>,
    lower: Option<u64>,
) -> Result<bool, String> {
    if handle.exited()? {
        return Ok(true);
    }
    let birth = birth_tick(&stat.map_err(|e| e.to_string())?)?;
    Ok(lower.is_some_and(|lower| birth < lower))
}

pub(super) fn runtime_birth(status: &str) -> Result<u64, String> {
    // A procfs mounted for an ancestor PID namespace exposes multiple NSpid
    // values. Do not feed those numeric IDs to pidfd_open in a different view.
    let ids = status
        .lines()
        .find_map(|line| line.strip_prefix("NSpid:"))
        .ok_or("missing procfs namespace proof")?
        .split_whitespace()
        .map(str::parse::<u32>)
        .collect::<Result<Vec<_>, _>>()
        .map_err(|e| e.to_string())?;
    if ids != [std::process::id()] {
        return Err("procfs PID namespace mismatch".into());
    }
    let stat = fs::read_to_string("/proc/self/stat").map_err(|e| e.to_string())?;
    if stat.split_whitespace().next() != Some(&std::process::id().to_string()) {
        return Err("procfs process identity mismatch".into());
    }
    birth_tick(&stat)
}

fn outside_owner(status: &str, owner: u32) -> Result<bool, String> {
    let value = status
        .lines()
        .find_map(|line| line.strip_prefix("Uid:"))
        .ok_or("missing UID census")?;
    let uids = value
        .split_whitespace()
        .map(str::parse::<u32>)
        .collect::<Result<Vec<_>, _>>()
        .map_err(|e| e.to_string())?;
    if uids.len() != 4 {
        return Err("incomplete UID census".into());
    }
    let nnp = status
        .lines()
        .find_map(|line| line.strip_prefix("NoNewPrivs:"))
        .ok_or("missing no-new-privileges census")?
        .trim();
    if !matches!(nnp, "0" | "1") {
        return Err("invalid no-new-privileges census".into());
    }
    // NNP is irreversible and inherited. A process without it cannot belong to
    // this launch, including nondumpable same-UID SSH/login processes.
    Ok(uids.iter().any(|uid| *uid != owner) || nnp == "0")
}

pub(super) fn reap_owned_helpers(
    token: &str,
    owner_uid: Option<u32>,
    runtime_start: Option<u64>,
) -> Result<(), String> {
    let expected = format!("YOYOPOD_WORKER_LIFETIME={token}");
    let deadline = Instant::now() + Duration::from_secs(2);
    loop {
        let mut owned = Vec::new();
        let mut error = None;
        for entry in fs::read_dir("/proc").map_err(|e| e.to_string())? {
            let entry = match entry {
                Ok(entry) => entry,
                Err(e) => {
                    error = Some(e.to_string());
                    continue;
                }
            };
            let Some(pid) = entry
                .file_name()
                .to_str()
                .and_then(|s| s.parse::<i32>().ok())
                .and_then(Pid::from_raw)
            else {
                continue;
            };
            let handle = match pidfd_open(pid, PidfdFlags::empty()) {
                Ok(handle) => handle,
                Err(rustix::io::Errno::SRCH) => continue,
                Err(e) => {
                    error = Some(format!("incomplete pidfd census: {e}"));
                    continue;
                }
            };
            match preexisting_or_gone(
                &handle,
                fs::read_to_string(entry.path().join("stat")),
                runtime_start,
            ) {
                Ok(true) => continue,
                Ok(false) => (),
                Err(e) => {
                    error = Some(format!("incomplete process birth census: {e}"));
                    continue;
                }
            }
            if let Some(uid) = owner_uid {
                let status = fs::read_to_string(entry.path().join("status"));
                // /proc directory ownership may change with dumpability: use the
                // actual four kernel credential UIDs, checked against the pidfd.
                if handle.exited()? {
                    continue;
                }
                match status
                    .map_err(|e| e.to_string())
                    .and_then(|s| outside_owner(&s, uid))
                {
                    Ok(true) => continue,
                    Ok(false) => (),
                    Err(e) => {
                        error = Some(format!("incomplete process ownership census: {e}"));
                        continue;
                    }
                }
            }
            match kill_if_owned(
                &handle,
                fs::read(entry.path().join("environ")),
                expected.as_bytes(),
            ) {
                Ok(true) => owned.push(handle),
                Ok(false) => (),
                Err(e) => error = Some(format!("pid {}: {e}", pid.as_raw_nonzero())),
            }
        }
        // Even when another entry failed, wait for every helper already signalled.
        for handle in &owned {
            while !handle.exited()? {
                if Instant::now() >= deadline {
                    return Err("old worker helper has not exited".into());
                }
                std::thread::sleep(Duration::from_millis(10));
            }
        }
        if let Some(error) = error {
            return Err(error);
        }
        if owned.is_empty() {
            return Ok(());
        }
        if Instant::now() >= deadline {
            return Err("helper census did not converge".into());
        }
        // Repeat after exit: a helper could have forked while the census ran.
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::cell::Cell;
    struct Handle {
        gone: bool,
        signals: Cell<usize>,
    }
    impl ProcessHandle for Handle {
        fn exited(&self) -> Result<bool, String> {
            Ok(self.gone)
        }
        fn kill(&self) -> Result<(), String> {
            self.signals.set(self.signals.get() + 1);
            Ok(())
        }
    }
    #[test]
    fn birth_bound_excludes_only_proven_older_processes() {
        let live = Handle {
            gone: false,
            signals: Cell::new(0),
        };
        let stat = |tick| format!("123 (name with ) parens) S {} {tick} 0", "0 ".repeat(18));
        assert!(preexisting_or_gone(&live, Ok(stat(99)), Some(100)).unwrap());
        for tick in [100, 101] {
            assert!(!preexisting_or_gone(&live, Ok(stat(tick)), Some(100)).unwrap());
            assert!(kill_if_owned(
                &live,
                Err(std::io::ErrorKind::PermissionDenied.into()),
                b"token"
            )
            .is_err());
        }
        assert!(preexisting_or_gone(&live, Ok("malformed".into()), Some(100)).is_err());
        assert!(preexisting_or_gone(
            &live,
            Err(std::io::ErrorKind::PermissionDenied.into()),
            Some(100)
        )
        .is_err());
        let gone = Handle {
            gone: true,
            signals: Cell::new(0),
        };
        assert!(
            preexisting_or_gone(&gone, Err(std::io::ErrorKind::NotFound.into()), Some(100))
                .unwrap()
        );
    }
    #[test]
    fn bounded_census_excludes_only_impossible_credentials() {
        assert!(!outside_owner("Uid: 1000 1000 1000 1000\nNoNewPrivs: 1", 1000).unwrap());
        assert!(outside_owner("Uid: 0 0 0 0\nNoNewPrivs: 1", 1000).unwrap());
        assert!(outside_owner("Uid: 1000 1000 0 1000\nNoNewPrivs: 1", 1000).unwrap());
        assert!(outside_owner("Uid: 1000 1000 1000 1000\nNoNewPrivs: 0", 1000).unwrap());
        assert!(outside_owner("Uid: 1000 1000 1000 1000", 1000).is_err());
    }
    #[test]
    fn pid_reuse_after_environment_read_never_signals_replacement() {
        let old = Handle {
            gone: true,
            signals: Cell::new(0),
        };
        assert!(!kill_if_owned(&old, Ok(b"token".to_vec()), b"token").unwrap());
        assert_eq!(old.signals.get(), 0);
    }
    #[test]
    fn unreadable_live_process_cannot_prove_census_complete() {
        let live = Handle {
            gone: false,
            signals: Cell::new(0),
        };
        assert!(kill_if_owned(
            &live,
            Err(std::io::ErrorKind::PermissionDenied.into()),
            b"token"
        )
        .is_err());
        assert_eq!(live.signals.get(), 0);
        let gone = Handle {
            gone: true,
            signals: Cell::new(0),
        };
        assert!(!kill_if_owned(&gone, Err(std::io::ErrorKind::NotFound.into()), b"token").unwrap());
    }
    #[test]
    fn matching_live_handle_is_the_only_signal_target() {
        let live = Handle {
            gone: false,
            signals: Cell::new(0),
        };
        assert!(!kill_if_owned(&live, Ok(b"other".to_vec()), b"token").unwrap());
        assert!(kill_if_owned(&live, Ok(b"token\0x=y".to_vec()), b"token").unwrap());
        assert_eq!(live.signals.get(), 1);
    }
}
