use std::collections::{HashMap, VecDeque};
use std::time::Duration;

use yoyopod_network_host::at::{
    parse_carrier, parse_registration, parse_signal_quality, AtCommandSet, CarrierInfo,
    SimStatus, SignalInfo,
};
use yoyopod_network_host::gps::{parse_cgpsinfo, GpsFix, GpsReader};
use yoyopod_network_host::transport::{LineTransport, TransportError};

#[derive(Default)]
struct FakeTransport {
    responses: HashMap<String, VecDeque<String>>,
    sent: Vec<(String, Option<Duration>)>,
}

impl FakeTransport {
    fn with_response(mut self, command: &str, response: &str) -> Self {
        self.responses
            .entry(command.to_string())
            .or_default()
            .push_back(response.to_string());
        self
    }
}

impl LineTransport for FakeTransport {
    fn send_command(
        &mut self,
        command: &str,
        timeout: Option<Duration>,
    ) -> Result<String, TransportError> {
        self.sent.push((command.to_string(), timeout));
        Ok(self
            .responses
            .get_mut(command)
            .and_then(VecDeque::pop_front)
            .unwrap_or_else(|| "OK".to_string()))
    }
}

#[test]
fn parse_cgpsinfo_returns_decimal_fix_and_telemetry() {
    let fix = parse_cgpsinfo("+CGPSINFO: 4852.4300,N,00221.1300,E,130426,120000.0,35.0,0.5,\nOK")
        .expect("gps fix should parse");

    assert!((fix.lat - 48.873_833).abs() < 0.000_1);
    assert!((fix.lng - 2.352_166).abs() < 0.000_1);
    assert_eq!(
        fix,
        GpsFix {
            lat: fix.lat,
            lng: fix.lng,
            altitude: 35.0,
            speed: 0.5,
            timestamp: None,
        }
    );
}

#[test]
fn parse_cgpsinfo_returns_none_for_no_fix_payload() {
    assert_eq!(parse_cgpsinfo("+CGPSINFO: ,,,,,,,,\nOK"), None);
}

#[test]
fn parse_cgpsinfo_rejects_malformed_hemisphere_markers() {
    assert_eq!(
        parse_cgpsinfo("+CGPSINFO: 4852.4300,Q,00221.1300,E,130426,120000.0,35.0,0.5,\nOK"),
        None
    );
    assert_eq!(
        parse_cgpsinfo("+CGPSINFO: 4852.4300,N,00221.1300,Q,130426,120000.0,35.0,0.5,\nOK"),
        None
    );
}

#[test]
fn parse_cgpsinfo_applies_southern_and_western_hemisphere_signs() {
    let fix = parse_cgpsinfo("+CGPSINFO: 3351.1200,S,15112.3400,W,130426,120000.0,12.5,1.2,\nOK")
        .expect("gps fix should parse");

    assert!(fix.lat < 0.0);
    assert!(fix.lng < 0.0);
    assert_eq!(fix.altitude, 12.5);
    assert_eq!(fix.speed, 1.2);
}

#[test]
fn signal_bars_follow_python_thresholds() {
    let cases = [
        (SignalInfo { csq: 0 }, 0),
        (SignalInfo { csq: 5 }, 1),
        (SignalInfo { csq: 12 }, 2),
        (SignalInfo { csq: 20 }, 3),
        (SignalInfo { csq: 28 }, 4),
        (SignalInfo { csq: 99 }, 0),
    ];

    for (signal, expected_bars) in cases {
        assert_eq!(
            signal.bars(),
            expected_bars,
            "unexpected bars for csq {}",
            signal.csq
        );
    }
}

#[test]
fn parse_signal_quality_defaults_to_not_detectable_when_missing() {
    assert_eq!(parse_signal_quality("ERROR"), SignalInfo { csq: 99 });
}

#[test]
fn parse_carrier_maps_known_access_technologies() {
    assert_eq!(
        parse_carrier("+COPS: 0,0,\"T-Mobile\",7\nOK"),
        CarrierInfo {
            carrier: "T-Mobile".to_string(),
            network_type: "4G".to_string(),
        }
    );
    assert_eq!(
        parse_carrier("+COPS: 0,0,\"Carrier\",2\nOK"),
        CarrierInfo {
            carrier: "Carrier".to_string(),
            network_type: "3G".to_string(),
        }
    );
    assert_eq!(
        parse_carrier("+COPS: 0,0,\"Carrier\",0\nOK"),
        CarrierInfo {
            carrier: "Carrier".to_string(),
            network_type: "2G".to_string(),
        }
    );
}

#[test]
fn parse_registration_treats_home_and_roaming_as_registered() {
    assert!(parse_registration("+CEREG: 0,1\nOK"));
    assert!(parse_registration("+CEREG: 0,5\nOK"));
    assert!(!parse_registration("+CEREG: 0,0\nOK"));
}

#[test]
fn at_command_set_get_signal_quality_sends_expected_command_and_timeout() {
    let transport = FakeTransport::default().with_response("AT+CSQ", "+CSQ: 18,0\nOK");
    let mut at = AtCommandSet::new(transport);

    let info = at
        .get_signal_quality()
        .expect("signal response should parse");

    assert_eq!(info, SignalInfo { csq: 18 });
    let transport = at.into_inner();
    assert_eq!(
        transport.sent,
        vec![("AT+CSQ".to_string(), Some(Duration::from_secs(2)))]
    );
}

#[test]
fn at_command_set_configure_pdp_formats_python_compatible_command() {
    let transport = FakeTransport::default();
    let mut at = AtCommandSet::new(transport);

    at.configure_pdp("internet")
        .expect("pdp command should send");

    let transport = at.into_inner();
    assert_eq!(
        transport.sent,
        vec![(
            "AT+CGDCONT=1,\"IP\",\"internet\"".to_string(),
            Some(Duration::from_secs(2))
        )]
    );
}

#[test]
fn gps_reader_enable_and_query_delegate_to_at_commands() {
    let transport = FakeTransport::default()
        .with_response("AT+CGPS=1", "OK")
        .with_response(
            "AT+CGPSINFO",
            "+CGPSINFO: 4852.4300,N,00221.1300,E,130426,120000.0,35.0,0.5,\nOK",
        );
    let mut reader = GpsReader::new(transport);

    assert!(reader.enable().expect("enable should succeed"));
    let fix = reader
        .query()
        .expect("query should succeed")
        .expect("fix expected");

    assert!((fix.lat - 48.873_833).abs() < 0.000_1);
    let transport = reader.into_inner();
    assert_eq!(
        transport.sent,
        vec![
            ("AT+CGPS=1".to_string(), Some(Duration::from_secs(2))),
            ("AT+CGPSINFO".to_string(), Some(Duration::from_secs(2))),
        ]
    );
}

#[test]
fn at_command_set_reports_sim_pin_state_and_unlocks_sim_with_configured_pin() {
    let transport = FakeTransport::default()
        .with_response("AT+CPIN?", "+CPIN: SIM PIN\nOK")
        .with_response("AT+CPIN=1234", "OK")
        .with_response("AT+CPIN?", "+CPIN: READY\nOK");
    let mut at = AtCommandSet::new(transport);

    assert_eq!(
        at.get_sim_status().expect("cpin status should parse"),
        SimStatus::PinRequired
    );
    assert!(at
        .unlock_sim("1234")
        .expect("pin unlock command should return success"));
    assert_eq!(
        at.get_sim_status().expect("cpin ready should parse"),
        SimStatus::Ready
    );

    let transport = at.into_inner();
    assert_eq!(
        transport.sent,
        vec![
            ("AT+CPIN?".to_string(), Some(Duration::from_secs(2))),
            ("AT+CPIN=\"1234\"".to_string(), Some(Duration::from_secs(2))),
            ("AT+CPIN?".to_string(), Some(Duration::from_secs(2))),
        ]
    );
}

#[test]
fn at_command_set_supports_full_functionality_and_reset_commands() {
    let transport = FakeTransport::default()
        .with_response("AT+CFUN=1", "OK")
        .with_response("AT+CFUN=6", "OK");
    let mut at = AtCommandSet::new(transport);

    at.radio_full().expect("cfun full should succeed");
    at.radio_reset().expect("cfun reset should succeed");

    let transport = at.into_inner();
    assert_eq!(
        transport.sent,
        vec![
            ("AT+CFUN=1".to_string(), Some(Duration::from_secs(2))),
            ("AT+CFUN=6".to_string(), Some(Duration::from_secs(2))),
        ]
    );
}
