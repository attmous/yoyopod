use std::collections::{HashMap, HashSet};
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
const NM_ACCESS_POINT_INTERFACE: &str = "org.freedesktop.NetworkManager.AccessPoint";
const NM_DEVICE_TYPE_WIFI: u32 = 2;
const NM_SETTINGS_ADD_TO_DISK: u32 = 0x1;
const NM_SETTINGS_UPDATE_TO_DISK: u32 = 0x1;
const NM_AP_FLAGS_PRIVACY: u32 = 0x1;
const NM_AP_SEC_KEY_MGMT_802_1X: u32 = 0x200;
const NM_AP_SEC_KEY_MGMT_SAE: u32 = 0x400;
const NM_AP_SEC_KEY_MGMT_OWE: u32 = 0x800;
const MAX_SAVED_PROFILES: usize = 32;
const MAX_NEARBY_NETWORKS: usize = 64;
const SCAN_WAIT_TIMEOUT: Duration = Duration::from_secs(4);
const SCAN_POLL_INTERVAL: Duration = Duration::from_millis(200);

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

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct WifiActiveNetwork {
    pub profile_id: String,
    pub ssid: String,
    pub security: WifiSecurity,
    pub signal_percent: u8,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct WifiSavedProfile {
    pub profile_id: String,
    pub ssid: String,
    pub security: WifiSecurity,
    pub hidden: bool,
    pub active: bool,
    pub autoconnect: bool,
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
            schema_version: 1,
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
}

pub struct NetworkManagerWifiController {
    connection: Connection,
    last_scan_at: Option<u64>,
}

impl NetworkManagerWifiController {
    pub fn connect() -> Result<Self, WifiOperationError> {
        Connection::system()
            .map(|connection| Self {
                connection,
                last_scan_at: None,
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
            if setting_string(&settings, "connection", "uuid").as_deref() == Some(profile_id) {
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
            let specific: OwnedObjectPath = proxy
                .get_property("SpecificObject")
                .map_err(|_| WifiOperationError::operation_failed())?;
            let (ssid, security, signal_percent) = if specific.as_str() == "/" {
                let (_, settings) = self.find_connection(&profile_id)?;
                (
                    setting_ssid(&settings).unwrap_or_default(),
                    profile_security(&settings),
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
            }));
        }

        Ok(None)
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
            schema_version: 1,
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
        let settings = build_profile_settings(&request, false)?;
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
}

#[derive(Debug, Clone)]
struct AccessPointFact {
    ssid: String,
    security: WifiSecurity,
    signal_percent: u8,
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
    if request.profile_id.trim().is_empty() || request.profile_id.len() > 80 {
        return Err(WifiOperationError::new(
            "wifi_invalid_profile_id",
            "The saved Wi-Fi network reference is invalid",
        ));
    }
    if let Some(ssid) = request.ssid.as_deref() {
        validate_ssid(ssid)?;
    }
    if let Some(security) = request.security {
        validate_password(security, request.password.as_deref(), false)?;
    }
    Ok(())
}

fn build_profile_settings(
    request: &WifiAddProfileRequest,
    autoconnect: bool,
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
            ("autoconnect-priority".to_string(), owned(-100_i32)?),
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
        };

        let error = ensure_profile_inactive(Some(&active), "active-profile")
            .expect_err("active profile must be protected locally");

        assert_eq!(error.code, "wifi_active_profile_immutable");
        assert!(ensure_profile_inactive(Some(&active), "another-profile").is_ok());
    }
}
