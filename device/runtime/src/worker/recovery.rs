//! Recovery work owns retained records; the loop only polls, never joins it.
use super::*;
use std::sync::{Arc, Mutex};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RecoveryStatus {
    Pending,
    Ready,
}

pub(super) struct Retirement {
    worker: Arc<Mutex<WorkerProcess>>,
    result: Option<Receiver<Result<(), String>>>,
}

impl Retirement {
    pub(super) fn request_stop(&self) {
        // Never join a census thread on the shutdown path. If it owns the lock,
        // it is already killing/reaping this child; otherwise request kill now.
        if let Ok(mut worker) = self.worker.try_lock() {
            #[cfg(target_os = "linux")]
            if worker.network_owner.is_some() {
                // Retirement retains the privileged control owner and original
                // launcher until authenticated drain. Never kill sudo first.
                return;
            }
            if matches!(worker.child.try_wait(), Ok(None)) {
                let _ = worker.child.kill();
            }
        }
    }
}

impl WorkerSupervisor {
    pub fn recover_worker(&mut self, domain: WorkerDomain) -> Result<RecoveryStatus, String> {
        self.recover_with(domain, reap_owned_helpers)
    }

    fn recover_with(
        &mut self,
        domain: WorkerDomain,
        reap: impl FnOnce(&str, Option<u32>, Option<u64>) -> Result<(), String> + Send + 'static,
    ) -> Result<RecoveryStatus, String> {
        if !self.specs.contains_key(&domain) {
            return Err("worker has no startup specification".into());
        }
        if self.starting.contains_key(&domain) {
            return Ok(RecoveryStatus::Pending);
        }
        if !self.retiring.contains_key(&domain) {
            let worker = self
                .workers
                .remove(&domain)
                .ok_or("worker record missing")?;
            self.retiring.insert(
                domain,
                Retirement {
                    worker: Arc::new(Mutex::new(worker)),
                    result: None,
                },
            );
        }
        let retirement = self.retiring.get_mut(&domain).unwrap();
        if retirement.result.is_some() {
            return Ok(RecoveryStatus::Pending);
        }
        let worker = Arc::clone(&retirement.worker);
        let (tx, rx) = mpsc::channel();
        // The supervisor retains the Arc even on thread failure or poisoned lock.
        thread::Builder::new()
            .name(format!("retire-{}", domain.as_str()))
            .spawn(move || {
                let result = (|| {
                    let mut worker = worker.lock().map_err(|_| "retiring worker lock poisoned")?;
                    #[cfg(target_os = "linux")]
                    if let Some(owner) = worker.network_owner.as_mut() {
                        // The privileged original owner must prove ECHILD BEFORE
                        // reaping its sudo launcher. No token census crosses sudo.
                        owner.drain()?;
                        let deadline = Instant::now() + Duration::from_secs(2);
                        while worker
                            .child
                            .try_wait()
                            .map_err(|e| e.to_string())?
                            .is_none()
                        {
                            if Instant::now() >= deadline {
                                return Err("drained Network launcher not reaped".into());
                            }
                            thread::sleep(Duration::from_millis(10));
                        }
                        return Ok(());
                    }
                    if worker
                        .child
                        .try_wait()
                        .map_err(|e| e.to_string())?
                        .is_none()
                    {
                        worker.child.kill().map_err(|e| e.to_string())?;
                    }
                    worker.child.wait().map_err(|e| e.to_string())?;
                    reap(
                        &worker.lifetime_token,
                        worker.owner_uid,
                        worker.runtime_start,
                    )
                })();
                let _ = tx.send(result);
            })
            .map_err(|e| e.to_string())?;
        retirement.result = Some(rx);
        Ok(RecoveryStatus::Pending)
    }

    pub fn poll_recovery(&mut self, domain: WorkerDomain) -> Result<RecoveryStatus, String> {
        if let Some(retirement) = self.retiring.get_mut(&domain) {
            let receiver = retirement
                .result
                .as_ref()
                .ok_or("retirement requires retry")?;
            let result = match receiver.try_recv() {
                Ok(result) => result,
                Err(mpsc::TryRecvError::Empty) => return Ok(RecoveryStatus::Pending),
                Err(mpsc::TryRecvError::Disconnected) => Err("retirement thread lost".into()),
            };
            retirement.result = None;
            result?; // Keep the child AND token on every error.
            self.retiring.remove(&domain);
            let spec = self.specs[&domain].clone();
            if !self.start(spec) {
                return Err("replacement worker could not start".into());
            }
            self.starting
                .insert(domain, Instant::now() + Duration::from_secs(3));
        }
        let deadline = *self
            .starting
            .get(&domain)
            .ok_or("no recovery in progress")?;
        let worker = self
            .workers
            .get_mut(&domain)
            .ok_or("replacement record missing")?;
        let ready = format!("{}.ready", domain.as_str());
        let mut found = false;
        for message in drain_receiver(&worker.messages, MAX_PRESERVED_READY_MESSAGES) {
            if message.message_type == ready {
                found = true;
            } else {
                preserve_ready_backlog(&mut worker.pending_messages, message);
            }
        }
        if found && !worker_has_exited(worker) && verify_worker_credentials(worker).is_ok() {
            self.starting.remove(&domain);
            return Ok(RecoveryStatus::Ready);
        }
        if Instant::now() >= deadline || worker_has_exited(worker) {
            self.starting.remove(&domain);
            return Err("replacement worker readiness failed".into());
        }
        Ok(RecoveryStatus::Pending)
    }
}

#[cfg(target_os = "linux")]
mod helpers;
#[cfg(target_os = "linux")]
use helpers::reap_owned_helpers;
#[cfg(not(target_os = "linux"))]
fn reap_owned_helpers(_: &str, _: Option<u32>, _: Option<u64>) -> Result<(), String> {
    Err("worker resource reconciliation requires Linux pidfds/procfs".into())
}

#[cfg(all(test, target_os = "linux"))]
mod tests {
    use super::*;
    fn finish(supervisor: &mut WorkerSupervisor) -> Result<RecoveryStatus, String> {
        let deadline = Instant::now() + Duration::from_secs(4);
        loop {
            let result = supervisor.poll_recovery(WorkerDomain::Media);
            if result != Ok(RecoveryStatus::Pending) {
                return result;
            }
            assert!(Instant::now() < deadline);
            thread::sleep(Duration::from_millis(1));
        }
    }
    #[test]
    fn failed_reap_retains_worker_for_retry() {
        let mut supervisor = WorkerSupervisor::default();
        assert!(supervisor.start(WorkerSpec::new(
            WorkerDomain::Media,
            "/bin/sleep",
            ["60".into()]
        )));
        let token = supervisor.workers[&WorkerDomain::Media]
            .lifetime_token
            .clone();
        supervisor
            .recover_with(WorkerDomain::Media, |_, _, _| {
                Err("injected census failure".into())
            })
            .unwrap();
        assert!(finish(&mut supervisor).is_err());
        assert_eq!(
            supervisor.retiring[&WorkerDomain::Media]
                .worker
                .lock()
                .unwrap()
                .lifetime_token,
            token
        );
        let (tx, rx) = mpsc::channel();
        supervisor
            .recover_with(WorkerDomain::Media, move |seen, _, _| {
                tx.send(seen.to_owned()).unwrap();
                Err("still uncertain".into())
            })
            .unwrap();
        assert!(finish(&mut supervisor).is_err());
        assert_eq!(rx.recv().unwrap(), token);
        assert!(supervisor.retiring.contains_key(&WorkerDomain::Media));
        assert!(!supervisor.workers.contains_key(&WorkerDomain::Media));
    }
}

/// Only a non-root, single-UID process with no current/inheritable/ambient
/// capabilities can establish this boundary. NNP then prevents setuid/file-cap
/// exec from escaping it; privileged launches require the complete census.
#[cfg(target_os = "linux")]
fn unprivileged_owner(status: &str) -> Result<Option<u32>, String> {
    let fields: HashMap<_, _> = status
        .lines()
        .filter_map(|line| line.split_once(':'))
        .collect();
    let uids = fields
        .get("Uid")
        .ok_or("missing process UID proof")?
        .split_whitespace()
        .map(str::parse::<u32>)
        .collect::<Result<Vec<_>, _>>()
        .map_err(|e| e.to_string())?;
    if uids.len() != 4 {
        return Err("incomplete process UID proof".into());
    }
    let mut privileged = uids[0] == 0 || uids.iter().any(|uid| *uid != uids[0]);
    for name in ["CapInh", "CapPrm", "CapEff", "CapAmb"] {
        let value = fields.get(name).ok_or("missing process capability proof")?;
        privileged |= u64::from_str_radix(value.trim(), 16).map_err(|e| e.to_string())? != 0;
    }
    Ok((!privileged).then_some(uids[0]))
}

pub(super) fn worker_command(
    program: &str,
    domain: WorkerDomain,
) -> Result<(Command, Option<u32>, Option<u64>), String> {
    #[cfg(target_os = "linux")]
    {
        let status = std::fs::read_to_string("/proc/self/status").map_err(|e| e.to_string())?;
        let runtime_start = helpers::runtime_birth(&status)?;
        let owner = if matches!(
            domain,
            WorkerDomain::Media | WorkerDomain::Voip | WorkerDomain::Voice
        ) {
            audio_owner(&status)?
        } else {
            None
        };
        if let Some(uid) = owner {
            // setpriv execs the worker in place: Child/pidfd identity is unchanged.
            // Missing executable or rejected NNP setup fails startup, never falls back.
            ordinary_executable("/usr/bin/setpriv")?;
            ordinary_executable(program)?;
            let mut command = Command::new("/usr/bin/setpriv");
            command.args([
                "--inh-caps=-all",
                "--ambient-caps=-all",
                "--no-new-privs",
                "--",
                program,
            ]);
            command.env("YOYOPOD_AUDIO_OWNER_UID", uid.to_string());
            return Ok((command, owner, Some(runtime_start)));
        }
        Ok((Command::new(program), None, Some(runtime_start)))
    }
    #[cfg(not(target_os = "linux"))]
    {
        let _ = domain;
        Ok((Command::new(program), None, None))
    }
}

#[cfg(target_os = "linux")]
fn audio_owner(status: &str) -> Result<Option<u32>, String> {
    let uid = status
        .lines()
        .find_map(|line| line.strip_prefix("Uid:"))
        .ok_or("missing UIDs")?
        .split_whitespace()
        .map(str::parse::<u32>)
        .collect::<Result<Vec<_>, _>>()
        .map_err(|e| e.to_string())?;
    if uid.len() != 4 {
        return Err("incomplete UIDs".into());
    }
    if uid[0] == 0 || uid.iter().any(|id| *id != uid[0]) {
        return Ok(None);
    }
    Ok(Some(uid[0]))
}

#[cfg(target_os = "linux")]
fn ordinary_executable(program: &str) -> Result<(), String> {
    use std::os::unix::fs::MetadataExt;
    let metadata = std::fs::metadata(program).map_err(|e| e.to_string())?;
    if !metadata.is_file() || metadata.mode() & 0o6000 != 0 {
        return Err("audio executable must be an ordinary non-setid file".into());
    }
    let proof = Command::new("/usr/sbin/getcap")
        .arg(program)
        .output()
        .map_err(|e| e.to_string())?;
    if !proof.status.success() || !proof.stdout.is_empty() {
        return Err("audio executable file capabilities could not be excluded".into());
    }
    Ok(())
}

pub(super) fn verify_worker_credentials(worker: &mut WorkerProcess) -> Result<(), String> {
    #[cfg(target_os = "linux")]
    if let Some(owner) = worker.owner_uid.take() {
        let status = std::fs::read_to_string(format!("/proc/{}/status", worker.child.id()))
            .map_err(|e| e.to_string())?;
        if unprivileged_owner(&status)? != Some(owner)
            || !status.lines().any(|line| line == "NoNewPrivs:\t1")
        {
            return Err("audio worker post-exec credential proof failed".into());
        }
        worker.owner_uid = Some(owner);
    }
    #[cfg(not(target_os = "linux"))]
    let _ = worker;
    Ok(())
}

#[cfg(all(test, target_os = "linux"))]
mod credentials_tests {
    use super::*;
    #[test]
    fn uid_boundary_requires_all_credentials_and_zero_gain_capabilities() {
        let status = "Uid:\t1000 1000 1000 1000\nCapInh:\t0\nCapPrm:\t0\nCapEff:\t0\nCapAmb:\t0\n";
        assert_eq!(unprivileged_owner(status).unwrap(), Some(1000));
        for field in ["CapInh", "CapPrm", "CapEff", "CapAmb"] {
            assert_eq!(
                unprivileged_owner(
                    &status.replace(&format!("{field}:\t0"), &format!("{field}:\t1"))
                )
                .unwrap(),
                None
            );
        }
        assert_eq!(
            unprivileged_owner(&status.replace("1000 1000 1000 1000", "1000 1000 0 1000")).unwrap(),
            None
        );
        assert_eq!(
            unprivileged_owner(&status.replace("1000", "0")).unwrap(),
            None
        );
        assert!(unprivileged_owner("Uid: 1000").is_err());
    }
    #[test]
    fn privilege_escalating_domains_do_not_receive_uid_exclusion() {
        for domain in [
            WorkerDomain::Network,
            WorkerDomain::Power,
            WorkerDomain::Ui,
            WorkerDomain::Cloud,
        ] {
            let (command, owner, birth) = worker_command("/bin/true", domain).unwrap();
            assert_eq!(command.get_program(), "/bin/true");
            assert_eq!(owner, None);
            assert!(birth.is_some());
        }
    }
    #[test]
    fn worker_launch_binds_no_new_privileges_before_exec() {
        let (mut command, owner, _) = worker_command("/bin/cat", WorkerDomain::Media).unwrap();
        let output = command.arg("/proc/self/status").output().unwrap();
        assert!(output.status.success());
        if owner.is_some() {
            let status = String::from_utf8(output.stdout).unwrap();
            assert!(status.lines().any(|line| line == "NoNewPrivs:\t1"));
            assert_eq!(unprivileged_owner(&status).unwrap(), owner);
        }
    }
}
