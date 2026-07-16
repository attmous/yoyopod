use yoyopod_protocol::ui::{
    AnimationRequest, InputAction, RuntimeSnapshot, RuntimeSnapshotPatch, UiIntent,
};

use crate::animation;
use crate::components;
use crate::router::history::HistoryEntry;
use crate::scene::{defaults_for, GlobalClock, SceneGraph, SceneId};
use crate::DirtyRegion;

use super::state::{DirtyState, HomeMode, UiRuntime};
use super::{input_router, navigator, snapshot, UiScreen};

#[derive(Debug, Clone)]
pub struct FrameRequest {
    pub scene_graph: SceneGraph,
    pub dirty_region: Option<DirtyRegion>,
}

impl UiRuntime {
    pub fn apply_snapshot(&mut self, snapshot: RuntimeSnapshot) {
        let change = snapshot::replace_full(&mut self.snapshot, snapshot);
        self.full_snapshots += 1;
        navigator::apply_app_state_route(self, &change.previous_app_state, &change.app_state);
        navigator::apply_runtime_preemption(self);
        navigator::clamp_focus(self);
        self.dirty.mark_full();
    }

    pub fn apply_patch(&mut self, patch: RuntimeSnapshotPatch) {
        let domain = patch.domain();
        let previous_screen = self.active_screen;
        let previous_focus = self.focus_index;
        let previous_stack_len = self.screen_stack.len();
        let change = snapshot::apply_patch(&mut self.snapshot, patch);
        *self.patches_per_domain.entry(domain).or_insert(0) += 1;
        navigator::apply_app_state_route(self, &change.previous_app_state, &change.app_state);
        navigator::apply_runtime_preemption(self);
        navigator::clamp_focus(self);
        self.dirty.mark_patch_domain(change.domain);
        if self.active_screen != previous_screen || self.screen_stack.len() != previous_stack_len {
            self.dirty.navigation = true;
        }
        if self.focus_index != previous_focus {
            self.dirty.focus = true;
        }
    }

    pub fn handle_input(&mut self, action: InputAction, now_ms: u64) {
        self.last_input_ms = Some(now_ms);
        if self.active_screen == UiScreen::Hub && self.home_mode == HomeMode::Ambient {
            self.home_mode = HomeMode::Idle;
            self.dirty.input = true;
            self.dirty.focus = true;
            return;
        }
        let route_state = input_router::InputRouteState {
            active_screen: self.active_screen,
            voice_note_phase: self.voice_note_phase(),
        };
        match input_router::route(action, &route_state) {
            input_router::AppCommand::AdvanceFocus => navigator::advance_focus(self),
            input_router::AppCommand::SelectFocused => navigator::select_focused(self),
            input_router::AppCommand::GoHome => navigator::go_home(self),
            input_router::AppCommand::GoBack => navigator::go_back_or_emit(self),
            input_router::AppCommand::PttPress => navigator::handle_ptt_press(self),
            input_router::AppCommand::PttRelease => navigator::handle_ptt_release(self),
        }
        navigator::clamp_focus(self);
        self.dirty.input = true;
        self.dirty.focus = true;
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
        self.transitions
            .retain(|transition| !transition.is_complete(now_ms));
        if had_transitions {
            self.dirty.animation = true;
        }
        had_transitions
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
            self.selected_contact.as_ref(),
            defaults,
        );
        active.id = SceneId::with_route_key(self.active_screen, self.active_route_key());
        active.timelines.extend(
            self.transitions
                .iter()
                .map(|transition| transition.timeline()),
        );
        let mut chrome = components::screens::chrome::chrome_for_screen(
            self.active_screen,
            &self.snapshot,
            self.focus_index,
            self.selected_contact.as_ref(),
            (self.active_screen == UiScreen::Hub && self.home_mode == HomeMode::Focused)
                .then_some(self.focus_index),
            self.active_screen != UiScreen::Hub || self.home_mode != HomeMode::Ambient,
        );
        chrome.status.time = elapsed_time_label(now_ms);
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
            UiScreen::TalkContact | UiScreen::VoiceNote => self
                .selected_contact
                .as_ref()
                .map(|contact| contact.id.as_str()),
            _ => None,
        }
    }
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

fn elapsed_time_label(now_ms: u64) -> String {
    let total_seconds = now_ms / 1_000;
    let minutes = (total_seconds / 60).min(99);
    let seconds = total_seconds % 60;
    format!("{minutes:02}:{seconds:02}")
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::engine::flatten;
    use crate::scene::roles;

    fn count_visible_role(element: &crate::engine::Element, role: &'static str) -> usize {
        usize::from(element.role == Some(role) && element.props.visible != Some(false))
            + element
                .children
                .iter()
                .map(|child| count_visible_role(child, role))
                .sum::<usize>()
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
    }
}
