use crate::runtime::{RuntimeSnapshot, UiScreen, UiView};

pub fn contacts_view(snapshot: &RuntimeSnapshot, focus_index: usize) -> UiView {
    UiView {
        screen: UiScreen::Contacts,
        title: "Contacts".to_string(),
        subtitle: "People".to_string(),
        footer: "Tap = Next | 2x Tap = Call | Hold = Back".to_string(),
        items: snapshot.call.contacts.clone(),
        focus_index,
    }
}

pub fn call_history_view(snapshot: &RuntimeSnapshot, focus_index: usize) -> UiView {
    UiView {
        screen: UiScreen::CallHistory,
        title: "History".to_string(),
        subtitle: "Recent calls".to_string(),
        footer: "Tap = Next | 2x Tap = Call | Hold = Back".to_string(),
        items: snapshot.call.history.clone(),
        focus_index,
    }
}

pub fn incoming_view(snapshot: &RuntimeSnapshot, focus_index: usize) -> UiView {
    UiView {
        screen: UiScreen::IncomingCall,
        title: call_peer_name(snapshot),
        subtitle: snapshot.call.peer_address.clone(),
        footer: "2x Tap = Answer | Hold = Reject".to_string(),
        items: Vec::new(),
        focus_index,
    }
}

pub fn outgoing_view(snapshot: &RuntimeSnapshot, focus_index: usize) -> UiView {
    UiView {
        screen: UiScreen::OutgoingCall,
        title: call_peer_name(snapshot),
        subtitle: snapshot.call.peer_address.clone(),
        footer: "Hold = Cancel".to_string(),
        items: Vec::new(),
        focus_index,
    }
}

pub fn in_call_view(snapshot: &RuntimeSnapshot, focus_index: usize) -> UiView {
    UiView {
        screen: UiScreen::InCall,
        title: call_peer_name(snapshot),
        subtitle: snapshot.call.duration_text.clone(),
        footer: "Tap = Mute | Hold = Hang Up".to_string(),
        items: Vec::new(),
        focus_index,
    }
}

fn call_peer_name(snapshot: &RuntimeSnapshot) -> String {
    if snapshot.call.peer_name.trim().is_empty() {
        "Unknown".to_string()
    } else {
        snapshot.call.peer_name.clone()
    }
}
