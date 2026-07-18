use crate::engine::{Element, Key};
use crate::scene::{roles, PlayerHeroArtwork, PlayerHeroModel};
use crate::ElementKind;

const INK: u32 = 0x1B1B1F;
const IDLE_TRANSPORT_OPACITY: u8 = 140;

pub fn player_hero(model: &PlayerHeroModel) -> Element {
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
    match &model.artwork {
        PlayerHeroArtwork::Track { icon_key, fill_rgb } => {
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
        PlayerHeroArtwork::Contact { initial, fill_rgb } => {
            Element::new(ElementKind::Container, Some(roles::HERO_AVATAR))
                .key(Key::Static("hero_avatar"))
                .accent(*fill_rgb)
                .opacity(opacity)
                .child(
                    Element::new(ElementKind::Label, Some(roles::HERO_AVATAR_INITIAL))
                        .key(Key::Static("hero_avatar_initial"))
                        .text(initial)
                        .accent(INK),
                )
        }
    }
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
