//! Privileged owner for a single Network lifetime, using existing sudo authority.
//! The owner is a subreaper, not a process-name/ancestry census. Only its kernel
//! children (including adopted descendants) can be signalled. ECHILD proves drain.
use serde::{Deserialize, Serialize};
use std::io::{Read, Write};
use std::os::unix::fs::{DirBuilderExt, PermissionsExt};
use std::os::unix::io::AsRawFd;
use std::os::unix::net::{UnixListener, UnixStream};
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::mpsc::{self, Receiver};
use std::time::{Duration, Instant};

#[derive(Serialize, Deserialize)]
struct Launch {
    socket: PathBuf,
    token: String,
    supervisor: u32,
    uid: u32,
    gid: u32,
    groups: Vec<u32>,
    bind_cap: bool,
    program: String,
    args: Vec<String>,
    fixture: bool,
}

pub struct NetworkOwner {
    connection: Receiver<Result<UnixStream, String>>,
    stream: Option<UnixStream>,
    directory: PathBuf,
    drained: bool,
}

fn credentials(stream: &UnixStream) -> Result<libc::ucred, String> {
    let mut value = libc::ucred {
        pid: 0,
        uid: 0,
        gid: 0,
    };
    let mut size = std::mem::size_of_val(&value) as libc::socklen_t;
    let result = unsafe {
        libc::getsockopt(
            stream.as_raw_fd(),
            libc::SOL_SOCKET,
            libc::SO_PEERCRED,
            (&mut value as *mut libc::ucred).cast(),
            &mut size,
        )
    };
    if result != 0 || size as usize != std::mem::size_of_val(&value) {
        return Err("cannot authenticate Network owner peer".into());
    }
    Ok(value)
}

fn field_numbers(status: &str, name: &str) -> Result<Vec<u32>, String> {
    status
        .lines()
        .find_map(|line| line.strip_prefix(name))
        .ok_or("missing Network credentials")?
        .split_whitespace()
        .map(|n| n.parse::<u32>().map_err(|e| e.to_string()))
        .collect()
}

impl NetworkOwner {
    /// This constructor never waits for sudo/handshake. Authentication happens in
    /// a bounded background thread; retirement alone may block awaiting proof.
    pub fn launch(
        program: &str,
        args: &[String],
        token: &str,
        fixture: bool,
    ) -> Result<(Self, Child), String> {
        let status = std::fs::read_to_string("/proc/self/status").map_err(|e| e.to_string())?;
        let uids = field_numbers(&status, "Uid:")?;
        let gids = field_numbers(&status, "Gid:")?;
        if uids.len() != 4
            || gids.len() != 4
            || uids.iter().any(|v| *v != uids[0])
            || gids.iter().any(|v| *v != gids[0])
        {
            return Err(
                "Network guardian requires the supported equal non-root service credentials".into(),
            );
        }
        if uids[0] != 0 && !status.lines().any(|line| line == "NoNewPrivs:\t0") {
            return Err("Network sudo requires the existing NNP0 contract".into());
        }
        let mut caps = Vec::new();
        for key in ["CapInh:", "CapPrm:", "CapEff:", "CapAmb:"] {
            let value = status
                .lines()
                .find_map(|line| line.strip_prefix(key))
                .ok_or("missing Network caps")?;
            caps.push(u64::from_str_radix(value.trim(), 16).map_err(|e| e.to_string())?);
        }
        if uids[0] != 0 && (caps.iter().any(|cap| *cap != caps[0]) || !matches!(caps[0], 0 | 0x400))
        {
            return Err("unsupported Network capability contract".into());
        }
        let directory = std::env::temp_dir().join(format!("yoyopod-network-owner-{token}"));
        std::fs::DirBuilder::new()
            .mode(0o700)
            .create(&directory)
            .map_err(|e| e.to_string())?;
        let socket = directory.join("control");
        let listener = UnixListener::bind(&socket).map_err(|e| e.to_string())?;
        std::fs::set_permissions(&socket, std::fs::Permissions::from_mode(0o600))
            .map_err(|e| e.to_string())?;
        listener.set_nonblocking(true).map_err(|e| e.to_string())?;
        let launch = Launch {
            socket,
            token: token.into(),
            supervisor: std::process::id(),
            uid: uids[0],
            gid: gids[0],
            groups: field_numbers(&status, "Groups:")?,
            bind_cap: caps[0] == 0x400,
            program: program.into(),
            args: args.to_vec(),
            fixture,
        };
        let executable = std::env::current_exe().map_err(|e| e.to_string())?;
        let mut command = if launch.uid == 0 {
            Command::new(&executable)
        } else {
            let mut command = Command::new("/usr/bin/sudo");
            command.args(["-n", "--"]).arg(&executable);
            command
        };
        command
            .arg("--network-lifetime-owner")
            .arg(serde_json::to_string(&launch).map_err(|e| e.to_string())?)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::inherit());
        let child = command.spawn().map_err(|e| e.to_string())?;
        let (tx, connection) = mpsc::channel();
        let expected = token.as_bytes().to_vec();
        std::thread::spawn(move || {
            let result = (|| {
                let deadline = Instant::now() + Duration::from_secs(5);
                loop {
                    match listener.accept() {
                        Ok((mut stream, _)) => {
                            if credentials(&stream)?.uid != 0 {
                                continue;
                            }
                            stream
                                .set_read_timeout(Some(Duration::from_secs(3)))
                                .map_err(|e| e.to_string())?;
                            stream
                                .set_write_timeout(Some(Duration::from_secs(3)))
                                .map_err(|e| e.to_string())?;
                            let mut hello = vec![0; expected.len()];
                            stream.read_exact(&mut hello).map_err(|e| e.to_string())?;
                            if hello != expected {
                                return Err("Network owner lifetime mismatch".into());
                            }
                            stream.write_all(b"START\n").map_err(|e| e.to_string())?;
                            return Ok(stream);
                        }
                        Err(e)
                            if e.kind() == std::io::ErrorKind::WouldBlock
                                && Instant::now() < deadline =>
                        {
                            std::thread::sleep(Duration::from_millis(10))
                        }
                        Err(e) => return Err(format!("Network owner handshake failed: {e}")),
                    }
                }
            })();
            let _ = tx.send(result);
        });
        Ok((
            Self {
                connection,
                stream: None,
                directory,
                drained: false,
            },
            child,
        ))
    }

    pub fn drain(&mut self) -> Result<(), String> {
        if self.drained {
            return Ok(());
        }
        if self.stream.is_none() {
            self.stream = Some(
                self.connection
                    .recv_timeout(Duration::from_secs(5))
                    .map_err(|e| e.to_string())??,
            );
        }
        let stream = self.stream.as_mut().unwrap();
        stream
            .set_read_timeout(Some(Duration::from_secs(10)))
            .map_err(|e| e.to_string())?;
        // A worker can exit naturally, in which case its owner's ACK is already
        // queued and the write may fail. Only reading the exact ACK is proof.
        let _ = stream.write_all(b"STOP\n");
        let mut acknowledgement = [0; 8];
        stream
            .read_exact(&mut acknowledgement)
            .map_err(|e| format!("Network drain unconfirmed: {e}"))?;
        if &acknowledgement != b"DRAINED\n" {
            return Err("Network owner refused/incompletely drained".into());
        }
        self.drained = true;
        Ok(())
    }
}

impl Drop for NetworkOwner {
    fn drop(&mut self) {
        // Dropping the authenticated stream requests cleanup via EOF; it does not
        // manufacture evidence. A failed retirement keeps this object alive.
        let _ = std::fs::remove_file(self.directory.join("control"));
        let _ = std::fs::remove_dir(&self.directory);
    }
}

fn children() -> Result<Vec<i32>, String> {
    let mut children = Vec::new();
    for task in std::fs::read_dir("/proc/self/task").map_err(|e| e.to_string())? {
        let path = task.map_err(|e| e.to_string())?.path().join("children");
        let owned = match std::fs::read_to_string(path) {
            Ok(owned) => owned,
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => continue,
            Err(e) => return Err(e.to_string()),
        };
        for id in owned.split_whitespace() {
            children.push(id.parse::<i32>().map_err(|e| e.to_string())?);
        }
    }
    children.sort_unstable();
    children.dedup();
    Ok(children)
}

fn drain_children() -> Result<(), String> {
    let deadline = Instant::now() + Duration::from_secs(8);
    loop {
        loop {
            let result = unsafe { libc::waitpid(-1, std::ptr::null_mut(), libc::WNOHANG) };
            if result > 0 {
                continue;
            }
            if result < 0 {
                let error = std::io::Error::last_os_error();
                if error.raw_os_error() == Some(libc::ECHILD) {
                    return Ok(());
                }
                if error.raw_os_error() == Some(libc::EINTR) {
                    continue;
                }
                return Err(error.to_string());
            }
            break;
        }
        for pid in children()? {
            let Some(pid) = rustix::process::Pid::from_raw(pid) else {
                return Err("invalid owned child PID".into());
            };
            let handle =
                match rustix::process::pidfd_open(pid, rustix::process::PidfdFlags::empty()) {
                    Ok(handle) => handle,
                    Err(rustix::io::Errno::SRCH) => continue,
                    Err(error) => return Err(error.to_string()),
                };
            // Verify the kernel-owned child relation AFTER opening the stable
            // handle; a reused unrelated PID cannot receive a signal.
            if !children()?.contains(&pid.as_raw_nonzero().get()) {
                continue;
            }
            match rustix::process::pidfd_send_signal(&handle, rustix::process::Signal::KILL) {
                Ok(()) | Err(rustix::io::Errno::SRCH) => {}
                Err(error) => return Err(error.to_string()),
            }
        }
        if Instant::now() >= deadline {
            return Err("Network descendants have not exited/reaped".into());
        }
        std::thread::sleep(Duration::from_millis(10));
    }
}

fn run_owner(launch: Launch) -> Result<(), String> {
    if unsafe { libc::geteuid() } != 0 {
        return Err("Network lifetime owner must run after sudo escalation".into());
    }
    let valid_program = std::path::Path::new(&launch.program)
        .file_name()
        .is_some_and(|name| name == "yoyopod-network-host");
    if !valid_program && !launch.fixture {
        return Err("only the Network worker is supported".into());
    }
    if launch.token.is_empty() || launch.token.len() > 256 {
        return Err("invalid Network lifetime".into());
    }
    let mut stream = UnixStream::connect(&launch.socket).map_err(|e| e.to_string())?;
    let peer = credentials(&stream)?;
    if peer.uid != launch.uid || peer.pid as u32 != launch.supervisor {
        return Err("Network supervisor authentication failed".into());
    }
    stream
        .write_all(launch.token.as_bytes())
        .map_err(|e| e.to_string())?;
    stream
        .set_read_timeout(Some(Duration::from_secs(3)))
        .map_err(|e| e.to_string())?;
    let mut start = [0; 6];
    stream.read_exact(&mut start).map_err(|e| e.to_string())?;
    if &start != b"START\n" {
        return Err("Network start not authorized".into());
    }
    if unsafe { libc::prctl(libc::PR_SET_CHILD_SUBREAPER, 1, 0, 0, 0) } != 0 {
        return Err(std::io::Error::last_os_error().to_string());
    }
    let groups = launch
        .groups
        .iter()
        .map(u32::to_string)
        .collect::<Vec<_>>()
        .join(",");
    let caps = if launch.bind_cap {
        "-all,+net_bind_service"
    } else {
        "-all"
    };
    let executable = if launch.fixture {
        std::env::current_exe().map_err(|e| e.to_string())?
    } else {
        PathBuf::from(&launch.program)
    };
    let mut command = if launch.uid == 0 {
        Command::new(&executable)
    } else {
        let mut command = Command::new("/usr/bin/setpriv");
        command
            .arg("--reuid")
            .arg(launch.uid.to_string())
            .arg("--regid")
            .arg(launch.gid.to_string());
        if groups.is_empty() {
            command.arg("--clear-groups");
        } else {
            command.arg("--groups").arg(groups);
        }
        command
            .arg(format!("--inh-caps={caps}"))
            .arg(format!("--ambient-caps={caps}"))
            .arg("--")
            .arg(&executable);
        command.env("YOYOPOD_NETWORK_CREDENTIALS", serde_json::json!({"uid":launch.uid,"gid":launch.gid,"groups":launch.groups,"cap":if launch.bind_cap {0x400} else {0}}).to_string());
        command
    };
    if launch.fixture {
        command.arg("--network-owner-fixture-worker");
    } else {
        command.args(&launch.args);
    }
    command
        .env("YOYOPOD_WORKER_LIFETIME", &launch.token)
        .stdin(Stdio::inherit())
        .stdout(Stdio::inherit())
        .stderr(Stdio::inherit());
    stream
        .set_read_timeout(Some(Duration::from_millis(50)))
        .map_err(|e| e.to_string())?;
    let mut child = command.spawn().map_err(|e| e.to_string())?;
    let mut stop = false;
    loop {
        let mut byte = [0];
        match stream.read(&mut byte) {
            Ok(_) => stop = true,
            Err(e)
                if matches!(
                    e.kind(),
                    std::io::ErrorKind::TimedOut | std::io::ErrorKind::WouldBlock
                ) => {}
            Err(_) => stop = true,
        }
        if !matches!(child.try_wait(), Ok(None)) {
            stop = true;
        }
        if stop {
            match drain_children() {
                Ok(()) => {
                    stream.write_all(b"DRAINED\n").map_err(|e| e.to_string())?;
                    return Ok(());
                }
                Err(error) => {
                    eprintln!("Network ownership retained: {error}");
                    // Retain subreaper ownership and retry; never ACK uncertainty.
                    std::thread::sleep(Duration::from_millis(100));
                }
            }
        }
    }
}

pub fn dispatch_internal() -> anyhow::Result<bool> {
    let args: Vec<_> = std::env::args().skip(1).collect();
    match args.first().map(String::as_str) {
        Some("--network-owner-proof") => {
            use std::io::BufRead;
            let token = format!(
                "proof-{}-{}",
                std::process::id(),
                std::time::SystemTime::now()
                    .duration_since(std::time::UNIX_EPOCH)?
                    .as_nanos()
            );
            let (mut owner, mut child) =
                NetworkOwner::launch("fixture", &[], &token, true).map_err(anyhow::Error::msg)?;
            let stdout = child
                .stdout
                .take()
                .ok_or_else(|| anyhow::anyhow!("missing fixture output"))?;
            let (tx, rx) = mpsc::channel();
            std::thread::spawn(move || {
                for line in std::io::BufReader::new(stdout).lines() {
                    let Ok(line) = line else {
                        break;
                    };
                    let _ = tx.send(line);
                }
            });
            let line = rx.recv_timeout(Duration::from_secs(10))?;
            let event: serde_json::Value = serde_json::from_str(&line)?;
            anyhow::ensure!(
                event["type"] == "network.fixture_started",
                "fixture never reached real elevated descendant startup"
            );
            let mut handles = Vec::new();
            for field in ["root_pid", "leaf_pid"] {
                let pid = rustix::process::Pid::from_raw(
                    event["payload"][field]
                        .as_i64()
                        .ok_or_else(|| anyhow::anyhow!("missing fixture PID"))?
                        as i32,
                )
                .ok_or_else(|| anyhow::anyhow!("invalid fixture PID"))?;
                handles.push(rustix::process::pidfd_open(
                    pid,
                    rustix::process::PidfdFlags::empty(),
                )?);
            }
            owner.drain().map_err(anyhow::Error::msg)?;
            let deadline = Instant::now() + Duration::from_secs(3);
            while child.try_wait()?.is_none() {
                anyhow::ensure!(
                    Instant::now() < deadline,
                    "original sudo launcher not reaped"
                );
                std::thread::sleep(Duration::from_millis(10));
            }
            for handle in &handles {
                let mut fds = [rustix::event::PollFd::new(
                    handle,
                    rustix::event::PollFlags::IN,
                )];
                rustix::event::poll(&mut fds, Some(&rustix::event::Timespec::default()))?;
                anyhow::ensure!(
                    fds[0].revents().contains(rustix::event::PollFlags::IN),
                    "privileged descendant is still alive"
                );
            }
            println!(
                "{}",
                serde_json::json!({"network_owner_proof":"passed","actual_root_descendant":true,"sudo_token_stripped":event["payload"]["token_stripped"],"descendant_pidfds_exited":true,"guardian_echild_ack":true,"original_launcher_reaped":true})
            );
        }
        Some("--network-lifetime-owner") if args.len() == 2 => {
            run_owner(serde_json::from_str(&args[1])?).map_err(anyhow::Error::msg)?;
        }
        Some("--network-owner-fixture-worker") => {
            yoyopod_protocol::process::verify_network_credentials()?;
            let mut child = Command::new("/usr/bin/sudo")
                .args(["-n", "--"])
                .arg(std::env::current_exe()?)
                .arg("--network-owner-fixture-root")
                .spawn()?;
            let status = child.wait()?;
            anyhow::ensure!(status.success(), "fixture escalation failed");
        }
        Some("--network-owner-fixture-root") => {
            anyhow::ensure!(
                unsafe { libc::geteuid() } == 0,
                "fixture must actually run as root"
            );
            let mut child = Command::new(std::env::current_exe()?)
                .arg("--network-owner-fixture-leaf")
                .spawn()?;
            child.wait()?;
        }
        Some("--network-owner-fixture-leaf") => {
            // Deliberately leave the worker process group; only subreaper
            // ownership, not a group kill, can establish complete cleanup.
            anyhow::ensure!(
                unsafe { libc::setsid() } >= 0,
                "fixture session escape failed"
            );
            anyhow::ensure!(
                unsafe { libc::geteuid() } == 0,
                "fixture leaf is not actually privileged"
            );
            println!(
                "{}",
                serde_json::json!({"kind":"event","type":"network.fixture_started","payload":{"root_pid":unsafe { libc::getppid() },"leaf_pid":std::process::id(),"session_escaped":true,"token_stripped":std::env::var_os("YOYOPOD_WORKER_LIFETIME").is_none()}})
            );
            loop {
                std::thread::sleep(Duration::from_secs(1));
            }
        }
        _ => return Ok(false),
    }
    Ok(true)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn real_subreaper_drains_adopted_session_escape_to_echild() {
        const CHILD: &str = "YOYOPOD_TEST_SUBREAPER";
        if std::env::var_os(CHILD).is_none() {
            let status = Command::new(std::env::current_exe().unwrap())
                .args([
                    "--exact",
                    "network_owner::tests::real_subreaper_drains_adopted_session_escape_to_echild",
                    "--nocapture",
                ])
                .env(CHILD, "1")
                .status()
                .unwrap();
            assert!(status.success());
            return;
        }
        assert_eq!(
            unsafe { libc::prctl(libc::PR_SET_CHILD_SUBREAPER, 1, 0, 0, 0) },
            0
        );
        let mut parent = Command::new("/bin/sh")
            .args(["-c", "setsid sleep 60 & echo $!; wait"])
            .stdout(Stdio::piped())
            .spawn()
            .unwrap();
        let mut line = String::new();
        std::io::BufRead::read_line(
            &mut std::io::BufReader::new(parent.stdout.take().unwrap()),
            &mut line,
        )
        .unwrap();
        let pid = rustix::process::Pid::from_raw(line.trim().parse().unwrap()).unwrap();
        let leaf = rustix::process::pidfd_open(pid, rustix::process::PidfdFlags::empty()).unwrap();
        drain_children().unwrap();
        // The guardian's waitpid loop already reaped this retained Child.
        assert_eq!(
            parent.wait().unwrap_err().raw_os_error(),
            Some(libc::ECHILD)
        );
        assert!(children().unwrap().is_empty());
        assert_eq!(
            unsafe { libc::waitpid(-1, std::ptr::null_mut(), libc::WNOHANG) },
            -1
        );
        assert_eq!(
            std::io::Error::last_os_error().raw_os_error(),
            Some(libc::ECHILD)
        );
        use std::os::fd::AsRawFd;
        let mut poll = libc::pollfd {
            fd: leaf.as_raw_fd(),
            events: libc::POLLIN,
            revents: 0,
        };
        assert_eq!(unsafe { libc::poll(&mut poll, 1, 0) }, 1);
        assert_ne!(poll.revents & libc::POLLIN, 0);
    }
    #[test]
    fn denied_or_lost_control_never_becomes_drain_proof() {
        for denied in [true, false] {
            let (stream, mut peer) = UnixStream::pair().unwrap();
            let (_tx, connection) = mpsc::channel();
            let mut owner = NetworkOwner {
                connection,
                stream: Some(stream),
                directory: PathBuf::from("/nonexistent-test-owner"),
                drained: false,
            };
            std::thread::spawn(move || {
                if denied {
                    let mut stop = [0; 5];
                    peer.read_exact(&mut stop).unwrap();
                    peer.write_all(b"DENIED!\n").unwrap();
                }
            });
            assert!(owner.drain().is_err());
            assert!(!owner.drained);
        }
    }
    #[test]
    fn missing_registration_never_becomes_drain_proof() {
        let (tx, connection) = mpsc::channel();
        tx.send(Err("sudo authentication/registration unavailable".into()))
            .unwrap();
        let mut owner = NetworkOwner {
            connection,
            stream: None,
            directory: PathBuf::from("/nonexistent-test-owner"),
            drained: false,
        };
        assert!(owner.drain().is_err());
        assert!(!owner.drained);
    }
}
