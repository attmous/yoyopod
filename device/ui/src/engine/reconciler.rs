use crate::animation::{AnimatableProp, AnimatableValue, TimelineSampler};
use crate::scene::{region_rect, RegionId, Stage};
use crate::{Mutation, NodeId, PropChange};

use std::collections::BTreeMap;

use super::{props, Element, ElementProps, Layout, NodeIdAlloc, NodePath};

#[derive(Debug, Default)]
pub struct Reconciler;

struct DiffContext<'a, 'timeline> {
    previous_ids: &'a BTreeMap<NodePath, NodeId>,
    next_ids: &'a mut BTreeMap<NodePath, NodeId>,
    node_alloc: &'a mut NodeIdAlloc,
    stage: Stage,
    sampler: &'a TimelineSampler<'timeline>,
    out: &'a mut Vec<Mutation>,
}

impl Reconciler {
    pub fn diff(
        &mut self,
        previous: Option<&Element>,
        previous_ids: &BTreeMap<NodePath, NodeId>,
        next: &Element,
        frame: (Stage, &TimelineSampler<'_>),
        node_alloc: &mut NodeIdAlloc,
        out: &mut Vec<Mutation>,
    ) -> BTreeMap<NodePath, NodeId> {
        out.clear();
        let mut next_ids = BTreeMap::new();
        let root_path = NodePath::root(next);
        let mut context = DiffContext {
            previous_ids,
            next_ids: &mut next_ids,
            node_alloc,
            stage: frame.0,
            sampler: frame.1,
            out,
        };
        diff_element(previous, next, NodeId(0), root_path, &mut context);
        next_ids
    }
}

fn diff_element(
    previous: Option<&Element>,
    next: &Element,
    parent: NodeId,
    path: NodePath,
    context: &mut DiffContext<'_, '_>,
) -> NodeId {
    let previous_node = context.previous_ids.get(&path).copied();
    let replace = previous
        .map(|previous| should_replace(previous, next))
        .unwrap_or(false);
    let node = if replace {
        context.node_alloc.alloc()
    } else {
        previous_node.unwrap_or_else(|| context.node_alloc.alloc())
    };
    context.next_ids.insert(path.clone(), node);

    match previous {
        None => create_subtree(node, parent, next, path, context),
        Some(previous) if replace => {
            if let Some(previous_node) = previous_node {
                remove_subtree(
                    previous,
                    path.clone(),
                    previous_node,
                    context.previous_ids,
                    context.out,
                );
            }
            create_subtree(node, parent, next, path, context);
        }
        Some(previous) => {
            emit_prop_updates(node, &previous.props, &next.props, context.out);
            if previous.layout != next.layout {
                emit_place(node, next.layout, context.stage, context.out);
            }
            emit_animation_updates(node, next, context.sampler, context.out);
            diff_children(previous, next, node, path, context);
        }
    }
    node
}

fn create_subtree(
    node: NodeId,
    parent: NodeId,
    element: &Element,
    path: NodePath,
    context: &mut DiffContext<'_, '_>,
) {
    context.next_ids.insert(path.clone(), node);
    context.out.push(Mutation::Create {
        node,
        parent,
        kind: element.kind,
        role: element.role,
    });
    emit_prop_updates(node, &ElementProps::default(), &element.props, context.out);
    emit_place(node, element.layout, context.stage, context.out);
    emit_animation_updates(node, element, context.sampler, context.out);
    for (index, child) in element.children.iter().enumerate() {
        let child_path = path.child(child, index);
        let child_node = context.node_alloc.alloc();
        create_subtree(child_node, node, child, child_path, context);
    }
}

fn diff_children(
    previous: &Element,
    next: &Element,
    parent: NodeId,
    parent_path: NodePath,
    context: &mut DiffContext<'_, '_>,
) {
    let mut order = Vec::with_capacity(next.children.len());
    let mut matched_previous = vec![false; previous.children.len()];
    for (index, child) in next.children.iter().enumerate() {
        let child_path = parent_path.child(child, index);
        let previous_match =
            previous
                .children
                .iter()
                .enumerate()
                .find(|(previous_index, previous_child)| {
                    parent_path.child(previous_child, *previous_index) == child_path
                });
        let previous_child = previous_match.map(|(previous_index, previous_child)| {
            matched_previous[previous_index] = true;
            previous_child
        });
        let node = diff_element(previous_child, child, parent, child_path, context);
        order.push(node);
    }
    for (index, child) in previous.children.iter().enumerate() {
        if matched_previous[index] {
            continue;
        }
        let child_path = parent_path.child(child, index);
        if let Some(node) = context.previous_ids.get(&child_path).copied() {
            remove_subtree(child, child_path, node, context.previous_ids, context.out);
        }
    }
    if !order.is_empty()
        && child_order_changed(previous, &parent_path, context.previous_ids, &order)
    {
        context.out.push(Mutation::Reorder { parent, order });
    }
}

fn child_order_changed(
    previous: &Element,
    parent_path: &NodePath,
    previous_ids: &BTreeMap<NodePath, NodeId>,
    order: &[NodeId],
) -> bool {
    if previous.children.len() != order.len() {
        return true;
    }

    previous
        .children
        .iter()
        .enumerate()
        .zip(order.iter().copied())
        .any(|((index, child), next_node)| {
            previous_ids.get(&parent_path.child(child, index)).copied() != Some(next_node)
        })
}

fn emit_prop_updates(
    node: NodeId,
    previous: &ElementProps,
    next: &ElementProps,
    out: &mut Vec<Mutation>,
) {
    props::diff_props(previous, next, |prop| {
        out.push(Mutation::Update { node, prop });
    });
    if next.text.is_none() && previous.text.is_some() {
        out.push(Mutation::Update {
            node,
            prop: PropChange::Text(String::new()),
        });
    }
    if next.icon_key.is_none() && previous.icon_key.is_some() {
        out.push(Mutation::Update {
            node,
            prop: PropChange::Icon(String::new()),
        });
    }
}

fn emit_place(node: NodeId, layout: Layout, stage: Stage, out: &mut Vec<Mutation>) {
    let Some((x, y, w, h)) = resolve_layout(stage, layout) else {
        return;
    };
    out.push(Mutation::Place { node, x, y, w, h });
}

fn resolve_layout(stage: Stage, layout: Layout) -> Option<(i32, i32, i32, i32)> {
    match layout {
        Layout::Absolute { x, y, w, h } => Some((x, y, w, h)),
        Layout::Region(RegionId::Auto) => None,
        Layout::Region(region) => {
            let rect = region_rect(stage, region)
                .unwrap_or_else(|| panic!("stage {stage:?} has no rect for region {region:?}"));
            Some((rect.x, rect.y, rect.w, rect.h))
        }
    }
}

fn emit_animation_updates(
    node: NodeId,
    element: &Element,
    sampler: &TimelineSampler<'_>,
    out: &mut Vec<Mutation>,
) {
    if let Some(anim) = element.anim {
        if let Some((property, value)) = sampler.slot_value(anim.timeline, anim.track) {
            if let Some(prop) = prop_change_for_animation(property, value) {
                out.push(Mutation::Update { node, prop });
            }
        }
    }

    if let Some(actor) = element.actor {
        for property in actor_properties() {
            let Some(value) = sampler.value(actor, property) else {
                continue;
            };
            if let Some(prop) = prop_change_for_animation(property, value) {
                out.push(Mutation::Update { node, prop });
            }
        }
    }
}

fn actor_properties() -> [AnimatableProp; 8] {
    [
        AnimatableProp::Opacity,
        AnimatableProp::X,
        AnimatableProp::Y,
        AnimatableProp::Scale,
        AnimatableProp::SelectionOffset,
        AnimatableProp::ProgressPermille,
        AnimatableProp::AccentMix,
        AnimatableProp::BorderWidth,
    ]
}

fn prop_change_for_animation(
    property: AnimatableProp,
    value: AnimatableValue,
) -> Option<PropChange> {
    match (property, value) {
        (AnimatableProp::Opacity, AnimatableValue::U8(value)) => Some(PropChange::Opacity(value)),
        (AnimatableProp::X, AnimatableValue::I32(value)) => Some(PropChange::OffsetX(value)),
        (AnimatableProp::Y, AnimatableValue::I32(value)) => Some(PropChange::OffsetY(value)),
        (AnimatableProp::Scale, AnimatableValue::I32(value)) => {
            Some(PropChange::ScalePermille(value))
        }
        (AnimatableProp::SelectionOffset, AnimatableValue::I32(value)) => {
            Some(PropChange::SelectionOffset(value))
        }
        (AnimatableProp::ProgressPermille, AnimatableValue::I32(value)) => {
            Some(PropChange::Progress(value))
        }
        (AnimatableProp::AccentMix, AnimatableValue::Rgb(value)) => Some(PropChange::Accent(value)),
        _ => None,
    }
}

fn remove_subtree(
    element: &Element,
    path: NodePath,
    node: NodeId,
    previous_ids: &BTreeMap<NodePath, NodeId>,
    out: &mut Vec<Mutation>,
) {
    for (index, child) in element.children.iter().enumerate() {
        let child_path = path.child(child, index);
        if let Some(child_node) = previous_ids.get(&child_path).copied() {
            remove_subtree(child, child_path, child_node, previous_ids, out);
        }
    }
    out.push(Mutation::Remove { node });
}

fn should_replace(previous: &Element, next: &Element) -> bool {
    previous.key != next.key || previous.kind != next.kind || previous.role != next.role
}
