use serde_json::json;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CallHistoryEntry {
    pub session_id: String,
    pub peer_sip_address: String,
    pub direction: String,
    pub outcome: String,
    pub duration_seconds: u64,
    pub seen: bool,
}

#[derive(Debug, Clone)]
pub struct CallHistoryStore {
    max_entries: usize,
    entries: Vec<CallHistoryEntry>,
}

impl Default for CallHistoryStore {
    fn default() -> Self {
        Self::memory(50)
    }
}

impl CallHistoryStore {
    pub fn memory(max_entries: usize) -> Self {
        Self {
            max_entries: max_entries.max(1),
            entries: Vec::new(),
        }
    }

    pub fn record(&mut self, entry: CallHistoryEntry) {
        self.entries.insert(0, entry);
        self.entries.truncate(self.max_entries);
    }

    pub fn mark_seen(&mut self, peer_sip_address: &str) {
        let peer_sip_address = peer_sip_address.trim();
        for entry in &mut self.entries {
            if peer_sip_address.is_empty() || entry.peer_sip_address == peer_sip_address {
                entry.seen = true;
            }
        }
    }

    pub fn unseen_count(&self) -> usize {
        self.entries.iter().filter(|entry| !entry.seen).count()
    }

    pub fn summary_payload(&self) -> serde_json::Value {
        json!({
            "unseen_call_history": self.unseen_count(),
            "recent_call_history": self.entries.iter().map(entry_payload).collect::<Vec<_>>(),
        })
    }
}

fn entry_payload(entry: &CallHistoryEntry) -> serde_json::Value {
    json!({
        "session_id": entry.session_id,
        "peer_sip_address": entry.peer_sip_address,
        "direction": entry.direction,
        "outcome": entry.outcome,
        "duration_seconds": entry.duration_seconds,
        "seen": entry.seen,
    })
}
