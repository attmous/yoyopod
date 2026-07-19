use crate::animation::{presets, ActorRef, TimelineRef, TrackIndex};
use crate::components::widgets::{
    context_label as context_label_widget, wheel_header as wheel_header_widget,
};
use crate::scene::roles;
use crate::scene::{
    FxLayer, GlowBloom, Halo, HudScene, LayerSlot, Modal, ParticleField, PulseRing, Scene,
    SceneContext, SceneGraph, LAYER_ORDER,
};
use crate::ElementKind;

use super::{AnimSlot, Element, Key};

pub fn flatten(graph: &SceneGraph) -> Element {
    LAYER_ORDER
        .into_iter()
        .filter(|slot| slot.is_graph_overlay())
        .fold(
            Element::new(ElementKind::Container, Some(roles::SCENE_GRAPH))
                .key(Key::Static("scene_graph"))
                .child(scene_element(&graph.active)),
            |element, slot| match graph_overlay_element(graph, slot) {
                Some(layer) => element.child(layer),
                None => element,
            },
        )
}

pub fn scene_element(scene: &Scene) -> Element {
    let root = Element::new(ElementKind::Container, Some(roles::SCENE_ROOT))
        .key(Key::Scene {
            screen: scene.id.screen.as_str(),
            generation: scene.id.generation,
        })
        .actor(ActorRef::Screen)
        .with_anim(AnimSlot {
            timeline: TimelineRef(presets::SCENE_ENTER_TIMELINE_ID),
            track: TrackIndex(0),
        });
    LAYER_ORDER
        .into_iter()
        .filter(|slot| slot.is_scene_owned())
        .fold(root, |element, slot| {
            match scene_layer_element(scene, slot) {
                Some(layer) => element.child(layer),
                None => element,
            }
        })
}

fn scene_layer_element(scene: &Scene, slot: LayerSlot) -> Option<Element> {
    match slot {
        LayerSlot::Backdrop => Some(scene.backdrop.element()),
        LayerSlot::Stage => Some(stage_element(scene.stage)),
        LayerSlot::Decks => Some(decks_element(scene)),
        LayerSlot::Cursor => scene.cursor.as_ref().map(|cursor| cursor.element()),
        LayerSlot::Fx => fx_element(&scene.fx),
        LayerSlot::Hud | LayerSlot::Modal => None,
    }
}

fn graph_overlay_element(graph: &SceneGraph, slot: LayerSlot) -> Option<Element> {
    match slot {
        LayerSlot::Hud => Some(hud_element(&graph.hud)),
        LayerSlot::Modal => Some(modal_stack_element(&graph.modal_stack)),
        LayerSlot::Backdrop
        | LayerSlot::Stage
        | LayerSlot::Decks
        | LayerSlot::Cursor
        | LayerSlot::Fx => None,
    }
}

fn stage_element(_stage: crate::scene::Stage) -> Element {
    Element::new(ElementKind::Container, Some(roles::SCENE_STAGE)).key(Key::Static("stage"))
}

fn decks_element(scene: &Scene) -> Element {
    let root =
        Element::new(ElementKind::Container, Some(roles::SCENE_DECKS)).key(Key::Static("decks"));
    let root = scene
        .decks
        .iter()
        .enumerate()
        .fold(root, |element, (index, deck)| {
            element.child(deck.element(index))
        });
    match scene.context.as_ref() {
        Some(SceneContext::WheelHeader(header)) => root.child(wheel_header_widget(header)),
        Some(SceneContext::Label(label)) => root.child(context_label_widget(label)),
        None => root,
    }
}

fn hud_element(hud: &HudScene) -> Element {
    hud.element()
}

fn modal_stack_element(modal_stack: &[Modal]) -> Element {
    modal_stack.iter().enumerate().fold(
        Element::new(ElementKind::Container, Some(roles::MODAL_STACK))
            .key(Key::Static("modal_stack")),
        |element, (index, modal)| element.child(modal.element(index)),
    )
}

fn fx_element(fx: &FxLayer) -> Option<Element> {
    if fx.halos.is_empty() && fx.pulses.is_empty() && fx.particles.is_empty() && fx.glows.is_empty()
    {
        return None;
    }

    let mut element =
        Element::new(ElementKind::Container, Some(roles::SCENE_FX)).key(Key::Static("scene_fx"));
    for (index, halo) in fx.halos.iter().enumerate() {
        element = element.child(halo_element(index, halo));
    }
    for (index, pulse) in fx.pulses.iter().enumerate() {
        element = element.child(pulse_element(index, pulse));
    }
    for (field_index, field) in fx.particles.iter().enumerate() {
        for index in 0..field.count.min(8) {
            element = element.child(particle_element(field_index, index, field));
        }
    }
    for (index, glow) in fx.glows.iter().enumerate() {
        element = element.child(glow_element(index, glow));
    }
    Some(element)
}

fn halo_element(index: usize, halo: &Halo) -> Element {
    fx_target_element(
        roles::FX_HALO,
        Key::String(format!("fx:halo:{index}")),
        halo.target,
    )
    .accent(halo.color)
    .with_opacity(halo.max_opacity)
}

fn pulse_element(index: usize, pulse: &PulseRing) -> Element {
    fx_target_element(
        roles::FX_PULSE,
        Key::String(format!("fx:pulse:{index}")),
        pulse.target,
    )
    .accent(pulse.color)
    .scale_permille((pulse.max_radius * 1_000 / 62).clamp(100, 1_000))
    .with_opacity(if index == 0 { 72 } else { 48 })
}

fn particle_element(field_index: usize, index: u8, field: &ParticleField) -> Element {
    Element::new(ElementKind::Container, Some(roles::FX_PARTICLE))
        .key(Key::String(format!("fx:particle:{field_index}:{index}")))
        .region(field.region)
        .accent(field.color)
}

fn glow_element(index: usize, glow: &GlowBloom) -> Element {
    let role = match glow.target {
        ActorRef::Screen => roles::FX_SPINNER,
        _ => roles::FX_GLOW,
    };
    fx_target_element(role, Key::String(format!("fx:glow:{index}")), glow.target)
        .with_opacity(glow.intensity)
}

fn fx_target_element(role: &'static str, key: Key, target: ActorRef) -> Element {
    let element = Element::new(ElementKind::Container, Some(role))
        .key(key)
        .actor(target);
    match target {
        ActorRef::Region(region) => element.region(region),
        ActorRef::Screen
        | ActorRef::DeckItem { .. }
        | ActorRef::FxNode { .. }
        | ActorRef::Cursor => element,
    }
}

trait FxElementExt {
    fn with_opacity(self, opacity: u8) -> Self;
}

impl FxElementExt for Element {
    fn with_opacity(mut self, opacity: u8) -> Self {
        self.props.opacity = Some(opacity);
        self
    }
}
