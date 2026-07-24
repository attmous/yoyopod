use time::{Month, OffsetDateTime, Weekday};
use yoyopod_protocol::ui::{
    AnimationRequest, InputAction, RuntimeSnapshot, RuntimeSnapshotPatch, SystemIntent, UiEvent,
    UiFocusChanged, UiIntent,
};

use crate::animation;
use crate::components;
use crate::components::widgets::CompanionVariant;
use crate::router::history::HistoryEntry;
use crate::scene::{
    defaults_for, GlobalClock, HudBattery, HudConnectivity, HudConnectivityKind, HudStatus,
    SceneGraph, SceneId,
};
use crate::theme::ColorScheme;
use crate::DirtyRegion;

use super::state::{DirtyState, HomeMode, SystemOverlayPreview, UiRuntime};
use super::{input_router, navigator, snapshot, UiScreen};

const RUNTIME_LINK_ERROR: &str = "Lost runtime link";
const WATCH_ORBIT_DIRTY_REGION: DirtyRegion = DirtyRegion {
    x: 2,
    y: 22,
    w: 236,
    h: 236,
};

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
        let previous_playing = self.snapshot.voice.playback_active;
        let previous_file_path = self.snapshot.voice.playback_file_path.clone();
        let previous_companion = CompanionVariant::from_setting(&self.snapshot.settings.companion);
        let mut change = snapshot::replace_full(&mut self.snapshot, snapshot);
        self.enforce_system_overlay_preview();
        self.enforce_companion_preview();
        self.reset_companion_phase_if_changed(previous_companion);
        if self.system_overlay_preview.is_some() || self.companion_preview.is_some() {
            change.app_state = self.snapshot.app_state;
        }
        self.reconcile_system_overlay_snapshot();
        self.full_snapshots += 1;
        navigator::apply_app_state_route(self, &change.previous_app_state, &change.app_state);
        navigator::apply_runtime_preemption(self);
        navigator::reconcile_replay_snapshot(self, previous_playing, &previous_file_path);
        navigator::clamp_focus(self);
        self.reconcile_pending_wheel_roll(pending_identity);
        self.dirty.mark_full();
        self.refresh_focus_accessibility();
    }

    pub fn apply_patch(&mut self, patch: RuntimeSnapshotPatch) {
        let domain = patch.domain();
        let pending_identity = self.pending_wheel_identity();
        let previous_screen = self.active_screen;
        let previous_focus = self.focus_index;
        let previous_stack_len = self.screen_stack.len();
        let previous_playing = self.snapshot.voice.playback_active;
        let previous_file_path = self.snapshot.voice.playback_file_path.clone();
        let previous_companion = CompanionVariant::from_setting(&self.snapshot.settings.companion);
        let mut change = snapshot::apply_patch(&mut self.snapshot, patch);
        self.enforce_system_overlay_preview();
        self.enforce_companion_preview();
        self.reset_companion_phase_if_changed(previous_companion);
        if self.system_overlay_preview.is_some() || self.companion_preview.is_some() {
            change.app_state = self.snapshot.app_state;
        }
        self.reconcile_system_overlay_snapshot();
        *self.patches_per_domain.entry(domain).or_insert(0) += 1;
        navigator::apply_app_state_route(self, &change.previous_app_state, &change.app_state);
        navigator::apply_runtime_preemption(self);
        navigator::reconcile_replay_snapshot(self, previous_playing, &previous_file_path);
        navigator::clamp_focus(self);
        self.reconcile_pending_wheel_roll(pending_identity);
        self.dirty.mark_patch_domain(change.domain);
        if self.active_screen != previous_screen || self.screen_stack.len() != previous_stack_len {
            self.dirty.navigation = true;
        }
        if self.focus_index != previous_focus {
            self.dirty.focus = true;
        }
        self.refresh_focus_accessibility();
    }

    pub fn handle_input(&mut self, action: InputAction, now_ms: u64) {
        if self.wake_home_from_ambient(now_ms) {
            return;
        }
        self.last_input_ms = Some(now_ms);
        if crate::router::is_overlay_screen(self.active_screen) {
            match action {
                InputAction::Home => {
                    self.dismiss_system_overlay();
                    navigator::go_home(self);
                }
                InputAction::Select
                    if self.active_screen == UiScreen::Error && self.snapshot.overlay.retryable =>
                {
                    self.retry_system_overlay(true);
                }
                InputAction::Advance
                | InputAction::Select
                | InputAction::Back
                | InputAction::PttPress
                | InputAction::PttRelease => {}
            }
            self.dirty.input = true;
            self.dirty.focus = true;
            self.refresh_focus_accessibility();
            return;
        }
        if self.pending_wheel_roll.is_some() {
            if action == InputAction::Advance {
                self.dirty.input = true;
                return;
            }
            self.commit_pending_wheel_roll();
        }
        if self.active_screen == UiScreen::Ask
            && action == InputAction::PttPress
            && self.snapshot.voice.ask_unavailable
        {
            self.clear_local_ask_failure();
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
        self.refresh_focus_accessibility();
    }

    pub(crate) fn wake_home_from_ambient(&mut self, now_ms: u64) -> bool {
        if self.active_screen != UiScreen::Hub || self.home_mode != HomeMode::Ambient {
            return false;
        }

        self.last_input_ms = Some(now_ms);
        self.home_mode = HomeMode::Focused;
        self.focus_index = 0;
        self.scene_revision = self.scene_revision.wrapping_add(1);
        self.dirty.input = true;
        self.dirty.focus = true;
        self.dirty.navigation = true;
        self.refresh_focus_accessibility();
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
            if next == HomeMode::Ambient {
                self.scene_revision = self.scene_revision.wrapping_add(1);
                self.dirty.navigation = true;
            }
            self.home_mode = next;
            self.dirty.focus = true;
            self.refresh_focus_accessibility();
        }
    }

    pub fn advance_ask_state(&mut self, now_ms: u64) -> bool {
        if self.active_screen != UiScreen::Ask || !self.snapshot.voice.ask_unavailable {
            self.ask_offline_started_ms = None;
            return false;
        }

        let started_ms = *self.ask_offline_started_ms.get_or_insert(now_ms);
        if now_ms.saturating_sub(started_ms) < ASK_FAILURE_VISIBLE_MS {
            return false;
        }

        self.clear_local_ask_failure();
        self.intents.push(UiIntent::Voice(
            yoyopod_protocol::ui::VoiceIntent::AskCancel,
        ));
        true
    }

    fn clear_local_ask_failure(&mut self) {
        self.ask_offline_started_ms = None;
        self.snapshot.voice.ask_unavailable = false;
        self.snapshot.voice.phase = "idle".to_string();
        self.snapshot.voice.headline = "Ask".to_string();
        self.snapshot.voice.body = "Ask me anything...".to_string();
        self.snapshot.voice.capture_in_flight = false;
        self.snapshot.voice.ptt_active = false;
        self.snapshot.voice.playback_active = false;
        self.snapshot.voice.playback_paused = false;
        self.dirty.voice = true;
    }

    pub fn advance_system_overlay(&mut self, now_ms: u64) -> bool {
        if let Some(preview) = self.system_overlay_preview {
            self.enforce_system_overlay_preview();
            let previous_step = self.system_overlay.spinner_step;
            self.system_overlay.loading_visible = preview == SystemOverlayPreview::Loading;
            if preview == SystemOverlayPreview::Loading {
                self.system_overlay.spinner_step = ((now_ms / 80) % 8) as u8;
            }
            navigator::apply_runtime_preemption(self);
            let changed = self.system_overlay.spinner_step != previous_step;
            if changed {
                self.dirty.animation = true;
                self.dirty.overlay = true;
            }
            return changed;
        }
        if !self.snapshot.overlay.error.trim().is_empty() {
            self.system_overlay.reset_loading();
            let signature = self.system_overlay_signature();
            if self.system_overlay.error_signature != signature {
                self.system_overlay.reset_error();
                self.system_overlay.error_signature = signature;
            }
            let entered_ms = *self.system_overlay.error_started_ms.get_or_insert(now_ms);
            let elapsed_ms = now_ms.saturating_sub(entered_ms);
            let mut changed = false;
            if !self.system_overlay.error_announced {
                self.intents
                    .push(UiIntent::System(if self.snapshot.overlay.retryable {
                        SystemIntent::AnnounceRecoverableError
                    } else {
                        SystemIntent::AnnounceUnrecoverableError
                    }));
                self.system_overlay.error_announced = true;
                changed = true;
            }
            if self.snapshot.overlay.retryable
                && self.snapshot.overlay.retry_count == 0
                && elapsed_ms >= 4_000
            {
                self.retry_system_overlay(false);
                return true;
            }
            if !self.snapshot.overlay.retryable
                && elapsed_ms >= 60_000
                && !self.system_overlay.unrecoverable_repeat_announced
            {
                self.intents
                    .push(UiIntent::System(SystemIntent::AnnounceUnrecoverableError));
                self.system_overlay.unrecoverable_repeat_announced = true;
                changed = true;
            }
            navigator::apply_runtime_preemption(self);
            return changed;
        }

        self.system_overlay.reset_error();
        if self.snapshot.overlay.loading {
            let started_ms = *self.system_overlay.loading_started_ms.get_or_insert(now_ms);
            let elapsed_ms = now_ms.saturating_sub(started_ms);
            let mut changed = false;
            if elapsed_ms >= 300 && !self.system_overlay.loading_visible {
                self.system_overlay.loading_visible = true;
                changed = true;
            }
            if elapsed_ms >= 2_000 && !self.system_overlay.loading_announced {
                self.intents
                    .push(UiIntent::System(SystemIntent::AnnounceWait));
                self.system_overlay.loading_announced = true;
                changed = true;
            }
            if elapsed_ms >= 8_000 {
                self.intents
                    .push(UiIntent::System(SystemIntent::LoadingTimedOut));
                self.snapshot.overlay.loading = false;
                self.snapshot.overlay.error = "operation_timeout".to_string();
                self.snapshot.overlay.code = "operation_timeout".to_string();
                self.snapshot.overlay.retryable = true;
                self.system_overlay.reset();
                navigator::apply_runtime_preemption(self);
                self.dirty.overlay = true;
                self.dirty.navigation = true;
                return true;
            }
            if self.system_overlay.loading_visible {
                let spinner_step = ((elapsed_ms / 80) % 8) as u8;
                if spinner_step != self.system_overlay.spinner_step {
                    self.system_overlay.spinner_step = spinner_step;
                    self.dirty.animation = true;
                    changed = true;
                }
            }
            if changed {
                self.dirty.overlay = true;
            }
            navigator::apply_runtime_preemption(self);
            return changed;
        }

        let was_active = crate::router::is_overlay_screen(self.active_screen);
        self.system_overlay.reset();
        navigator::apply_runtime_preemption(self);
        if was_active {
            self.dirty.overlay = true;
            self.dirty.navigation = true;
        }
        was_active
    }

    pub(crate) fn note_system_overlay_snapshot_received(&mut self, now_ms: u64) {
        if self.snapshot.overlay.loading && self.system_overlay.loading_started_ms.is_none() {
            self.system_overlay.loading_started_ms = Some(now_ms);
        }
        if !self.snapshot.overlay.error.trim().is_empty()
            && self.system_overlay.error_started_ms.is_none()
        {
            self.system_overlay.error_started_ms = Some(now_ms);
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
        self.dirty.animation_full_frame = true;
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
            self.refresh_focus_accessibility();
        }
        if had_transitions || had_wheel_roll {
            self.dirty.animation = true;
        }
        if had_transitions {
            self.dirty.animation_full_frame = true;
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
        self.snapshot.overlay.error = RUNTIME_LINK_ERROR.to_string();
        self.snapshot.overlay.message.clear();
        self.snapshot.overlay.retryable = false;
        self.snapshot.overlay.code = "runtime_stalled".to_string();
        self.snapshot.overlay.source = "ui.watchdog".to_string();
        self.snapshot.overlay.retry_count = 0;
        self.reconcile_system_overlay_snapshot();
        navigator::apply_runtime_preemption(self);
        self.dirty.overlay = true;
        self.dirty.navigation = true;
        self.refresh_focus_accessibility();
    }

    pub fn mark_runtime_connected(&mut self) -> bool {
        if self.snapshot.overlay.error != RUNTIME_LINK_ERROR {
            return false;
        }

        self.snapshot.overlay.error.clear();
        self.snapshot.overlay.code.clear();
        self.snapshot.overlay.source.clear();
        self.snapshot.overlay.retryable = false;
        self.snapshot.overlay.retry_count = 0;
        self.reconcile_system_overlay_snapshot();
        navigator::apply_runtime_preemption(self);
        navigator::clamp_focus(self);
        self.dirty.overlay = true;
        self.dirty.navigation = true;
        self.refresh_focus_accessibility();
        true
    }

    pub fn scene_graph(&self, now_ms: u64) -> SceneGraph {
        let (rendered_screen, rendered_focus) = self.rendered_screen_and_focus();
        let watch_face_visible = self.active_screen == UiScreen::Hub
            && rendered_screen == UiScreen::Hub
            && self.home_mode == HomeMode::Ambient;
        let mut active = if watch_face_visible {
            let (date, time) = current_watch_face_text();
            components::screens::watch_face::scene(&self.snapshot, date, time)
        } else {
            let defaults = defaults_for(rendered_screen);
            components::screens::scene_for_screen(
                rendered_screen,
                &self.snapshot,
                rendered_focus,
                self.selected_playlist.as_ref(),
                self.selected_contact.as_ref(),
                self.replay_index,
                defaults,
            )
        };
        active.id = SceneId::with_route_key(rendered_screen, self.route_key(rendered_screen));
        active.id.generation = active.id.generation.wrapping_add(self.scene_revision);
        active.timelines.extend(
            self.transitions
                .iter()
                .map(|transition| transition.timeline()),
        );
        if let Some(pending) = self
            .pending_wheel_roll
            .as_ref()
            .filter(|pending| pending.screen == rendered_screen)
        {
            active.timelines.push(pending.timeline.clone());
        }
        let hud = if watch_face_visible {
            crate::scene::HudScene::new(
                crate::engine::Element::new(
                    crate::ElementKind::Container,
                    Some(crate::scene::roles::HUD),
                )
                .key(crate::engine::Key::Static("ambient_hud"))
                .visible(false),
            )
        } else {
            let mut chrome = components::screens::chrome::chrome_for_screen(
                rendered_screen,
                &self.snapshot,
                rendered_focus,
                self.selected_playlist.as_ref(),
                self.selected_contact.as_ref(),
                (rendered_screen == UiScreen::Hub && self.home_mode == HomeMode::Focused)
                    .then_some(rendered_focus),
                true,
            );
            if crate::router::is_overlay_screen(self.active_screen) {
                chrome.status_opacity = 255;
                chrome.deck.opacity = 140;
            }
            if self.status_bar_preview_enabled {
                chrome.status = status_bar_preview_status(now_ms);
                chrome.deck.visible = false;
            } else {
                chrome.status.time = current_status_time().1;
            }
            components::screens::chrome::hud_scene(chrome)
        };
        let modal_stack = match self.active_screen {
            UiScreen::Loading => vec![crate::scene::Modal::Loading {
                spinner_step: self.system_overlay.spinner_step,
            }],
            UiScreen::Error => vec![crate::scene::Modal::Error {
                retryable: self.snapshot.overlay.retryable,
            }],
            _ => active.modal.clone().into_iter().collect(),
        };
        SceneGraph {
            color_scheme: self.theme_preview.unwrap_or_else(|| {
                ColorScheme::resolve(&self.snapshot.settings.theme, current_local_hour())
            }),
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
        self.dirty.any().then(|| {
            let scene_graph = self.scene_graph(now_ms);
            let orbit_is_only_animation = scene_graph.active.timelines.len() == 1
                && scene_graph.active.timelines[0].id
                    == animation::presets::WATCH_ORBIT_TIMELINE_ID;
            let dirty_region =
                if self.active_screen == UiScreen::Hub && self.home_mode == HomeMode::Ambient {
                    (self.dirty.animation_only() && orbit_is_only_animation)
                        .then_some(WATCH_ORBIT_DIRTY_REGION)
                } else {
                    self.dirty.render_region(self.active_screen)
                };
            FrameRequest {
                scene_graph,
                dirty_region,
            }
        })
    }

    pub fn active_title(&self) -> String {
        let (screen, focus) = self.rendered_screen_and_focus();
        components::screens::chrome::chrome_for_screen(
            screen,
            &self.snapshot,
            focus,
            self.selected_playlist.as_ref(),
            self.selected_contact.as_ref(),
            (screen == UiScreen::Hub && self.home_mode == HomeMode::Focused).then_some(focus),
            screen != UiScreen::Hub || self.home_mode != HomeMode::Ambient,
        )
        .title
    }

    pub fn mark_clean(&mut self) {
        self.dirty = DirtyState::default();
    }

    pub fn take_intents(&mut self) -> Vec<UiIntent> {
        std::mem::take(&mut self.intents)
    }

    pub fn take_accessibility_events(&mut self) -> Vec<UiEvent> {
        std::mem::take(&mut self.accessibility_events)
    }

    pub(crate) fn refresh_focus_accessibility(&mut self) {
        let descriptor = super::accessibility::focused_item(self);
        if !self.snapshot.settings.speak_names || descriptor.is_none() {
            if self.last_focus_identity.take().is_some() {
                self.accessibility_events.push(UiEvent::FocusCleared);
            }
            return;
        }

        let descriptor = descriptor.expect("focus descriptor checked above");
        if descriptor.label.trim().is_empty() {
            return;
        }
        let identity = format!(
            "{}|{}|{}|{}|{}",
            self.active_screen.as_str(),
            self.route_key(self.active_screen).unwrap_or_default(),
            self.focus_index,
            descriptor.key,
            descriptor.label,
        );
        if self.last_focus_identity.as_deref() == Some(identity.as_str()) {
            return;
        }

        self.focus_prompt_sequence = self.focus_prompt_sequence.wrapping_add(1);
        self.last_focus_identity = Some(identity);
        self.accessibility_events
            .push(UiEvent::FocusChanged(UiFocusChanged::new(
                format!("ui-focus-{}", self.focus_prompt_sequence),
                descriptor.label,
            )));
    }

    pub fn wants_ptt_passthrough(&self) -> bool {
        navigator::wants_ptt_passthrough(self)
    }

    fn route_key(&self, screen: UiScreen) -> Option<&str> {
        match screen {
            UiScreen::PlaylistTracks => self
                .selected_playlist
                .as_ref()
                .map(|playlist| playlist.id.as_str()),
            UiScreen::TalkContact | UiScreen::Replay | UiScreen::VoiceNote => self
                .selected_contact
                .as_ref()
                .map(|contact| contact.id.as_str()),
            _ => None,
        }
    }

    fn rendered_screen_and_focus(&self) -> (UiScreen, usize) {
        if !crate::router::is_overlay_screen(self.active_screen) {
            return (self.active_screen, self.focus_index);
        }
        self.screen_stack
            .iter()
            .rev()
            .find(|entry| !crate::router::is_overlay_screen(entry.screen))
            .map(|entry| (entry.screen, entry.focus_index))
            .unwrap_or((UiScreen::Hub, 0))
    }

    fn reconcile_system_overlay_snapshot(&mut self) {
        if !self.snapshot.overlay.loading {
            self.system_overlay.reset_loading();
        }
        if self.snapshot.overlay.error.trim().is_empty() {
            self.system_overlay.reset_error();
        } else {
            let signature = self.system_overlay_signature();
            if self.system_overlay.error_signature != signature {
                self.system_overlay.reset_error();
                self.system_overlay.error_signature = signature;
            }
        }
    }

    pub(crate) fn enable_system_overlay_preview(&mut self, preview: SystemOverlayPreview) {
        self.screen_stack.clear();
        self.active_screen = UiScreen::Ask;
        self.focus_index = 0;
        self.system_overlay_preview = Some(preview);
        self.enforce_system_overlay_preview();
        self.reconcile_system_overlay_snapshot();
        if preview == SystemOverlayPreview::Loading {
            self.system_overlay.loading_visible = true;
        }
        navigator::apply_runtime_preemption(self);
        self.dirty.overlay = true;
        self.dirty.navigation = true;
    }

    pub(crate) fn enable_companion_preview(&mut self, preview: CompanionVariant) {
        let previous_companion = CompanionVariant::from_setting(&self.snapshot.settings.companion);
        self.screen_stack.clear();
        self.active_screen = UiScreen::Hub;
        self.focus_index = 0;
        self.home_mode = HomeMode::Idle;
        self.companion_preview = Some(preview);
        self.enforce_companion_preview();
        self.reset_companion_phase_if_changed(previous_companion);
        self.dirty.settings = true;
        self.dirty.navigation = true;
    }

    pub(crate) fn enable_theme_preview(&mut self, preview: ColorScheme) {
        self.theme_preview = Some(preview);
        self.dirty.settings = true;
    }

    fn enforce_companion_preview(&mut self) {
        let Some(preview) = self.companion_preview else {
            return;
        };
        self.snapshot.app_state = UiScreen::Hub;
        self.snapshot.settings.companion = preview.name().to_string();
    }

    pub(crate) fn apply_companion_choice(&mut self, value: &str) {
        let previous = CompanionVariant::from_setting(&self.snapshot.settings.companion);
        let selected = CompanionVariant::from_setting(value);
        self.snapshot.settings.companion = selected.name().to_string();
        self.reset_companion_phase_if_changed(previous);
        self.dirty.settings = true;
    }

    fn reset_companion_phase_if_changed(&mut self, previous: CompanionVariant) {
        let current = CompanionVariant::from_setting(&self.snapshot.settings.companion);
        if current == previous {
            return;
        }
        self.scene_revision = self.scene_revision.wrapping_add(1);
        self.dirty.animation = true;
    }

    fn enforce_system_overlay_preview(&mut self) {
        let Some(preview) = self.system_overlay_preview else {
            return;
        };
        self.snapshot.app_state = UiScreen::Ask;
        self.snapshot.overlay.loading = preview == SystemOverlayPreview::Loading;
        self.snapshot.overlay.error = match preview {
            SystemOverlayPreview::Loading => String::new(),
            SystemOverlayPreview::RecoverableError => "preview_recoverable".to_string(),
            SystemOverlayPreview::UnrecoverableError => "preview_unrecoverable".to_string(),
        };
        self.snapshot.overlay.message.clear();
        self.snapshot.overlay.retryable = preview == SystemOverlayPreview::RecoverableError;
        self.snapshot.overlay.code = match preview {
            SystemOverlayPreview::Loading => String::new(),
            SystemOverlayPreview::RecoverableError => "preview_recoverable".to_string(),
            SystemOverlayPreview::UnrecoverableError => "preview_unrecoverable".to_string(),
        };
        self.snapshot.overlay.source = "ui.preview".to_string();
        self.snapshot.overlay.retry_count =
            u8::from(preview == SystemOverlayPreview::RecoverableError);
    }

    fn system_overlay_signature(&self) -> String {
        format!(
            "{}|{}|{}|{}",
            self.snapshot.overlay.code,
            self.snapshot.overlay.source,
            self.snapshot.overlay.retryable,
            self.snapshot.overlay.retry_count
        )
    }

    fn retry_system_overlay(&mut self, announce: bool) {
        if announce {
            self.intents
                .push(UiIntent::System(SystemIntent::AnnounceRetry));
        }
        self.intents
            .push(UiIntent::System(SystemIntent::RetryOverlay));
        self.clear_local_system_overlay();
    }

    fn dismiss_system_overlay(&mut self) {
        self.intents
            .push(UiIntent::System(SystemIntent::DismissOverlay));
        self.clear_local_system_overlay();
    }

    fn clear_local_system_overlay(&mut self) {
        self.snapshot.overlay.loading = false;
        self.snapshot.overlay.error.clear();
        self.snapshot.overlay.message.clear();
        self.snapshot.overlay.retryable = false;
        self.snapshot.overlay.code.clear();
        self.snapshot.overlay.source.clear();
        self.snapshot.overlay.retry_count = 0;
        self.system_overlay.reset();
        navigator::apply_runtime_preemption(self);
        self.dirty.overlay = true;
        self.dirty.navigation = true;
    }

    fn begin_wheel_roll(&mut self, now_ms: u64) -> bool {
        let Some(item_count) = self.wheel_item_count() else {
            return false;
        };
        let timeline = match self.active_screen {
            UiScreen::Talk | UiScreen::TalkContact => {
                animation::presets::contact_wheel_roll(item_count, 0, now_ms)
            }
            UiScreen::Setup
            | UiScreen::SetupCompanion
            | UiScreen::SetupContacts
            | UiScreen::SetupTheme => animation::presets::setup_wheel_roll(item_count, 0, now_ms),
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
            route_key: self.route_key(self.active_screen).map(str::to_owned),
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
            route_key: self.route_key(self.active_screen).map(str::to_owned),
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
        let static_items: &[&str] = match screen {
            UiScreen::Setup => &[
                "volume",
                "companion",
                "contacts",
                "theme",
                "speak_names",
                "about",
            ],
            UiScreen::SetupCompanion => &["blob", "owl", "cat", "bunny", "robot"],
            UiScreen::SetupTheme => &["light", "dark", "auto"],
            _ => &[],
        };
        if !static_items.is_empty() {
            return Some(
                static_items
                    .iter()
                    .map(|value| (*value).to_string())
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
            UiScreen::SetupContacts => &self.snapshot.call.contacts,
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
const ASK_FAILURE_VISIBLE_MS: u64 = 4_000;

fn current_status_time() -> (i64, String) {
    let now = current_local_datetime();
    (
        now.unix_timestamp() / 60,
        format!("{:02}:{:02}", now.hour(), now.minute()),
    )
}

fn current_watch_face_text() -> (String, String) {
    watch_face_text(current_local_datetime())
}

fn watch_face_text(now: OffsetDateTime) -> (String, String) {
    let weekday = match now.weekday() {
        Weekday::Monday => "MON",
        Weekday::Tuesday => "TUE",
        Weekday::Wednesday => "WED",
        Weekday::Thursday => "THU",
        Weekday::Friday => "FRI",
        Weekday::Saturday => "SAT",
        Weekday::Sunday => "SUN",
    };
    let month = match now.month() {
        Month::January => "JAN",
        Month::February => "FEB",
        Month::March => "MAR",
        Month::April => "APR",
        Month::May => "MAY",
        Month::June => "JUN",
        Month::July => "JUL",
        Month::August => "AUG",
        Month::September => "SEP",
        Month::October => "OCT",
        Month::November => "NOV",
        Month::December => "DEC",
    };
    (
        format!("{weekday} {:02} {month}", now.day()),
        format!("{:02}:{:02}", now.hour(), now.minute()),
    )
}

fn current_local_datetime() -> OffsetDateTime {
    OffsetDateTime::now_local().unwrap_or_else(|_| OffsetDateTime::now_utc())
}

fn current_local_hour() -> u8 {
    current_local_datetime().hour()
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
    use crate::application::intents;
    use crate::engine::flatten;
    use crate::scene::roles;
    use yoyopod_protocol::ui::{
        AnimationEasing, AnimationProperty, AnimationTarget, CallIntent, ContactAction,
        ListItemSnapshot, MusicIntent, OverlayRuntimeSnapshot, PlaylistTrackAction, SettingsIntent,
        SettingsRuntimeSnapshot, SystemIntent, UiEvent, UiFocusChanged, VoiceIntent,
        VoiceNoteSummarySnapshot, VoiceRecipientAction,
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
    fn focused_home_card_emits_one_spoken_label_per_focus_change() {
        let mut runtime = UiRuntime::default();

        runtime.handle_input(InputAction::Advance, 100);
        assert_eq!(
            runtime.take_accessibility_events(),
            vec![UiEvent::FocusChanged(UiFocusChanged::new(
                "ui-focus-1",
                "Listen"
            ))]
        );

        runtime.handle_input(InputAction::Advance, 200);
        assert_eq!(
            runtime.take_accessibility_events(),
            vec![UiEvent::FocusChanged(UiFocusChanged::new(
                "ui-focus-2",
                "Talk"
            ))]
        );

        runtime.refresh_focus_accessibility();
        assert!(runtime.take_accessibility_events().is_empty());
    }

    #[test]
    fn wheel_speaks_only_after_the_visible_roll_commits() {
        let mut runtime = UiRuntime {
            active_screen: UiScreen::Playlists,
            ..UiRuntime::default()
        };
        runtime.snapshot.music.playlists = vec![
            ListItemSnapshot::new("morning", "Morning songs", "", "playlist"),
            ListItemSnapshot::new("bedtime", "Bedtime songs", "", "playlist"),
        ];
        runtime.refresh_focus_accessibility();
        runtime.take_accessibility_events();

        runtime.handle_input(InputAction::Advance, 100);
        assert!(runtime.take_accessibility_events().is_empty());

        runtime.advance_animations(280);
        assert_eq!(
            runtime.take_accessibility_events(),
            vec![UiEvent::FocusChanged(UiFocusChanged::new(
                "ui-focus-2",
                "Bedtime songs"
            ))]
        );
    }

    #[test]
    fn speak_names_toggle_cancels_and_restores_the_current_prompt() {
        let mut runtime = UiRuntime {
            active_screen: UiScreen::Setup,
            focus_index: 4,
            ..UiRuntime::default()
        };
        runtime.refresh_focus_accessibility();
        runtime.take_accessibility_events();

        runtime.apply_patch(RuntimeSnapshotPatch::Settings(SettingsRuntimeSnapshot {
            speak_names: false,
            ..runtime.snapshot.settings.clone()
        }));
        assert_eq!(
            runtime.take_accessibility_events(),
            vec![UiEvent::FocusCleared]
        );

        runtime.apply_patch(RuntimeSnapshotPatch::Settings(SettingsRuntimeSnapshot {
            speak_names: true,
            ..runtime.snapshot.settings.clone()
        }));
        assert_eq!(
            runtime.take_accessibility_events(),
            vec![UiEvent::FocusChanged(UiFocusChanged::new(
                "ui-focus-2",
                "Speak names, on"
            ))]
        );
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
    fn system_overlay_preview_survives_runtime_snapshots_for_hardware_review() {
        let mut runtime = UiRuntime::default();
        runtime.enable_system_overlay_preview(SystemOverlayPreview::Loading);
        runtime.apply_snapshot(RuntimeSnapshot::default());
        runtime.advance_system_overlay(60_000);

        assert_eq!(runtime.active_screen, UiScreen::Loading);
        assert!(runtime.snapshot.overlay.loading);
        assert!(runtime.snapshot.overlay.error.is_empty());
        assert!(runtime.take_intents().is_empty());
    }

    #[test]
    fn companion_preview_survives_runtime_snapshots_for_hardware_review() {
        let mut runtime = UiRuntime::default();
        runtime.enable_companion_preview(CompanionVariant::Robot);
        runtime.apply_snapshot(RuntimeSnapshot::default());

        assert_eq!(runtime.active_screen, UiScreen::Hub);
        assert_eq!(runtime.snapshot.settings.companion, "Robot");
        let graph = flatten::flatten(&runtime.scene_graph(0));
        let sprite = find_role(&graph, roles::COMPANION_SPRITE).unwrap();
        assert_eq!(sprite.props.icon_key.as_deref(), Some("companion_robot"));
    }

    #[test]
    fn companion_change_rebuilds_the_home_actor_and_resets_breathe_phase() {
        let mut runtime = UiRuntime::default();
        let previous_revision = runtime.scene_revision;
        runtime.apply_companion_choice("Owl");

        assert_eq!(runtime.snapshot.settings.companion, "Owl");
        assert_eq!(runtime.scene_revision, previous_revision.wrapping_add(1));
        assert!(runtime.dirty.animation);
    }

    #[test]
    fn system_error_is_a_true_overlay_with_safe_copy_and_live_chrome() {
        let mut runtime = UiRuntime {
            active_screen: UiScreen::Ask,
            ..UiRuntime::default()
        };
        runtime.apply_patch(RuntimeSnapshotPatch::Overlay(OverlayRuntimeSnapshot {
            error: "raw backend exception must never render".to_string(),
            retryable: true,
            code: "voice_failed".to_string(),
            source: "voice.ask".to_string(),
            ..OverlayRuntimeSnapshot::default()
        }));

        assert_eq!(runtime.active_screen, UiScreen::Error);
        let graph = runtime.scene_graph(0);
        assert_eq!(graph.active.id.screen, UiScreen::Ask);
        let flattened = flatten::flatten(&graph);
        assert_eq!(count_visible_role(&flattened, roles::SYS_SCRIM), 1);
        assert_eq!(count_visible_role(&flattened, roles::SYS_BADGE), 1);
        assert_eq!(count_visible_role(&flattened, roles::SYS_MSG), 1);
        assert_eq!(
            find_role(&flattened, roles::SCENE_DECKS)
                .unwrap()
                .props
                .opacity,
            Some(0)
        );
        assert_eq!(
            find_role(&flattened, roles::SCENE_BACKDROP)
                .unwrap()
                .props
                .opacity,
            None
        );
        assert_eq!(
            find_role(&flattened, roles::STATUS_BAR)
                .unwrap()
                .props
                .opacity,
            Some(255)
        );
        assert_eq!(
            find_role(&flattened, roles::DECK_BAR)
                .unwrap()
                .props
                .opacity,
            Some(140)
        );
        let message = find_role(&flattened, roles::SYS_MSG)
            .and_then(|element| element.props.text.as_deref())
            .unwrap();
        assert_eq!(message, "Oops, something went wrong.\nLet's try again!");
        assert!(!message.contains("backend"));
    }

    #[test]
    fn loading_debounces_animates_announces_and_escalates() {
        let mut runtime = UiRuntime::default();
        runtime.apply_patch(RuntimeSnapshotPatch::Overlay(OverlayRuntimeSnapshot {
            loading: true,
            source: "music.load_playlist".to_string(),
            ..OverlayRuntimeSnapshot::default()
        }));

        runtime.advance_system_overlay(1_000);
        runtime.advance_system_overlay(1_299);
        assert_eq!(runtime.active_screen, UiScreen::Hub);

        runtime.advance_system_overlay(1_300);
        assert_eq!(runtime.active_screen, UiScreen::Loading);
        let loading = flatten::flatten(&runtime.scene_graph(1_300));
        assert_eq!(count_visible_role(&loading, roles::SYS_SPINNER_DOT), 8);
        assert_eq!(count_visible_role(&loading, roles::SYS_MSG), 1);

        runtime.advance_system_overlay(3_000);
        assert_eq!(
            runtime.take_intents(),
            vec![UiIntent::System(SystemIntent::AnnounceWait)]
        );

        runtime.advance_system_overlay(9_000);
        assert_eq!(runtime.active_screen, UiScreen::Error);
        assert!(runtime.snapshot.overlay.retryable);
        assert_eq!(runtime.snapshot.overlay.code, "operation_timeout");
        assert_eq!(
            runtime.take_intents(),
            vec![UiIntent::System(SystemIntent::LoadingTimedOut)]
        );
    }

    #[test]
    fn recoverable_error_retries_manually_and_cannot_be_repushed_locally() {
        let mut runtime = UiRuntime::default();
        runtime.apply_patch(RuntimeSnapshotPatch::Overlay(OverlayRuntimeSnapshot {
            error: "worker_error".to_string(),
            retryable: true,
            code: "worker_media_error".to_string(),
            source: "music.play".to_string(),
            ..OverlayRuntimeSnapshot::default()
        }));

        runtime.handle_input(InputAction::Select, 100);

        assert_eq!(runtime.active_screen, UiScreen::Hub);
        assert!(runtime.snapshot.overlay.error.is_empty());
        assert_eq!(
            runtime.take_intents(),
            vec![
                UiIntent::System(SystemIntent::AnnounceRetry),
                UiIntent::System(SystemIntent::RetryOverlay),
            ]
        );
    }

    #[test]
    fn recoverable_error_auto_retries_only_the_first_failure() {
        let mut runtime = UiRuntime::default();
        runtime.apply_patch(RuntimeSnapshotPatch::Overlay(OverlayRuntimeSnapshot {
            error: "worker_error".to_string(),
            retryable: true,
            code: "worker_media_error".to_string(),
            source: "music.play".to_string(),
            ..OverlayRuntimeSnapshot::default()
        }));
        runtime.advance_system_overlay(0);
        runtime.take_intents();
        runtime.advance_system_overlay(4_000);
        assert_eq!(
            runtime.take_intents(),
            vec![UiIntent::System(SystemIntent::RetryOverlay)]
        );

        runtime.apply_patch(RuntimeSnapshotPatch::Overlay(OverlayRuntimeSnapshot {
            error: "worker_error".to_string(),
            retryable: true,
            code: "worker_media_error".to_string(),
            source: "music.play".to_string(),
            retry_count: 1,
            ..OverlayRuntimeSnapshot::default()
        }));
        runtime.advance_system_overlay(5_000);
        runtime.take_intents();
        runtime.advance_system_overlay(10_000);
        assert!(runtime.take_intents().is_empty());
        assert_eq!(runtime.active_screen, UiScreen::Error);
    }

    #[test]
    fn unrecoverable_error_consumes_select_and_long_press_goes_home() {
        let mut runtime = UiRuntime {
            active_screen: UiScreen::Talk,
            ..UiRuntime::default()
        };
        runtime.apply_patch(RuntimeSnapshotPatch::Overlay(OverlayRuntimeSnapshot {
            error: "hardware_fault".to_string(),
            retryable: false,
            code: "power_hardware_fault".to_string(),
            source: "power.refresh".to_string(),
            ..OverlayRuntimeSnapshot::default()
        }));

        runtime.handle_input(InputAction::Select, 100);
        assert_eq!(runtime.active_screen, UiScreen::Error);
        assert!(runtime.take_intents().is_empty());

        runtime.handle_input(InputAction::Home, 500);
        assert_eq!(runtime.active_screen, UiScreen::Hub);
        assert_eq!(
            runtime.take_intents(),
            vec![UiIntent::System(SystemIntent::DismissOverlay)]
        );
    }

    #[test]
    fn runtime_link_recovery_clears_only_the_watchdog_error_and_restores_the_route() {
        let mut runtime = UiRuntime::default();
        runtime.active_screen = UiScreen::Talk;

        runtime.mark_runtime_stalled();
        assert_eq!(runtime.active_screen, UiScreen::Error);
        assert_eq!(runtime.snapshot.overlay.error, RUNTIME_LINK_ERROR);

        assert!(runtime.mark_runtime_connected());
        assert_eq!(runtime.active_screen, UiScreen::Talk);
        assert!(runtime.snapshot.overlay.error.is_empty());
        assert!(runtime.dirty.overlay);
        assert!(runtime.dirty.navigation);

        runtime.snapshot.overlay.error = "Call failed".to_string();
        runtime.active_screen = UiScreen::Error;
        assert!(!runtime.mark_runtime_connected());
        assert_eq!(runtime.active_screen, UiScreen::Error);
        assert_eq!(runtime.snapshot.overlay.error, "Call failed");
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
    fn setup_root_rolls_opens_volume_and_volume_steps_then_pops() {
        let mut runtime = UiRuntime::default();
        runtime.home_mode = HomeMode::Focused;
        runtime.focus_index = 3;
        runtime.handle_input(InputAction::Select, 100);
        assert_eq!(runtime.active_screen, UiScreen::Setup);

        runtime.handle_input(InputAction::Select, 200);
        assert_eq!(runtime.active_screen, UiScreen::SetupVolume);
        runtime.handle_input(InputAction::Advance, 300);
        assert_eq!(
            runtime.take_intents(),
            vec![UiIntent::Settings(SettingsIntent::VolumeStep)]
        );

        runtime.handle_input(InputAction::Select, 400);
        assert_eq!(runtime.active_screen, UiScreen::Setup);
        assert_eq!(runtime.focus_index, 0);
    }

    #[test]
    fn setup_root_roll_is_animated_and_speak_names_toggles_in_place() {
        let mut runtime = UiRuntime::default();
        runtime.active_screen = UiScreen::Setup;
        runtime.handle_input(InputAction::Advance, 100);
        assert_eq!(runtime.focus_index, 0);
        assert!(runtime.pending_wheel_roll.is_some());
        runtime.advance_animations(280);
        assert_eq!(runtime.focus_index, 1);

        runtime.focus_index = 4;
        runtime.handle_input(InputAction::Select, 300);
        assert_eq!(runtime.active_screen, UiScreen::Setup);
        assert_eq!(
            runtime.take_intents(),
            vec![UiIntent::Settings(SettingsIntent::SpeakNamesToggle)]
        );
    }

    #[test]
    fn setup_companion_selects_and_returns_home_while_theme_stays_open() {
        let mut companion = UiRuntime::default();
        companion.active_screen = UiScreen::SetupCompanion;
        companion.focus_index = 3;
        companion.handle_input(InputAction::Select, 100);
        assert_eq!(companion.active_screen, UiScreen::Hub);
        assert_eq!(companion.snapshot.settings.companion, "Bunny");
        assert_eq!(
            companion.take_intents(),
            vec![UiIntent::Settings(SettingsIntent::CompanionSet(
                "Bunny".to_string()
            ))]
        );

        let mut theme = UiRuntime::default();
        theme.active_screen = UiScreen::SetupTheme;
        theme.focus_index = 1;
        theme.handle_input(InputAction::Select, 100);
        assert_eq!(theme.active_screen, UiScreen::SetupTheme);
        assert_eq!(
            theme.take_intents(),
            vec![UiIntent::Settings(SettingsIntent::ThemeSet(
                "Dark".to_string()
            ))]
        );
    }

    #[test]
    fn theme_snapshot_selects_the_renderer_scheme() {
        let mut runtime = UiRuntime::default();
        runtime.apply_patch(RuntimeSnapshotPatch::Settings(SettingsRuntimeSnapshot {
            theme: "Dark".to_string(),
            ..SettingsRuntimeSnapshot::default()
        }));

        assert_eq!(
            runtime.scene_graph(100).color_scheme,
            crate::theme::ColorScheme::Dark
        );
    }

    #[test]
    fn theme_preview_stays_authoritative_during_runtime_snapshots() {
        let mut runtime = UiRuntime::default();
        runtime.enable_theme_preview(crate::theme::ColorScheme::Dark);
        runtime.apply_snapshot(RuntimeSnapshot::default());

        assert_eq!(
            runtime.scene_graph(100).color_scheme,
            crate::theme::ColorScheme::Dark
        );
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
    fn ask_captures_the_physical_hold_and_release_end_to_end() {
        let mut runtime = UiRuntime::default();
        runtime.active_screen = UiScreen::Ask;

        assert!(runtime.wants_ptt_passthrough());
        runtime.handle_input(InputAction::PttPress, 400);
        assert_eq!(
            runtime.take_intents(),
            vec![UiIntent::Voice(VoiceIntent::AskStart)]
        );

        runtime.snapshot.voice.phase = "listening".to_string();
        runtime.snapshot.voice.capture_in_flight = true;
        runtime.snapshot.voice.ptt_active = true;
        runtime.snapshot.voice.capture_level_permille = 720;
        let held = flatten::flatten(&runtime.scene_graph(1_000));
        assert_eq!(
            find_role(&held, roles::STATUS_BAR).and_then(|status| status.props.opacity),
            Some(140)
        );
        assert_eq!(
            find_role(&held, roles::DECK_BAR).and_then(|deck| deck.props.opacity),
            Some(140)
        );

        runtime.handle_input(InputAction::PttRelease, 1_400);
        assert_eq!(
            runtime.take_intents(),
            vec![UiIntent::Voice(VoiceIntent::AskStop)]
        );
    }

    #[test]
    fn ask_failure_returns_to_idle_after_four_seconds() {
        let mut runtime = UiRuntime::default();
        runtime.active_screen = UiScreen::Ask;
        runtime.snapshot.voice.ask_unavailable = true;
        runtime.snapshot.voice.phase = "offline".to_string();

        assert!(!runtime.advance_ask_state(1_000));
        assert!(!runtime.advance_ask_state(4_999));
        assert!(runtime.take_intents().is_empty());

        assert!(runtime.advance_ask_state(5_000));
        assert!(!runtime.snapshot.voice.ask_unavailable);
        assert_eq!(runtime.snapshot.voice.phase, "idle");
        assert_eq!(
            runtime.take_intents(),
            vec![UiIntent::Voice(VoiceIntent::AskCancel)]
        );
    }

    #[test]
    fn ptt_retries_immediately_during_an_ask_failure() {
        let mut runtime = UiRuntime::default();
        runtime.active_screen = UiScreen::Ask;
        runtime.snapshot.voice.ask_unavailable = true;
        runtime.snapshot.voice.phase = "offline".to_string();
        runtime.advance_ask_state(1_000);

        runtime.handle_input(InputAction::PttPress, 2_000);

        assert!(!runtime.snapshot.voice.ask_unavailable);
        assert!(runtime.ask_offline_started_ms.is_none());
        assert_eq!(
            runtime.take_intents(),
            vec![UiIntent::Voice(VoiceIntent::AskStart)]
        );
    }

    #[test]
    fn ask_double_press_cancels_thinking_or_answer_playback() {
        let mut runtime = UiRuntime::default();
        runtime.active_screen = UiScreen::Ask;
        runtime.snapshot.network.connected = true;
        runtime.snapshot.voice.phase = "thinking".to_string();
        runtime.handle_input(InputAction::Select, 100);
        assert_eq!(
            runtime.take_intents(),
            vec![UiIntent::Voice(VoiceIntent::AskCancel)]
        );

        runtime.snapshot.voice.phase = "reply".to_string();
        runtime.snapshot.voice.playback_active = true;
        runtime.handle_input(InputAction::Select, 200);
        assert_eq!(
            runtime.take_intents(),
            vec![UiIntent::Voice(VoiceIntent::AskCancel)]
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
    fn call_overlays_cycle_and_activate_every_visible_control() {
        let mama = contact("sip:mama@example.test", "Mama");

        let mut incoming = UiRuntime::default();
        incoming.snapshot.call.contacts = vec![mama.clone()];
        incoming.snapshot.call.peer_name = mama.title.clone();
        incoming.snapshot.call.peer_address = mama.id.clone();
        incoming.snapshot.call.state = "incoming".to_string();
        incoming.active_screen = UiScreen::IncomingCall;

        incoming.handle_input(InputAction::Advance, 100);
        assert_eq!(incoming.focus_index, 1);
        incoming.handle_input(InputAction::Select, 200);
        assert_eq!(
            incoming.take_intents(),
            vec![UiIntent::Call(CallIntent::Reject)]
        );
        incoming.handle_input(InputAction::Advance, 300);
        assert_eq!(incoming.focus_index, 0);
        incoming.handle_input(InputAction::Select, 400);
        assert_eq!(
            incoming.take_intents(),
            vec![UiIntent::Call(CallIntent::Answer)]
        );

        let mut outgoing = UiRuntime::default();
        outgoing.snapshot.call.state = "outgoing".to_string();
        outgoing.active_screen = UiScreen::OutgoingCall;
        outgoing.handle_input(InputAction::Advance, 100);
        assert_eq!(outgoing.focus_index, 0);
        outgoing.handle_input(InputAction::Select, 200);
        assert_eq!(
            outgoing.take_intents(),
            vec![UiIntent::Call(CallIntent::Hangup)]
        );

        let mut active = UiRuntime::default();
        active.snapshot.call.state = "active".to_string();
        active.active_screen = UiScreen::InCall;
        active.handle_input(InputAction::Select, 100);
        assert_eq!(
            active.take_intents(),
            vec![UiIntent::Call(CallIntent::ToggleMute)]
        );
        active.handle_input(InputAction::Advance, 200);
        assert_eq!(active.focus_index, 1);
        active.handle_input(InputAction::Select, 300);
        assert_eq!(
            active.take_intents(),
            vec![UiIntent::Call(CallIntent::Hangup)]
        );
    }

    #[test]
    fn call_overlay_dims_the_deck_and_keeps_talk_selected() {
        let mut runtime = UiRuntime::default();
        runtime.snapshot.call.state = "active".to_string();
        runtime.snapshot.call.peer_name = "Mama".to_string();
        runtime.snapshot.call.duration_text = "02:14".to_string();
        runtime.active_screen = UiScreen::InCall;

        let graph = flatten::flatten(&runtime.scene_graph(1_000));
        let deck = find_role(&graph, roles::DECK_BAR).expect("deck bar");
        let state = find_role(&graph, roles::CALL_STATE).expect("call state");
        let duration = find_role(&graph, roles::CALL_DURATION).expect("call duration");

        assert_eq!(deck.props.opacity, Some(140));
        assert_eq!(state.props.text.as_deref(), Some("IN CALL"));
        assert_eq!(duration.props.text.as_deref(), Some("02:14"));
    }

    #[test]
    fn ringing_call_uses_two_outlined_pulse_layers() {
        let mut runtime = UiRuntime::default();
        runtime.snapshot.call.state = "incoming".to_string();
        runtime.snapshot.call.peer_name = "Mama".to_string();
        runtime.active_screen = UiScreen::IncomingCall;

        let graph = flatten::flatten(&runtime.scene_graph(1_000));
        assert_eq!(count_visible_role(&graph, roles::FX_PULSE), 2);
    }

    fn replay_note(
        message_id: &str,
        file_path: &str,
        duration_ms: i32,
    ) -> VoiceNoteSummarySnapshot {
        VoiceNoteSummarySnapshot {
            message_id: message_id.to_string(),
            local_file_path: file_path.to_string(),
            duration_ms,
            ..VoiceNoteSummarySnapshot::default()
        }
    }

    #[test]
    fn talk_replay_opens_pauses_resumes_and_auto_advances_the_contact_queue() {
        let mama = contact("sip:mama@example.test", "Mama");
        let first = replay_note("note-1", "/tmp/one.wav", 7_000);
        let second = replay_note("note-2", "/tmp/two.wav", 5_000);
        let mut runtime = UiRuntime::default();
        runtime.snapshot.call.contacts = vec![mama.clone()];
        runtime
            .snapshot
            .call
            .voice_notes_by_contact
            .insert(mama.id.clone(), vec![first.clone(), second.clone()]);
        runtime.selected_contact = Some(mama.clone());
        runtime.active_screen = UiScreen::TalkContact;
        runtime.focus_index = 2;

        runtime.handle_input(InputAction::Select, 100);
        assert_eq!(runtime.active_screen, UiScreen::Replay);
        assert_eq!(runtime.focus_index, 1);
        assert_eq!(
            runtime.take_intents(),
            vec![UiIntent::Voice(VoiceIntent::PlayLatest(
                intents::voice_file_action(&mama, &first).expect("first note payload")
            ))]
        );

        let mut voice = runtime.snapshot.voice.clone();
        voice.playback_active = true;
        voice.playback_file_path = first.local_file_path.clone();
        voice.playback_duration_ms = first.duration_ms;
        runtime.apply_patch(RuntimeSnapshotPatch::Voice(voice.clone()));
        runtime.handle_input(InputAction::Select, 200);
        assert_eq!(
            runtime.take_intents(),
            vec![UiIntent::Voice(VoiceIntent::PausePlayback)]
        );

        voice.playback_active = false;
        voice.playback_paused = true;
        runtime.apply_patch(RuntimeSnapshotPatch::Voice(voice.clone()));
        runtime.handle_input(InputAction::Select, 300);
        assert_eq!(
            runtime.take_intents(),
            vec![UiIntent::Voice(VoiceIntent::ResumePlayback)]
        );

        voice.playback_active = true;
        voice.playback_paused = false;
        runtime.apply_patch(RuntimeSnapshotPatch::Voice(voice.clone()));
        voice.playback_active = false;
        voice.playback_file_path.clear();
        runtime.apply_patch(RuntimeSnapshotPatch::Voice(voice.clone()));
        assert_eq!(runtime.replay_index, 1);
        assert_eq!(
            runtime.take_intents(),
            vec![UiIntent::Voice(VoiceIntent::PlayLatest(
                intents::voice_file_action(&mama, &second).expect("second note payload")
            ))]
        );

        voice.playback_active = true;
        voice.playback_file_path = second.local_file_path.clone();
        runtime.apply_patch(RuntimeSnapshotPatch::Voice(voice.clone()));
        voice.playback_active = false;
        voice.playback_file_path.clear();
        runtime.apply_patch(RuntimeSnapshotPatch::Voice(voice));
        assert_eq!(runtime.active_screen, UiScreen::TalkContact);
        assert_eq!(runtime.focus_index, 2);
    }

    #[test]
    fn replay_delete_waits_for_store_confirmation_then_plays_the_next_note() {
        let mama = contact("sip:mama@example.test", "Mama");
        let first = replay_note("note-1", "/tmp/one.wav", 7_000);
        let second = replay_note("note-2", "/tmp/two.wav", 5_000);
        let mut runtime = UiRuntime::default();
        runtime.snapshot.call.contacts = vec![mama.clone()];
        runtime
            .snapshot
            .call
            .voice_notes_by_contact
            .insert(mama.id.clone(), vec![first.clone(), second.clone()]);
        runtime.selected_contact = Some(mama.clone());
        runtime.active_screen = UiScreen::TalkContact;
        runtime.focus_index = 2;
        runtime.handle_input(InputAction::Select, 100);
        runtime.take_intents();

        runtime.snapshot.voice.playback_active = true;
        runtime.snapshot.voice.playback_file_path = first.local_file_path.clone();
        runtime.focus_index = 0;
        runtime.handle_input(InputAction::Select, 200);
        assert_eq!(
            runtime.take_intents(),
            vec![
                UiIntent::Voice(VoiceIntent::StopPlayback),
                UiIntent::Voice(VoiceIntent::Delete(
                    intents::voice_file_action(&mama, &first).expect("delete payload")
                )),
            ]
        );

        let mut call = runtime.snapshot.call.clone();
        call.voice_notes_by_contact
            .insert(mama.id.clone(), vec![second.clone()]);
        runtime.apply_patch(RuntimeSnapshotPatch::Call(call));
        assert_eq!(runtime.active_screen, UiScreen::Replay);
        assert_eq!(runtime.replay_index, 0);
        assert_eq!(
            runtime.take_intents(),
            vec![UiIntent::Voice(VoiceIntent::PlayLatest(
                intents::voice_file_action(&mama, &second).expect("next note payload")
            ))]
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
        assert_eq!(count_visible_role(&ambient, roles::STATUS_BAR), 0);
        assert_eq!(count_visible_role(&ambient, roles::WATCH_FACE), 1);

        runtime.handle_input(InputAction::Advance, 30_200);
        assert_eq!(runtime.home_mode, HomeMode::Focused);
        assert_eq!(runtime.focus_index, 0);
        let awake = flatten::flatten(&runtime.scene_graph(30_200));
        assert_eq!(count_visible_role(&awake, roles::DECK_BAR), 1);
        assert_eq!(count_visible_role(&awake, roles::WATCH_FACE), 0);

        runtime.handle_input(InputAction::Advance, 30_300);
        assert_eq!(runtime.focus_index, 1);
    }

    #[test]
    fn ambient_transition_and_wake_remount_the_full_screen_scene() {
        let mut runtime = UiRuntime::default();
        let mut engine = crate::engine::Engine::default();
        runtime.advance_home_state(0);
        engine.render(&runtime.scene_graph(0), 0);

        runtime.advance_home_state(30_000);
        let ambient_graph = runtime.scene_graph(30_000);
        let ambient = engine.render(&ambient_graph, 30_000).to_vec();
        assert!(ambient.iter().any(|mutation| matches!(
            mutation,
            crate::engine::Mutation::Create {
                role: Some(role),
                ..
            } if *role == roles::WATCH_FACE
        )));

        assert!(runtime.wake_home_from_ambient(30_100));
        let awake_graph = runtime.scene_graph(30_100);
        let awake = engine.render(&awake_graph, 30_100);
        assert!(awake.iter().any(|mutation| matches!(
            mutation,
            crate::engine::Mutation::Create {
                role: Some(role),
                ..
            } if *role == roles::COMPANION
        )));
    }

    #[test]
    fn watch_face_text_uses_uppercase_local_calendar_and_24_hour_time() {
        let now = time::Date::from_calendar_date(2026, Month::July, 23)
            .expect("valid date")
            .with_hms(9, 41, 0)
            .expect("valid time")
            .assume_utc();

        assert_eq!(
            watch_face_text(now),
            ("THU 23 JUL".to_string(), "09:41".to_string())
        );
    }

    #[test]
    fn ambient_power_updates_request_a_full_frame() {
        let mut runtime = UiRuntime::default();
        runtime.advance_home_state(0);
        runtime.advance_home_state(30_000);
        runtime.mark_clean();
        runtime.dirty.power = true;

        let frame = runtime.frame_request(30_100).expect("ambient frame");
        assert_eq!(frame.dirty_region, None);
    }

    #[test]
    fn ambient_orbit_animation_flushes_only_its_square_region() {
        let mut runtime = UiRuntime::default();
        runtime.advance_home_state(0);
        runtime.advance_home_state(30_000);
        runtime.mark_clean();
        runtime.dirty.animation = true;

        let frame = runtime
            .frame_request(30_100)
            .expect("ambient animation frame");
        assert_eq!(frame.dirty_region, Some(WATCH_ORBIT_DIRTY_REGION));
        assert_eq!(frame.dirty_region.expect("orbit region").w, 236);
        assert_eq!(frame.dirty_region.expect("orbit region").h, 236);
    }

    #[test]
    fn ambient_external_animation_requests_a_full_frame() {
        let mut runtime = UiRuntime::default();
        runtime.advance_home_state(0);
        runtime.advance_home_state(30_000);
        runtime.mark_clean();
        runtime.start_animation(
            AnimationRequest {
                id: "ambient-fade".to_string(),
                target: AnimationTarget::ActiveScreen,
                property: AnimationProperty::Opacity,
                easing: AnimationEasing::EaseInOut,
                from: 0,
                to: 255,
                duration_ms: 500,
            },
            30_000,
        );

        let frame = runtime
            .frame_request(30_100)
            .expect("ambient external animation frame");
        assert_eq!(frame.scene_graph.active.timelines.len(), 2);
        assert_eq!(frame.dirty_region, None);
    }

    #[test]
    fn ambient_external_animation_completion_requests_a_full_frame() {
        let mut runtime = UiRuntime::default();
        runtime.advance_home_state(0);
        runtime.advance_home_state(30_000);
        runtime.mark_clean();
        runtime.start_animation(
            AnimationRequest {
                id: "ambient-fade".to_string(),
                target: AnimationTarget::Runtime,
                property: AnimationProperty::Opacity,
                easing: AnimationEasing::EaseInOut,
                from: 0,
                to: 255,
                duration_ms: 500,
            },
            30_000,
        );
        runtime.mark_clean();

        assert!(runtime.advance_animations(30_500));
        assert!(runtime.transitions.is_empty());
        let frame = runtime
            .frame_request(30_500)
            .expect("ambient transition completion frame");
        assert_eq!(frame.scene_graph.active.timelines.len(), 1);
        assert_eq!(frame.dirty_region, None);

        runtime.mark_clean();
        runtime.mark_animation_frame();
        let orbit_frame = runtime
            .frame_request(30_600)
            .expect("post-transition orbit frame");
        assert_eq!(
            orbit_frame.dirty_region,
            Some(WATCH_ORBIT_DIRTY_REGION),
            "the full-frame override must clear after the completion frame renders"
        );
    }
}
