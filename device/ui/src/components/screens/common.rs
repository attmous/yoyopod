use yoyopod_protocol::ui::{ListItemSnapshot, UiScreen};

use crate::engine::Key;
use crate::scene::{
    Backdrop, CallOverlayKind, CallOverlayModel, Cursor, Deck, DeckItem, DeckItemAnim, DeckKind,
    FocusPolicy, ItemRender, RegionId, RowModel, Scene, SceneDefaults, SceneId,
};

pub fn hero_scene(
    screen: UiScreen,
    defaults: &SceneDefaults,
    accent: u32,
    item_count: usize,
    focus: usize,
) -> Scene {
    Scene {
        id: SceneId::new(screen),
        backdrop: defaults.backdrop(accent),
        stage: defaults.stage,
        context: None,
        decks: vec![Deck {
            kind: DeckKind::CardRow,
            region: RegionId::HeroIcon,
            items: Vec::new(),
            focus_index: focus,
            focus_policy: FocusPolicy::Wrap,
            item_anim: DeckItemAnim::ScaleOnFocus {
                from_permille: 960,
                to_permille: 1000,
            },
            swap_anim: None,
            recycle_window: Some(3),
        }],
        cursor: Some(Cursor::UnderlineDots {
            count: item_count,
            focus,
        }),
        fx: defaults.fx_layer(accent),
        modal: None,
        timelines: defaults.fx_timelines(),
    }
}

pub fn list_scene(
    screen: UiScreen,
    defaults: &SceneDefaults,
    items: &[ListItemSnapshot],
    focus: usize,
    focus_policy: FocusPolicy,
) -> Scene {
    let rows = items.iter().map(row_model).collect::<Vec<_>>();
    let deck = Deck {
        kind: DeckKind::List,
        region: RegionId::ListBody,
        items: rows
            .into_iter()
            .map(|row| DeckItem {
                key: Key::String(row.id.clone()),
                render: ItemRender::Row(row),
            })
            .collect(),
        focus_index: focus,
        focus_policy,
        item_anim: DeckItemAnim::StaggerEnter {
            delay_per_index_ms: 40,
        },
        swap_anim: None,
        recycle_window: Some(4),
    };
    let cursor_index = deck.focused_visible_index();
    Scene {
        id: SceneId::new(screen),
        backdrop: defaults.backdrop(0x3ddd53),
        stage: defaults.stage,
        context: None,
        decks: vec![deck],
        cursor: Some(Cursor::RowGlow {
            index: cursor_index,
        }),
        fx: defaults.fx_layer(0x3ddd53),
        modal: None,
        timelines: defaults.fx_timelines(),
    }
}

pub fn action_scene(screen: UiScreen, defaults: &SceneDefaults, focus: usize) -> Scene {
    Scene {
        id: SceneId::new(screen),
        backdrop: defaults.backdrop(0x00d4ff),
        stage: defaults.stage,
        context: None,
        decks: vec![Deck {
            kind: DeckKind::Buttons,
            region: RegionId::ButtonRow,
            items: Vec::new(),
            focus_index: focus,
            focus_policy: FocusPolicy::Wrap,
            item_anim: DeckItemAnim::ScaleOnFocus {
                from_permille: 960,
                to_permille: 1000,
            },
            swap_anim: None,
            recycle_window: None,
        }],
        cursor: Some(Cursor::UnderlineDots { count: 3, focus }),
        fx: defaults.fx_layer(0x00d4ff),
        modal: None,
        timelines: defaults.fx_timelines(),
    }
}

pub fn call_scene(screen: UiScreen, defaults: &SceneDefaults, model: CallOverlayModel) -> Scene {
    Scene {
        id: SceneId::new(screen),
        backdrop: Backdrop::Solid(super::talk::TALK_STAGE_PERI),
        stage: defaults.stage,
        context: None,
        decks: vec![Deck {
            kind: DeckKind::Page,
            region: RegionId::ListBody,
            items: vec![DeckItem {
                key: Key::Static("call"),
                render: ItemRender::CallOverlay(model),
            }],
            focus_index: 0,
            focus_policy: FocusPolicy::None,
            item_anim: DeckItemAnim::None,
            swap_anim: None,
            recycle_window: None,
        }],
        cursor: None,
        fx: defaults.fx_layer(0xA9A6E5),
        modal: None,
        timelines: defaults.fx_timelines(),
    }
}

pub fn call_overlay_model(
    snapshot: &yoyopod_protocol::ui::RuntimeSnapshot,
    kind: CallOverlayKind,
    focus: usize,
) -> CallOverlayModel {
    let name = if snapshot.call.peer_name.trim().is_empty() {
        "Unknown".to_string()
    } else {
        snapshot.call.peer_name.clone()
    };
    let contact_index = snapshot.call.contacts.iter().position(|contact| {
        contact.id == snapshot.call.peer_address
            || contact.subtitle == snapshot.call.peer_address
            || contact.title.eq_ignore_ascii_case(&name)
    });
    let initial = contact_index
        .map(|index| super::talk::contact_initial(&snapshot.call.contacts[index]))
        .unwrap_or_else(|| {
            name.chars()
                .find(|character| character.is_alphanumeric())
                .map(|character| character.to_uppercase().collect())
                .unwrap_or_else(|| "?".to_string())
        });
    let duration = if snapshot.call.duration_text.trim().is_empty() {
        "00:00".to_string()
    } else {
        snapshot.call.duration_text.clone()
    };

    CallOverlayModel {
        address: format!(
            "{} · {}",
            if snapshot
                .call
                .session
                .as_ref()
                .is_some_and(|s| s.transport == yoyopod_protocol::call::CallTransport::Gsm)
            {
                "GSM"
            } else {
                "VoIP"
            },
            snapshot.call.peer_address
        ),
        accept_enabled: snapshot.call.accept_enabled,
        kind,
        state: match kind {
            CallOverlayKind::Incoming
                if !snapshot.call.accept_enabled
                    && !snapshot.call.gsm_available
                    && snapshot.call.session.as_ref().is_some_and(|key| {
                        key.transport == yoyopod_protocol::call::CallTransport::Gsm
                    }) =>
            {
                match snapshot.call.gsm_unavailable_reason.as_str() {
                    "Audio unavailable" => "Audio unavailable",
                    "Modem unavailable" => "Modem unavailable",
                    "Call audio failed" => "Call audio failed",
                    reason if reason.trim().is_empty() => "Audio unavailable",
                    _ => "Modem unavailable",
                }
            }
            CallOverlayKind::Incoming
                if snapshot.call.session_phase
                    == Some(yoyopod_protocol::call::CallPhase::Answering)
                    || !snapshot.call.accept_enabled
                        && snapshot.call.session_phase
                            == Some(yoyopod_protocol::call::CallPhase::Preparing) =>
            {
                "CONNECTING..."
            }
            CallOverlayKind::Incoming => "INCOMING",
            CallOverlayKind::Outgoing => "CALLING...",
            CallOverlayKind::Active => "IN CALL",
        }
        .to_string(),
        name,
        initial,
        avatar_rgb: super::talk::contact_color(contact_index.unwrap_or(3)),
        duration,
        muted: snapshot.call.muted,
        focus_index: focus,
    }
}

pub fn overlay_scene(
    screen: UiScreen,
    defaults: &SceneDefaults,
    modal: crate::scene::Modal,
) -> Scene {
    Scene {
        id: SceneId::new(screen),
        backdrop: defaults.backdrop(0x3ddd53),
        stage: defaults.stage,
        context: None,
        decks: Vec::new(),
        cursor: None,
        fx: defaults.fx_layer(0x3ddd53),
        modal: Some(modal),
        timelines: defaults.fx_timelines(),
    }
}

fn row_model(item: &ListItemSnapshot) -> RowModel {
    RowModel {
        id: item.id.clone(),
        title: item.title.clone(),
        subtitle: item.subtitle.clone(),
        icon_key: item.icon_key.clone(),
        selected: false,
    }
}

#[cfg(test)]
mod gsm_provider_tests {
    use super::*;
    use yoyopod_protocol::call::{CallPhase, CallTransport, SessionKey};

    #[test]
    fn gsm_provider_blocked_navigator_suppresses_answer_and_keeps_targeted_cancel() {
        use yoyopod_protocol::call::{CallAction, CallCommand, RejectReason};
        use yoyopod_protocol::ui::{CallIntent, InputAction, UiIntent};
        let key = SessionKey {
            transport: CallTransport::Gsm,
            generation: 9,
            call_id: "gsm-incoming-1".into(),
        };
        let mut runtime = crate::application::UiRuntime::default();
        runtime.snapshot.call.state = "incoming".into();
        runtime.snapshot.call.session = Some(key.clone());
        runtime.snapshot.call.session_phase = Some(CallPhase::Ringing);
        runtime.snapshot.call.gsm_available = false;
        runtime.snapshot.call.gsm_unavailable_reason = "Audio unavailable".into();
        runtime.snapshot.call.accept_enabled = false;
        crate::application::navigator::apply_runtime_preemption(&mut runtime);
        assert_eq!(runtime.focus_index, 0);
        runtime.handle_input(InputAction::Select, 1);
        assert!(runtime.take_intents().is_empty());
        runtime.handle_input(InputAction::Advance, 2);
        assert_eq!(runtime.focus_index, 1);
        runtime.handle_input(InputAction::Select, 3);
        assert_eq!(
            runtime.take_intents(),
            vec![UiIntent::Call(CallIntent::Session(CallCommand {
                key,
                action: CallAction::Reject(RejectReason::Cancelled)
            }))]
        );
    }

    #[test]
    fn gsm_provider_blocked_incoming_uses_existing_state_slot_and_focus() {
        let mut snapshot = yoyopod_protocol::ui::RuntimeSnapshot::default();
        snapshot.call.session = Some(SessionKey {
            transport: CallTransport::Gsm,
            generation: 9,
            call_id: "gsm-incoming-1".into(),
        });
        snapshot.call.accept_enabled = false;
        snapshot.call.gsm_available = false;
        snapshot.call.gsm_unavailable_reason = "Audio unavailable".into();
        for phase in [CallPhase::Preparing, CallPhase::Ringing, CallPhase::Ending] {
            snapshot.call.session_phase = Some(phase);
            let model = call_overlay_model(&snapshot, CallOverlayKind::Incoming, 0);
            assert!(!model.accept_enabled);
            assert_eq!(model.state, "Audio unavailable");
            assert_eq!(model.focus_index, 0);
            assert_eq!(
                call_overlay_model(&snapshot, CallOverlayKind::Incoming, 1).focus_index,
                1
            );
        }
        snapshot.call.gsm_unavailable_reason =
            "Selected modem lost; native reconciliation required".into();
        assert_eq!(
            call_overlay_model(&snapshot, CallOverlayKind::Incoming, 0).state,
            "Modem unavailable"
        );
        snapshot.call.gsm_unavailable_reason.clear();
        assert_eq!(
            call_overlay_model(&snapshot, CallOverlayKind::Incoming, 0).state,
            "Audio unavailable"
        );
    }
}
