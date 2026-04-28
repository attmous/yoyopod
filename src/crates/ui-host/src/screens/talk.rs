use crate::runtime::{ListItemSnapshot, UiScreen, UiView};

pub fn view(focus_index: usize) -> UiView {
    UiView {
        screen: UiScreen::Talk,
        title: "Talk".to_string(),
        subtitle: "Calls and notes".to_string(),
        footer: "Tap = Next | 2x Tap = Open | Hold = Back".to_string(),
        items: items(),
        focus_index,
    }
}

pub fn items() -> Vec<ListItemSnapshot> {
    vec![
        ListItemSnapshot::new("contacts", "Contacts", "Call someone", "contact"),
        ListItemSnapshot::new("call_history", "History", "Recent calls", "history"),
        ListItemSnapshot::new("voice_note", "Voice Note", "Record a note", "mic"),
    ]
}
