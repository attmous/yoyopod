use std::path::Path;
use yoyopod_protocol::call::DeviceMode;

#[derive(serde::Serialize, serde::Deserialize)]
struct StoredMode {
    mode: DeviceMode,
}

pub fn load_mode(path: &Path) -> Result<DeviceMode, String> {
    match std::fs::read(path) {
        Ok(bytes) => serde_json::from_slice::<StoredMode>(&bytes)
            .map(|stored| stored.mode)
            .map_err(|error| format!("invalid call mode {}: {error}", path.display())),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(DeviceMode::Normal),
        Err(error) => Err(format!("read call mode {}: {error}", path.display())),
    }
}

pub fn save_mode(path: &Path, mode: DeviceMode) -> Result<(), String> {
    use std::io::Write;
    static NEXT_TEMP: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
    let parent = path
        .parent()
        .filter(|p| !p.as_os_str().is_empty())
        .unwrap_or(Path::new("."));
    std::fs::create_dir_all(parent).map_err(|error| error.to_string())?;
    let temporary = parent.join(format!(
        ".call-policy-{}-{}.tmp",
        std::process::id(),
        NEXT_TEMP.fetch_add(1, std::sync::atomic::Ordering::Relaxed)
    ));
    let result = (|| -> Result<(), String> {
        let mut options = std::fs::OpenOptions::new();
        options.write(true).create_new(true);
        #[cfg(unix)]
        {
            use std::os::unix::fs::OpenOptionsExt;
            options.mode(0o600);
        }
        let mut file = options
            .open(&temporary)
            .map_err(|error| error.to_string())?;
        let bytes = serde_json::to_vec(&StoredMode { mode }).map_err(|error| error.to_string())?;
        file.write_all(&bytes).map_err(|error| error.to_string())?;
        file.flush().map_err(|error| error.to_string())?;
        file.sync_all().map_err(|error| error.to_string())?;
        drop(file);
        std::fs::rename(&temporary, path).map_err(|error| error.to_string())
    })();
    if result.is_err() {
        let _ = std::fs::remove_file(&temporary);
    }
    result
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn missing_and_corrupt_mode_files() {
        let root = tempfile::tempdir().unwrap();
        let path = root.path().join("mode.json");
        assert_eq!(load_mode(&path).unwrap(), DeviceMode::Normal);
        std::fs::write(&path, "invalid").unwrap();
        assert!(load_mode(&path).is_err());
    }
    #[test]
    fn exact_modes_survive_restart() {
        let root = tempfile::tempdir().unwrap();
        let path = root.path().join("nested/mode.json");
        for (mode, value) in [
            (DeviceMode::Normal, "normal"),
            (DeviceMode::Silent, "silent"),
            (DeviceMode::DoNotDisturb, "do_not_disturb"),
        ] {
            save_mode(&path, mode.clone()).unwrap();
            assert_eq!(load_mode(&path).unwrap(), mode);
            let stored: serde_json::Value =
                serde_json::from_slice(&std::fs::read(&path).unwrap()).unwrap();
            assert_eq!(stored["mode"], value);
        }
    }
    #[test]
    fn configured_corrupt_mode_uses_safe_fallback_and_restart_projects_committed_mode() {
        let root = tempfile::tempdir().unwrap();
        let path = root.path().join("mode.json");
        std::fs::write(&path, r#"{"mode":"unknown"}"#).unwrap();
        let mut state = crate::state::RuntimeState::default();
        state.configure_call_preferences(path.clone());
        assert_eq!(state.settings.device_mode, DeviceMode::DoNotDisturb);
        assert!(state.call_preferences_error.is_some());
        state.apply_ui_intent(&yoyopod_protocol::ui::UiIntent::Settings(
            yoyopod_protocol::ui::SettingsIntent::DeviceModeSet(DeviceMode::Silent),
        ));
        assert_eq!(state.ui_snapshot().settings.device_mode, DeviceMode::Silent);
        let mut restarted = crate::state::RuntimeState::default();
        restarted.configure_call_preferences(path);
        assert_eq!(restarted.settings.device_mode, DeviceMode::Silent);
    }
    #[cfg(unix)]
    #[test]
    fn mode_store_is_private() {
        use std::os::unix::fs::PermissionsExt;
        let root = tempfile::tempdir().unwrap();
        let path = root.path().join("mode.json");
        save_mode(&path, DeviceMode::Normal).unwrap();
        assert_eq!(
            std::fs::metadata(path).unwrap().permissions().mode() & 0o777,
            0o600
        );
    }
    #[test]
    fn failed_settings_save_retains_effective_mode() {
        let root = tempfile::tempdir().unwrap();
        let blocker = root.path().join("blocker");
        std::fs::write(&blocker, "file").unwrap();
        let mut state = crate::state::RuntimeState {
            call_mode_file: blocker.join("mode.json"),
            ..Default::default()
        };
        state.apply_ui_intent(&yoyopod_protocol::ui::UiIntent::Settings(
            yoyopod_protocol::ui::SettingsIntent::DeviceModeSet(DeviceMode::Silent),
        ));
        assert_eq!(state.settings.device_mode, DeviceMode::Normal);
        assert!(state.call_preferences_error.is_some());
    }
}
