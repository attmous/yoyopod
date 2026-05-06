use serde_json::json;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct LifecycleEvent {
    pub state: String,
    pub previous_state: String,
    pub reason: String,
    pub recovered: bool,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct LifecycleState {
    state: String,
    reason: String,
    recovery_pending: bool,
    events: Vec<LifecycleEvent>,
}

impl Default for LifecycleState {
    fn default() -> Self {
        Self {
            state: "unconfigured".to_string(),
            reason: String::new(),
            recovery_pending: false,
            events: Vec::new(),
        }
    }
}

impl LifecycleState {
    pub fn state(&self) -> &str {
        &self.state
    }

    pub fn reason(&self) -> &str {
        &self.reason
    }

    pub fn recovery_pending(&self) -> bool {
        self.recovery_pending
    }

    pub fn mark_recovery_pending(&mut self) {
        self.recovery_pending = true;
    }

    pub fn clear_recovery_pending(&mut self) {
        self.recovery_pending = false;
    }

    pub fn backend_available(&self, registered: bool) -> bool {
        registered && self.state == "registered"
    }

    pub fn payload(&self, registered: bool) -> serde_json::Value {
        json!({
            "state": self.state,
            "reason": self.reason,
            "backend_available": self.backend_available(registered),
        })
    }

    pub fn record(&mut self, state: &str, reason: &str, recovered: bool) {
        let previous_state = self.state.clone();
        let state = state.to_string();
        let reason = reason.to_string();
        self.state = state.clone();
        self.reason = reason.clone();
        self.events.push(LifecycleEvent {
            state,
            previous_state,
            reason,
            recovered,
        });
    }

    pub fn take_events(&mut self) -> Vec<LifecycleEvent> {
        std::mem::take(&mut self.events)
    }
}
