use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc::{self, Receiver};
use std::sync::Arc;
use std::thread;
use std::time::Duration;

use anyhow::{Context, Result};
use rumqttc::{Client, Event, Incoming, MqttOptions, QoS, Transport};
use serde_json::Value;

use crate::config::CloudHostConfig;

const MAX_MQTT_EVENTS_PER_DRAIN: usize = 64;

#[derive(Debug, Clone, PartialEq)]
pub enum MqttRuntimeEvent {
    Connected,
    Disconnected(String),
    Command(Value),
    Error(String),
}

pub trait CloudMqttBackend {
    fn start(&mut self, config: &CloudHostConfig) -> Result<()>;
    fn stop(&mut self);
    fn is_connected(&self) -> bool;
    fn publish(&mut self, topic: &str, payload: &str, qos: u8) -> Result<bool>;
    fn drain_events(&mut self) -> Vec<MqttRuntimeEvent>;
}

#[derive(Default)]
pub struct DisabledMqttBackend;

impl CloudMqttBackend for DisabledMqttBackend {
    fn start(&mut self, _config: &CloudHostConfig) -> Result<()> {
        Ok(())
    }

    fn stop(&mut self) {}

    fn is_connected(&self) -> bool {
        false
    }

    fn publish(&mut self, _topic: &str, _payload: &str, _qos: u8) -> Result<bool> {
        Ok(false)
    }

    fn drain_events(&mut self) -> Vec<MqttRuntimeEvent> {
        Vec::new()
    }
}

#[derive(Default)]
pub struct RumqttBackend {
    client: Option<Client>,
    connected: Arc<AtomicBool>,
    events: Option<Receiver<MqttRuntimeEvent>>,
}

impl CloudMqttBackend for RumqttBackend {
    fn start(&mut self, config: &CloudHostConfig) -> Result<()> {
        self.stop();
        let mut options = mqtt_options(config)?;
        options.set_keep_alive(Duration::from_secs(60));
        options.set_clean_session(true);
        if !config.mqtt_username.trim().is_empty() {
            options.set_credentials(config.mqtt_username.clone(), config.mqtt_password.clone());
        }

        let (client, mut connection) = Client::new(options, 16);
        client
            .subscribe(config.device_command_topic(), QoS::AtLeastOnce)
            .context("subscribe cloud command topic")?;

        let (tx, rx) = mpsc::channel();
        let connected = Arc::new(AtomicBool::new(false));
        let connected_for_thread = Arc::clone(&connected);
        thread::spawn(move || {
            let mut disconnect_reported = false;
            for notification in connection.iter() {
                match notification {
                    Ok(Event::Incoming(Incoming::ConnAck(_))) => {
                        mark_connected(&connected_for_thread, &mut disconnect_reported);
                        let _ = tx.send(MqttRuntimeEvent::Connected);
                    }
                    Ok(Event::Incoming(Incoming::Disconnect)) => {
                        if mark_disconnected(&connected_for_thread, &mut disconnect_reported) {
                            let _ =
                                tx.send(MqttRuntimeEvent::Disconnected("broker disconnect".into()));
                        }
                    }
                    Ok(Event::Incoming(Incoming::Publish(publish))) => {
                        match serde_json::from_slice::<Value>(&publish.payload) {
                            Ok(payload) => {
                                let _ = tx.send(MqttRuntimeEvent::Command(payload));
                            }
                            Err(error) => {
                                let _ = tx.send(MqttRuntimeEvent::Error(format!(
                                    "invalid MQTT command payload: {error}"
                                )));
                            }
                        }
                    }
                    Ok(_) => {}
                    Err(error) => {
                        if mark_disconnected(&connected_for_thread, &mut disconnect_reported) {
                            let _ = tx.send(MqttRuntimeEvent::Disconnected(error.to_string()));
                        }
                    }
                }
            }
        });

        self.client = Some(client);
        self.connected = connected;
        self.events = Some(rx);
        Ok(())
    }

    fn stop(&mut self) {
        self.connected.store(false, Ordering::SeqCst);
        if let Some(client) = &self.client {
            let _ = client.disconnect();
        }
        self.client = None;
        self.events = None;
    }

    fn is_connected(&self) -> bool {
        self.connected.load(Ordering::SeqCst)
    }

    fn publish(&mut self, topic: &str, payload: &str, qos: u8) -> Result<bool> {
        let Some(client) = &self.client else {
            return Ok(false);
        };
        client
            .publish(topic, qos_from_u8(qos), false, payload.as_bytes())
            .with_context(|| format!("publish MQTT topic {topic}"))?;
        Ok(true)
    }

    fn drain_events(&mut self) -> Vec<MqttRuntimeEvent> {
        let Some(rx) = &self.events else {
            return Vec::new();
        };
        let mut events = Vec::new();
        while events.len() < MAX_MQTT_EVENTS_PER_DRAIN {
            let Ok(event) = rx.try_recv() else {
                break;
            };
            events.push(event);
        }
        events
    }
}

fn mark_connected(connected: &AtomicBool, disconnect_reported: &mut bool) {
    connected.store(true, Ordering::SeqCst);
    *disconnect_reported = false;
}

fn mark_disconnected(connected: &AtomicBool, disconnect_reported: &mut bool) -> bool {
    connected.store(false, Ordering::SeqCst);
    if *disconnect_reported {
        return false;
    }
    *disconnect_reported = true;
    true
}

fn mqtt_options(config: &CloudHostConfig) -> Result<MqttOptions> {
    let client_id = format!("yoyopod-{}", config.device_id.trim());
    let transport = config.mqtt_transport.trim().to_ascii_lowercase();
    let mut options = if matches!(
        transport.as_str(),
        "websocket" | "websockets" | "ws" | "wss"
    ) {
        let broker_url = websocket_broker_url(config);
        MqttOptions::new(client_id, broker_url, config.mqtt_broker_port)
    } else {
        MqttOptions::new(
            client_id,
            config.mqtt_broker_host.trim(),
            config.mqtt_broker_port,
        )
    };

    if matches!(
        transport.as_str(),
        "websocket" | "websockets" | "ws" | "wss"
    ) {
        if config.mqtt_use_tls || transport == "wss" {
            options.set_transport(Transport::wss_with_default_config());
        } else {
            options.set_transport(Transport::ws());
        }
    } else if config.mqtt_use_tls {
        options.set_transport(Transport::tls_with_default_config());
    }

    Ok(options)
}

fn websocket_broker_url(config: &CloudHostConfig) -> String {
    let host = config.mqtt_broker_host.trim();
    if host.starts_with("ws://") || host.starts_with("wss://") {
        return host.to_string();
    }
    let scheme = if config.mqtt_use_tls { "wss" } else { "ws" };
    format!("{scheme}://{host}:{}/mqtt", config.mqtt_broker_port)
}

fn qos_from_u8(qos: u8) -> QoS {
    match qos {
        0 => QoS::AtMostOnce,
        2 => QoS::ExactlyOnce,
        _ => QoS::AtLeastOnce,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn disconnect_events_are_reported_once_until_reconnect() {
        let connected = AtomicBool::new(true);
        let mut disconnect_reported = false;

        assert!(mark_disconnected(&connected, &mut disconnect_reported));
        assert!(!connected.load(Ordering::SeqCst));
        assert!(!mark_disconnected(&connected, &mut disconnect_reported));

        mark_connected(&connected, &mut disconnect_reported);
        assert!(connected.load(Ordering::SeqCst));
        assert!(mark_disconnected(&connected, &mut disconnect_reported));
    }

    #[test]
    fn mqtt_event_drain_is_bounded() {
        let (tx, rx) = mpsc::channel();
        for index in 0..(MAX_MQTT_EVENTS_PER_DRAIN + 3) {
            tx.send(MqttRuntimeEvent::Command(json!({ "index": index })))
                .unwrap();
        }
        let mut backend = RumqttBackend {
            client: None,
            connected: Arc::new(AtomicBool::new(false)),
            events: Some(rx),
        };

        assert_eq!(backend.drain_events().len(), MAX_MQTT_EVENTS_PER_DRAIN);
        assert_eq!(backend.drain_events().len(), 3);
    }
}
