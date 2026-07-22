use std::path::Path;

#[cfg(feature = "native-lvgl")]
use anyhow::anyhow;
use anyhow::Result;

#[cfg(feature = "native-lvgl")]
use crate::renderer::lvgl::NativeLvglFacade;
#[cfg(feature = "native-lvgl")]
use crate::renderer::node_registry::NodeRegistry;
#[cfg(feature = "native-lvgl")]
use crate::renderer::widgets::{LvglFacade, WidgetId};
use crate::renderer::{Framebuffer, RenderReport, Renderer};
use crate::theme::ColorScheme;
use crate::Mutation;
use crate::RenderMode;
#[cfg(feature = "native-lvgl")]
use crate::{ElementKind, NodeId, PropChange};

#[cfg(feature = "native-lvgl")]
const MAX_ACTIVE_WIDGETS: usize = 60;

#[cfg(not(feature = "native-lvgl"))]
pub struct LvglRenderer;

#[cfg(feature = "native-lvgl")]
pub struct LvglRenderer {
    facade: NativeLvglFacade,
    node_registry: NodeRegistry,
}

#[cfg(feature = "native-lvgl")]
impl LvglRenderer {
    pub fn open(explicit_source: Option<&Path>) -> Result<Self> {
        Ok(Self {
            facade: NativeLvglFacade::open(explicit_source)?,
            node_registry: NodeRegistry::default(),
        })
    }

    pub fn initialize_display(&mut self, framebuffer: &Framebuffer) -> Result<()> {
        self.facade.ensure_display_registered(framebuffer)
    }

    /// Capture the active screen via LVGL's native snapshot (readback path).
    pub fn readback_rgb565(&mut self) -> Result<crate::screenshot::Rgb565Image> {
        self.facade.snapshot_active_screen()
    }

    pub fn set_color_scheme(&mut self, color_scheme: ColorScheme) -> Result<bool> {
        let changed = self.facade.set_color_scheme(color_scheme)?;
        if changed {
            self.node_registry.clear();
        }
        Ok(changed)
    }
}

#[cfg(feature = "native-lvgl")]
impl Renderer for LvglRenderer {
    fn apply(&mut self, mutations: &[Mutation]) -> Result<()> {
        for mutation in mutations {
            apply_mutation(&mut self.facade, &mut self.node_registry, mutation)?;
        }
        if self.node_registry.len() > MAX_ACTIVE_WIDGETS {
            anyhow::bail!(
                "LVGL widget budget exceeded: {} active widgets, max {}",
                self.node_registry.len(),
                MAX_ACTIVE_WIDGETS
            );
        }
        Ok(())
    }

    fn flush(&mut self, framebuffer: &mut Framebuffer, mode: RenderMode) -> Result<RenderReport> {
        if self.facade.display_needs_reset(framebuffer) {
            self.node_registry.clear();
        }
        self.facade.ensure_display_registered(framebuffer)?;
        self.facade.render_frame(framebuffer)?;
        Ok(RenderReport {
            renderer: "lvgl",
            mode,
            widget_count: self.node_registry.len(),
        })
    }
}

#[cfg(feature = "native-lvgl")]
fn apply_mutation(
    facade: &mut NativeLvglFacade,
    registry: &mut NodeRegistry,
    mutation: &Mutation,
) -> Result<()> {
    match mutation {
        Mutation::Create {
            node,
            parent,
            kind,
            role,
        } => create_widget(facade, registry, *node, *parent, *kind, *role),
        Mutation::Update { node, prop } => update_widget(facade, registry, *node, prop),
        Mutation::Place { node, x, y, w, h } => {
            let widget = widget_for(registry, *node)?;
            facade.set_geometry(widget, *x, *y, *w, *h)
        }
        Mutation::Reorder { parent, order } => {
            let parent = widget_for(registry, *parent)?;
            let order = order
                .iter()
                .map(|node| widget_for(registry, *node))
                .collect::<Result<Vec<_>>>()?;
            facade.reorder_children(parent, &order)
        }
        Mutation::Remove { node } => {
            if let Some(widget) = registry.remove(*node) {
                facade.destroy(widget)?;
            }
            Ok(())
        }
    }
}

#[cfg(feature = "native-lvgl")]
fn create_widget(
    facade: &mut NativeLvglFacade,
    registry: &mut NodeRegistry,
    node: NodeId,
    parent: NodeId,
    kind: ElementKind,
    role: Option<&'static str>,
) -> Result<()> {
    if registry.widget(node).is_some() {
        return Ok(());
    }
    if node == NodeId(0) || parent == node || registry.is_empty() {
        let widget = facade.create_root()?;
        registry.bind(node, widget);
        return Ok(());
    }

    let parent = widget_for(registry, parent)?;
    let role = role.ok_or_else(|| anyhow!("LVGL mutation create missing widget role"))?;
    let widget = match kind {
        ElementKind::Container | ElementKind::Progress => facade.create_container(parent, role)?,
        ElementKind::Label => facade.create_label(parent, role)?,
        ElementKind::Image => facade.create_image(parent, role)?,
        ElementKind::Arc => facade.create_arc(parent, role)?,
        ElementKind::Qr => facade.create_qrcode(parent, role)?,
    };
    registry.bind(node, widget);
    Ok(())
}

#[cfg(feature = "native-lvgl")]
fn update_widget(
    facade: &mut NativeLvglFacade,
    registry: &NodeRegistry,
    node: NodeId,
    prop: &PropChange,
) -> Result<()> {
    let widget = widget_for(registry, node)?;
    match prop {
        PropChange::Text(text) => facade.set_text(widget, text),
        PropChange::Icon(icon) => facade.set_icon(widget, icon),
        PropChange::Accent(rgb) => facade.set_accent(widget, *rgb),
        PropChange::Selected(selected) => facade.set_selected(widget, *selected),
        PropChange::Visible(visible) => facade.set_visible(widget, *visible),
        PropChange::Opacity(opacity) => facade.set_opacity(widget, *opacity),
        PropChange::OffsetX(offset) => facade.set_x_offset(widget, *offset),
        PropChange::OffsetY(offset) => facade.set_y_offset(widget, *offset),
        PropChange::ScalePermille(scale) => facade.set_scale(widget, *scale),
        PropChange::SelectionOffset(offset) => facade.set_y_offset(widget, *offset),
        PropChange::Variant(variant) => facade.set_variant(widget, variant, 0),
        PropChange::Progress(value) => facade.set_progress(widget, *value),
    }
}

#[cfg(feature = "native-lvgl")]
fn widget_for(registry: &NodeRegistry, node: NodeId) -> Result<WidgetId> {
    registry
        .widget(node)
        .ok_or_else(|| anyhow!("LVGL mutation referenced unknown node {:?}", node))
}

#[cfg(not(feature = "native-lvgl"))]
impl LvglRenderer {
    pub fn open(_explicit_source: Option<&Path>) -> Result<Self> {
        anyhow::bail!("native-lvgl feature is disabled for this build")
    }

    pub fn initialize_display(&mut self, _framebuffer: &Framebuffer) -> Result<()> {
        anyhow::bail!("native-lvgl feature is disabled for this build")
    }

    pub fn readback_rgb565(&mut self) -> Result<crate::screenshot::Rgb565Image> {
        anyhow::bail!("native-lvgl feature is disabled for this build")
    }

    pub fn set_color_scheme(&mut self, _color_scheme: ColorScheme) -> Result<bool> {
        anyhow::bail!("native-lvgl feature is disabled for this build")
    }
}

#[cfg(not(feature = "native-lvgl"))]
impl Renderer for LvglRenderer {
    fn apply(&mut self, _mutations: &[Mutation]) -> Result<()> {
        anyhow::bail!("native-lvgl feature is disabled for this build")
    }

    fn flush(&mut self, _framebuffer: &mut Framebuffer, _mode: RenderMode) -> Result<RenderReport> {
        anyhow::bail!("native-lvgl feature is disabled for this build")
    }
}
