use std::fs;
use std::io::Read;
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::time::{SystemTime, UNIX_EPOCH};

use serde::{Deserialize, Serialize};

use crate::bluetooth::{BluetoothController, BluetoothState};

const DEFAULT_SETTINGS_PATH: &str = "/var/lib/yoyopod/audio/settings.json";
const DEFAULT_ASOUND_CONFIG_PATH: &str = "/var/lib/yoyopod/audio/asoundrc";

#[derive(Debug, Clone, PartialEq, Eq)]
struct BuiltinAudioDevices {
    media: String,
    voip_playback: String,
    voip_ringer: String,
    voip_capture: String,
    voip_media: String,
}

impl Default for BuiltinAudioDevices {
    fn default() -> Self {
        Self {
            media: "alsa/default".to_string(),
            voip_playback: "ALSA: wm8960-soundcard".to_string(),
            voip_ringer: "ALSA: wm8960-soundcard".to_string(),
            voip_capture: "ALSA: wm8960-soundcard".to_string(),
            voip_media: "ALSA: wm8960-soundcard".to_string(),
        }
    }
}

impl BuiltinAudioDevices {
    fn load(config_dir: &Path) -> Self {
        let hardware = fs::read(config_dir.join("device/hardware.yaml"))
            .ok()
            .and_then(|bytes| serde_yaml::from_slice::<serde_yaml::Value>(&bytes).ok())
            .unwrap_or(serde_yaml::Value::Null);
        let configured = |path: &[&str], env_name: &str, fallback: &str| {
            std::env::var(env_name)
                .ok()
                .filter(|value| !value.trim().is_empty())
                .or_else(|| yaml_string(&hardware, path))
                .unwrap_or_else(|| fallback.to_string())
        };
        Self {
            media: mpv_alsa_device(&configured(
                &["media_audio", "alsa_device"],
                "YOYOPOD_ALSA_DEVICE",
                "default",
            )),
            voip_playback: configured(
                &["communication_audio", "playback_device_id"],
                "YOYOPOD_PLAYBACK_DEVICE",
                "ALSA: wm8960-soundcard",
            ),
            voip_ringer: configured(
                &["communication_audio", "ringer_device_id"],
                "YOYOPOD_RINGER_DEVICE",
                "ALSA: wm8960-soundcard",
            ),
            voip_capture: configured(
                &["communication_audio", "capture_device_id"],
                "YOYOPOD_CAPTURE_DEVICE",
                "ALSA: wm8960-soundcard",
            ),
            voip_media: configured(
                &["communication_audio", "media_device_id"],
                "YOYOPOD_MEDIA_DEVICE",
                "ALSA: wm8960-soundcard",
            ),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct AudioSettings {
    pub routes: AudioRoutes,
    pub levels: AudioLevels,
    pub alert_policy: String,
    pub fallback_policy: String,
}

impl Default for AudioSettings {
    fn default() -> Self {
        Self {
            routes: AudioRoutes {
                media_output_id: "builtin-speaker".to_string(),
                communication_output_id: "builtin-speaker".to_string(),
                communication_input_id: "builtin-microphone".to_string(),
            },
            levels: AudioLevels {
                media: 65,
                communication: 70,
                alerts: 70,
                microphone_gain: 60,
                max_output: 100,
            },
            alert_policy: "mirror_builtin_and_selected".to_string(),
            fallback_policy: "builtin".to_string(),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct AudioRoutes {
    pub media_output_id: String,
    pub communication_output_id: String,
    pub communication_input_id: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct AudioLevels {
    pub media: u8,
    pub communication: u8,
    pub alerts: u8,
    pub microphone_gain: u8,
    pub max_output: u8,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct AudioState {
    pub schema_version: u8,
    pub status: String,
    pub applied_revision: u64,
    pub applied: AudioSettings,
    pub endpoints: AudioEndpoints,
    pub fallback_reason: Option<String>,
    pub input_meter: Option<AudioInputMeter>,
    pub reported_at: u64,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct AudioEndpoints {
    pub outputs: Vec<AudioEndpoint>,
    pub inputs: Vec<AudioEndpoint>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct AudioEndpoint {
    pub endpoint_id: String,
    pub name: String,
    pub kind: String,
    pub accessory_id: Option<String>,
    pub available: bool,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct AudioInputMeter {
    pub level_percent: u8,
    pub expires_at: u64,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct AudioRouteLocal {
    pub media_device: String,
    pub media_volume: u8,
    pub voip_playback_device: String,
    pub voip_ringer_device: String,
    pub voip_capture_device: String,
    pub voip_media_device: String,
    pub communication_volume: u8,
    pub microphone_gain: u8,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AudioOperationError {
    pub code: &'static str,
    pub message: String,
}

impl AudioOperationError {
    fn invalid(message: impl Into<String>) -> Self {
        Self {
            code: "audio_invalid_settings",
            message: message.into(),
        }
    }

    fn failed(message: impl Into<String>) -> Self {
        Self {
            code: "audio_operation_failed",
            message: message.into(),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AppliedAudio {
    pub state: AudioState,
    pub route: AudioRouteLocal,
}

pub struct AudioManager {
    settings_path: PathBuf,
    asound_path: PathBuf,
    desired_revision: u64,
    desired: AudioSettings,
    input_meter: Option<AudioInputMeter>,
    last_resolved: Option<AppliedAudio>,
    builtin: BuiltinAudioDevices,
}

impl AudioManager {
    pub fn open(config_dir: impl AsRef<Path>) -> Self {
        let settings_path = std::env::var_os("YOYOPOD_AUDIO_SETTINGS_FILE")
            .map(PathBuf::from)
            .unwrap_or_else(|| PathBuf::from(DEFAULT_SETTINGS_PATH));
        let asound_path = std::env::var_os("YOYOPOD_ASOUND_CONFIG")
            .map(PathBuf::from)
            .unwrap_or_else(|| PathBuf::from(DEFAULT_ASOUND_CONFIG_PATH));
        Self::open_at_with_builtin(
            settings_path,
            asound_path,
            BuiltinAudioDevices::load(config_dir.as_ref()),
        )
    }

    #[cfg(test)]
    fn open_at(settings_path: PathBuf, asound_path: PathBuf) -> Self {
        Self::open_at_with_builtin(settings_path, asound_path, BuiltinAudioDevices::default())
    }

    fn open_at_with_builtin(
        settings_path: PathBuf,
        asound_path: PathBuf,
        builtin: BuiltinAudioDevices,
    ) -> Self {
        let stored = fs::read(&settings_path)
            .ok()
            .and_then(|bytes| serde_json::from_slice::<StoredAudioSettings>(&bytes).ok());
        Self {
            settings_path,
            asound_path,
            desired_revision: stored.as_ref().map_or(0, |stored| stored.revision),
            desired: stored.map_or_else(AudioSettings::default, |stored| stored.settings),
            input_meter: None,
            last_resolved: None,
            builtin,
        }
    }

    pub fn apply(
        &mut self,
        revision: u64,
        settings: AudioSettings,
        bluetooth: &dyn BluetoothController,
        bluetooth_state: &BluetoothState,
    ) -> Result<AppliedAudio, AudioOperationError> {
        validate_settings(&settings)?;
        if revision < self.desired_revision
            || (revision == self.desired_revision && settings != self.desired)
        {
            return Err(AudioOperationError::invalid(
                "A newer or locally changed audio configuration is already active",
            ));
        }
        self.desired_revision = revision;
        self.desired = settings;
        self.persist()?;
        self.resolve(bluetooth, bluetooth_state)
    }

    pub fn set_output_level(
        &mut self,
        level: u8,
        bluetooth: &dyn BluetoothController,
        bluetooth_state: &BluetoothState,
    ) -> Result<AppliedAudio, AudioOperationError> {
        let max_output = self.desired.levels.max_output.clamp(20, 100);
        let level = level.min(max_output);
        self.desired.levels.media = level;
        self.desired.levels.communication = level;
        self.desired.levels.alerts = level.max(20).min(max_output);
        self.persist()?;
        self.resolve(bluetooth, bluetooth_state)
    }

    pub fn current(
        &mut self,
        bluetooth: &dyn BluetoothController,
        bluetooth_state: &BluetoothState,
    ) -> Result<AppliedAudio, AudioOperationError> {
        self.resolve(bluetooth, bluetooth_state)
    }

    pub fn current_if_changed(
        &mut self,
        bluetooth: &dyn BluetoothController,
        bluetooth_state: &BluetoothState,
    ) -> Result<Option<AppliedAudio>, AudioOperationError> {
        let previous = self.last_resolved.clone();
        let applied = self.resolve(bluetooth, bluetooth_state)?;
        Ok(previous
            .as_ref()
            .is_none_or(|previous| !same_audio_application(previous, &applied))
            .then_some(applied))
    }

    pub fn test_output(
        &self,
        target: &str,
        route: &AudioRouteLocal,
    ) -> Result<(), AudioOperationError> {
        let (device, volume): (&str, u8) = match target {
            "media" => (route.media_device.as_str(), route.media_volume),
            "communication" => (
                route.voip_playback_device.as_str(),
                route.communication_volume,
            ),
            "alerts" => (
                route.voip_ringer_device.as_str(),
                self.desired
                    .levels
                    .alerts
                    .min(self.desired.levels.max_output),
            ),
            _ => return Err(AudioOperationError::invalid("Unknown audio test target")),
        };
        let sample = [
            "/usr/share/sounds/alsa/Front_Center.wav",
            "/usr/share/sounds/freedesktop/stereo/audio-volume-change.oga",
        ]
        .into_iter()
        .find(|path| Path::new(path).exists())
        .ok_or_else(|| AudioOperationError::failed("No audio test sound is installed"))?;
        let audio_device = mpv_alsa_device(device);
        let status = Command::new("mpv")
            .args(output_test_args(&audio_device, volume, sample))
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status()
            .map_err(|_| AudioOperationError::failed("The test sound could not be started"))?;
        if !status.success() {
            return Err(AudioOperationError::failed(
                "The selected audio output is not currently available",
            ));
        }
        Ok(())
    }

    pub fn test_input(
        &mut self,
        route: &AudioRouteLocal,
        duration_seconds: u64,
    ) -> Result<AudioInputMeter, AudioOperationError> {
        let device = local_alsa_device(&route.voip_capture_device);
        let duration = duration_seconds.clamp(1, 10).to_string();
        let mut child = Command::new("arecord")
            .args([
                "-q", "-D", device, "-d", &duration, "-f", "S16_LE", "-c", "1", "-r", "8000", "-t",
                "raw",
            ])
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .spawn()
            .map_err(|_| AudioOperationError::failed("The microphone test could not start"))?;
        let mut captured = Vec::new();
        if let Some(mut stdout) = child.stdout.take() {
            stdout.read_to_end(&mut captured).map_err(|_| {
                AudioOperationError::failed("The microphone test could not be read")
            })?;
        }
        let status = child
            .wait()
            .map_err(|_| AudioOperationError::failed("The microphone test did not finish"))?;
        if !status.success() {
            return Err(AudioOperationError::failed(
                "The selected microphone is not currently available",
            ));
        }
        let peak = captured
            .chunks_exact(2)
            .map(|bytes| i16::from_le_bytes([bytes[0], bytes[1]]).unsigned_abs())
            .max()
            .unwrap_or(0);
        let meter = AudioInputMeter {
            level_percent: ((u32::from(peak) * 100) / u32::from(i16::MAX as u16)).min(100) as u8,
            expires_at: epoch_seconds() + 15,
        };
        self.input_meter = Some(meter.clone());
        Ok(meter)
    }

    fn resolve(
        &mut self,
        bluetooth: &dyn BluetoothController,
        bluetooth_state: &BluetoothState,
    ) -> Result<AppliedAudio, AudioOperationError> {
        if self
            .input_meter
            .as_ref()
            .is_some_and(|meter| meter.expires_at <= epoch_seconds())
        {
            self.input_meter = None;
        }
        let connected = |endpoint_id: &str| {
            bluetooth_state.accessories.iter().find(|accessory| {
                accessory.accessory_id == endpoint_id && accessory.paired && accessory.connected
            })
        };
        let media_accessory = connected(&self.desired.routes.media_output_id)
            .filter(|accessory| accessory.capabilities.stereo || accessory.capabilities.hands_free);
        let media_uses_sco =
            media_accessory.is_some_and(|accessory| !accessory.capabilities.stereo);
        let communication_output_accessory =
            connected(&self.desired.routes.communication_output_id)
                .filter(|accessory| accessory.capabilities.hands_free);
        let communication_input_accessory = connected(&self.desired.routes.communication_input_id)
            .filter(|accessory| accessory.capabilities.microphone);
        let media_address =
            media_accessory.and_then(|accessory| bluetooth.raw_address(&accessory.accessory_id));
        let communication_output_address = communication_output_accessory
            .and_then(|accessory| bluetooth.raw_address(&accessory.accessory_id));
        let communication_input_address = communication_input_accessory
            .and_then(|accessory| bluetooth.raw_address(&accessory.accessory_id));
        let output_address = media_address
            .as_deref()
            .or(communication_output_address.as_deref());
        let input_address = communication_input_address
            .as_deref()
            .or(communication_output_address.as_deref());
        write_asound_config(&self.asound_path, output_address, input_address)?;

        let media_fallback = !self.desired.routes.media_output_id.starts_with("builtin-")
            && media_accessory.is_none();
        let communication_output_fallback = !self
            .desired
            .routes
            .communication_output_id
            .starts_with("builtin-")
            && communication_output_accessory.is_none();
        let communication_input_fallback = !self
            .desired
            .routes
            .communication_input_id
            .starts_with("builtin-")
            && communication_input_accessory.is_none();
        let fallback =
            media_fallback || communication_output_fallback || communication_input_fallback;
        let route = AudioRouteLocal {
            media_device: if media_fallback
                || self.desired.routes.media_output_id == "builtin-speaker"
            {
                self.builtin.media.as_str()
            } else {
                if media_uses_sco {
                    "alsa/yoyopod_bt_sco"
                } else {
                    "alsa/yoyopod_bt_a2dp"
                }
            }
            .to_string(),
            media_volume: self
                .desired
                .levels
                .media
                .min(self.desired.levels.max_output),
            voip_playback_device: if communication_output_fallback
                || self.desired.routes.communication_output_id == "builtin-speaker"
            {
                self.builtin.voip_playback.as_str()
            } else {
                "ALSA: yoyopod_bt_sco"
            }
            .to_string(),
            // Safety alerts/ringing always retain the built-in route.
            voip_ringer_device: self.builtin.voip_ringer.clone(),
            voip_capture_device: if communication_input_fallback
                || self.desired.routes.communication_input_id == "builtin-microphone"
            {
                self.builtin.voip_capture.as_str()
            } else {
                "ALSA: yoyopod_bt_sco"
            }
            .to_string(),
            voip_media_device: if communication_output_fallback
                || self.desired.routes.communication_output_id == "builtin-speaker"
            {
                self.builtin.voip_media.as_str()
            } else {
                "ALSA: yoyopod_bt_sco"
            }
            .to_string(),
            communication_volume: self
                .desired
                .levels
                .communication
                .min(self.desired.levels.max_output),
            microphone_gain: self.desired.levels.microphone_gain,
        };
        let applied = applied_settings(
            &self.desired,
            media_fallback,
            communication_output_fallback,
            communication_input_fallback,
        );
        let applied = AppliedAudio {
            state: AudioState {
                schema_version: 1,
                status: if bluetooth_state.status == "unavailable" {
                    "degraded"
                } else if fallback {
                    "degraded"
                } else {
                    "ready"
                }
                .to_string(),
                applied_revision: self.desired_revision,
                applied,
                endpoints: endpoints(bluetooth_state),
                fallback_reason: fallback.then(|| {
                    "A selected Bluetooth route is disconnected; built-in audio is active"
                        .to_string()
                }),
                input_meter: self.input_meter.clone(),
                reported_at: epoch_seconds(),
            },
            route,
        };
        self.last_resolved = Some(applied.clone());
        Ok(applied)
    }

    fn persist(&self) -> Result<(), AudioOperationError> {
        let stored = StoredAudioSettings {
            revision: self.desired_revision,
            settings: self.desired.clone(),
        };
        atomic_json_write(&self.settings_path, &stored)
            .map_err(|_| AudioOperationError::failed("Audio settings could not be saved"))
    }
}

#[derive(Serialize, Deserialize)]
struct StoredAudioSettings {
    revision: u64,
    settings: AudioSettings,
}

fn validate_settings(settings: &AudioSettings) -> Result<(), AudioOperationError> {
    let levels = &settings.levels;
    if settings.alert_policy != "mirror_builtin_and_selected"
        || settings.fallback_policy != "builtin"
        || levels.max_output < 20
        || levels.max_output > 100
        || levels.microphone_gain > 100
        || levels.alerts < 20
        || levels.media > levels.max_output
        || levels.communication > levels.max_output
        || levels.alerts > levels.max_output
    {
        return Err(AudioOperationError::invalid(
            "Audio settings are outside the supported safe range",
        ));
    }
    Ok(())
}

fn applied_settings(
    desired: &AudioSettings,
    media_fallback: bool,
    communication_output_fallback: bool,
    communication_input_fallback: bool,
) -> AudioSettings {
    let mut applied = desired.clone();
    if media_fallback {
        applied.routes.media_output_id = "builtin-speaker".to_string();
    }
    if communication_output_fallback {
        applied.routes.communication_output_id = "builtin-speaker".to_string();
    }
    if communication_input_fallback {
        applied.routes.communication_input_id = "builtin-microphone".to_string();
    }
    applied
}

fn endpoints(bluetooth: &BluetoothState) -> AudioEndpoints {
    let mut outputs = vec![AudioEndpoint {
        endpoint_id: "builtin-speaker".to_string(),
        name: "YoYoPod speaker".to_string(),
        kind: "builtin".to_string(),
        accessory_id: None,
        available: true,
    }];
    let mut inputs = vec![AudioEndpoint {
        endpoint_id: "builtin-microphone".to_string(),
        name: "YoYoPod microphone".to_string(),
        kind: "builtin".to_string(),
        accessory_id: None,
        available: true,
    }];
    for accessory in bluetooth
        .accessories
        .iter()
        .filter(|accessory| accessory.paired)
    {
        if accessory.capabilities.output {
            outputs.push(AudioEndpoint {
                endpoint_id: accessory.accessory_id.clone(),
                name: accessory.name.clone(),
                kind: "bluetooth".to_string(),
                accessory_id: Some(accessory.accessory_id.clone()),
                available: accessory.connected,
            });
        }
        if accessory.capabilities.microphone {
            inputs.push(AudioEndpoint {
                endpoint_id: accessory.accessory_id.clone(),
                name: accessory.name.clone(),
                kind: "bluetooth".to_string(),
                accessory_id: Some(accessory.accessory_id.clone()),
                available: accessory.connected,
            });
        }
    }
    AudioEndpoints { outputs, inputs }
}

fn write_asound_config(
    path: &Path,
    output_address: Option<&str>,
    input_address: Option<&str>,
) -> Result<(), AudioOperationError> {
    let output = output_address.unwrap_or("00:00:00:00:00:00");
    let input = input_address.unwrap_or(output);
    let config = format!(
        "# Managed by YoYoPod. Bluetooth addresses stay on-device.\n\
</usr/share/alsa/alsa.conf>\n\
pcm.yoyopod_bt_a2dp {{\n  type bluealsa\n  device \"{output}\"\n  profile \"a2dp\"\n}}\n\
pcm.yoyopod_bt_sco {{\n  type bluealsa\n  device \"{input}\"\n  profile \"sco\"\n}}\n"
    );
    if fs::read(path).is_ok_and(|existing| existing == config.as_bytes()) {
        return Ok(());
    }
    atomic_write(path, config.as_bytes())
        .map_err(|_| AudioOperationError::failed("The local audio route could not be configured"))
}

fn same_audio_application(left: &AppliedAudio, right: &AppliedAudio) -> bool {
    let mut left_state = left.state.clone();
    let mut right_state = right.state.clone();
    left_state.reported_at = 0;
    right_state.reported_at = 0;
    left.route == right.route && left_state == right_state
}

fn yaml_string(value: &serde_yaml::Value, path: &[&str]) -> Option<String> {
    let mut current = value;
    for segment in path {
        current = current
            .as_mapping()?
            .get(serde_yaml::Value::String((*segment).to_string()))?;
    }
    current
        .as_str()
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(str::to_string)
}

fn mpv_alsa_device(device: &str) -> String {
    if device.starts_with("alsa/") {
        device.to_string()
    } else {
        format!("alsa/{}", local_alsa_device(device))
    }
}

fn output_test_args(audio_device: &str, volume: u8, sample: &str) -> Vec<String> {
    vec![
        "--no-config".to_string(),
        "--really-quiet".to_string(),
        "--no-video".to_string(),
        "--audio-display=no".to_string(),
        "--ao=alsa".to_string(),
        format!("--audio-device={audio_device}"),
        format!("--volume={}", volume.min(100)),
        "--volume-max=100".to_string(),
        sample.to_string(),
    ]
}

fn local_alsa_device(device: &str) -> &str {
    device
        .strip_prefix("alsa/")
        .or_else(|| device.strip_prefix("ALSA: "))
        .unwrap_or(device)
}

fn atomic_json_write(path: &Path, value: &impl Serialize) -> Result<(), std::io::Error> {
    atomic_write(path, &serde_json::to_vec_pretty(value)?)
}

fn atomic_write(path: &Path, bytes: &[u8]) -> Result<(), std::io::Error> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)?;
        fs::set_permissions(parent, fs::Permissions::from_mode(0o750))?;
    }
    let temporary = path.with_extension("tmp");
    fs::write(&temporary, bytes)?;
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
    use crate::bluetooth::{
        BluetoothAccessory, BluetoothCapabilities, BluetoothOperationError,
        UnavailableBluetoothController,
    };

    #[test]
    fn disconnected_selected_accessory_falls_back_without_losing_desired_setting() {
        let directory = tempfile::tempdir().expect("tempdir");
        let mut manager = AudioManager::open_at(
            directory.path().join("settings.json"),
            directory.path().join("asoundrc"),
        );
        let state = BluetoothState {
            schema_version: 1,
            status: "ready".to_string(),
            radio_enabled: true,
            scanning: false,
            accessories: vec![BluetoothAccessory {
                accessory_id: "9b0692e3-a07a-42f0-9fa7-a7704bbcf777".to_string(),
                name: "Headset".to_string(),
                kind: "headset".to_string(),
                paired: true,
                connected: false,
                trusted: true,
                auto_connect: true,
                capabilities: BluetoothCapabilities {
                    output: true,
                    microphone: true,
                    stereo: true,
                    hands_free: true,
                },
                battery_percent: None,
                signal_percent: None,
                last_seen_at: 1,
            }],
            scanned_at: None,
            reported_at: 1,
        };
        let id = state.accessories[0].accessory_id.clone();
        let mut settings = AudioSettings::default();
        settings.routes.media_output_id = id;
        let applied = manager
            .apply(2, settings, &UnavailableBluetoothController, &state)
            .expect("apply");
        assert_eq!(
            applied.state.applied.routes.media_output_id,
            "builtin-speaker"
        );
        assert_eq!(applied.state.status, "degraded");
        assert_eq!(applied.state.applied_revision, 2);
    }

    #[test]
    fn a2dp_only_communication_output_falls_back_to_builtin() {
        let directory = tempfile::tempdir().expect("tempdir");
        let mut manager = AudioManager::open_at(
            directory.path().join("settings.json"),
            directory.path().join("asoundrc"),
        );
        let accessory_id = "9b0692e3-a07a-42f0-9fa7-a7704bbcf778".to_string();
        let state = BluetoothState {
            schema_version: 1,
            status: "ready".to_string(),
            radio_enabled: true,
            scanning: false,
            accessories: vec![BluetoothAccessory {
                accessory_id: accessory_id.clone(),
                name: "Speaker".to_string(),
                kind: "speaker".to_string(),
                paired: true,
                connected: true,
                trusted: true,
                auto_connect: true,
                capabilities: BluetoothCapabilities {
                    output: true,
                    microphone: false,
                    stereo: true,
                    hands_free: false,
                },
                battery_percent: None,
                signal_percent: None,
                last_seen_at: 1,
            }],
            scanned_at: None,
            reported_at: 1,
        };
        let mut settings = AudioSettings::default();
        settings.routes.communication_output_id = accessory_id;

        let applied = manager
            .apply(2, settings, &UnavailableBluetoothController, &state)
            .expect("apply");

        assert_eq!(applied.route.voip_playback_device, "ALSA: wm8960-soundcard");
        assert_eq!(
            applied.state.applied.routes.communication_output_id,
            "builtin-speaker"
        );
        assert_eq!(applied.state.status, "degraded");
    }

    #[test]
    fn hands_free_only_media_output_uses_the_sco_profile() {
        let directory = tempfile::tempdir().expect("tempdir");
        let mut manager = AudioManager::open_at(
            directory.path().join("settings.json"),
            directory.path().join("asoundrc"),
        );
        let accessory_id = "9b0692e3-a07a-42f0-9fa7-a7704bbcf777".to_string();
        let state = BluetoothState {
            schema_version: 1,
            status: "ready".to_string(),
            radio_enabled: true,
            scanning: false,
            accessories: vec![BluetoothAccessory {
                accessory_id: accessory_id.clone(),
                name: "Hands-free headset".to_string(),
                kind: "headset".to_string(),
                paired: true,
                connected: true,
                trusted: true,
                auto_connect: true,
                capabilities: BluetoothCapabilities {
                    output: true,
                    microphone: true,
                    stereo: false,
                    hands_free: true,
                },
                battery_percent: None,
                signal_percent: None,
                last_seen_at: 1,
            }],
            scanned_at: None,
            reported_at: 1,
        };
        let mut settings = AudioSettings::default();
        settings.routes.media_output_id = accessory_id.clone();

        let applied = manager
            .apply(2, settings, &UnavailableBluetoothController, &state)
            .expect("apply");

        assert_eq!(applied.route.media_device, "alsa/yoyopod_bt_sco");
        assert_eq!(applied.state.applied.routes.media_output_id, accessory_id);
        assert_eq!(applied.state.status, "ready");
    }

    #[test]
    fn unchanged_periodic_audio_state_is_not_reapplied() {
        let directory = tempfile::tempdir().expect("tempdir");
        let mut manager = AudioManager::open_at(
            directory.path().join("settings.json"),
            directory.path().join("asoundrc"),
        );
        let state = BluetoothState::unavailable();

        manager
            .current(&UnavailableBluetoothController, &state)
            .expect("initial state");
        let unchanged = manager
            .current_if_changed(&UnavailableBluetoothController, &state)
            .expect("periodic state");

        assert!(unchanged.is_none());
    }

    #[test]
    fn configured_builtin_devices_are_preserved_in_local_routes() {
        let directory = tempfile::tempdir().expect("tempdir");
        let builtin = BuiltinAudioDevices {
            media: "alsa/custom-speaker".to_string(),
            voip_playback: "ALSA: custom-playback".to_string(),
            voip_ringer: "ALSA: custom-ringer".to_string(),
            voip_capture: "ALSA: custom-capture".to_string(),
            voip_media: "ALSA: custom-media".to_string(),
        };
        let mut manager = AudioManager::open_at_with_builtin(
            directory.path().join("settings.json"),
            directory.path().join("asoundrc"),
            builtin,
        );

        let applied = manager
            .current(
                &UnavailableBluetoothController,
                &BluetoothState::unavailable(),
            )
            .expect("route");

        assert_eq!(applied.route.media_device, "alsa/custom-speaker");
        assert_eq!(applied.route.voip_playback_device, "ALSA: custom-playback");
        assert_eq!(applied.route.voip_ringer_device, "ALSA: custom-ringer");
        assert_eq!(applied.route.voip_capture_device, "ALSA: custom-capture");
        assert_eq!(applied.route.voip_media_device, "ALSA: custom-media");
    }

    #[test]
    fn output_test_uses_the_selected_device_and_bounded_level() {
        let args = output_test_args("alsa/yoyopod_bt_a2dp", 86, "/tmp/test.wav");

        assert!(args.contains(&"--audio-device=alsa/yoyopod_bt_a2dp".to_string()));
        assert!(args.contains(&"--volume=86".to_string()));
        assert!(args.contains(&"--volume-max=100".to_string()));
        assert_eq!(args.last().map(String::as_str), Some("/tmp/test.wav"));
    }

    #[test]
    fn local_output_level_updates_all_output_domains_and_persists() {
        let directory = tempfile::tempdir().expect("tempdir");
        let settings_path = directory.path().join("settings.json");
        let mut manager =
            AudioManager::open_at(settings_path.clone(), directory.path().join("asoundrc"));
        let state = BluetoothState::unavailable();

        let applied = manager
            .set_output_level(100, &UnavailableBluetoothController, &state)
            .expect("set output level");

        assert_eq!(applied.route.media_volume, 100);
        assert_eq!(applied.route.communication_volume, 100);
        assert_eq!(applied.state.applied.levels.media, 100);
        assert_eq!(applied.state.applied.levels.communication, 100);
        assert_eq!(applied.state.applied.levels.alerts, 100);
        assert_eq!(applied.state.applied.levels.max_output, 100);

        let stored: StoredAudioSettings =
            serde_json::from_slice(&fs::read(settings_path).expect("settings file"))
                .expect("stored settings");
        assert_eq!(stored.settings.levels.media, 100);
        assert_eq!(stored.settings.levels.max_output, 100);
    }

    #[test]
    fn local_output_level_preserves_the_configured_safety_cap() {
        let directory = tempfile::tempdir().expect("tempdir");
        let settings_path = directory.path().join("settings.json");
        let mut manager =
            AudioManager::open_at(settings_path.clone(), directory.path().join("asoundrc"));
        let state = BluetoothState::unavailable();
        let mut settings = AudioSettings::default();
        settings.levels.max_output = 70;
        settings.levels.media = 65;
        settings.levels.communication = 70;
        settings.levels.alerts = 70;
        manager
            .apply(2, settings, &UnavailableBluetoothController, &state)
            .expect("apply capped settings");

        let applied = manager
            .set_output_level(90, &UnavailableBluetoothController, &state)
            .expect("set capped output level");

        assert_eq!(applied.state.applied.levels.media, 70);
        assert_eq!(applied.state.applied.levels.communication, 70);
        assert_eq!(applied.state.applied.levels.alerts, 70);
        assert_eq!(applied.state.applied.levels.max_output, 70);
        let stored: StoredAudioSettings =
            serde_json::from_slice(&fs::read(settings_path).expect("settings file"))
                .expect("stored settings");
        assert_eq!(stored.settings.levels.max_output, 70);
    }

    #[test]
    fn same_revision_replay_cannot_overwrite_a_local_volume_change() {
        let directory = tempfile::tempdir().expect("tempdir");
        let settings_path = directory.path().join("settings.json");
        let mut manager =
            AudioManager::open_at(settings_path.clone(), directory.path().join("asoundrc"));
        let state = BluetoothState::unavailable();
        let cloud_settings = AudioSettings::default();
        manager
            .apply(
                2,
                cloud_settings.clone(),
                &UnavailableBluetoothController,
                &state,
            )
            .expect("initial cloud settings");
        manager
            .set_output_level(55, &UnavailableBluetoothController, &state)
            .expect("local volume");

        let error = manager
            .apply(2, cloud_settings, &UnavailableBluetoothController, &state)
            .expect_err("same revision must not overwrite local volume");

        assert_eq!(error.code, "audio_invalid_settings");
        let current = manager
            .current(&UnavailableBluetoothController, &state)
            .expect("current settings");
        assert_eq!(current.state.applied.levels.media, 55);
        let stored: StoredAudioSettings =
            serde_json::from_slice(&fs::read(settings_path).expect("settings file"))
                .expect("stored settings");
        assert_eq!(stored.settings.levels.media, 55);
        assert_eq!(stored.revision, 2);
    }

    #[test]
    fn managed_asound_config_includes_the_system_alsa_configuration() {
        let directory = tempfile::tempdir().expect("tempdir");
        let path = directory.path().join("asoundrc");

        write_asound_config(&path, Some("00:11:22:33:44:55"), None).expect("write asound config");

        let config = fs::read_to_string(path).expect("asound config");
        assert!(config.contains("</usr/share/alsa/alsa.conf>"));
        assert!(config.contains("pcm.yoyopod_bt_a2dp"));
        assert!(config.contains("pcm.yoyopod_bt_sco"));
    }

    #[allow(dead_code)]
    fn error_type_is_public(error: BluetoothOperationError) -> &'static str {
        error.code
    }
}
