use std::fs;
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use serde::{Deserialize, Serialize};
use uuid::Uuid;
use zbus::blocking::{Connection, Proxy};
use zbus::fdo::ManagedObjects;
use zvariant::OwnedObjectPath;

const BLUEZ_DESTINATION: &str = "org.bluez";
const AUDIO_SINK_UUID: &str = "0000110b-0000-1000-8000-00805f9b34fb";
const HANDSFREE_UUID: &str = "0000111e-0000-1000-8000-00805f9b34fb";
const HEADSET_UUID: &str = "00001108-0000-1000-8000-00805f9b34fb";
const DEFAULT_REGISTRY_PATH: &str = "/var/lib/yoyopod/bluetooth/accessories.json";
const SCAN_DURATION: Duration = Duration::from_secs(12);
const SCAN_REFRESH_INTERVAL: Duration = Duration::from_secs(1);

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct BluetoothState {
    pub schema_version: u8,
    pub status: String,
    pub radio_enabled: bool,
    pub scanning: bool,
    pub accessories: Vec<BluetoothAccessory>,
    pub scanned_at: Option<u64>,
    pub reported_at: u64,
}

impl BluetoothState {
    pub fn unavailable() -> Self {
        Self {
            schema_version: 1,
            status: "unavailable".to_string(),
            radio_enabled: false,
            scanning: false,
            accessories: Vec::new(),
            scanned_at: None,
            reported_at: epoch_seconds(),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct BluetoothAccessory {
    pub accessory_id: String,
    pub name: String,
    pub kind: String,
    pub paired: bool,
    pub connected: bool,
    pub trusted: bool,
    pub auto_connect: bool,
    pub capabilities: BluetoothCapabilities,
    pub battery_percent: Option<u8>,
    pub signal_percent: Option<u8>,
    pub last_seen_at: u64,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct BluetoothCapabilities {
    pub output: bool,
    pub microphone: bool,
    pub stereo: bool,
    pub hands_free: bool,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct BluetoothOperationError {
    pub code: &'static str,
    pub message: String,
}

impl BluetoothOperationError {
    fn unavailable() -> Self {
        Self {
            code: "bluetooth_unavailable",
            message: "Bluetooth is not available on this YoYoPod".to_string(),
        }
    }

    fn failed(message: impl Into<String>) -> Self {
        Self {
            code: "bluetooth_operation_failed",
            message: message.into(),
        }
    }

    fn invalid_accessory() -> Self {
        Self {
            code: "bluetooth_accessory_not_found",
            message: "The Bluetooth accessory is no longer available".to_string(),
        }
    }
}

pub trait BluetoothController {
    fn refresh(&mut self) -> Result<BluetoothState, BluetoothOperationError>;
    fn set_radio(&mut self, enabled: bool) -> Result<BluetoothState, BluetoothOperationError>;
    fn start_scan(&mut self) -> Result<BluetoothState, BluetoothOperationError>;
    fn stop_scan(&mut self) -> Result<BluetoothState, BluetoothOperationError>;
    fn pair(&mut self, accessory_id: &str) -> Result<BluetoothState, BluetoothOperationError>;
    fn connect(&mut self, accessory_id: &str) -> Result<BluetoothState, BluetoothOperationError>;
    fn disconnect(&mut self, accessory_id: &str)
        -> Result<BluetoothState, BluetoothOperationError>;
    fn forget(&mut self, accessory_id: &str) -> Result<BluetoothState, BluetoothOperationError>;
    fn update_accessory(
        &mut self,
        accessory_id: &str,
        alias: Option<&str>,
        auto_connect: Option<bool>,
    ) -> Result<BluetoothState, BluetoothOperationError>;
    fn raw_address(&self, accessory_id: &str) -> Option<String>;
    fn tick(&mut self) -> Option<BluetoothState>;
}

pub struct UnavailableBluetoothController;

impl BluetoothController for UnavailableBluetoothController {
    fn refresh(&mut self) -> Result<BluetoothState, BluetoothOperationError> {
        Ok(BluetoothState::unavailable())
    }

    fn set_radio(&mut self, _: bool) -> Result<BluetoothState, BluetoothOperationError> {
        Err(BluetoothOperationError::unavailable())
    }

    fn start_scan(&mut self) -> Result<BluetoothState, BluetoothOperationError> {
        Err(BluetoothOperationError::unavailable())
    }

    fn stop_scan(&mut self) -> Result<BluetoothState, BluetoothOperationError> {
        Err(BluetoothOperationError::unavailable())
    }

    fn pair(&mut self, _: &str) -> Result<BluetoothState, BluetoothOperationError> {
        Err(BluetoothOperationError::unavailable())
    }

    fn connect(&mut self, _: &str) -> Result<BluetoothState, BluetoothOperationError> {
        Err(BluetoothOperationError::unavailable())
    }

    fn disconnect(&mut self, _: &str) -> Result<BluetoothState, BluetoothOperationError> {
        Err(BluetoothOperationError::unavailable())
    }

    fn forget(&mut self, _: &str) -> Result<BluetoothState, BluetoothOperationError> {
        Err(BluetoothOperationError::unavailable())
    }

    fn update_accessory(
        &mut self,
        _: &str,
        _: Option<&str>,
        _: Option<bool>,
    ) -> Result<BluetoothState, BluetoothOperationError> {
        Err(BluetoothOperationError::unavailable())
    }

    fn raw_address(&self, _: &str) -> Option<String> {
        None
    }

    fn tick(&mut self) -> Option<BluetoothState> {
        None
    }
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
struct AccessoryRegistry {
    accessories: Vec<RegistryEntry>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct RegistryEntry {
    accessory_id: String,
    address: String,
    #[serde(default)]
    alias: String,
    #[serde(default)]
    auto_connect: bool,
    #[serde(default)]
    last_seen_at: u64,
}

pub struct BluezBluetoothController {
    connection: Connection,
    adapter_path: OwnedObjectPath,
    registry_path: PathBuf,
    registry: AccessoryRegistry,
    scan_deadline: Option<Instant>,
    scan_refresh_deadline: Option<Instant>,
    scanned_at: Option<u64>,
}

impl BluezBluetoothController {
    pub fn connect() -> Result<Self, BluetoothOperationError> {
        Self::connect_with_registry(PathBuf::from(DEFAULT_REGISTRY_PATH))
    }

    fn connect_with_registry(registry_path: PathBuf) -> Result<Self, BluetoothOperationError> {
        let connection =
            Connection::system().map_err(|_| BluetoothOperationError::unavailable())?;
        let objects = managed_objects(&connection)?;
        let adapter_path = objects
            .iter()
            .find(|(_, interfaces)| interfaces.contains_key("org.bluez.Adapter1"))
            .map(|(path, _)| path.clone())
            .ok_or_else(BluetoothOperationError::unavailable)?;
        let registry = load_registry(&registry_path).unwrap_or_default();
        Ok(Self {
            connection,
            adapter_path,
            registry_path,
            registry,
            scan_deadline: None,
            scan_refresh_deadline: None,
            scanned_at: None,
        })
    }

    fn adapter_proxy(&self) -> Result<Proxy<'_>, BluetoothOperationError> {
        Proxy::new(
            &self.connection,
            BLUEZ_DESTINATION,
            self.adapter_path.as_str(),
            "org.bluez.Adapter1",
        )
        .map_err(|_| BluetoothOperationError::unavailable())
    }

    fn device_path(&self, accessory_id: &str) -> Option<OwnedObjectPath> {
        let address = self
            .registry
            .accessories
            .iter()
            .find(|entry| entry.accessory_id == accessory_id)?
            .address
            .clone();
        managed_objects(&self.connection)
            .ok()?
            .into_iter()
            .find(|(path, interfaces)| {
                interfaces.contains_key("org.bluez.Device1")
                    && device_property::<String>(&self.connection, path, "Address")
                        .is_some_and(|candidate| candidate.eq_ignore_ascii_case(&address))
            })
            .map(|(path, _)| path)
    }

    fn address_for_id(&self, accessory_id: &str) -> Option<String> {
        self.registry
            .accessories
            .iter()
            .find(|entry| entry.accessory_id == accessory_id)
            .map(|entry| entry.address.clone())
    }

    fn device_proxy<'a>(
        &'a self,
        path: &'a OwnedObjectPath,
    ) -> Result<Proxy<'a>, BluetoothOperationError> {
        Proxy::new(
            &self.connection,
            BLUEZ_DESTINATION,
            path.as_str(),
            "org.bluez.Device1",
        )
        .map_err(|_| BluetoothOperationError::invalid_accessory())
    }

    fn save_registry(&self) -> Result<(), BluetoothOperationError> {
        save_registry(&self.registry_path, &self.registry)
            .map_err(|_| BluetoothOperationError::failed("Bluetooth settings could not be saved"))
    }

    fn refresh_inner(&mut self) -> Result<BluetoothState, BluetoothOperationError> {
        let radio_enabled = self
            .adapter_proxy()?
            .get_property::<bool>("Powered")
            .unwrap_or(false);
        let scanning = self
            .adapter_proxy()?
            .get_property::<bool>("Discovering")
            .unwrap_or(false);
        let now = epoch_seconds();
        let objects = managed_objects(&self.connection)?;
        let mut accessories = Vec::new();
        let mut registry_changed = false;

        for (path, interfaces) in &objects {
            if !interfaces.contains_key("org.bluez.Device1") {
                continue;
            }
            let uuids =
                device_property::<Vec<String>>(&self.connection, path, "UUIDs").unwrap_or_default();
            let capabilities = capabilities_for(&uuids);
            if !capabilities.output {
                continue;
            }
            let Some(address) = device_property::<String>(&self.connection, path, "Address") else {
                continue;
            };
            let entry_index = if let Some(index) = self
                .registry
                .accessories
                .iter()
                .position(|entry| entry.address.eq_ignore_ascii_case(&address))
            {
                index
            } else {
                self.registry.accessories.push(RegistryEntry {
                    accessory_id: Uuid::new_v4().to_string(),
                    address: address.clone(),
                    alias: String::new(),
                    auto_connect: false,
                    last_seen_at: now,
                });
                registry_changed = true;
                self.registry.accessories.len() - 1
            };
            let entry = &mut self.registry.accessories[entry_index];
            if entry.last_seen_at != now {
                entry.last_seen_at = now;
                registry_changed = true;
            }
            let system_name = device_property::<String>(&self.connection, path, "Alias")
                .or_else(|| device_property::<String>(&self.connection, path, "Name"))
                .unwrap_or_else(|| "Bluetooth audio".to_string());
            let name = if entry.alias.trim().is_empty() {
                system_name
            } else {
                entry.alias.clone()
            };
            let rssi = device_property::<i16>(&self.connection, path, "RSSI");
            accessories.push(BluetoothAccessory {
                accessory_id: entry.accessory_id.clone(),
                name: clean_name(&name),
                kind: accessory_kind(&name, &capabilities),
                paired: device_property::<bool>(&self.connection, path, "Paired").unwrap_or(false),
                connected: device_property::<bool>(&self.connection, path, "Connected")
                    .unwrap_or(false),
                trusted: device_property::<bool>(&self.connection, path, "Trusted")
                    .unwrap_or(false),
                auto_connect: entry.auto_connect,
                capabilities,
                battery_percent: battery_percent(&self.connection, path),
                signal_percent: rssi.map(rssi_percent),
                last_seen_at: entry.last_seen_at,
            });
        }
        accessories.sort_by(|left, right| {
            right
                .connected
                .cmp(&left.connected)
                .then_with(|| right.paired.cmp(&left.paired))
                .then_with(|| left.name.to_lowercase().cmp(&right.name.to_lowercase()))
        });
        if registry_changed {
            self.save_registry()?;
        }
        Ok(BluetoothState {
            schema_version: 1,
            status: "ready".to_string(),
            radio_enabled,
            scanning,
            accessories,
            scanned_at: self.scanned_at,
            reported_at: now,
        })
    }

    fn call_device(
        &mut self,
        accessory_id: &str,
        method: &str,
    ) -> Result<BluetoothState, BluetoothOperationError> {
        let path = self
            .device_path(accessory_id)
            .ok_or_else(BluetoothOperationError::invalid_accessory)?;
        self.device_proxy(&path)?
            .call::<_, _, ()>(method, &())
            .map_err(|_| {
                BluetoothOperationError::failed(format!(
                    "The accessory could not be {}",
                    method.to_lowercase()
                ))
            })?;
        self.refresh_inner()
    }
}

impl BluetoothController for BluezBluetoothController {
    fn refresh(&mut self) -> Result<BluetoothState, BluetoothOperationError> {
        self.refresh_inner()
    }

    fn set_radio(&mut self, enabled: bool) -> Result<BluetoothState, BluetoothOperationError> {
        self.adapter_proxy()?
            .set_property("Powered", enabled)
            .map_err(|_| BluetoothOperationError::failed("Bluetooth radio could not be changed"))?;
        if !enabled {
            self.scan_deadline = None;
            self.scan_refresh_deadline = None;
        }
        self.refresh_inner()
    }

    fn start_scan(&mut self) -> Result<BluetoothState, BluetoothOperationError> {
        let adapter = self.adapter_proxy()?;
        if !adapter.get_property::<bool>("Powered").unwrap_or(false) {
            adapter.set_property("Powered", true).map_err(|_| {
                BluetoothOperationError::failed("Bluetooth radio could not be enabled")
            })?;
        }
        adapter
            .call::<_, _, ()>("StartDiscovery", &())
            .map_err(|_| BluetoothOperationError::failed("Bluetooth scan could not be started"))?;
        drop(adapter);
        let now = Instant::now();
        self.scan_deadline = Some(now + SCAN_DURATION);
        self.scan_refresh_deadline = Some(now + SCAN_REFRESH_INTERVAL);
        self.refresh_inner()
    }

    fn stop_scan(&mut self) -> Result<BluetoothState, BluetoothOperationError> {
        let adapter = self.adapter_proxy()?;
        if adapter.get_property::<bool>("Discovering").unwrap_or(false) {
            adapter
                .call::<_, _, ()>("StopDiscovery", &())
                .map_err(|_| {
                    BluetoothOperationError::failed("Bluetooth scan could not be stopped")
                })?;
        }
        drop(adapter);
        self.scan_deadline = None;
        self.scan_refresh_deadline = None;
        self.scanned_at = Some(epoch_seconds());
        self.refresh_inner()
    }

    fn pair(&mut self, accessory_id: &str) -> Result<BluetoothState, BluetoothOperationError> {
        let address = self
            .address_for_id(accessory_id)
            .ok_or_else(BluetoothOperationError::invalid_accessory)?;
        let output = Command::new("bluetoothctl")
            .args(["--agent", "NoInputNoOutput", "pair", &address])
            .output()
            .map_err(|_| BluetoothOperationError::failed("Bluetooth pairing could not start"))?;
        if !output.status.success() {
            return Err(BluetoothOperationError {
                code: "bluetooth_pairing_rejected",
                message:
                    "Pairing was not accepted. Put the accessory in pairing mode and try again."
                        .to_string(),
            });
        }
        let path = self
            .device_path(accessory_id)
            .ok_or_else(BluetoothOperationError::invalid_accessory)?;
        {
            let device = self.device_proxy(&path)?;
            let _ = device.set_property("Trusted", true);
        }
        self.refresh_inner()
    }

    fn connect(&mut self, accessory_id: &str) -> Result<BluetoothState, BluetoothOperationError> {
        if let Ok(state) = self.refresh_inner() {
            for connected in state
                .accessories
                .into_iter()
                .filter(|accessory| accessory.connected && accessory.accessory_id != accessory_id)
            {
                let _ = self.disconnect(&connected.accessory_id);
            }
        }
        self.call_device(accessory_id, "Connect")
    }

    fn disconnect(
        &mut self,
        accessory_id: &str,
    ) -> Result<BluetoothState, BluetoothOperationError> {
        self.call_device(accessory_id, "Disconnect")
    }

    fn forget(&mut self, accessory_id: &str) -> Result<BluetoothState, BluetoothOperationError> {
        let path = self
            .device_path(accessory_id)
            .ok_or_else(BluetoothOperationError::invalid_accessory)?;
        self.adapter_proxy()?
            .call::<_, _, ()>("RemoveDevice", &(path,))
            .map_err(|_| BluetoothOperationError::failed("The accessory could not be forgotten"))?;
        self.registry
            .accessories
            .retain(|entry| entry.accessory_id != accessory_id);
        self.save_registry()?;
        self.refresh_inner()
    }

    fn update_accessory(
        &mut self,
        accessory_id: &str,
        alias: Option<&str>,
        auto_connect: Option<bool>,
    ) -> Result<BluetoothState, BluetoothOperationError> {
        let entry = self
            .registry
            .accessories
            .iter_mut()
            .find(|entry| entry.accessory_id == accessory_id)
            .ok_or_else(BluetoothOperationError::invalid_accessory)?;
        if let Some(alias) = alias {
            entry.alias = clean_name(alias);
        }
        if let Some(auto_connect) = auto_connect {
            entry.auto_connect = auto_connect;
        }
        self.save_registry()?;
        self.refresh_inner()
    }

    fn raw_address(&self, accessory_id: &str) -> Option<String> {
        self.address_for_id(accessory_id)
    }

    fn tick(&mut self) -> Option<BluetoothState> {
        let now = Instant::now();
        if self.scan_deadline.is_some_and(|deadline| now >= deadline) {
            return self.stop_scan().ok();
        }
        if self.scan_deadline.is_some()
            && self
                .scan_refresh_deadline
                .is_some_and(|deadline| now >= deadline)
        {
            self.scan_refresh_deadline = Some(now + SCAN_REFRESH_INTERVAL);
            return self.refresh_inner().ok();
        }
        None
    }
}

fn managed_objects(connection: &Connection) -> Result<ManagedObjects, BluetoothOperationError> {
    Proxy::new(
        connection,
        BLUEZ_DESTINATION,
        "/",
        "org.freedesktop.DBus.ObjectManager",
    )
    .and_then(|proxy| proxy.call("GetManagedObjects", &()))
    .map_err(|_| BluetoothOperationError::unavailable())
}

fn device_property<T>(connection: &Connection, path: &OwnedObjectPath, property: &str) -> Option<T>
where
    T: TryFrom<zvariant::OwnedValue>,
    T::Error: Into<zbus::Error>,
{
    Proxy::new(
        connection,
        BLUEZ_DESTINATION,
        path.as_str(),
        "org.bluez.Device1",
    )
    .ok()?
    .get_property::<T>(property)
    .ok()
}

fn battery_percent(connection: &Connection, path: &OwnedObjectPath) -> Option<u8> {
    Proxy::new(
        connection,
        BLUEZ_DESTINATION,
        path.as_str(),
        "org.bluez.Battery1",
    )
    .ok()?
    .get_property::<u8>("Percentage")
    .ok()
}

fn capabilities_for(uuids: &[String]) -> BluetoothCapabilities {
    let has = |uuid: &str| {
        uuids
            .iter()
            .any(|candidate| candidate.eq_ignore_ascii_case(uuid))
    };
    let stereo = has(AUDIO_SINK_UUID);
    let hands_free = has(HANDSFREE_UUID) || has(HEADSET_UUID);
    BluetoothCapabilities {
        output: stereo || hands_free,
        microphone: hands_free,
        stereo,
        hands_free,
    }
}

fn accessory_kind(name: &str, capabilities: &BluetoothCapabilities) -> String {
    let normalized = name.to_lowercase();
    if normalized.contains("earbud") || normalized.contains("airpod") || normalized.contains("buds")
    {
        "earbuds"
    } else if capabilities.microphone
        && (normalized.contains("headset") || normalized.contains("headphone"))
    {
        "headset"
    } else if normalized.contains("speaker") {
        "speaker"
    } else if normalized.contains("headphone") {
        "headphones"
    } else {
        "unknown_audio"
    }
    .to_string()
}

fn clean_name(value: &str) -> String {
    value
        .chars()
        .filter(|character| !character.is_control())
        .collect::<String>()
        .trim()
        .chars()
        .take(80)
        .collect()
}

fn rssi_percent(rssi: i16) -> u8 {
    (((rssi.clamp(-100, -40) + 100) * 100) / 60) as u8
}

fn load_registry(path: &Path) -> Result<AccessoryRegistry, std::io::Error> {
    let bytes = fs::read(path)?;
    serde_json::from_slice(&bytes)
        .map_err(|error| std::io::Error::new(std::io::ErrorKind::InvalidData, error))
}

fn save_registry(path: &Path, registry: &AccessoryRegistry) -> Result<(), std::io::Error> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)?;
        fs::set_permissions(parent, fs::Permissions::from_mode(0o750))?;
    }
    let temporary = path.with_extension("tmp");
    fs::write(&temporary, serde_json::to_vec_pretty(registry)?)?;
    fs::set_permissions(&temporary, fs::Permissions::from_mode(0o600))?;
    fs::rename(temporary, path)
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
    fn capabilities_only_allow_audio_profiles() {
        assert!(!capabilities_for(&["0000180f-0000-1000-8000-00805f9b34fb".to_string()]).output);
        let capabilities =
            capabilities_for(&[AUDIO_SINK_UUID.to_string(), HANDSFREE_UUID.to_string()]);
        assert!(capabilities.output);
        assert!(capabilities.stereo);
        assert!(capabilities.microphone);
    }

    #[test]
    fn scan_window_is_short_and_refreshes_incrementally() {
        assert_eq!(SCAN_DURATION, Duration::from_secs(12));
        assert_eq!(SCAN_REFRESH_INTERVAL, Duration::from_secs(1));
        assert!(SCAN_REFRESH_INTERVAL < SCAN_DURATION);
    }

    #[test]
    fn registry_is_private_and_round_trips_opaque_ids() {
        let directory = tempfile::tempdir().expect("tempdir");
        let path = directory.path().join("accessories.json");
        let registry = AccessoryRegistry {
            accessories: vec![RegistryEntry {
                accessory_id: Uuid::new_v4().to_string(),
                address: "AA:BB:CC:DD:EE:FF".to_string(),
                alias: "Kitchen headset".to_string(),
                auto_connect: true,
                last_seen_at: 10,
            }],
        };
        save_registry(&path, &registry).expect("save");
        let loaded = load_registry(&path).expect("load");
        assert_eq!(
            loaded.accessories[0].accessory_id,
            registry.accessories[0].accessory_id
        );
        assert_eq!(
            fs::metadata(path).expect("metadata").permissions().mode() & 0o777,
            0o600
        );
    }
}
