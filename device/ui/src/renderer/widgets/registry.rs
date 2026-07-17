use std::collections::HashMap;
use std::ptr::NonNull;

use anyhow::{anyhow, Result};

use crate::renderer::lvgl::ffi;
use crate::renderer::widgets::{WidgetId, WidgetRole};

#[derive(Debug, Clone, Copy)]
pub(crate) struct Layout {
    pub x: i32,
    pub y: i32,
    pub width: i32,
    pub height: i32,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum WidgetKind {
    Root,
    Container,
    Label,
    Image,
}

#[derive(Debug)]
pub(crate) struct WidgetNode {
    pub obj: NonNull<ffi::lv_obj_t>,
    pub kind: WidgetKind,
    pub role: WidgetRole,
    pub parent: Option<WidgetId>,
    pub children: Vec<WidgetId>,
    pub layout: Layout,
    pub x_offset: i32,
    pub y_offset: i32,
    pub scale_permille: i32,
}

#[derive(Debug, Default)]
pub(crate) struct WidgetRegistry {
    next_widget_id: u64,
    widgets: HashMap<WidgetId, WidgetNode>,
}

impl WidgetRegistry {
    pub fn obj(&self, widget: WidgetId) -> Result<NonNull<ffi::lv_obj_t>> {
        self.widgets
            .get(&widget)
            .map(|node| node.obj)
            .ok_or_else(|| anyhow!("unknown LVGL widget {}", widget.raw()))
    }

    pub fn node_mut(&mut self, widget: WidgetId) -> Result<&mut WidgetNode> {
        self.widgets
            .get_mut(&widget)
            .ok_or_else(|| anyhow!("unknown LVGL widget {}", widget.raw()))
    }

    pub fn register(
        &mut self,
        obj: NonNull<ffi::lv_obj_t>,
        kind: WidgetKind,
        role: WidgetRole,
        parent: Option<WidgetId>,
        layout: Layout,
    ) -> WidgetId {
        let id = self.next_widget_id();
        self.widgets.insert(
            id,
            WidgetNode {
                obj,
                kind,
                role,
                parent,
                children: Vec::new(),
                layout,
                x_offset: 0,
                y_offset: 0,
                scale_permille: 1000,
            },
        );
        if let Some(parent) = parent {
            if let Some(parent_node) = self.widgets.get_mut(&parent) {
                parent_node.children.push(id);
            }
        }
        id
    }

    pub fn remove_subtree(&mut self, widget: WidgetId) {
        if let Some(parent) = self.widgets.get(&widget).and_then(|node| node.parent) {
            if let Some(parent_node) = self.widgets.get_mut(&parent) {
                parent_node.children.retain(|child| *child != widget);
            }
        }
        if let Some(node) = self.widgets.remove(&widget) {
            for child in node.children {
                self.remove_subtree(child);
            }
        }
    }

    pub fn reorder_children(&mut self, parent: WidgetId, order: &[WidgetId]) -> Result<()> {
        let current = self
            .widgets
            .get(&parent)
            .map(|node| node.children.clone())
            .ok_or_else(|| anyhow!("unknown parent widget {}", parent.raw()))?;
        if current.len() != order.len() {
            anyhow::bail!(
                "reorder for widget {} has {} children, expected {}",
                parent.raw(),
                order.len(),
                current.len()
            );
        }
        for child in order {
            if !current.contains(child) {
                anyhow::bail!(
                    "reorder for widget {} referenced non-child widget {}",
                    parent.raw(),
                    child.raw()
                );
            }
        }
        let parent = self.node_mut(parent)?;
        parent.children = order.to_vec();
        Ok(())
    }

    pub fn child_role_count(&self, parent: WidgetId, role: WidgetRole) -> Result<usize> {
        let parent = self
            .widgets
            .get(&parent)
            .ok_or_else(|| anyhow!("unknown parent widget {}", parent.raw()))?;
        Ok(parent
            .children
            .iter()
            .filter(|child| {
                self.widgets
                    .get(child)
                    .is_some_and(|node| node.role == role)
            })
            .count())
    }

    pub fn clear(&mut self) {
        self.widgets.clear();
    }

    fn next_widget_id(&mut self) -> WidgetId {
        let id = WidgetId::new(self.next_widget_id);
        self.next_widget_id += 1;
        id
    }
}
