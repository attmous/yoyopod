use serde_json::Value;

use crate::state::RuntimeState;

pub fn build_status_payload(state: &RuntimeState) -> Value {
    state.status_payload()
}
