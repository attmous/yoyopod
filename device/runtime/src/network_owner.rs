//! Privileged owner for a single Network lifetime, using existing sudo authority.
//! The owner is a subreaper, not a process-name/ancestry census. Only its kernel
//! children (including adopted descendants) can be signalled. ECHILD proves drain.
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
use std::io::{Read, Write};
use std::os::unix::ffi::{OsStrExt, OsStringExt};
use std::os::unix::fs::{DirBuilderExt, PermissionsExt};
use std::os::unix::io::AsRawFd;
use std::os::unix::net::{UnixListener, UnixStream};
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::mpsc::{self, Receiver};
use std::time::{Duration, Instant};

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
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
    environment: NetworkEnvironment,
    fixture: bool,
}

// Network config.rs and audio.rs are the supported configuration readers.
// Never carry PATH, loader variables, or arbitrary caller-selected names across
// sudo. Values retain absent/empty/non-UTF8 semantics of those actual readers.
const NETWORK_ENVIRONMENT: [&str; 16] = [
    "YOYOPOD_CONFIG_BOARD",
    "YOYOPOD_NETWORK_ENABLED",
    "YOYOPOD_MODEM_PORT",
    "YOYOPOD_MODEM_PPP_PORT",
    "YOYOPOD_MODEM_BAUD",
    "YOYOPOD_MODEM_APN",
    "YOYOPOD_MODEM_GPS_ENABLED",
    "YOYOPOD_MODEM_PPP_TIMEOUT",
    "YOYOPOD_ALSA_DEVICE",
    "YOYOPOD_LOCAL_CAPTURE_DEVICE",
    "YOYOPOD_PLAYBACK_DEVICE",
    "YOYOPOD_RINGER_DEVICE",
    "YOYOPOD_CAPTURE_DEVICE",
    "YOYOPOD_MEDIA_DEVICE",
    "YOYOPOD_AUDIO_SETTINGS_FILE",
    "YOYOPOD_ASOUND_CONFIG",
];

#[derive(Serialize, Deserialize)]
#[serde(transparent)]
struct NetworkEnvironment(BTreeMap<String, Option<Vec<u8>>>);

impl NetworkEnvironment {
    fn capture(mut read: impl FnMut(&str) -> Option<std::ffi::OsString>) -> Self {
        Self(
            NETWORK_ENVIRONMENT
                .into_iter()
                .map(|name| {
                    (
                        name.to_owned(),
                        read(name).map(|value| value.as_bytes().to_vec()),
                    )
                })
                .collect(),
        )
    }

    fn apply(&self, command: &mut Command) -> Result<(), String> {
        if self.0.len() != NETWORK_ENVIRONMENT.len()
            || self
                .0
                .keys()
                .any(|name| !NETWORK_ENVIRONMENT.contains(&name.as_str()))
            || self.0.values().flatten().any(|value| value.contains(&0))
        {
            return Err("invalid Network configuration environment snapshot".into());
        }
        for (name, value) in &self.0 {
            if let Some(value) = value {
                command.env(name, std::ffi::OsString::from_vec(value.clone()));
            } else {
                // Absence is explicit, so guardian/sudo defaults cannot replace
                // an unset supervisor override with a different value.
                command.env_remove(name);
            }
        }
        Ok(())
    }
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
            environment: NetworkEnvironment::capture(|name| std::env::var_os(name)),
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

fn worker_command(launch: &Launch) -> Result<Command, String> {
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
    launch.environment.apply(&mut command)?;
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
    Ok(command)
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
    let mut command = worker_command(&launch)?;
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
    fn network_child_builder_restores_supported_overrides_after_env_reset() {
        for uid in [1000, 0] {
            let launch: Launch = serde_json::from_value(serde_json::json!({
                "socket":"/unused", "token":"test", "supervisor":1,
                "uid":uid, "gid":1000, "groups":[44,1000], "bind_cap":true,
                "program":"/usr/bin/yoyopod-network-host", "args":["--config-dir","config"],
                "fixture":false,
                "environment": {
                    "YOYOPOD_CONFIG_BOARD": [114,112,105],
                    "YOYOPOD_NETWORK_ENABLED": [116,114,117,101],
                    "YOYOPOD_MODEM_PORT": [47,100,101,118,47,116,116,121,85,83,66,50],
                    "YOYOPOD_MODEM_PPP_PORT": null,
                    "YOYOPOD_MODEM_BAUD": [49,49,53,50,48,48],
                    "YOYOPOD_MODEM_APN": [116,101,115,116,46,97,112,110],
                    "YOYOPOD_MODEM_GPS_ENABLED": [102,97,108,115,101],
                    "YOYOPOD_MODEM_PPP_TIMEOUT": [54,48],
                    "YOYOPOD_ALSA_DEVICE": [104,119,58,50],
                    "YOYOPOD_LOCAL_CAPTURE_DEVICE": [],
                    "YOYOPOD_PLAYBACK_DEVICE": [65,76,83,65,58,32,120],
                    "YOYOPOD_RINGER_DEVICE": [65,76,83,65,58,32,114],
                    "YOYOPOD_CAPTURE_DEVICE": [65,76,83,65,58,32,99],
                    "YOYOPOD_MEDIA_DEVICE": [65,76,83,65,58,32,109],
                    "YOYOPOD_AUDIO_SETTINGS_FILE": [],
                    "YOYOPOD_ASOUND_CONFIG": [47,116,109,112,47,255]
                }
            }))
            .unwrap();
            let command = worker_command(&launch).unwrap();
            let env: std::collections::BTreeMap<_, _> = command.get_envs().collect();
            for (key, expected) in [
                ("YOYOPOD_CONFIG_BOARD", Some("rpi")),
                ("YOYOPOD_NETWORK_ENABLED", Some("true")),
                ("YOYOPOD_MODEM_PORT", Some("/dev/ttyUSB2")),
                ("YOYOPOD_MODEM_PPP_PORT", None),
                ("YOYOPOD_MODEM_BAUD", Some("115200")),
                ("YOYOPOD_MODEM_APN", Some("test.apn")),
                ("YOYOPOD_MODEM_GPS_ENABLED", Some("false")),
                ("YOYOPOD_MODEM_PPP_TIMEOUT", Some("60")),
                ("YOYOPOD_ALSA_DEVICE", Some("hw:2")),
                ("YOYOPOD_LOCAL_CAPTURE_DEVICE", Some("")),
                ("YOYOPOD_PLAYBACK_DEVICE", Some("ALSA: x")),
                ("YOYOPOD_RINGER_DEVICE", Some("ALSA: r")),
                ("YOYOPOD_CAPTURE_DEVICE", Some("ALSA: c")),
                ("YOYOPOD_MEDIA_DEVICE", Some("ALSA: m")),
                ("YOYOPOD_AUDIO_SETTINGS_FILE", Some("")),
            ] {
                assert_eq!(
                    env.get(std::ffi::OsStr::new(key)),
                    Some(&expected.map(std::ffi::OsStr::new)),
                    "{key} at child boundary, uid={uid}"
                );
            }
            use std::os::unix::ffi::OsStrExt;
            assert_eq!(
                env.get(std::ffi::OsStr::new("YOYOPOD_ASOUND_CONFIG"))
                    .unwrap()
                    .unwrap()
                    .as_bytes(),
                b"/tmp/\xff"
            );
            assert!(!env.contains_key(std::ffi::OsStr::new("PATH")));
            assert!(!env.contains_key(std::ffi::OsStr::new("LD_PRELOAD")));
            assert_eq!(
                command.get_program(),
                if uid == 0 {
                    "/usr/bin/yoyopod-network-host"
                } else {
                    "/usr/bin/setpriv"
                }
            );
        }
    }

    #[test]
    fn network_environment_snapshot_preserves_bytes_and_rejects_unlisted_or_incomplete_input() {
        let captured = NetworkEnvironment::capture(|name| match name {
            "YOYOPOD_MODEM_APN" => Some("  custom.apn  ".into()),
            "YOYOPOD_AUDIO_SETTINGS_FILE" => Some("".into()),
            "YOYOPOD_ASOUND_CONFIG" => Some(std::ffi::OsString::from_vec(b"/tmp/\xff".to_vec())),
            _ => None,
        });
        let encoded = serde_json::to_string(&captured).unwrap();
        let mut decoded: NetworkEnvironment = serde_json::from_str(&encoded).unwrap();
        let mut child = Command::new("/usr/bin/env");
        child.env_clear().arg("-0"); // Model the cleared environment after sudo.
        decoded.apply(&mut child).unwrap();
        let output = child.output().unwrap();
        assert!(output.status.success());
        let values: Vec<_> = output.stdout.split(|byte| *byte == 0).collect();
        assert!(values.contains(&b"YOYOPOD_MODEM_APN=  custom.apn  ".as_slice()));
        assert!(values.contains(&b"YOYOPOD_AUDIO_SETTINGS_FILE=".as_slice()));
        assert!(values.contains(&b"YOYOPOD_ASOUND_CONFIG=/tmp/\xff".as_slice()));
        assert!(!values
            .iter()
            .any(|value| value.starts_with(b"YOYOPOD_NETWORK_ENABLED=")));
        for key in [
            "PATH",
            "LD_PRELOAD",
            "YOYOPOD_NETWORK_CREDENTIALS",
            "UNKNOWN",
        ] {
            decoded.0.insert(key.into(), Some(b"injected".to_vec()));
            assert!(decoded.apply(&mut Command::new("/bin/true")).is_err());
            decoded.0.remove(key);
        }
        decoded
            .0
            .insert("YOYOPOD_MODEM_APN".into(), Some(b"nul\0value".to_vec()));
        assert!(decoded.apply(&mut Command::new("/bin/true")).is_err());
        decoded.0.remove("YOYOPOD_MODEM_APN");
        assert!(decoded.apply(&mut Command::new("/bin/true")).is_err());
    }

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
