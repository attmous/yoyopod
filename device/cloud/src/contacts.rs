use std::fs::{self, OpenOptions};
use std::io::Write;
#[cfg(unix)]
use std::os::unix::fs::{OpenOptionsExt, PermissionsExt};
use std::path::{Path, PathBuf};

use anyhow::{anyhow, Context, Result};
use serde_json::{json, Value};

use crate::config::CloudHostConfig;

pub fn validate_contacts(config: &Value) -> Result<()> {
    let Some(contacts) = config.get("contacts") else {
        return Ok(());
    };
    let entries = contacts
        .get("entries")
        .and_then(Value::as_array)
        .ok_or_else(|| anyhow!("cloud contacts entries must be an array"))?;
    let mut ids = std::collections::BTreeSet::new();
    for entry in entries {
        let id = nonempty_string(entry, "id")
            .ok_or_else(|| anyhow!("cloud contact identity is missing"))?;
        if !ids.insert(id) || nonempty_string(entry, "name").is_none() {
            return Err(anyhow!("cloud contact identity is invalid"));
        }
        for key in ["can_call", "can_receive"] {
            if !entry.get(key).is_some_and(Value::is_boolean) {
                return Err(anyhow!("cloud contact permission is invalid"));
            }
        }
    }
    Ok(())
}

// Cloud policy is authoritative, including an empty list. Keep only local
// voice aliases for matching people; never keep a deleted seed contact alive.
pub fn persist_contacts(config: &CloudHostConfig, value: &Value) -> Result<Option<Vec<Value>>> {
    validate_contacts(value)?;
    let Some(entries) = value.pointer("/contacts/entries").and_then(Value::as_array) else {
        return Ok(None);
    };
    let root = Path::new(&config.runtime_root);
    let directory_path = root.join("config/people/directory.yaml");
    let directory: Value = if directory_path.exists() {
        serde_yaml::from_str(&fs::read_to_string(directory_path)?)?
    } else {
        json!({})
    };
    let path = runtime_path(
        root,
        directory.get("contacts_file"),
        "data/people/contacts.yaml",
    );
    let seed = runtime_path(
        root,
        directory.get("contacts_seed_file"),
        "config/people/contacts.seed.yaml",
    );
    let previous = fs::read_to_string(if path.exists() { &path } else { &seed })
        .ok()
        .and_then(|raw| serde_yaml::from_str::<Value>(&raw).ok());
    let mut speed_dial = serde_json::Map::new();
    let contacts: Vec<Value> = entries
        .iter()
        .map(|entry| {
            let mut contact = entry.clone();
            contact["favorite"] = json!(entry
                .get("is_primary")
                .and_then(Value::as_bool)
                .unwrap_or(false));
            if let Some(old) = previous
                .as_ref()
                .and_then(|value| value.get("contacts"))
                .and_then(Value::as_array)
                .and_then(|contacts| {
                    contacts.iter().find(|old| {
                        old.get("id") == entry.get("id") && entry.get("id").is_some()
                            || nonempty_string(old, "sip_address").is_some()
                                && nonempty_string(old, "sip_address")
                                    == nonempty_string(entry, "sip_address")
                    })
                })
            {
                if let Some(aliases) = old.get("aliases").filter(|value| value.is_array()) {
                    contact["aliases"] = aliases.clone();
                }
            }
            if entry.get("can_call").and_then(Value::as_bool) == Some(true) {
                if let (Some(number @ 1..=9), Some(sip)) = (
                    entry.get("quick_dial").and_then(Value::as_u64),
                    nonempty_string(entry, "sip_address"),
                ) {
                    speed_dial.insert(number.to_string(), json!(sip));
                }
            }
            contact
        })
        .collect();
    let payload = json!({"contacts": &contacts, "speed_dial": speed_dial});
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)?;
    }
    let temporary = path.with_extension("sync.tmp");
    let mut options = OpenOptions::new();
    options.create(true).truncate(true).write(true);
    #[cfg(unix)]
    options.mode(0o600);
    let mut file = options.open(&temporary).context("open contacts store")?;
    file.write_all(serde_yaml::to_string(&payload)?.as_bytes())?;
    file.sync_all()?;
    #[cfg(unix)]
    fs::set_permissions(&temporary, fs::Permissions::from_mode(0o600))?;
    fs::rename(temporary, path).context("replace contacts store")?;
    Ok(Some(contacts))
}

fn runtime_path(root: &Path, value: Option<&Value>, fallback: &str) -> PathBuf {
    root.join(value.and_then(Value::as_str).unwrap_or(fallback))
}

fn nonempty_string<'a>(value: &'a Value, key: &str) -> Option<&'a str> {
    value
        .get(key)
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|value| !value.is_empty())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn contact(id: &str, name: &str, sip: &str) -> Value {
        json!({"id": id, "name": name, "sip_address": sip,
            "can_call": true, "can_receive": true, "is_primary": true, "quick_dial": 1})
    }

    #[test]
    fn saves_edits_clears_removed_contacts_and_preserves_only_matching_aliases() {
        let root = tempfile::tempdir().unwrap();
        let config = CloudHostConfig {
            runtime_root: root.path().to_string_lossy().into_owned(),
            ..Default::default()
        };
        fs::create_dir_all(root.path().join("config/people")).unwrap();
        fs::write(
            root.path().join("config/people/directory.yaml"),
            "contacts_file: data/custom/people.yaml\n",
        )
        .unwrap();
        fs::write(root.path().join("config/people/contacts.seed.yaml"),
            "contacts:\n  - name: Old\n    sip_address: sip:old@example.com\n    aliases: [grandma]\n  - name: Remove\n    sip_address: sip:remove@example.com\n").unwrap();
        persist_contacts(
            &config,
            &json!({"contacts": {"entries": [contact("one", "Grandma", "sip:old@example.com")]}}),
        )
        .unwrap();
        let path = root.path().join("data/custom/people.yaml");
        let mut saved: Value = serde_yaml::from_str(&fs::read_to_string(&path).unwrap()).unwrap();
        assert_eq!(saved["contacts"].as_array().unwrap().len(), 1);
        assert_eq!(saved["contacts"][0]["aliases"], json!(["grandma"]));
        let mut changed = contact("one", "Nana", "sip:new@example.com");
        changed["can_call"] = json!(false);
        persist_contacts(&config, &json!({"contacts": {"entries": [changed]}})).unwrap();
        saved = serde_yaml::from_str(&fs::read_to_string(&path).unwrap()).unwrap();
        assert_eq!(saved["contacts"][0]["name"], "Nana");
        assert_eq!(saved["contacts"][0]["sip_address"], "sip:new@example.com");
        assert_eq!(saved["speed_dial"], json!({}));
        assert_eq!(saved["contacts"][0]["aliases"], json!(["grandma"]));
        assert!(persist_contacts(&config, &json!({"contacts": {"entries": [{}]}})).is_err());
        assert_eq!(
            serde_yaml::from_str::<Value>(&fs::read_to_string(&path).unwrap()).unwrap(),
            saved
        );
        persist_contacts(&config, &json!({"contacts": {"entries": []}})).unwrap();
        saved = serde_yaml::from_str(&fs::read_to_string(path).unwrap()).unwrap();
        assert_eq!(saved["contacts"], json!([]));
    }
}
