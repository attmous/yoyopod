use crate::runtime::{RuntimeSnapshot, UiScreen, UiView};

pub fn loading_view(snapshot: &RuntimeSnapshot) -> UiView {
    UiView {
        screen: UiScreen::Loading,
        title: "Loading".to_string(),
        subtitle: snapshot.overlay.message.clone(),
        footer: String::new(),
        items: Vec::new(),
        focus_index: 0,
    }
}

pub fn error_view(snapshot: &RuntimeSnapshot) -> UiView {
    UiView {
        screen: UiScreen::Error,
        title: "Error".to_string(),
        subtitle: snapshot.overlay.error.clone(),
        footer: "Hold = Back".to_string(),
        items: Vec::new(),
        focus_index: 0,
    }
}
