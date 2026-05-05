use serde_json::json;
use std::collections::HashMap;

const RCS_FT_HTTP_MIME: &str = "application/vnd.gsma.rcs-ft-http+xml";

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct MessageRecord {
    pub message_id: String,
    pub peer_sip_address: String,
    pub sender_sip_address: String,
    pub recipient_sip_address: String,
    pub kind: String,
    pub direction: String,
    pub delivery_state: String,
    pub text: String,
    pub local_file_path: String,
    pub mime_type: String,
    pub duration_ms: i32,
    pub unread: bool,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct MessageSessionState {
    message_id: String,
    kind: String,
    direction: String,
    delivery_state: String,
    local_file_path: String,
    error: String,
}

impl MessageSessionState {
    pub fn received(message: &MessageRecord) -> Self {
        Self {
            message_id: message.message_id.clone(),
            kind: message.kind.clone(),
            direction: message.direction.clone(),
            delivery_state: message.delivery_state.clone(),
            local_file_path: message.local_file_path.clone(),
            error: String::new(),
        }
    }

    pub fn delivery_changed(
        message_id: &str,
        delivery_state: &str,
        local_file_path: &str,
        error: &str,
    ) -> Self {
        Self {
            message_id: message_id.to_string(),
            kind: String::new(),
            direction: String::new(),
            delivery_state: delivery_state.to_string(),
            local_file_path: local_file_path.to_string(),
            error: error.to_string(),
        }
    }

    pub fn download_completed(message_id: &str, local_file_path: &str) -> Self {
        Self {
            message_id: message_id.to_string(),
            kind: String::new(),
            direction: String::new(),
            delivery_state: "delivered".to_string(),
            local_file_path: local_file_path.to_string(),
            error: String::new(),
        }
    }

    pub fn failed(message_id: &str, reason: &str) -> Self {
        Self {
            message_id: message_id.to_string(),
            kind: String::new(),
            direction: String::new(),
            delivery_state: "failed".to_string(),
            local_file_path: String::new(),
            error: reason.to_string(),
        }
    }

    pub fn payload(&self) -> serde_json::Value {
        json!({
            "message_id": self.message_id,
            "kind": self.kind,
            "direction": self.direction,
            "delivery_state": self.delivery_state,
            "local_file_path": self.local_file_path,
            "error": self.error,
        })
    }
}

#[derive(Debug, Default)]
pub struct OutboundMessageIds {
    ids: HashMap<String, String>,
}

impl OutboundMessageIds {
    pub fn len(&self) -> usize {
        self.ids.len()
    }

    pub fn clear(&mut self) {
        self.ids.clear();
    }

    pub fn translate(&mut self, backend_id: &str, terminal: bool) -> String {
        let client_id = self.ids.get(backend_id).cloned();
        if terminal && client_id.is_some() {
            self.ids.remove(backend_id);
        }
        client_id.unwrap_or_else(|| backend_id.to_string())
    }

    pub fn remember(
        &mut self,
        backend_id: &str,
        client_id: &str,
        label: &str,
    ) -> Result<(), String> {
        let backend_id = backend_id.trim();
        if backend_id.is_empty() {
            return Err(format!("{label} backend returned empty message id"));
        }
        if backend_id != client_id {
            self.ids
                .insert(backend_id.to_string(), client_id.to_string());
        }
        Ok(())
    }
}

pub fn is_terminal_delivery_state(value: &str) -> bool {
    matches!(value, "delivered" | "failed")
}

pub fn normalize_message_record(mut message: MessageRecord) -> MessageRecord {
    if message.mime_type != RCS_FT_HTTP_MIME || message.text.is_empty() {
        return message;
    }

    let voice_note_envelope = message.kind == "voice_note"
        || (message.kind == "text" && is_voice_recording_envelope(&message.text));
    if !voice_note_envelope {
        return message;
    }

    message.kind = "voice_note".to_string();
    message.mime_type =
        extract_voice_note_payload_mime(&message.text).unwrap_or_else(|| "audio/wav".to_string());
    if message.duration_ms <= 0 {
        message.duration_ms = extract_voice_note_duration_ms(&message.text);
    }
    message.text.clear();
    message
}

fn is_voice_recording_envelope(xml_text: &str) -> bool {
    xml_text.contains("voice-recording=yes")
}

fn extract_voice_note_payload_mime(xml_text: &str) -> Option<String> {
    let content_type = extract_tag_text(xml_text, "<content-type>", "</content-type>")?;
    let mime_type = content_type.split(';').next().unwrap_or("").trim();
    if mime_type.is_empty() {
        None
    } else {
        Some(mime_type.to_string())
    }
}

fn extract_voice_note_duration_ms(xml_text: &str) -> i32 {
    extract_tag_text(xml_text, "<am:playing-length>", "</am:playing-length>")
        .and_then(|duration| duration.parse::<i32>().ok())
        .unwrap_or_default()
        .max(0)
}

fn extract_tag_text<'a>(xml_text: &'a str, opening: &str, closing: &str) -> Option<&'a str> {
    let start = xml_text.find(opening)? + opening.len();
    let rest = &xml_text[start..];
    let end = rest.find(closing)?;
    Some(&rest[..end])
}
