use crate::runtime::{ListItemSnapshot, RuntimeSnapshot, UiScreen, UiView};
use crate::screens::{chrome, AskViewModel, TalkActionButtonModel, TalkActionsViewModel};

pub fn ask_model(snapshot: &RuntimeSnapshot) -> AskViewModel {
    AskViewModel {
        chrome: chrome::chrome(snapshot, "2x Tap = Ask | Hold = Back"),
        title: snapshot.voice.headline.clone(),
        subtitle: snapshot.voice.body.clone(),
        icon_key: "ask".to_string(),
    }
}

pub fn voice_note_model(
    snapshot: &RuntimeSnapshot,
    focus_index: usize,
    selected_contact: Option<&ListItemSnapshot>,
) -> TalkActionsViewModel {
    let contact_name = selected_contact
        .or_else(|| snapshot.call.contacts.first())
        .map(|contact| contact.title.clone())
        .unwrap_or_else(|| "Friend".to_string());
    let phase = voice_note_phase(snapshot);
    match phase.as_str() {
        "review" => voice_note_action_model(
            snapshot,
            &contact_name,
            focus_index,
            "Tap next / Double choose",
            vec![
                ("Send", "check", 1),
                ("Play", "play", 0),
                ("Again", "close", 2),
            ],
        ),
        "failed" => voice_note_action_model(
            snapshot,
            &contact_name,
            focus_index,
            "Tap next / Double choose",
            vec![("Retry", "retry", 2), ("Again", "close", 2)],
        ),
        "sending" => voice_note_primary_model(
            snapshot,
            &contact_name,
            "Sending",
            "Sending",
            0,
            "Please wait",
            "voice_note",
            0,
        ),
        "sent" => voice_note_primary_model(
            snapshot,
            &contact_name,
            "Sent",
            "Sent",
            1,
            "Double done / Hold back",
            "check",
            1,
        ),
        "recording" => voice_note_primary_model(
            snapshot,
            &contact_name,
            "Recording",
            "Recording",
            3,
            "Release to stop",
            "voice_note",
            3,
        ),
        _ => voice_note_primary_model(
            snapshot,
            &contact_name,
            "Voice Note",
            "Hold to record",
            4,
            "Hold record / Double back",
            "voice_note",
            3,
        ),
    }
}

pub fn ask_view(snapshot: &RuntimeSnapshot, focus_index: usize) -> UiView {
    UiView {
        screen: UiScreen::Ask,
        title: snapshot.voice.headline.clone(),
        subtitle: snapshot.voice.body.clone(),
        footer: "2x Tap = Ask | Hold = Back".to_string(),
        items: Vec::new(),
        focus_index,
    }
}

pub fn voice_note_view(
    snapshot: &RuntimeSnapshot,
    focus_index: usize,
    selected_contact: Option<&ListItemSnapshot>,
) -> UiView {
    let model = voice_note_model(snapshot, focus_index, selected_contact);
    let title = model.contact_name.clone();
    let subtitle = model.status.clone();
    let footer = model.chrome.footer.clone();
    let selected_index = model.selected_index;
    UiView {
        screen: UiScreen::VoiceNote,
        title,
        subtitle,
        footer,
        items: if model.layout_kind == 1 {
            Vec::new()
        } else {
            model
                .buttons
                .iter()
                .enumerate()
                .map(|(index, button)| {
                    ListItemSnapshot::new(
                        format!("voice_note_action_{index}"),
                        button.title.clone(),
                        "",
                        button.icon_key.clone(),
                    )
                })
                .collect()
        },
        focus_index: selected_index,
    }
}

pub fn voice_note_action_count(snapshot: &RuntimeSnapshot) -> usize {
    match voice_note_phase(snapshot).as_str() {
        "review" => 3,
        "failed" => 2,
        _ => 0,
    }
}

fn voice_note_action_model(
    snapshot: &RuntimeSnapshot,
    contact_name: &str,
    focus_index: usize,
    footer: &str,
    actions: Vec<(&'static str, &'static str, i32)>,
) -> TalkActionsViewModel {
    let selected_index = focus_index.min(actions.len().saturating_sub(1));
    TalkActionsViewModel {
        chrome: chrome::chrome(snapshot, footer),
        contact_name: contact_name.to_string(),
        title: actions
            .get(selected_index)
            .map(|action| action.0.to_string())
            .unwrap_or_default(),
        status: String::new(),
        status_kind: 0,
        buttons: actions
            .into_iter()
            .map(|(title, icon_key, color_kind)| TalkActionButtonModel {
                title: title.to_string(),
                icon_key: icon_key.to_string(),
                color_kind,
            })
            .collect(),
        selected_index,
        layout_kind: 0,
        button_size_kind: 0,
    }
}

fn voice_note_primary_model(
    snapshot: &RuntimeSnapshot,
    contact_name: &str,
    title: &str,
    status: &str,
    status_kind: i32,
    footer: &str,
    icon_key: &str,
    color_kind: i32,
) -> TalkActionsViewModel {
    TalkActionsViewModel {
        chrome: chrome::chrome(snapshot, footer),
        contact_name: contact_name.to_string(),
        title: title.to_string(),
        status: status.to_string(),
        status_kind,
        buttons: vec![TalkActionButtonModel {
            title: title.to_string(),
            icon_key: icon_key.to_string(),
            color_kind,
        }],
        selected_index: 0,
        layout_kind: 1,
        button_size_kind: 2,
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
