//! On-device Wi-Fi onboarding: put the radio into Access Point mode, serve a
//! captive-portal web page, and connect the device to the home network the user
//! picks there.
//!
//! The device has a single Wi-Fi radio, so it cannot host an AP and scan at the
//! same time. The flow is therefore: scan + cache nearby networks, bring up a
//! WPA2 hotspot (NetworkManager `mode=ap`, `ipv4=shared`), run the portal, and -
//! once the user submits a network - tear the hotspot down and join as a station.
//!
//! The whole lifecycle runs on a background thread; status updates flow back to
//! the worker over a channel and are surfaced to the UI as `wifi_provisioning_state`.

use std::collections::HashMap;
use std::io::Read;
use std::sync::mpsc::{self, Receiver, Sender, TryRecvError};
use std::thread::{self, JoinHandle};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use serde::Serialize;
use serde_json::json;
use tiny_http::{Header, Method, Response, Server};
use zbus::blocking::{Connection, Proxy};
use zbus::zvariant::{OwnedObjectPath, OwnedValue, Value};

use crate::wifi::{NetworkManagerWifiController, WifiController, WifiSecurity};

const NM_SERVICE: &str = "org.freedesktop.NetworkManager";
const NM_PATH: &str = "/org/freedesktop/NetworkManager";
const NM_INTERFACE: &str = "org.freedesktop.NetworkManager";
const NM_SETTINGS_PATH: &str = "/org/freedesktop/NetworkManager/Settings";
const NM_SETTINGS_INTERFACE: &str = "org.freedesktop.NetworkManager.Settings";
const NM_CONNECTION_INTERFACE: &str = "org.freedesktop.NetworkManager.Settings.Connection";
const NM_DEVICE_INTERFACE: &str = "org.freedesktop.NetworkManager.Device";
const NM_ACTIVE_CONNECTION_INTERFACE: &str = "org.freedesktop.NetworkManager.Connection.Active";
const NM_DEVICE_TYPE_WIFI: u32 = 2;
const NM_SETTINGS_ADD_TO_DISK: u32 = 0x1;
const NM_ACTIVE_STATE_ACTIVATED: u32 = 2;
const NM_ACTIVE_STATE_DEACTIVATED: u32 = 4;
/// How long to wait for the chosen station connection to actually activate
/// before reporting failure (wrong password, DHCP timeout, etc.).
const CONNECT_TIMEOUT: Duration = Duration::from_secs(30);
const CONNECT_POLL: Duration = Duration::from_millis(500);
/// How long to wait for the AP to reach ACTIVATED before announcing the portal.
/// NetworkManager's shared-mode setup (starting dnsmasq for DHCP/DNS) can take
/// ~25s on the Pi, so keep this generous; a timeout is treated as "still coming
/// up" rather than a failure (the AP has already begun broadcasting by then).
const AP_ACTIVATE_TIMEOUT: Duration = Duration::from_secs(40);

/// NetworkManager `ipv4.method=shared` always hands the AP host this address and
/// runs a DHCP+DNS server for clients, so the portal lives here on port 80.
const PORTAL_GATEWAY: &str = "10.42.0.1";
const PORTAL_BIND: &str = "0.0.0.0:80";
const AP_CONNECTION_ID: &str = "YoYoPod Setup";
const PORTAL_POLL: Duration = Duration::from_millis(250);
/// If the user has not submitted a network within this window, tear the hotspot
/// down and let NetworkManager auto-reconnect the previously active profile so
/// the device returns online on its own.
const AP_TIMEOUT: Duration = Duration::from_secs(120);

/// Captive-portal probe URLs various mobile OSes fetch to detect a login page;
/// answering with a redirect makes the setup page pop up automatically.
const PROBE_PATHS: &[&str] = &[
    "/generate_204",
    "/gen_204",
    "/hotspot-detect.html",
    "/library/test/success.html",
    "/ncsi.txt",
    "/connecttest.txt",
    "/canonical.html",
    "/success.txt",
];

/// Snapshot of the onboarding flow, serialized verbatim into the
/// `wifi_provisioning_state` event. Field names match the UI's
/// `WifiSetupRuntimeSnapshot`. The home-network password is never stored here.
#[derive(Debug, Clone, Serialize)]
pub struct WifiProvisioningState {
    pub schema_version: u16,
    pub active: bool,
    pub phase: String,
    pub ap_ssid: String,
    pub ap_password: String,
    pub portal_url: String,
    pub qr_payload: String,
    pub status_text: String,
    pub error: String,
    pub reported_at: u64,
}

impl WifiProvisioningState {
    fn base() -> Self {
        Self {
            schema_version: 1,
            active: true,
            phase: String::new(),
            ap_ssid: String::new(),
            ap_password: String::new(),
            portal_url: String::new(),
            qr_payload: String::new(),
            status_text: String::new(),
            error: String::new(),
            reported_at: epoch_seconds(),
        }
    }

    fn phase(phase: &str, status: &str) -> Self {
        Self {
            phase: phase.to_string(),
            status_text: status.to_string(),
            ..Self::base()
        }
    }

    /// The terminal "not provisioning" state the worker folds in once the flow
    /// ends, so the UI leaves the setup screen's active state.
    pub fn idle() -> Self {
        Self {
            active: false,
            phase: "idle".to_string(),
            ..Self::base()
        }
    }

    pub fn error(message: &str) -> Self {
        Self {
            active: false,
            phase: "error".to_string(),
            error: message.to_string(),
            status_text: message.to_string(),
            ..Self::base()
        }
    }
}

/// A nearby network as advertised to the portal page.
#[derive(Debug, Clone, Serialize)]
struct PortalNetwork {
    ssid: String,
    security: String,
    signal_percent: u8,
    saved: bool,
}

/// Handle the worker keeps while onboarding is active.
pub struct WifiProvisioner {
    status_rx: Receiver<WifiProvisioningState>,
    stop_tx: Sender<()>,
    handle: Option<JoinHandle<()>>,
}

impl WifiProvisioner {
    /// Spawn the onboarding worker thread. Returns the handle plus the initial
    /// state to emit immediately.
    pub fn start() -> (Self, WifiProvisioningState) {
        let (status_tx, status_rx) = mpsc::channel();
        let (stop_tx, stop_rx) = mpsc::channel();
        let handle = thread::spawn(move || run_flow(&status_tx, &stop_rx));
        (
            Self {
                status_rx,
                stop_tx,
                handle: Some(handle),
            },
            WifiProvisioningState::phase("starting", "Starting Wi-Fi setup..."),
        )
    }

    /// Drain any status updates produced since the last poll.
    pub fn drain(&mut self) -> Vec<WifiProvisioningState> {
        self.status_rx.try_iter().collect()
    }

    /// True once the background thread has finished (connected, failed, or torn down).
    pub fn finished(&self) -> bool {
        self.handle.as_ref().is_none_or(|handle| handle.is_finished())
    }

    /// Join a thread that has already finished on its own (its terminal state
    /// was delivered via `drain`), without emitting anything further.
    pub fn join(mut self) {
        if let Some(handle) = self.handle.take() {
            let _ = handle.join();
        }
    }

    /// Signal teardown and wait for the thread to restore station mode.
    pub fn stop(mut self) -> WifiProvisioningState {
        let _ = self.stop_tx.send(());
        if let Some(handle) = self.handle.take() {
            let _ = handle.join();
        }
        // Flush any final state the thread emitted, else report idle.
        self.status_rx
            .try_iter()
            .last()
            .unwrap_or_else(WifiProvisioningState::idle)
    }
}

/// The onboarding state machine, run on the background thread.
fn run_flow(status_tx: &Sender<WifiProvisioningState>, stop_rx: &Receiver<()>) {
    let networks = scan_networks();
    let _ = status_tx.send(WifiProvisioningState::phase(
        "starting",
        "Setting up hotspot...",
    ));

    let credentials = ApCredentials::generate();
    let hotspot = match Hotspot::start(&credentials) {
        Ok(hotspot) => hotspot,
        Err(error) => {
            let _ = status_tx.send(WifiProvisioningState::error(&error));
            return;
        }
    };

    // Bind the captive portal BEFORE announcing it. If port 80 is unavailable
    // (the service is missing CAP_NET_BIND_SERVICE, or something else holds the
    // port) surface an error and tear the hotspot down, rather than leaving a
    // "ready" hotspot with no page behind it and blocking forever.
    let server = match Server::http(PORTAL_BIND) {
        Ok(server) => server,
        Err(_) => {
            hotspot.stop();
            let _ = status_tx.send(WifiProvisioningState::error(
                "Wi-Fi setup could not open its setup page. Please try again.",
            ));
            return;
        }
    };

    let ready = WifiProvisioningState {
        phase: "portal_ready".to_string(),
        ap_ssid: credentials.ssid.clone(),
        ap_password: credentials.password.clone(),
        portal_url: format!("http://{PORTAL_GATEWAY}/"),
        qr_payload: credentials.qr_payload(),
        status_text: "Scan with your phone, then pick your network".to_string(),
        ..WifiProvisioningState::base()
    };
    let _ = status_tx.send(ready);

    let outcome = serve_portal(server, &networks, stop_rx);

    // Whatever happens next, the hotspot must come down so the radio is free.
    hotspot.stop();

    match outcome {
        PortalOutcome::Stopped => {
            let _ = status_tx.send(WifiProvisioningState::idle());
        }
        PortalOutcome::TimedOut => {
            // Hotspot is already down (above); NetworkManager auto-reconnects the
            // previously active profile. Surface a brief note, then go idle.
            let _ = status_tx.send(WifiProvisioningState {
                active: false,
                phase: "idle".to_string(),
                status_text: "Wi-Fi setup timed out - reconnected to Wi-Fi.".to_string(),
                ..WifiProvisioningState::base()
            });
        }
        PortalOutcome::Connect(request) => {
            let _ = status_tx.send(WifiProvisioningState::phase(
                "connecting",
                &format!("Connecting to {}...", request.ssid),
            ));
            match connect_to_network(&request) {
                Ok(()) => {
                    let _ = status_tx.send(WifiProvisioningState {
                        active: false,
                        phase: "connected".to_string(),
                        status_text: format!("Connected to {}", request.ssid),
                        ..WifiProvisioningState::base()
                    });
                }
                Err(error) => {
                    let _ = status_tx.send(WifiProvisioningState::error(&error));
                }
            }
        }
    }
}

enum PortalOutcome {
    Stopped,
    TimedOut,
    Connect(ConnectRequest),
}

#[derive(Debug, Clone)]
struct ConnectRequest {
    ssid: String,
    security: WifiSecurity,
    password: String,
}

/// Run the captive-portal HTTP server until the user submits a network or the
/// worker asks us to stop.
fn serve_portal(
    server: Server,
    networks: &[PortalNetwork],
    stop_rx: &Receiver<()>,
) -> PortalOutcome {
    let networks_json = serde_json::to_string(networks).unwrap_or_else(|_| "[]".to_string());
    let deadline = Instant::now() + AP_TIMEOUT;

    loop {
        match stop_rx.try_recv() {
            Ok(()) | Err(TryRecvError::Disconnected) => return PortalOutcome::Stopped,
            Err(TryRecvError::Empty) => {}
        }
        if Instant::now() >= deadline {
            return PortalOutcome::TimedOut;
        }
        let request = match server.recv_timeout(PORTAL_POLL) {
            Ok(Some(request)) => request,
            Ok(None) => continue,
            Err(_) => return PortalOutcome::Stopped,
        };
        if let Some(connect) = handle_request(request, &networks_json) {
            return PortalOutcome::Connect(connect);
        }
    }
}

/// Handle a single portal request. Returns a connect request when the user
/// submits credentials (after acknowledging it to the phone).
fn handle_request(mut request: tiny_http::Request, networks_json: &str) -> Option<ConnectRequest> {
    let url = request.url().to_string();
    let path = url.split('?').next().unwrap_or("/");
    let is_post = *request.method() == Method::Post;

    if is_post && path == "/connect" {
        let mut body = String::new();
        let _ = request.as_reader().read_to_string(&mut body);
        match parse_connect(&body) {
            Ok(connect) => {
                let _ = request.respond(json_response(
                    200,
                    &json!({ "status": "connecting", "ssid": connect.ssid }).to_string(),
                ));
                return Some(connect);
            }
            Err(message) => {
                let _ = request
                    .respond(json_response(400, &json!({ "error": message }).to_string()));
                return None;
            }
        }
    }

    if path == "/networks" {
        let _ = request.respond(json_response(200, networks_json));
        return None;
    }

    if PROBE_PATHS.contains(&path) {
        let _ = request.respond(redirect_response());
        return None;
    }

    // Everything else (including the OS's captive check on "/") gets the page.
    let _ = request.respond(html_response(PORTAL_HTML));
    None
}

fn parse_connect(body: &str) -> Result<ConnectRequest, String> {
    let value: serde_json::Value =
        serde_json::from_str(body).map_err(|_| "invalid request".to_string())?;
    let ssid = value
        .get("ssid")
        .and_then(serde_json::Value::as_str)
        .map(str::trim)
        .filter(|ssid| !ssid.is_empty() && ssid.len() <= 32)
        .ok_or_else(|| "enter a network name".to_string())?
        .to_string();
    let password = value
        .get("password")
        .and_then(serde_json::Value::as_str)
        .unwrap_or("")
        .to_string();
    let security = match value.get("security").and_then(serde_json::Value::as_str) {
        Some("open") => WifiSecurity::Open,
        Some("wpa3_personal") => WifiSecurity::Wpa3Personal,
        _ => WifiSecurity::Wpa2Personal,
    };
    if security != WifiSecurity::Open && (password.len() < 8 || password.len() > 63) {
        return Err("password must be 8–63 characters".to_string());
    }
    Ok(ConnectRequest {
        ssid,
        security,
        password,
    })
}

/// Scan for nearby networks before the AP takes over the radio. Best-effort:
/// an empty list just means the portal shows manual entry only.
fn scan_networks() -> Vec<PortalNetwork> {
    let Ok(mut controller) = NetworkManagerWifiController::connect() else {
        return Vec::new();
    };
    let state = match controller.scan() {
        Ok(state) => state,
        Err(_) => return Vec::new(),
    };
    state
        .nearby_networks
        .into_iter()
        .map(|network| PortalNetwork {
            ssid: network.ssid,
            security: security_slug(network.security).to_string(),
            signal_percent: network.signal_percent,
            saved: network.saved,
        })
        .collect()
}

/// Join the selected home network. Unlike the cloud-driven `add_profile`, this
/// runs with no active station connection (the AP is being torn down), so it
/// creates an autoconnect profile and activates it directly.
fn connect_to_network(request: &ConnectRequest) -> Result<(), String> {
    let connection = Connection::system().map_err(|_| "Wi-Fi is unavailable".to_string())?;
    let (connection_path, active_path) = {
        let device = wifi_device_path(&connection)?;
        let settings = build_station_settings(request)?;
        let settings_proxy = proxy(&connection, NM_SETTINGS_PATH, NM_SETTINGS_INTERFACE)?;
        let (path, _result): (OwnedObjectPath, HashMap<String, OwnedValue>) = settings_proxy
            .call(
                "AddConnection2",
                &(
                    settings,
                    NM_SETTINGS_ADD_TO_DISK,
                    HashMap::<String, OwnedValue>::new(),
                ),
            )
            .map_err(|_| "could not save the network".to_string())?;
        let manager = proxy(&connection, NM_PATH, NM_INTERFACE)?;
        let active: OwnedObjectPath = manager
            .call("ActivateConnection", &(path.clone(), device, root_path()))
            .map_err(|_| "could not connect to the network".to_string())?;
        (path, active)
    };
    // ActivateConnection returns as soon as the request is accepted, before the
    // station link is really up - so a wrong password or DHCP failure would
    // otherwise be reported as success. Wait for the active connection to reach
    // ACTIVATED with an IPv4 address (or fail/time out) before returning. On
    // failure, delete the autoconnect profile we just created so NetworkManager
    // doesn't keep retrying a bad saved network on later onboarding attempts.
    match wait_for_active(&connection, &active_path, true, CONNECT_TIMEOUT) {
        ActiveWait::Activated => Ok(()),
        // A station connection that never gets an IPv4 lease in time (or drops)
        // is a real failure - delete the profile so NM stops retrying it.
        ActiveWait::Deactivated | ActiveWait::TimedOut => {
            if let Ok(profile) = proxy(&connection, connection_path.as_str(), NM_CONNECTION_INTERFACE)
            {
                let _ = profile.call::<_, _, ()>("Delete", &());
            }
            Err("Could not join that network - check the password.".to_string())
        }
    }
}

/// Result of watching an active connection come up.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum ActiveWait {
    /// Reached ACTIVATED (and, if required, has an IPv4 address).
    Activated,
    /// Explicitly failed / was torn down (rfkill, driver, wrong password, ...).
    Deactivated,
    /// Neither happened before the deadline - still activating.
    TimedOut,
}

/// Poll an active-connection object until it reaches ACTIVATED (optionally with
/// an IPv4 address), it deactivates, or the deadline passes.
fn wait_for_active(
    connection: &Connection,
    active_path: &OwnedObjectPath,
    require_ipv4: bool,
    timeout: Duration,
) -> ActiveWait {
    let deadline = Instant::now() + timeout;
    loop {
        if let Ok(active) = proxy(connection, active_path.as_str(), NM_ACTIVE_CONNECTION_INTERFACE)
        {
            let state: u32 = active.get_property("State").unwrap_or(0);
            if state == NM_ACTIVE_STATE_ACTIVATED {
                if !require_ipv4 {
                    return ActiveWait::Activated;
                }
                let ip4: OwnedObjectPath = active
                    .get_property("Ip4Config")
                    .unwrap_or_else(|_| root_path());
                if ip4.as_str() != "/" {
                    return ActiveWait::Activated;
                }
            } else if state == NM_ACTIVE_STATE_DEACTIVATED {
                return ActiveWait::Deactivated;
            }
        }
        if Instant::now() >= deadline {
            return ActiveWait::TimedOut;
        }
        thread::sleep(CONNECT_POLL);
    }
}

/// A WPA2 hotspot connection managed through its lifetime by NetworkManager.
struct Hotspot {
    connection: Connection,
    path: OwnedObjectPath,
}

impl Hotspot {
    fn start(credentials: &ApCredentials) -> Result<Self, String> {
        let connection = Connection::system().map_err(|_| "Wi-Fi is unavailable".to_string())?;
        // Scope the D-Bus proxies so their borrow of `connection` ends before it
        // is moved into the returned handle.
        let path = {
            let device = wifi_device_path(&connection)?;
            let settings = build_ap_settings(credentials)?;
            let settings_proxy = proxy(&connection, NM_SETTINGS_PATH, NM_SETTINGS_INTERFACE)?;
            let (path, _result): (OwnedObjectPath, HashMap<String, OwnedValue>) = settings_proxy
                .call(
                    "AddConnection2",
                    &(
                        settings,
                        NM_SETTINGS_ADD_TO_DISK,
                        HashMap::<String, OwnedValue>::new(),
                    ),
                )
                .map_err(|_| "could not create the hotspot".to_string())?;
            let manager = proxy(&connection, NM_PATH, NM_INTERFACE)?;
            // ActivateConnection only means the request was accepted; the AP can
            // still fail asynchronously (rfkill, driver/AP-mode failure,
            // shared-mode setup). Treat only an explicit DEACTIVATED as a real
            // failure - a timeout means it's still coming up (NM's dnsmasq setup
            // is slow) and the radio is already broadcasting, so proceed.
            let failed = match manager.call::<_, _, OwnedObjectPath>(
                "ActivateConnection",
                &(path.clone(), device, root_path()),
            ) {
                Err(_) => true,
                Ok(active) => {
                    wait_for_active(&connection, &active, false, AP_ACTIVATE_TIMEOUT)
                        == ActiveWait::Deactivated
                }
            };
            if failed {
                // Don't leave the AP profile behind if it cannot be brought up
                // (e.g. a missing polkit "share" grant): delete it before failing
                // so repeated attempts don't accumulate orphaned "YoYoPod Setup"
                // connections.
                if let Ok(connection_proxy) =
                    proxy(&connection, path.as_str(), NM_CONNECTION_INTERFACE)
                {
                    let _ = connection_proxy.call::<_, _, ()>("Delete", &());
                }
                return Err("could not start the hotspot".to_string());
            }
            path
        };
        Ok(Self { connection, path })
    }

    /// Delete the hotspot profile. NetworkManager deactivates it and reconnects
    /// the saved station profile (autoconnect) so the device returns online.
    fn stop(self) {
        if let Ok(proxy) = proxy(
            &self.connection,
            self.path.as_str(),
            NM_CONNECTION_INTERFACE,
        ) {
            let _ = proxy.call::<_, _, ()>("Delete", &());
        }
    }
}

/// Randomly generated hotspot identity for one onboarding session.
struct ApCredentials {
    ssid: String,
    password: String,
}

impl ApCredentials {
    fn generate() -> Self {
        let entropy = random_bytes(8);
        let suffix: String = entropy[..2]
            .iter()
            .map(|byte| format!("{byte:02X}"))
            .collect();
        // 8 base32-ish chars (no ambiguous 0/O/1/I) keep the WPA2 key easy to type.
        const ALPHABET: &[u8] = b"ABCDEFGHJKMNPQRSTUVWXYZ23456789";
        let password: String = entropy
            .iter()
            .map(|byte| ALPHABET[(*byte as usize) % ALPHABET.len()] as char)
            .collect();
        Self {
            ssid: format!("YoYoPod-{suffix}"),
            password,
        }
    }

    /// Standard Wi-Fi-join URI so a phone camera offers to join the hotspot.
    fn qr_payload(&self) -> String {
        format!(
            "WIFI:S:{};T:WPA;P:{};;",
            escape_qr(&self.ssid),
            escape_qr(&self.password)
        )
    }
}

fn build_ap_settings(credentials: &ApCredentials) -> Result<NmSettings, String> {
    let mut settings = NmSettings::new();
    settings.insert(
        "connection".to_string(),
        HashMap::from([
            ("id".to_string(), owned(AP_CONNECTION_ID.to_string())?),
            ("type".to_string(), owned("802-11-wireless".to_string())?),
            ("autoconnect".to_string(), owned(false)?),
        ]),
    );
    settings.insert(
        "802-11-wireless".to_string(),
        HashMap::from([
            (
                "ssid".to_string(),
                owned(credentials.ssid.as_bytes().to_vec())?,
            ),
            ("mode".to_string(), owned("ap".to_string())?),
            ("band".to_string(), owned("bg".to_string())?),
            ("channel".to_string(), owned(6_u32)?),
        ]),
    );
    settings.insert(
        "802-11-wireless-security".to_string(),
        HashMap::from([
            ("key-mgmt".to_string(), owned("wpa-psk".to_string())?),
            ("psk".to_string(), owned(credentials.password.clone())?),
        ]),
    );
    settings.insert(
        "ipv4".to_string(),
        HashMap::from([("method".to_string(), owned("shared".to_string())?)]),
    );
    settings.insert(
        "ipv6".to_string(),
        HashMap::from([("method".to_string(), owned("ignore".to_string())?)]),
    );
    Ok(settings)
}

fn build_station_settings(request: &ConnectRequest) -> Result<NmSettings, String> {
    let mut settings = NmSettings::new();
    settings.insert(
        "connection".to_string(),
        HashMap::from([
            ("id".to_string(), owned(format!("YoYoPod {}", request.ssid))?),
            ("type".to_string(), owned("802-11-wireless".to_string())?),
            ("autoconnect".to_string(), owned(true)?),
        ]),
    );
    settings.insert(
        "802-11-wireless".to_string(),
        HashMap::from([
            ("ssid".to_string(), owned(request.ssid.as_bytes().to_vec())?),
            ("mode".to_string(), owned("infrastructure".to_string())?),
        ]),
    );
    if request.security != WifiSecurity::Open {
        let key_mgmt = if request.security == WifiSecurity::Wpa3Personal {
            "sae"
        } else {
            "wpa-psk"
        };
        settings.insert(
            "802-11-wireless-security".to_string(),
            HashMap::from([
                ("key-mgmt".to_string(), owned(key_mgmt.to_string())?),
                ("psk".to_string(), owned(request.password.clone())?),
            ]),
        );
    }
    settings.insert(
        "ipv4".to_string(),
        HashMap::from([("method".to_string(), owned("auto".to_string())?)]),
    );
    settings.insert(
        "ipv6".to_string(),
        HashMap::from([("method".to_string(), owned("auto".to_string())?)]),
    );
    Ok(settings)
}

type NmSettings = HashMap<String, HashMap<String, OwnedValue>>;

fn wifi_device_path(connection: &Connection) -> Result<OwnedObjectPath, String> {
    let manager = proxy(connection, NM_PATH, NM_INTERFACE)?;
    let paths: Vec<OwnedObjectPath> = manager
        .call("GetDevices", &())
        .map_err(|_| "Wi-Fi is unavailable".to_string())?;
    paths
        .into_iter()
        .find(|path| {
            proxy(connection, path.as_str(), NM_DEVICE_INTERFACE)
                .and_then(|proxy| {
                    proxy
                        .get_property::<u32>("DeviceType")
                        .map_err(|_| String::new())
                })
                .is_ok_and(|device_type| device_type == NM_DEVICE_TYPE_WIFI)
        })
        .ok_or_else(|| "no Wi-Fi radio found".to_string())
}

fn proxy<'a>(
    connection: &'a Connection,
    path: &'a str,
    interface: &'a str,
) -> Result<Proxy<'a>, String> {
    Proxy::new(connection, NM_SERVICE, path, interface)
        .map_err(|_| "Wi-Fi is unavailable".to_string())
}

fn owned<T>(value: T) -> Result<OwnedValue, String>
where
    T: Into<Value<'static>>,
{
    let value: Value<'static> = value.into();
    value
        .try_to_owned()
        .map_err(|_| "could not encode Wi-Fi settings".to_string())
}

fn root_path() -> OwnedObjectPath {
    OwnedObjectPath::try_from("/").expect("root object path is valid")
}

fn security_slug(security: WifiSecurity) -> &'static str {
    match security {
        WifiSecurity::Open => "open",
        WifiSecurity::Wpa2Personal => "wpa2_personal",
        WifiSecurity::Wpa3Personal => "wpa3_personal",
        WifiSecurity::Enterprise => "enterprise",
    }
}

/// Escape the characters reserved by the `WIFI:` URI scheme.
fn escape_qr(value: &str) -> String {
    let mut escaped = String::with_capacity(value.len());
    for character in value.chars() {
        if matches!(character, '\\' | ';' | ',' | ':' | '"') {
            escaped.push('\\');
        }
        escaped.push(character);
    }
    escaped
}

fn random_bytes(len: usize) -> Vec<u8> {
    use std::fs::File;
    let mut buffer = vec![0_u8; len];
    if File::open("/dev/urandom")
        .and_then(|mut file| file.read_exact(&mut buffer))
        .is_ok()
    {
        return buffer;
    }
    // Fallback: derive from the clock if /dev/urandom is unavailable.
    let seed = epoch_seconds().wrapping_mul(2_654_435_761);
    for (index, byte) in buffer.iter_mut().enumerate() {
        *byte = (seed >> ((index % 8) * 8)) as u8;
    }
    buffer
}

fn epoch_seconds() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_secs())
        .unwrap_or_default()
}

fn json_response(status: u16, body: &str) -> Response<std::io::Cursor<Vec<u8>>> {
    let header = Header::from_bytes(&b"Content-Type"[..], &b"application/json"[..])
        .expect("static header is valid");
    Response::from_string(body.to_string())
        .with_status_code(status)
        .with_header(header)
}

fn html_response(body: &str) -> Response<std::io::Cursor<Vec<u8>>> {
    let header = Header::from_bytes(&b"Content-Type"[..], &b"text/html; charset=utf-8"[..])
        .expect("static header is valid");
    Response::from_string(body.to_string()).with_header(header)
}

fn redirect_response() -> Response<std::io::Cursor<Vec<u8>>> {
    let location = format!("http://{PORTAL_GATEWAY}/");
    let header =
        Header::from_bytes(&b"Location"[..], location.as_bytes()).expect("location header is valid");
    Response::from_string(String::new())
        .with_status_code(302)
        .with_header(header)
}

const PORTAL_HTML: &str = include_str!("portal.html");

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn qr_payload_is_a_wifi_join_uri_with_escaping() {
        let credentials = ApCredentials {
            ssid: "YoYoPod-1A2B".to_string(),
            password: "ABCD2345".to_string(),
        };
        assert_eq!(
            credentials.qr_payload(),
            "WIFI:S:YoYoPod-1A2B;T:WPA;P:ABCD2345;;"
        );
        assert_eq!(escape_qr("a;b:c"), "a\\;b\\:c");
    }

    #[test]
    fn generated_credentials_are_typeable_and_unique_enough() {
        let credentials = ApCredentials::generate();
        assert!(credentials.ssid.starts_with("YoYoPod-"));
        assert_eq!(credentials.password.len(), 8);
        assert!((8..=63).contains(&credentials.password.len()));
    }

    #[test]
    fn parse_connect_requires_a_usable_password_for_secured_networks() {
        let ok = parse_connect(r#"{"ssid":"Home","security":"wpa2_personal","password":"longenough"}"#)
            .expect("valid request");
        assert_eq!(ok.ssid, "Home");
        assert_eq!(ok.security, WifiSecurity::Wpa2Personal);

        assert!(parse_connect(r#"{"ssid":"Home","password":"short"}"#).is_err());
        assert!(parse_connect(r#"{"ssid":"","password":"longenough"}"#).is_err());
        assert!(
            parse_connect(r#"{"ssid":"Open","security":"open","password":""}"#).is_ok(),
            "open networks need no password"
        );
    }

    #[test]
    fn security_slugs_match_the_ui_contract() {
        assert_eq!(security_slug(WifiSecurity::Open), "open");
        assert_eq!(security_slug(WifiSecurity::Wpa2Personal), "wpa2_personal");
        assert_eq!(security_slug(WifiSecurity::Wpa3Personal), "wpa3_personal");
    }
}
