use yoyopod_protocol::ui::{ListItemSnapshot, RuntimeSnapshot, UiScreen};

use crate::engine::Key;
use crate::scene::{
    Backdrop, Deck, DeckItem, DeckItemAnim, DeckKind, EmptyStateModel, FocusPolicy, ItemRender,
    RegionId, Scene, SceneDefaults, SceneId, WheelBadgeKind, WheelBadgeModel, WheelItemModel,
    WheelItemVariant,
};

const TALK_STAGE_PERI: u32 = 0xE7E5F7;
const CONTACT_COLORS: [u32; 4] = [0xE8A93C, 0x9DFC7C, 0xF37767, 0xA9A6E5];

pub struct TalkProps {
    pub defaults: SceneDefaults,
    pub items: Vec<DeckItem>,
    pub focus: usize,
}

pub fn props_from(snapshot: &RuntimeSnapshot, focus: usize, defaults: SceneDefaults) -> TalkProps {
    TalkProps {
        defaults,
        items: contact_items(snapshot),
        focus,
    }
}

pub fn scene(props: &TalkProps) -> Scene {
    let deck = if props.items.is_empty() {
        Deck {
            kind: DeckKind::Grid,
            region: RegionId::Auto,
            items: vec![DeckItem {
                key: Key::Static("talk_empty"),
                render: ItemRender::EmptyState(EmptyStateModel {
                    icon_key: "plus".to_string(),
                    message: "No contacts yet.\nAsk a grown-up!".to_string(),
                    accent: 0xA9A6E5,
                }),
            }],
            focus_index: 0,
            focus_policy: FocusPolicy::None,
            item_anim: DeckItemAnim::None,
            swap_anim: None,
            recycle_window: Some(1),
        }
    } else {
        Deck {
            kind: DeckKind::Wheel,
            region: RegionId::Auto,
            items: props.items.clone(),
            focus_index: props.focus,
            focus_policy: FocusPolicy::Wrap,
            item_anim: DeckItemAnim::ScaleOnFocus {
                from_permille: 700,
                to_permille: 1_000,
            },
            swap_anim: None,
            recycle_window: Some(3),
        }
    };

    Scene {
        id: SceneId::new(UiScreen::Talk),
        backdrop: Backdrop::Solid(TALK_STAGE_PERI),
        stage: props.defaults.stage,
        context: None,
        decks: vec![deck],
        cursor: None,
        fx: Default::default(),
        modal: None,
        timelines: Vec::new(),
    }
}

fn contact_items(snapshot: &RuntimeSnapshot) -> Vec<DeckItem> {
    snapshot
        .call
        .contacts
        .iter()
        .enumerate()
        .map(|(index, contact)| DeckItem {
            key: Key::String(contact.id.clone()),
            render: ItemRender::Wheel(WheelItemModel {
                title: contact.title.clone(),
                subtitle: String::new(),
                variant: WheelItemVariant::Contact {
                    initial: contact_initial(contact),
                    avatar_rgb: CONTACT_COLORS[index % CONTACT_COLORS.len()],
                    badge: contact_badge(snapshot, contact),
                },
            }),
        })
        .collect()
}

pub(crate) fn contact_initial(contact: &ListItemSnapshot) -> String {
    contact
        .icon_key
        .strip_prefix("mono:")
        .and_then(|value| value.chars().find(|character| character.is_alphanumeric()))
        .or_else(|| {
            contact
                .title
                .chars()
                .find(|character| character.is_alphanumeric())
        })
        .map(|character| character.to_uppercase().collect())
        .unwrap_or_else(|| "?".to_string())
}

pub(crate) fn contact_color(snapshot: &RuntimeSnapshot, contact: &ListItemSnapshot) -> u32 {
    snapshot
        .call
        .contacts
        .iter()
        .position(|candidate| candidate.id == contact.id)
        .map(|index| CONTACT_COLORS[index % CONTACT_COLORS.len()])
        .unwrap_or(CONTACT_COLORS[0])
}

fn contact_badge(
    snapshot: &RuntimeSnapshot,
    contact: &ListItemSnapshot,
) -> Option<WheelBadgeModel> {
    let stuck = snapshot
        .call
        .latest_voice_note_by_contact
        .get(&contact.id)
        .is_some_and(|note| {
            note.direction.eq_ignore_ascii_case("outgoing")
                && matches!(
                    note.delivery_state.trim().to_ascii_lowercase().as_str(),
                    "failed" | "error"
                )
        });
    if stuck {
        return Some(WheelBadgeModel {
            label: "!".to_string(),
            kind: WheelBadgeKind::Stuck,
        });
    }

    snapshot
        .call
        .unread_voice_notes_by_contact
        .get(&contact.id)
        .copied()
        .filter(|count| *count > 0)
        .map(|count| WheelBadgeModel {
            label: count.to_string(),
            kind: WheelBadgeKind::Count,
        })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::scene::{defaults_for, roles};
    use yoyopod_protocol::ui::VoiceNoteSummarySnapshot;

    fn contact(id: &str, title: &str) -> ListItemSnapshot {
        let initial = title
            .chars()
            .find(|character| character.is_alphanumeric())
            .unwrap_or('?');
        ListItemSnapshot::new(id, title, "", format!("mono:{initial}"))
    }

    #[test]
    fn talk_root_is_the_contact_wheel_directly() {
        let mut snapshot = RuntimeSnapshot::default();
        snapshot.call.contacts = vec![
            contact("mama", "Mama"),
            contact("papa", "Papa"),
            contact("grandma", "Grandma"),
        ];
        snapshot
            .call
            .unread_voice_notes_by_contact
            .insert("mama".to_string(), 2);

        let scene = scene(&props_from(&snapshot, 0, defaults_for(UiScreen::Talk)));
        assert_eq!(scene.backdrop, Backdrop::Solid(TALK_STAGE_PERI));
        assert!(scene.context.is_none());
        assert_eq!(scene.decks[0].kind, DeckKind::Wheel);
        assert_eq!(scene.decks[0].focus_policy, FocusPolicy::Wrap);
        assert_eq!(scene.decks[0].items.len(), 3);

        let element = scene.decks[0].element(0);
        assert_eq!(element.children[2].role, Some(roles::TALK_WHEEL_ITEM));
        assert_eq!(
            element.children[2].children[0].role,
            Some(roles::WHEEL_AVATAR)
        );
        assert_eq!(
            element.children[2].children[2].role,
            Some(roles::WHEEL_BADGE)
        );
    }

    #[test]
    fn failed_outgoing_note_takes_priority_over_the_unread_count() {
        let contact = contact("mama", "Mama");
        let mut snapshot = RuntimeSnapshot::default();
        snapshot.call.contacts = vec![contact.clone()];
        snapshot
            .call
            .unread_voice_notes_by_contact
            .insert(contact.id.clone(), 2);
        snapshot.call.latest_voice_note_by_contact.insert(
            contact.id.clone(),
            VoiceNoteSummarySnapshot {
                direction: "outgoing".to_string(),
                delivery_state: "failed".to_string(),
                ..VoiceNoteSummarySnapshot::default()
            },
        );

        assert_eq!(
            contact_badge(&snapshot, &contact),
            Some(WheelBadgeModel {
                label: "!".to_string(),
                kind: WheelBadgeKind::Stuck,
            })
        );
    }

    #[test]
    fn empty_talk_root_uses_the_deboxed_grown_up_hint() {
        let snapshot = RuntimeSnapshot::default();
        let scene = scene(&props_from(&snapshot, 0, defaults_for(UiScreen::Talk)));

        assert_eq!(scene.decks[0].kind, DeckKind::Grid);
        assert_eq!(scene.decks[0].items.len(), 1);
        assert!(matches!(
            scene.decks[0].items[0].render,
            ItemRender::EmptyState(_)
        ));
    }
}
