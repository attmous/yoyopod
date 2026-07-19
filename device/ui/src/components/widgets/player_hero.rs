use crate::engine::{Element, Key};
use crate::scene::{roles, PlayerHeroModel, PlayerHeroVariant};
use crate::ElementKind;

const INK: u32 = 0x1B1B1F;
const IDLE_TRANSPORT_OPACITY: u8 = 140;

pub fn player_hero(model: &PlayerHeroModel) -> Element {
    match &model.variant {
        PlayerHeroVariant::Music { .. } => music_player_hero(model),
        PlayerHeroVariant::VoiceReplay => replay_player_hero(model),
    }
}

fn music_player_hero(model: &PlayerHeroModel) -> Element {
    Element::new(ElementKind::Container, Some(roles::HERO_PLAYER))
        .child(
            Element::new(ElementKind::Label, Some(roles::HERO_CONTEXT))
                .key(Key::Static("hero_context"))
                .text(&model.context),
        )
        .child(
            Element::new(ElementKind::Arc, Some(roles::HERO_ARC))
                .key(Key::Static("hero_arc"))
                .progress(model.progress_permille)
                .accent(model.accent),
        )
        .child(artwork(model))
        .child(transport_image(
            roles::HERO_PREV,
            "hero_previous",
            &model.left_icon_key,
            model.focus_index == 0,
        ))
        .child(
            Element::new(ElementKind::Container, Some(roles::HERO_PLAY))
                .key(Key::Static("hero_play"))
                .accent(model.accent)
                .selected(model.focus_index == 1)
                .scale_permille(if model.focus_index == 1 { 1100 } else { 1000 })
                .child(
                    Element::new(ElementKind::Image, Some(roles::HERO_PLAY_ICON))
                        .key(Key::Static("hero_play_icon"))
                        .icon(if model.playing { "pause_sm" } else { "play_sm" })
                        .accent(INK),
                ),
        )
        .child(transport_image(
            roles::HERO_NEXT,
            "hero_next",
            &model.right_icon_key,
            model.focus_index == 2,
        ))
        .child(
            Element::new(ElementKind::Label, Some(roles::HERO_TIME_L))
                .key(Key::Static("hero_elapsed"))
                .text(&model.elapsed),
        )
        .child(
            Element::new(ElementKind::Label, Some(roles::HERO_TIME_R))
                .key(Key::Static("hero_total"))
                .text(&model.total),
        )
        .child(
            Element::new(ElementKind::Label, Some(roles::HERO_TITLE))
                .key(Key::Static("hero_title"))
                .text(&model.title),
        )
}

fn artwork(model: &PlayerHeroModel) -> Element {
    let opacity = if model.playing { 255 } else { 179 };
    match &model.variant {
        PlayerHeroVariant::Music { icon_key, fill_rgb } => {
            Element::new(ElementKind::Container, Some(roles::HERO_ART))
                .key(Key::Static("hero_art"))
                .accent(*fill_rgb)
                .opacity(opacity)
                .child(
                    Element::new(ElementKind::Image, Some(roles::HERO_ART_ICON))
                        .key(Key::Static("hero_art_icon"))
                        .icon(icon_key)
                        .accent(INK),
                )
        }
        PlayerHeroVariant::VoiceReplay => unreachable!("Replay has no artwork tile"),
    }
}

fn replay_player_hero(model: &PlayerHeroModel) -> Element {
    Element::new(ElementKind::Container, Some(roles::HERO_PLAYER))
        .child(
            Element::new(ElementKind::Label, Some(roles::HERO_CONTEXT))
                .key(Key::Static("hero_context"))
                .text(&model.context),
        )
        .child(
            Element::new(ElementKind::Arc, Some(roles::HERO_ARC))
                .key(Key::Static("hero_arc"))
                .progress(model.progress_permille)
                .accent(model.accent),
        )
        .child(replay_transport(
            roles::REPLAY_DELETE,
            roles::REPLAY_DELETE_ICON,
            "replay_delete",
            &model.left_icon_key,
            model.focus_index == 0,
            true,
        ))
        .child(
            Element::new(ElementKind::Container, Some(roles::REPLAY_PLAY))
                .key(Key::Static("replay_play"))
                .accent(model.accent)
                .selected(model.focus_index == 1)
                .child(
                    Element::new(ElementKind::Image, Some(roles::REPLAY_PLAY_ICON))
                        .key(Key::Static("replay_play_icon"))
                        .icon(if model.playing { "pause_sm" } else { "play_sm" })
                        .accent(INK),
                ),
        )
        .child(replay_transport(
            roles::REPLAY_NEXT,
            roles::REPLAY_NEXT_ICON,
            "replay_next",
            &model.right_icon_key,
            model.focus_index == 2,
            model.right_enabled,
        ))
        .child(
            Element::new(ElementKind::Label, Some(roles::HERO_TIME_L))
                .key(Key::Static("hero_elapsed"))
                .text(&model.elapsed),
        )
        .child(
            Element::new(ElementKind::Label, Some(roles::HERO_TIME_R))
                .key(Key::Static("hero_total"))
                .text(&model.total),
        )
        .child(
            Element::new(ElementKind::Label, Some(roles::REPLAY_TITLE))
                .key(Key::Static("replay_title"))
                .text(&model.title),
        )
        .child(
            Element::new(ElementKind::Label, Some(roles::REPLAY_META))
                .key(Key::Static("replay_meta"))
                .text(&model.subtitle),
        )
}

fn replay_transport(
    role: &'static str,
    icon_role: &'static str,
    key: &'static str,
    icon: &str,
    focused: bool,
    enabled: bool,
) -> Element {
    Element::new(ElementKind::Container, Some(role))
        .key(Key::Static(key))
        .selected(focused && enabled)
        .opacity(if !enabled {
            48
        } else if focused {
            255
        } else {
            IDLE_TRANSPORT_OPACITY
        })
        .child(
            Element::new(ElementKind::Image, Some(icon_role))
                .key(Key::String(format!("{key}:icon")))
                .icon(icon)
                .accent(INK),
        )
}

fn transport_image(role: &'static str, key: &'static str, icon: &str, focused: bool) -> Element {
    Element::new(ElementKind::Image, Some(role))
        .key(Key::Static(key))
        .icon(icon)
        .accent(INK)
        .selected(focused)
        .opacity(if focused { 255 } else { IDLE_TRANSPORT_OPACITY })
        .scale_permille(if focused { 1100 } else { 1000 })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn replay_uses_the_disc_as_the_play_control_and_disables_end_of_queue() {
        let hero = player_hero(&PlayerHeroModel {
            context: "REPLAY".to_string(),
            title: "Mama".to_string(),
            subtitle: "Recording 5 of 5".to_string(),
            elapsed: "0:06".to_string(),
            total: "0:48".to_string(),
            progress_permille: 125,
            playing: true,
            focus_index: 1,
            accent: 0xA9A6E5,
            variant: PlayerHeroVariant::VoiceReplay,
            left_icon_key: "trash_sm".to_string(),
            right_icon_key: "next_sm".to_string(),
            right_enabled: false,
        });

        let play = &hero.children[3];
        assert_eq!(play.role, Some(roles::REPLAY_PLAY));
        assert_eq!(play.props.selected, Some(true));
        assert_eq!(play.children[0].props.icon_key.as_deref(), Some("pause_sm"));
        assert_eq!(
            hero.children[2].children[0].props.icon_key.as_deref(),
            Some("trash_sm")
        );
        assert_eq!(hero.children[4].props.opacity, Some(48));
        assert_eq!(hero.children[7].props.text.as_deref(), Some("Mama"));
        assert_eq!(
            hero.children[8].props.text.as_deref(),
            Some("Recording 5 of 5")
        );
    }
}
