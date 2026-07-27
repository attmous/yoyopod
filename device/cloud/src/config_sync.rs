use std::fs::{self, OpenOptions};
use std::io::Write;
#[cfg(unix)]
use std::os::unix::fs::{OpenOptionsExt, PermissionsExt};
use std::path::Path;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use anyhow::{anyhow, Context, Result};
use serde_json::{json, Value};

use crate::config::CloudHostConfig;

pub struct CloudConfigSync {
    config: CloudHostConfig,
    agent: ureq::Agent,
    access_token: Option<String>,
    next_poll_at: u64,
}

enum ConfigFetchError {
    Unauthorized,
    Failed,
}

impl CloudConfigSync {
    pub fn new(config: CloudHostConfig) -> Self {
        let timeout = Duration::from_secs_f64(config.timeout_seconds.clamp(1.0, 30.0));
        Self {
            config,
            agent: ureq::AgentBuilder::new().timeout(timeout).build(),
            access_token: None,
            next_poll_at: 0,
        }
    }

    pub fn load_cached(&self) -> Result<Option<Value>> {
        let path = self.config.cache_path();
        if !path.exists() {
            return Ok(None);
        }
        let raw = fs::read_to_string(&path)
            .with_context(|| format!("read cached cloud config {}", path.display()))?;
        let value: Value = serde_json::from_str(&raw).context("parse cached cloud config")?;
        validate_device_config(value).map(Some)
    }

    pub fn poll(&mut self, force: bool) -> Result<Option<Value>> {
        if !self.config.provisioned() {
            return Ok(None);
        }
        let now = epoch_seconds();
        if !force && now < self.next_poll_at {
            return Ok(None);
        }
        self.next_poll_at = now.saturating_add(self.config.config_poll_interval_seconds.max(1));

        let value = self.fetch_authenticated_config()?;
        let value = validate_device_config(value)?;
        persist_private_json(&self.config.cache_path(), &value)?;
        Ok(Some(value))
    }

    fn fetch_authenticated_config(&mut self) -> Result<Value> {
        if self.access_token.is_none() {
            self.access_token = Some(self.authenticate()?);
        }
        match self.fetch_with_current_token() {
            Ok(value) => Ok(value),
            Err(ConfigFetchError::Unauthorized) => {
                self.access_token = Some(self.authenticate()?);
                self.fetch_with_current_token()
                    .map_err(|_| anyhow!("cloud config request failed after reauthentication"))
            }
            Err(ConfigFetchError::Failed) => Err(anyhow!("cloud config request failed")),
        }
    }

    fn authenticate(&self) -> Result<String> {
        let url = join_url(&self.config.api_base_url, &self.config.auth_path);
        let response = self
            .agent
            .post(&url)
            .send_json(json!({
                "device_id": self.config.device_id,
                "device_secret": self.config.device_secret,
            }))
            .map_err(|_| anyhow!("device authentication failed"))?;
        let payload: Value = response
            .into_json()
            .map_err(|_| anyhow!("device authentication response was invalid"))?;
        payload
            .get("access_token")
            .and_then(Value::as_str)
            .map(str::trim)
            .filter(|value| !value.is_empty())
            .map(str::to_string)
            .ok_or_else(|| anyhow!("device authentication did not return a token"))
    }

    fn fetch_with_current_token(&self) -> Result<Value, ConfigFetchError> {
        let path = self
            .config
            .config_path_template
            .replace("{device_id}", self.config.device_id.trim());
        let url = join_url(&self.config.api_base_url, &path);
        let response = self
            .agent
            .get(&url)
            .set(
                "Authorization",
                &format!(
                    "Bearer {}",
                    self.access_token.as_deref().unwrap_or_default()
                ),
            )
            .call()
            .map_err(|error| match error {
                ureq::Error::Status(401, _) => ConfigFetchError::Unauthorized,
                _ => ConfigFetchError::Failed,
            })?;
        response
            .into_json::<Value>()
            .map_err(|_| ConfigFetchError::Failed)
    }
}

pub fn validate_device_config(value: Value) -> Result<Value> {
    let object = value
        .as_object()
        .ok_or_else(|| anyhow!("cloud config must be an object"))?;
    if object
        .get("config_version")
        .and_then(Value::as_u64)
        .is_none()
    {
        return Err(anyhow!("cloud config version is missing"));
    }
    let features = object.get("features").and_then(Value::as_object);
    if features
        .and_then(|value| value.get("location_tracking"))
        .is_some_and(|value| !value.is_boolean())
    {
        return Err(anyhow!("cloud location tracking flag is invalid"));
    }
    let connectivity = object.get("connectivity").and_then(Value::as_object);
    let moving = connectivity
        .and_then(|value| value.get("location_moving_interval_seconds"))
        .and_then(Value::as_u64)
        .unwrap_or(60);
    let stationary = connectivity
        .and_then(|value| value.get("location_stationary_interval_seconds"))
        .and_then(Value::as_u64)
        .or_else(|| {
            connectivity
                .and_then(|value| value.get("location_report_interval_seconds"))
                .and_then(Value::as_u64)
        })
        .unwrap_or(300);
    if !(30..=900).contains(&moving) || !(120..=3_600).contains(&stationary) || stationary < moving
    {
        return Err(anyhow!("cloud location intervals are invalid"));
    }
    Ok(value)
}

fn persist_private_json(path: &Path, value: &Value) -> Result<()> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)
            .with_context(|| format!("create cloud config cache {}", parent.display()))?;
    }
    let temporary = path.with_extension("tmp");
    let mut options = OpenOptions::new();
    options.create(true).truncate(true).write(true);
    #[cfg(unix)]
    options.mode(0o600);
    let mut file = options
        .open(&temporary)
        .with_context(|| format!("open cloud config cache {}", temporary.display()))?;
    serde_json::to_writer(&mut file, value).context("encode cloud config cache")?;
    file.write_all(b"\n").context("finish cloud config cache")?;
    file.sync_all().context("sync cloud config cache")?;
    #[cfg(unix)]
    fs::set_permissions(&temporary, fs::Permissions::from_mode(0o600))
        .context("secure cloud config cache")?;
    fs::rename(&temporary, path).context("replace cloud config cache")?;
    Ok(())
}

fn join_url(base: &str, path: &str) -> String {
    format!(
        "{}/{}",
        base.trim_end_matches('/'),
        path.trim_start_matches('/')
    )
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

    #[test]
    fn validates_new_and_legacy_location_intervals() {
        assert!(validate_device_config(json!({
            "config_version": 3,
            "features": {"location_tracking": true},
            "connectivity": {
                "location_moving_interval_seconds": 60,
                "location_stationary_interval_seconds": 300
            }
        }))
        .is_ok());
        assert!(validate_device_config(json!({
            "config_version": 2,
            "connectivity": {"location_report_interval_seconds": 600}
        }))
        .is_ok());
        assert!(validate_device_config(json!({
            "config_version": 4,
            "connectivity": {
                "location_moving_interval_seconds": 500,
                "location_stationary_interval_seconds": 300
            }
        }))
        .is_err());
    }
}
