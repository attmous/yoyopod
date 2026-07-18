use yoyopod_protocol::ui::{ListItemSnapshot, UiScreen};

use crate::engine::Key;
use crate::scene::{
    Backdrop, Deck, DeckItem, DeckItemAnim, DeckKind, FocusPolicy, ItemRender, RegionId, Scene,
    SceneDefaults, SceneId, WheelHeaderModel, WheelItemModel, WheelItemVariant,
};

const LISTEN_STAGE_LIME: u32 = 0xE6FDE0;
const PLATE_COLORS: [u32; 4] = [0xE5443B, 0xE8A93C, 0xA9A6E5, 0xFFD06A];

pub fn models(items: &[ListItemSnapshot]) -> Vec<WheelItemModel> {
    items
        .iter()
        .map(|item| WheelItemModel {
            title: item.title.clone(),
            subtitle: item.subtitle.clone(),
            variant: WheelItemVariant::Media {
                initial: title_initial(&item.title),
                plate_rgb: plate_color(&item.id),
            },
        })
        .collect()
}

pub fn scene(
    screen: UiScreen,
    defaults: &SceneDefaults,
    header: WheelHeaderModel,
    items: &[WheelItemModel],
    focus: usize,
) -> Scene {
    let deck = Deck {
        kind: DeckKind::Wheel,
        region: RegionId::Auto,
        items: items
            .iter()
            .enumerate()
            .map(|(index, item)| DeckItem {
                key: Key::Indexed(index),
                render: ItemRender::Wheel(item.clone()),
            })
            .collect(),
        focus_index: focus,
        focus_policy: FocusPolicy::Wrap,
        item_anim: DeckItemAnim::None,
        swap_anim: None,
        recycle_window: Some(3),
    };
    Scene {
        id: SceneId::new(screen),
        backdrop: Backdrop::Solid(LISTEN_STAGE_LIME),
        stage: defaults.stage,
        context: Some(header),
        decks: vec![deck],
        cursor: None,
        fx: Default::default(),
        modal: None,
        timelines: Vec::new(),
    }
}

pub fn header(title: &str, item_count: usize, focus: usize) -> WheelHeaderModel {
    let counter = (item_count > 1).then(|| format!("{} / {item_count}", focus % item_count + 1));
    WheelHeaderModel::new(compact_context_title(title), counter)
}

fn compact_context_title(title: &str) -> String {
    let title = title.trim();
    let suffix = [" - ", " – ", " — "]
        .into_iter()
        .find_map(|separator| {
            title
                .rsplit_once(separator)
                .map(|(_, suffix)| suffix.trim())
        })
        .filter(|suffix| !suffix.is_empty())
        .unwrap_or(title);
    suffix.to_uppercase()
}

fn title_initial(title: &str) -> String {
    title
        .chars()
        .find(|character| character.is_alphanumeric())
        .map(|character| character.to_uppercase().collect())
        .unwrap_or_else(|| "?".to_string())
}

fn plate_color(id: &str) -> u32 {
    let hash = id
        .as_bytes()
        .iter()
        .fold(0xcbf29ce484222325_u64, |hash, byte| {
            (hash ^ u64::from(*byte)).wrapping_mul(0x100000001b3)
        });
    PLATE_COLORS[hash as usize % PLATE_COLORS.len()]
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn media_models_have_stable_initials_and_plate_colors() {
        let item = ListItemSnapshot::new("mix", "morning songs", "12 tracks", "playlist");
        let first = models(std::slice::from_ref(&item));
        let second = models(&[item]);
        assert_eq!(first, second);
        let WheelItemVariant::Media { initial, .. } = &first[0].variant else {
            panic!("media wheel must use the media variant");
        };
        assert_eq!(initial, "M");
    }

    #[test]
    fn media_header_keeps_title_and_counter_separate() {
        assert_eq!(
            header("Morning Songs", 12, 3),
            WheelHeaderModel::new("MORNING SONGS", Some("4 / 12".to_string()))
        );
        assert_eq!(
            header("Morning Songs", 1, 0),
            WheelHeaderModel::new("MORNING SONGS", None)
        );
        assert_eq!(
            header("Morning Songs", 0, 0),
            WheelHeaderModel::new("MORNING SONGS", None)
        );
    }

    #[test]
    fn media_header_prefers_a_specific_title_suffix() {
        assert_eq!(
            header("Open Classics - Holst", 3, 0),
            WheelHeaderModel::new("HOLST", Some("1 / 3".to_string()))
        );
    }
}
