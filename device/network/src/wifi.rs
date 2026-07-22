use std::collections::{HashMap, HashSet};
use std::net::Ipv4Addr;
use std::thread;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use serde::{Deserialize, Serialize};
use zbus::blocking::{Connection, Proxy};
use zbus::zvariant::{OwnedObjectPath, OwnedValue, Value};

const NM_SERVICE: &str = "org.freedesktop.NetworkManager";
const NM_PATH: &str = "/org/freedesktop/NetworkManager";
const NM_INTERFACE: &str = "org.freedesktop.NetworkManager";
const NM_SETTINGS_PATH: &str = "/org/freedesktop/NetworkManager/Settings";
const NM_SETTINGS_INTERFACE: &str = "org.freedesktop.NetworkManager.Settings";
const NM_CONNECTION_INTERFACE: &str = "org.freedesktop.NetworkManager.Settings.Connection";
const NM_DEVICE_INTERFACE: &str = "org.freedesktop.NetworkManager.Device";
const NM_WIRELESS_INTERFACE: &str = "org.freedesktop.NetworkManager.Device.Wireless";
const NM_ACTIVE_CONNECTION_INTERFACE: &str = "org.freedesktop.NetworkManager.Connection.Active";
const NM_IP4_CONFIG_INTERFACE: &str = "org.freedesktop.NetworkManager.IP4Config";
const NM_ACCESS_POINT_INTERFACE: &str = "org.freedesktop.NetworkManager.AccessPoint";
const NM_DEVICE_TYPE_WIFI: u32 = 2;
const NM_SETTINGS_ADD_TO_DISK: u32 = 0x1;
const NM_SETTINGS_UPDATE_TO_DISK: u32 = 0x1;
const NM_AP_FLAGS_PRIVACY: u32 = 0x1;
const NM_AP_SEC_KEY_MGMT_802_1X: u32 = 0x200;
const NM_AP_SEC_KEY_MGMT_SAE: u32 = 0x400;
const NM_AP_SEC_KEY_MGMT_OWE: u32 = 0x800;
const NM_AUTOCONNECT_PRIORITY_MIN: i32 = -999;
const NM_AUTOCONNECT_PRIORITY_MAX: i32 = 999;
const MAX_SAVED_PROFILES: usize = 32;
const MAX_NEARBY_NETWORKS: usize = 64;
const SCAN_WAIT_TIMEOUT: Duration = Duration::from_secs(4);
const SCAN_POLL_INTERVAL: Duration = Duration::from_millis(200);
const CHANGE_LOCAL_TIMEOUT: Duration = Duration::from_secs(25);
const CHANGE_POLL_INTERVAL: Duration = Duration::from_millis(250);
const CHECKPOINT_ROLLBACK_SECONDS: u32 = 90;

type NmSettings = HashMap<String, HashMap<String, OwnedValue>>;

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq, Hash)]
#[serde(rename_all = "snake_case")]
pub enum WifiSecurity {
    Open,
    Wpa2Personal,
    Wpa3Personal,
    Enterprise,
}

impl WifiSecurity {
    pub fn supports_profile_changes(self) -> bool {
        !matches!(self, Self::Enterprise)
    }
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum WifiStateStatus {
    Ready,
    Unavailable,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum WifiIpv4Mode {
    Dhcp,
    Static,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct WifiIpv4Config {
    pub mode: WifiIpv4Mode,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub address: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub prefix_length: Option<u8>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub gateway: Option<String>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub dns_servers: Vec<String>,
}

impl WifiIpv4Config {
    pub fn dhcp() -> Self {
        Self {
            mode: WifiIpv4Mode::Dhcp,
            address: None,
            prefix_length: None,
            gateway: None,
            dns_servers: Vec::new(),
        }
    }
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum WifiActivationPreference {
    Preferred,
    SessionOnly,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum WifiChangeOperation {
    ActivateProfile,
    UpdateIpv4,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct WifiActiveNetwork {
    pub profile_id: String,
    pub ssid: String,
    pub security: WifiSecurity,
    pub signal_percent: u8,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub ipv4: Option<WifiIpv4Config>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct WifiSavedProfile {
    pub profile_id: String,
    pub ssid: String,
    pub security: WifiSecurity,
    pub hidden: bool,
    pub active: bool,
    pub autoconnect: bool,
    pub ipv4_config: WifiIpv4Config,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct WifiNearbyNetwork {
    pub ssid: String,
    pub security: WifiSecurity,
    pub signal_percent: u8,
    pub saved: bool,
    pub active: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct WifiState {
    pub schema_version: u16,
    pub status: WifiStateStatus,
    pub radio_enabled: bool,
    pub active_network: Option<WifiActiveNetwork>,
    pub saved_profiles: Vec<WifiSavedProfile>,
    pub nearby_networks: Vec<WifiNearbyNetwork>,
    pub scanned_at: Option<u64>,
    pub reported_at: u64,
}

impl WifiState {
    pub fn unavailable() -> Self {
        Self {
            schema_version: 2,
            status: WifiStateStatus::Unavailable,
            radio_enabled: false,
            active_network: None,
            saved_profiles: Vec::new(),
            nearby_networks: Vec::new(),
            scanned_at: None,
            reported_at: epoch_seconds(),
        }
    }
}

#[derive(Debug, Clone, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct WifiAddProfileRequest {
    pub ssid: String,
    pub security: WifiSecurity,
    #[serde(default)]
    pub password: Option<String>,
    #[serde(default)]
    pub hidden: bool,
}

#[derive(Debug, Clone, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct WifiUpdateProfileRequest {
    pub profile_id: String,
    #[serde(default)]
    pub ssid: Option<String>,
    #[serde(default)]
    pub security: Option<WifiSecurity>,
    #[serde(default)]
    pub password: Option<String>,
    #[serde(default)]
    pub hidden: Option<bool>,
}

#[derive(Debug, Clone, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct WifiActivateProfileRequest {
    pub profile_id: String,
    pub preference: WifiActivationPreference,
}

#[derive(Debug, Clone, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct WifiUpdateIpv4Request {
    pub profile_id: String,
    pub ipv4: WifiIpv4Config,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum WifiChangeStart {
    Immediate(WifiState),
    Pending {
        profile_id: String,
        operation: WifiChangeOperation,
    },
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WifiOperationError {
    pub code: String,
    pub message: String,
}

impl WifiOperationError {
    pub fn new(code: impl Into<String>, message: impl Into<String>) -> Self {
        Self {
            code: code.into(),
            message: message.into(),
        }
    }

    fn unavailable() -> Self {
        Self::new(
            "wifi_unavailable",
            "Wi-Fi management is not available on this YoYoPod",
        )
    }

    fn operation_failed() -> Self {
        Self::new(
            "wifi_operation_failed",
            "The Wi-Fi operation could not be completed",
        )
    }
}

pub trait WifiController: Send {
    fn refresh(&mut self) -> Result<WifiState, WifiOperationError>;
    fn scan(&mut self) -> Result<WifiState, WifiOperationError>;
    fn add_profile(
        &mut self,
        request: WifiAddProfileRequest,
    ) -> Result<WifiState, WifiOperationError>;
    fn update_profile(
        &mut self,
        request: WifiUpdateProfileRequest,
    ) -> Result<WifiState, WifiOperationError>;
    fn forget_profile(&mut self, profile_id: &str) -> Result<WifiState, WifiOperationError>;
    fn begin_activate_profile(
        &mut self,
        request: WifiActivateProfileRequest,
    ) -> Result<WifiChangeStart, WifiOperationError>;
    fn begin_update_ipv4(
        &mut self,
        request: WifiUpdateIpv4Request,
    ) -> Result<WifiChangeStart, WifiOperationError>;
    fn confirm_pending_change(&mut self) -> Result<WifiState, WifiOperationError>;
    fn rollback_pending_change(&mut self) -> Result<WifiState, WifiOperationError>;
}

#[derive(Debug, Default)]
pub struct UnavailableWifiController;

impl WifiController for UnavailableWifiController {
    fn refresh(&mut self) -> Result<WifiState, WifiOperationError> {
        Ok(WifiState::unavailable())
    }

    fn scan(&mut self) -> Result<WifiState, WifiOperationError> {
        Err(WifiOperationError::unavailable())
    }

    fn add_profile(
        &mut self,
        _request: WifiAddProfileRequest,
    ) -> Result<WifiState, WifiOperationError> {
        Err(WifiOperationError::unavailable())
    }

    fn update_profile(
        &mut self,
        _request: WifiUpdateProfileRequest,
    ) -> Result<WifiState, WifiOperationError> {
        Err(WifiOperationError::unavailable())
    }

    fn forget_profile(&mut self, _profile_id: &str) -> Result<WifiState, WifiOperationError> {
        Err(WifiOperationError::unavailable())
    }

    fn begin_activate_profile(
        &mut self,
        _request: WifiActivateProfileRequest,
    ) -> Result<WifiChangeStart, WifiOperationError> {
        Err(WifiOperationError::unavailable())
    }

    fn begin_update_ipv4(
        &mut self,
        _request: WifiUpdateIpv4Request,
    ) -> Result<WifiChangeStart, WifiOperationError> {
        Err(WifiOperationError::unavailable())
    }

    fn confirm_pending_change(&mut self) -> Result<WifiState, WifiOperationError> {
        Err(WifiOperationError::unavailable())
    }

    fn rollback_pending_change(&mut self) -> Result<WifiState, WifiOperationError> {
        Err(WifiOperationError::unavailable())
    }
}

struct PendingNetworkManagerChange {
    checkpoint_path: OwnedObjectPath,
    target_profile_id: String,
    previous_profile_id: Option<String>,
    preference: WifiActivationPreference,
    restore_connection: Option<(OwnedObjectPath, NmSettings)>,
}

pub struct NetworkManagerWifiController {
    connection: Connection,
    last_scan_at: Option<u64>,
    pending_change: Option<PendingNetworkManagerChange>,
}

impl NetworkManagerWifiController {
    pub fn connect() -> Result<Self, WifiOperationError> {
        Connection::system()
            .map(|connection| Self {
                connection,
                last_scan_at: None,
                pending_change: None,
            })
            .map_err(|_| WifiOperationError::unavailable())
    }

    fn proxy<'a>(
        &'a self,
        path: &'a str,
        interface: &'a str,
    ) -> Result<Proxy<'a>, WifiOperationError> {
        Proxy::new(&self.connection, NM_SERVICE, path, interface)
            .map_err(|_| WifiOperationError::operation_failed())
    }

    fn manager(&self) -> Result<Proxy<'_>, WifiOperationError> {
        self.proxy(NM_PATH, NM_INTERFACE)
    }

    fn settings(&self) -> Result<Proxy<'_>, WifiOperationError> {
        self.proxy(NM_SETTINGS_PATH, NM_SETTINGS_INTERFACE)
    }

    fn wifi_device_paths(&self) -> Result<Vec<OwnedObjectPath>, WifiOperationError> {
        let paths: Vec<OwnedObjectPath> = self
            .manager()?
            .call("GetDevices", &())
            .map_err(|_| WifiOperationError::operation_failed())?;
        Ok(paths
            .into_iter()
            .filter(|path| {
                self.proxy(path.as_str(), NM_DEVICE_INTERFACE)
                    .and_then(|proxy| {
                        proxy
                            .get_property::<u32>("DeviceType")
                            .map_err(|_| WifiOperationError::operation_failed())
                    })
                    .is_ok_and(|device_type| device_type == NM_DEVICE_TYPE_WIFI)
            })
            .collect())
    }

    fn connection_paths(&self) -> Result<Vec<OwnedObjectPath>, WifiOperationError> {
        self.settings()?
            .call("ListConnections", &())
            .map_err(|_| WifiOperationError::operation_failed())
    }

    fn get_settings(&self, path: &OwnedObjectPath) -> Result<NmSettings, WifiOperationError> {
        self.proxy(path.as_str(), NM_CONNECTION_INTERFACE)?
            .call("GetSettings", &())
            .map_err(|_| WifiOperationError::operation_failed())
    }

    fn find_connection(
        &self,
        profile_id: &str,
    ) -> Result<(OwnedObjectPath, NmSettings), WifiOperationError> {
        for path in self.connection_paths()? {
            let settings = self.get_settings(&path)?;
            if settings_match_wifi_profile(&settings, profile_id) {
                return Ok((path, settings));
            }
        }
        Err(WifiOperationError::new(
            "wifi_profile_not_found",
            "The saved Wi-Fi network was not found",
        ))
    }

    fn active_profile(&self) -> Result<Option<WifiActiveNetwork>, WifiOperationError> {
        let active_paths: Vec<OwnedObjectPath> = self
            .manager()?
            .get_property("ActiveConnections")
            .map_err(|_| WifiOperationError::operation_failed())?;

        for path in active_paths {
            let proxy = self.proxy(path.as_str(), NM_ACTIVE_CONNECTION_INTERFACE)?;
            let connection_type: String = proxy
                .get_property("Type")
                .map_err(|_| WifiOperationError::operation_failed())?;
            if connection_type != "802-11-wireless" {
                continue;
            }
            let profile_id: String = proxy
                .get_property("Uuid")
                .map_err(|_| WifiOperationError::operation_failed())?;
            let ip4_config_path: OwnedObjectPath = proxy
                .get_property("Ip4Config")
                .unwrap_or_else(|_| root_object_path());
            let specific: OwnedObjectPath = proxy
                .get_property("SpecificObject")
                .map_err(|_| WifiOperationError::operation_failed())?;
            let (_, settings_for_profile) = self.find_connection(&profile_id)?;
            let (ssid, security, signal_percent) = if specific.as_str() == "/" {
                (
                    setting_ssid(&settings_for_profile).unwrap_or_default(),
                    profile_security(&settings_for_profile),
                    0,
                )
            } else {
                let ap = self.access_point(&specific)?;
                (ap.ssid, ap.security, ap.signal_percent)
            };
            return Ok(Some(WifiActiveNetwork {
                profile_id,
                ssid,
                security,
                signal_percent,
                ipv4: self.active_ipv4_config(&ip4_config_path, &settings_for_profile)?,
            }));
        }

        Ok(None)
    }

    fn active_ipv4_config(
        &self,
        path: &OwnedObjectPath,
        settings: &NmSettings,
    ) -> Result<Option<WifiIpv4Config>, WifiOperationError> {
        if path.as_str() == "/" {
            return Ok(None);
        }
        let proxy = self.proxy(path.as_str(), NM_IP4_CONFIG_INTERFACE)?;
        let address_data: Vec<HashMap<String, OwnedValue>> =
            proxy.get_property("AddressData").unwrap_or_default();
        let (address, prefix_length) = address_data
            .first()
            .map(|entry| {
                (
                    dict_string(entry, "address"),
                    dict_u32(entry, "prefix").and_then(|value| u8::try_from(value).ok()),
                )
            })
            .unwrap_or((None, None));
        let gateway = proxy
            .get_property::<String>("Gateway")
            .ok()
            .filter(|value| !value.trim().is_empty());
        let nameserver_data: Vec<HashMap<String, OwnedValue>> =
            proxy.get_property("NameserverData").unwrap_or_default();
        let dns_servers = nameserver_data
            .iter()
            .filter_map(|entry| dict_string(entry, "address"))
            .take(3)
            .collect();
        let configured = profile_ipv4_config(settings);
        Ok(Some(WifiIpv4Config {
            mode: configured.mode,
            address,
            prefix_length,
            gateway,
            dns_servers,
        }))
    }

    fn access_point(&self, path: &OwnedObjectPath) -> Result<AccessPointFact, WifiOperationError> {
        let proxy = self.proxy(path.as_str(), NM_ACCESS_POINT_INTERFACE)?;
        let ssid: Vec<u8> = proxy
            .get_property("Ssid")
            .map_err(|_| WifiOperationError::operation_failed())?;
        let flags: u32 = proxy
            .get_property("Flags")
            .map_err(|_| WifiOperationError::operation_failed())?;
        let wpa_flags: u32 = proxy
            .get_property("WpaFlags")
            .map_err(|_| WifiOperationError::operation_failed())?;
        let rsn_flags: u32 = proxy
            .get_property("RsnFlags")
            .map_err(|_| WifiOperationError::operation_failed())?;
        let strength: u8 = proxy
            .get_property("Strength")
            .map_err(|_| WifiOperationError::operation_failed())?;
        Ok(AccessPointFact {
            ssid: sanitize_ssid(&ssid),
            security: access_point_security(flags, wpa_flags, rsn_flags),
            signal_percent: strength.min(100),
        })
    }

    fn nearby_networks(
        &self,
        saved_profiles: &[WifiSavedProfile],
        active: Option<&WifiActiveNetwork>,
    ) -> Result<Vec<WifiNearbyNetwork>, WifiOperationError> {
        let saved = saved_profiles
            .iter()
            .map(|profile| (profile.ssid.clone(), profile.security))
            .collect::<HashSet<_>>();
        let mut by_network = HashMap::<(String, WifiSecurity), WifiNearbyNetwork>::new();
        for device_path in self.wifi_device_paths()? {
            let access_points: Vec<OwnedObjectPath> = self
                .proxy(device_path.as_str(), NM_WIRELESS_INTERFACE)?
                .get_property("AccessPoints")
                .map_err(|_| WifiOperationError::operation_failed())?;
            for access_point_path in access_points {
                let fact = self.access_point(&access_point_path)?;
                if fact.ssid.is_empty() {
                    continue;
                }
                let key = (fact.ssid.clone(), fact.security);
                let candidate = WifiNearbyNetwork {
                    saved: saved.contains(&key),
                    active: active.is_some_and(|current| {
                        current.ssid == fact.ssid && current.security == fact.security
                    }),
                    ssid: fact.ssid,
                    security: fact.security,
                    signal_percent: fact.signal_percent,
                };
                by_network
                    .entry(key)
                    .and_modify(|current| {
                        if candidate.signal_percent > current.signal_percent {
                            *current = candidate.clone();
                        }
                    })
                    .or_insert(candidate);
            }
        }
        let mut nearby = by_network.into_values().collect::<Vec<_>>();
        nearby.sort_by(|left, right| {
            right
                .active
                .cmp(&left.active)
                .then_with(|| right.signal_percent.cmp(&left.signal_percent))
                .then_with(|| left.ssid.to_lowercase().cmp(&right.ssid.to_lowercase()))
        });
        nearby.truncate(MAX_NEARBY_NETWORKS);
        Ok(nearby)
    }

    fn saved_profiles(
        &self,
        active_profile_id: Option<&str>,
    ) -> Result<Vec<WifiSavedProfile>, WifiOperationError> {
        let mut profiles = Vec::new();
        for path in self.connection_paths()? {
            let settings = self.get_settings(&path)?;
            if setting_string(&settings, "connection", "type").as_deref() != Some("802-11-wireless")
            {
                continue;
            }
            let Some(profile_id) = setting_string(&settings, "connection", "uuid") else {
                continue;
            };
            profiles.push(WifiSavedProfile {
                active: active_profile_id == Some(profile_id.as_str()),
                profile_id,
                ssid: setting_ssid(&settings).unwrap_or_default(),
                security: profile_security(&settings),
                hidden: setting_bool(&settings, "802-11-wireless", "hidden").unwrap_or(false),
                autoconnect: setting_bool(&settings, "connection", "autoconnect").unwrap_or(true),
                ipv4_config: profile_ipv4_config(&settings),
            });
        }
        profiles.sort_by(|left, right| {
            right
                .active
                .cmp(&left.active)
                .then_with(|| left.ssid.to_lowercase().cmp(&right.ssid.to_lowercase()))
        });
        profiles.truncate(MAX_SAVED_PROFILES);
        Ok(profiles)
    }

    fn request_scan(&self) -> Result<(), WifiOperationError> {
        for path in self.wifi_device_paths()? {
            let proxy = self.proxy(path.as_str(), NM_WIRELESS_INTERFACE)?;
            let previous = proxy.get_property::<i64>("LastScan").unwrap_or(-1);
            let options = HashMap::<String, OwnedValue>::new();
            proxy
                .call::<_, _, ()>("RequestScan", &(options,))
                .map_err(|_| {
                    WifiOperationError::new(
                        "wifi_scan_failed",
                        "Nearby Wi-Fi networks could not be scanned",
                    )
                })?;
            let deadline = std::time::Instant::now() + SCAN_WAIT_TIMEOUT;
            while std::time::Instant::now() < deadline {
                let current = proxy.get_property::<i64>("LastScan").unwrap_or(previous);
                if current > previous {
                    break;
                }
                thread::sleep(SCAN_POLL_INTERVAL);
            }
        }
        Ok(())
    }

    fn ensure_inactive(&self, profile_id: &str) -> Result<(), WifiOperationError> {
        ensure_profile_inactive(self.active_profile()?.as_ref(), profile_id)
    }

    fn new_profile_autoconnect_priority(&self) -> Result<i32, WifiOperationError> {
        let active = self.active_profile()?.ok_or_else(|| {
            WifiOperationError::new(
                "wifi_active_profile_required",
                "An active Wi-Fi network is required before saving another network",
            )
        })?;
        let (_, settings) = self.find_connection(&active.profile_id)?;
        let active_priority =
            setting_i32(&settings, "connection", "autoconnect-priority").unwrap_or(0);
        lower_autoconnect_priority(active_priority)
    }

    fn update_connection(
        &self,
        path: &OwnedObjectPath,
        settings: NmSettings,
    ) -> Result<(), WifiOperationError> {
        let result: HashMap<String, OwnedValue> = self
            .proxy(path.as_str(), NM_CONNECTION_INTERFACE)?
            .call(
                "Update2",
                &(
                    settings,
                    NM_SETTINGS_UPDATE_TO_DISK,
                    HashMap::<String, OwnedValue>::new(),
                ),
            )
            .map_err(|_| WifiOperationError::operation_failed())?;
        let _ = result;
        Ok(())
    }

    fn merge_existing_secret(
        &self,
        path: &OwnedObjectPath,
        settings: &mut NmSettings,
    ) -> Result<(), WifiOperationError> {
        let secrets: NmSettings = self
            .proxy(path.as_str(), NM_CONNECTION_INTERFACE)?
            .call("GetSecrets", &("802-11-wireless-security",))
            .map_err(|_| {
                WifiOperationError::new(
                    "wifi_password_required",
                    "Enter the Wi-Fi password to update this saved network",
                )
            })?;
        let Some(psk) = secrets
            .get("802-11-wireless-security")
            .and_then(|group| group.get("psk"))
            .cloned()
        else {
            return Err(WifiOperationError::new(
                "wifi_password_required",
                "Enter the Wi-Fi password to update this saved network",
            ));
        };
        settings
            .entry("802-11-wireless-security".to_string())
            .or_default()
            .insert("psk".to_string(), psk);
        Ok(())
    }

    fn ensure_no_pending_change(&self) -> Result<(), WifiOperationError> {
        if self.pending_change.is_some() {
            return Err(WifiOperationError::new(
                "wifi_change_in_progress",
                "Another Wi-Fi connectivity change is already in progress",
            ));
        }
        Ok(())
    }

    fn create_checkpoint(&self) -> Result<OwnedObjectPath, WifiOperationError> {
        let devices = self.wifi_device_paths()?;
        if devices.is_empty() {
            return Err(WifiOperationError::unavailable());
        }
        self.manager()?
            .call(
                "CheckpointCreate",
                &(devices, CHECKPOINT_ROLLBACK_SECONDS, 0_u32),
            )
            .map_err(|_| {
                WifiOperationError::new(
                    "wifi_checkpoint_failed",
                    "The current Wi-Fi connection could not be protected",
                )
            })
    }

    fn activate_connection_path(
        &self,
        connection_path: &OwnedObjectPath,
    ) -> Result<(), WifiOperationError> {
        let device_path = self
            .wifi_device_paths()?
            .into_iter()
            .next()
            .ok_or_else(WifiOperationError::unavailable)?;
        let _: OwnedObjectPath = self
            .manager()?
            .call(
                "ActivateConnection",
                &(connection_path.clone(), device_path, root_object_path()),
            )
            .map_err(|_| {
                WifiOperationError::new(
                    "wifi_activation_failed",
                    "The saved Wi-Fi network could not be activated",
                )
            })?;
        Ok(())
    }

    fn wait_for_active_profile(&self, profile_id: &str) -> Result<(), WifiOperationError> {
        let deadline = std::time::Instant::now() + CHANGE_LOCAL_TIMEOUT;
        while std::time::Instant::now() < deadline {
            if self.active_profile()?.is_some_and(|active| {
                active.profile_id == profile_id
                    && active
                        .ipv4
                        .as_ref()
                        .and_then(|ipv4| ipv4.address.as_ref())
                        .is_some()
            }) {
                return Ok(());
            }
            thread::sleep(CHANGE_POLL_INTERVAL);
        }
        Err(WifiOperationError::new(
            "wifi_activation_timeout",
            "The saved Wi-Fi network did not become ready in time",
        ))
    }

    fn rollback_change_data(
        &self,
        pending: PendingNetworkManagerChange,
    ) -> Result<(), WifiOperationError> {
        if let Some((path, settings)) = pending.restore_connection {
            let _ = self.update_connection(&path, settings);
        }
        let _result: HashMap<String, u32> = self
            .manager()?
            .call("CheckpointRollback", &(pending.checkpoint_path,))
            .map_err(|_| {
                WifiOperationError::new(
                    "wifi_rollback_failed",
                    "The previous Wi-Fi connection could not be restored automatically",
                )
            })?;
        Ok(())
    }

    fn make_profile_preferred(
        &self,
        target_profile_id: &str,
    ) -> Result<Vec<(OwnedObjectPath, NmSettings)>, WifiOperationError> {
        let mut wifi_profiles = Vec::new();
        for path in self.connection_paths()? {
            let settings = self.get_settings(&path)?;
            if setting_string(&settings, "connection", "type").as_deref() != Some("802-11-wireless")
            {
                continue;
            }
            let Some(profile_id) = setting_string(&settings, "connection", "uuid") else {
                continue;
            };
            let priority =
                setting_i32(&settings, "connection", "autoconnect-priority").unwrap_or(0);
            wifi_profiles.push((path, settings, profile_id, priority));
        }
        if !wifi_profiles
            .iter()
            .any(|(_, _, profile_id, _)| profile_id == target_profile_id)
        {
            return Err(WifiOperationError::new(
                "wifi_profile_not_found",
                "The saved Wi-Fi network was not found",
            ));
        }

        let maximum = wifi_profiles
            .iter()
            .map(|(_, _, _, priority)| *priority)
            .max()
            .unwrap_or(0)
            .clamp(NM_AUTOCONNECT_PRIORITY_MIN, NM_AUTOCONNECT_PRIORITY_MAX);
        let target_priority = if maximum < NM_AUTOCONNECT_PRIORITY_MAX {
            maximum + 1
        } else {
            NM_AUTOCONNECT_PRIORITY_MAX
        };

        let mut updates = Vec::new();
        for (path, mut settings, profile_id, priority) in wifi_profiles {
            let next_priority = if profile_id == target_profile_id {
                target_priority
            } else if target_priority == NM_AUTOCONNECT_PRIORITY_MAX
                && priority == NM_AUTOCONNECT_PRIORITY_MAX
            {
                NM_AUTOCONNECT_PRIORITY_MAX - 1
            } else {
                continue;
            };
            let original = settings.clone();
            apply_preferred_profile_settings(
                &mut settings,
                profile_id == target_profile_id,
                next_priority,
            )?;
            updates.push((path, original, settings));
        }
        for (path, _, settings) in &updates {
            if let Err(error) = self.update_connection(path, settings.clone()) {
                for (restore_path, original, _) in &updates {
                    let _ = self.update_connection(restore_path, original.clone());
                }
                return Err(error);
            }
        }
        Ok(updates
            .into_iter()
            .map(|(path, original, _)| (path, original))
            .collect())
    }

    fn build_state(&self) -> Result<WifiState, WifiOperationError> {
        let radio_enabled: bool = self
            .manager()?
            .get_property("WirelessEnabled")
            .map_err(|_| WifiOperationError::operation_failed())?;
        let active_network = self.active_profile()?;
        let saved_profiles = self.saved_profiles(
            active_network
                .as_ref()
                .map(|active| active.profile_id.as_str()),
        )?;
        let nearby_networks = self.nearby_networks(&saved_profiles, active_network.as_ref())?;
        Ok(WifiState {
            schema_version: 2,
            status: WifiStateStatus::Ready,
            radio_enabled,
            active_network,
            saved_profiles,
            nearby_networks,
            scanned_at: self.last_scan_at,
            reported_at: epoch_seconds(),
        })
    }
}

impl WifiController for NetworkManagerWifiController {
    fn refresh(&mut self) -> Result<WifiState, WifiOperationError> {
        self.build_state()
    }

    fn scan(&mut self) -> Result<WifiState, WifiOperationError> {
        self.request_scan()?;
        self.last_scan_at = Some(epoch_seconds());
        self.build_state()
    }

    fn add_profile(
        &mut self,
        request: WifiAddProfileRequest,
    ) -> Result<WifiState, WifiOperationError> {
        validate_add_request(&request)?;
        let autoconnect_priority = self.new_profile_autoconnect_priority()?;
        let settings = build_profile_settings(&request, false, autoconnect_priority)?;
        let (path, _result): (OwnedObjectPath, HashMap<String, OwnedValue>) = self
            .settings()?
            .call(
                "AddConnection2",
                &(
                    settings.clone(),
                    NM_SETTINGS_ADD_TO_DISK,
                    HashMap::<String, OwnedValue>::new(),
                ),
            )
            .map_err(|_| {
                WifiOperationError::new(
                    "wifi_profile_add_failed",
                    "The Wi-Fi network could not be saved",
                )
            })?;

        // Preserve fields generated while NetworkManager normalizes the profile,
        // including its opaque UUID, before enabling low-priority autoconnect.
        let mut normalized_settings = self.get_settings(&path)?;
        normalized_settings
            .entry("connection".to_string())
            .or_default()
            .insert("autoconnect".to_string(), owned(true)?);
        self.update_connection(&path, normalized_settings)?;
        self.build_state()
    }

    fn update_profile(
        &mut self,
        request: WifiUpdateProfileRequest,
    ) -> Result<WifiState, WifiOperationError> {
        validate_update_request(&request)?;
        self.ensure_inactive(&request.profile_id)?;
        let (path, mut settings) = self.find_connection(&request.profile_id)?;
        let current_security = profile_security(&settings);
        if current_security == WifiSecurity::Enterprise {
            return Err(WifiOperationError::new(
                "wifi_enterprise_unsupported",
                "Enterprise Wi-Fi profiles cannot be changed here",
            ));
        }
        let next_security = request.security.unwrap_or(current_security);
        if !next_security.supports_profile_changes() {
            return Err(WifiOperationError::new(
                "wifi_enterprise_unsupported",
                "Enterprise Wi-Fi profiles cannot be changed here",
            ));
        }
        validate_password(next_security, request.password.as_deref(), false)?;

        if let Some(ssid) = request.ssid.as_ref() {
            settings
                .entry("connection".to_string())
                .or_default()
                .insert("id".to_string(), owned(format!("YoYoPod {ssid}"))?);
            settings
                .entry("802-11-wireless".to_string())
                .or_default()
                .insert("ssid".to_string(), owned(ssid.as_bytes().to_vec())?);
        }
        if let Some(hidden) = request.hidden {
            settings
                .entry("802-11-wireless".to_string())
                .or_default()
                .insert("hidden".to_string(), owned(hidden)?);
        }

        apply_security_settings(&mut settings, next_security, request.password.as_deref())?;
        if next_security != WifiSecurity::Open && request.password.is_none() {
            self.merge_existing_secret(&path, &mut settings)?;
        }
        self.update_connection(&path, settings)?;
        self.build_state()
    }

    fn forget_profile(&mut self, profile_id: &str) -> Result<WifiState, WifiOperationError> {
        self.ensure_inactive(profile_id)?;
        let (path, _) = self.find_connection(profile_id)?;
        self.proxy(path.as_str(), NM_CONNECTION_INTERFACE)?
            .call::<_, _, ()>("Delete", &())
            .map_err(|_| {
                WifiOperationError::new(
                    "wifi_profile_forget_failed",
                    "The saved Wi-Fi network could not be forgotten",
                )
            })?;
        self.build_state()
    }

    fn begin_activate_profile(
        &mut self,
        request: WifiActivateProfileRequest,
    ) -> Result<WifiChangeStart, WifiOperationError> {
        self.ensure_no_pending_change()?;
        validate_profile_id(&request.profile_id)?;
        let previous_profile_id = self.active_profile()?.map(|active| active.profile_id);
        if previous_profile_id.as_deref() == Some(request.profile_id.as_str()) {
            return Err(WifiOperationError::new(
                "wifi_profile_already_active",
                "This Wi-Fi network is already active",
            ));
        }
        let (connection_path, _) = self.find_connection(&request.profile_id)?;
        let checkpoint_path = self.create_checkpoint()?;
        self.pending_change = Some(PendingNetworkManagerChange {
            checkpoint_path,
            target_profile_id: request.profile_id.clone(),
            previous_profile_id,
            preference: request.preference,
            restore_connection: None,
        });
        if let Err(error) = self
            .activate_connection_path(&connection_path)
            .and_then(|_| self.wait_for_active_profile(&request.profile_id))
        {
            let _ = self.rollback_pending_change();
            return Err(error);
        }
        Ok(WifiChangeStart::Pending {
            profile_id: request.profile_id,
            operation: WifiChangeOperation::ActivateProfile,
        })
    }

    fn begin_update_ipv4(
        &mut self,
        request: WifiUpdateIpv4Request,
    ) -> Result<WifiChangeStart, WifiOperationError> {
        self.ensure_no_pending_change()?;
        validate_profile_id(&request.profile_id)?;
        validate_ipv4_config(&request.ipv4)?;
        let active = self.active_profile()?;
        let is_active = active
            .as_ref()
            .is_some_and(|profile| profile.profile_id == request.profile_id);
        let (connection_path, mut settings) = self.find_connection(&request.profile_id)?;
        let previous_settings = settings.clone();
        apply_ipv4_settings(&mut settings, &request.ipv4)?;

        if !is_active {
            self.update_connection(&connection_path, settings)?;
            return self.build_state().map(WifiChangeStart::Immediate);
        }

        let checkpoint_path = self.create_checkpoint()?;
        self.pending_change = Some(PendingNetworkManagerChange {
            checkpoint_path,
            target_profile_id: request.profile_id.clone(),
            previous_profile_id: active.map(|profile| profile.profile_id),
            preference: WifiActivationPreference::SessionOnly,
            restore_connection: Some((connection_path.clone(), previous_settings)),
        });
        let result = self
            .update_connection(&connection_path, settings)
            .and_then(|_| self.activate_connection_path(&connection_path))
            .and_then(|_| self.wait_for_active_profile(&request.profile_id));
        if let Err(error) = result {
            let _ = self.rollback_pending_change();
            return Err(error);
        }
        Ok(WifiChangeStart::Pending {
            profile_id: request.profile_id,
            operation: WifiChangeOperation::UpdateIpv4,
        })
    }

    fn confirm_pending_change(&mut self) -> Result<WifiState, WifiOperationError> {
        let pending = self.pending_change.take().ok_or_else(|| {
            WifiOperationError::new(
                "wifi_change_not_pending",
                "There is no Wi-Fi connectivity change to confirm",
            )
        })?;
        let priority_restore = if pending.preference == WifiActivationPreference::Preferred {
            match self.make_profile_preferred(&pending.target_profile_id) {
                Ok(restore) => restore,
                Err(error) => {
                    let _ = self.rollback_change_data(pending);
                    return Err(error);
                }
            }
        } else {
            Vec::new()
        };
        if self
            .manager()?
            .call::<_, _, ()>("CheckpointDestroy", &(pending.checkpoint_path.clone(),))
            .is_err()
        {
            for (path, settings) in priority_restore {
                let _ = self.update_connection(&path, settings);
            }
            let _ = self.rollback_change_data(pending);
            return Err(WifiOperationError::new(
                "wifi_checkpoint_commit_failed",
                "The Wi-Fi connectivity change could not be committed",
            ));
        }
        self.build_state()
    }

    fn rollback_pending_change(&mut self) -> Result<WifiState, WifiOperationError> {
        let pending = self.pending_change.take().ok_or_else(|| {
            WifiOperationError::new(
                "wifi_change_not_pending",
                "There is no Wi-Fi connectivity change to restore",
            )
        })?;
        let previous_profile_id = pending.previous_profile_id.clone();
        self.rollback_change_data(pending)?;
        if let Some(profile_id) = previous_profile_id {
            let deadline = std::time::Instant::now() + Duration::from_secs(10);
            while std::time::Instant::now() < deadline {
                if self
                    .active_profile()?
                    .is_some_and(|active| active.profile_id == profile_id)
                {
                    break;
                }
                thread::sleep(CHANGE_POLL_INTERVAL);
            }
        }
        self.build_state()
    }
}

#[derive(Debug, Clone)]
struct AccessPointFact {
    ssid: String,
    security: WifiSecurity,
    signal_percent: u8,
}

fn root_object_path() -> OwnedObjectPath {
    OwnedObjectPath::try_from("/").expect("root D-Bus object path should be valid")
}

fn validate_profile_id(profile_id: &str) -> Result<(), WifiOperationError> {
    if profile_id.trim().is_empty() || profile_id.len() > 80 {
        return Err(WifiOperationError::new(
            "wifi_invalid_profile_id",
            "The saved Wi-Fi network reference is invalid",
        ));
    }
    Ok(())
}

fn usable_ipv4(address: Ipv4Addr) -> bool {
    let octets = address.octets();
    !address.is_unspecified()
        && !address.is_loopback()
        && !address.is_multicast()
        && octets != [255, 255, 255, 255]
        && octets[0] != 0
}

fn ipv4_bits(address: Ipv4Addr) -> u32 {
    u32::from_be_bytes(address.octets())
}

fn validate_ipv4_config(config: &WifiIpv4Config) -> Result<(), WifiOperationError> {
    if config.mode == WifiIpv4Mode::Dhcp {
        if config.address.is_some()
            || config.prefix_length.is_some()
            || config.gateway.is_some()
            || !config.dns_servers.is_empty()
        {
            return Err(WifiOperationError::new(
                "wifi_invalid_ipv4_config",
                "DHCP does not accept static IPv4 fields",
            ));
        }
        return Ok(());
    }

    let address = config
        .address
        .as_deref()
        .and_then(|value| value.parse::<Ipv4Addr>().ok())
        .filter(|address| usable_ipv4(*address))
        .ok_or_else(|| {
            WifiOperationError::new(
                "wifi_invalid_ipv4_address",
                "Enter a usable static IPv4 address",
            )
        })?;
    let prefix = config
        .prefix_length
        .filter(|prefix| (1..=30).contains(prefix))
        .ok_or_else(|| {
            WifiOperationError::new(
                "wifi_invalid_ipv4_prefix",
                "Use an IPv4 prefix length between 1 and 30",
            )
        })?;
    let gateway = config
        .gateway
        .as_deref()
        .and_then(|value| value.parse::<Ipv4Addr>().ok())
        .filter(|gateway| usable_ipv4(*gateway))
        .ok_or_else(|| {
            WifiOperationError::new("wifi_invalid_ipv4_gateway", "Enter a usable IPv4 gateway")
        })?;
    let mask = u32::MAX << (32 - u32::from(prefix));
    let network = ipv4_bits(address) & mask;
    let broadcast = network | !mask;
    if ipv4_bits(address) == network
        || ipv4_bits(address) == broadcast
        || ipv4_bits(gateway) == network
        || ipv4_bits(gateway) == broadcast
        || (ipv4_bits(gateway) & mask) != network
    {
        return Err(WifiOperationError::new(
            "wifi_invalid_ipv4_subnet",
            "The static address and gateway must be usable addresses in the same subnet",
        ));
    }
    if !(1..=3).contains(&config.dns_servers.len())
        || config.dns_servers.iter().any(|value| {
            value
                .parse::<Ipv4Addr>()
                .map(|address| !usable_ipv4(address))
                .unwrap_or(true)
        })
    {
        return Err(WifiOperationError::new(
            "wifi_invalid_ipv4_dns",
            "Enter one to three usable IPv4 DNS servers",
        ));
    }
    Ok(())
}

fn validate_ssid(ssid: &str) -> Result<(), WifiOperationError> {
    let length = ssid.as_bytes().len();
    if ssid.trim().is_empty() || length > 32 || ssid.chars().any(|character| character.is_control())
    {
        return Err(WifiOperationError::new(
            "wifi_invalid_ssid",
            "Enter a Wi-Fi name between 1 and 32 bytes",
        ));
    }
    Ok(())
}

fn ensure_profile_inactive(
    active: Option<&WifiActiveNetwork>,
    profile_id: &str,
) -> Result<(), WifiOperationError> {
    if active.is_some_and(|active| active.profile_id == profile_id) {
        return Err(WifiOperationError::new(
            "wifi_active_profile_immutable",
            "The active Wi-Fi network cannot be changed or forgotten",
        ));
    }
    Ok(())
}

fn settings_match_wifi_profile(settings: &NmSettings, profile_id: &str) -> bool {
    setting_string(settings, "connection", "type").as_deref() == Some("802-11-wireless")
        && setting_string(settings, "connection", "uuid").as_deref() == Some(profile_id)
}

fn apply_preferred_profile_settings(
    settings: &mut NmSettings,
    is_target: bool,
    priority: i32,
) -> Result<(), WifiOperationError> {
    let connection = settings.entry("connection".to_string()).or_default();
    if is_target {
        connection.insert("autoconnect".to_string(), owned(true)?);
    }
    connection.insert("autoconnect-priority".to_string(), owned(priority)?);
    Ok(())
}

fn lower_autoconnect_priority(active_priority: i32) -> Result<i32, WifiOperationError> {
    if !(NM_AUTOCONNECT_PRIORITY_MIN..=NM_AUTOCONNECT_PRIORITY_MAX).contains(&active_priority)
        || active_priority == NM_AUTOCONNECT_PRIORITY_MIN
    {
        return Err(WifiOperationError::new(
            "wifi_profile_priority_unavailable",
            "Another Wi-Fi network cannot be saved safely while this profile is active",
        ));
    }
    Ok(active_priority - 1)
}

fn validate_password(
    security: WifiSecurity,
    password: Option<&str>,
    required: bool,
) -> Result<(), WifiOperationError> {
    if security == WifiSecurity::Enterprise {
        return Err(WifiOperationError::new(
            "wifi_enterprise_unsupported",
            "Enterprise Wi-Fi profiles cannot be added or changed here",
        ));
    }
    if security == WifiSecurity::Open {
        if password.is_some_and(|value| !value.is_empty()) {
            return Err(WifiOperationError::new(
                "wifi_open_password_not_allowed",
                "Open Wi-Fi networks do not use a password",
            ));
        }
        return Ok(());
    }
    let Some(password) = password.filter(|value| !value.is_empty()) else {
        return if required {
            Err(WifiOperationError::new(
                "wifi_password_required",
                "Enter the Wi-Fi password",
            ))
        } else {
            Ok(())
        };
    };
    let valid = (8..=63).contains(&password.len())
        || (password.len() == 64 && password.bytes().all(|byte| byte.is_ascii_hexdigit()));
    if !valid {
        return Err(WifiOperationError::new(
            "wifi_invalid_password",
            "Use 8 to 63 characters, or a 64-character hexadecimal key",
        ));
    }
    Ok(())
}

fn validate_add_request(request: &WifiAddProfileRequest) -> Result<(), WifiOperationError> {
    validate_ssid(&request.ssid)?;
    validate_password(request.security, request.password.as_deref(), true)
}

fn validate_update_request(request: &WifiUpdateProfileRequest) -> Result<(), WifiOperationError> {
    validate_profile_id(&request.profile_id)?;
    if let Some(ssid) = request.ssid.as_deref() {
        validate_ssid(ssid)?;
    }
    if let Some(security) = request.security {
        validate_password(security, request.password.as_deref(), false)?;
    }
    Ok(())
}

fn apply_ipv4_settings(
    settings: &mut NmSettings,
    config: &WifiIpv4Config,
) -> Result<(), WifiOperationError> {
    validate_ipv4_config(config)?;
    let group = settings.entry("ipv4".to_string()).or_default();
    for key in ["address-data", "addresses", "gateway", "dns", "dns-data"] {
        group.remove(key);
    }
    if config.mode == WifiIpv4Mode::Dhcp {
        group.insert("method".to_string(), owned("auto".to_string())?);
        group.insert("ignore-auto-dns".to_string(), owned(false)?);
        return Ok(());
    }

    let address = config.address.clone().unwrap_or_default();
    let prefix = u32::from(config.prefix_length.unwrap_or_default());
    let address_data = vec![HashMap::from([
        ("address".to_string(), owned(address)?),
        ("prefix".to_string(), owned(prefix)?),
    ])];
    group.insert("method".to_string(), owned("manual".to_string())?);
    group.insert("address-data".to_string(), owned(address_data)?);
    group.insert(
        "gateway".to_string(),
        owned(config.gateway.clone().unwrap_or_default())?,
    );
    group.insert("dns-data".to_string(), owned(config.dns_servers.clone())?);
    group.insert("ignore-auto-dns".to_string(), owned(true)?);
    Ok(())
}

fn build_profile_settings(
    request: &WifiAddProfileRequest,
    autoconnect: bool,
    autoconnect_priority: i32,
) -> Result<NmSettings, WifiOperationError> {
    let mut settings = NmSettings::new();
    settings.insert(
        "connection".to_string(),
        HashMap::from([
            (
                "id".to_string(),
                owned(format!("YoYoPod {}", request.ssid))?,
            ),
            ("type".to_string(), owned("802-11-wireless".to_string())?),
            ("autoconnect".to_string(), owned(autoconnect)?),
            (
                "autoconnect-priority".to_string(),
                owned(autoconnect_priority)?,
            ),
        ]),
    );
    settings.insert(
        "802-11-wireless".to_string(),
        HashMap::from([
            ("ssid".to_string(), owned(request.ssid.as_bytes().to_vec())?),
            ("mode".to_string(), owned("infrastructure".to_string())?),
            ("hidden".to_string(), owned(request.hidden)?),
        ]),
    );
    settings.insert(
        "ipv4".to_string(),
        HashMap::from([("method".to_string(), owned("auto".to_string())?)]),
    );
    settings.insert(
        "ipv6".to_string(),
        HashMap::from([("method".to_string(), owned("auto".to_string())?)]),
    );
    apply_security_settings(&mut settings, request.security, request.password.as_deref())?;
    Ok(settings)
}

fn apply_security_settings(
    settings: &mut NmSettings,
    security: WifiSecurity,
    password: Option<&str>,
) -> Result<(), WifiOperationError> {
    if security == WifiSecurity::Open {
        settings.remove("802-11-wireless-security");
        return Ok(());
    }
    if security == WifiSecurity::Enterprise {
        return Err(WifiOperationError::new(
            "wifi_enterprise_unsupported",
            "Enterprise Wi-Fi profiles cannot be added or changed here",
        ));
    }
    let group = settings
        .entry("802-11-wireless-security".to_string())
        .or_default();
    group.insert(
        "key-mgmt".to_string(),
        owned(match security {
            WifiSecurity::Wpa3Personal => "sae".to_string(),
            _ => "wpa-psk".to_string(),
        })?,
    );
    if let Some(password) = password.filter(|value| !value.is_empty()) {
        group.insert("psk".to_string(), owned(password.to_string())?);
    } else {
        group.remove("psk");
    }
    Ok(())
}

fn owned<T>(value: T) -> Result<OwnedValue, WifiOperationError>
where
    T: Into<Value<'static>>,
{
    let value: Value<'static> = value.into();
    value
        .try_to_owned()
        .map_err(|_| WifiOperationError::operation_failed())
}

fn setting_value<'a>(settings: &'a NmSettings, group: &str, key: &str) -> Option<&'a OwnedValue> {
    settings.get(group)?.get(key)
}

fn setting_string(settings: &NmSettings, group: &str, key: &str) -> Option<String> {
    String::try_from(setting_value(settings, group, key)?.clone()).ok()
}

fn setting_bool(settings: &NmSettings, group: &str, key: &str) -> Option<bool> {
    bool::try_from(setting_value(settings, group, key)?.clone()).ok()
}

fn setting_i32(settings: &NmSettings, group: &str, key: &str) -> Option<i32> {
    i32::try_from(setting_value(settings, group, key)?.clone()).ok()
}

fn setting_string_array(settings: &NmSettings, group: &str, key: &str) -> Vec<String> {
    Vec::<String>::try_from(
        setting_value(settings, group, key)
            .cloned()
            .unwrap_or_else(|| {
                owned(Vec::<String>::new()).expect("empty string array should encode")
            }),
    )
    .unwrap_or_default()
}

fn setting_dict_array(
    settings: &NmSettings,
    group: &str,
    key: &str,
) -> Vec<HashMap<String, OwnedValue>> {
    setting_value(settings, group, key)
        .cloned()
        .and_then(|value| Vec::<HashMap<String, OwnedValue>>::try_from(value).ok())
        .unwrap_or_default()
}

fn dict_string(values: &HashMap<String, OwnedValue>, key: &str) -> Option<String> {
    String::try_from(values.get(key)?.clone()).ok()
}

fn dict_u32(values: &HashMap<String, OwnedValue>, key: &str) -> Option<u32> {
    u32::try_from(values.get(key)?.clone()).ok()
}

fn profile_ipv4_config(settings: &NmSettings) -> WifiIpv4Config {
    if setting_string(settings, "ipv4", "method").as_deref() != Some("manual") {
        return WifiIpv4Config::dhcp();
    }
    let address_data = setting_dict_array(settings, "ipv4", "address-data");
    let first_address = address_data.first();
    WifiIpv4Config {
        mode: WifiIpv4Mode::Static,
        address: first_address.and_then(|entry| dict_string(entry, "address")),
        prefix_length: first_address
            .and_then(|entry| dict_u32(entry, "prefix"))
            .and_then(|value| u8::try_from(value).ok()),
        gateway: setting_string(settings, "ipv4", "gateway")
            .filter(|value| !value.trim().is_empty()),
        dns_servers: setting_string_array(settings, "ipv4", "dns-data")
            .into_iter()
            .take(3)
            .collect(),
    }
}

fn setting_ssid(settings: &NmSettings) -> Option<String> {
    let bytes =
        Vec::<u8>::try_from(setting_value(settings, "802-11-wireless", "ssid")?.clone()).ok()?;
    Some(sanitize_ssid(&bytes))
}

fn sanitize_ssid(bytes: &[u8]) -> String {
    let mut sanitized = String::new();
    for character in String::from_utf8_lossy(bytes)
        .chars()
        .filter(|character| !character.is_control())
    {
        if sanitized.len() + character.len_utf8() > 32 {
            break;
        }
        sanitized.push(character);
    }
    sanitized
}

fn profile_security(settings: &NmSettings) -> WifiSecurity {
    match setting_string(settings, "802-11-wireless-security", "key-mgmt")
        .unwrap_or_default()
        .to_ascii_lowercase()
        .as_str()
    {
        "sae" | "owe" => WifiSecurity::Wpa3Personal,
        "wpa-eap" | "ieee8021x" => WifiSecurity::Enterprise,
        "wpa-psk" | "wpa-none" => WifiSecurity::Wpa2Personal,
        _ => WifiSecurity::Open,
    }
}

fn access_point_security(flags: u32, wpa_flags: u32, rsn_flags: u32) -> WifiSecurity {
    let combined = wpa_flags | rsn_flags;
    if combined & NM_AP_SEC_KEY_MGMT_802_1X != 0 {
        WifiSecurity::Enterprise
    } else if combined & (NM_AP_SEC_KEY_MGMT_SAE | NM_AP_SEC_KEY_MGMT_OWE) != 0 {
        WifiSecurity::Wpa3Personal
    } else if flags & NM_AP_FLAGS_PRIVACY != 0 || combined != 0 {
        WifiSecurity::Wpa2Personal
    } else {
        WifiSecurity::Open
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

    #[test]
    fn access_point_security_is_sanitized_to_supported_labels() {
        assert_eq!(access_point_security(0, 0, 0), WifiSecurity::Open);
        assert_eq!(
            access_point_security(NM_AP_FLAGS_PRIVACY, 0, 0),
            WifiSecurity::Wpa2Personal
        );
        assert_eq!(
            access_point_security(NM_AP_FLAGS_PRIVACY, 0, NM_AP_SEC_KEY_MGMT_SAE),
            WifiSecurity::Wpa3Personal
        );
        assert_eq!(
            access_point_security(NM_AP_FLAGS_PRIVACY, 0, NM_AP_SEC_KEY_MGMT_802_1X),
            WifiSecurity::Enterprise
        );
    }

    #[test]
    fn wifi_password_validation_accepts_passphrases_and_hex_keys() {
        assert!(validate_password(WifiSecurity::Wpa2Personal, Some("eight888"), true).is_ok());
        assert!(validate_password(WifiSecurity::Wpa3Personal, Some(&"a".repeat(64)), true).is_ok());
        assert!(validate_password(WifiSecurity::Wpa2Personal, Some("short"), true).is_err());
        assert!(validate_password(WifiSecurity::Open, Some("unexpected"), true).is_err());
    }

    #[test]
    fn wifi_ssids_reject_controls_and_sanitize_to_thirty_two_bytes() {
        assert!(validate_ssid("Family\nWiFi").is_err());
        assert_eq!(
            sanitize_ssid("123456789012345678901234567890é".as_bytes()).len(),
            32
        );
        assert_eq!(sanitize_ssid(b"Family\nWiFi"), "FamilyWiFi");
    }

    #[test]
    fn active_profile_is_immutable_even_if_a_caller_requests_a_change() {
        let active = WifiActiveNetwork {
            profile_id: "active-profile".to_string(),
            ssid: "Family WiFi".to_string(),
            security: WifiSecurity::Wpa2Personal,
            signal_percent: 80,
            ipv4: None,
        };

        let error = ensure_profile_inactive(Some(&active), "active-profile")
            .expect_err("active profile must be protected locally");

        assert_eq!(error.code, "wifi_active_profile_immutable");
        assert!(ensure_profile_inactive(Some(&active), "another-profile").is_ok());
    }

    #[test]
    fn wifi_profile_lookup_rejects_non_wifi_connections_with_the_same_uuid() {
        let profile_id = "11111111-1111-4111-8111-111111111111";
        let wifi = NmSettings::from([(
            "connection".to_string(),
            HashMap::from([
                ("uuid".to_string(), owned(profile_id.to_string()).unwrap()),
                (
                    "type".to_string(),
                    owned("802-11-wireless".to_string()).unwrap(),
                ),
            ]),
        )]);
        let ethernet = NmSettings::from([(
            "connection".to_string(),
            HashMap::from([
                ("uuid".to_string(), owned(profile_id.to_string()).unwrap()),
                (
                    "type".to_string(),
                    owned("802-3-ethernet".to_string()).unwrap(),
                ),
            ]),
        )]);

        assert!(settings_match_wifi_profile(&wifi, profile_id));
        assert!(!settings_match_wifi_profile(&ethernet, profile_id));
    }

    #[test]
    fn preferred_profile_demotion_preserves_disabled_autoconnect() {
        let mut demoted = NmSettings::from([(
            "connection".to_string(),
            HashMap::from([
                ("autoconnect".to_string(), owned(false).unwrap()),
                ("autoconnect-priority".to_string(), owned(999_i32).unwrap()),
            ]),
        )]);
        apply_preferred_profile_settings(&mut demoted, false, 998).unwrap();
        assert_eq!(
            setting_bool(&demoted, "connection", "autoconnect"),
            Some(false)
        );
        assert_eq!(
            setting_i32(&demoted, "connection", "autoconnect-priority"),
            Some(998)
        );

        apply_preferred_profile_settings(&mut demoted, true, 999).unwrap();
        assert_eq!(
            setting_bool(&demoted, "connection", "autoconnect"),
            Some(true)
        );
    }

    #[test]
    fn new_profile_priority_is_strictly_lower_than_the_active_profile() {
        assert_eq!(lower_autoconnect_priority(0).unwrap(), -1);
        assert_eq!(lower_autoconnect_priority(-998).unwrap(), -999);
        assert!(lower_autoconnect_priority(-999).is_err());
        assert!(lower_autoconnect_priority(1_000).is_err());
    }

    #[test]
    fn new_profile_settings_keep_autoconnect_blocked_until_the_profile_is_saved() {
        let request = WifiAddProfileRequest {
            ssid: "Family WiFi".to_string(),
            security: WifiSecurity::Wpa2Personal,
            password: Some("safe-test-passphrase".to_string()),
            hidden: false,
        };

        let settings = build_profile_settings(&request, false, -1).unwrap();

        assert_eq!(
            setting_bool(&settings, "connection", "autoconnect"),
            Some(false)
        );
        assert_eq!(
            setting_i32(&settings, "connection", "autoconnect-priority"),
            Some(-1)
        );
    }

    #[test]
    fn static_ipv4_requires_a_gateway_in_the_same_subnet_and_dns() {
        let valid = WifiIpv4Config {
            mode: WifiIpv4Mode::Static,
            address: Some("192.168.50.40".to_string()),
            prefix_length: Some(24),
            gateway: Some("192.168.50.1".to_string()),
            dns_servers: vec!["1.1.1.1".to_string()],
        };
        assert!(validate_ipv4_config(&valid).is_ok());
        assert!(validate_ipv4_config(&WifiIpv4Config {
            gateway: Some("192.168.60.1".to_string()),
            ..valid.clone()
        })
        .is_err());
        assert!(validate_ipv4_config(&WifiIpv4Config {
            dns_servers: Vec::new(),
            ..valid
        })
        .is_err());
    }

    #[test]
    fn ipv4_settings_round_trip_without_hardware_paths_or_secrets() {
        let mut settings = NmSettings::new();
        let config = WifiIpv4Config {
            mode: WifiIpv4Mode::Static,
            address: Some("10.20.30.40".to_string()),
            prefix_length: Some(24),
            gateway: Some("10.20.30.1".to_string()),
            dns_servers: vec!["9.9.9.9".to_string(), "1.1.1.1".to_string()],
        };
        apply_ipv4_settings(&mut settings, &config).unwrap();
        assert_eq!(profile_ipv4_config(&settings), config);

        apply_ipv4_settings(&mut settings, &WifiIpv4Config::dhcp()).unwrap();
        assert_eq!(profile_ipv4_config(&settings), WifiIpv4Config::dhcp());
    }
}
