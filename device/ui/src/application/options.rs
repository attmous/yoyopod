use yoyopod_protocol::ui::{ListItemSnapshot, RuntimeSnapshot};

#[derive(Debug, Clone, Copy)]
pub struct TalkContactAction {
    pub kind: &'static str,
}

pub fn listen_items(_snapshot: &RuntimeSnapshot) -> Vec<ListItemSnapshot> {
    vec![
        ListItemSnapshot::new("playlists", "Playlists", "", "icon_playlists"),
        ListItemSnapshot::new("recent_tracks", "Recents", "", "icon_recents"),
        ListItemSnapshot::new("shuffle", "Shuffle all", "", "icon_shuffle"),
    ]
}

pub fn talk_contact_actions(
    snapshot: &RuntimeSnapshot,
    selected_contact: Option<&ListItemSnapshot>,
) -> Vec<TalkContactAction> {
    if selected_contact
        .or_else(|| snapshot.call.contacts.first())
        .is_some_and(|contact| contact.communication_unavailable)
    {
        return Vec::new();
    }
    vec![
        TalkContactAction { kind: "call" },
        TalkContactAction { kind: "record" },
        TalkContactAction { kind: "replay" },
    ]
}

pub fn voice_note_action_count(snapshot: &RuntimeSnapshot) -> usize {
    match voice_note_phase(snapshot).as_str() {
        "review" => 3,
        "failed" => 2,
        _ => 0,
    }
}

fn voice_note_phase(snapshot: &RuntimeSnapshot) -> String {
    let phase = snapshot.voice.phase.trim().to_ascii_lowercase();
    if snapshot.voice.capture_in_flight || snapshot.voice.ptt_active || phase == "recording" {
        return "recording".to_string();
    }
    if matches!(phase.as_str(), "review" | "sending" | "sent" | "failed") {
        return phase;
    }
    "ready".to_string()
}
