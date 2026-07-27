use std::collections::{HashSet, VecDeque};
use std::fs::{self, OpenOptions};
use std::io::Write;
#[cfg(unix)]
use std::os::unix::fs::{OpenOptionsExt, PermissionsExt};
use std::path::PathBuf;
use std::time::{SystemTime, UNIX_EPOCH};

use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};
use serde_json::Value;

pub const MAX_LOCATION_OUTBOX_AGE_SECONDS: u64 = 24 * 60 * 60;
pub const MAX_LOCATION_OUTBOX_FIXES: usize = 3_000;

#[derive(Debug, Clone, Serialize, Deserialize)]
struct OutboxEntry {
    fix_id: String,
    queued_at: u64,
    message: Value,
}

#[derive(Debug)]
pub struct LocationOutbox {
    path: PathBuf,
    entries: VecDeque<OutboxEntry>,
    sent_in_session: HashSet<String>,
}

impl LocationOutbox {
    pub fn open(path: PathBuf) -> Result<Self> {
        let entries = if path.exists() {
            let raw = fs::read_to_string(&path)
                .with_context(|| format!("read location outbox {}", path.display()))?;
            serde_json::from_str::<VecDeque<OutboxEntry>>(&raw).context("parse location outbox")?
        } else {
            VecDeque::new()
        };
        let mut outbox = Self {
            path,
            entries,
            sent_in_session: HashSet::new(),
        };
        if outbox.prune(epoch_seconds()) {
            outbox.persist()?;
        }
        Ok(outbox)
    }

    pub fn empty(path: PathBuf) -> Self {
        Self {
            path,
            entries: VecDeque::new(),
            sent_in_session: HashSet::new(),
        }
    }

    pub fn enqueue(&mut self, fix_id: String, message: Value) -> Result<()> {
        let now = epoch_seconds();
        self.prune(now);
        if self.entries.iter().any(|entry| entry.fix_id == fix_id) {
            return Ok(());
        }
        self.entries.push_back(OutboxEntry {
            fix_id,
            queued_at: now,
            message,
        });
        while self.entries.len() > MAX_LOCATION_OUTBOX_FIXES {
            if let Some(removed) = self.entries.pop_front() {
                self.sent_in_session.remove(&removed.fix_id);
            }
        }
        self.persist()
    }

    pub fn begin_connection(&mut self) {
        self.sent_in_session.clear();
    }

    pub fn pending_messages(&mut self) -> Result<Vec<(String, String)>> {
        if self.prune(epoch_seconds()) {
            self.persist()?;
        }
        let now = epoch_seconds();
        self.entries
            .iter()
            .filter(|entry| !self.sent_in_session.contains(&entry.fix_id))
            .map(|entry| {
                let mut message = entry.message.clone();
                if now.saturating_sub(entry.queued_at) >= 30 {
                    if let Some(payload) = message.get_mut("payload") {
                        if payload.get("reason").and_then(Value::as_str) == Some("periodic") {
                            payload["reason"] = Value::String("backfill".to_string());
                        }
                    }
                }
                serde_json::to_string(&message)
                    .map(|encoded| (entry.fix_id.clone(), encoded))
                    .context("encode queued location fix")
            })
            .collect()
    }

    pub fn mark_sent(&mut self, fix_id: &str) {
        self.sent_in_session.insert(fix_id.to_string());
    }

    pub fn acknowledge(&mut self, fix_id: &str) -> Result<bool> {
        let before = self.entries.len();
        self.entries.retain(|entry| entry.fix_id != fix_id);
        self.sent_in_session.remove(fix_id);
        if self.entries.len() == before {
            return Ok(false);
        }
        self.persist()?;
        Ok(true)
    }

    #[cfg(test)]
    pub fn len(&self) -> usize {
        self.entries.len()
    }

    #[cfg(test)]
    pub fn is_empty(&self) -> bool {
        self.entries.is_empty()
    }

    fn prune(&mut self, now: u64) -> bool {
        let before = self.entries.len();
        self.entries
            .retain(|entry| now.saturating_sub(entry.queued_at) <= MAX_LOCATION_OUTBOX_AGE_SECONDS);
        self.sent_in_session
            .retain(|fix_id| self.entries.iter().any(|entry| &entry.fix_id == fix_id));
        before != self.entries.len()
    }

    fn persist(&self) -> Result<()> {
        if let Some(parent) = self.path.parent() {
            fs::create_dir_all(parent)
                .with_context(|| format!("create location outbox {}", parent.display()))?;
        }
        let temporary = self.path.with_extension("tmp");
        let mut options = OpenOptions::new();
        options.create(true).truncate(true).write(true);
        #[cfg(unix)]
        options.mode(0o600);
        let mut file = options
            .open(&temporary)
            .with_context(|| format!("open location outbox {}", temporary.display()))?;
        serde_json::to_writer(&mut file, &self.entries).context("encode location outbox")?;
        file.write_all(b"\n").context("finish location outbox")?;
        file.sync_all().context("sync location outbox")?;
        #[cfg(unix)]
        fs::set_permissions(&temporary, fs::Permissions::from_mode(0o600))
            .context("secure location outbox")?;
        fs::rename(&temporary, &self.path).context("replace location outbox")?;
        Ok(())
    }
}

fn epoch_seconds() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_secs())
        .unwrap_or_default()
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn survives_restart_and_removes_only_after_ack() {
        let directory = tempfile::tempdir().unwrap();
        let path = directory.path().join("location.json");
        let mut outbox = LocationOutbox::open(path.clone()).unwrap();
        outbox
            .enqueue(
                "fix-1".to_string(),
                json!({"payload": {"fixId": "fix-1", "reason": "periodic"}}),
            )
            .unwrap();
        outbox.mark_sent("fix-1");

        let mut restarted = LocationOutbox::open(path).unwrap();
        assert_eq!(restarted.len(), 1);
        assert_eq!(restarted.pending_messages().unwrap().len(), 1);
        assert!(restarted.acknowledge("fix-1").unwrap());
        assert!(restarted.is_empty());
    }

    #[cfg(unix)]
    #[test]
    fn persisted_outbox_is_owner_only() {
        let directory = tempfile::tempdir().unwrap();
        let path = directory.path().join("location.json");
        let mut outbox = LocationOutbox::open(path.clone()).unwrap();
        outbox
            .enqueue("fix-1".to_string(), json!({"payload": {"fixId": "fix-1"}}))
            .unwrap();
        assert_eq!(
            fs::metadata(path).unwrap().permissions().mode() & 0o777,
            0o600
        );
    }
}
