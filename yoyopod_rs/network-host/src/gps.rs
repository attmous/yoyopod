use crate::at::AtCommandSet;
use crate::transport::{LineTransport, TransportError};

#[derive(Debug, Clone, PartialEq)]
pub struct GpsFix {
    pub lat: f64,
    pub lng: f64,
    pub altitude: f64,
    pub speed: f64,
    pub timestamp: Option<String>,
}

pub fn parse_cgpsinfo(response: &str) -> Option<GpsFix> {
    let payload = response
        .lines()
        .map(str::trim)
        .find(|line| line.starts_with("+CGPSINFO:"))?
        .trim_start_matches("+CGPSINFO:")
        .trim();

    let fields: Vec<_> = payload.split(',').map(str::trim).collect();
    if fields.len() < 8 {
        return None;
    }

    let (lat_raw, lat_hemi, lng_raw, lng_hemi) = (fields[0], fields[1], fields[2], fields[3]);
    if lat_raw.is_empty() || lat_hemi.is_empty() || lng_raw.is_empty() || lng_hemi.is_empty() {
        return None;
    }
    if !matches!(lat_hemi, "N" | "S") || !matches!(lng_hemi, "E" | "W") {
        return None;
    }

    let mut lat = ddmm_to_decimal(lat_raw.parse().ok()?);
    if lat_hemi == "S" {
        lat = -lat;
    }

    let mut lng = ddmm_to_decimal(lng_raw.parse().ok()?);
    if lng_hemi == "W" {
        lng = -lng;
    }

    Some(GpsFix {
        lat,
        lng,
        altitude: fields[6].parse().ok()?,
        speed: fields[7].parse().ok()?,
        timestamp: None,
    })
}

pub struct GpsReader<T> {
    at: AtCommandSet<T>,
}

impl<T> GpsReader<T> {
    pub fn new(transport: T) -> Self {
        Self {
            at: AtCommandSet::new(transport),
        }
    }

    pub fn into_inner(self) -> T {
        self.at.into_inner()
    }
}

impl<T> GpsReader<T>
where
    T: LineTransport,
{
    pub fn enable(&mut self) -> Result<bool, TransportError> {
        self.at.enable_gps()
    }

    pub fn disable(&mut self) -> Result<(), TransportError> {
        self.at.disable_gps()
    }

    pub fn query(&mut self) -> Result<Option<GpsFix>, TransportError> {
        self.at.query_gps()
    }
}

fn ddmm_to_decimal(value: f64) -> f64 {
    let degrees = (value / 100.0).floor();
    let minutes = value - (degrees * 100.0);
    degrees + (minutes / 60.0)
}
