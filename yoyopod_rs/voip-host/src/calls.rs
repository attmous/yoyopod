use serde_json::json;
use std::time::Instant;

#[derive(Debug, Clone)]
pub struct CallSession {
    state: String,
    active_call_id: Option<String>,
    active_peer: String,
    muted: bool,
    active_session: Option<CallSessionRecord>,
    last_finished_session: Option<CallSessionRecord>,
}

impl Default for CallSession {
    fn default() -> Self {
        Self {
            state: "idle".to_string(),
            active_call_id: None,
            active_peer: String::new(),
            muted: false,
            active_session: None,
            last_finished_session: None,
        }
    }
}

#[derive(Debug, Clone)]
struct CallSessionRecord {
    session_id: String,
    direction: String,
    peer_sip_address: String,
    started_at: Instant,
    answered: bool,
    terminal_state: String,
    local_end_action: String,
    duration_seconds: Option<u64>,
}

impl CallSessionRecord {
    fn new(session_id: &str, direction: &str, peer_sip_address: &str) -> Self {
        Self {
            session_id: session_id.to_string(),
            direction: direction.to_string(),
            peer_sip_address: peer_sip_address.to_string(),
            started_at: Instant::now(),
            answered: false,
            terminal_state: String::new(),
            local_end_action: String::new(),
            duration_seconds: None,
        }
    }

    fn duration_seconds(&self) -> u64 {
        self.duration_seconds
            .unwrap_or_else(|| self.started_at.elapsed().as_secs())
    }

    fn history_outcome(&self) -> String {
        if self.terminal_state.is_empty() {
            return String::new();
        }
        if self.answered {
            return "completed".to_string();
        }
        if self.direction == "incoming" && self.local_end_action == "reject" {
            return "rejected".to_string();
        }
        if self.terminal_state == "error" {
            return "failed".to_string();
        }
        if self.direction == "incoming" {
            return "missed".to_string();
        }
        "cancelled".to_string()
    }
}

impl CallSession {
    pub fn state(&self) -> &str {
        &self.state
    }

    pub fn active_call_id(&self) -> Option<&str> {
        self.active_call_id.as_deref()
    }

    pub fn active_peer(&self) -> &str {
        &self.active_peer
    }

    pub fn muted(&self) -> bool {
        self.muted
    }

    pub fn session_payload(&self) -> serde_json::Value {
        if let Some(session) = self.active_session.as_ref() {
            return json!({
                "active": true,
                "session_id": session.session_id,
                "direction": session.direction,
                "peer_sip_address": session.peer_sip_address,
                "answered": session.answered,
                "terminal_state": "",
                "local_end_action": session.local_end_action,
                "duration_seconds": session.duration_seconds(),
                "history_outcome": "",
            });
        }
        if let Some(session) = self.last_finished_session.as_ref() {
            return json!({
                "active": false,
                "session_id": session.session_id,
                "direction": session.direction,
                "peer_sip_address": session.peer_sip_address,
                "answered": session.answered,
                "terminal_state": session.terminal_state,
                "local_end_action": session.local_end_action,
                "duration_seconds": session.duration_seconds(),
                "history_outcome": session.history_outcome(),
            });
        }
        json!({
            "active": false,
            "session_id": "",
            "direction": "",
            "peer_sip_address": "",
            "answered": false,
            "terminal_state": "",
            "local_end_action": "",
            "duration_seconds": 0,
            "history_outcome": "",
        })
    }

    pub fn set_active_call_id(&mut self, call_id: Option<String>) {
        self.active_call_id = call_id;
    }

    pub fn start_outgoing(&mut self, call_id: &str, peer: &str) {
        self.active_call_id = Some(call_id.to_string());
        self.active_peer = peer.to_string();
        self.state = "outgoing_init".to_string();
        self.begin_session(call_id, "outgoing", peer);
    }

    pub fn incoming(&mut self, call_id: &str, peer: &str) {
        self.active_call_id = Some(call_id.to_string());
        self.active_peer = peer.to_string();
        self.state = "incoming".to_string();
        self.begin_session(call_id, "incoming", peer);
    }

    pub fn set_muted(&mut self, muted: bool) {
        self.muted = muted;
    }

    pub fn apply_call_state(&mut self, call_id: &str, state: &str) {
        self.state = state.to_string();
        if is_terminal_call_state(state) {
            if self.matches_active_session(call_id) {
                self.finish_session(state, None);
                self.clear_identity();
            }
        } else {
            self.active_call_id = Some(call_id.to_string());
            if is_answered_call_state(state) {
                self.mark_answered();
            }
        }
    }

    pub fn clear(&mut self) {
        self.state = "idle".to_string();
        self.clear_identity();
        self.active_session = None;
        self.last_finished_session = None;
    }

    pub fn clear_with_state(&mut self, state: &str) {
        self.state = state.to_string();
        self.finish_session(state, None);
        self.clear_identity();
    }

    pub fn clear_with_state_and_action(&mut self, state: &str, local_end_action: &str) {
        self.state = state.to_string();
        self.finish_session(state, Some(local_end_action));
        self.clear_identity();
    }

    fn clear_identity(&mut self) {
        self.active_call_id = None;
        self.active_peer.clear();
        self.muted = false;
    }

    fn begin_session(&mut self, session_id: &str, direction: &str, peer_sip_address: &str) {
        self.active_session = Some(CallSessionRecord::new(
            session_id,
            direction,
            peer_sip_address,
        ));
        self.last_finished_session = None;
    }

    fn mark_answered(&mut self) {
        if let Some(session) = self.active_session.as_mut() {
            session.answered = true;
        }
    }

    fn finish_session(&mut self, state: &str, local_end_action: Option<&str>) {
        if let Some(mut session) = self.active_session.take() {
            session.terminal_state = state.to_string();
            if let Some(action) = local_end_action {
                session.local_end_action = action.to_string();
            }
            session.duration_seconds = Some(session.started_at.elapsed().as_secs());
            self.last_finished_session = Some(session);
        }
    }

    fn matches_active_session(&self, call_id: &str) -> bool {
        self.active_call_id.as_deref() == Some(call_id)
            || self.active_call_id.is_none()
            || self
                .active_session
                .as_ref()
                .is_some_and(|session| session.peer_sip_address == call_id)
    }
}

fn is_terminal_call_state(state: &str) -> bool {
    matches!(state, "idle" | "released" | "error" | "end")
}

fn is_answered_call_state(state: &str) -> bool {
    matches!(
        state,
        "connected" | "streams_running" | "paused" | "paused_by_remote" | "updated_by_remote"
    )
}
