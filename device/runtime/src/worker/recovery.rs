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

impl WorkerSupervisor {
    pub fn recover_worker(&mut self, domain: WorkerDomain) -> Result<RecoveryStatus, String> {
        self.recover_with(domain, reap_owned_helpers)
    }

    fn recover_with(
        &mut self,
        domain: WorkerDomain,
        reap: impl FnOnce(&str) -> Result<(), String> + Send + 'static,
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
                    if worker
                        .child
                        .try_wait()
                        .map_err(|e| e.to_string())?
                        .is_none()
                    {
                        worker.child.kill().map_err(|e| e.to_string())?;
                    }
                    worker.child.wait().map_err(|e| e.to_string())?;
                    reap(&worker.lifetime_token)
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
        if found && !worker_has_exited(worker) {
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
fn reap_owned_helpers(_: &str) -> Result<(), String> {
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
            .recover_with(WorkerDomain::Media, |_| {
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
            .recover_with(WorkerDomain::Media, move |seen| {
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
