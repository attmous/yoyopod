pub(crate) fn icon_label(icon_key: &str) -> String {
    if let Some(monogram) = icon_key.strip_prefix("mono:") {
        if !monogram.is_empty() {
            return monogram.to_string();
        }
    }

    let label = match icon_key {
        "playlist" | "people" | "person" | "contact" | "contacts" => "\u{f00b}",
        "ask" => "AI",
        "battery" | "setup" | "power" => "\u{f011}",
        "call_active" | "call_incoming" | "call_outgoing" | "call" | "talk" => "\u{f095}",
        "check" => "\u{f00c}",
        "clock" | "retry" | "recent" | "history" => "\u{f021}",
        "close" => "\u{f00d}",
        "play" | "icon_play" => "\u{f04b}",
        "listen" | "music_note" | "track" => "\u{f001}",
        "microphone" | "mic" | "voice_note" => "\u{f304}",
        "signal" | "network" => "\u{f1eb}",
        "care" | "settings" => "\u{f013}",
        "mic_off" => "X",
        _ => "\u{f00b}",
    };
    label.to_string()
}
