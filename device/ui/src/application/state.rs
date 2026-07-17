use crate::animation::Transition;
use crate::router;
use crate::router::history::HistoryEntry;
use crate::DirtyRegion;
use std::collections::BTreeMap;

use yoyopod_protocol::ui::{
    ListItemSnapshot, RuntimeSnapshot, RuntimeSnapshotDomain, UiIntent, UiScreen, VoiceFileAction,
    VoiceNoteSummarySnapshot, VoiceRecipientAction,
};

use super::intents;

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
    pub(crate) selected_contact: Option<ListItemSnapshot>,
    pub(crate) transitions: Vec<Transition>,
    pub(crate) full_snapshots: u64,
    pub(crate) patches_per_domain: BTreeMap<RuntimeSnapshotDomain, u64>,
    pub(crate) status_bar_preview_enabled: bool,
    pub(crate) status_bar_preview_stage: Option<u8>,
    pub(crate) status_clock_minute: Option<i64>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum HomeMode {
    Idle,
    Focused,
    Ambient,
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
    pub network: bool,
    pub overlay: bool,
    pub navigation: bool,
    pub focus: bool,
    pub input: bool,
    pub animation: bool,
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
            || self.network
            || self.overlay
            || self.navigation
            || self.focus
            || self.input
            || self.animation
    }

    pub(crate) fn mark_full(&mut self) {
        self.full = true;
        self.app_state = true;
        self.hub = true;
        self.music = true;
        self.call = true;
        self.voice = true;
        self.power = true;
        self.network = true;
        self.overlay = true;
        self.navigation = true;
        self.focus = true;
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
            RuntimeSnapshotDomain::Network => self.network = true,
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
            selected_contact: None,
            transitions: Vec::new(),
            full_snapshots: 0,
            patches_per_domain: BTreeMap::new(),
            status_bar_preview_enabled: false,
            status_bar_preview_stage: None,
            status_clock_minute: None,
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

    pub(crate) fn latest_voice_note_payload(&self) -> Option<VoiceFileAction> {
        let contact = self
            .selected_contact
            .as_ref()
            .or_else(|| self.snapshot.call.contacts.first())?;
        let note = self
            .snapshot
            .call
            .latest_voice_note_by_contact
            .get(&contact.id)?;
        voice_file_action(contact, note)
    }
}

fn voice_file_action(
    contact: &ListItemSnapshot,
    note: &VoiceNoteSummarySnapshot,
) -> Option<VoiceFileAction> {
    intents::voice_file_action(contact, note)
}
