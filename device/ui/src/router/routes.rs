pub use yoyopod_protocol::ui::UiScreen;
use yoyopod_protocol::ui::{
    InputAction, IntentKind, RuntimeSnapshotDomain, ScreenCapabilities, UiIntent,
};

use crate::scene::FocusPolicy;
use crate::DirtyRegion;

use super::route::{
    AdvanceTarget, BackPolicy, DynamicActionKind, IntentTemplate, ListKind, NavigationPolicy,
    PassthroughPolicy, Persistence, Route, SelectionTarget, SnapshotCondition,
};

const STATUS_BAR_REGION: DirtyRegion = DirtyRegion {
    x: 0,
    y: 0,
    w: 240,
    h: 32,
};

pub const fn status_bar_region() -> DirtyRegion {
    STATUS_BAR_REGION
}

pub const ROUTES: [Route; UiScreen::ALL.len()] = [
    route(UiScreen::Hub),
    route(UiScreen::Listen),
    route(UiScreen::Playlists),
    route(UiScreen::PlaylistTracks),
    route(UiScreen::RecentTracks),
    route(UiScreen::NowPlaying),
    route(UiScreen::Ask),
    route(UiScreen::Talk),
    route(UiScreen::Contacts),
    route(UiScreen::CallHistory),
    route(UiScreen::TalkContact),
    route(UiScreen::Replay),
    route(UiScreen::VoiceNote),
    route(UiScreen::IncomingCall),
    route(UiScreen::OutgoingCall),
    route(UiScreen::InCall),
    route(UiScreen::Setup),
    route(UiScreen::SetupVolume),
    route(UiScreen::SetupCompanion),
    route(UiScreen::SetupContacts),
    route(UiScreen::SetupTheme),
    route(UiScreen::SetupAbout),
    route(UiScreen::SetupWifi),
    route(UiScreen::Loading),
    route(UiScreen::Error),
];

pub fn route_for(screen: UiScreen) -> Route {
    ROUTES
        .iter()
        .copied()
        .find(|route| route.screen == screen)
        .unwrap_or_else(|| panic!("missing route for {}", screen.as_str()))
}

pub fn validate_routes() -> anyhow::Result<()> {
    let mut seen = Vec::with_capacity(ROUTES.len());
    for route in ROUTES {
        if seen.contains(&route.screen) {
            anyhow::bail!("duplicate UI route for {}", route.screen.as_str());
        }
        seen.push(route.screen);
    }

    for screen in UiScreen::ALL {
        if !seen.contains(&screen) {
            anyhow::bail!("missing UI route for {}", screen.as_str());
        }
    }

    Ok(())
}

const fn route(screen: UiScreen) -> Route {
    Route {
        screen,
        title: screen.as_str(),
        focus_policy: focus_policy(screen),
        nav_policy: navigation_policy(screen),
        persistence: persistence(screen),
        select: select_targets(screen),
        advance: advance_target(screen),
        passthrough: passthrough_policies(screen),
        back: back_policies(screen),
        on_enter: None,
        on_exit: None,
    }
}

pub const fn dirty_region_for(
    screen: UiScreen,
    domain: RuntimeSnapshotDomain,
) -> Option<DirtyRegion> {
    match (screen, domain) {
        (UiScreen::SetupAbout, RuntimeSnapshotDomain::Power | RuntimeSnapshotDomain::Network) => {
            None
        }
        (_, RuntimeSnapshotDomain::Power | RuntimeSnapshotDomain::Network) => {
            Some(STATUS_BAR_REGION)
        }
        _ => None,
    }
}

pub fn screen_capabilities() -> Vec<ScreenCapabilities> {
    UiScreen::ALL
        .iter()
        .copied()
        .map(|screen| {
            let entry = route_for(screen);
            let mut supported_intents = Vec::new();
            for target in entry.select {
                add_selection_intent(*target, &mut supported_intents);
            }
            if let AdvanceTarget::EmitIntent(intent) = entry.advance {
                add_intent_kind(template_intent_kind(intent), &mut supported_intents);
            }
            for passthrough in entry.passthrough {
                add_intent_kind(
                    template_intent_kind(passthrough.intent),
                    &mut supported_intents,
                );
            }
            for back in entry.back {
                add_intent_kind(template_intent_kind(back.intent), &mut supported_intents);
            }
            ScreenCapabilities {
                screen,
                supported_intents,
                passthrough: entry.passthrough.first().map(|policy| policy.trigger),
            }
        })
        .collect()
}

fn add_selection_intent(target: SelectionTarget, supported_intents: &mut Vec<IntentKind>) {
    match target {
        SelectionTarget::EmitIntent(template)
        | SelectionTarget::PushWithIntent {
            intent: template, ..
        } => add_intent_kind(template_intent_kind(template), supported_intents),
        SelectionTarget::DynamicListItem { kind } => {
            if let Some(intent) = dynamic_list_intent_kind(kind) {
                add_intent_kind(intent, supported_intents);
            }
        }
        SelectionTarget::DynamicAction { kind } => {
            for intent in dynamic_action_intent_kinds(kind) {
                add_intent_kind((*intent).into(), supported_intents);
            }
        }
        SelectionTarget::PushScreen(_)
        | SelectionTarget::AdvanceFocus
        | SelectionTarget::PopScreen
        | SelectionTarget::Noop => {}
    }
}

fn add_intent_kind(intent: IntentKind, supported_intents: &mut Vec<IntentKind>) {
    if !supported_intents.contains(&intent) {
        supported_intents.push(intent);
    }
}

fn template_intent_kind(template: IntentTemplate) -> IntentKind {
    let (domain, action) = match template {
        IntentTemplate::MusicShuffleAll => ("music", "shuffle_all"),
        IntentTemplate::MusicPreviousTrack => ("music", "previous_track"),
        IntentTemplate::MusicPlayPause => ("music", "play_pause"),
        IntentTemplate::MusicNextTrack => ("music", "next_track"),
        IntentTemplate::VoiceAskStart => ("voice", "ask_start"),
        IntentTemplate::VoiceAskStop => ("voice", "ask_stop"),
        IntentTemplate::VoiceAskCancel => ("voice", "ask_cancel"),
        IntentTemplate::VoiceCaptureStartAndSendRecipient => ("voice", "capture_start_and_send"),
        IntentTemplate::VoiceCaptureStop => ("voice", "capture_stop"),
        IntentTemplate::VoiceCaptureCancel => ("voice", "capture_cancel"),
        IntentTemplate::VoiceDiscard => ("voice", "discard"),
        IntentTemplate::CallAnswer => ("call", "answer"),
        IntentTemplate::CallReject => ("call", "reject"),
        IntentTemplate::CallHangup => ("call", "hangup"),
        IntentTemplate::CallToggleMute => ("call", "toggle_mute"),
        IntentTemplate::SettingsVolumeStep => ("settings", "volume_step"),
        IntentTemplate::SettingsSpeakNamesToggle => ("settings", "speak_names_toggle"),
        IntentTemplate::SettingsWifiSetupStart => ("settings", "wifi_setup_start"),
        IntentTemplate::SettingsWifiSetupStop => ("settings", "wifi_setup_stop"),
    };
    IntentKind {
        domain: domain.to_string(),
        action: action.to_string(),
    }
}

fn dynamic_list_intent_kind(kind: ListKind) -> Option<IntentKind> {
    match kind {
        ListKind::Playlists => None,
        ListKind::PlaylistTracks => Some(IntentKind {
            domain: "music".to_string(),
            action: "play_playlist_track".to_string(),
        }),
        ListKind::RecentTracks => Some(IntentKind {
            domain: "music".to_string(),
            action: "play_recent_track".to_string(),
        }),
        ListKind::Contacts | ListKind::CallHistory => Some(IntentKind {
            domain: "call".to_string(),
            action: "start".to_string(),
        }),
    }
}

fn dynamic_action_intent_kinds(kind: DynamicActionKind) -> &'static [IntentKindLiteral] {
    const TALK_CONTACT_INTENTS: &[IntentKindLiteral] = &[
        IntentKindLiteral::new("call", "start"),
        IntentKindLiteral::new("voice", "capture_start"),
        IntentKindLiteral::new("voice", "play_latest"),
        IntentKindLiteral::new("voice", "mark_seen"),
    ];
    const VOICE_NOTE_INTENTS: &[IntentKindLiteral] = &[
        IntentKindLiteral::new("voice", "capture_start"),
        IntentKindLiteral::new("voice", "capture_stop"),
        IntentKindLiteral::new("voice", "capture_cancel"),
        IntentKindLiteral::new("voice", "send"),
        IntentKindLiteral::new("voice", "play"),
        IntentKindLiteral::new("voice", "discard"),
    ];
    const REPLAY_INTENTS: &[IntentKindLiteral] = &[
        IntentKindLiteral::new("voice", "play_latest"),
        IntentKindLiteral::new("voice", "pause_playback"),
        IntentKindLiteral::new("voice", "resume_playback"),
        IntentKindLiteral::new("voice", "stop_playback"),
        IntentKindLiteral::new("voice", "delete"),
    ];
    const ASK_INTENTS: &[IntentKindLiteral] = &[
        IntentKindLiteral::new("voice", "ask_start"),
        IntentKindLiteral::new("voice", "ask_stop"),
        IntentKindLiteral::new("voice", "ask_cancel"),
    ];
    const SETUP_COMPANION_INTENTS: &[IntentKindLiteral] =
        &[IntentKindLiteral::new("settings", "companion_set")];
    const SETUP_THEME_INTENTS: &[IntentKindLiteral] =
        &[IntentKindLiteral::new("settings", "theme_set")];

    match kind {
        DynamicActionKind::Ask => ASK_INTENTS,
        DynamicActionKind::TalkContact => TALK_CONTACT_INTENTS,
        DynamicActionKind::Replay => REPLAY_INTENTS,
        DynamicActionKind::VoiceNote => VOICE_NOTE_INTENTS,
        DynamicActionKind::SetupCompanion => SETUP_COMPANION_INTENTS,
        DynamicActionKind::SetupTheme => SETUP_THEME_INTENTS,
    }
}

#[derive(Debug, Clone, Copy)]
struct IntentKindLiteral {
    domain: &'static str,
    action: &'static str,
}

impl IntentKindLiteral {
    const fn new(domain: &'static str, action: &'static str) -> Self {
        Self { domain, action }
    }
}

impl From<IntentKindLiteral> for IntentKind {
    fn from(value: IntentKindLiteral) -> Self {
        Self {
            domain: value.domain.to_string(),
            action: value.action.to_string(),
        }
    }
}

const HUB_SELECT: &[SelectionTarget] = &[
    SelectionTarget::PushScreen(UiScreen::Listen),
    SelectionTarget::PushScreen(UiScreen::Talk),
    SelectionTarget::PushScreen(UiScreen::Ask),
    SelectionTarget::PushScreen(UiScreen::Setup),
];
const LISTEN_SELECT: &[SelectionTarget] = &[
    SelectionTarget::PushScreen(UiScreen::Playlists),
    SelectionTarget::PushScreen(UiScreen::RecentTracks),
    SelectionTarget::PushWithIntent {
        screen: UiScreen::NowPlaying,
        intent: IntentTemplate::MusicShuffleAll,
    },
];
const PLAYLISTS_SELECT: &[SelectionTarget] = &[SelectionTarget::DynamicListItem {
    kind: ListKind::Playlists,
}];
const PLAYLIST_TRACKS_SELECT: &[SelectionTarget] = &[SelectionTarget::DynamicListItem {
    kind: ListKind::PlaylistTracks,
}];
const RECENT_TRACKS_SELECT: &[SelectionTarget] = &[SelectionTarget::DynamicListItem {
    kind: ListKind::RecentTracks,
}];
const CONTACTS_SELECT: &[SelectionTarget] = &[SelectionTarget::DynamicListItem {
    kind: ListKind::Contacts,
}];
const CALL_HISTORY_SELECT: &[SelectionTarget] = &[SelectionTarget::DynamicListItem {
    kind: ListKind::CallHistory,
}];
const NOW_PLAYING_SELECT: &[SelectionTarget] = &[
    SelectionTarget::EmitIntent(IntentTemplate::MusicPreviousTrack),
    SelectionTarget::EmitIntent(IntentTemplate::MusicPlayPause),
    SelectionTarget::EmitIntent(IntentTemplate::MusicNextTrack),
];
const ASK_SELECT: &[SelectionTarget] = &[SelectionTarget::DynamicAction {
    kind: DynamicActionKind::Ask,
}];
const TALK_CONTACT_SELECT: &[SelectionTarget] = &[SelectionTarget::DynamicAction {
    kind: DynamicActionKind::TalkContact,
}];
const REPLAY_SELECT: &[SelectionTarget] = &[SelectionTarget::DynamicAction {
    kind: DynamicActionKind::Replay,
}];
const VOICE_NOTE_SELECT: &[SelectionTarget] = &[SelectionTarget::DynamicAction {
    kind: DynamicActionKind::VoiceNote,
}];
const INCOMING_SELECT: &[SelectionTarget] = &[
    SelectionTarget::EmitIntent(IntentTemplate::CallAnswer),
    SelectionTarget::EmitIntent(IntentTemplate::CallReject),
];
const OUTGOING_SELECT: &[SelectionTarget] =
    &[SelectionTarget::EmitIntent(IntentTemplate::CallHangup)];
const IN_CALL_SELECT: &[SelectionTarget] = &[
    SelectionTarget::EmitIntent(IntentTemplate::CallToggleMute),
    SelectionTarget::EmitIntent(IntentTemplate::CallHangup),
];
const SETUP_SELECT: &[SelectionTarget] = &[
    SelectionTarget::PushScreen(UiScreen::SetupVolume),
    SelectionTarget::PushScreen(UiScreen::SetupCompanion),
    SelectionTarget::PushScreen(UiScreen::SetupContacts),
    SelectionTarget::PushScreen(UiScreen::SetupTheme),
    SelectionTarget::EmitIntent(IntentTemplate::SettingsSpeakNamesToggle),
    SelectionTarget::PushWithIntent {
        screen: UiScreen::SetupWifi,
        intent: IntentTemplate::SettingsWifiSetupStart,
    },
    SelectionTarget::PushScreen(UiScreen::SetupAbout),
];
const SETUP_VOLUME_SELECT: &[SelectionTarget] = &[SelectionTarget::PopScreen];
const SETUP_COMPANION_SELECT: &[SelectionTarget] = &[SelectionTarget::DynamicAction {
    kind: DynamicActionKind::SetupCompanion,
}];
const SETUP_THEME_SELECT: &[SelectionTarget] = &[SelectionTarget::DynamicAction {
    kind: DynamicActionKind::SetupTheme,
}];
const NO_SELECT: &[SelectionTarget] = &[SelectionTarget::Noop];

const ASK_PASSTHROUGH: &[PassthroughPolicy] = &[
    PassthroughPolicy {
        trigger: InputAction::PttPress,
        when: SnapshotCondition::Always,
        intent: IntentTemplate::VoiceAskStart,
        captures_button: true,
    },
    PassthroughPolicy {
        trigger: InputAction::PttRelease,
        when: SnapshotCondition::Always,
        intent: IntentTemplate::VoiceAskStop,
        captures_button: true,
    },
];
const TALK_CONTACT_PASSTHROUGH: &[PassthroughPolicy] = &[
    PassthroughPolicy {
        trigger: InputAction::PttPress,
        when: SnapshotCondition::TalkContactRecordAvailable,
        intent: IntentTemplate::VoiceCaptureStartAndSendRecipient,
        captures_button: true,
    },
    PassthroughPolicy {
        trigger: InputAction::PttRelease,
        when: SnapshotCondition::TalkContactRecordHeldOrPending,
        intent: IntentTemplate::VoiceCaptureStop,
        captures_button: true,
    },
];
const NO_PASSTHROUGH: &[PassthroughPolicy] = &[];

const VOICE_NOTE_BACK: &[BackPolicy] = &[
    BackPolicy {
        when: SnapshotCondition::VoiceRecording,
        intent: IntentTemplate::VoiceCaptureCancel,
        pop_screen: true,
    },
    BackPolicy {
        when: SnapshotCondition::VoiceReviewOrFailedOrSent,
        intent: IntentTemplate::VoiceDiscard,
        pop_screen: true,
    },
];
const SETUP_WIFI_BACK: &[BackPolicy] = &[BackPolicy {
    when: SnapshotCondition::Always,
    intent: IntentTemplate::SettingsWifiSetupStop,
    pop_screen: true,
}];
const NO_BACK: &[BackPolicy] = &[];

const fn select_targets(screen: UiScreen) -> &'static [SelectionTarget] {
    match screen {
        UiScreen::Hub => HUB_SELECT,
        UiScreen::Listen => LISTEN_SELECT,
        UiScreen::Talk => CONTACTS_SELECT,
        UiScreen::Playlists => PLAYLISTS_SELECT,
        UiScreen::PlaylistTracks => PLAYLIST_TRACKS_SELECT,
        UiScreen::RecentTracks => RECENT_TRACKS_SELECT,
        UiScreen::NowPlaying => NOW_PLAYING_SELECT,
        UiScreen::Ask => ASK_SELECT,
        UiScreen::VoiceNote => VOICE_NOTE_SELECT,
        UiScreen::Contacts => CONTACTS_SELECT,
        UiScreen::TalkContact => TALK_CONTACT_SELECT,
        UiScreen::Replay => REPLAY_SELECT,
        UiScreen::CallHistory => CALL_HISTORY_SELECT,
        UiScreen::IncomingCall => INCOMING_SELECT,
        UiScreen::OutgoingCall => OUTGOING_SELECT,
        UiScreen::InCall => IN_CALL_SELECT,
        UiScreen::Setup => SETUP_SELECT,
        UiScreen::SetupVolume => SETUP_VOLUME_SELECT,
        UiScreen::SetupCompanion => SETUP_COMPANION_SELECT,
        UiScreen::SetupContacts | UiScreen::SetupAbout | UiScreen::SetupWifi => NO_SELECT,
        UiScreen::SetupTheme => SETUP_THEME_SELECT,
        UiScreen::Loading | UiScreen::Error => NO_SELECT,
    }
}

const fn passthrough_policies(screen: UiScreen) -> &'static [PassthroughPolicy] {
    match screen {
        UiScreen::Ask => ASK_PASSTHROUGH,
        UiScreen::TalkContact => TALK_CONTACT_PASSTHROUGH,
        _ => NO_PASSTHROUGH,
    }
}

const fn back_policies(screen: UiScreen) -> &'static [BackPolicy] {
    match screen {
        UiScreen::VoiceNote => VOICE_NOTE_BACK,
        UiScreen::SetupWifi => SETUP_WIFI_BACK,
        _ => NO_BACK,
    }
}

pub fn static_intent_template(template: IntentTemplate) -> Option<UiIntent> {
    match template {
        IntentTemplate::MusicShuffleAll => Some(UiIntent::Music(
            yoyopod_protocol::ui::MusicIntent::ShuffleAll,
        )),
        IntentTemplate::MusicPreviousTrack => Some(UiIntent::Music(
            yoyopod_protocol::ui::MusicIntent::PreviousTrack,
        )),
        IntentTemplate::MusicPlayPause => Some(UiIntent::Music(
            yoyopod_protocol::ui::MusicIntent::PlayPause,
        )),
        IntentTemplate::MusicNextTrack => Some(UiIntent::Music(
            yoyopod_protocol::ui::MusicIntent::NextTrack,
        )),
        IntentTemplate::VoiceAskStart => {
            Some(UiIntent::Voice(yoyopod_protocol::ui::VoiceIntent::AskStart))
        }
        IntentTemplate::VoiceAskStop => {
            Some(UiIntent::Voice(yoyopod_protocol::ui::VoiceIntent::AskStop))
        }
        IntentTemplate::VoiceAskCancel => Some(UiIntent::Voice(
            yoyopod_protocol::ui::VoiceIntent::AskCancel,
        )),
        IntentTemplate::VoiceCaptureStartAndSendRecipient => None,
        IntentTemplate::VoiceCaptureStop => Some(UiIntent::Voice(
            yoyopod_protocol::ui::VoiceIntent::CaptureStop,
        )),
        IntentTemplate::VoiceCaptureCancel => Some(UiIntent::Voice(
            yoyopod_protocol::ui::VoiceIntent::CaptureCancel,
        )),
        IntentTemplate::VoiceDiscard => {
            Some(UiIntent::Voice(yoyopod_protocol::ui::VoiceIntent::Discard))
        }
        IntentTemplate::CallAnswer => {
            Some(UiIntent::Call(yoyopod_protocol::ui::CallIntent::Answer))
        }
        IntentTemplate::CallReject => {
            Some(UiIntent::Call(yoyopod_protocol::ui::CallIntent::Reject))
        }
        IntentTemplate::CallHangup => {
            Some(UiIntent::Call(yoyopod_protocol::ui::CallIntent::Hangup))
        }
        IntentTemplate::CallToggleMute => {
            Some(UiIntent::Call(yoyopod_protocol::ui::CallIntent::ToggleMute))
        }
        IntentTemplate::SettingsVolumeStep => Some(UiIntent::Settings(
            yoyopod_protocol::ui::SettingsIntent::VolumeStep,
        )),
        IntentTemplate::SettingsSpeakNamesToggle => Some(UiIntent::Settings(
            yoyopod_protocol::ui::SettingsIntent::SpeakNamesToggle,
        )),
        IntentTemplate::SettingsWifiSetupStart => Some(UiIntent::Settings(
            yoyopod_protocol::ui::SettingsIntent::WifiSetupStart,
        )),
        IntentTemplate::SettingsWifiSetupStop => Some(UiIntent::Settings(
            yoyopod_protocol::ui::SettingsIntent::WifiSetupStop,
        )),
    }
}

const fn focus_policy(screen: UiScreen) -> FocusPolicy {
    match screen {
        UiScreen::Hub
        | UiScreen::Listen
        | UiScreen::Talk
        | UiScreen::TalkContact
        | UiScreen::Replay
        | UiScreen::VoiceNote
        | UiScreen::IncomingCall
        | UiScreen::InCall
        | UiScreen::Setup
        | UiScreen::SetupVolume
        | UiScreen::SetupCompanion
        | UiScreen::SetupContacts
        | UiScreen::SetupTheme
        | UiScreen::SetupAbout => FocusPolicy::Wrap,
        UiScreen::Contacts | UiScreen::CallHistory => FocusPolicy::Clamp,
        UiScreen::Playlists
        | UiScreen::PlaylistTracks
        | UiScreen::RecentTracks
        | UiScreen::NowPlaying => FocusPolicy::Wrap,
        UiScreen::SetupWifi
        | UiScreen::Ask
        | UiScreen::OutgoingCall
        | UiScreen::Loading
        | UiScreen::Error => FocusPolicy::None,
    }
}

const fn advance_target(screen: UiScreen) -> AdvanceTarget {
    match screen {
        UiScreen::SetupVolume => AdvanceTarget::EmitIntent(IntentTemplate::SettingsVolumeStep),
        _ => AdvanceTarget::Focus,
    }
}

const fn navigation_policy(screen: UiScreen) -> NavigationPolicy {
    match screen {
        UiScreen::Hub => NavigationPolicy::Root,
        UiScreen::Loading | UiScreen::Error => NavigationPolicy::Overlay,
        UiScreen::IncomingCall | UiScreen::OutgoingCall | UiScreen::InCall => {
            NavigationPolicy::Call
        }
        _ => NavigationPolicy::Stack,
    }
}

const fn persistence(screen: UiScreen) -> Persistence {
    match screen {
        UiScreen::NowPlaying => Persistence::KeepAlive,
        UiScreen::Loading | UiScreen::Error => Persistence::Singleton,
        _ => Persistence::Ephemeral,
    }
}
