use yoyopod_protocol::ui::{RuntimeSnapshot, UiScreen};

pub fn runtime_preemption(snapshot: &RuntimeSnapshot) -> Option<UiScreen> {
    runtime_preemption_for_display(snapshot, true)
}

pub fn runtime_preemption_for_display(
    snapshot: &RuntimeSnapshot,
    loading_visible: bool,
) -> Option<UiScreen> {
    if !snapshot.overlay.error.trim().is_empty() {
        return Some(UiScreen::Error);
    }
    if snapshot.overlay.loading && loading_visible {
        return Some(UiScreen::Loading);
    }
    match snapshot.call.state.as_str() {
        "incoming" => Some(UiScreen::IncomingCall),
        "outgoing" => Some(UiScreen::OutgoingCall),
        "active" => Some(UiScreen::InCall),
        _ => None,
    }
}

pub const fn is_call_screen(screen: UiScreen) -> bool {
    matches!(
        screen,
        UiScreen::IncomingCall | UiScreen::OutgoingCall | UiScreen::InCall
    )
}

pub const fn is_overlay_screen(screen: UiScreen) -> bool {
    matches!(screen, UiScreen::Loading | UiScreen::Error)
}
