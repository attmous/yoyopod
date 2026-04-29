use serde::{Deserialize, Serialize};
use serde_json::json;

use crate::input::InputAction;
use crate::screens;

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
        }
    }
}

impl UiRuntime {
    pub fn apply_snapshot(&mut self, snapshot: RuntimeSnapshot) {
        self.snapshot = snapshot;
        self.apply_runtime_preemption();
        self.clamp_focus();
        self.dirty = true;
    }

    pub fn handle_input(&mut self, action: InputAction) {
        match action {
            InputAction::Advance => self.advance_focus(),
            InputAction::Select => self.select_focused(),
            InputAction::Back => self.go_back_or_emit(),
            InputAction::PttPress => self.intents.push(UiIntent::new("voice", "capture_start")),
            InputAction::PttRelease => self.intents.push(UiIntent::new("voice", "capture_stop")),
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
        Self::view_for_screen(self.active_screen, &self.snapshot, self.focus_index)
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
            UiScreen::VoiceNote => screens::ask::voice_note_view(snapshot, focus_index),
            UiScreen::IncomingCall => screens::call::incoming_view(snapshot, focus_index),
            UiScreen::OutgoingCall => screens::call::outgoing_view(snapshot, focus_index),
            UiScreen::InCall => screens::call::in_call_view(snapshot, focus_index),
            UiScreen::Power => screens::power::view(snapshot, focus_index),
            UiScreen::Loading => screens::overlay::loading_view(snapshot),
            UiScreen::Error => screens::overlay::error_view(snapshot),
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
                0 => self.push_screen(UiScreen::NowPlaying),
                1 => self.push_screen(UiScreen::Playlists),
                2 => self.push_screen(UiScreen::RecentTracks),
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
            UiScreen::Ask | UiScreen::VoiceNote => {
                self.intents.push(UiIntent::new("voice", "capture_toggle"))
            }
            UiScreen::Contacts => {
                if let Some(item) = self.snapshot.call.contacts.get(self.focus_index).cloned() {
                    self.emit_call_start(&item);
                }
            }
            UiScreen::CallHistory => {
                if let Some(item) = self.snapshot.call.history.get(self.focus_index).cloned() {
                    self.emit_call_start(&item);
                }
            }
            UiScreen::IncomingCall => self.intents.push(UiIntent::new("call", "answer")),
            UiScreen::InCall => self.intents.push(UiIntent::new("call", "toggle_mute")),
            _ => {}
        }
    }

    fn go_back_or_emit(&mut self) {
        match self.active_screen {
            UiScreen::IncomingCall => self.intents.push(UiIntent::new("call", "reject")),
            UiScreen::OutgoingCall | UiScreen::InCall => {
                self.intents.push(UiIntent::new("call", "hangup"))
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
            UiScreen::Power => screens::power::items(&self.snapshot).len().max(1),
            _ => 0,
        }
    }
}

fn item_payload(item: &ListItemSnapshot) -> serde_json::Value {
    json!({"id": item.id, "title": item.title})
}
