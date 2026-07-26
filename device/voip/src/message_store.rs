use crate::messages::{normalize_message_record, MessageRecord};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};
use time::{format_description::well_known::Rfc3339, OffsetDateTime};

const DEFAULT_MAX_ENTRIES: usize = 200;
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
struct StoredMessage {
    id: String,
    peer_sip_address: String,
    sender_sip_address: String,
    recipient_sip_address: String,
    kind: String,
    direction: String,
    delivery_state: String,
    created_at: String,
    updated_at: String,
    #[serde(default)]
    text: String,
    #[serde(default)]
    local_file_path: String,
    #[serde(default)]
    mime_type: String,
    #[serde(default)]
    duration_ms: i32,
    #[serde(default)]
    unread: bool,
    #[serde(default)]
    display_name: String,
}

#[derive(Debug, Default, Serialize, Deserialize)]
struct StorePayload {
    #[serde(default)]
    messages: Vec<StoredMessage>,
}

#[derive(Debug, Clone)]
pub struct MessageStore {
    store_dir: Option<PathBuf>,
    max_entries: usize,
    messages: Vec<StoredMessage>,
}

impl Default for MessageStore {
    fn default() -> Self {
        Self::memory(DEFAULT_MAX_ENTRIES)
    }
}

impl MessageStore {
    pub fn memory(max_entries: usize) -> Self {
        Self {
            store_dir: None,
            max_entries: max_entries.max(1),
            messages: Vec::new(),
        }
    }

    pub fn open(store_dir: impl AsRef<Path>, max_entries: usize) -> Self {
        let store_dir = store_dir.as_ref();
        if store_dir.as_os_str().is_empty() {
            return Self::memory(max_entries);
        }

        let mut store = Self {
            store_dir: Some(store_dir.to_path_buf()),
            max_entries: max_entries.max(1),
            messages: Vec::new(),
        };
        store.load();
        store
    }

    pub fn upsert(&mut self, message: MessageRecord) -> Result<(), String> {
        let message = normalize_message_record(message);
        let previous = self.take_message(&message.message_id);
        let now = now_timestamp();
        let stored = StoredMessage {
            id: message.message_id,
            peer_sip_address: message.peer_sip_address,
            sender_sip_address: message.sender_sip_address,
            recipient_sip_address: message.recipient_sip_address,
            kind: message.kind,
            direction: message.direction,
            delivery_state: message.delivery_state,
            created_at: previous
                .as_ref()
                .map(|message| message.created_at.clone())
                .unwrap_or_else(|| now.clone()),
            updated_at: now,
            text: message.text,
            local_file_path: message.local_file_path,
            mime_type: message.mime_type,
            duration_ms: message.duration_ms.max(0),
            unread: message.unread,
            display_name: previous
                .map(|message| message.display_name)
                .unwrap_or_default(),
        };
        self.messages.insert(0, stored);
        self.truncate();
        self.save()
    }

    pub fn update_delivery(
        &mut self,
        message_id: &str,
        delivery_state: &str,
        local_file_path: &str,
    ) -> Result<(), String> {
        if let Some(message) = self.find_mut(message_id) {
            message.delivery_state = delivery_state.to_string();
            if !local_file_path.is_empty() {
                message.local_file_path = local_file_path.to_string();
            }
            message.updated_at = now_timestamp();
            self.reorder_message(message_id);
            return self.save();
        }
        Ok(())
    }

    pub fn update_download(
        &mut self,
        message_id: &str,
        local_file_path: &str,
        mime_type: &str,
    ) -> Result<(), String> {
        if let Some(message) = self.find_mut(message_id) {
            if !local_file_path.is_empty() {
                message.local_file_path = local_file_path.to_string();
            }
            if !mime_type.is_empty() {
                message.mime_type = mime_type.to_string();
            }
            message.updated_at = now_timestamp();
            self.reorder_message(message_id);
            return self.save();
        }
        Ok(())
    }

    pub fn mark_contact_seen(&mut self, sip_address: &str) -> Result<(), String> {
        let mut changed = false;
        let now = now_timestamp();
        for message in &mut self.messages {
            if message.peer_sip_address == sip_address
                && message.direction == "incoming"
                && message.unread
            {
                message.unread = false;
                message.updated_at = now.clone();
                changed = true;
            }
        }
        if changed {
            return self.save();
        }
        Ok(())
    }

    pub fn delete_voice_note(&mut self, message_id: &str) -> Result<Option<String>, String> {
        let Some(index) = self
            .messages
            .iter()
            .position(|message| message.id == message_id && message.kind == "voice_note")
        else {
            return Ok(None);
        };
        let removed = self.messages.remove(index);
        if let Err(error) = self.save() {
            self.messages.insert(index, removed);
            return Err(error);
        }
        Ok(Some(removed.local_file_path))
    }

    pub fn summary_payload(&self) -> Value {
        json!({
            "unread_voice_notes": self.unread_voice_note_count(),
            "unread_voice_notes_by_contact": self.unread_voice_note_counts_by_contact(),
            "latest_voice_note_by_contact": self.latest_voice_note_by_contact(),
            "voice_notes_by_contact": self.voice_notes_by_contact(),
        })
    }

    fn load(&mut self) {
        let Some(index_file) = self.index_file() else {
            self.messages.clear();
            return;
        };
        let Ok(contents) = fs::read_to_string(index_file) else {
            self.messages.clear();
            return;
        };
        match serde_json::from_str::<StorePayload>(&contents) {
            Ok(mut payload) => {
                payload.messages.truncate(self.max_entries);
                self.messages = payload.messages;
            }
            Err(error) => {
                eprintln!("failed to load VoIP message store: {error}");
                self.messages.clear();
            }
        }
    }

    fn save(&self) -> Result<(), String> {
        let Some(store_dir) = &self.store_dir else {
            return Ok(());
        };
        fs::create_dir_all(store_dir).map_err(|error| error.to_string())?;
        let index_file = store_dir.join("messages.json");
        let payload = StorePayload {
            messages: self
                .messages
                .iter()
                .take(self.max_entries)
                .cloned()
                .collect(),
        };
        let encoded = serde_json::to_string_pretty(&payload).map_err(|error| error.to_string())?;
        fs::write(index_file, encoded).map_err(|error| error.to_string())
    }

    fn index_file(&self) -> Option<PathBuf> {
        self.store_dir
            .as_ref()
            .map(|store_dir| store_dir.join("messages.json"))
    }

    fn unread_voice_note_count(&self) -> usize {
        self.messages
            .iter()
            .filter(|message| is_unread_incoming_voice_note(message))
            .count()
    }

    fn unread_voice_note_counts_by_contact(&self) -> BTreeMap<String, usize> {
        let mut counts = BTreeMap::new();
        for message in &self.messages {
            if is_unread_incoming_voice_note(message) && !message.peer_sip_address.is_empty() {
                *counts.entry(message.peer_sip_address.clone()).or_insert(0) += 1;
            }
        }
        counts
    }

    fn latest_voice_note_by_contact(&self) -> BTreeMap<String, Value> {
        let mut latest = BTreeMap::new();
        for message in &self.messages {
            if message.kind != "voice_note"
                || message.peer_sip_address.is_empty()
                || latest.contains_key(&message.peer_sip_address)
            {
                continue;
            }
            latest.insert(
                message.peer_sip_address.clone(),
                json!({
                    "message_id": message.id,
                    "direction": message.direction,
                    "delivery_state": message.delivery_state,
                    "local_file_path": message.local_file_path,
                    "duration_ms": message.duration_ms.max(0),
                    "unread": message.unread,
                    "display_name": message.display_name,
                }),
            );
        }
        latest
    }

    fn voice_notes_by_contact(&self) -> BTreeMap<String, Vec<Value>> {
        let mut notes: BTreeMap<String, Vec<Value>> = BTreeMap::new();
        for message in &self.messages {
            if message.kind != "voice_note"
                || message.peer_sip_address.is_empty()
                || message.local_file_path.is_empty()
            {
                continue;
            }
            notes
                .entry(message.peer_sip_address.clone())
                .or_default()
                .push(voice_note_value(message));
        }
        notes
    }

    fn take_message(&mut self, message_id: &str) -> Option<StoredMessage> {
        let index = self
            .messages
            .iter()
            .position(|message| message.id == message_id)?;
        Some(self.messages.remove(index))
    }

    fn find_mut(&mut self, message_id: &str) -> Option<&mut StoredMessage> {
        self.messages
            .iter_mut()
            .find(|message| message.id == message_id)
    }

    fn reorder_message(&mut self, message_id: &str) {
        if let Some(message) = self.take_message(message_id) {
            self.messages.insert(0, message);
            self.truncate();
        }
    }

    fn truncate(&mut self) {
        self.messages.truncate(self.max_entries);
    }
}

fn voice_note_value(message: &StoredMessage) -> Value {
    json!({
        "message_id": message.id,
        "direction": message.direction,
        "delivery_state": message.delivery_state,
        "local_file_path": message.local_file_path,
        "duration_ms": message.duration_ms.max(0),
        "unread": message.unread,
        "display_name": message.display_name,
    })
}

fn is_unread_incoming_voice_note(message: &StoredMessage) -> bool {
    message.kind == "voice_note" && message.direction == "incoming" && message.unread
}

fn now_timestamp() -> String {
    OffsetDateTime::now_utc()
        .format(&Rfc3339)
        .unwrap_or_else(|_| fallback_timestamp())
}

fn fallback_timestamp() -> String {
    let seconds = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_secs())
        .unwrap_or_default();
    format!("1970-01-01T00:00:{:02}Z", seconds % 60)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn voice_note(id: &str, peer: &str, file_path: &str) -> MessageRecord {
        MessageRecord {
            message_id: id.to_string(),
            peer_sip_address: peer.to_string(),
            sender_sip_address: "sip:yoyopod@example.test".to_string(),
            recipient_sip_address: peer.to_string(),
            kind: "voice_note".to_string(),
            direction: "outgoing".to_string(),
            delivery_state: "failed".to_string(),
            text: String::new(),
            local_file_path: file_path.to_string(),
            mime_type: "audio/wav".to_string(),
            duration_ms: 7_000,
            unread: false,
        }
    }

    #[test]
    fn replay_queue_preserves_newest_first_contact_order() {
        let mut store = MessageStore::memory(10);
        store
            .upsert(voice_note(
                "first",
                "sip:mama@example.test",
                "/tmp/first.wav",
            ))
            .expect("store first note");
        store
            .upsert(voice_note(
                "second",
                "sip:mama@example.test",
                "/tmp/second.wav",
            ))
            .expect("store second note");

        let payload = store.summary_payload();
        let queue = payload["voice_notes_by_contact"]["sip:mama@example.test"]
            .as_array()
            .expect("contact queue");
        assert_eq!(queue.len(), 2);
        assert_eq!(queue[0]["message_id"], "second");
        assert_eq!(queue[1]["message_id"], "first");
    }

    #[test]
    fn deleting_a_voice_note_removes_it_from_replay() {
        let mut store = MessageStore::memory(10);
        store
            .upsert(voice_note("note", "sip:mama@example.test", "/tmp/note.wav"))
            .expect("store note");

        assert_eq!(
            store.delete_voice_note("note").expect("delete note"),
            Some("/tmp/note.wav".to_string())
        );
        assert!(store.summary_payload()["voice_notes_by_contact"]
            .as_object()
            .expect("queue map")
            .is_empty());
    }
}
