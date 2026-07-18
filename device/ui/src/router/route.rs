use yoyopod_protocol::ui::InputAction;
pub use yoyopod_protocol::ui::UiScreen;

use crate::animation::TimelineRef;
use crate::scene::FocusPolicy;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum NavigationPolicy {
    Root,
    Stack,
    Overlay,
    Call,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Persistence {
    Ephemeral,
    KeepAlive,
    Singleton,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum IntentTemplate {
    MusicShuffleAll,
    MusicPreviousTrack,
    MusicPlayPause,
    MusicNextTrack,
    VoiceAskStart,
    VoiceAskStop,
    VoiceCaptureStartAndSendRecipient,
    VoiceCaptureStop,
    VoiceCaptureCancel,
    VoiceDiscard,
    CallAnswer,
    CallReject,
    CallHangup,
    CallToggleMute,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ListKind {
    Playlists,
    PlaylistTracks,
    RecentTracks,
    Contacts,
    CallHistory,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DynamicActionKind {
    TalkContact,
    VoiceNote,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SelectionTarget {
    PushScreen(UiScreen),
    EmitIntent(IntentTemplate),
    PushWithIntent {
        screen: UiScreen,
        intent: IntentTemplate,
    },
    DynamicListItem {
        kind: ListKind,
    },
    DynamicAction {
        kind: DynamicActionKind,
    },
    AdvanceFocus,
    Noop,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SnapshotCondition {
    Always,
    VoiceRecording,
    VoiceReviewOrFailedOrSent,
    TalkContactRecordAvailable,
    TalkContactRecordHeldOrPending,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct PassthroughPolicy {
    pub trigger: InputAction,
    pub when: SnapshotCondition,
    pub intent: IntentTemplate,
    pub captures_button: bool,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct BackPolicy {
    pub when: SnapshotCondition,
    pub intent: IntentTemplate,
    pub pop_screen: bool,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Route {
    pub screen: UiScreen,
    pub title: &'static str,
    pub focus_policy: FocusPolicy,
    pub nav_policy: NavigationPolicy,
    pub persistence: Persistence,
    pub select: &'static [SelectionTarget],
    pub back: &'static [BackPolicy],
    pub passthrough: &'static [PassthroughPolicy],
    pub on_enter: Option<TimelineRef>,
    pub on_exit: Option<TimelineRef>,
}
