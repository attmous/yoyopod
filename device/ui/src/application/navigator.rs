use crate::router::{
    self, is_call_screen, is_overlay_screen, route_for, runtime_preemption_for_display,
    static_intent_template, AdvanceTarget, BackPolicy, DynamicActionKind, IntentTemplate, ListKind,
    NavigationPolicy, PassthroughPolicy, SelectionTarget, SnapshotCondition,
};
use crate::scene::FocusPolicy;
use yoyopod_protocol::ui::{
    CallIntent, ListItemSnapshot, MusicIntent, SettingsIntent, UiIntent, VoiceIntent,
};

use super::state::HomeMode;
use super::{focus, intents, options, UiRuntime, UiScreen};

pub fn apply_runtime_preemption(runtime: &mut UiRuntime) {
    if let Some(key) = runtime.snapshot.call.session.clone() {
        if matches!(
            runtime.snapshot.call.state.as_str(),
            "incoming" | "outgoing" | "active"
        ) {
            let new_session = runtime
                .interrupted_navigation
                .as_ref()
                .is_none_or(|(old, _)| old != &key);
            if new_session {
                remove_flashlight_route(runtime);
                let entry = runtime
                    .interrupted_navigation
                    .take()
                    .map(|(_, entry)| entry)
                    .unwrap_or_else(|| {
                        crate::router::history::HistoryEntry::new(
                            runtime.active_screen,
                            runtime.focus_index,
                            if matches!(
                                runtime.active_screen,
                                UiScreen::Talk | UiScreen::Contacts | UiScreen::SetupContacts
                            ) {
                                runtime
                                    .snapshot
                                    .call
                                    .contacts
                                    .get(runtime.focus_index)
                                    .map(|c| c.contact_id.clone())
                            } else {
                                runtime
                                    .selected_contact
                                    .as_ref()
                                    .map(|c| c.contact_id.clone())
                                    .or_else(|| {
                                        runtime.selected_playlist.as_ref().map(|p| p.id.clone())
                                    })
                            },
                        )
                    });
                runtime.interrupted_navigation = Some((key, entry));
                runtime.pending_wheel_roll = None;
                runtime.home_mode = HomeMode::Focused;
                runtime.last_input_ms = None;
                runtime.focus_index = 0;
                runtime.call_wake_pending = true;
                runtime.accessibility_events.clear();
                runtime.scene_revision = runtime.scene_revision.wrapping_add(1);
            }
            if let Some(screen) = runtime_preemption_for_display(
                &runtime.snapshot,
                runtime.system_overlay.loading_visible,
            ) {
                let old = runtime.active_screen;
                runtime.active_screen = screen;
                reset_transient_screen_if_left(runtime, old);
            }
            return;
        }
    }
    if runtime.snapshot.call.state == "idle" {
        if let Some((_, entry)) = runtime.interrupted_navigation.take() {
            let directory_screen = matches!(
                entry.screen,
                UiScreen::Talk | UiScreen::Contacts | UiScreen::SetupContacts
            );
            let directory_focus = entry.selected_id.as_ref().and_then(|id| {
                runtime
                    .snapshot
                    .call
                    .contacts
                    .iter()
                    .position(|c| &c.contact_id == id)
            });
            let valid_selection = match entry.screen {
                UiScreen::TalkContact | UiScreen::CallMethod | UiScreen::Replay => {
                    runtime.selected_contact.is_some()
                }
                UiScreen::PlaylistTracks => runtime.selected_playlist.as_ref().is_some_and(|p| {
                    runtime
                        .snapshot
                        .music
                        .playlists
                        .iter()
                        .any(|v| v.id == p.id)
                }),
                _ => true,
            };
            let safe = valid_selection
                && (!directory_screen || entry.selected_id.is_none() || directory_focus.is_some())
                && !is_overlay_screen(entry.screen)
                && !is_call_screen(entry.screen)
                && !matches!(
                    entry.screen,
                    UiScreen::Ask | UiScreen::VoiceNote | UiScreen::Replay | UiScreen::Flashlight
                );
            runtime.active_screen = if safe { entry.screen } else { UiScreen::Hub };
            runtime.focus_index = if safe {
                if directory_screen {
                    directory_focus.unwrap_or(entry.focus_index)
                } else {
                    entry.focus_index
                }
            } else {
                0
            };
            if !safe {
                runtime.screen_stack.clear();
            }
            runtime.home_mode = HomeMode::Focused;
            runtime.last_input_ms = None;
            runtime.pending_wheel_roll = None;
            clamp_focus(runtime);
            return;
        }
    }
    if let Some(screen) =
        runtime_preemption_for_display(&runtime.snapshot, runtime.system_overlay.loading_visible)
    {
        remove_flashlight_route(runtime);
        if runtime.active_screen != screen {
            if runtime.active_screen == UiScreen::Replay {
                leave_replay(runtime);
            }
            if is_overlay_screen(runtime.active_screen) && is_overlay_screen(screen) {
                runtime.active_screen = screen;
                runtime.focus_index = 0;
            } else {
                push_screen(runtime, screen);
            }
        }
        return;
    }

    if is_overlay_screen(runtime.active_screen) {
        pop_until_not_overlay(runtime);
    }

    if is_call_screen(runtime.active_screen) && runtime.snapshot.call.state == "idle" {
        pop_until_not_call(runtime);
    }
}

pub fn apply_app_state_route(
    runtime: &mut UiRuntime,
    previous_app_state: &UiScreen,
    app_state: &UiScreen,
) {
    if runtime.interrupted_navigation.is_some() {
        return;
    }
    if app_state == previous_app_state {
        return;
    }
    if runtime.active_screen != *app_state {
        if runtime.active_screen == UiScreen::Replay {
            leave_replay(runtime);
        }
        let previous_screen = runtime.active_screen;
        runtime.screen_stack.clear();
        runtime.active_screen = *app_state;
        reset_transient_screen_if_left(runtime, previous_screen);
        runtime.focus_index = initial_focus(*app_state);
        if *app_state == UiScreen::Hub {
            runtime.home_mode = HomeMode::Idle;
            runtime.last_input_ms = None;
            runtime.selected_playlist = None;
            runtime.selected_contact = None;
            reset_replay_state(runtime);
        }
    }
}

pub fn advance_focus(runtime: &mut UiRuntime) {
    if let AdvanceTarget::EmitIntent(template) = route_for(runtime.active_screen).advance {
        emit_static_intent(runtime, template);
        return;
    }
    if runtime.active_screen == UiScreen::Hub && runtime.home_mode == HomeMode::Idle {
        runtime.focus_index = 0;
        runtime.home_mode = HomeMode::Focused;
        return;
    }
    let count = focus_count(runtime);
    runtime.focus_index = match route_for(runtime.active_screen).focus_policy {
        FocusPolicy::None => runtime.focus_index,
        FocusPolicy::Wrap => focus::advance(runtime.focus_index, count),
        FocusPolicy::Clamp => focus::advance_clamped(runtime.focus_index, count),
    };
}

pub fn select_focused(runtime: &mut UiRuntime, now_ms: u64) {
    if runtime.active_screen == UiScreen::Hub && runtime.home_mode != HomeMode::Focused {
        return;
    }
    if runtime.active_screen == UiScreen::Stopwatch {
        runtime.activate_stopwatch_action(now_ms);
        return;
    }
    let route = route_for(runtime.active_screen);
    let Some(target) = router::select::selection_target(route, runtime.focus_index) else {
        return;
    };
    apply_selection_target(runtime, target);
}

pub fn go_home(runtime: &mut UiRuntime) {
    if is_call_screen(runtime.active_screen) {
        go_back_from_call_screen(runtime);
        return;
    }
    if runtime.active_screen == UiScreen::Replay {
        leave_replay(runtime);
    }
    let previous_screen = runtime.active_screen;
    runtime.screen_stack.clear();
    runtime.active_screen = UiScreen::Hub;
    reset_transient_screen_if_left(runtime, previous_screen);
    runtime.focus_index = 0;
    runtime.home_mode = HomeMode::Idle;
    runtime.selected_playlist = None;
    runtime.selected_contact = None;
    reset_replay_state(runtime);
}

pub fn exit_flashlight(runtime: &mut UiRuntime) {
    runtime.screen_stack.clear();
    runtime.active_screen = UiScreen::Hub;
    runtime.focus_index = 4;
    runtime.home_mode = HomeMode::Focused;
    runtime.selected_playlist = None;
    runtime.selected_contact = None;
    runtime.clear_flashlight();
    reset_replay_state(runtime);
}

pub fn go_back_or_emit(runtime: &mut UiRuntime) {
    if apply_back_passthrough(runtime) {
        return;
    }

    match route_for(runtime.active_screen).nav_policy {
        NavigationPolicy::Root => {}
        NavigationPolicy::Overlay | NavigationPolicy::Stack => pop_screen_or_hub(runtime),
        NavigationPolicy::Call => go_back_from_call_screen(runtime),
    }
}

pub fn handle_ptt_press(runtime: &mut UiRuntime) {
    apply_passthrough_trigger(runtime, yoyopod_protocol::ui::InputAction::PttPress);
}

pub fn handle_ptt_release(runtime: &mut UiRuntime) {
    apply_passthrough_trigger(runtime, yoyopod_protocol::ui::InputAction::PttRelease);
}

pub fn wants_ptt_passthrough(runtime: &UiRuntime) -> bool {
    let route = route_for(runtime.active_screen);
    router::passthrough::captures_button(route, |condition| matches_condition(runtime, condition))
}

pub fn clamp_focus(runtime: &mut UiRuntime) {
    let count = focus_count(runtime);
    runtime.focus_index = focus::clamp(runtime.focus_index, count);
}

pub fn reconcile_selected_contact(runtime: &mut UiRuntime) {
    let Some(selected) = runtime.selected_contact.as_ref() else {
        return;
    };
    let current = runtime.snapshot.call.contacts.iter().find(|contact| {
        if !selected.contact_id.is_empty() {
            contact.contact_id == selected.contact_id
        } else {
            contact.id == selected.id
        }
    });
    runtime.selected_contact = current.cloned();
    if runtime.selected_contact.is_none()
        && matches!(
            runtime.active_screen,
            UiScreen::TalkContact | UiScreen::CallMethod | UiScreen::Replay
        )
    {
        if runtime.active_screen == UiScreen::Replay {
            leave_replay(runtime);
        }
        while runtime.active_screen != UiScreen::Talk && !runtime.screen_stack.is_empty() {
            pop_screen_or_hub(runtime);
        }
        if runtime.active_screen != UiScreen::Talk {
            runtime.active_screen = UiScreen::Talk;
        }
        runtime.focus_index = 0;
    }
}

fn apply_selection_target(runtime: &mut UiRuntime, target: SelectionTarget) {
    match target {
        SelectionTarget::PushScreen(UiScreen::Talk)
            if runtime.snapshot.voice.interrupted_draft_path.is_some() =>
        {
            push_screen(runtime, UiScreen::VoiceNote)
        }
        SelectionTarget::PushScreen(screen) => push_screen(runtime, screen),
        SelectionTarget::EmitIntent(template) => emit_static_intent(runtime, template),
        SelectionTarget::PushWithIntent { screen, intent } => {
            emit_static_intent(runtime, intent);
            push_screen(runtime, screen);
        }
        SelectionTarget::DynamicListItem { kind } => select_dynamic_list_item(runtime, kind),
        SelectionTarget::DynamicAction { kind } => select_dynamic_action(runtime, kind),
        SelectionTarget::AdvanceFocus => advance_focus(runtime),
        SelectionTarget::PopScreen => pop_screen_or_hub(runtime),
        SelectionTarget::Noop => {}
    }
}

fn emit_static_intent(runtime: &mut UiRuntime, template: IntentTemplate) {
    use yoyopod_protocol::call::{CallAction, RejectReason};
    let action = match template {
        IntentTemplate::CallAnswer => {
            if !runtime.snapshot.call.accept_enabled {
                return;
            }
            Some(CallAction::Answer)
        }
        IntentTemplate::CallReject => Some(CallAction::Reject(RejectReason::Cancelled)),
        IntentTemplate::CallHangup => Some(CallAction::Hangup),
        IntentTemplate::CallToggleMute => Some(CallAction::SetMute(!runtime.snapshot.call.muted)),
        _ => None,
    };
    if let Some(action) = action {
        if let Some(intent) = intents::session_action(&runtime.snapshot, action) {
            runtime.intents.push(intent);
        }
        return;
    }
    if let Some(intent) = static_intent_template(template) {
        runtime.intents.push(intent);
    }
}

fn select_dynamic_list_item(runtime: &mut UiRuntime, kind: ListKind) {
    match kind {
        ListKind::Playlists => {
            if let Some(item) = runtime
                .snapshot
                .music
                .playlists
                .get(runtime.focus_index)
                .cloned()
            {
                runtime.selected_playlist = Some(item);
                push_screen(runtime, UiScreen::PlaylistTracks);
            }
        }
        ListKind::PlaylistTracks => {
            let Some(playlist) = runtime.selected_playlist.as_ref() else {
                return;
            };
            let Some(track) = runtime
                .snapshot
                .music
                .playlist_tracks
                .get(&playlist.id)
                .and_then(|tracks| tracks.get(runtime.focus_index))
            else {
                return;
            };
            runtime
                .intents
                .push(UiIntent::Music(MusicIntent::PlayPlaylistTrack(
                    intents::playlist_track_action(playlist, track, runtime.focus_index),
                )));
            push_screen(runtime, UiScreen::NowPlaying);
        }
        ListKind::RecentTracks => {
            if let Some(item) = runtime
                .snapshot
                .music
                .recent_tracks
                .get(runtime.focus_index)
                .cloned()
            {
                runtime
                    .intents
                    .push(UiIntent::Music(MusicIntent::PlayRecentTrack(
                        intents::list_item_action(&item),
                    )));
                push_screen(runtime, UiScreen::NowPlaying);
            }
        }
        ListKind::Contacts => {
            if let Some(item) = runtime
                .snapshot
                .call
                .contacts
                .get(runtime.focus_index)
                .cloned()
            {
                runtime.selected_contact = Some(item);
                push_screen(runtime, UiScreen::TalkContact);
            }
        }
        ListKind::CallHistory => {
            if let Some(item) = runtime
                .snapshot
                .call
                .history
                .get(runtime.focus_index)
                .cloned()
            {
                emit_call_start(runtime, &item);
            }
        }
    }
}

fn select_dynamic_action(runtime: &mut UiRuntime, kind: DynamicActionKind) {
    match kind {
        DynamicActionKind::Ask => select_ask_action(runtime),
        DynamicActionKind::TalkContact => select_talk_contact_action(runtime),
        DynamicActionKind::CallMethod => select_call_method(runtime),
        DynamicActionKind::Replay => select_replay_action(runtime),
        DynamicActionKind::VoiceNote => select_voice_note(runtime),
        DynamicActionKind::SetupCompanion => select_setup_companion(runtime),
        DynamicActionKind::SetupTheme => select_setup_theme(runtime),
        DynamicActionKind::SetupCallMode => select_call_mode(runtime),
        DynamicActionKind::SetupContactPriority => select_contact_priority(runtime),
    }
}

pub fn select_call_mode(runtime: &mut UiRuntime) {
    use yoyopod_protocol::call::DeviceMode;
    let modes = [
        DeviceMode::Normal,
        DeviceMode::Silent,
        DeviceMode::DoNotDisturb,
    ];
    if let Some(mode) = modes.get(runtime.focus_index) {
        runtime
            .intents
            .push(UiIntent::Settings(SettingsIntent::DeviceModeSet(
                mode.clone(),
            )));
    }
}

fn select_contact_priority(runtime: &mut UiRuntime) {
    let Some(contact) = runtime.snapshot.call.contacts.get(runtime.focus_index) else {
        return;
    };
    if contact.contact_id.trim().is_empty()
        || runtime
            .snapshot
            .settings
            .priority_write
            .as_ref()
            .is_some_and(|write| write.pending)
    {
        return;
    }
    runtime
        .intents
        .push(UiIntent::Settings(SettingsIntent::ContactPrioritySet(
            yoyopod_protocol::call::ContactPrioritySet {
                contact_id: contact.contact_id.clone(),
                priority: !contact.priority,
            },
        )));
}

const COMPANIONS: [&str; 5] = ["Blob", "Owl", "Cat", "Bunny", "Robot"];
const THEMES: [&str; 3] = ["Light", "Dark", "Auto"];

fn select_setup_companion(runtime: &mut UiRuntime) {
    let Some(value) = COMPANIONS.get(runtime.focus_index) else {
        return;
    };
    runtime
        .intents
        .push(UiIntent::Settings(SettingsIntent::CompanionSet(
            (*value).to_string(),
        )));
    runtime.apply_companion_choice(value);
    go_home(runtime);
}

fn select_setup_theme(runtime: &mut UiRuntime) {
    let Some(value) = THEMES.get(runtime.focus_index) else {
        return;
    };
    runtime
        .intents
        .push(UiIntent::Settings(SettingsIntent::ThemeSet(
            (*value).to_string(),
        )));
}

fn select_ask_action(runtime: &mut UiRuntime) {
    let phase = runtime.snapshot.voice.phase.trim().to_ascii_lowercase();
    if runtime.snapshot.voice.playback_active
        || runtime.snapshot.voice.playback_paused
        || matches!(
            phase.as_str(),
            "thinking" | "reply" | "answering" | "offline"
        )
    {
        runtime
            .intents
            .push(UiIntent::Voice(VoiceIntent::AskCancel));
    }
}

fn apply_back_passthrough(runtime: &mut UiRuntime) -> bool {
    let route = route_for(runtime.active_screen);
    let policy =
        router::back::back_policy(route, |condition| matches_condition(runtime, condition));
    if let Some(policy) = policy {
        emit_back_intent(runtime, policy);
        if policy.pop_screen {
            pop_screen_or_hub(runtime);
        }
        return true;
    }
    false
}

fn emit_back_intent(runtime: &mut UiRuntime, policy: BackPolicy) {
    emit_static_intent(runtime, policy.intent);
}

fn go_back_from_call_screen(runtime: &mut UiRuntime) {
    match runtime.active_screen {
        UiScreen::IncomingCall => emit_static_intent(runtime, IntentTemplate::CallReject),
        UiScreen::OutgoingCall | UiScreen::InCall => {
            emit_static_intent(runtime, IntentTemplate::CallHangup);
        }
        _ => {}
    }
}

fn emit_call_start(runtime: &mut UiRuntime, item: &ListItemSnapshot) {
    if !item.can_call
        || !runtime.snapshot.call.contacts.iter().any(|contact| {
            contact.id == item.id && contact.can_call && !contact.communication_unavailable
        })
    {
        return;
    }
    runtime
        .intents
        .push(UiIntent::Call(CallIntent::Start(intents::contact_action(
            item,
        ))));
}

fn select_talk_contact_action(runtime: &mut UiRuntime) {
    let actions =
        options::talk_contact_actions(&runtime.snapshot, runtime.selected_contact.as_ref());
    let Some(action) = actions.get(runtime.focus_index) else {
        return;
    };
    match action.kind {
        "review_draft" => push_screen(runtime, UiScreen::VoiceNote),
        "discard_draft" => {
            if let Some(action) = runtime.saved_draft_action() {
                runtime
                    .intents
                    .push(UiIntent::Voice(VoiceIntent::SavedDiscard(action)));
            }
        }
        "call" => {
            push_screen(runtime, UiScreen::CallMethod);
        }
        // Recording is owned by the physical-button hold passthrough while
        // this action is focused; selecting the tile does not change routes.
        "record" => {}
        "replay" => {
            runtime.replay_index = 0;
            if runtime.replay_note_payload().is_some() {
                push_screen(runtime, UiScreen::Replay);
                start_current_replay_note(runtime);
            }
        }
        _ => {}
    }
}

fn select_call_method(runtime: &mut UiRuntime) {
    let Some(contact) = runtime.selected_contact.as_ref() else {
        return;
    };
    let method = if runtime.focus_index == 0 {
        yoyopod_protocol::ui::CallMethod::Sip
    } else {
        yoyopod_protocol::ui::CallMethod::Gsm
    };
    if options::call_method_disabled_reason(&runtime.snapshot, contact, method).is_some() {
        return;
    }
    let mut action = intents::contact_action(contact);
    action.method = method;
    runtime
        .intents
        .push(UiIntent::Call(CallIntent::Start(action)));
}

fn select_replay_action(runtime: &mut UiRuntime) {
    let Some(payload) = runtime.replay_note_payload() else {
        pop_screen_or_hub(runtime);
        return;
    };
    match runtime.focus_index {
        0 => {
            runtime.replay_auto_advance_armed = false;
            runtime.replay_pending_delete_message_id = Some(payload.message_id.clone());
            if runtime.snapshot.voice.playback_active || runtime.snapshot.voice.playback_paused {
                runtime
                    .intents
                    .push(UiIntent::Voice(VoiceIntent::StopPlayback));
            }
            runtime
                .intents
                .push(UiIntent::Voice(VoiceIntent::Delete(payload)));
        }
        1 => {
            let is_current = runtime.snapshot.voice.playback_file_path == payload.file_path;
            if is_current && runtime.snapshot.voice.playback_active {
                runtime.replay_auto_advance_armed = false;
                runtime
                    .intents
                    .push(UiIntent::Voice(VoiceIntent::PausePlayback));
            } else if is_current && runtime.snapshot.voice.playback_paused {
                runtime.replay_auto_advance_armed = true;
                runtime
                    .intents
                    .push(UiIntent::Voice(VoiceIntent::ResumePlayback));
            } else {
                start_current_replay_note(runtime);
            }
        }
        _ => {
            runtime.replay_auto_advance_armed = false;
            if runtime.replay_index + 1 < runtime.replay_notes().len() {
                if runtime.snapshot.voice.playback_active || runtime.snapshot.voice.playback_paused
                {
                    runtime
                        .intents
                        .push(UiIntent::Voice(VoiceIntent::StopPlayback));
                }
                advance_replay_note(runtime);
            } else {
                pop_screen_or_hub(runtime);
            }
        }
    }
}

fn start_current_replay_note(runtime: &mut UiRuntime) -> bool {
    let Some(payload) = runtime.replay_note_payload() else {
        return false;
    };
    runtime.replay_auto_advance_armed = true;
    runtime
        .intents
        .push(UiIntent::Voice(VoiceIntent::PlayLatest(payload)));
    true
}

fn advance_replay_note(runtime: &mut UiRuntime) {
    let note_count = runtime.replay_notes().len();
    if runtime.replay_index + 1 >= note_count {
        pop_screen_or_hub(runtime);
        return;
    }
    runtime.replay_index += 1;
    start_current_replay_note(runtime);
}

pub(crate) fn reconcile_replay_snapshot(
    runtime: &mut UiRuntime,
    previous_playing: bool,
    previous_file_path: &str,
) {
    if runtime.active_screen != UiScreen::Replay {
        return;
    }

    if let Some(message_id) = runtime.replay_pending_delete_message_id.clone() {
        let deleted = !runtime
            .replay_notes()
            .iter()
            .any(|note| note.message_id == message_id);
        if deleted {
            runtime.replay_pending_delete_message_id = None;
            if runtime.replay_index >= runtime.replay_notes().len() {
                pop_screen_or_hub(runtime);
            } else {
                start_current_replay_note(runtime);
            }
        }
        return;
    }

    if runtime.replay_index >= runtime.replay_notes().len() {
        pop_screen_or_hub(runtime);
        return;
    }
    let current_file_path = runtime
        .replay_note_payload()
        .map(|payload| payload.file_path)
        .unwrap_or_default();
    let completed = previous_playing
        && !runtime.snapshot.voice.playback_active
        && !runtime.snapshot.voice.playback_paused
        && runtime.replay_auto_advance_armed
        && previous_file_path == current_file_path;
    if completed {
        runtime.replay_auto_advance_armed = false;
        advance_replay_note(runtime);
    }
}

fn leave_replay(runtime: &mut UiRuntime) {
    if runtime.snapshot.voice.playback_active || runtime.snapshot.voice.playback_paused {
        runtime
            .intents
            .push(UiIntent::Voice(VoiceIntent::StopPlayback));
    }
    reset_replay_state(runtime);
}

fn reset_replay_state(runtime: &mut UiRuntime) {
    runtime.replay_index = 0;
    runtime.replay_auto_advance_armed = false;
    runtime.replay_pending_delete_message_id = None;
}

fn select_voice_note(runtime: &mut UiRuntime) {
    if let Some(action) = runtime.saved_draft_action() {
        match runtime.voice_note_phase().as_str() {
            "review" | "failed" => match runtime.focus_index {
                0 if runtime.snapshot.voice.interrupted_draft_send_allowed => runtime
                    .intents
                    .push(UiIntent::Voice(VoiceIntent::SavedSend(action))),
                1 => runtime
                    .intents
                    .push(UiIntent::Voice(VoiceIntent::Play(Some(action)))),
                2 => runtime
                    .intents
                    .push(UiIntent::Voice(VoiceIntent::SavedDiscard(action))),
                _ => {}
            },
            "sent" => {
                runtime
                    .intents
                    .push(UiIntent::Voice(VoiceIntent::SavedDiscard(action)));
                pop_screen_or_hub(runtime);
            }
            _ => {}
        }
        return;
    }
    match runtime.voice_note_phase().as_str() {
        "ready" => pop_screen_or_hub(runtime),
        "recording" => runtime
            .intents
            .push(UiIntent::Voice(VoiceIntent::CaptureStop)),
        "review" => match runtime.focus_index {
            0 => {
                if let Some(payload) = runtime.voice_note_recipient_payload() {
                    runtime
                        .intents
                        .push(UiIntent::Voice(VoiceIntent::Send(payload)));
                }
            }
            1 => runtime
                .intents
                .push(UiIntent::Voice(VoiceIntent::Play(None))),
            _ => runtime.intents.push(UiIntent::Voice(VoiceIntent::Discard)),
        },
        "failed" => match runtime.focus_index {
            0 => {
                if let Some(payload) = runtime.voice_note_recipient_payload() {
                    runtime
                        .intents
                        .push(UiIntent::Voice(VoiceIntent::Send(payload)));
                }
            }
            _ => runtime.intents.push(UiIntent::Voice(VoiceIntent::Discard)),
        },
        "sent" => {
            runtime.intents.push(UiIntent::Voice(VoiceIntent::Discard));
            pop_screen_or_hub(runtime);
        }
        "sending" => {}
        _ => {}
    }
}

fn apply_passthrough_trigger(runtime: &mut UiRuntime, trigger: yoyopod_protocol::ui::InputAction) {
    let route = route_for(runtime.active_screen);
    let policy = router::passthrough::passthrough_policy(route, trigger, |condition| {
        matches_condition(runtime, condition)
    });
    if let Some(policy) = policy {
        emit_passthrough_intent(runtime, policy);
    }
}

fn emit_passthrough_intent(runtime: &mut UiRuntime, policy: PassthroughPolicy) {
    match policy.intent {
        IntentTemplate::VoiceCaptureStartAndSendRecipient => {
            if let Some(payload) = runtime.voice_note_recipient_payload() {
                runtime
                    .intents
                    .push(UiIntent::Voice(VoiceIntent::CaptureStartAndSend(payload)));
            }
        }
        template => emit_static_intent(runtime, template),
    }
}

fn matches_condition(runtime: &UiRuntime, condition: SnapshotCondition) -> bool {
    match condition {
        SnapshotCondition::Always => true,
        SnapshotCondition::VoiceRecording => runtime.voice_note_phase() == "recording",
        SnapshotCondition::VoiceReviewOrFailedOrSent => matches!(
            runtime.voice_note_phase().as_str(),
            "review" | "failed" | "sent"
        ),
        SnapshotCondition::TalkContactRecordAvailable => {
            runtime.active_screen == UiScreen::TalkContact
                && options::talk_contact_actions(
                    &runtime.snapshot,
                    runtime.selected_contact.as_ref(),
                )
                .get(runtime.focus_index)
                .is_some_and(|action| action.kind == "record")
                && !matches!(runtime.voice_note_phase().as_str(), "recording" | "sending")
        }
        SnapshotCondition::TalkContactRecordHeldOrPending => {
            runtime.active_screen == UiScreen::TalkContact
                && options::talk_contact_actions(
                    &runtime.snapshot,
                    runtime.selected_contact.as_ref(),
                )
                .get(runtime.focus_index)
                .is_some_and(|action| action.kind == "record")
                && runtime.voice_note_phase() != "sending"
        }
    }
}

fn push_screen(runtime: &mut UiRuntime, screen: UiScreen) {
    let previous_screen = runtime.active_screen;
    let selected_id = runtime
        .selected_contact
        .as_ref()
        .map(|contact| contact.id.clone())
        .or_else(|| {
            runtime
                .selected_playlist
                .as_ref()
                .map(|playlist| playlist.id.clone())
        });
    router::history::push(
        &mut runtime.screen_stack,
        &mut runtime.active_screen,
        runtime.focus_index,
        selected_id,
        screen,
    );
    reset_transient_screen_if_left(runtime, previous_screen);
    runtime.focus_index = initial_focus(screen);
}

const fn initial_focus(screen: UiScreen) -> usize {
    if matches!(screen, UiScreen::NowPlaying | UiScreen::Replay) {
        1
    } else {
        0
    }
}

fn pop_screen_or_hub(runtime: &mut UiRuntime) {
    if runtime.active_screen == UiScreen::Replay {
        leave_replay(runtime);
    }
    let previous_screen = runtime.active_screen;
    let entry = router::history::pop_or_hub(&mut runtime.screen_stack, &mut runtime.active_screen);
    reset_transient_screen_if_left(runtime, previous_screen);
    runtime.focus_index = entry.map(|entry| entry.focus_index).unwrap_or(0);
}

fn pop_until_not_call(runtime: &mut UiRuntime) {
    let previous_screen = runtime.active_screen;
    let entry = router::history::pop_until(
        &mut runtime.screen_stack,
        &mut runtime.active_screen,
        is_call_screen,
    );
    reset_transient_screen_if_left(runtime, previous_screen);
    runtime.focus_index = entry.map(|entry| entry.focus_index).unwrap_or(0);
}

fn pop_until_not_overlay(runtime: &mut UiRuntime) {
    let previous_screen = runtime.active_screen;
    let entry = router::history::pop_until(
        &mut runtime.screen_stack,
        &mut runtime.active_screen,
        is_overlay_screen,
    );
    reset_transient_screen_if_left(runtime, previous_screen);
    runtime.focus_index = entry.map(|entry| entry.focus_index).unwrap_or(0);
}

fn focus_count(runtime: &UiRuntime) -> usize {
    if runtime.active_screen == UiScreen::Stopwatch {
        return runtime.stopwatch_action_count();
    }
    focus::focus_count(
        runtime.active_screen,
        &runtime.snapshot,
        runtime.selected_playlist.as_ref(),
        runtime.selected_contact.as_ref(),
        runtime.replay_index,
    )
}

fn reset_transient_screen_if_left(runtime: &mut UiRuntime, previous_screen: UiScreen) {
    if previous_screen == UiScreen::Stopwatch && runtime.active_screen != UiScreen::Stopwatch {
        runtime.reset_stopwatch();
    }
    if previous_screen == UiScreen::Flashlight && runtime.active_screen != UiScreen::Flashlight {
        runtime.clear_flashlight();
    }
}

fn remove_flashlight_route(runtime: &mut UiRuntime) {
    let flashlight_was_active = runtime.active_screen == UiScreen::Flashlight;
    runtime
        .screen_stack
        .retain(|entry| entry.screen != UiScreen::Flashlight);
    if flashlight_was_active {
        runtime.screen_stack.clear();
        runtime.active_screen = UiScreen::Hub;
        runtime.focus_index = 4;
        runtime.home_mode = HomeMode::Focused;
    }
    runtime.clear_flashlight();
}
