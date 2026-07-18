use yoyopod_protocol::ui::{ListItemSnapshot, RuntimeSnapshot, UiScreen};

use crate::engine::Key;
use crate::scene::{
    Backdrop, ContextLabelModel, Deck, DeckItem, DeckItemAnim, DeckKind, FocusPolicy, ItemRender,
    RecordingPanelModel, RegionId, Scene, SceneContext, SceneDefaults, SceneId, WheelBadgeKind,
    WheelBadgeModel, WheelItemModel, WheelItemVariant,
};

const TALK_STAGE_PERI: u32 = 0xE7E5F7;
const TALK_STAGE_RECORDING: u32 = 0xE5443B;

pub struct TalkContactProps {
    pub defaults: SceneDefaults,
    pub context: String,
    pub actions: Vec<DeckItem>,
    pub focus: usize,
    pub recording: bool,
    pub recording_duration_ms: i32,
    pub capture_level_permille: i32,
}

pub fn props_from(
    snapshot: &RuntimeSnapshot,
    focus: usize,
    selected_contact: Option<&ListItemSnapshot>,
    defaults: SceneDefaults,
) -> TalkContactProps {
    let contact = selected_contact.or_else(|| snapshot.call.contacts.first());
    TalkContactProps {
        defaults,
        context: contact
            .map(|contact| contact.title.trim().to_uppercase())
            .filter(|title| !title.is_empty())
            .unwrap_or_else(|| "CONTACT".to_string()),
        actions: actions(snapshot, contact),
        focus,
        recording: snapshot.voice.ptt_active
            || snapshot.voice.capture_in_flight
            || snapshot.voice.phase.eq_ignore_ascii_case("recording"),
        recording_duration_ms: snapshot.voice.recording_duration_ms.max(0),
        capture_level_permille: snapshot.voice.capture_level_permille.clamp(0, 1000),
    }
}

pub fn scene(props: &TalkContactProps) -> Scene {
    if props.recording {
        return recording_scene(props);
    }
    Scene {
        id: SceneId::new(UiScreen::TalkContact),
        backdrop: Backdrop::Solid(TALK_STAGE_PERI),
        stage: props.defaults.stage,
        context: Some(SceneContext::Label(ContextLabelModel::new(&props.context))),
        decks: vec![Deck {
            kind: DeckKind::Wheel,
            region: RegionId::Auto,
            items: props.actions.clone(),
            focus_index: props.focus,
            focus_policy: FocusPolicy::Wrap,
            item_anim: DeckItemAnim::ScaleOnFocus {
                from_permille: 700,
                to_permille: 1_000,
            },
            swap_anim: None,
            recycle_window: Some(3),
        }],
        cursor: None,
        fx: Default::default(),
        modal: None,
        timelines: Vec::new(),
    }
}

fn recording_scene(props: &TalkContactProps) -> Scene {
    Scene {
        id: SceneId::new(UiScreen::TalkContact),
        backdrop: Backdrop::Solid(TALK_STAGE_RECORDING),
        stage: props.defaults.stage,
        context: None,
        decks: vec![Deck {
            kind: DeckKind::Buttons,
            region: RegionId::Auto,
            items: vec![DeckItem {
                key: Key::Static("held_recording"),
                render: ItemRender::RecordingPanel(RecordingPanelModel {
                    context: props.context.clone(),
                    duration_ms: props.recording_duration_ms,
                    level_permille: props.capture_level_permille,
                }),
            }],
            focus_index: 0,
            focus_policy: FocusPolicy::None,
            item_anim: DeckItemAnim::None,
            swap_anim: None,
            recycle_window: Some(1),
        }],
        cursor: None,
        fx: Default::default(),
        modal: None,
        timelines: Vec::new(),
    }
}

fn actions(
    snapshot: &RuntimeSnapshot,
    selected_contact: Option<&ListItemSnapshot>,
) -> Vec<DeckItem> {
    let unread = selected_contact
        .and_then(|contact| snapshot.call.unread_voice_notes_by_contact.get(&contact.id))
        .copied()
        .unwrap_or(0);
    vec![
        action("call", "Call", "call", None),
        action("record", "Hold to record", "mic", None),
        action(
            "replay",
            "Replay",
            "play",
            (unread > 0).then(|| WheelBadgeModel {
                label: if unread > 9 {
                    "9+".to_string()
                } else {
                    unread.to_string()
                },
                kind: WheelBadgeKind::Count,
            }),
        ),
    ]
}

fn action(
    key: &'static str,
    title: &'static str,
    icon_key: &'static str,
    badge: Option<WheelBadgeModel>,
) -> DeckItem {
    DeckItem {
        key: Key::Static(key),
        render: ItemRender::Wheel(WheelItemModel {
            title: title.to_string(),
            subtitle: String::new(),
            variant: WheelItemVariant::Action {
                icon_key: icon_key.to_string(),
                badge,
            },
        }),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::scene::{defaults_for, roles};

    fn contact() -> ListItemSnapshot {
        ListItemSnapshot::new("sip:mama@example.test", "Mama", "", "mono:M")
    }

    #[test]
    fn talk_contact_is_the_designed_three_action_wheel() {
        let mama = contact();
        let mut snapshot = RuntimeSnapshot::default();
        snapshot.call.contacts = vec![mama.clone()];
        let scene = scene(&props_from(
            &snapshot,
            1,
            Some(&mama),
            defaults_for(UiScreen::TalkContact),
        ));

        assert_eq!(scene.backdrop, Backdrop::Solid(TALK_STAGE_PERI));
        assert_eq!(
            scene.context.as_ref().and_then(SceneContext::label),
            Some(&ContextLabelModel::new("MAMA"))
        );
        assert_eq!(scene.decks[0].kind, DeckKind::Wheel);
        assert_eq!(scene.decks[0].focus_policy, FocusPolicy::Wrap);
        assert_eq!(scene.decks[0].focus_index, 1);
        assert_eq!(scene.decks[0].items.len(), 3);
        assert!(scene.cursor.is_none());

        let focused = scene.decks[0].element(0);
        assert_eq!(focused.children[2].role, Some(roles::TALK_WHEEL_ITEM));
        assert_eq!(
            focused.children[2].children[0].role,
            Some(roles::WHEEL_ICON)
        );
    }

    #[test]
    fn replay_badge_uses_the_selected_contacts_unread_count() {
        let mama = contact();
        let mut snapshot = RuntimeSnapshot::default();
        snapshot.call.contacts = vec![mama.clone()];
        snapshot
            .call
            .unread_voice_notes_by_contact
            .insert(mama.id.clone(), 12);

        let items = actions(&snapshot, Some(&mama));
        let ItemRender::Wheel(WheelItemModel {
            variant: WheelItemVariant::Action { badge, .. },
            ..
        }) = &items[2].render
        else {
            panic!("Replay must use the action wheel variant");
        };
        assert_eq!(
            badge,
            &Some(WheelBadgeModel {
                label: "9+".to_string(),
                kind: WheelBadgeKind::Count,
            })
        );
    }

    #[test]
    fn live_recording_replaces_the_wheel_with_the_full_bleed_meter() {
        let mama = contact();
        let mut snapshot = RuntimeSnapshot::default();
        snapshot.call.contacts = vec![mama.clone()];
        snapshot.voice.phase = "recording".to_string();
        snapshot.voice.ptt_active = true;
        snapshot.voice.recording_duration_ms = 7_420;
        snapshot.voice.capture_level_permille = 618;

        let scene = scene(&props_from(
            &snapshot,
            1,
            Some(&mama),
            defaults_for(UiScreen::TalkContact),
        ));

        assert_eq!(scene.backdrop, Backdrop::Solid(TALK_STAGE_RECORDING));
        assert!(scene.context.is_none());
        assert_eq!(scene.decks[0].kind, DeckKind::Buttons);
        assert_eq!(scene.decks[0].focus_policy, FocusPolicy::None);
        assert!(scene.cursor.is_none());
        let ItemRender::RecordingPanel(panel) = &scene.decks[0].items[0].render else {
            panic!("recording must replace the action wheel with the recording panel");
        };
        assert_eq!(panel.context, "MAMA");
        assert_eq!(panel.duration_ms, 7_420);
        assert_eq!(panel.level_permille, 618);
    }
}
