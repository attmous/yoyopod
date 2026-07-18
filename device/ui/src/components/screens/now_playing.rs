use yoyopod_protocol::ui::{RuntimeSnapshot, UiScreen};

use crate::engine::Key;
use crate::scene::{
    Backdrop, Deck, DeckItem, DeckItemAnim, DeckKind, ItemRender, PlayerHeroArtwork,
    PlayerHeroModel, RegionId, Scene, SceneDefaults, SceneId,
};

const LISTEN_STAGE_LIME: u32 = 0xE6FDE0;

pub struct NowPlayingProps {
    pub defaults: SceneDefaults,
    pub model: PlayerHeroModel,
}

pub fn props_from(
    snapshot: &RuntimeSnapshot,
    focus: usize,
    defaults: SceneDefaults,
) -> NowPlayingProps {
    let context = if snapshot.music.artist.trim().is_empty() {
        "NOW PLAYING".to_string()
    } else {
        snapshot.music.artist.to_uppercase()
    };
    NowPlayingProps {
        defaults,
        model: PlayerHeroModel {
            context,
            title: snapshot.music.title.clone(),
            elapsed: snapshot.music.elapsed_text.clone(),
            total: snapshot.music.total_text.clone(),
            progress_permille: snapshot.music.progress_permille.clamp(0, 1000),
            playing: snapshot.music.playing,
            focus_index: focus.min(2),
            accent: 0x9DFC7C,
            artwork: PlayerHeroArtwork::Track {
                icon_key: "music_note".to_string(),
                fill_rgb: 0xE8A93C,
            },
            left_icon_key: "prev_sm".to_string(),
            right_icon_key: "next_sm".to_string(),
        },
    }
}

pub fn scene(props: &NowPlayingProps) -> Scene {
    Scene {
        id: SceneId::new(UiScreen::NowPlaying),
        backdrop: Backdrop::Solid(LISTEN_STAGE_LIME),
        stage: props.defaults.stage,
        context: None,
        decks: vec![Deck {
            kind: DeckKind::Page,
            region: RegionId::Auto,
            items: vec![DeckItem {
                key: Key::Static("now_playing"),
                render: ItemRender::PlayerHero(props.model.clone()),
            }],
            focus_index: 0,
            focus_policy: crate::scene::FocusPolicy::None,
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

#[cfg(test)]
mod tests {
    use super::*;
    use crate::scene::defaults_for;

    #[test]
    fn now_playing_uses_the_arc_hero_and_tracks_transport_focus() {
        let mut snapshot = RuntimeSnapshot::default();
        snapshot.music.playing = true;
        snapshot.music.progress_permille = 420;
        let props = props_from(&snapshot, 1, defaults_for(UiScreen::NowPlaying));
        let scene = scene(&props);

        assert_eq!(scene.backdrop, Backdrop::Solid(LISTEN_STAGE_LIME));
        assert_eq!(scene.fx, Default::default());
        let ItemRender::PlayerHero(hero) = &scene.decks[0].items[0].render else {
            panic!("NowPlaying must render the player hero");
        };
        assert_eq!(hero.progress_permille, 420);
        assert!(hero.playing);
        assert_eq!(hero.focus_index, 1);
    }
}
