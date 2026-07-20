use yoyopod_protocol::ui::{RuntimeSnapshot, RuntimeSnapshotPatch};

use super::{domains, full, SnapshotChange};

pub fn apply_patch(current: &mut RuntimeSnapshot, patch: RuntimeSnapshotPatch) -> SnapshotChange {
    let previous_app_state = current.app_state;
    let domain = patch.domain();

    match patch {
        RuntimeSnapshotPatch::Full(snapshot) => {
            return full::replace_full(current, snapshot);
        }
        RuntimeSnapshotPatch::AppState(app_state) => current.app_state = app_state,
        RuntimeSnapshotPatch::Hub(hub) => domains::hub::apply(current, hub),
        RuntimeSnapshotPatch::Music(music) => domains::music::apply(current, music),
        RuntimeSnapshotPatch::Call(call) => domains::call::apply(current, call),
        RuntimeSnapshotPatch::Voice(voice) => domains::voice::apply(current, voice),
        RuntimeSnapshotPatch::Power(power) => domains::power::apply(current, power),
        RuntimeSnapshotPatch::Settings(settings) => current.settings = settings,
        RuntimeSnapshotPatch::Network(network) => domains::network::apply(current, network),
        RuntimeSnapshotPatch::Overlay(overlay) => domains::overlay::apply(current, overlay),
    }

    SnapshotChange {
        domain,
        previous_app_state,
        app_state: current.app_state,
    }
}
