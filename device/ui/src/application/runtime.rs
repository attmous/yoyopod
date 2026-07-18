use time::OffsetDateTime;
use yoyopod_protocol::ui::{
    AnimationRequest, InputAction, RuntimeSnapshot, RuntimeSnapshotPatch, UiIntent,
};

use crate::animation;
use crate::components;
use crate::router::history::HistoryEntry;
use crate::scene::{
    defaults_for, GlobalClock, HudBattery, HudConnectivity, HudConnectivityKind, HudStatus,
    SceneGraph, SceneId,
};
use crate::DirtyRegion;

use super::state::{DirtyState, HomeMode, UiRuntime};
use super::{input_router, navigator, snapshot, UiScreen};

#[derive(Debug, Clone)]
pub struct FrameRequest {
    pub scene_graph: SceneGraph,
    pub dirty_region: Option<DirtyRegion>,
}

impl UiRuntime {
    pub(crate) fn with_status_bar_preview(enabled: bool) -> Self {
        Self {
            status_bar_preview_enabled: enabled,
            ..Self::default()
        }
    }

    pub(crate) fn advance_status_bar(&mut self, now_ms: u64) {
        let (minute, _) = current_status_time();
        if self.status_clock_minute != Some(minute) {
            self.status_clock_minute = Some(minute);
            self.dirty.power = true;
        }

        if self.status_bar_preview_enabled {
            let stage = status_bar_preview_stage(now_ms);
            if self.status_bar_preview_stage != Some(stage) {
                self.status_bar_preview_stage = Some(stage);
                self.dirty.network = true;
                self.dirty.power = true;
            }
        }
    }

    pub fn apply_snapshot(&mut self, snapshot: RuntimeSnapshot) {
        let pending_identity = self.pending_wheel_identity();
        let change = snapshot::replace_full(&mut self.snapshot, snapshot);
        self.full_snapshots += 1;
        navigator::apply_app_state_route(self, &change.previous_app_state, &change.app_state);
        navigator::apply_runtime_preemption(self);
        navigator::clamp_focus(self);
        self.reconcile_pending_wheel_roll(pending_identity);
        self.dirty.mark_full();
    }

    pub fn apply_patch(&mut self, patch: RuntimeSnapshotPatch) {
        let domain = patch.domain();
        let pending_identity = self.pending_wheel_identity();
        let previous_screen = self.active_screen;
        let previous_focus = self.focus_index;
        let previous_stack_len = self.screen_stack.len();
        let change = snapshot::apply_patch(&mut self.snapshot, patch);
        *self.patches_per_domain.entry(domain).or_insert(0) += 1;
        navigator::apply_app_state_route(self, &change.previous_app_state, &change.app_state);
        navigator::apply_runtime_preemption(self);
        navigator::clamp_focus(self);
        self.reconcile_pending_wheel_roll(pending_identity);
        self.dirty.mark_patch_domain(change.domain);
        if self.active_screen != previous_screen || self.screen_stack.len() != previous_stack_len {
            self.dirty.navigation = true;
        }
        if self.focus_index != previous_focus {
            self.dirty.focus = true;
        }
    }

    pub fn handle_input(&mut self, action: InputAction, now_ms: u64) {
        if self.wake_home_from_ambient(now_ms) {
            return;
        }
        self.last_input_ms = Some(now_ms);
        if self.pending_wheel_roll.is_some() {
            if action == InputAction::Advance {
                self.dirty.input = true;
                return;
            }
            self.commit_pending_wheel_roll();
        }
        let previous_screen = self.active_screen;
        let route_state = input_router::InputRouteState {
            active_screen: self.active_screen,
            voice_note_phase: self.voice_note_phase(),
        };
        match input_router::route(action, &route_state) {
            input_router::AppCommand::AdvanceFocus => {
                if !self.begin_wheel_roll(now_ms) {
                    navigator::advance_focus(self);
                }
            }
            input_router::AppCommand::SelectFocused => navigator::select_focused(self),
            input_router::AppCommand::GoHome => navigator::go_home(self),
            input_router::AppCommand::GoBack => navigator::go_back_or_emit(self),
            input_router::AppCommand::PttPress => navigator::handle_ptt_press(self),
            input_router::AppCommand::PttRelease => navigator::handle_ptt_release(self),
        }
        if self.active_screen != previous_screen {
            self.pending_wheel_roll = None;
        }
        navigator::clamp_focus(self);
        self.dirty.input = true;
        self.dirty.focus = true;
    }

    pub(crate) fn wake_home_from_ambient(&mut self, now_ms: u64) -> bool {
        if self.active_screen != UiScreen::Hub || self.home_mode != HomeMode::Ambient {
            return false;
        }

        self.last_input_ms = Some(now_ms);
        self.home_mode = HomeMode::Idle;
        self.dirty.input = true;
        self.dirty.focus = true;
        true
    }

    pub fn advance_home_state(&mut self, now_ms: u64) {
        let last_input_ms = *self.last_input_ms.get_or_insert(now_ms);
        if self.active_screen != UiScreen::Hub {
            return;
        }

        let idle_ms = now_ms.saturating_sub(last_input_ms);
        let next = match self.home_mode {
            HomeMode::Focused if idle_ms >= 8_000 => Some(HomeMode::Idle),
            HomeMode::Idle if idle_ms >= 30_000 => Some(HomeMode::Ambient),
            HomeMode::Idle | HomeMode::Focused | HomeMode::Ambient => None,
        };
        if let Some(next) = next {
            self.home_mode = next;
            self.dirty.focus = true;
        }
    }

    pub fn start_animation(&mut self, request: AnimationRequest, started_at_ms: u64) {
        let transition = animation::Transition::from_request(
            request,
            self.active_screen,
            self.focus_index,
            started_at_ms,
        );
        self.transitions
            .retain(|active| active.id != transition.id || active.target != transition.target);
        self.transitions.push(transition);
        self.dirty.animation = true;
    }

    pub fn advance_animations(&mut self, now_ms: u64) -> bool {
        let had_transitions = !self.transitions.is_empty();
        let had_wheel_roll = self.pending_wheel_roll.is_some();
        self.transitions
            .retain(|transition| !transition.is_complete(now_ms));
        let roll_completed = self.pending_wheel_roll.as_ref().is_some_and(|pending| {
            now_ms.saturating_sub(pending.timeline.started_ms)
                >= animation::presets::WHEEL_ROLL_DURATION_MS
        });
        if roll_completed {
            self.commit_pending_wheel_roll();
            navigator::clamp_focus(self);
            self.dirty.focus = true;
        }
        if had_transitions || had_wheel_roll {
            self.dirty.animation = true;
        }
        had_transitions || had_wheel_roll
    }

    pub fn mark_animation_frame(&mut self) {
        self.dirty.animation = true;
    }

    pub fn active_screen(&self) -> UiScreen {
        self.active_screen
    }

    pub fn mark_runtime_stalled(&mut self) {
        self.snapshot.overlay.loading = false;
        self.snapshot.overlay.error = "Lost runtime link".to_string();
        self.snapshot.overlay.message.clear();
        navigator::apply_runtime_preemption(self);
        self.dirty.overlay = true;
        self.dirty.navigation = true;
    }

    pub fn scene_graph(&self, now_ms: u64) -> SceneGraph {
        let defaults = defaults_for(self.active_screen);
        let mut active = components::screens::scene_for_screen(
            self.active_screen,
            &self.snapshot,
            self.focus_index,
            self.selected_playlist.as_ref(),
            self.selected_contact.as_ref(),
            defaults,
        );
        active.id = SceneId::with_route_key(self.active_screen, self.active_route_key());
        active.id.generation = active.id.generation.wrapping_add(self.scene_revision);
        active.timelines.extend(
            self.transitions
                .iter()
                .map(|transition| transition.timeline()),
        );
        if let Some(pending) = self
            .pending_wheel_roll
            .as_ref()
            .filter(|pending| pending.screen == self.active_screen)
        {
            active.timelines.push(pending.timeline.clone());
        }
        let mut chrome = components::screens::chrome::chrome_for_screen(
            self.active_screen,
            &self.snapshot,
            self.focus_index,
            self.selected_playlist.as_ref(),
            self.selected_contact.as_ref(),
            (self.active_screen == UiScreen::Hub && self.home_mode == HomeMode::Focused)
                .then_some(self.focus_index),
            self.active_screen != UiScreen::Hub || self.home_mode != HomeMode::Ambient,
        );
        if self.status_bar_preview_enabled {
            chrome.status = status_bar_preview_status(now_ms);
            chrome.deck.visible = false;
        } else {
            chrome.status.time = current_status_time().1;
        }
        let hud = components::screens::chrome::hud_scene(chrome);
        let modal_stack = active.modal.clone().into_iter().collect();
        SceneGraph {
            hud,
            active,
            history: self
                .screen_stack
                .iter()
                .map(|entry| crate::scene::ScenePushFrame {
                    route: entry.screen,
                    params: crate::scene::RouteParams {
                        selected_id: entry.selected_id.clone(),
                    },
                    cached_state: scene_cache_entry(entry),
                })
                .collect(),
            modal_stack,
            global_clock: GlobalClock {
                started_ms: 0,
                now_ms,
            },
        }
    }

    pub fn frame_request(&self, now_ms: u64) -> Option<FrameRequest> {
        self.dirty.any().then(|| FrameRequest {
            scene_graph: self.scene_graph(now_ms),
            dirty_region: self.dirty.render_region(self.active_screen),
        })
    }

    pub fn active_title(&self) -> String {
        components::screens::chrome::chrome_for_screen(
            self.active_screen,
            &self.snapshot,
            self.focus_index,
            self.selected_playlist.as_ref(),
            self.selected_contact.as_ref(),
            (self.active_screen == UiScreen::Hub && self.home_mode == HomeMode::Focused)
                .then_some(self.focus_index),
            self.active_screen != UiScreen::Hub || self.home_mode != HomeMode::Ambient,
        )
        .title
    }

    pub fn mark_clean(&mut self) {
        self.dirty = DirtyState::default();
    }

    pub fn take_intents(&mut self) -> Vec<UiIntent> {
        std::mem::take(&mut self.intents)
    }

    pub fn wants_ptt_passthrough(&self) -> bool {
        navigator::wants_ptt_passthrough(self)
    }

    fn active_route_key(&self) -> Option<&str> {
        match self.active_screen {
            UiScreen::PlaylistTracks => self
                .selected_playlist
                .as_ref()
                .map(|playlist| playlist.id.as_str()),
            UiScreen::TalkContact | UiScreen::VoiceNote => self
                .selected_contact
                .as_ref()
                .map(|contact| contact.id.as_str()),
            _ => None,
        }
    }

    fn begin_wheel_roll(&mut self, now_ms: u64) -> bool {
        let Some(item_count) = self.wheel_item_count() else {
            return false;
        };
        let timeline = match self.active_screen {
            UiScreen::Talk | UiScreen::TalkContact => {
                animation::presets::contact_wheel_roll(item_count, 0, now_ms)
            }
            UiScreen::Playlists | UiScreen::PlaylistTracks | UiScreen::RecentTracks => {
                animation::presets::media_wheel_roll(item_count, 0, now_ms)
            }
            _ => None,
        };
        let Some(timeline) = timeline else {
            return false;
        };

        let source_focus = self.focus_index;
        navigator::advance_focus(self);
        let target_focus = self.focus_index;
        // Keep the old focus painted while its three semantic slots roll.
        // The target becomes authoritative when the 180 ms timeline completes.
        self.focus_index = source_focus;
        if target_focus == source_focus {
            return false;
        }

        self.pending_wheel_roll = Some(super::state::PendingWheelRoll {
            screen: self.active_screen,
            target_focus,
            timeline,
        });
        true
    }

    fn commit_pending_wheel_roll(&mut self) {
        let Some(pending) = self.pending_wheel_roll.take() else {
            return;
        };
        if pending.screen == self.active_screen {
            self.focus_index = pending.target_focus;
            // Wheel timelines write transient transform and opacity styles to
            // native LVGL actors. Retire that actor generation when the
            // semantic focus commits so the next frame is rebuilt from the
            // static scene model instead of retaining the timeline's terminal
            // styles.
            self.scene_revision = self.scene_revision.wrapping_add(1);
            self.dirty.focus = true;
        }
    }

    fn abort_pending_wheel_roll(&mut self) {
        if self.pending_wheel_roll.take().is_none() {
            return;
        }

        // Animation tracks mutate native LVGL transform and opacity styles. A
        // list replacement makes those actors ambiguous, so force a new scene
        // generation and let reconciliation rebuild every wheel slot cleanly.
        self.scene_revision = self.scene_revision.wrapping_add(1);
        self.dirty.focus = true;
    }

    fn pending_wheel_identity(&self) -> Option<WheelIdentity> {
        let pending = self.pending_wheel_roll.as_ref()?;
        Some(WheelIdentity {
            screen: pending.screen,
            route_key: self.active_route_key().map(str::to_owned),
            item_ids: self.wheel_item_ids(pending.screen)?,
        })
    }

    fn reconcile_pending_wheel_roll(&mut self, before: Option<WheelIdentity>) {
        let Some(before) = before else {
            return;
        };
        if self.pending_wheel_roll.is_none() {
            return;
        }
        if self.active_screen != before.screen {
            self.pending_wheel_roll = None;
            return;
        }

        let after = WheelIdentity {
            screen: self.active_screen,
            route_key: self.active_route_key().map(str::to_owned),
            item_ids: self.wheel_item_ids(self.active_screen).unwrap_or_default(),
        };
        if after != before {
            self.abort_pending_wheel_roll();
        }
    }

    fn wheel_item_count(&self) -> Option<usize> {
        self.wheel_item_ids(self.active_screen).map(|ids| ids.len())
    }

    fn wheel_item_ids(&self, screen: UiScreen) -> Option<Vec<String>> {
        if screen == UiScreen::TalkContact {
            return Some(
                super::options::talk_contact_actions(
                    &self.snapshot,
                    self.selected_contact.as_ref(),
                )
                .into_iter()
                .map(|action| action.kind.to_string())
                .collect(),
            );
        }
        let items = match screen {
            UiScreen::Playlists => &self.snapshot.music.playlists,
            UiScreen::PlaylistTracks => self
                .selected_playlist
                .as_ref()
                .and_then(|playlist| self.snapshot.music.playlist_tracks.get(&playlist.id))
                .map_or(&[][..], Vec::as_slice),
            UiScreen::RecentTracks => &self.snapshot.music.recent_tracks,
            UiScreen::Talk => &self.snapshot.call.contacts,
            _ => return None,
        };
        Some(items.iter().map(|item| item.id.clone()).collect())
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct WheelIdentity {
    screen: UiScreen,
    route_key: Option<String>,
    item_ids: Vec<String>,
}

fn scene_cache_entry(entry: &HistoryEntry) -> crate::scene::SceneCacheEntry {
    match crate::router::route_for(entry.screen).persistence {
        crate::router::Persistence::Ephemeral => crate::scene::SceneCacheEntry::Discarded,
        crate::router::Persistence::KeepAlive | crate::router::Persistence::Singleton => {
            crate::scene::SceneCacheEntry::Retained {
                actor_state: crate::scene::ActorState {
                    focus_index: entry.focus_index,
                },
            }
        }
    }
}

const STATUS_BAR_PREVIEW_STAGE_MS: u64 = 5_000;
const STATUS_BAR_PREVIEW_STAGE_COUNT: u8 = 6;

fn current_status_time() -> (i64, String) {
    let now = OffsetDateTime::now_local().unwrap_or_else(|_| OffsetDateTime::now_utc());
    (
        now.unix_timestamp() / 60,
        format!("{:02}:{:02}", now.hour(), now.minute()),
    )
}

fn status_bar_preview_stage(now_ms: u64) -> u8 {
    ((now_ms / STATUS_BAR_PREVIEW_STAGE_MS) % u64::from(STATUS_BAR_PREVIEW_STAGE_COUNT)) as u8
}

fn status_bar_preview_status(now_ms: u64) -> HudStatus {
    let stage = status_bar_preview_stage(now_ms);
    let (kind, connected, strength, gps_has_fix, voip_registered, percent, charging, label) =
        match stage {
            0 => (
                HudConnectivityKind::Unknown,
                false,
                0,
                false,
                false,
                0,
                false,
                "S0 OFF",
            ),
            1 => (
                HudConnectivityKind::Cellular,
                true,
                1,
                false,
                false,
                25,
                false,
                "S1 25",
            ),
            2 => (
                HudConnectivityKind::Cellular,
                true,
                2,
                true,
                false,
                50,
                false,
                "S2 50",
            ),
            3 => (
                HudConnectivityKind::Cellular,
                true,
                3,
                true,
                true,
                75,
                false,
                "S3 75",
            ),
            4 => (
                HudConnectivityKind::Cellular,
                true,
                4,
                true,
                true,
                100,
                false,
                "S4 100",
            ),
            _ => (
                HudConnectivityKind::Wifi,
                true,
                4,
                true,
                true,
                100,
                true,
                "S5 CHG",
            ),
        };

    HudStatus {
        time: label.to_string(),
        connectivity: HudConnectivity {
            kind,
            connected,
            strength,
        },
        gps_has_fix,
        voip_registered,
        battery: HudBattery {
            percent,
            charging,
            available: true,
        },
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::engine::flatten;
    use crate::scene::roles;
    use yoyopod_protocol::ui::{
        CallIntent, ContactAction, ListItemSnapshot, MusicIntent, PlaylistTrackAction, VoiceIntent,
        VoiceRecipientAction,
    };

    fn contact(id: &str, title: &str) -> ListItemSnapshot {
        let initial = title
            .chars()
            .find(|character| character.is_alphanumeric())
            .unwrap_or('?');
        ListItemSnapshot::new(id, title, "", format!("mono:{initial}"))
    }

    fn count_visible_role(element: &crate::engine::Element, role: &'static str) -> usize {
        usize::from(element.role == Some(role) && element.props.visible != Some(false))
            + element
                .children
                .iter()
                .map(|child| count_visible_role(child, role))
                .sum::<usize>()
    }

    fn find_role<'a>(
        element: &'a crate::engine::Element,
        role: &'static str,
    ) -> Option<&'a crate::engine::Element> {
        if element.role == Some(role) {
            return Some(element);
        }
        element
            .children
            .iter()
            .find_map(|child| find_role(child, role))
    }

    #[test]
    fn status_bar_preview_cycles_every_contract_state() {
        let stages = (0..STATUS_BAR_PREVIEW_STAGE_COUNT)
            .map(|stage| status_bar_preview_status(u64::from(stage) * STATUS_BAR_PREVIEW_STAGE_MS))
            .collect::<Vec<_>>();

        assert_eq!(stages[0].time, "S0 OFF");
        assert!(!stages[0].connectivity.connected);
        assert_eq!(stages[0].battery.percent, 0);

        assert_eq!(stages[1].connectivity.kind, HudConnectivityKind::Cellular);
        assert_eq!(stages[1].connectivity.strength, 1);
        assert_eq!(stages[1].battery.percent, 25);

        assert!(stages[2].gps_has_fix);
        assert!(!stages[2].voip_registered);
        assert_eq!(stages[2].battery.percent, 50);

        assert!(stages[3].voip_registered);
        assert_eq!(stages[3].connectivity.strength, 3);
        assert_eq!(stages[3].battery.percent, 75);

        assert_eq!(stages[4].connectivity.strength, 4);
        assert_eq!(stages[4].battery.percent, 100);
        assert!(!stages[4].battery.charging);

        assert_eq!(stages[5].connectivity.kind, HudConnectivityKind::Wifi);
        assert!(stages[5].battery.charging);
        assert_eq!(stages[5].time, "S5 CHG");
    }

    #[test]
    fn status_bar_preview_isolated_slice_hides_the_deck() {
        let runtime = UiRuntime::with_status_bar_preview(true);
        let graph = flatten::flatten(&runtime.scene_graph(0));

        assert_eq!(count_visible_role(&graph, roles::DECK_BAR), 0);
    }

    #[test]
    fn home_lands_idle_then_focuses_first_deck_slot() {
        let mut runtime = UiRuntime::default();
        let idle = flatten::flatten(&runtime.scene_graph(0));
        assert_eq!(runtime.home_mode, HomeMode::Idle);
        assert_eq!(count_visible_role(&idle, roles::DECK_PILL), 0);

        runtime.handle_input(InputAction::Advance, 100);
        let focused = flatten::flatten(&runtime.scene_graph(100));
        assert_eq!(runtime.home_mode, HomeMode::Focused);
        assert_eq!(runtime.focus_index, 0);
        assert_eq!(count_visible_role(&focused, roles::DECK_PILL), 1);
    }

    #[test]
    fn home_focus_wraps_and_select_opens_category() {
        let mut runtime = UiRuntime::default();
        for now_ms in [100, 200, 300, 400, 500] {
            runtime.handle_input(InputAction::Advance, now_ms);
        }
        assert_eq!(runtime.focus_index, 0);

        runtime.handle_input(InputAction::Select, 600);
        assert_eq!(runtime.active_screen, UiScreen::Listen);
    }

    #[test]
    fn home_opens_talk_and_talk_selects_the_focused_contact_directly() {
        let mama = contact("sip:mama@example.test", "Mama");
        let papa = contact("sip:papa@example.test", "Papa");
        let mut runtime = UiRuntime::default();
        runtime.snapshot.call.contacts = vec![mama, papa.clone()];

        runtime.handle_input(InputAction::Advance, 100);
        runtime.handle_input(InputAction::Advance, 200);
        runtime.handle_input(InputAction::Select, 300);
        assert_eq!(runtime.active_screen, UiScreen::Talk);
        assert_eq!(runtime.focus_index, 0);

        runtime.handle_input(InputAction::Advance, 400);
        runtime.advance_animations(580);
        assert_eq!(runtime.focus_index, 1);

        runtime.handle_input(InputAction::Select, 600);
        assert_eq!(runtime.active_screen, UiScreen::TalkContact);
        assert_eq!(runtime.selected_contact, Some(papa));
        assert!(runtime.take_intents().is_empty());
    }

    #[test]
    fn home_action_pops_entire_stack_and_clears_focus() {
        let mut runtime = UiRuntime::default();
        runtime.handle_input(InputAction::Advance, 100);
        runtime.handle_input(InputAction::Select, 200);
        runtime.handle_input(InputAction::Select, 300);
        assert_ne!(runtime.active_screen, UiScreen::Hub);

        runtime.handle_input(InputAction::Home, 400);
        assert_eq!(runtime.active_screen, UiScreen::Hub);
        assert!(runtime.screen_stack.is_empty());
        assert_eq!(runtime.home_mode, HomeMode::Idle);
    }

    #[test]
    fn now_playing_rolls_and_activates_all_transport_targets() {
        let mut runtime = UiRuntime::default();
        runtime.active_screen = UiScreen::Listen;
        runtime.focus_index = 2;

        runtime.handle_input(InputAction::Select, 50);
        assert_eq!(runtime.active_screen, UiScreen::NowPlaying);
        assert_eq!(runtime.focus_index, 1);
        assert_eq!(
            runtime.take_intents(),
            vec![UiIntent::Music(MusicIntent::ShuffleAll)]
        );

        runtime.handle_input(InputAction::Select, 100);
        assert_eq!(
            runtime.take_intents(),
            vec![UiIntent::Music(MusicIntent::PlayPause)]
        );

        runtime.handle_input(InputAction::Advance, 200);
        assert_eq!(runtime.focus_index, 2);
        runtime.handle_input(InputAction::Select, 300);
        assert_eq!(
            runtime.take_intents(),
            vec![UiIntent::Music(MusicIntent::NextTrack)]
        );

        runtime.handle_input(InputAction::Advance, 400);
        assert_eq!(runtime.focus_index, 0);
        runtime.handle_input(InputAction::Select, 500);
        assert_eq!(
            runtime.take_intents(),
            vec![UiIntent::Music(MusicIntent::PreviousTrack)]
        );
    }

    #[test]
    fn playlist_wheel_opens_tracks_and_plays_the_focused_track() {
        let playlist = ListItemSnapshot::new(
            "/music/Open Classics.m3u",
            "Open Classics",
            "2 tracks",
            "playlist",
        );
        let tracks = vec![
            ListItemSnapshot::new("/music/1.mp3", "Chaconne", "5:32", "track"),
            ListItemSnapshot::new("/music/2.mp3", "March", "4:18", "track"),
        ];
        let mut runtime = UiRuntime::default();
        runtime.snapshot.music.playlists = vec![playlist.clone()];
        runtime
            .snapshot
            .music
            .playlist_tracks
            .insert(playlist.id.clone(), tracks);
        runtime.active_screen = UiScreen::Listen;

        runtime.handle_input(InputAction::Select, 100);
        assert_eq!(runtime.active_screen, UiScreen::Playlists);
        runtime.handle_input(InputAction::Select, 200);
        assert_eq!(runtime.active_screen, UiScreen::PlaylistTracks);
        assert_eq!(runtime.selected_playlist, Some(playlist.clone()));
        assert!(runtime.take_intents().is_empty());

        runtime.handle_input(InputAction::Advance, 300);
        assert_eq!(runtime.focus_index, 0);
        assert_eq!(
            runtime
                .pending_wheel_roll
                .as_ref()
                .map(|pending| pending.timeline.tracks.len()),
            Some(6)
        );
        runtime.advance_animations(479);
        assert_eq!(runtime.focus_index, 0);
        runtime.advance_animations(480);
        assert_eq!(runtime.focus_index, 1);
        assert!(runtime.pending_wheel_roll.is_none());

        runtime.handle_input(InputAction::Select, 500);
        assert_eq!(runtime.active_screen, UiScreen::NowPlaying);
        assert_eq!(
            runtime.take_intents(),
            vec![UiIntent::Music(MusicIntent::PlayPlaylistTrack(
                PlaylistTrackAction {
                    playlist_path: playlist.id,
                    track_uri: "/music/2.mp3".to_string(),
                    track_index: 1,
                }
            ))]
        );
    }

    #[test]
    fn three_item_media_wheel_runs_the_approved_roll_before_committing_focus() {
        let mut runtime = UiRuntime::default();
        runtime.snapshot.music.recent_tracks = vec![
            ListItemSnapshot::new("/music/1.mp3", "Chaconne", "5:32", "track"),
            ListItemSnapshot::new("/music/2.mp3", "Intermezzo", "4:18", "track"),
            ListItemSnapshot::new("/music/3.mp3", "March", "3:07", "track"),
        ];
        runtime.active_screen = UiScreen::RecentTracks;
        runtime.focus_index = 0;
        runtime.mark_clean();

        runtime.handle_input(InputAction::Advance, 1_000);
        assert_eq!(runtime.focus_index, 0);
        let pending = runtime
            .pending_wheel_roll
            .as_ref()
            .expect("media advance should schedule a roll");
        assert_eq!(pending.target_focus, 1);
        assert_eq!(pending.timeline.tracks.len(), 9);
        assert!(runtime
            .scene_graph(1_000)
            .active
            .timelines
            .iter()
            .any(|timeline| timeline.id == animation::presets::MEDIA_WHEEL_ROLL_TIMELINE_ID));

        runtime.advance_animations(1_179);
        assert_eq!(runtime.focus_index, 0);
        runtime.mark_clean();
        runtime.advance_animations(1_180);
        assert_eq!(runtime.focus_index, 1);
        assert!(runtime.pending_wheel_roll.is_none());
        assert!(runtime.dirty.focus);
    }

    #[test]
    fn contact_wheel_rolls_for_180_ms_before_committing_focus() {
        let mut runtime = UiRuntime::default();
        runtime.snapshot.call.contacts = vec![
            contact("sip:mama@example.test", "Mama"),
            contact("sip:papa@example.test", "Papa"),
            contact("sip:grandma@example.test", "Grandma"),
        ];
        runtime.active_screen = UiScreen::Talk;

        runtime.handle_input(InputAction::Advance, 1_000);
        assert_eq!(runtime.focus_index, 0);
        let pending = runtime
            .pending_wheel_roll
            .as_ref()
            .expect("contact advance should schedule a roll");
        assert_eq!(pending.target_focus, 1);
        assert_eq!(pending.timeline.tracks.len(), 9);
        assert_eq!(
            pending.timeline.id,
            animation::presets::CONTACT_WHEEL_ROLL_TIMELINE_ID
        );

        runtime.advance_animations(1_179);
        assert_eq!(runtime.focus_index, 0);
        runtime.advance_animations(1_180);
        assert_eq!(runtime.focus_index, 1);
        assert!(runtime.pending_wheel_roll.is_none());
    }

    #[test]
    fn talk_contact_action_wheel_rolls_then_keeps_recording_on_the_same_route() {
        let mama = contact("sip:mama@example.test", "Mama");
        let mut runtime = UiRuntime::default();
        runtime.snapshot.call.contacts = vec![mama.clone()];
        runtime.selected_contact = Some(mama);
        runtime.active_screen = UiScreen::TalkContact;

        runtime.handle_input(InputAction::Advance, 1_000);
        assert_eq!(runtime.focus_index, 0);
        let pending = runtime
            .pending_wheel_roll
            .as_ref()
            .expect("TalkContact advance should schedule the shared wheel roll");
        assert_eq!(pending.target_focus, 1);
        assert_eq!(
            pending.timeline.id,
            animation::presets::CONTACT_WHEEL_ROLL_TIMELINE_ID
        );

        let animated_generation = runtime.scene_graph(1_100).active.id.generation;
        runtime.advance_animations(1_180);
        assert_eq!(runtime.focus_index, 1);
        assert_eq!(
            runtime.scene_graph(1_180).active.id.generation,
            animated_generation.wrapping_add(1),
            "committing a wheel roll must retire actors carrying native timeline styles"
        );
        runtime.handle_input(InputAction::Select, 1_200);
        assert_eq!(runtime.active_screen, UiScreen::TalkContact);
        assert!(runtime.take_intents().is_empty());
    }

    #[test]
    fn talk_contact_ptt_is_focused_only_and_release_stops_the_live_capture() {
        let mama = contact("sip:mama@example.test", "Mama");
        let mut runtime = UiRuntime::default();
        runtime.snapshot.call.contacts = vec![mama.clone()];
        runtime.selected_contact = Some(mama);
        runtime.active_screen = UiScreen::TalkContact;

        assert!(!runtime.wants_ptt_passthrough());
        runtime.focus_index = 1;
        assert!(runtime.wants_ptt_passthrough());

        runtime.handle_input(InputAction::PttPress, 400);
        assert_eq!(
            runtime.take_intents(),
            vec![UiIntent::Voice(VoiceIntent::CaptureStartAndSend(
                VoiceRecipientAction {
                    id: "sip:mama@example.test".to_string(),
                    recipient_address: "sip:mama@example.test".to_string(),
                    recipient_name: "Mama".to_string(),
                    file_path: String::new(),
                }
            ))]
        );

        runtime.snapshot.voice.phase = "recording".to_string();
        runtime.snapshot.voice.capture_in_flight = true;
        runtime.snapshot.voice.ptt_active = true;
        runtime.snapshot.voice.recording_duration_ms = 7_420;
        runtime.snapshot.voice.capture_level_permille = 618;
        assert!(runtime.wants_ptt_passthrough());
        let held = flatten::flatten(&runtime.scene_graph(1_000));
        assert_eq!(
            find_role(&held, roles::DECK_BAR).and_then(|deck| deck.props.opacity),
            Some(140)
        );
        assert_eq!(
            find_role(&held, roles::RECORDING_TIMER).and_then(|timer| timer.props.text.as_deref()),
            Some("0:07")
        );
        assert_eq!(
            find_role(&held, roles::VOICE_METER_LEVEL).and_then(|meter| meter.props.progress),
            Some(618)
        );
        runtime.handle_input(InputAction::PttRelease, 1_400);
        assert_eq!(
            runtime.take_intents(),
            vec![UiIntent::Voice(VoiceIntent::CaptureStop)]
        );
    }

    #[test]
    fn talk_contact_call_action_still_emits_the_selected_contact() {
        let mama = contact("sip:mama@example.test", "Mama");
        let mut runtime = UiRuntime::default();
        runtime.snapshot.call.contacts = vec![mama.clone()];
        runtime.selected_contact = Some(mama);
        runtime.active_screen = UiScreen::TalkContact;

        runtime.handle_input(InputAction::Select, 100);

        assert_eq!(
            runtime.take_intents(),
            vec![UiIntent::Call(CallIntent::Start(ContactAction {
                id: "sip:mama@example.test".to_string(),
                name: "Mama".to_string(),
                sip_address: String::new(),
                uri: String::new(),
            }))]
        );
    }

    #[test]
    fn call_status_patch_preserves_a_contact_roll_when_contact_ids_are_stable() {
        let mut runtime = UiRuntime::default();
        runtime.snapshot.call.contacts = vec![
            contact("sip:mama@example.test", "Mama"),
            contact("sip:papa@example.test", "Papa"),
            contact("sip:grandma@example.test", "Grandma"),
        ];
        runtime.active_screen = UiScreen::Talk;

        runtime.handle_input(InputAction::Advance, 1_000);
        let mut call = runtime.snapshot.call.clone();
        call.registered = true;
        runtime.apply_patch(RuntimeSnapshotPatch::Call(call));

        let pending = runtime
            .pending_wheel_roll
            .as_ref()
            .expect("stable contact identity must preserve the active roll");
        assert_eq!(pending.target_focus, 1);
        assert_eq!(pending.timeline.started_ms, 1_000);
        runtime.advance_animations(1_180);
        assert_eq!(runtime.focus_index, 1);
    }

    #[test]
    fn contact_replacement_aborts_a_contact_roll_and_resets_wheel_actors() {
        let mut runtime = UiRuntime::default();
        runtime.snapshot.call.contacts = vec![
            contact("sip:mama@example.test", "Mama"),
            contact("sip:papa@example.test", "Papa"),
            contact("sip:grandma@example.test", "Grandma"),
        ];
        runtime.active_screen = UiScreen::Talk;
        runtime.handle_input(InputAction::Advance, 1_000);
        let previous_revision = runtime.scene_revision;

        let mut call = runtime.snapshot.call.clone();
        call.contacts.pop();
        runtime.apply_patch(RuntimeSnapshotPatch::Call(call));

        assert!(runtime.pending_wheel_roll.is_none());
        assert_eq!(runtime.focus_index, 0);
        assert_eq!(runtime.scene_revision, previous_revision.wrapping_add(1));
        assert!(runtime.dirty.focus);
    }

    #[test]
    fn playback_progress_patch_does_not_interrupt_media_wheel_roll() {
        let mut runtime = UiRuntime::default();
        runtime.snapshot.music.recent_tracks = vec![
            ListItemSnapshot::new("/music/1.mp3", "Chaconne", "5:32", "track"),
            ListItemSnapshot::new("/music/2.mp3", "Intermezzo", "4:18", "track"),
            ListItemSnapshot::new("/music/3.mp3", "March", "3:07", "track"),
        ];
        runtime.active_screen = UiScreen::RecentTracks;

        runtime.handle_input(InputAction::Advance, 1_000);
        let mut music = runtime.snapshot.music.clone();
        music.progress_permille = 375;
        music.elapsed_text = "1:23".to_string();
        runtime.apply_patch(RuntimeSnapshotPatch::Music(music));

        assert_eq!(runtime.focus_index, 0);
        let pending = runtime
            .pending_wheel_roll
            .as_ref()
            .expect("stable media identity must preserve the active roll");
        assert_eq!(pending.target_focus, 1);
        assert_eq!(pending.timeline.started_ms, 1_000);

        runtime.advance_animations(1_179);
        assert_eq!(runtime.focus_index, 0);
        runtime.advance_animations(1_180);
        assert_eq!(runtime.focus_index, 1);
        assert!(runtime.pending_wheel_roll.is_none());
    }

    #[test]
    fn media_list_replacement_aborts_roll_and_rebuilds_transformed_slots() {
        let mut runtime = UiRuntime::default();
        runtime.snapshot.music.recent_tracks = vec![
            ListItemSnapshot::new("/music/1.mp3", "Chaconne", "5:32", "track"),
            ListItemSnapshot::new("/music/2.mp3", "Intermezzo", "4:18", "track"),
            ListItemSnapshot::new("/music/3.mp3", "March", "3:07", "track"),
        ];
        runtime.active_screen = UiScreen::RecentTracks;
        let mut engine = crate::engine::Engine::default();
        engine.render(&runtime.scene_graph(900), 900);

        runtime.handle_input(InputAction::Advance, 1_000);
        engine.render(&runtime.scene_graph(1_090), 1_090);
        let previous_revision = runtime.scene_revision;
        let mut music = runtime.snapshot.music.clone();
        music.recent_tracks.pop();
        runtime.apply_patch(RuntimeSnapshotPatch::Music(music));

        assert!(runtime.pending_wheel_roll.is_none());
        assert_eq!(runtime.focus_index, 0);
        assert_eq!(runtime.scene_revision, previous_revision.wrapping_add(1));
        assert!(runtime.dirty.focus);
        let rebuilt = engine.render(&runtime.scene_graph(1_100), 1_100);
        assert!(rebuilt.iter().any(|mutation| matches!(
            mutation,
            crate::engine::Mutation::Create {
                role: Some(role),
                ..
            } if *role == roles::MEDIA_WHEEL_FOCUS
        )));
    }

    #[test]
    fn media_wheel_roll_emits_motion_then_refreshes_the_slot_roots() {
        let mut runtime = UiRuntime::default();
        runtime.snapshot.music.recent_tracks = vec![
            ListItemSnapshot::new("/music/1.mp3", "Chaconne", "5:32", "track"),
            ListItemSnapshot::new("/music/2.mp3", "Intermezzo", "4:18", "track"),
            ListItemSnapshot::new("/music/3.mp3", "March", "3:07", "track"),
        ];
        runtime.active_screen = UiScreen::RecentTracks;
        let mut engine = crate::engine::Engine::default();
        engine.render(&runtime.scene_graph(900), 900);

        runtime.handle_input(InputAction::Advance, 1_000);
        engine.render(&runtime.scene_graph(1_000), 1_000);
        runtime.advance_animations(1_090);
        let moving = engine.render(&runtime.scene_graph(1_090), 1_090);
        assert!(moving.iter().any(|mutation| matches!(
            mutation,
            crate::engine::Mutation::Update {
                prop: crate::engine::PropChange::OffsetY(value),
                ..
            } if *value < 0
        )));
        assert!(moving.iter().any(|mutation| matches!(
            mutation,
            crate::engine::Mutation::Update {
                prop: crate::engine::PropChange::ScalePermille(value),
                ..
            } if *value != 1_000
        )));

        runtime.advance_animations(1_180);
        let committed = engine.render(&runtime.scene_graph(1_180), 1_180);
        assert!(committed.iter().any(|mutation| matches!(
            mutation,
            crate::engine::Mutation::Create {
                role: Some(role),
                ..
            } if *role == roles::MEDIA_WHEEL_FOCUS
        )));
        assert_eq!(runtime.focus_index, 1);
    }

    #[test]
    fn home_focus_decays_then_enters_and_wakes_from_ambient() {
        let mut runtime = UiRuntime::default();
        runtime.handle_input(InputAction::Advance, 100);
        runtime.advance_home_state(8_100);
        assert_eq!(runtime.home_mode, HomeMode::Idle);

        runtime.advance_home_state(30_100);
        assert_eq!(runtime.home_mode, HomeMode::Ambient);
        let ambient = flatten::flatten(&runtime.scene_graph(30_100));
        assert_eq!(count_visible_role(&ambient, roles::DECK_BAR), 0);

        runtime.handle_input(InputAction::Advance, 30_200);
        assert_eq!(runtime.home_mode, HomeMode::Idle);
        let awake = flatten::flatten(&runtime.scene_graph(30_200));
        assert_eq!(count_visible_role(&awake, roles::DECK_BAR), 1);
    }

    #[test]
    fn ambient_wake_emits_a_visible_deck_mutation() {
        let mut runtime = UiRuntime::default();
        let mut engine = crate::engine::Engine::default();
        runtime.advance_home_state(0);
        engine.render(&runtime.scene_graph(0), 0);

        runtime.advance_home_state(30_000);
        let ambient_graph = runtime.scene_graph(30_000);
        let hidden = engine.render(&ambient_graph, 30_000).to_vec();
        let deck_node = hidden
            .iter()
            .find_map(|mutation| match mutation {
                crate::engine::Mutation::Update {
                    node,
                    prop: crate::engine::PropChange::Visible(false),
                } => Some(*node),
                _ => None,
            })
            .expect("ambient transition must hide the deck");

        assert!(runtime.wake_home_from_ambient(30_100));
        let awake_graph = runtime.scene_graph(30_100);
        let awake = engine.render(&awake_graph, 30_100);
        assert!(awake.iter().any(|mutation| matches!(
            mutation,
            crate::engine::Mutation::Update {
                node,
                prop: crate::engine::PropChange::Visible(true),
            } if *node == deck_node
        )));
    }
}
