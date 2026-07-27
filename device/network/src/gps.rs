use crate::at::AtCommandSet;
use crate::transport::{LineTransport, TransportError};
use time::format_description::well_known::Rfc3339;
use time::{Date, Month, PrimitiveDateTime, Time};

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

    let mut lat = ddmm_to_decimal(lat_raw.parse().ok()?, 90.0)?;
    if lat_hemi == "S" {
        lat = -lat;
    }

    let mut lng = ddmm_to_decimal(lng_raw.parse().ok()?, 180.0)?;
    if lng_hemi == "W" {
        lng = -lng;
    }
    if !lat.is_finite()
        || !lng.is_finite()
        || !(-90.0..=90.0).contains(&lat)
        || !(-180.0..=180.0).contains(&lng)
    {
        return None;
    }

    Some(GpsFix {
        lat,
        lng,
        altitude: fields[6].parse().ok()?,
        speed: fields[7].parse().ok()?,
        timestamp: parse_gnss_timestamp(fields[4], fields[5]),
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

fn ddmm_to_decimal(value: f64, max_degrees: f64) -> Option<f64> {
    if !value.is_finite() || value < 0.0 {
        return None;
    }
    let degrees = (value / 100.0).floor();
    let minutes = value - (degrees * 100.0);
    if degrees > max_degrees || !(0.0..60.0).contains(&minutes) {
        return None;
    }
    let decimal = degrees + (minutes / 60.0);
    (decimal <= max_degrees).then_some(decimal)
}

fn parse_gnss_timestamp(date: &str, utc: &str) -> Option<String> {
    let date = date.trim();
    let utc = utc.trim();
    if date.len() != 6 || utc.len() < 6 {
        return None;
    }
    let day = date.get(0..2)?.parse::<u8>().ok()?;
    let month = Month::try_from(date.get(2..4)?.parse::<u8>().ok()?).ok()?;
    let short_year = date.get(4..6)?.parse::<i32>().ok()?;
    let year = if short_year >= 80 {
        1900 + short_year
    } else {
        2000 + short_year
    };
    let hour = utc.get(0..2)?.parse::<u8>().ok()?;
    let minute = utc.get(2..4)?.parse::<u8>().ok()?;
    let seconds = utc.get(4..)?.parse::<f64>().ok()?;
    if !seconds.is_finite() || !(0.0..60.0).contains(&seconds) {
        return None;
    }
    let second = seconds.floor() as u8;
    let nanosecond = ((seconds - f64::from(second)) * 1_000_000_000.0).round() as u32;
    let date = Date::from_calendar_date(year, month, day).ok()?;
    let time = Time::from_hms_nano(hour, minute, second, nanosecond).ok()?;
    PrimitiveDateTime::new(date, time)
        .assume_utc()
        .format(&Rfc3339)
        .ok()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_timestamp_and_hemispheres() {
        let fix = parse_cgpsinfo(
            "\r\n+CGPSINFO: 3459.5000,S,05822.2500,W,270726,142305.250,17.5,2.0\r\nOK\r\n",
        )
        .expect("valid fix");

        assert!((fix.lat - -34.991_666_666).abs() < 0.000_001);
        assert!((fix.lng - -58.370_833_333).abs() < 0.000_001);
        assert_eq!(fix.timestamp.as_deref(), Some("2026-07-27T14:23:05.25Z"));
    }

    #[test]
    fn rejects_no_fix_and_invalid_coordinates() {
        assert!(parse_cgpsinfo("+CGPSINFO: ,,,,,,,,").is_none());
        assert!(
            parse_cgpsinfo("+CGPSINFO: 9060.0000,N,01131.0000,E,270726,142305.000,1.0,0.0")
                .is_none()
        );
    }
}
