use crate::runtime::{RuntimeSnapshot, UiScreen, UiView};

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

pub fn voice_note_view(snapshot: &RuntimeSnapshot, focus_index: usize) -> UiView {
    UiView {
        screen: UiScreen::VoiceNote,
        title: if snapshot.voice.capture_in_flight {
            "Recording".to_string()
        } else {
            "Voice Note".to_string()
        },
        subtitle: snapshot.voice.body.clone(),
        footer: "2x Tap = Record | Hold = Back".to_string(),
        items: Vec::new(),
        focus_index,
    }
}
