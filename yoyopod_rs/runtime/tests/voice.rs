use yoyopod_runtime::voice::{
    match_voice_command, normalize_voice_activation, route_voice_transcript, VoiceCommandAlias,
    VoiceCommandIntent, VoiceCommandSettings, VoiceRouteKind,
};

#[test]
fn match_voice_command_extracts_family_call_variants() {
    for (phrase, expected_contact) in [
        ("call mama", "mama"),
        ("call mommy", "mommy"),
        ("call my mama", "mama"),
        ("please call my mom", "mom"),
        ("ring mama", "mama"),
        ("phone mom", "mom"),
        ("call daddy", "daddy"),
        ("call papa", "papa"),
    ] {
        let command = match_voice_command(phrase);

        assert_eq!(command.intent, VoiceCommandIntent::CallContact, "{phrase}");
        assert_eq!(command.contact_name, expected_contact, "{phrase}");
    }
}

#[test]
fn match_voice_command_handles_observed_stt_script_noise_for_call_mama() {
    for phrase in [
        "Kual mama?",
        "\u{ace0} \u{b9c8}\u{b9c8}",
        "\u{06a9}\u{0648}\u{0644} \u{0645}\u{0627}\u{0645}\u{0627}",
        "\u{06a9}\u{0648} \u{0645}\u{0627}\u{0645}\u{0627}",
    ] {
        let command = match_voice_command(phrase);

        assert_eq!(command.intent, VoiceCommandIntent::CallContact, "{phrase}");
        assert_eq!(command.contact_name, "mama", "{phrase}");
    }
}

#[test]
fn match_voice_command_tolerates_python_fuzzy_trigger_typos() {
    for (phrase, expected_contact) in [("caall mama", "mama"), ("phonee mama", "mama")] {
        let command = match_voice_command(phrase);

        assert_eq!(command.intent, VoiceCommandIntent::CallContact, "{phrase}");
        assert_eq!(command.contact_name, expected_contact, "{phrase}");
    }

    for (phrase, expected_intent) in [
        ("volum up", VoiceCommandIntent::VolumeUp),
        ("shufle music", VoiceCommandIntent::PlayMusic),
    ] {
        assert_eq!(
            match_voice_command(phrase).intent,
            expected_intent,
            "{phrase}"
        );
    }
}

#[test]
fn match_voice_command_handles_music_volume_screen_and_mic_phrases() {
    for (phrase, expected_intent) in [
        ("play a song", VoiceCommandIntent::PlayMusic),
        ("play songs", VoiceCommandIntent::PlayMusic),
        ("put on music", VoiceCommandIntent::PlayMusic),
        ("start songs", VoiceCommandIntent::PlayMusic),
        ("play kids music", VoiceCommandIntent::PlayMusic),
        ("play", VoiceCommandIntent::PlayMusic),
        ("\u{63a8},\u{97f3}\u{4e50}", VoiceCommandIntent::PlayMusic),
        (
            "\u{067e}\u{0644}\u{06cc} \u{0645}\u{0648}\u{0632}\u{06cc}\u{06a9}",
            VoiceCommandIntent::PlayMusic,
        ),
        ("louder", VoiceCommandIntent::VolumeUp),
        ("make it louder", VoiceCommandIntent::VolumeUp),
        ("too quiet", VoiceCommandIntent::VolumeUp),
        (
            "\u{0648}\u{0648}\u{0644}\u{06cc}\u{0648}\u{0645} \u{0627}\u{067e}",
            VoiceCommandIntent::VolumeUp,
        ),
        ("quieter", VoiceCommandIntent::VolumeDown),
        ("make it quieter", VoiceCommandIntent::VolumeDown),
        ("too loud", VoiceCommandIntent::VolumeDown),
        ("read this", VoiceCommandIntent::ReadScreen),
        ("what is on the screen", VoiceCommandIntent::ReadScreen),
        ("turn off the mic", VoiceCommandIntent::MuteMic),
        ("mute the microphone", VoiceCommandIntent::MuteMic),
        ("turn on the microphone", VoiceCommandIntent::UnmuteMic),
        ("unmute the mic", VoiceCommandIntent::UnmuteMic),
    ] {
        assert_eq!(
            match_voice_command(phrase).intent,
            expected_intent,
            "{phrase}"
        );
    }
}

#[test]
fn match_voice_command_rejects_negated_and_nearby_non_commands() {
    for phrase in [
        "loud",
        "quiet",
        "not louder",
        "do not make it louder",
        "turn volume not up",
        "read this book",
        "turn on the music",
        "turn off the light",
        "mute music",
        "play a game",
        "do not call mom",
        "don't call mom",
        "never call dad",
        "can t call mom",
        "do nt call mom",
        "call not mom",
    ] {
        assert_eq!(
            match_voice_command(phrase).intent,
            VoiceCommandIntent::Unknown,
            "{phrase}"
        );
    }
}

#[test]
fn route_voice_transcript_strips_activation_before_ask_fallback() {
    let settings = VoiceCommandSettings::default();

    let decision = route_voice_transcript("hey yoyo why is mars red", &settings);

    assert_eq!(decision.kind, VoiceRouteKind::AskFallback);
    assert_eq!(decision.stripped_prefix, "hey yoyo");
    assert_eq!(decision.normalized_text, "why is mars red");
}

#[test]
fn route_voice_transcript_recognizes_ask_exit_before_fallback() {
    let settings = VoiceCommandSettings {
        ask_fallback_enabled: false,
        ..VoiceCommandSettings::default()
    };

    for phrase in [
        "exit ask",
        "hey yoyo go back",
        "yoyo stop asking",
        "stop ask",
        "leave ask",
        "close ask",
    ] {
        let decision = route_voice_transcript(phrase, &settings);

        assert_eq!(decision.kind, VoiceRouteKind::AskExit, "{phrase}");
        assert_eq!(decision.reason, "ask_exit", "{phrase}");
        assert_eq!(decision.command, None, "{phrase}");
    }
}

#[test]
fn command_dictionary_call_alias_requires_contact_slot() {
    let settings = VoiceCommandSettings {
        command_aliases: vec![VoiceCommandAlias {
            intent: VoiceCommandIntent::CallContact,
            aliases: vec!["dial".to_string()],
        }],
        ..VoiceCommandSettings::default()
    };

    let incomplete = route_voice_transcript("hey yoyo dial", &settings);
    assert_eq!(incomplete.kind, VoiceRouteKind::AskFallback);

    let command = route_voice_transcript("hey yoyo dial mama", &settings);
    assert_eq!(command.kind, VoiceRouteKind::Command);
    let command = command.command.expect("command");
    assert_eq!(command.intent, VoiceCommandIntent::CallContact);
    assert_eq!(command.contact_name, "mama");
}

#[test]
fn command_dictionary_aliases_use_intent_fuzzy_matching() {
    let settings = VoiceCommandSettings {
        command_aliases: vec![VoiceCommandAlias {
            intent: VoiceCommandIntent::VolumeUp,
            aliases: vec!["boost sound".to_string()],
        }],
        ..VoiceCommandSettings::default()
    };

    let decision = route_voice_transcript("hey yoyo boast sound", &settings);

    assert_eq!(decision.kind, VoiceRouteKind::Command);
    let command = decision.command.expect("command");
    assert_eq!(command.intent, VoiceCommandIntent::VolumeUp);
}

#[test]
fn normalize_voice_activation_handles_repeated_yoyo_prefixes() {
    let prefixes = vec!["yoyo".to_string(), "hey yoyo".to_string()];

    let result = normalize_voice_activation("yo yo yoyo play music", &prefixes);

    assert_eq!(result.stripped_prefix, "yoyo");
    assert_eq!(result.normalized_text, "play music");
}
