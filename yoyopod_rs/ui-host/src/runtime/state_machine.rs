use serde::{Deserialize, Serialize};
use serde_json::json;

use crate::input::InputAction;
use crate::screens;
use crate::screens::ScreenModel;

use super::{ListItemSnapshot, RuntimeSnapshot, UiIntent};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum UiScreen {
    Hub,
    Listen,
    Playlists,
    RecentTracks,
    NowPlaying,
    Ask,
    Talk,
    Contacts,
    CallHistory,
    TalkContact,
    VoiceNote,
    IncomingCall,
    OutgoingCall,
    InCall,
    Power,
    Loading,
    Error,
}

impl UiScreen {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Hub => "hub",
            Self::Listen => "listen",
            Self::Playlists => "playlists",
            Self::RecentTracks => "recent_tracks",
            Self::NowPlaying => "now_playing",
            Self::Ask => "ask",
            Self::Talk => "talk",
            Self::Contacts => "contacts",
            Self::CallHistory => "call_history",
            Self::TalkContact => "talk_contact",
            Self::VoiceNote => "voice_note",
            Self::IncomingCall => "incoming_call",
            Self::OutgoingCall => "outgoing_call",
            Self::InCall => "in_call",
            Self::Power => "power",
            Self::Loading => "loading",
            Self::Error => "error",
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct UiView {
    pub screen: UiScreen,
    pub title: String,
    pub subtitle: String,
    pub footer: String,
    pub items: Vec<ListItemSnapshot>,
    pub focus_index: usize,
}

#[derive(Debug, Clone)]
pub struct UiRuntime {
    snapshot: RuntimeSnapshot,
    active_screen: UiScreen,
    screen_stack: Vec<UiScreen>,
    focus_index: usize,
    intents: Vec<UiIntent>,
    dirty: bool,
    last_app_state: String,
    selected_contact: Option<ListItemSnapshot>,
}

impl Default for UiRuntime {
    fn default() -> Self {
        Self {
            snapshot: RuntimeSnapshot::default(),
            active_screen: UiScreen::Hub,
            screen_stack: Vec::new(),
            focus_index: 0,
            intents: Vec::new(),
            dirty: true,
            last_app_state: "hub".to_string(),
            selected_contact: None,
        }
    }
}

impl UiRuntime {
    pub fn apply_snapshot(&mut self, snapshot: RuntimeSnapshot) {
        let app_state = snapshot.app_state.clone();
        self.snapshot = snapshot;
        self.apply_app_state_route(&app_state);
        self.last_app_state = app_state;
        self.apply_runtime_preemption();
        self.clamp_focus();
        self.dirty = true;
    }

    pub fn handle_input(&mut self, action: InputAction) {
        match action {
            InputAction::Advance => self.advance_focus(),
            InputAction::Select => self.select_focused(),
            InputAction::Back => self.go_back_or_emit(),
            InputAction::PttPress => self.handle_ptt_press(),
            InputAction::PttRelease => self.handle_ptt_release(),
        }
        self.clamp_focus();
        self.dirty = true;
    }

    pub fn active_screen(&self) -> UiScreen {
        self.active_screen
    }

    pub fn snapshot(&self) -> &RuntimeSnapshot {
        &self.snapshot
    }

    pub fn stack(&self) -> &[UiScreen] {
        &self.screen_stack
    }

    pub fn focus_index(&self) -> usize {
        self.focus_index
    }

    pub fn is_dirty(&self) -> bool {
        self.dirty
    }

    pub fn mark_clean(&mut self) {
        self.dirty = false;
    }

    pub fn take_intents(&mut self) -> Vec<UiIntent> {
        std::mem::take(&mut self.intents)
    }

    pub fn active_view(&self) -> UiView {
        match self.active_screen {
            UiScreen::TalkContact => screens::call::talk_contact_view(
                &self.snapshot,
                self.focus_index,
                self.selected_contact.as_ref(),
            ),
            UiScreen::VoiceNote => screens::ask::voice_note_view(
                &self.snapshot,
                self.focus_index,
                self.selected_contact.as_ref(),
            ),
            _ => Self::view_for_screen(self.active_screen, &self.snapshot, self.focus_index),
        }
    }

    pub fn active_screen_model(&self) -> ScreenModel {
        match self.active_screen {
            UiScreen::TalkContact => ScreenModel::TalkContact(screens::call::talk_contact_model(
                &self.snapshot,
                self.focus_index,
                self.selected_contact.as_ref(),
            )),
            UiScreen::VoiceNote => ScreenModel::VoiceNote(screens::ask::voice_note_model(
                &self.snapshot,
                self.focus_index,
                self.selected_contact.as_ref(),
            )),
            _ => {
                Self::screen_model_for_screen(self.active_screen, &self.snapshot, self.focus_index)
            }
        }
    }

    pub fn view_for_screen(
        screen: UiScreen,
        snapshot: &RuntimeSnapshot,
        focus_index: usize,
    ) -> UiView {
        match screen {
            UiScreen::Hub => screens::hub::view(snapshot, focus_index),
            UiScreen::Listen => screens::listen::view(snapshot, focus_index),
            UiScreen::Playlists => screens::music::playlists_view(snapshot, focus_index),
            UiScreen::RecentTracks => screens::music::recent_tracks_view(snapshot, focus_index),
            UiScreen::NowPlaying => screens::music::now_playing_view(snapshot, focus_index),
            UiScreen::Ask => screens::ask::ask_view(snapshot, focus_index),
            UiScreen::Talk => screens::talk::view(focus_index),
            UiScreen::Contacts => screens::call::contacts_view(snapshot, focus_index),
            UiScreen::CallHistory => screens::call::call_history_view(snapshot, focus_index),
            UiScreen::TalkContact => screens::call::talk_contact_view(snapshot, focus_index, None),
            UiScreen::VoiceNote => screens::ask::voice_note_view(snapshot, focus_index, None),
            UiScreen::IncomingCall => screens::call::incoming_view(snapshot, focus_index),
            UiScreen::OutgoingCall => screens::call::outgoing_view(snapshot, focus_index),
            UiScreen::InCall => screens::call::in_call_view(snapshot, focus_index),
            UiScreen::Power => screens::power::view(snapshot, focus_index),
            UiScreen::Loading => screens::overlay::loading_view(snapshot),
            UiScreen::Error => screens::overlay::error_view(snapshot),
        }
    }

    pub fn screen_model_for_screen(
        screen: UiScreen,
        snapshot: &RuntimeSnapshot,
        focus_index: usize,
    ) -> ScreenModel {
        match screen {
            UiScreen::Hub => ScreenModel::Hub(screens::hub::model(snapshot, focus_index)),
            UiScreen::Listen => ScreenModel::Listen(screens::listen::model(snapshot, focus_index)),
            UiScreen::Playlists => {
                ScreenModel::Playlists(screens::music::playlists_model(snapshot, focus_index))
            }
            UiScreen::RecentTracks => ScreenModel::RecentTracks(
                screens::music::recent_tracks_model(snapshot, focus_index),
            ),
            UiScreen::NowPlaying => {
                ScreenModel::NowPlaying(screens::music::now_playing_model(snapshot))
            }
            UiScreen::Ask => ScreenModel::Ask(screens::ask::ask_model(snapshot)),
            UiScreen::Talk => ScreenModel::Talk(screens::talk::model(snapshot, focus_index)),
            UiScreen::Contacts => {
                ScreenModel::Contacts(screens::call::contacts_model(snapshot, focus_index))
            }
            UiScreen::CallHistory => {
                ScreenModel::CallHistory(screens::call::call_history_model(snapshot, focus_index))
            }
            UiScreen::TalkContact => ScreenModel::TalkContact(screens::call::talk_contact_model(
                snapshot,
                focus_index,
                None,
            )),
            UiScreen::VoiceNote => {
                ScreenModel::VoiceNote(screens::ask::voice_note_model(snapshot, focus_index, None))
            }
            UiScreen::IncomingCall => {
                ScreenModel::IncomingCall(screens::call::incoming_model(snapshot))
            }
            UiScreen::OutgoingCall => {
                ScreenModel::OutgoingCall(screens::call::outgoing_model(snapshot))
            }
            UiScreen::InCall => ScreenModel::InCall(screens::call::in_call_model(snapshot)),
            UiScreen::Power => ScreenModel::Power(screens::power::model(snapshot, focus_index)),
            UiScreen::Loading => ScreenModel::Loading(screens::overlay::loading_model(snapshot)),
            UiScreen::Error => ScreenModel::Error(screens::overlay::error_model(snapshot)),
        }
    }

    fn apply_runtime_preemption(&mut self) {
        let desired = if !self.snapshot.overlay.error.trim().is_empty() {
            Some(UiScreen::Error)
        } else if self.snapshot.overlay.loading {
            Some(UiScreen::Loading)
        } else {
            match self.snapshot.call.state.as_str() {
                "incoming" => Some(UiScreen::IncomingCall),
                "outgoing" => Some(UiScreen::OutgoingCall),
                "active" => Some(UiScreen::InCall),
                _ => None,
            }
        };

        if let Some(screen) = desired {
            if self.active_screen != screen {
                self.push_screen(screen);
            }
            return;
        }

        if self.is_overlay_screen() {
            self.pop_until_not_overlay();
        }

        if self.is_call_screen() && self.snapshot.call.state == "idle" {
            self.pop_until_not_call();
        }
    }

    fn apply_app_state_route(&mut self, app_state: &str) {
        if app_state == self.last_app_state {
            return;
        }
        let Some(screen) = Self::screen_for_app_state(app_state) else {
            return;
        };
        if self.active_screen != screen {
            self.screen_stack.clear();
            self.active_screen = screen;
            self.focus_index = 0;
        }
    }

    fn screen_for_app_state(app_state: &str) -> Option<UiScreen> {
        match app_state.trim() {
            "hub" | "home" | "menu" => Some(UiScreen::Hub),
            "listen" => Some(UiScreen::Listen),
            "playlists" => Some(UiScreen::Playlists),
            "recent_tracks" => Some(UiScreen::RecentTracks),
            "now_playing" => Some(UiScreen::NowPlaying),
            "ask" => Some(UiScreen::Ask),
            "call" | "talk" => Some(UiScreen::Talk),
            "contacts" => Some(UiScreen::Contacts),
            "call_history" => Some(UiScreen::CallHistory),
            "talk_contact" => Some(UiScreen::TalkContact),
            "voice_note" => Some(UiScreen::VoiceNote),
            "incoming_call" => Some(UiScreen::IncomingCall),
            "outgoing_call" => Some(UiScreen::OutgoingCall),
            "in_call" => Some(UiScreen::InCall),
            "power" | "setup" => Some(UiScreen::Power),
            "loading" => Some(UiScreen::Loading),
            "error" => Some(UiScreen::Error),
            _ => None,
        }
    }

    fn advance_focus(&mut self) {
        let count = self.focus_count();
        if count == 0 {
            return;
        }
        self.focus_index = (self.focus_index + 1) % count;
    }

    fn select_focused(&mut self) {
        match self.active_screen {
            UiScreen::Hub => match self.focus_index {
                0 => self.push_screen(UiScreen::Listen),
                1 => self.push_screen(UiScreen::Talk),
                2 => self.push_screen(UiScreen::Ask),
                _ => self.push_screen(UiScreen::Power),
            },
            UiScreen::Listen => match self.focus_index {
                0 => self.push_screen(UiScreen::Playlists),
                1 => self.push_screen(UiScreen::RecentTracks),
                _ => {
                    self.intents.push(UiIntent::new("music", "shuffle_all"));
                    self.push_screen(UiScreen::NowPlaying);
                }
            },
            UiScreen::Talk => match self.focus_index {
                0 => self.push_screen(UiScreen::Contacts),
                1 => self.push_screen(UiScreen::CallHistory),
                _ => self.push_screen(UiScreen::VoiceNote),
            },
            UiScreen::Playlists => {
                if let Some(item) = self.snapshot.music.playlists.get(self.focus_index).cloned() {
                    self.intents.push(UiIntent::with_payload(
                        "music",
                        "load_playlist",
                        item_payload(&item),
                    ));
                    self.push_screen(UiScreen::NowPlaying);
                }
            }
            UiScreen::RecentTracks => {
                if let Some(item) = self
                    .snapshot
                    .music
                    .recent_tracks
                    .get(self.focus_index)
                    .cloned()
                {
                    self.intents.push(UiIntent::with_payload(
                        "music",
                        "play_recent_track",
                        item_payload(&item),
                    ));
                    self.push_screen(UiScreen::NowPlaying);
                }
            }
            UiScreen::NowPlaying => self.intents.push(UiIntent::new("music", "play_pause")),
            UiScreen::Ask => self.intents.push(UiIntent::new("voice", "ask_start")),
            UiScreen::VoiceNote => self.select_voice_note(),
            UiScreen::Contacts => {
                if let Some(item) = self.snapshot.call.contacts.get(self.focus_index).cloned() {
                    self.selected_contact = Some(item);
                    self.push_screen(UiScreen::TalkContact);
                }
            }
            UiScreen::TalkContact => self.select_talk_contact_action(),
            UiScreen::CallHistory => {
                if let Some(item) = self.snapshot.call.history.get(self.focus_index).cloned() {
                    self.emit_call_start(&item);
                }
            }
            UiScreen::IncomingCall => self.intents.push(UiIntent::new("call", "answer")),
            UiScreen::InCall => self.intents.push(UiIntent::new("call", "toggle_mute")),
            UiScreen::Power => self.advance_focus(),
            _ => {}
        }
    }

    fn go_back_or_emit(&mut self) {
        match self.active_screen {
            UiScreen::IncomingCall => self.intents.push(UiIntent::new("call", "reject")),
            UiScreen::OutgoingCall | UiScreen::InCall => {
                self.intents.push(UiIntent::new("call", "hangup"))
            }
            UiScreen::VoiceNote if self.voice_note_phase() == "recording" => {
                self.intents.push(UiIntent::new("voice", "capture_cancel"));
                self.pop_screen_or_hub();
            }
            UiScreen::VoiceNote
                if matches!(
                    self.voice_note_phase().as_str(),
                    "review" | "failed" | "sent"
                ) =>
            {
                self.intents.push(UiIntent::new("voice", "discard"));
                self.pop_screen_or_hub();
            }
            UiScreen::Loading | UiScreen::Error => self.pop_screen_or_hub(),
            UiScreen::Hub => {}
            _ => self.pop_screen_or_hub(),
        }
    }

    fn emit_call_start(&mut self, item: &ListItemSnapshot) {
        self.intents.push(UiIntent::with_payload(
            "call",
            "start",
            json!({"id": item.id, "name": item.title}),
        ));
    }

    fn select_talk_contact_action(&mut self) {
        let actions =
            screens::call::talk_contact_actions(&self.snapshot, self.selected_contact.as_ref());
        let Some(action) = actions.get(self.focus_index) else {
            return;
        };
        match action.kind {
            "call" => {
                if let Some(item) = self.selected_contact.clone() {
                    self.emit_call_start(&item);
                }
            }
            "voice_note" => self.push_screen(UiScreen::VoiceNote),
            "play_note" => {
                if let Some(payload) = self.latest_voice_note_payload() {
                    self.intents
                        .push(UiIntent::with_payload("voice", "play_latest", payload));
                }
            }
            _ => {}
        }
    }

    fn select_voice_note(&mut self) {
        match self.voice_note_phase().as_str() {
            "ready" => self.pop_screen_or_hub(),
            "recording" => self.intents.push(UiIntent::new("voice", "capture_stop")),
            "review" => match self.focus_index {
                0 => {
                    if let Some(payload) = self.voice_note_recipient_payload() {
                        self.intents
                            .push(UiIntent::with_payload("voice", "send", payload));
                    }
                }
                1 => self.intents.push(UiIntent::new("voice", "play")),
                _ => self.intents.push(UiIntent::new("voice", "discard")),
            },
            "failed" => match self.focus_index {
                0 => {
                    if let Some(payload) = self.voice_note_recipient_payload() {
                        self.intents
                            .push(UiIntent::with_payload("voice", "send", payload));
                    }
                }
                _ => self.intents.push(UiIntent::new("voice", "discard")),
            },
            "sent" => {
                self.intents.push(UiIntent::new("voice", "discard"));
                self.pop_screen_or_hub();
            }
            "sending" => {}
            _ => {}
        }
    }

    fn handle_ptt_press(&mut self) {
        if self.active_screen == UiScreen::VoiceNote && self.voice_note_phase() == "ready" {
            if let Some(payload) = self.voice_note_recipient_payload() {
                self.intents
                    .push(UiIntent::with_payload("voice", "capture_start", payload));
            }
            return;
        }
        if self.active_screen == UiScreen::Ask {
            self.intents.push(UiIntent::new("voice", "ask_start"));
        }
    }

    fn handle_ptt_release(&mut self) {
        if self.active_screen == UiScreen::VoiceNote && self.voice_note_phase() == "recording" {
            self.intents.push(UiIntent::new("voice", "capture_stop"));
            return;
        }
        if self.active_screen == UiScreen::Ask {
            self.intents.push(UiIntent::new("voice", "ask_stop"));
        }
    }

    pub fn wants_ptt_passthrough(&self) -> bool {
        self.active_screen == UiScreen::VoiceNote
            && matches!(self.voice_note_phase().as_str(), "ready" | "recording")
    }

    fn voice_note_phase(&self) -> String {
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

    fn voice_note_recipient_payload(&self) -> Option<serde_json::Value> {
        let contact = self
            .selected_contact
            .as_ref()
            .or_else(|| self.snapshot.call.contacts.first())?;
        if contact.id.trim().is_empty() {
            return None;
        }
        Some(json!({
            "id": contact.id,
            "recipient_address": contact.id,
            "recipient_name": contact.title,
        }))
    }

    fn latest_voice_note_payload(&self) -> Option<serde_json::Value> {
        let contact = self
            .selected_contact
            .as_ref()
            .or_else(|| self.snapshot.call.contacts.first())?;
        let note = self
            .snapshot
            .call
            .latest_voice_note_by_contact
            .get(&contact.id)?;
        if note.local_file_path.trim().is_empty() {
            return None;
        }
        Some(json!({
            "id": contact.id,
            "recipient_name": contact.title,
            "file_path": note.local_file_path,
        }))
    }

    fn push_screen(&mut self, screen: UiScreen) {
        if self.active_screen != screen {
            self.screen_stack.push(self.active_screen);
        }
        self.active_screen = screen;
        self.focus_index = 0;
    }

    fn pop_screen_or_hub(&mut self) {
        self.active_screen = self.screen_stack.pop().unwrap_or(UiScreen::Hub);
        self.focus_index = 0;
    }

    fn pop_until_not_call(&mut self) {
        while self.is_call_screen() {
            self.active_screen = self.screen_stack.pop().unwrap_or(UiScreen::Hub);
        }
        self.focus_index = 0;
    }

    fn pop_until_not_overlay(&mut self) {
        while self.is_overlay_screen() {
            self.active_screen = self.screen_stack.pop().unwrap_or(UiScreen::Hub);
        }
        self.focus_index = 0;
    }

    fn is_call_screen(&self) -> bool {
        matches!(
            self.active_screen,
            UiScreen::IncomingCall | UiScreen::OutgoingCall | UiScreen::InCall
        )
    }

    fn is_overlay_screen(&self) -> bool {
        matches!(self.active_screen, UiScreen::Loading | UiScreen::Error)
    }

    fn clamp_focus(&mut self) {
        let count = self.focus_count();
        if count == 0 {
            self.focus_index = 0;
        } else if self.focus_index >= count {
            self.focus_index = count - 1;
        }
    }

    fn focus_count(&self) -> usize {
        match self.active_screen {
            UiScreen::Hub => self.snapshot.hub.cards.len().max(1),
            UiScreen::Listen => screens::listen::items(&self.snapshot).len(),
            UiScreen::Playlists => self.snapshot.music.playlists.len(),
            UiScreen::RecentTracks => self.snapshot.music.recent_tracks.len(),
            UiScreen::Talk => screens::talk::items().len(),
            UiScreen::Contacts => self.snapshot.call.contacts.len(),
            UiScreen::CallHistory => self.snapshot.call.history.len(),
            UiScreen::TalkContact => {
                screens::call::talk_contact_actions(&self.snapshot, self.selected_contact.as_ref())
                    .len()
            }
            UiScreen::VoiceNote => screens::ask::voice_note_action_count(&self.snapshot),
            UiScreen::Power => screens::power::page_count(&self.snapshot),
            _ => 0,
        }
    }
}

fn item_payload(item: &ListItemSnapshot) -> serde_json::Value {
    json!({"id": item.id, "title": item.title})
}
