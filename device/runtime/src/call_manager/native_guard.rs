//! Durable fail-closed marker for GSM operations that can outlive runtime/MM clients.
//! This is not history: it contains no caller identity, address, or conversation data.
use super::SessionKey;
use serde::{Deserialize, Serialize};
use std::{
    io::Write,
    path::{Path, PathBuf},
};

#[derive(Serialize, Deserialize)]
struct DirtyMarker {
    version: u8,
    key: SessionKey,
    native_owner: Option<String>,
}

#[derive(Debug, Clone, Default)]
pub struct NativeOperationGuard {
    path: Option<PathBuf>,
    dirty: bool,
    quarantined: bool,
    pending: Vec<SessionKey>,
}
impl NativeOperationGuard {
    /// An empty path is the in-memory harness mode; production always configures a path.
    pub fn load(path: &Path) -> (Self, Option<String>) {
        if path.as_os_str().is_empty() {
            return (Self::default(), None);
        }
        let mut guard = Self {
            path: Some(path.to_owned()),
            ..Default::default()
        };
        match std::fs::read(path) {
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => (guard, None),
            result => {
                guard.dirty = true;
                guard.quarantined = true;
                let reason = match result {
                    Ok(bytes) => match serde_json::from_slice::<DirtyMarker>(&bytes) {
                        Ok(marker)
                            if marker.version == 1
                                && marker.key.transport == super::CallTransport::Gsm =>
                        {
                            "unfinished GSM native operation requires verified recovery".to_owned()
                        }
                        _ => "invalid GSM recovery marker; call admission quarantined".into(),
                    },
                    Err(_) => "unreadable GSM recovery marker; call admission quarantined".into(),
                };
                (guard, Some(reason))
            }
        }
    }
    pub fn blocked(&self) -> bool {
        self.quarantined || !self.pending.is_empty()
    }
    pub fn quarantined(&self) -> bool {
        self.quarantined
    }
    pub fn quarantine(&mut self) {
        self.quarantined = true;
    }

    /// MUST succeed before dispatch. Already-durable dirty state covers additional keys;
    /// in-memory pending keys still prevent secondary cleanup clearing another operation.
    pub fn before_dispatch(
        &mut self,
        key: &SessionKey,
        native_owner: Option<&str>,
    ) -> Result<(), String> {
        if self.quarantined {
            return Err("native operation recovery is quarantined".into());
        }
        if !self.dirty {
            if let Some(path) = &self.path {
                if let Err(error) = write_dirty(
                    path,
                    &DirtyMarker {
                        version: 1,
                        key: key.clone(),
                        native_owner: native_owner.map(str::to_owned),
                    },
                ) {
                    self.quarantined = true;
                    return Err(error);
                }
            }
            self.dirty = true;
        }
        if !self.pending.contains(key) {
            self.pending.push(key.clone());
        }
        Ok(())
    }
    /// Only a generation-fenced terminal fact from the surviving native actor qualifies.
    pub fn terminal(&mut self, key: &SessionKey) {
        self.pending.retain(|pending| pending != key);
    }
    pub fn clear_if_released(&mut self, resources_released: bool) -> Result<(), String> {
        if !self.dirty || self.quarantined || !self.pending.is_empty() || !resources_released {
            return Ok(());
        }
        if let Some(path) = &self.path {
            std::fs::remove_file(path).map_err(|e| format!("clear native recovery marker: {e}"))?;
            sync_parent(path)?;
        }
        self.dirty = false;
        Ok(())
    }
}

fn write_dirty(path: &Path, marker: &DirtyMarker) -> Result<(), String> {
    let parent = path
        .parent()
        .filter(|p| !p.as_os_str().is_empty())
        .unwrap_or(Path::new("."));
    std::fs::create_dir_all(parent).map_err(|e| e.to_string())?;
    // Persist newly created ancestor directory entries too.
    #[cfg(target_os = "linux")]
    for ancestor in parent.ancestors() {
        if !ancestor.as_os_str().is_empty() {
            std::fs::File::open(ancestor)
                .and_then(|f| f.sync_all())
                .map_err(|e| e.to_string())?;
        }
    }
    static SERIAL: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
    let temporary = parent.join(format!(
        ".native-call-{}-{}.tmp",
        std::process::id(),
        SERIAL.fetch_add(1, std::sync::atomic::Ordering::Relaxed)
    ));
    let result = (|| {
        let mut options = std::fs::OpenOptions::new();
        options.write(true).create_new(true);
        #[cfg(unix)]
        {
            use std::os::unix::fs::OpenOptionsExt;
            options.mode(0o600);
        }
        let mut file = options.open(&temporary).map_err(|e| e.to_string())?;
        file.write_all(&serde_json::to_vec(marker).map_err(|e| e.to_string())?)
            .map_err(|e| e.to_string())?;
        file.sync_all().map_err(|e| e.to_string())?;
        drop(file);
        std::fs::rename(&temporary, path).map_err(|e| e.to_string())?;
        sync_parent(path)
    })();
    if result.is_err() {
        let _ = std::fs::remove_file(temporary);
    }
    result
}
fn sync_parent(path: &Path) -> Result<(), String> {
    #[cfg(target_os = "linux")]
    {
        let parent = path
            .parent()
            .filter(|p| !p.as_os_str().is_empty())
            .unwrap_or(Path::new("."));
        std::fs::File::open(parent)
            .and_then(|f| f.sync_all())
            .map_err(|e| e.to_string())?;
    }
    #[cfg(not(target_os = "linux"))]
    let _ = path;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    fn key(id: &str) -> SessionKey {
        SessionKey {
            transport: crate::call_manager::CallTransport::Gsm,
            generation: 7,
            call_id: id.into(),
        }
    }
    #[test]
    fn durable_marker_survives_restart_and_secondary_cannot_clear_primary() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("nested/guard.json");
        let (mut guard, error) = NativeOperationGuard::load(&path);
        assert!(error.is_none());
        assert!(!guard.blocked());
        guard.before_dispatch(&key("a"), Some("bus/owner")).unwrap();
        guard.before_dispatch(&key("b"), Some("bus/owner")).unwrap();
        guard.terminal(&key("b"));
        guard.clear_if_released(true).unwrap();
        assert!(path.exists());
        let (restarted, error) = NativeOperationGuard::load(&path);
        assert!(error.is_some());
        assert!(restarted.quarantined());
        guard.terminal(&key("a"));
        guard.clear_if_released(false).unwrap();
        assert!(path.exists());
        guard.clear_if_released(true).unwrap();
        assert!(!path.exists());
    }
    #[test]
    fn corruption_and_write_failure_fail_closed() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("guard.json");
        std::fs::write(&path, "bad").unwrap();
        let (guard, error) = NativeOperationGuard::load(&path);
        assert!(guard.quarantined());
        assert!(error.is_some());
        let (mut guard, _) = NativeOperationGuard::load(&path.join("guard.json"));
        guard.dirty = false;
        assert!(guard.before_dispatch(&key("a"), None).is_err());
        assert!(guard.quarantined());
    }
}
