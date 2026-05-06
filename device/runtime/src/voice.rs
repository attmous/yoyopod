use std::collections::HashSet;
use std::fs;
use std::path::Path;

use serde_json::Value;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct VoiceCommandSettings {
    pub commands_enabled: bool,
    pub ai_requests_enabled: bool,
    pub activation_prefixes: Vec<String>,
    pub ask_fallback_enabled: bool,
    pub disabled_intents: Vec<VoiceCommandIntent>,
    pub command_aliases: Vec<VoiceCommandAlias>,
    pub route_actions: Vec<VoiceRouteAction>,
    pub ask_model: String,
    pub ask_instructions: String,
    pub ask_max_history_turns: usize,
    pub ask_max_response_chars: usize,
}

impl Default for VoiceCommandSettings {
    fn default() -> Self {
        Self {
            commands_enabled: true,
            ai_requests_enabled: true,
            activation_prefixes: vec!["yoyo".to_string(), "hey yoyo".to_string()],
            ask_fallback_enabled: true,
            disabled_intents: Vec::new(),
            command_aliases: Vec::new(),
            route_actions: Vec::new(),
            ask_model: "gpt-4.1-mini".to_string(),
            ask_instructions: DEFAULT_ASK_INSTRUCTIONS.to_string(),
            ask_max_history_turns: 4,
            ask_max_response_chars: 480,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct VoiceCaptureSettings {
    pub sample_rate_hz: u64,
    pub request_timeout_ms: u64,
    pub max_audio_ms: u64,
    pub stt_model: String,
    pub stt_language: String,
    pub stt_prompt: String,
}

impl Default for VoiceCaptureSettings {
    fn default() -> Self {
        Self {
            sample_rate_hz: 16_000,
            request_timeout_ms: 12_000,
            max_audio_ms: 30_000,
            stt_model: "gpt-4o-mini-transcribe".to_string(),
            stt_language: "en".to_string(),
            stt_prompt: DEFAULT_STT_PROMPT.to_string(),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct VoiceSpeechSettings {
    pub sample_rate_hz: u64,
    pub request_timeout_ms: u64,
    pub tts_model: String,
    pub tts_voice: String,
    pub tts_instructions: String,
}

impl Default for VoiceSpeechSettings {
    fn default() -> Self {
        Self {
            sample_rate_hz: 16_000,
            request_timeout_ms: 12_000,
            tts_model: "gpt-4o-mini-tts".to_string(),
            tts_voice: "coral".to_string(),
            tts_instructions: DEFAULT_TTS_INSTRUCTIONS.to_string(),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct VoiceCommandAlias {
    pub intent: VoiceCommandIntent,
    pub aliases: Vec<String>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct VoiceRouteAction {
    pub route_name: String,
    pub aliases: Vec<String>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum VoiceConfirmationResponse {
    Yes,
    No,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct VoiceCommandDictionary {
    pub disabled_intents: Vec<VoiceCommandIntent>,
    pub command_aliases: Vec<VoiceCommandAlias>,
    pub route_actions: Vec<VoiceRouteAction>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum VoiceCommandIntent {
    CallContact,
    PlayMusic,
    ReadScreen,
    VolumeUp,
    VolumeDown,
    MuteMic,
    UnmuteMic,
    Unknown,
}

impl VoiceCommandIntent {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::CallContact => "call_contact",
            Self::PlayMusic => "play_music",
            Self::ReadScreen => "read_screen",
            Self::VolumeUp => "volume_up",
            Self::VolumeDown => "volume_down",
            Self::MuteMic => "mute_mic",
            Self::UnmuteMic => "unmute_mic",
            Self::Unknown => "unknown",
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct VoiceCommandMatch {
    pub intent: VoiceCommandIntent,
    pub transcript: String,
    pub contact_name: String,
}

impl VoiceCommandMatch {
    pub fn unknown(transcript: impl Into<String>) -> Self {
        Self {
            intent: VoiceCommandIntent::Unknown,
            transcript: transcript.into(),
            contact_name: String::new(),
        }
    }

    pub fn is_command(&self) -> bool {
        self.intent != VoiceCommandIntent::Unknown
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum VoiceRouteKind {
    Command,
    Action,
    AskFallback,
    AskExit,
    LocalHelp,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct VoiceRouteDecision {
    pub kind: VoiceRouteKind,
    pub original_text: String,
    pub normalized_text: String,
    pub stripped_prefix: String,
    pub command: Option<VoiceCommandMatch>,
    pub route_name: String,
    pub reason: &'static str,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct VoiceActivationResult {
    pub original_text: String,
    pub normalized_text: String,
    pub stripped_prefix: String,
}

const DEFAULT_ASK_INSTRUCTIONS: &str = "You are YoYoPod's friendly Ask helper for a child using a small handheld audio device. Answer in simple language a child can understand. Keep answers to 1-3 short sentences unless the child asks for a story. Be warm, calm, and encouraging. Do not use scary detail. Do not ask for private information. For medical, legal, safety, emergency, or adult topics, give a brief safe answer and say to ask a grown-up. If you are unsure, say so simply. Do not claim to browse the internet or know live facts.";
const DEFAULT_STT_PROMPT: &str = "Transcribe this YoYoPod voice command in English Latin letters. Do not output Arabic, Persian, Korean, or other non-Latin scripts. Preserve family names such as mama, baba, mom, dad, mommy, daddy, and papa.";
const DEFAULT_TTS_INSTRUCTIONS: &str = "Speak warmly and calmly for a child. Use simple words, friendly pacing, and brief answers. Avoid scary emphasis.";

const POLITE_PREFIX_TOKENS: &[&str] = &[
    "please", "hey", "hi", "hello", "yo", "can", "could", "would", "will", "you",
];
const SLOT_FILLER_TOKENS: &[&str] = &["a", "an", "the", "to", "for", "my", "please", "now"];
const NEGATION_TOKENS: &[&str] = &[
    "no", "not", "never", "dont", "don't", "cant", "can't", "cannot", "wont", "won't", "n't",
];
const EXACT_TRIGGER_SUFFIX_TOKENS: &[&str] = &["please", "now"];
const CALL_TRIGGERS: &[&str] = &["call", "phone", "ring"];
const VOLUME_UP_TRIGGERS: &[&str] = &[
    "volume up",
    "turn volume up",
    "turn it up",
    "raise volume",
    "increase volume",
    "louder",
    "make it louder",
    "too quiet",
];
const VOLUME_DOWN_TRIGGERS: &[&str] = &[
    "volume down",
    "turn volume down",
    "turn it down",
    "lower volume",
    "decrease volume",
    "quieter",
    "make it quieter",
    "too loud",
];
const PLAY_MUSIC_TRIGGERS: &[&str] = &[
    "play music",
    "play",
    "play some music",
    "start music",
    "start some music",
    "start playing music",
    "shuffle music",
    "play a song",
    "play songs",
    "put on music",
    "start songs",
    "play kids music",
];
const READ_SCREEN_TRIGGERS: &[&str] = &[
    "read screen",
    "read the screen",
    "read this screen",
    "read this",
    "what is on the screen",
    "tell me what is on the screen",
];
const MUTE_MIC_TRIGGERS: &[&str] = &[
    "mute mic",
    "mute microphone",
    "mute the mic",
    "mute the microphone",
    "turn off the mic",
    "turn off microphone",
    "turn off the microphone",
];
const UNMUTE_MIC_TRIGGERS: &[&str] = &[
    "unmute mic",
    "unmute microphone",
    "unmute the mic",
    "unmute the microphone",
    "turn on the mic",
    "turn on microphone",
    "turn on the microphone",
];
const ASK_EXIT_PHRASES: &[&str] = &[
    "exit ask",
    "go back",
    "stop asking",
    "stop ask",
    "leave ask",
    "close ask",
];
const CALL_TRIGGER_FUZZY_THRESHOLD: f64 = 0.86;
const VOLUME_FUZZY_THRESHOLD: f64 = 0.78;
const PLAY_MUSIC_FUZZY_THRESHOLD: f64 = 0.78;
const SAFE_ROUTE_ACTIONS: &[&str] = &["open_talk", "open_listen", "open_setup", "go_home", "back"];
const CONFIRM_YES_TOKENS: &[&str] = &["yes", "yeah", "yep", "yup", "sure", "ok", "okay"];
const CONFIRM_NO_TOKENS: &[&str] = &[
    "no", "nope", "nah", "cancel", "stop", "dont", "don't", "not", "never",
];
const EXACT_TRIGGERS: &[&str] = &[
    "louder",
    "quieter",
    "play",
    "play a song",
    "play songs",
    "put on music",
    "start songs",
    "play kids music",
    "read screen",
    "read the screen",
    "read this screen",
    "read this",
    "what is on the screen",
    "tell me what is on the screen",
    "mute mic",
    "mute microphone",
    "mute the mic",
    "mute the microphone",
    "turn off the mic",
    "turn off microphone",
    "turn off the microphone",
    "unmute mic",
    "unmute microphone",
    "unmute the mic",
    "unmute the microphone",
    "turn on the mic",
    "turn on microphone",
    "turn on the microphone",
];

pub fn route_voice_transcript(
    transcript: &str,
    settings: &VoiceCommandSettings,
) -> VoiceRouteDecision {
    let activation = normalize_voice_activation(transcript, &settings.activation_prefixes);
    if ASK_EXIT_PHRASES.contains(&activation.normalized_text.as_str()) {
        return VoiceRouteDecision {
            kind: VoiceRouteKind::AskExit,
            original_text: transcript.to_string(),
            normalized_text: activation.normalized_text,
            stripped_prefix: activation.stripped_prefix,
            command: None,
            route_name: String::new(),
            reason: "ask_exit",
        };
    }

    let command = match_voice_command_with_settings(&activation.normalized_text, settings);
    if settings.commands_enabled && command.is_command() {
        return VoiceRouteDecision {
            kind: VoiceRouteKind::Command,
            original_text: transcript.to_string(),
            normalized_text: activation.normalized_text,
            stripped_prefix: activation.stripped_prefix,
            command: Some(command),
            route_name: String::new(),
            reason: "command_match",
        };
    }
    if settings.commands_enabled {
        if let Some(action) =
            match_voice_route_action(&activation.normalized_text, &settings.route_actions)
        {
            return VoiceRouteDecision {
                kind: VoiceRouteKind::Action,
                original_text: transcript.to_string(),
                normalized_text: activation.normalized_text,
                stripped_prefix: activation.stripped_prefix,
                command: None,
                route_name: action.route_name.clone(),
                reason: "action_match",
            };
        }
    }
    if settings.ask_fallback_enabled
        && settings.ai_requests_enabled
        && !activation.normalized_text.trim().is_empty()
    {
        return VoiceRouteDecision {
            kind: VoiceRouteKind::AskFallback,
            original_text: transcript.to_string(),
            normalized_text: activation.normalized_text,
            stripped_prefix: activation.stripped_prefix,
            command: None,
            route_name: String::new(),
            reason: "ask_fallback",
        };
    }
    VoiceRouteDecision {
        kind: VoiceRouteKind::LocalHelp,
        original_text: transcript.to_string(),
        normalized_text: activation.normalized_text,
        stripped_prefix: activation.stripped_prefix,
        command: None,
        route_name: String::new(),
        reason: "no_command_no_fallback",
    }
}

pub fn normalize_voice_activation(transcript: &str, prefixes: &[String]) -> VoiceActivationResult {
    let mut tokens = tokenize(transcript);
    let prefix_tokens = prefixes
        .iter()
        .filter_map(|prefix| {
            let normalized = tokenize(prefix);
            if normalized.is_empty() {
                None
            } else {
                Some((normalized.join(" "), normalized))
            }
        })
        .collect::<Vec<_>>();
    let mut stripped_prefix = String::new();
    while !tokens.is_empty() {
        let mut matched = false;
        for (prefix, prefix_tokens) in &prefix_tokens {
            if starts_with_tokens(&tokens, prefix_tokens) {
                if stripped_prefix.is_empty() {
                    stripped_prefix = prefix.clone();
                }
                tokens = tokens[prefix_tokens.len()..].to_vec();
                matched = true;
                break;
            }
        }
        if !matched {
            break;
        }
    }

    let normalized_text = if stripped_prefix.is_empty() {
        transcript.trim().to_string()
    } else {
        tokens.join(" ")
    };

    VoiceActivationResult {
        original_text: transcript.to_string(),
        normalized_text,
        stripped_prefix,
    }
}

pub fn load_voice_command_dictionary(path: impl AsRef<Path>) -> VoiceCommandDictionary {
    let path = path.as_ref();
    if path.as_os_str().is_empty() || !path.exists() {
        return VoiceCommandDictionary::default();
    }

    let Ok(contents) = fs::read_to_string(path) else {
        return VoiceCommandDictionary::default();
    };
    let Ok(payload) = serde_yaml::from_str::<Value>(&contents) else {
        return VoiceCommandDictionary::default();
    };

    VoiceCommandDictionary {
        disabled_intents: dictionary_disabled_intents(payload.get("intents")),
        command_aliases: dictionary_command_aliases(payload.get("intents")),
        route_actions: dictionary_route_actions(payload.get("actions")),
    }
}

pub fn match_voice_confirmation_response(transcript: &str) -> Option<VoiceConfirmationResponse> {
    let tokens = tokenize(transcript);
    if tokens
        .iter()
        .any(|token| CONFIRM_YES_TOKENS.contains(&token.as_str()))
    {
        return Some(VoiceConfirmationResponse::Yes);
    }
    if tokens
        .iter()
        .any(|token| CONFIRM_NO_TOKENS.contains(&token.as_str()))
    {
        return Some(VoiceConfirmationResponse::No);
    }
    None
}

fn match_voice_command_with_settings(
    transcript: &str,
    settings: &VoiceCommandSettings,
) -> VoiceCommandMatch {
    if !settings.commands_enabled {
        return VoiceCommandMatch::unknown(transcript);
    }

    if let Some(alias_match) = match_command_alias(
        transcript,
        &settings.command_aliases,
        &settings.disabled_intents,
    ) {
        return alias_match;
    }

    let command = match_voice_command(transcript);
    if settings.disabled_intents.contains(&command.intent) {
        VoiceCommandMatch::unknown(transcript)
    } else {
        command
    }
}

fn match_command_alias(
    transcript: &str,
    aliases: &[VoiceCommandAlias],
    disabled_intents: &[VoiceCommandIntent],
) -> Option<VoiceCommandMatch> {
    let expanded = expand_common_stt_aliases(transcript);
    let transcript_tokens = tokenize(&expanded);
    if has_negation(&transcript_tokens) {
        return None;
    }
    let tokens = strip_polite_prefix(&transcript_tokens);
    let normalized = tokens.join(" ");
    if normalized.is_empty() {
        return None;
    }

    for alias in aliases {
        if disabled_intents.contains(&alias.intent) {
            continue;
        }
        if alias.intent == VoiceCommandIntent::CallContact {
            if let Some(contact_name) = match_call_alias(&tokens, &alias.aliases) {
                return Some(VoiceCommandMatch {
                    intent: alias.intent,
                    transcript: transcript.to_string(),
                    contact_name,
                });
            }
            continue;
        }
        if alias.aliases.iter().any(|phrase| {
            phrase == &normalized
                || fixed_phrase_score(&tokens, phrase, fuzzy_threshold_for_intent(alias.intent))
                    .is_some()
        }) {
            return Some(VoiceCommandMatch {
                intent: alias.intent,
                transcript: transcript.to_string(),
                contact_name: String::new(),
            });
        }
    }
    None
}

fn fuzzy_threshold_for_intent(intent: VoiceCommandIntent) -> f64 {
    match intent {
        VoiceCommandIntent::CallContact => CALL_TRIGGER_FUZZY_THRESHOLD,
        VoiceCommandIntent::VolumeUp | VoiceCommandIntent::VolumeDown => VOLUME_FUZZY_THRESHOLD,
        VoiceCommandIntent::PlayMusic => PLAY_MUSIC_FUZZY_THRESHOLD,
        VoiceCommandIntent::ReadScreen => 0.8,
        VoiceCommandIntent::MuteMic | VoiceCommandIntent::UnmuteMic => 0.84,
        VoiceCommandIntent::Unknown => 1.0,
    }
}

fn match_call_alias(tokens: &[String], aliases: &[String]) -> Option<String> {
    for alias in aliases {
        let alias_tokens = tokenize(alias);
        if alias_tokens.is_empty() || !starts_with_tokens(tokens, &alias_tokens) {
            continue;
        }
        let slot_tokens = trim_slot_tokens(&tokens[alias_tokens.len()..]);
        if !slot_tokens.is_empty() && !has_negation(&slot_tokens) {
            return Some(slot_tokens.join(" "));
        }
    }
    None
}

fn match_voice_route_action<'a>(
    transcript: &str,
    actions: &'a [VoiceRouteAction],
) -> Option<&'a VoiceRouteAction> {
    let normalized = normalize_dictionary_phrase(transcript);
    if normalized.is_empty() {
        return None;
    }
    actions
        .iter()
        .find(|action| action.aliases.iter().any(|alias| alias == &normalized))
}

pub fn match_voice_command(transcript: &str) -> VoiceCommandMatch {
    let expanded = expand_common_stt_aliases(transcript);
    let transcript_tokens = tokenize(&expanded);
    if has_negation(&transcript_tokens) {
        return VoiceCommandMatch::unknown(transcript);
    }
    let tokens = strip_polite_prefix(&transcript_tokens);
    if tokens.is_empty() {
        return VoiceCommandMatch::unknown(transcript);
    }

    if let Some(contact_name) = match_call_contact(&tokens) {
        return VoiceCommandMatch {
            intent: VoiceCommandIntent::CallContact,
            transcript: transcript.to_string(),
            contact_name,
        };
    }

    if let Some(intent) = match_fixed_command_intent(&tokens) {
        return VoiceCommandMatch {
            intent,
            transcript: transcript.to_string(),
            contact_name: String::new(),
        };
    }

    VoiceCommandMatch::unknown(transcript)
}

fn match_fixed_command_intent(tokens: &[String]) -> Option<VoiceCommandIntent> {
    let mut best_score = 0.0;
    let mut best_intent = None;

    for (intent, phrases, fuzzy_threshold) in [
        (
            VoiceCommandIntent::VolumeUp,
            VOLUME_UP_TRIGGERS,
            VOLUME_FUZZY_THRESHOLD,
        ),
        (
            VoiceCommandIntent::VolumeDown,
            VOLUME_DOWN_TRIGGERS,
            VOLUME_FUZZY_THRESHOLD,
        ),
        (
            VoiceCommandIntent::PlayMusic,
            PLAY_MUSIC_TRIGGERS,
            PLAY_MUSIC_FUZZY_THRESHOLD,
        ),
        (VoiceCommandIntent::ReadScreen, READ_SCREEN_TRIGGERS, 1.0),
        (VoiceCommandIntent::UnmuteMic, UNMUTE_MIC_TRIGGERS, 1.0),
        (VoiceCommandIntent::MuteMic, MUTE_MIC_TRIGGERS, 1.0),
    ] {
        for phrase in phrases {
            let Some(score) = fixed_phrase_score(tokens, phrase, fuzzy_threshold) else {
                continue;
            };
            if score > best_score {
                best_score = score;
                best_intent = Some(intent);
            }
        }
    }

    best_intent
}

fn match_call_contact(tokens: &[String]) -> Option<String> {
    for (index, token) in tokens.iter().enumerate() {
        if !call_trigger_matches(token) {
            continue;
        }
        if has_negation(&tokens[..index]) {
            continue;
        }
        let slot_tokens = trim_slot_tokens(&tokens[index + 1..]);
        if slot_tokens.is_empty() || has_negation(&slot_tokens) {
            continue;
        }
        return Some(slot_tokens.join(" "));
    }
    None
}

fn call_trigger_matches(token: &str) -> bool {
    CALL_TRIGGERS.contains(&token)
        || CALL_TRIGGERS
            .iter()
            .any(|trigger| text_similarity(token, trigger) >= CALL_TRIGGER_FUZZY_THRESHOLD)
}

fn fixed_phrase_score(tokens: &[String], phrase: &str, fuzzy_threshold: f64) -> Option<f64> {
    let phrase_tokens = tokenize(phrase);
    if phrase_tokens.is_empty() {
        return None;
    }
    if EXACT_TRIGGERS.contains(&phrase) {
        return matches_exact_trigger(tokens, &phrase_tokens).then_some(1.0);
    }
    if tokens.len() < phrase_tokens.len() {
        return None;
    }
    if tokens
        .windows(phrase_tokens.len())
        .enumerate()
        .any(|(index, window)| {
            window == phrase_tokens.as_slice()
                && !has_negation(&tokens[..index])
                && !has_negation(window)
        })
    {
        return Some(1.0);
    }
    if fuzzy_threshold >= 1.0 {
        return None;
    }

    best_window_match(tokens, &phrase_tokens).and_then(|(score, start, end)| {
        if score >= fuzzy_threshold
            && !has_negation(&tokens[..start])
            && !has_negation(&tokens[start..end])
        {
            Some(score)
        } else {
            None
        }
    })
}

fn matches_exact_trigger(tokens: &[String], phrase_tokens: &[String]) -> bool {
    let mut end = tokens.len();
    while end > 0 && EXACT_TRIGGER_SUFFIX_TOKENS.contains(&tokens[end - 1].as_str()) {
        end -= 1;
    }
    tokens[..end] == *phrase_tokens
}

fn best_window_match(tokens: &[String], phrase_tokens: &[String]) -> Option<(f64, usize, usize)> {
    if tokens.is_empty() || phrase_tokens.is_empty() {
        return None;
    }

    let min_window = phrase_tokens.len().saturating_sub(1).max(1);
    if tokens.len() < min_window {
        return None;
    }
    let max_window = if tokens.len() <= phrase_tokens.len() + 2 {
        tokens.len()
    } else {
        (phrase_tokens.len() + 2).min(tokens.len())
    };

    let mut best_score = 0.0;
    let mut best_start = 0;
    let mut best_end = 0;
    for window_size in min_window..=max_window {
        for start in 0..=tokens.len() - window_size {
            let end = start + window_size;
            let window = &tokens[start..end];
            let score = if window == phrase_tokens {
                1.0
            } else {
                phrase_similarity(window, phrase_tokens)
            };
            if score > best_score {
                best_score = score;
                best_start = start;
                best_end = end;
            }
        }
    }
    Some((best_score, best_start, best_end))
}

fn phrase_similarity(candidate_tokens: &[String], phrase_tokens: &[String]) -> f64 {
    let candidate = candidate_tokens
        .iter()
        .map(String::as_str)
        .collect::<Vec<_>>()
        .join(" ");
    let phrase = phrase_tokens
        .iter()
        .map(String::as_str)
        .collect::<Vec<_>>()
        .join(" ");
    text_similarity(&candidate, &phrase)
        .max(token_overlap_similarity(candidate_tokens, phrase_tokens))
}

fn text_similarity(candidate: &str, phrase: &str) -> f64 {
    let candidate_chars = candidate.chars().collect::<Vec<_>>();
    let phrase_chars = phrase.chars().collect::<Vec<_>>();
    if candidate_chars.is_empty() || phrase_chars.is_empty() {
        return 0.0;
    }

    let matching_len = sequence_matching_len(&candidate_chars, &phrase_chars);
    (2.0 * matching_len as f64) / (candidate_chars.len() + phrase_chars.len()) as f64
}

fn sequence_matching_len(left: &[char], right: &[char]) -> usize {
    let (left_start, right_start, size) = longest_common_substring(left, right);
    if size == 0 {
        return 0;
    }

    size + sequence_matching_len(&left[..left_start], &right[..right_start])
        + sequence_matching_len(&left[left_start + size..], &right[right_start + size..])
}

fn longest_common_substring(left: &[char], right: &[char]) -> (usize, usize, usize) {
    let mut best_left = 0;
    let mut best_right = 0;
    let mut best_size = 0;

    for left_start in 0..left.len() {
        for right_start in 0..right.len() {
            let mut size = 0;
            while left_start + size < left.len()
                && right_start + size < right.len()
                && left[left_start + size] == right[right_start + size]
            {
                size += 1;
            }
            if size > best_size {
                best_left = left_start;
                best_right = right_start;
                best_size = size;
            }
        }
    }

    (best_left, best_right, best_size)
}

fn token_overlap_similarity(candidate_tokens: &[String], phrase_tokens: &[String]) -> f64 {
    if candidate_tokens.is_empty() || phrase_tokens.is_empty() {
        return 0.0;
    }
    let candidate = candidate_tokens
        .iter()
        .map(String::as_str)
        .collect::<HashSet<_>>();
    let phrase = phrase_tokens
        .iter()
        .map(String::as_str)
        .collect::<HashSet<_>>();
    (2.0 * candidate.intersection(&phrase).count() as f64) / (candidate.len() + phrase.len()) as f64
}

fn expand_common_stt_aliases(transcript: &str) -> String {
    let mut expanded = String::new();
    let mut token = String::new();
    let mut token_kind = None;

    for character in transcript.chars() {
        let Some(kind) = stt_token_kind(character) else {
            flush_stt_token(&mut expanded, &mut token, token_kind);
            token_kind = None;
            expanded.push(character);
            continue;
        };

        if token_kind.is_some_and(|current| current != kind) {
            flush_stt_token(&mut expanded, &mut token, token_kind);
        }
        token_kind = Some(kind);
        token.push(normalize_stt_token_character(kind, character));
    }
    flush_stt_token(&mut expanded, &mut token, token_kind);

    expanded
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum SttTokenKind {
    Latin,
    ArabicScript,
    Hangul,
    Cjk,
}

fn stt_token_kind(character: char) -> Option<SttTokenKind> {
    if character.is_ascii_alphanumeric() || character == '\'' {
        Some(SttTokenKind::Latin)
    } else if ('\u{0600}'..='\u{06ff}').contains(&character) {
        Some(SttTokenKind::ArabicScript)
    } else if ('\u{ac00}'..='\u{d7af}').contains(&character) {
        Some(SttTokenKind::Hangul)
    } else if ('\u{4e00}'..='\u{9fff}').contains(&character) {
        Some(SttTokenKind::Cjk)
    } else {
        None
    }
}

fn normalize_stt_token_character(kind: SttTokenKind, character: char) -> char {
    match kind {
        SttTokenKind::Latin => character.to_ascii_lowercase(),
        SttTokenKind::ArabicScript => match character {
            '\u{064a}' => '\u{06cc}',
            '\u{0643}' => '\u{06a9}',
            '\u{0622}' => '\u{0627}',
            _ => character,
        },
        SttTokenKind::Hangul | SttTokenKind::Cjk => character,
    }
}

fn flush_stt_token(expanded: &mut String, token: &mut String, token_kind: Option<SttTokenKind>) {
    let Some(kind) = token_kind else {
        token.clear();
        return;
    };
    if token.is_empty() {
        return;
    }

    if let Some(alias) = stt_token_alias(kind, token) {
        push_stt_alias(expanded, alias);
    } else {
        expanded.push_str(token);
    }
    token.clear();
}

fn push_stt_alias(expanded: &mut String, alias: &str) {
    if expanded
        .chars()
        .last()
        .is_some_and(|last| !last.is_whitespace())
    {
        expanded.push(' ');
    }
    expanded.push_str(alias);
    expanded.push(' ');
}

fn stt_token_alias(kind: SttTokenKind, token: &str) -> Option<&'static str> {
    match kind {
        SttTokenKind::Latin => match token {
            "kual" => Some("call"),
            _ => None,
        },
        SttTokenKind::ArabicScript => match token {
            "\u{06a9}\u{0648}" | "\u{06a9}\u{0648}\u{0644}" => Some("call"),
            "\u{0645}\u{0627}\u{0645}\u{0627}" => Some("mama"),
            "\u{0648}\u{0648}\u{0644}\u{06cc}\u{0648}\u{0645}"
            | "\u{0648}\u{0644}\u{06cc}\u{0648}\u{0645}"
            | "\u{0648}\u{0627}\u{0644}\u{06cc}\u{0648}\u{0645}" => Some("volume"),
            "\u{0627}\u{067e}" => Some("up"),
            "\u{062f}\u{0627}\u{0648}\u{0646}" | "\u{062f}\u{0627}\u{0646}" => Some("down"),
            "\u{067e}\u{0644}\u{06cc}" => Some("play"),
            "\u{0645}\u{0648}\u{0632}\u{06cc}\u{06a9}"
            | "\u{0645}\u{06cc}\u{0648}\u{0632}\u{06cc}\u{06a9}" => Some("music"),
            _ => None,
        },
        SttTokenKind::Hangul => match token {
            "\u{ace0}" | "\u{cf5c}" => Some("call"),
            "\u{b9c8}\u{b9c8}" => Some("mama"),
            _ => None,
        },
        SttTokenKind::Cjk => match token {
            "\u{63a8}" => Some("play"),
            "\u{97f3}\u{4e50}" => Some("music"),
            _ => None,
        },
    }
}

fn tokenize(text: &str) -> Vec<String> {
    let mut raw = Vec::new();
    let mut current = String::new();
    for character in text.chars() {
        if character.is_ascii_alphanumeric() || character == '\'' {
            current.push(character.to_ascii_lowercase());
        } else if !current.is_empty() {
            raw.push(std::mem::take(&mut current));
        }
    }
    if !current.is_empty() {
        raw.push(current);
    }

    let mut normalized = Vec::new();
    let mut index = 0;
    while index < raw.len() {
        if index + 1 < raw.len() && raw[index] == "yo" && raw[index + 1] == "yo" {
            normalized.push("yoyo".to_string());
            index += 2;
        } else {
            normalized.push(raw[index].clone());
            index += 1;
        }
    }
    normalized
}

fn dictionary_disabled_intents(value: Option<&Value>) -> Vec<VoiceCommandIntent> {
    let Some(Value::Object(intents)) = value else {
        return Vec::new();
    };
    intents
        .iter()
        .filter_map(|(intent_name, payload)| {
            if payload
                .get("enabled")
                .and_then(Value::as_bool)
                .is_some_and(|enabled| !enabled)
            {
                voice_command_intent_from_name(intent_name)
            } else {
                None
            }
        })
        .collect()
}

fn dictionary_command_aliases(value: Option<&Value>) -> Vec<VoiceCommandAlias> {
    let Some(Value::Object(intents)) = value else {
        return Vec::new();
    };
    intents
        .iter()
        .filter_map(|(intent_name, payload)| {
            if payload
                .get("enabled")
                .and_then(Value::as_bool)
                .is_some_and(|enabled| !enabled)
            {
                return None;
            }
            let intent = voice_command_intent_from_name(intent_name)?;
            let aliases = normalized_phrase_list(payload.get("aliases"));
            if aliases.is_empty() {
                None
            } else {
                Some(VoiceCommandAlias { intent, aliases })
            }
        })
        .collect()
}

fn dictionary_route_actions(value: Option<&Value>) -> Vec<VoiceRouteAction> {
    let Some(Value::Object(actions)) = value else {
        return Vec::new();
    };
    actions
        .values()
        .filter_map(|payload| {
            let route_name = payload.get("route").and_then(Value::as_str)?.trim();
            if !SAFE_ROUTE_ACTIONS.contains(&route_name) {
                return None;
            }
            let aliases = normalized_phrase_list(payload.get("aliases"));
            if aliases.is_empty() {
                None
            } else {
                Some(VoiceRouteAction {
                    route_name: route_name.to_string(),
                    aliases,
                })
            }
        })
        .collect()
}

fn normalized_phrase_list(value: Option<&Value>) -> Vec<String> {
    let raw = match value {
        Some(Value::String(phrase)) => vec![phrase.as_str()],
        Some(Value::Array(phrases)) => phrases.iter().filter_map(Value::as_str).collect(),
        _ => Vec::new(),
    };
    let mut normalized = Vec::new();
    for phrase in raw {
        let phrase = normalize_dictionary_phrase(phrase);
        if !phrase.is_empty() && !normalized.contains(&phrase) {
            normalized.push(phrase);
        }
    }
    normalized
}

fn normalize_dictionary_phrase(value: &str) -> String {
    tokenize(value).join(" ")
}

fn voice_command_intent_from_name(value: &str) -> Option<VoiceCommandIntent> {
    match value.trim() {
        "call_contact" => Some(VoiceCommandIntent::CallContact),
        "play_music" => Some(VoiceCommandIntent::PlayMusic),
        "read_screen" => Some(VoiceCommandIntent::ReadScreen),
        "volume_up" => Some(VoiceCommandIntent::VolumeUp),
        "volume_down" => Some(VoiceCommandIntent::VolumeDown),
        "mute_mic" => Some(VoiceCommandIntent::MuteMic),
        "unmute_mic" => Some(VoiceCommandIntent::UnmuteMic),
        _ => None,
    }
}

fn strip_polite_prefix(tokens: &[String]) -> Vec<String> {
    let mut start = 0;
    while start < tokens.len() && POLITE_PREFIX_TOKENS.contains(&tokens[start].as_str()) {
        start += 1;
    }
    tokens[start..].to_vec()
}

fn trim_slot_tokens(tokens: &[String]) -> Vec<String> {
    let mut start = 0;
    let mut end = tokens.len();
    while start < end && SLOT_FILLER_TOKENS.contains(&tokens[start].as_str()) {
        start += 1;
    }
    while end > start && SLOT_FILLER_TOKENS.contains(&tokens[end - 1].as_str()) {
        end -= 1;
    }
    tokens[start..end].to_vec()
}

fn has_negation(tokens: &[String]) -> bool {
    tokens
        .iter()
        .any(|token| NEGATION_TOKENS.contains(&token.as_str()))
        || contains_token_sequence(tokens, &["can", "t"])
        || contains_token_sequence(tokens, &["do", "nt"])
        || contains_token_sequence(tokens, &["do", "n", "t"])
        || contains_token_sequence(tokens, &["don", "t"])
        || contains_token_sequence(tokens, &["won", "t"])
}

fn contains_token_sequence(tokens: &[String], sequence: &[&str]) -> bool {
    tokens.len() >= sequence.len()
        && tokens.windows(sequence.len()).any(|window| {
            window
                .iter()
                .map(String::as_str)
                .eq(sequence.iter().copied())
        })
}

fn starts_with_tokens(tokens: &[String], prefix: &[String]) -> bool {
    tokens.len() >= prefix.len() && tokens[..prefix.len()] == *prefix
}
