use crate::animation::{Timeline, Transition};
use crate::router;
use crate::router::history::HistoryEntry;
use crate::DirtyRegion;
use std::collections::BTreeMap;

use yoyopod_protocol::ui::{
    ListItemSnapshot, RuntimeSnapshot, RuntimeSnapshotDomain, UiEvent, UiIntent, UiScreen,
    VoiceFileAction, VoiceNoteSummarySnapshot, VoiceRecipientAction,
};

use super::intents;
use crate::components::widgets::CompanionVariant;
use crate::theme::ColorScheme;

#[derive(Debug, Clone)]
pub struct UiRuntime {
    pub(crate) snapshot: RuntimeSnapshot,
    pub(crate) active_screen: UiScreen,
    pub(crate) screen_stack: Vec<HistoryEntry>,
    pub(crate) focus_index: usize,
    pub(crate) home_mode: HomeMode,
    pub(crate) last_input_ms: Option<u64>,
    pub(crate) intents: Vec<UiIntent>,
    pub(crate) dirty: DirtyState,
    pub(crate) selected_playlist: Option<ListItemSnapshot>,
    pub(crate) selected_contact: Option<ListItemSnapshot>,
    pub(crate) replay_index: usize,
    pub(crate) replay_auto_advance_armed: bool,
    pub(crate) replay_pending_delete_message_id: Option<String>,
    pub(crate) transitions: Vec<Transition>,
    pub(crate) pending_wheel_roll: Option<PendingWheelRoll>,
    pub(crate) scene_revision: u32,
    pub(crate) full_snapshots: u64,
    pub(crate) patches_per_domain: BTreeMap<RuntimeSnapshotDomain, u64>,
    pub(crate) status_bar_preview_enabled: bool,
    pub(crate) status_bar_preview_stage: Option<u8>,
    pub(crate) status_clock_minute: Option<i64>,
    pub(crate) system_overlay: SystemOverlayState,
    pub(crate) system_overlay_preview: Option<SystemOverlayPreview>,
    pub(crate) companion_preview: Option<CompanionVariant>,
    pub(crate) theme_preview: Option<ColorScheme>,
    pub(crate) ask_offline_started_ms: Option<u64>,
    pub(crate) stopwatch: StopwatchState,
    pub(crate) flashlight_started_ms: Option<u64>,
    pub(crate) last_focus_identity: Option<String>,
    pub(crate) focus_prompt_sequence: u64,
    pub(crate) accessibility_events: Vec<UiEvent>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SystemOverlayPreview {
    Loading,
    RecoverableError,
    UnrecoverableError,
}

#[derive(Debug, Clone, Default)]
pub(crate) struct SystemOverlayState {
    pub loading_started_ms: Option<u64>,
    pub loading_visible: bool,
    pub loading_announced: bool,
    pub spinner_step: u8,
    pub error_started_ms: Option<u64>,
    pub error_signature: String,
    pub error_announced: bool,
    pub unrecoverable_repeat_announced: bool,
}

impl SystemOverlayState {
    pub fn reset_loading(&mut self) {
        self.loading_started_ms = None;
        self.loading_visible = false;
        self.loading_announced = false;
        self.spinner_step = 0;
    }

    pub fn reset_error(&mut self) {
        self.error_started_ms = None;
        self.error_signature.clear();
        self.error_announced = false;
        self.unrecoverable_repeat_announced = false;
    }

    pub fn reset(&mut self) {
        self.reset_loading();
        self.reset_error();
    }
}

#[derive(Debug, Clone)]
pub(crate) struct PendingWheelRoll {
    pub screen: UiScreen,
    pub target_focus: usize,
    pub timeline: Timeline,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum HomeMode {
    Idle,
    Focused,
    Ambient,
}

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub(crate) enum StopwatchPhase {
    #[default]
    Idle,
    Running,
    Paused,
}

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
struct StopwatchDisplayKey {
    hour_mode: bool,
    units: u64,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub(crate) struct StopwatchState {
    pub phase: StopwatchPhase,
    accumulated_ms: u64,
    started_at_ms: Option<u64>,
    displayed: StopwatchDisplayKey,
}

impl StopwatchState {
    pub fn elapsed_ms(&self, now_ms: u64) -> u64 {
        self.accumulated_ms.saturating_add(
            self.started_at_ms
                .map(|started_at_ms| now_ms.saturating_sub(started_at_ms))
                .unwrap_or(0),
        )
    }

    pub fn display_text(&self, now_ms: u64) -> String {
        format_stopwatch_duration(self.elapsed_ms(now_ms))
    }

    pub const fn action_count(&self) -> usize {
        if matches!(self.phase, StopwatchPhase::Paused) {
            2
        } else {
            1
        }
    }

    pub const fn action_label(&self, focus_index: usize) -> &'static str {
        match (self.phase, focus_index) {
            (StopwatchPhase::Idle, _) => "Start",
            (StopwatchPhase::Running, _) => "Pause",
            (StopwatchPhase::Paused, 0) => "Resume",
            (StopwatchPhase::Paused, _) => "Reset",
        }
    }

    pub const fn action_icon(&self, focus_index: usize) -> &'static str {
        match (self.phase, focus_index) {
            (StopwatchPhase::Running, _) => "pause_sm",
            (StopwatchPhase::Paused, index) if index > 0 => "reset_sm",
            _ => "play_sm",
        }
    }

    pub fn activate(&mut self, focus_index: usize, now_ms: u64) {
        match (self.phase, focus_index) {
            (StopwatchPhase::Idle, _) => {
                self.phase = StopwatchPhase::Running;
                self.started_at_ms = Some(now_ms);
            }
            (StopwatchPhase::Running, _) => {
                self.accumulated_ms = self.elapsed_ms(now_ms);
                self.started_at_ms = None;
                self.phase = StopwatchPhase::Paused;
                self.displayed = display_key(self.accumulated_ms);
            }
            (StopwatchPhase::Paused, 0) => {
                self.phase = StopwatchPhase::Running;
                self.started_at_ms = Some(now_ms);
            }
            (StopwatchPhase::Paused, _) => self.reset(),
        }
    }

    pub fn advance_display(&mut self, now_ms: u64) -> bool {
        if self.phase != StopwatchPhase::Running {
            return false;
        }
        let displayed = display_key(self.elapsed_ms(now_ms));
        if displayed == self.displayed {
            return false;
        }
        self.displayed = displayed;
        true
    }

    pub fn reset(&mut self) {
        *self = Self::default();
    }
}

fn display_key(elapsed_ms: u64) -> StopwatchDisplayKey {
    if elapsed_ms < 3_600_000 {
        StopwatchDisplayKey {
            hour_mode: false,
            units: elapsed_ms / 100,
        }
    } else {
        StopwatchDisplayKey {
            hour_mode: true,
            units: elapsed_ms / 1_000,
        }
    }
}

pub(crate) fn format_stopwatch_duration(elapsed_ms: u64) -> String {
    let total_seconds = elapsed_ms / 1_000;
    if elapsed_ms < 3_600_000 {
        format!(
            "{:02}:{:02}.{}",
            total_seconds / 60,
            total_seconds % 60,
            (elapsed_ms / 100) % 10
        )
    } else {
        format!(
            "{:02}:{:02}:{:02}",
            total_seconds / 3_600,
            (total_seconds / 60) % 60,
            total_seconds % 60
        )
    }
}

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct DirtyState {
    pub full: bool,
    pub app_state: bool,
    pub hub: bool,
    pub music: bool,
    pub call: bool,
    pub voice: bool,
    pub power: bool,
    pub settings: bool,
    pub network: bool,
    pub wifi_setup: bool,
    pub overlay: bool,
    pub navigation: bool,
    pub focus: bool,
    pub input: bool,
    pub animation: bool,
    pub stopwatch: bool,
}

impl DirtyState {
    pub fn any(self) -> bool {
        self.full
            || self.app_state
            || self.hub
            || self.music
            || self.call
            || self.voice
            || self.power
            || self.settings
            || self.network
            || self.wifi_setup
            || self.overlay
            || self.navigation
            || self.focus
            || self.input
            || self.animation
            || self.stopwatch
    }

    pub(crate) fn animation_only(mut self) -> bool {
        if !self.animation {
            return false;
        }
        self.animation = false;
        !self.any()
    }

    pub(crate) fn mark_full(&mut self) {
        self.full = true;
        self.app_state = true;
        self.hub = true;
        self.music = true;
        self.call = true;
        self.voice = true;
        self.power = true;
        self.settings = true;
        self.network = true;
        self.wifi_setup = true;
        self.overlay = true;
        self.navigation = true;
        self.focus = true;
        self.stopwatch = true;
    }

    pub(crate) fn mark_patch_domain(&mut self, domain: RuntimeSnapshotDomain) {
        match domain {
            RuntimeSnapshotDomain::Full => self.mark_full(),
            RuntimeSnapshotDomain::AppState => {
                self.app_state = true;
                self.navigation = true;
            }
            RuntimeSnapshotDomain::Hub => self.hub = true,
            RuntimeSnapshotDomain::Music => self.music = true,
            RuntimeSnapshotDomain::Call => self.call = true,
            RuntimeSnapshotDomain::Voice => self.voice = true,
            RuntimeSnapshotDomain::Power => self.power = true,
            RuntimeSnapshotDomain::Settings => self.settings = true,
            RuntimeSnapshotDomain::Network => self.network = true,
            RuntimeSnapshotDomain::WifiSetup => self.wifi_setup = true,
            RuntimeSnapshotDomain::Overlay => self.overlay = true,
        }
    }

    pub(crate) fn render_region(self, screen: UiScreen) -> Option<DirtyRegion> {
        if self.full
            || self.app_state
            || self.navigation
            || self.focus
            || self.input
            || self.animation
            || self.hub
            || self.music
            || self.call
            || self.voice
            || self.settings
            || self.wifi_setup
            || self.overlay
        {
            return None;
        }

        let mut region: Option<DirtyRegion> = None;
        for domain in [
            (self.power, RuntimeSnapshotDomain::Power),
            (self.network, RuntimeSnapshotDomain::Network),
        ] {
            if !domain.0 {
                continue;
            }
            let domain_region = router::dirty_region_for(screen, domain.1)?;
            region = Some(match region {
                Some(existing) => existing.union(domain_region),
                None => domain_region,
            });
        }
        region
    }
}

impl Default for UiRuntime {
    fn default() -> Self {
        Self {
            snapshot: RuntimeSnapshot::default(),
            active_screen: UiScreen::Hub,
            screen_stack: Vec::new(),
            focus_index: 0,
            home_mode: HomeMode::Idle,
            last_input_ms: None,
            intents: Vec::new(),
            dirty: {
                let mut dirty = DirtyState::default();
                dirty.mark_full();
                dirty
            },
            selected_playlist: None,
            selected_contact: None,
            replay_index: 0,
            replay_auto_advance_armed: false,
            replay_pending_delete_message_id: None,
            transitions: Vec::new(),
            pending_wheel_roll: None,
            scene_revision: 0,
            full_snapshots: 0,
            patches_per_domain: BTreeMap::new(),
            status_bar_preview_enabled: false,
            status_bar_preview_stage: None,
            status_clock_minute: None,
            system_overlay: SystemOverlayState::default(),
            system_overlay_preview: None,
            companion_preview: None,
            theme_preview: None,
            ask_offline_started_ms: None,
            stopwatch: StopwatchState::default(),
            flashlight_started_ms: None,
            last_focus_identity: None,
            focus_prompt_sequence: 0,
            accessibility_events: Vec::new(),
        }
    }
}

impl UiRuntime {
    pub(crate) fn voice_note_phase(&self) -> String {
        let phase = self.snapshot.voice.phase.trim().to_ascii_lowercase();
        if self.snapshot.voice.capture_in_flight
            || self.snapshot.voice.ptt_active
            || phase == "recording"
        {
            return "recording".to_string();
        }
        if matches!(phase.as_str(), "review" | "sending" | "sent" | "failed") {
            return phase;
        }
        "ready".to_string()
    }

    pub(crate) fn voice_note_recipient_payload(&self) -> Option<VoiceRecipientAction> {
        let contact = self
            .selected_contact
            .as_ref()
            .or_else(|| self.snapshot.call.contacts.first())?;
        intents::voice_recipient_action(contact)
    }

    pub(crate) fn replay_notes(&self) -> &[VoiceNoteSummarySnapshot] {
        let Some(contact) = self
            .selected_contact
            .as_ref()
            .or_else(|| self.snapshot.call.contacts.first())
        else {
            return &[];
        };
        self.snapshot
            .call
            .voice_notes_by_contact
            .get(&contact.id)
            .map(Vec::as_slice)
            .unwrap_or_default()
    }

    pub(crate) fn replay_note_payload(&self) -> Option<VoiceFileAction> {
        let contact = self
            .selected_contact
            .as_ref()
            .or_else(|| self.snapshot.call.contacts.first())?;
        let note = self.replay_notes().get(self.replay_index)?;
        voice_file_action(contact, note)
    }
}

fn voice_file_action(
    contact: &ListItemSnapshot,
    note: &VoiceNoteSummarySnapshot,
) -> Option<VoiceFileAction> {
    intents::voice_file_action(contact, note)
}
