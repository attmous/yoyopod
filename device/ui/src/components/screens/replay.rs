#[cfg(test)]
use yoyopod_protocol::ui::VoiceNoteSummarySnapshot;
use yoyopod_protocol::ui::{ListItemSnapshot, RuntimeSnapshot, UiScreen};

use crate::engine::Key;
use crate::scene::{
    Backdrop, Deck, DeckItem, DeckItemAnim, DeckKind, FocusPolicy, ItemRender, PlayerHeroModel,
    PlayerHeroVariant, RegionId, Scene, SceneDefaults, SceneId,
};

const TALK_STAGE_PERI: u32 = 0xE7E5F7;
const REPLAY_PERI: u32 = 0xA9A6E5;

pub struct ReplayProps {
    pub defaults: SceneDefaults,
    pub model: PlayerHeroModel,
}

pub fn props_from(
    snapshot: &RuntimeSnapshot,
    focus: usize,
    selected_contact: Option<&ListItemSnapshot>,
    replay_index: usize,
    defaults: SceneDefaults,
) -> ReplayProps {
    let contact = selected_contact.or_else(|| snapshot.call.contacts.first());
    let notes = contact
        .and_then(|contact| snapshot.call.voice_notes_by_contact.get(&contact.id))
        .map(Vec::as_slice)
        .unwrap_or_default();
    let note = notes.get(replay_index).or_else(|| notes.first());
    let current_file_matches = note.is_some_and(|note| {
        !note.local_file_path.is_empty()
            && note.local_file_path == snapshot.voice.playback_file_path
    });
    let duration_ms = note.map(|note| note.duration_ms.max(0)).unwrap_or_default();
    let elapsed_ms = if current_file_matches {
        snapshot.voice.playback_elapsed_ms.clamp(0, duration_ms)
    } else {
        0
    };
    let progress_permille = if duration_ms > 0 {
        (i64::from(elapsed_ms) * 1_000 / i64::from(duration_ms)).clamp(0, 1_000) as i32
    } else {
        0
    };
    let contact_name = contact
        .map(|contact| contact.title.trim())
        .filter(|name| !name.is_empty())
        .unwrap_or("Contact");
    let subtitle = if notes.is_empty() {
        "No recordings".to_string()
    } else {
        format!(
            "Recording {} of {}",
            replay_index.min(notes.len() - 1) + 1,
            notes.len()
        )
    };
    let has_next = replay_index + 1 < notes.len();

    ReplayProps {
        defaults,
        model: PlayerHeroModel {
            context: "REPLAY".to_string(),
            title: contact_name.to_string(),
            subtitle,
            elapsed: time_text(elapsed_ms),
            total: time_text(duration_ms),
            progress_permille,
            playing: current_file_matches && snapshot.voice.playback_active,
            focus_index: focus.min(2),
            accent: REPLAY_PERI,
            variant: PlayerHeroVariant::VoiceReplay,
            left_icon_key: "trash_sm".to_string(),
            right_icon_key: "next_sm".to_string(),
            right_enabled: has_next,
        },
    }
}

pub fn scene(props: &ReplayProps) -> Scene {
    Scene {
        id: SceneId::new(UiScreen::Replay),
        backdrop: Backdrop::Solid(TALK_STAGE_PERI),
        stage: props.defaults.stage,
        context: None,
        decks: vec![Deck {
            kind: DeckKind::Page,
            region: RegionId::Auto,
            items: vec![DeckItem {
                key: Key::Static("replay"),
                render: ItemRender::PlayerHero(props.model.clone()),
            }],
            focus_index: 0,
            focus_policy: FocusPolicy::None,
            item_anim: DeckItemAnim::None,
            swap_anim: None,
            recycle_window: None,
        }],
        cursor: None,
        fx: Default::default(),
        modal: None,
        timelines: Vec::new(),
    }
}

fn time_text(duration_ms: i32) -> String {
    let total_seconds = duration_ms.max(0) / 1_000;
    format!("{}:{:02}", total_seconds / 60, total_seconds % 60)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::scene::defaults_for;

    #[test]
    fn replay_reuses_arc_hero_with_contact_semantics() {
        let contact = ListItemSnapshot::new("sip:mama@example.test", "Mama", "", "mono:m");
        let mut snapshot = RuntimeSnapshot::default();
        snapshot.call.contacts.push(contact.clone());
        snapshot.call.voice_notes_by_contact.insert(
            contact.id.clone(),
            vec![VoiceNoteSummarySnapshot {
                message_id: "note-1".to_string(),
                local_file_path: "/tmp/note.wav".to_string(),
                duration_ms: 7_000,
                ..VoiceNoteSummarySnapshot::default()
            }],
        );
        snapshot.voice.playback_active = true;
        snapshot.voice.playback_file_path = "/tmp/note.wav".to_string();
        snapshot.voice.playback_elapsed_ms = 4_000;

        let props = props_from(
            &snapshot,
            1,
            Some(&contact),
            0,
            defaults_for(UiScreen::Replay),
        );
        assert_eq!(props.model.title, "Mama");
        assert_eq!(props.model.subtitle, "Recording 1 of 1");
        assert_eq!(props.model.elapsed, "0:04");
        assert_eq!(props.model.total, "0:07");
        assert_eq!(props.model.progress_permille, 571);
        assert!(props.model.playing);
        assert_eq!(props.model.left_icon_key, "trash_sm");
        assert!(!props.model.right_enabled);
        assert!(matches!(
            props.model.variant,
            PlayerHeroVariant::VoiceReplay
        ));
    }
}
