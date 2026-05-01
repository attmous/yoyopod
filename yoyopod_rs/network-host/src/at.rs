use std::time::Duration;

use crate::gps::{parse_cgpsinfo, GpsFix};
use crate::transport::{LineTransport, TransportError};

const ACCESS_TECH_2G: &str = "2G";
const ACCESS_TECH_3G: &str = "3G";
const ACCESS_TECH_4G: &str = "4G";
const ACCESS_TECH_UNKNOWN: &str = "unknown";

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SignalInfo {
    pub csq: u8,
}

impl SignalInfo {
    pub fn bars(&self) -> u8 {
        match self.csq {
            99 | 0 => 0,
            1..=9 => 1,
            10..=14 => 2,
            15..=24 => 3,
            _ => 4,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Default)]
pub struct CarrierInfo {
    pub carrier: String,
    pub network_type: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum SimStatus {
    Ready,
    PinRequired,
    PukRequired,
    NotInserted,
    Unknown(String),
}

pub fn parse_signal_quality(response: &str) -> SignalInfo {
    let csq = find_prefixed_line(response, "+CSQ:")
        .and_then(|line| line.split(',').next())
        .and_then(|value| value.trim().parse::<u8>().ok())
        .unwrap_or(99);
    SignalInfo { csq }
}

pub fn parse_carrier(response: &str) -> CarrierInfo {
    let Some(line) = find_prefixed_line(response, "+COPS:") else {
        return CarrierInfo::default();
    };
    let Some(open_quote) = line.find('"') else {
        return CarrierInfo::default();
    };
    let remainder = &line[(open_quote + 1)..];
    let Some(close_quote) = remainder.find('"') else {
        return CarrierInfo::default();
    };
    let carrier = &remainder[..close_quote];
    let tech_code = remainder[(close_quote + 1)..]
        .trim_start_matches(',')
        .split(',')
        .next()
        .map(str::trim)
        .unwrap_or_default();

    CarrierInfo {
        carrier: carrier.to_string(),
        network_type: access_technology_name(tech_code).to_string(),
    }
}

pub fn parse_registration(response: &str) -> bool {
    find_prefixed_line(response, "+CEREG:")
        .and_then(|line| line.split(',').nth(1))
        .map(str::trim)
        .is_some_and(|status| matches!(status, "1" | "5"))
}

pub fn parse_sim_status(response: &str) -> SimStatus {
    match find_prefixed_line(response, "+CPIN:") {
        Some("READY") => SimStatus::Ready,
        Some("SIM PIN") => SimStatus::PinRequired,
        Some("SIM PUK") => SimStatus::PukRequired,
        Some("NOT INSERTED") => SimStatus::NotInserted,
        Some(status) => SimStatus::Unknown(status.to_string()),
        None => SimStatus::Unknown(response.trim().to_string()),
    }
}

pub struct AtCommandSet<T> {
    transport: T,
}

impl<T> AtCommandSet<T> {
    pub fn new(transport: T) -> Self {
        Self { transport }
    }

    pub fn into_inner(self) -> T {
        self.transport
    }

    pub fn transport_mut(&mut self) -> &mut T {
        &mut self.transport
    }
}

impl<T> AtCommandSet<T>
where
    T: LineTransport,
{
    pub fn ping(&mut self) -> Result<bool, TransportError> {
        Ok(self.send("AT")?.contains("OK"))
    }

    pub fn echo_off(&mut self) -> Result<(), TransportError> {
        self.send("ATE0")?;
        Ok(())
    }

    pub fn check_sim(&mut self) -> Result<bool, TransportError> {
        Ok(matches!(self.get_sim_status()?, SimStatus::Ready))
    }

    pub fn get_sim_status(&mut self) -> Result<SimStatus, TransportError> {
        Ok(parse_sim_status(&self.send("AT+CPIN?")?))
    }

    pub fn unlock_sim(&mut self, pin: &str) -> Result<bool, TransportError> {
        Ok(self
            .send(&format!("AT+CPIN=\"{}\"", pin.trim()))?
            .contains("OK"))
    }

    pub fn get_signal_quality(&mut self) -> Result<SignalInfo, TransportError> {
        Ok(parse_signal_quality(&self.send("AT+CSQ")?))
    }

    pub fn get_carrier(&mut self) -> Result<CarrierInfo, TransportError> {
        Ok(parse_carrier(&self.send("AT+COPS?")?))
    }

    pub fn get_registration(&mut self) -> Result<bool, TransportError> {
        Ok(parse_registration(&self.send("AT+CEREG?")?))
    }

    pub fn configure_pdp(&mut self, apn: &str) -> Result<(), TransportError> {
        self.send(&format!("AT+CGDCONT=1,\"IP\",\"{}\"", apn))?;
        Ok(())
    }

    pub fn enable_gps(&mut self) -> Result<bool, TransportError> {
        Ok(self.send("AT+CGPS=1")?.contains("OK"))
    }

    pub fn disable_gps(&mut self) -> Result<(), TransportError> {
        self.send("AT+CGPS=0")?;
        Ok(())
    }

    pub fn query_gps(&mut self) -> Result<Option<GpsFix>, TransportError> {
        Ok(parse_cgpsinfo(&self.send("AT+CGPSINFO")?))
    }

    pub fn hangup(&mut self) -> Result<(), TransportError> {
        self.send("ATH")?;
        Ok(())
    }

    pub fn radio_full(&mut self) -> Result<(), TransportError> {
        self.send("AT+CFUN=1")?;
        Ok(())
    }

    pub fn radio_off(&mut self) -> Result<(), TransportError> {
        self.send("AT+CFUN=0")?;
        Ok(())
    }

    pub fn radio_reset(&mut self) -> Result<(), TransportError> {
        self.send("AT+CFUN=6")?;
        Ok(())
    }

    fn send(&mut self, command: &str) -> Result<String, TransportError> {
        self.transport
            .send_command(command, Some(Duration::from_secs(2)))
    }
}

fn find_prefixed_line<'a>(response: &'a str, prefix: &str) -> Option<&'a str> {
    response
        .lines()
        .map(str::trim)
        .find(|line| line.starts_with(prefix))
        .map(|line| line.trim_start_matches(prefix).trim())
}

fn access_technology_name(code: &str) -> &'static str {
    match code {
        "0" => ACCESS_TECH_2G,
        "2" => ACCESS_TECH_3G,
        "7" => ACCESS_TECH_4G,
        _ => ACCESS_TECH_UNKNOWN,
    }
}
