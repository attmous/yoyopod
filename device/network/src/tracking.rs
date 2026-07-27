use serde::{Deserialize, Serialize};
use serde_json::Value;

use crate::gps::GpsFix;

pub const GNSS_SAMPLE_INTERVAL_MS: u64 = 30_000;
pub const DEFAULT_MOVING_INTERVAL_SECONDS: u64 = 60;
pub const DEFAULT_STATIONARY_INTERVAL_SECONDS: u64 = 300;
const MOVING_SPEED_METERS_PER_SECOND: f64 = 0.8;
const MOVING_DISPLACEMENT_METERS: f64 = 25.0;
const KNOTS_TO_METERS_PER_SECOND: f64 = 0.514_444;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub struct LocationSettings {
    pub background_tracking_enabled: bool,
    pub moving_interval_seconds: u64,
    pub stationary_interval_seconds: u64,
}

impl Default for LocationSettings {
    fn default() -> Self {
        Self {
            background_tracking_enabled: true,
            moving_interval_seconds: DEFAULT_MOVING_INTERVAL_SECONDS,
            stationary_interval_seconds: DEFAULT_STATIONARY_INTERVAL_SECONDS,
        }
    }
}

impl LocationSettings {
    pub fn validate(self) -> Result<Self, &'static str> {
        if !(30..=900).contains(&self.moving_interval_seconds) {
            return Err("moving_interval_out_of_range");
        }
        if !(120..=3_600).contains(&self.stationary_interval_seconds) {
            return Err("stationary_interval_out_of_range");
        }
        if self.stationary_interval_seconds < self.moving_interval_seconds {
            return Err("stationary_interval_before_moving");
        }
        Ok(self)
    }

    pub fn from_cloud_config(value: &Value) -> Result<Self, &'static str> {
        if let Ok(settings) = serde_json::from_value::<Self>(value.clone()) {
            return settings.validate();
        }
        let features = value.get("features").unwrap_or(&Value::Null);
        let connectivity = value.get("connectivity").unwrap_or(&Value::Null);
        let background_tracking_enabled = features
            .get("location_tracking")
            .and_then(Value::as_bool)
            .unwrap_or(true);
        let moving_interval_seconds = connectivity
            .get("location_moving_interval_seconds")
            .and_then(Value::as_u64)
            .unwrap_or(DEFAULT_MOVING_INTERVAL_SECONDS);
        let stationary_interval_seconds = connectivity
            .get("location_stationary_interval_seconds")
            .and_then(Value::as_u64)
            .or_else(|| {
                connectivity
                    .get("location_report_interval_seconds")
                    .and_then(Value::as_u64)
            })
            .unwrap_or(DEFAULT_STATIONARY_INTERVAL_SECONDS);
        Self {
            background_tracking_enabled,
            moving_interval_seconds,
            stationary_interval_seconds,
        }
        .validate()
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct LocationFixEvent {
    pub schema_version: u8,
    pub fix_id: String,
    pub reason: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub command_id: Option<String>,
    pub reported_at: String,
    pub latitude: f64,
    pub longitude: f64,
    pub accuracy_meters: Option<f64>,
    pub altitude_meters: Option<f64>,
    pub speed_meters_per_second: Option<f64>,
    pub source: String,
}

impl LocationFixEvent {
    pub fn from_gps(
        fix: &GpsFix,
        fix_id: String,
        reason: &str,
        command_id: Option<String>,
        reported_at_fallback: String,
    ) -> Self {
        Self {
            schema_version: 1,
            fix_id,
            reason: reason.to_string(),
            command_id,
            reported_at: fix.timestamp.clone().unwrap_or(reported_at_fallback),
            latitude: fix.lat,
            longitude: fix.lng,
            accuracy_meters: None,
            altitude_meters: fix.altitude.is_finite().then_some(fix.altitude),
            speed_meters_per_second: fix
                .speed
                .is_finite()
                .then_some(fix.speed * KNOTS_TO_METERS_PER_SECOND),
            source: "gps".to_string(),
        }
    }
}

#[derive(Debug, Clone)]
pub struct TrackingEngine {
    settings: LocationSettings,
    last_sample_at_ms: Option<u64>,
    last_published_at_ms: Option<u64>,
    last_fix: Option<GpsFix>,
    consecutive_stationary_samples: u8,
    stationary: bool,
}

impl Default for TrackingEngine {
    fn default() -> Self {
        Self::new(LocationSettings::default())
    }
}

impl TrackingEngine {
    pub fn new(settings: LocationSettings) -> Self {
        Self {
            settings,
            last_sample_at_ms: None,
            last_published_at_ms: None,
            last_fix: None,
            consecutive_stationary_samples: 0,
            stationary: false,
        }
    }

    pub fn settings(&self) -> LocationSettings {
        self.settings
    }

    pub fn apply_settings(&mut self, settings: LocationSettings) {
        self.settings = settings;
        if !settings.background_tracking_enabled {
            self.last_sample_at_ms = None;
            self.consecutive_stationary_samples = 0;
            self.stationary = false;
        }
    }

    pub fn sample_due(&self, now_ms: u64) -> bool {
        self.settings.background_tracking_enabled
            && self
                .last_sample_at_ms
                .map(|last| now_ms.saturating_sub(last) >= GNSS_SAMPLE_INTERVAL_MS)
                .unwrap_or(true)
    }

    pub fn record_no_fix(&mut self, now_ms: u64) {
        self.last_sample_at_ms = Some(now_ms);
    }

    pub fn observe(&mut self, fix: &GpsFix, now_ms: u64) -> bool {
        self.last_sample_at_ms = Some(now_ms);
        let speed_mps = fix.speed * KNOTS_TO_METERS_PER_SECOND;
        let displacement = self
            .last_fix
            .as_ref()
            .map(|last| haversine_meters(last.lat, last.lng, fix.lat, fix.lng))
            .unwrap_or(0.0);
        let moving = speed_mps >= MOVING_SPEED_METERS_PER_SECOND
            || displacement >= MOVING_DISPLACEMENT_METERS;
        if moving {
            self.consecutive_stationary_samples = 0;
            self.stationary = false;
        } else {
            self.consecutive_stationary_samples =
                self.consecutive_stationary_samples.saturating_add(1);
            if self.consecutive_stationary_samples >= 2 {
                self.stationary = true;
            }
        }
        self.last_fix = Some(fix.clone());

        let interval_seconds = if self.stationary {
            self.settings.stationary_interval_seconds
        } else {
            self.settings.moving_interval_seconds
        };
        let publish = self
            .last_published_at_ms
            .map(|last| now_ms.saturating_sub(last) >= interval_seconds * 1_000)
            .unwrap_or(true);
        if publish {
            self.last_published_at_ms = Some(now_ms);
        }
        publish
    }
}

fn haversine_meters(lat1: f64, lng1: f64, lat2: f64, lng2: f64) -> f64 {
    let earth_radius_meters = 6_371_000.0_f64;
    let lat1 = lat1.to_radians();
    let lat2 = lat2.to_radians();
    let delta_lat = lat2 - lat1;
    let delta_lng = (lng2 - lng1).to_radians();
    let a =
        (delta_lat / 2.0).sin().powi(2) + lat1.cos() * lat2.cos() * (delta_lng / 2.0).sin().powi(2);
    2.0 * earth_radius_meters * a.sqrt().atan2((1.0 - a).sqrt())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn fix(lat: f64, speed_knots: f64) -> GpsFix {
        GpsFix {
            lat,
            lng: 13.4,
            altitude: 1.0,
            speed: speed_knots,
            timestamp: Some("2026-07-27T12:00:00Z".to_string()),
        }
    }

    #[test]
    fn stationary_mode_requires_two_low_motion_samples() {
        let mut engine = TrackingEngine::default();
        assert!(engine.observe(&fix(52.5, 0.0), 0));
        assert!(!engine.stationary);
        assert!(!engine.observe(&fix(52.5, 0.0), 30_000));
        assert!(engine.stationary);
        assert!(!engine.observe(&fix(52.5, 0.0), 60_000));
        assert!(engine.observe(&fix(52.5, 0.0), 300_000));
    }

    #[test]
    fn speed_or_displacement_selects_moving_interval() {
        let mut engine = TrackingEngine::default();
        assert!(engine.observe(&fix(52.5, 0.0), 0));
        assert!(!engine.observe(&fix(52.5, 0.0), 30_000));
        assert!(engine.observe(&fix(52.5003, 0.0), 60_000));
        assert!(!engine.stationary);
        assert!(engine.observe(&fix(52.5003, 2.0), 120_000));
    }

    #[test]
    fn legacy_cloud_config_uses_single_interval_as_stationary_fallback() {
        let settings = LocationSettings::from_cloud_config(&serde_json::json!({
            "features": {"location_tracking": false},
            "connectivity": {"location_report_interval_seconds": 600}
        }))
        .unwrap();
        assert!(!settings.background_tracking_enabled);
        assert_eq!(settings.moving_interval_seconds, 60);
        assert_eq!(settings.stationary_interval_seconds, 600);
    }
}
