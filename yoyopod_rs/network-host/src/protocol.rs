use serde::{Deserialize, Serialize};
use serde_json::{json, Value};

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct WorkerEnvelope {
    pub kind: String,
    #[serde(rename = "type")]
    pub r#type: String,
    #[serde(default)]
    pub payload: Value,
    #[serde(default)]
    pub request_id: Option<String>,
}

pub fn ready_event(config_dir: &str) -> WorkerEnvelope {
    WorkerEnvelope {
        kind: "event".to_string(),
        r#type: "network.ready".to_string(),
        payload: json!({ "config_dir": config_dir }),
        request_id: None,
    }
}

pub fn stopped_event(reason: &str) -> WorkerEnvelope {
    WorkerEnvelope {
        kind: "event".to_string(),
        r#type: "network.stopped".to_string(),
        payload: json!({ "reason": reason }),
        request_id: None,
    }
}
