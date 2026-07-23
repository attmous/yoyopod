use crate::animation::{presets::WATCH_ORBIT_TIMELINE_ID, ActorRef, TimelineRef, TrackIndex};
use crate::components::primitives::{container, image, label};
use crate::engine::{AnimSlot, Element, Key};
use crate::scene::{roles, RegionId, WatchFaceModel};
use crate::ElementKind;

const LIME: u32 = 0xA8F06A;

pub fn watch_face(model: &WatchFaceModel) -> Element {
    container(roles::WATCH_FACE)
        .key(Key::Static("watch_face"))
        .child(orbit_layer())
        .child(
            label(roles::WATCH_DATE)
                .key(Key::Static("watch_date"))
                .text(&model.date),
        )
        .child(
            label(roles::WATCH_TIME)
                .key(Key::Static("watch_time_bold_left"))
                .text(&model.time)
                .scale_permille(1_200),
        )
        .child(
            label(roles::WATCH_TIME)
                .key(Key::Static("watch_time_bold_center"))
                .text(&model.time)
                .scale_permille(1_200),
        )
        .child(
            label(roles::WATCH_TIME)
                .key(Key::Static("watch_time_bold_right"))
                .text(&model.time)
                .scale_permille(1_200),
        )
        .child(battery_complication(model))
}

fn orbit_layer() -> Element {
    container(roles::WATCH_ORBIT_LAYER)
        .key(Key::Static("watch_orbit_layer"))
        .actor(ActorRef::Region(RegionId::Backdrop))
        .child(orbit_segment(
            roles::WATCH_ORBIT_CYAN,
            "watch_orbit_cyan",
            1,
        ))
        .child(orbit_segment(
            roles::WATCH_ORBIT_ORANGE,
            "watch_orbit_orange",
            2,
        ))
        .child(orbit_segment(
            roles::WATCH_ORBIT_VIOLET,
            "watch_orbit_violet",
            3,
        ))
        .child(orbit_segment(
            roles::WATCH_ORBIT_LIME,
            "watch_orbit_lime",
            4,
        ))
        .child(orbit_dot(roles::WATCH_DOT_TOP, "watch_dot_top", 1))
        .child(orbit_dot(roles::WATCH_DOT_RIGHT, "watch_dot_right", 2))
        .child(orbit_dot(roles::WATCH_DOT_BOTTOM, "watch_dot_bottom", 3))
        .child(orbit_dot(roles::WATCH_DOT_LEFT, "watch_dot_left", 4))
}

fn orbit_segment(role: &'static str, key: &'static str, track: usize) -> Element {
    Element::new(ElementKind::Arc, Some(role))
        .key(Key::Static(key))
        .with_anim(orbit_anim(track))
}

fn orbit_dot(role: &'static str, key: &'static str, track: usize) -> Element {
    container(role)
        .key(Key::Static(key))
        .with_anim(orbit_anim(track))
}

fn orbit_anim(track: usize) -> AnimSlot {
    AnimSlot {
        timeline: TimelineRef(WATCH_ORBIT_TIMELINE_ID),
        track: TrackIndex(track),
    }
}

fn battery_complication(model: &WatchFaceModel) -> Element {
    container(roles::WATCH_BATTERY_CARD)
        .key(Key::Static("watch_battery_card"))
        .child(
            image(roles::WATCH_BATTERY_ICON)
                .key(Key::Static("watch_battery_icon"))
                .icon(battery_icon_key(model.battery_percent))
                .accent(LIME)
                .scale_permille(1_500),
        )
        .child(
            image(roles::WATCH_CHARGE_ICON)
                .key(Key::Static("watch_charge_icon"))
                .icon("status_charge")
                .accent(LIME)
                .scale_permille(1_400)
                .visible(model.power_available && model.charging),
        )
        .child(
            label(roles::WATCH_BATTERY_LABEL)
                .key(Key::Static("watch_battery_label"))
                .text(battery_label(model)),
        )
}

fn battery_icon_key(percent: i32) -> &'static str {
    match percent.clamp(0, 100) {
        0 => "status_battery_empty",
        1..=25 => "status_battery_1",
        26..=50 => "status_battery_2",
        51..=75 => "status_battery_3",
        _ => "status_battery_full",
    }
}

fn battery_label(model: &WatchFaceModel) -> String {
    if model.power_available {
        format!("{}%", model.battery_percent.clamp(0, 100))
    } else {
        "--%".to_string()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::engine::flatten;
    use crate::scene::{
        Backdrop, Deck, DeckItem, DeckItemAnim, DeckKind, FocusPolicy, FxLayer, RegionId, Scene,
        SceneGraph, SceneId, Stage,
    };
    use crate::theme::ColorScheme;
    use yoyopod_protocol::ui::UiScreen;

    #[test]
    fn battery_label_clamps_and_reports_unavailable_power() {
        let mut model = WatchFaceModel {
            date: "THU 23 JUL".to_string(),
            time: "09:41".to_string(),
            battery_percent: 116,
            charging: false,
            power_available: true,
        };
        assert_eq!(battery_label(&model), "100%");
        assert_eq!(
            battery_icon_key(model.battery_percent),
            "status_battery_full"
        );

        model.power_available = false;
        assert_eq!(battery_label(&model), "--%");
    }

    #[test]
    fn watch_face_contains_four_equal_orbit_roles() {
        let model = WatchFaceModel {
            date: "THU 23 JUL".to_string(),
            time: "09:41".to_string(),
            battery_percent: 86,
            charging: true,
            power_available: true,
        };
        let scene = Scene {
            id: SceneId::new(UiScreen::Hub),
            backdrop: Backdrop::Solid(0x090B14),
            stage: Stage::CenteredHeroIcon,
            context: None,
            decks: vec![Deck {
                kind: DeckKind::Page,
                region: RegionId::Auto,
                items: vec![DeckItem {
                    key: Key::Static("watch"),
                    render: crate::scene::ItemRender::WatchFace(model),
                }],
                focus_index: 0,
                focus_policy: FocusPolicy::None,
                item_anim: DeckItemAnim::None,
                swap_anim: None,
                recycle_window: Some(1),
            }],
            cursor: None,
            fx: FxLayer::default(),
            modal: None,
            timelines: Vec::new(),
        };
        let graph = SceneGraph {
            color_scheme: ColorScheme::Dark,
            hud: crate::scene::HudScene::new(
                container(roles::HUD).key(Key::Static("hud")).visible(false),
            ),
            active: scene,
            history: Vec::new(),
            modal_stack: Vec::new(),
            global_clock: Default::default(),
        };
        let root = flatten::flatten(&graph);
        let orbit_roles = [
            roles::WATCH_ORBIT_CYAN,
            roles::WATCH_ORBIT_ORANGE,
            roles::WATCH_ORBIT_VIOLET,
            roles::WATCH_ORBIT_LIME,
        ];
        for role in orbit_roles {
            assert_eq!(count_role(&root, role), 1, "missing orbit role {role}");
        }
        assert_eq!(count_role(&root, roles::WATCH_ORBIT_LAYER), 1);
        assert_eq!(count_role(&root, roles::WATCH_TIME), 3);
        assert_eq!(
            find_role(&root, roles::WATCH_TIME).props.scale_permille,
            Some(1_200)
        );
        assert_eq!(
            find_role(&root, roles::WATCH_BATTERY_ICON)
                .props
                .scale_permille,
            Some(1_500)
        );
    }

    fn find_role<'a>(element: &'a Element, role: &'static str) -> &'a Element {
        if element.role == Some(role) {
            return element;
        }
        element
            .children
            .iter()
            .find_map(|child| (count_role(child, role) > 0).then(|| find_role(child, role)))
            .unwrap_or_else(|| panic!("missing role {role}"))
    }

    fn count_role(element: &Element, role: &'static str) -> usize {
        usize::from(element.role == Some(role))
            + element
                .children
                .iter()
                .map(|child| count_role(child, role))
                .sum::<usize>()
    }
}
