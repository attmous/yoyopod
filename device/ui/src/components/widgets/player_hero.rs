use crate::engine::{Element, Key};
use crate::scene::{roles, PlayerHeroModel};
use crate::ElementKind;

const LISTEN_LIME: u32 = 0x9DFC7C;
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
                .accent(LISTEN_LIME),
        )
        .child(
            Element::new(ElementKind::Container, Some(roles::HERO_ART))
                .key(Key::Static("hero_art"))
                .opacity(if model.playing { 255 } else { 179 })
                .child(
                    Element::new(ElementKind::Image, Some(roles::HERO_ART_ICON))
                        .key(Key::Static("hero_art_icon"))
                        .icon("listen")
                        .accent(INK),
                ),
        )
        .child(transport_image(
            roles::HERO_PREV,
            "hero_previous",
            "prev_sm",
            model.focus_index == 0,
        ))
        .child(
            Element::new(ElementKind::Container, Some(roles::HERO_PLAY))
                .key(Key::Static("hero_play"))
                .accent(LISTEN_LIME)
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
            "next_sm",
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

fn transport_image(
    role: &'static str,
    key: &'static str,
    icon: &'static str,
    focused: bool,
) -> Element {
    Element::new(ElementKind::Image, Some(role))
        .key(Key::Static(key))
        .icon(icon)
        .accent(INK)
        .selected(focused)
        .opacity(if focused { 255 } else { IDLE_TRANSPORT_OPACITY })
        .scale_permille(if focused { 1100 } else { 1000 })
}
