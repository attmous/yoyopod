use crate::runtime::UiScreen;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct StatusBarModel {
    pub network_connected: bool,
    pub network_enabled: bool,
    pub connection_type: String,
    pub signal_strength: i32,
    pub gps_has_fix: bool,
    pub battery_percent: i32,
    pub charging: bool,
    pub power_available: bool,
    pub voip_state: i32,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ChromeModel {
    pub status: StatusBarModel,
    pub footer: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct HubCardModel {
    pub key: String,
    pub title: String,
    pub subtitle: String,
    pub accent: u32,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct HubViewModel {
    pub chrome: ChromeModel,
    pub cards: Vec<HubCardModel>,
    pub selected_index: usize,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ListRowModel {
    pub id: String,
    pub title: String,
    pub subtitle: String,
    pub icon_key: String,
    pub selected: bool,
}

/// ```compile_fail
/// use yoyopod_ui_host::runtime::UiScreen;
/// use yoyopod_ui_host::screens::{ChromeModel, ListRowModel, ListScreenModel, ScreenModel, StatusBarModel};
///
/// let _ = ScreenModel::Listen(ListScreenModel {
///     screen: UiScreen::Contacts,
///     chrome: ChromeModel {
///         status: StatusBarModel {
///             network_connected: false,
///             network_enabled: false,
///             connection_type: String::new(),
///             signal_strength: 0,
///             gps_has_fix: false,
///             battery_percent: 100,
///             charging: false,
///             power_available: true,
///             voip_state: 1,
///         },
///         footer: String::new(),
///     },
///     title: String::new(),
///     subtitle: String::new(),
///     rows: vec![ListRowModel {
///         id: "id".to_string(),
///         title: "title".to_string(),
///         subtitle: String::new(),
///         icon_key: "icon".to_string(),
///         selected: false,
///     }],
/// });
/// ```
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ListScreenModel {
    pub chrome: ChromeModel,
    pub title: String,
    pub subtitle: String,
    pub rows: Vec<ListRowModel>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct NowPlayingViewModel {
    pub chrome: ChromeModel,
    pub title: String,
    pub artist: String,
    pub state_text: String,
    pub progress_permille: i32,
}

#[derive(Debug, Clone, PartialEq, Eq)]
/// ```compile_fail
/// use yoyopod_ui_host::runtime::UiScreen;
/// use yoyopod_ui_host::screens::{AskViewModel, ChromeModel, StatusBarModel};
///
/// let _ = AskViewModel {
///     screen: UiScreen::VoiceNote,
///     chrome: ChromeModel {
///         status: StatusBarModel {
///             network_connected: false,
///             network_enabled: false,
///             connection_type: String::new(),
///             signal_strength: 0,
///             gps_has_fix: false,
///             battery_percent: 100,
///             charging: false,
///             power_available: true,
///             voip_state: 1,
///         },
///         footer: String::new(),
///     },
///     title: String::new(),
///     subtitle: String::new(),
///     icon_key: "ask".to_string(),
/// };
/// ```
pub struct AskViewModel {
    pub chrome: ChromeModel,
    pub title: String,
    pub subtitle: String,
    pub icon_key: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
/// ```compile_fail
/// use yoyopod_ui_host::runtime::UiScreen;
/// use yoyopod_ui_host::screens::{CallViewModel, ChromeModel, StatusBarModel};
///
/// let _ = CallViewModel {
///     screen: UiScreen::OutgoingCall,
///     chrome: ChromeModel {
///         status: StatusBarModel {
///             network_connected: false,
///             network_enabled: false,
///             connection_type: String::new(),
///             signal_strength: 0,
///             gps_has_fix: false,
///             battery_percent: 100,
///             charging: false,
///             power_available: true,
///             voip_state: 2,
///         },
///         footer: String::new(),
///     },
///     title: String::new(),
///     subtitle: String::new(),
///     detail: String::new(),
///     muted: false,
/// };
/// ```
pub struct CallViewModel {
    pub chrome: ChromeModel,
    pub title: String,
    pub subtitle: String,
    pub detail: String,
    pub muted: bool,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PowerViewModel {
    pub chrome: ChromeModel,
    pub title: String,
    pub subtitle: String,
    pub rows: Vec<ListRowModel>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
/// ```compile_fail
/// use yoyopod_ui_host::runtime::UiScreen;
/// use yoyopod_ui_host::screens::{ChromeModel, OverlayViewModel, StatusBarModel};
///
/// let _ = OverlayViewModel {
///     screen: UiScreen::Error,
///     chrome: ChromeModel {
///         status: StatusBarModel {
///             network_connected: false,
///             network_enabled: false,
///             connection_type: String::new(),
///             signal_strength: 0,
///             gps_has_fix: false,
///             battery_percent: 100,
///             charging: false,
///             power_available: true,
///             voip_state: 1,
///         },
///         footer: String::new(),
///     },
///     title: String::new(),
///     subtitle: String::new(),
/// };
/// ```
pub struct OverlayViewModel {
    pub chrome: ChromeModel,
    pub title: String,
    pub subtitle: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ScreenModel {
    Hub(HubViewModel),
    Listen(ListScreenModel),
    Playlists(ListScreenModel),
    RecentTracks(ListScreenModel),
    NowPlaying(NowPlayingViewModel),
    Ask(AskViewModel),
    Talk(ListScreenModel),
    Contacts(ListScreenModel),
    CallHistory(ListScreenModel),
    VoiceNote(AskViewModel),
    IncomingCall(CallViewModel),
    OutgoingCall(CallViewModel),
    InCall(CallViewModel),
    Power(PowerViewModel),
    Loading(OverlayViewModel),
    Error(OverlayViewModel),
}

impl ScreenModel {
    pub fn screen(&self) -> UiScreen {
        match self {
            Self::Hub(_) => UiScreen::Hub,
            Self::Listen(_) => UiScreen::Listen,
            Self::Playlists(_) => UiScreen::Playlists,
            Self::RecentTracks(_) => UiScreen::RecentTracks,
            Self::NowPlaying(_) => UiScreen::NowPlaying,
            Self::Ask(_) => UiScreen::Ask,
            Self::Talk(_) => UiScreen::Talk,
            Self::Contacts(_) => UiScreen::Contacts,
            Self::CallHistory(_) => UiScreen::CallHistory,
            Self::VoiceNote(_) => UiScreen::VoiceNote,
            Self::IncomingCall(_) => UiScreen::IncomingCall,
            Self::OutgoingCall(_) => UiScreen::OutgoingCall,
            Self::InCall(_) => UiScreen::InCall,
            Self::Power(_) => UiScreen::Power,
            Self::Loading(_) => UiScreen::Loading,
            Self::Error(_) => UiScreen::Error,
        }
    }
}
