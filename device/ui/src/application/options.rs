use yoyopod_protocol::ui::{ListItemSnapshot, RuntimeSnapshot};

#[derive(Debug, Clone, Copy)]
pub struct TalkContactAction {
    pub kind: &'static str,
}

pub fn listen_items(_snapshot: &RuntimeSnapshot) -> Vec<ListItemSnapshot> {
    vec![
        ListItemSnapshot::new("playlists", "Playlists", "Saved mixes", "playlist"),
        ListItemSnapshot::new("recent_tracks", "Recent", "Recently played", "recent"),
        ListItemSnapshot::new("shuffle", "Shuffle All", "Start music", "shuffle"),
    ]
}

pub fn talk_contact_actions(
    snapshot: &RuntimeSnapshot,
    selected_contact: Option<&ListItemSnapshot>,
) -> Vec<TalkContactAction> {
    let contact = selected_contact.or_else(|| snapshot.call.contacts.first());
    let mut actions = vec![
        TalkContactAction { kind: "call" },
        TalkContactAction { kind: "voice_note" },
    ];
    if contact
        .and_then(|contact| snapshot.call.latest_voice_note_by_contact.get(&contact.id))
        .is_some_and(|note| !note.local_file_path.trim().is_empty())
    {
        actions.push(TalkContactAction { kind: "play_note" });
    }
    actions
}

pub fn voice_note_action_count(snapshot: &RuntimeSnapshot) -> usize {
    match voice_note_phase(snapshot).as_str() {
        "review" => 3,
        "failed" => 2,
        _ => 0,
    }
}

pub fn power_page_count(snapshot: &RuntimeSnapshot) -> usize {
    if !snapshot.power.pages.is_empty() {
        return snapshot.power.pages.len();
    }
    if !snapshot.power.rows.is_empty() {
        return 1;
    }
    4
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
