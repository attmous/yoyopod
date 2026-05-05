use serde::{Deserialize, Serialize};
use serde_json::{json, Value};

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct UiIntent {
    pub domain: String,
    pub action: String,
    #[serde(default = "empty_payload")]
    pub payload: Value,
}

impl UiIntent {
    pub fn new(domain: impl Into<String>, action: impl Into<String>) -> Self {
        Self {
            domain: domain.into(),
            action: action.into(),
            payload: empty_payload(),
        }
    }

    pub fn with_payload(
        domain: impl Into<String>,
        action: impl Into<String>,
        payload: Value,
    ) -> Self {
        Self {
            domain: domain.into(),
            action: action.into(),
            payload,
        }
    }
}

fn empty_payload() -> Value {
    json!({})
}
