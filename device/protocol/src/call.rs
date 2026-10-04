use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum CallTransport {
    Gsm,
    Sip,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum DeviceMode {
    Normal,
    Silent,
    DoNotDisturb,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum CallDirection {
    Incoming,
    Outgoing,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum CallPhase {
    Preparing,
    Ringing,
    Answering,
    Outgoing,
    Active,
    Ending,
    Ended,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum RejectReason {
    Unapproved,
    Busy,
    Cancelled,
    Timeout,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum CallAction {
    Answer,
    Reject(RejectReason),
    Hangup,
    SetMute(bool),
}

impl Default for DeviceMode {
    fn default() -> Self {
        Self::Normal
    }
}
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
/// Worker-owned identity for one call in one supervised worker generation.
/// All fields are required on the wire; `call_id` must contain non-whitespace text.
/// Transport serializes as the snake_case string `gsm` or `sip`.
pub struct SessionKey {
    pub transport: CallTransport,
    pub generation: u64,
    #[serde(deserialize_with = "nonempty_call_id")]
    pub call_id: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct CallOffer {
    pub key: SessionKey,
    pub address: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct CallUpdate {
    pub key: SessionKey,
    pub direction: CallDirection,
    pub phase: CallPhase,
    pub address: String,
    pub duration_seconds: u64,
    pub muted: bool,
    pub sequence: u64,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
/// Targets exactly the supplied session; receivers must never infer the current call.
/// Actions use snake_case serde enum encoding (for example `"answer"` or
/// `{ "reject": "busy" }`).
pub struct CallCommand {
    pub key: SessionKey,
    pub action: CallAction,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct InterruptForCall {
    pub key: SessionKey,
    pub activity_generation: u64,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct RingtoneRequest {
    pub key: SessionKey,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ContactPrioritySet {
    pub contact_id: String,
    pub priority: bool,
}

fn nonempty_call_id<'de, D: serde::Deserializer<'de>>(deserializer: D) -> Result<String, D::Error> {
    let value = String::deserialize(deserializer)?;
    if value.trim().is_empty() {
        return Err(serde::de::Error::custom("call_id must be non-empty"));
    }
    Ok(value)
}
