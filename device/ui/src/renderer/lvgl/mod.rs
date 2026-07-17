pub(crate) mod ffi;
pub(crate) mod flush;
pub(crate) mod icons;
pub(crate) mod lifecycle;
pub(crate) mod snapshot;

use std::ffi::CString;
use std::ptr::{self, NonNull};
use std::time::Instant;

use anyhow::{anyhow, Context, Result};

use crate::renderer::assets::RenderAssets;
use crate::renderer::lvgl::flush::FlushTarget;
use crate::renderer::styling;
use crate::renderer::styling::layout::LayoutResolver;
use crate::renderer::styling::style::WidgetStyle;
use crate::renderer::styling::theme::ThemeResolver;
use crate::renderer::widgets::factory;
use crate::renderer::widgets::registry::{Layout, WidgetKind, WidgetNode, WidgetRegistry};
use crate::renderer::widgets::{LvglFacade, WidgetId, WidgetRole};
use crate::scene::roles;

const DEFAULT_WIDTH: i32 = 240;
const DEFAULT_HEIGHT: i32 = 280;

pub struct NativeLvglFacade {
    pub(crate) display: Option<NonNull<ffi::lv_display_t>>,
    pub(crate) blank_screen: Option<NonNull<ffi::lv_obj_t>>,
    pub(crate) draw_buffer: Vec<u8>,
    pub(crate) flush_target: FlushTarget,
    pub(crate) display_size: Option<(usize, usize)>,
    pub(crate) last_tick: Instant,
    pub(crate) widgets: WidgetRegistry,
    pub(crate) active_root: Option<WidgetId>,
    pub(crate) role_occurrences: std::collections::HashMap<&'static str, usize>,
    pub(crate) render_assets: RenderAssets,
}

impl NativeLvglFacade {
    pub(super) fn widget_obj(&self, widget: WidgetId) -> Result<NonNull<ffi::lv_obj_t>> {
        self.widgets.obj(widget)
    }

    pub(super) fn widget_node_mut(&mut self, widget: WidgetId) -> Result<&mut WidgetNode> {
        self.widgets.node_mut(widget)
    }

    pub(super) fn register_widget(
        &mut self,
        obj: NonNull<ffi::lv_obj_t>,
        kind: WidgetKind,
        role: WidgetRole,
        parent: Option<WidgetId>,
        layout: Layout,
    ) -> WidgetId {
        self.widgets.register(obj, kind, role, parent, layout)
    }

    pub(super) fn ensure_blank_screen(&mut self) -> Result<NonNull<ffi::lv_obj_t>> {
        if let Some(blank) = self.blank_screen {
            return Ok(blank);
        }

        let blank = unsafe { ffi::lv_obj_create(ptr::null_mut()) };
        let blank =
            NonNull::new(blank).ok_or_else(|| anyhow!("LVGL blank screen creation failed"))?;
        let size = self
            .display_size
            .map(|(width, height)| (width as i32, height as i32))
            .unwrap_or((DEFAULT_WIDTH, DEFAULT_HEIGHT));
        styling::reset_style_raw(blank);
        styling::apply_style_raw(blank, self.style_for_role(roles::ROOT)?);
        Self::apply_layout_raw(
            blank,
            Layout {
                x: 0,
                y: 0,
                width: size.0,
                height: size.1,
            },
        );
        self.blank_screen = Some(blank);
        Ok(blank)
    }

    pub(crate) fn invalidate_widget_registry(&mut self) {
        self.blank_screen = None;
        self.widgets.clear();
        self.active_root = None;
        self.role_occurrences.clear();
        self.flush_target.framebuffer = ptr::null_mut();
    }

    pub(super) fn apply_layout_raw(obj: NonNull<ffi::lv_obj_t>, layout: Layout) {
        unsafe {
            ffi::lv_obj_set_pos(obj.as_ptr(), layout.x, layout.y);
            ffi::lv_obj_set_size(obj.as_ptr(), layout.width.max(1), layout.height.max(1));
        }
    }

    pub(super) fn apply_node_layout_raw(
        obj: NonNull<ffi::lv_obj_t>,
        layout: Layout,
        x_offset: i32,
        y_offset: i32,
        scale_permille: i32,
    ) {
        Self::apply_layout_raw(
            obj,
            Layout {
                x: layout.x + x_offset,
                y: layout.y + y_offset,
                width: layout.width,
                height: layout.height,
            },
        );
        let lv_scale = ((scale_permille.max(1) * 256) + 500) / 1000;
        unsafe {
            ffi::lv_obj_set_style_transform_pivot_x(obj.as_ptr(), layout.width / 2, 0);
            ffi::lv_obj_set_style_transform_pivot_y(obj.as_ptr(), layout.height / 2, 0);
            ffi::lv_obj_set_style_transform_scale_x(obj.as_ptr(), lv_scale, 0);
            ffi::lv_obj_set_style_transform_scale_y(obj.as_ptr(), lv_scale, 0);
        }
    }

    fn layout_for_role_asset(&self, role: WidgetRole, occurrence: usize) -> Option<Layout> {
        LayoutResolver::new(&self.render_assets)
            .resolve_role(role, occurrence)
            .map(|layout| Layout {
                x: layout.x,
                y: layout.y,
                width: layout.width,
                height: layout.height,
            })
    }

    fn layout_for_root(&self) -> Layout {
        let (width, height) = self
            .display_size
            .map(|(width, height)| (width as i32, height as i32))
            .unwrap_or((DEFAULT_WIDTH, DEFAULT_HEIGHT));
        Layout {
            x: 0,
            y: 0,
            width,
            height,
        }
    }

    pub(super) fn next_role_layout(
        &mut self,
        _parent: Option<WidgetId>,
        role: WidgetRole,
    ) -> Result<Layout> {
        let occurrence = *self.role_occurrences.entry(role).or_insert(0);
        if let Some(layout) = self.layout_for_role_asset(role, occurrence) {
            self.role_occurrences.insert(role, occurrence + 1);
            return Ok(layout);
        }

        anyhow::bail!("missing LVGL layout asset for role {role}")
    }

    pub(super) fn style_for_role(&self, role: WidgetRole) -> Result<WidgetStyle> {
        ThemeResolver::new(&self.render_assets).style_for_role(role)
    }

    pub(super) fn style_for_selected_role(
        &self,
        role: WidgetRole,
        selected: bool,
    ) -> Result<WidgetStyle> {
        ThemeResolver::new(&self.render_assets).style_for_selected_role(role, selected)
    }
}

impl LvglFacade for NativeLvglFacade {
    fn create_root(&mut self) -> Result<WidgetId> {
        let obj = factory::create_root_object()?;
        let layout = self.layout_for_root();
        styling::reset_style_raw(obj);
        styling::apply_style_raw(obj, self.style_for_role(roles::ROOT)?);
        Self::apply_layout_raw(obj, layout);
        unsafe {
            ffi::lv_screen_load(obj.as_ptr());
        }
        self.role_occurrences.clear();
        let id = self.register_widget(obj, WidgetKind::Root, roles::ROOT, None, layout);
        self.active_root = Some(id);
        Ok(id)
    }

    fn create_container(&mut self, parent: WidgetId, role: WidgetRole) -> Result<WidgetId> {
        let parent_obj = self.widget_obj(parent)?;
        let obj = factory::create_container_object(parent_obj, role)?;
        let layout = self.next_role_layout(Some(parent), role)?;
        styling::reset_style_raw(obj);
        styling::apply_style_raw(obj, self.style_for_role(role)?);
        Self::apply_layout_raw(obj, layout);
        styling::apply_role_tuning_raw(obj, role);
        Ok(self.register_widget(obj, WidgetKind::Container, role, Some(parent), layout))
    }

    fn create_label(&mut self, parent: WidgetId, role: WidgetRole) -> Result<WidgetId> {
        let parent_obj = self.widget_obj(parent)?;
        let obj = factory::create_label_object(parent_obj, role)?;
        let layout = self.next_role_layout(Some(parent), role)?;
        styling::reset_style_raw(obj);
        styling::apply_style_raw(obj, self.style_for_role(role)?);
        Self::apply_layout_raw(obj, layout);
        styling::apply_role_tuning_raw(obj, role);
        Ok(self.register_widget(obj, WidgetKind::Label, role, Some(parent), layout))
    }

    fn create_image(&mut self, parent: WidgetId, role: WidgetRole) -> Result<WidgetId> {
        let parent_obj = self.widget_obj(parent)?;
        let obj = factory::create_image_object(parent_obj, role)?;
        let layout = self.next_role_layout(Some(parent), role)?;
        styling::reset_style_raw(obj);
        styling::apply_style_raw(obj, self.style_for_role(role)?);
        Self::apply_layout_raw(obj, layout);
        styling::apply_role_tuning_raw(obj, role);
        Ok(self.register_widget(obj, WidgetKind::Image, role, Some(parent), layout))
    }

    fn reorder_children(&mut self, parent: WidgetId, order: &[WidgetId]) -> Result<()> {
        self.widgets.reorder_children(parent, order)?;
        for (index, child) in order.iter().copied().enumerate() {
            let obj = self.widget_obj(child)?;
            unsafe {
                ffi::lv_obj_move_to_index(obj.as_ptr(), index as i32);
            }
        }
        Ok(())
    }

    fn set_text(&mut self, widget: WidgetId, text: &str) -> Result<()> {
        let node = self.widget_node_mut(widget)?;
        let text = CString::new(text).with_context(|| {
            format!(
                "LVGL text for widget {} contains an interior NUL byte",
                widget.raw()
            )
        })?;
        unsafe {
            ffi::lv_label_set_text(node.obj.as_ptr(), text.as_ptr());
            if matches!(node.role, roles::CALL_STATE_LABEL | roles::CALL_MUTE_LABEL) {
                ffi::lv_obj_center(node.obj.as_ptr());
            }
        }
        Ok(())
    }

    fn set_selected(&mut self, _widget: WidgetId, _selected: bool) -> Result<()> {
        let (obj, role, layout, x_offset, y_offset, scale_permille) = {
            let node = self.widget_node_mut(_widget)?;
            (
                node.obj,
                node.role,
                node.layout,
                node.x_offset,
                node.y_offset,
                node.scale_permille,
            )
        };
        styling::apply_style_raw(obj, self.style_for_selected_role(role, _selected)?);
        Self::apply_node_layout_raw(obj, layout, x_offset, y_offset, scale_permille);
        Ok(())
    }

    fn set_icon(&mut self, widget: WidgetId, icon_key: &str) -> Result<()> {
        let node = self.widget_node_mut(widget)?;
        if node.kind == WidgetKind::Image {
            let source = icons::source_for_key(icon_key);
            unsafe {
                ffi::lv_image_set_src(node.obj.as_ptr(), source);
            }
            return Ok(());
        }
        self.set_text(widget, &styling::icon_label(icon_key))
    }

    fn set_progress(&mut self, widget: WidgetId, value: i32) -> Result<()> {
        let value = value.clamp(0, 1000);
        let node = self.widget_node_mut(widget)?;
        if matches!(
            node.role,
            roles::PROGRESS_SWEEP_FILL | roles::VOICE_METER_LEVEL
        ) {
            let fill_width = (node.layout.width * value) / 1000;
            if fill_width <= 0 {
                styling::set_widget_hidden_raw(node.obj, true);
            } else {
                styling::set_widget_hidden_raw(node.obj, false);
                Self::apply_layout_raw(
                    node.obj,
                    Layout {
                        width: fill_width,
                        ..node.layout
                    },
                );
            }
            return Ok(());
        }

        let filled = ((value as usize) * 10) / 1000;
        let empty = 10usize.saturating_sub(filled);
        let bar = format!(
            "[{}{}] {}%",
            "#".repeat(filled),
            "-".repeat(empty),
            value / 10
        );
        self.set_text(widget, &bar)
    }

    fn set_visible(&mut self, widget: WidgetId, visible: bool) -> Result<()> {
        let node = self.widget_node_mut(widget)?;
        styling::set_widget_hidden_raw(node.obj, !visible);
        Ok(())
    }

    fn set_opacity(&mut self, widget: WidgetId, opacity: u8) -> Result<()> {
        let node = self.widget_node_mut(widget)?;
        unsafe {
            ffi::lv_obj_set_style_opa(node.obj.as_ptr(), opacity, 0);
        }
        Ok(())
    }

    fn set_x_offset(&mut self, widget: WidgetId, offset: i32) -> Result<()> {
        let node = self.widget_node_mut(widget)?;
        node.x_offset = offset;
        Self::apply_node_layout_raw(
            node.obj,
            node.layout,
            node.x_offset,
            node.y_offset,
            node.scale_permille,
        );
        Ok(())
    }

    fn set_y_offset(&mut self, widget: WidgetId, offset: i32) -> Result<()> {
        let node = self.widget_node_mut(widget)?;
        node.y_offset = offset;
        Self::apply_node_layout_raw(
            node.obj,
            node.layout,
            node.x_offset,
            node.y_offset,
            node.scale_permille,
        );
        Ok(())
    }

    fn set_scale(&mut self, widget: WidgetId, scale_permille: i32) -> Result<()> {
        let node = self.widget_node_mut(widget)?;
        node.scale_permille = scale_permille.clamp(100, 4000);
        Self::apply_node_layout_raw(
            node.obj,
            node.layout,
            node.x_offset,
            node.y_offset,
            node.scale_permille,
        );
        Ok(())
    }

    fn set_geometry(
        &mut self,
        widget: WidgetId,
        x: i32,
        y: i32,
        width: i32,
        height: i32,
    ) -> Result<()> {
        let node = self.widget_node_mut(widget)?;
        node.layout = Layout {
            x,
            y,
            width,
            height,
        };
        Self::apply_node_layout_raw(
            node.obj,
            node.layout,
            node.x_offset,
            node.y_offset,
            node.scale_permille,
        );
        Ok(())
    }

    fn set_variant(
        &mut self,
        widget: WidgetId,
        variant: WidgetRole,
        accent_rgb: u32,
    ) -> Result<()> {
        let node = self.widget_node_mut(widget)?;
        styling::apply_variant_raw(node.obj, node.role, variant, accent_rgb);
        Ok(())
    }

    fn set_accent(&mut self, widget: WidgetId, rgb: u32) -> Result<()> {
        let node = self.widget_node_mut(widget)?;
        styling::apply_accent_raw(node.obj, node.role, rgb);
        Ok(())
    }

    fn destroy(&mut self, widget: WidgetId) -> Result<()> {
        let obj = self.widget_obj(widget)?;
        if self.active_root == Some(widget) {
            let blank = self.ensure_blank_screen()?;
            unsafe {
                ffi::lv_screen_load(blank.as_ptr());
            }
        }
        unsafe {
            ffi::lv_obj_delete(obj.as_ptr());
        }
        self.widgets.remove_subtree(widget);
        if self.active_root == Some(widget) {
            self.active_root = None;
            self.role_occurrences.clear();
        }
        Ok(())
    }
}
