use std::collections::HashMap;
use std::ffi::CString;
use std::path::Path;
use std::ptr::{self, NonNull};
use std::time::Instant;

use anyhow::{anyhow, bail, Context, Result};

use crate::framebuffer::Framebuffer;
use crate::lvgl::sys;
use crate::lvgl::theme::{self, WidgetStyle};
use crate::lvgl::{LvglFacade, WidgetId};

const DEFAULT_WIDTH: i32 = 240;
const DEFAULT_HEIGHT: i32 = 280;
const DRAW_BUFFER_ROWS: usize = 40;
const OFFSCREEN: i32 = -4096;

#[derive(Debug, Clone, Copy)]
struct Layout {
    x: i32,
    y: i32,
    width: i32,
    height: i32,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum WidgetKind {
    Root,
    Container,
    Label,
}

#[derive(Debug)]
struct WidgetNode {
    obj: NonNull<sys::lv_obj_t>,
    _kind: WidgetKind,
    role: &'static str,
    _parent: Option<WidgetId>,
    children: Vec<WidgetId>,
    layout: Layout,
}

#[derive(Default)]
struct FlushTarget {
    framebuffer: *mut Framebuffer,
}

pub struct NativeLvglFacade {
    display: Option<NonNull<sys::lv_display_t>>,
    blank_screen: Option<NonNull<sys::lv_obj_t>>,
    draw_buffer: Vec<u8>,
    flush_target: FlushTarget,
    display_size: Option<(usize, usize)>,
    last_tick: Instant,
    next_widget_id: u64,
    widgets: HashMap<WidgetId, WidgetNode>,
    active_root: Option<WidgetId>,
    list_row_count: usize,
    power_row_count: usize,
}

impl NativeLvglFacade {
    pub fn open(explicit_source: Option<&Path>) -> Result<Self> {
        validate_explicit_source_dir(explicit_source)?;
        unsafe {
            sys::lv_init();
        }

        Ok(Self {
            display: None,
            blank_screen: None,
            draw_buffer: Vec::new(),
            flush_target: FlushTarget::default(),
            display_size: None,
            last_tick: Instant::now(),
            next_widget_id: 0,
            widgets: HashMap::new(),
            active_root: None,
            list_row_count: 0,
            power_row_count: 0,
        })
    }

    pub(crate) fn display_needs_reset(&self, framebuffer: &Framebuffer) -> bool {
        let size = (framebuffer.width(), framebuffer.height());
        self.display.is_some() && self.display_size != Some(size)
    }

    pub(crate) fn ensure_display_registered(&mut self, framebuffer: &Framebuffer) -> Result<()> {
        let size = (framebuffer.width(), framebuffer.height());
        if self.display_size == Some(size) && self.display.is_some() {
            return Ok(());
        }

        if let Some(display) = self.display.take() {
            unsafe {
                sys::lv_display_delete(display.as_ptr());
            }
        }
        self.invalidate_widget_registry();
        self.display_size = Some(size);

        let display = unsafe { sys::lv_display_create(size.0 as i32, size.1 as i32) };
        let display =
            NonNull::new(display).ok_or_else(|| anyhow!("LVGL display creation failed"))?;

        self.draw_buffer = vec![0; size.0 * DRAW_BUFFER_ROWS * 2];
        unsafe {
            sys::lv_display_set_default(display.as_ptr());
            sys::lv_display_set_flush_cb(display.as_ptr(), Some(lvgl_flush_callback));
            sys::lv_display_set_user_data(
                display.as_ptr(),
                &mut self.flush_target as *mut FlushTarget as *mut _,
            );
            sys::lv_display_set_buffers(
                display.as_ptr(),
                self.draw_buffer.as_mut_ptr().cast(),
                ptr::null_mut(),
                self.draw_buffer.len() as u32,
                sys::LV_DISPLAY_RENDER_MODE_PARTIAL,
            );
        }

        self.display = Some(display);
        Ok(())
    }

    pub(crate) fn render_frame(&mut self, framebuffer: &mut Framebuffer) -> Result<()> {
        self.ensure_display_registered(framebuffer)?;
        self.flush_target.framebuffer = framebuffer as *mut Framebuffer;

        if let Some(root) = self.active_root {
            let root_obj = self.widget_obj(root)?;
            unsafe {
                sys::lv_obj_invalidate(root_obj.as_ptr());
            }
        } else if let Some(display) = self.display {
            let active = unsafe { sys::lv_display_get_screen_active(display.as_ptr()) };
            if let Some(active) = NonNull::new(active) {
                unsafe {
                    sys::lv_obj_invalidate(active.as_ptr());
                }
            }
        }

        let elapsed_ms = self
            .last_tick
            .elapsed()
            .as_millis()
            .min(u128::from(u32::MAX)) as u32;
        self.last_tick = Instant::now();
        unsafe {
            sys::lv_tick_inc(elapsed_ms.max(1));
            let _ = sys::lv_timer_handler();
        }
        Ok(())
    }

    fn widget_obj(&self, widget: WidgetId) -> Result<NonNull<sys::lv_obj_t>> {
        self.widgets
            .get(&widget)
            .map(|node| node.obj)
            .ok_or_else(|| anyhow!("unknown LVGL widget {}", widget.raw()))
    }

    fn widget_node_mut(&mut self, widget: WidgetId) -> Result<&mut WidgetNode> {
        self.widgets
            .get_mut(&widget)
            .ok_or_else(|| anyhow!("unknown LVGL widget {}", widget.raw()))
    }

    fn next_widget_id(&mut self) -> WidgetId {
        let id = WidgetId::new(self.next_widget_id);
        self.next_widget_id += 1;
        id
    }

    fn register_widget(
        &mut self,
        obj: NonNull<sys::lv_obj_t>,
        kind: WidgetKind,
        role: &'static str,
        parent: Option<WidgetId>,
        layout: Layout,
    ) -> WidgetId {
        let id = self.next_widget_id();
        self.widgets.insert(
            id,
            WidgetNode {
                obj,
                _kind: kind,
                role,
                _parent: parent,
                children: Vec::new(),
                layout,
            },
        );
        if let Some(parent) = parent {
            if let Some(parent_node) = self.widgets.get_mut(&parent) {
                parent_node.children.push(id);
            }
        }
        id
    }

    fn ensure_blank_screen(&mut self) -> Result<NonNull<sys::lv_obj_t>> {
        if let Some(blank) = self.blank_screen {
            return Ok(blank);
        }

        let blank = unsafe { sys::lv_obj_create(ptr::null_mut()) };
        let blank =
            NonNull::new(blank).ok_or_else(|| anyhow!("LVGL blank screen creation failed"))?;
        let size = self
            .display_size
            .map(|(width, height)| (width as i32, height as i32))
            .unwrap_or((DEFAULT_WIDTH, DEFAULT_HEIGHT));
        Self::reset_style_raw(blank);
        Self::apply_style_raw(blank, theme::style_for_role("root"));
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

    fn remove_widget_subtree(&mut self, widget: WidgetId) {
        if let Some(node) = self.widgets.remove(&widget) {
            for child in node.children {
                self.remove_widget_subtree(child);
            }
        }
    }

    fn invalidate_widget_registry(&mut self) {
        self.blank_screen = None;
        self.widgets.clear();
        self.active_root = None;
        self.list_row_count = 0;
        self.power_row_count = 0;
        self.flush_target.framebuffer = ptr::null_mut();
    }

    fn apply_layout_raw(obj: NonNull<sys::lv_obj_t>, layout: Layout) {
        unsafe {
            sys::lv_obj_set_pos(obj.as_ptr(), layout.x, layout.y);
            sys::lv_obj_set_size(obj.as_ptr(), layout.width.max(1), layout.height.max(1));
        }
    }

    fn reset_style_raw(obj: NonNull<sys::lv_obj_t>) {
        unsafe {
            sys::lv_obj_remove_style_all(obj.as_ptr());
        }
    }

    fn apply_style_raw(obj: NonNull<sys::lv_obj_t>, style: WidgetStyle) {
        const SELECTOR: sys::LvStyleSelector = 0;

        unsafe {
            if let Some(bg_color) = style.bg_color {
                sys::lv_obj_set_style_bg_color(
                    obj.as_ptr(),
                    sys::lv_color_hex(bg_color & 0xFFFFFF),
                    SELECTOR,
                );
            }
            sys::lv_obj_set_style_bg_opa(obj.as_ptr(), style.bg_opa, SELECTOR);

            if let Some(text_color) = style.text_color {
                sys::lv_obj_set_style_text_color(
                    obj.as_ptr(),
                    sys::lv_color_hex(text_color & 0xFFFFFF),
                    SELECTOR,
                );
            }

            if let Some(border_color) = style.border_color {
                sys::lv_obj_set_style_border_color(
                    obj.as_ptr(),
                    sys::lv_color_hex(border_color & 0xFFFFFF),
                    SELECTOR,
                );
            }
            sys::lv_obj_set_style_border_width(obj.as_ptr(), style.border_width, SELECTOR);
            sys::lv_obj_set_style_radius(obj.as_ptr(), style.radius, SELECTOR);
            sys::lv_obj_set_style_outline_width(obj.as_ptr(), style.outline_width, SELECTOR);
            sys::lv_obj_set_style_shadow_width(obj.as_ptr(), style.shadow_width, SELECTOR);
        }
    }

    fn hide_widget_raw(obj: NonNull<sys::lv_obj_t>) {
        unsafe {
            sys::lv_obj_set_pos(obj.as_ptr(), OFFSCREEN, OFFSCREEN);
            sys::lv_obj_set_size(obj.as_ptr(), 1, 1);
        }
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

    fn next_role_layout(&mut self, parent: Option<WidgetId>, role: &'static str) -> Result<Layout> {
        let parent_role = parent
            .and_then(|widget| self.widgets.get(&widget).map(|node| node.role))
            .unwrap_or("root");

        let layout = match role {
            "status_bar" => Layout {
                x: 0,
                y: 0,
                width: 240,
                height: 30,
            },
            "status_network" => Layout {
                x: 10,
                y: 8,
                width: 42,
                height: 14,
            },
            "status_signal" => Layout {
                x: 98,
                y: 8,
                width: 44,
                height: 14,
            },
            "status_battery" => Layout {
                x: 184,
                y: 8,
                width: 48,
                height: 14,
            },
            "footer_bar" => Layout {
                x: 0,
                y: 248,
                width: 240,
                height: 32,
            },
            _ if parent_role == "footer_bar" => Layout {
                x: 10,
                y: 8,
                width: 220,
                height: 16,
            },
            "hub_icon_glow" => Layout {
                x: 62,
                y: 48,
                width: 116,
                height: 116,
            },
            "hub_card_panel" => Layout {
                x: 72,
                y: 58,
                width: 96,
                height: 96,
            },
            "hub_icon" => Layout {
                x: 18,
                y: 36,
                width: 60,
                height: 24,
            },
            "hub_title" => Layout {
                x: 60,
                y: 176,
                width: 120,
                height: 28,
            },
            "hub_subtitle" => Layout {
                x: 60,
                y: 204,
                width: 120,
                height: 18,
            },
            "list_title" => Layout {
                x: 20,
                y: 42,
                width: 200,
                height: 24,
            },
            "list_subtitle" => Layout {
                x: 20,
                y: 66,
                width: 200,
                height: 18,
            },
            "list_row" => {
                let index = self.list_row_count;
                self.list_row_count += 1;
                Layout {
                    x: 16,
                    y: 94 + (index as i32 * 36),
                    width: 208,
                    height: 32,
                }
            }
            "list_row_icon" => Layout {
                x: 8,
                y: 8,
                width: 40,
                height: 14,
            },
            "list_row_title" => Layout {
                x: 48,
                y: 5,
                width: 144,
                height: 14,
            },
            "list_row_subtitle" => Layout {
                x: 48,
                y: 18,
                width: 144,
                height: 12,
            },
            "now_playing_title" => Layout {
                x: 20,
                y: 134,
                width: 200,
                height: 22,
            },
            "now_playing_artist" => Layout {
                x: 20,
                y: 160,
                width: 200,
                height: 18,
            },
            "now_playing_state" => Layout {
                x: 20,
                y: 190,
                width: 200,
                height: 18,
            },
            "now_playing_progress" => Layout {
                x: 20,
                y: 216,
                width: 200,
                height: 18,
            },
            "now_playing_art" => Layout {
                x: 76,
                y: 42,
                width: 88,
                height: 78,
            },
            "now_playing_art_icon" => Layout {
                x: 20,
                y: 26,
                width: 48,
                height: 24,
            },
            "ask_icon_halo" => Layout {
                x: 72,
                y: 56,
                width: 96,
                height: 96,
            },
            "ask_icon" => Layout {
                x: 18,
                y: 36,
                width: 60,
                height: 24,
            },
            "ask_title" => Layout {
                x: 20,
                y: 176,
                width: 200,
                height: 24,
            },
            "ask_subtitle" => Layout {
                x: 24,
                y: 212,
                width: 192,
                height: 28,
            },
            "call_panel" => Layout {
                x: 72,
                y: 54,
                width: 96,
                height: 96,
            },
            "call_state_icon" => Layout {
                x: 18,
                y: 36,
                width: 60,
                height: 24,
            },
            "call_title" => Layout {
                x: 30,
                y: 176,
                width: 200,
                height: 24,
            },
            "call_subtitle" => Layout {
                x: 30,
                y: 204,
                width: 180,
                height: 18,
            },
            "call_detail" => Layout {
                x: 48,
                y: 226,
                width: 144,
                height: 18,
            },
            "call_mute_badge" => Layout {
                x: 72,
                y: 232,
                width: 96,
                height: 18,
            },
            "power_icon_halo" => Layout {
                x: 92,
                y: 42,
                width: 56,
                height: 56,
            },
            "power_icon" => Layout {
                x: 8,
                y: 18,
                width: 40,
                height: 18,
            },
            "power_title" => Layout {
                x: 60,
                y: 98,
                width: 120,
                height: 24,
            },
            "power_subtitle" => Layout {
                x: 20,
                y: 122,
                width: 200,
                height: 18,
            },
            "power_row" => {
                let index = self.power_row_count;
                self.power_row_count += 1;
                Layout {
                    x: 16,
                    y: 146 + (index as i32 * 24),
                    width: 208,
                    height: 20,
                }
            }
            "power_row_icon" => Layout {
                x: 8,
                y: 6,
                width: 40,
                height: 14,
            },
            "power_row_title" => Layout {
                x: 48,
                y: 3,
                width: 144,
                height: 14,
            },
            "power_row_subtitle" => Layout {
                x: 48,
                y: 15,
                width: 144,
                height: 12,
            },
            "overlay_title" => Layout {
                x: 20,
                y: 104,
                width: 200,
                height: 24,
            },
            "overlay_subtitle" => Layout {
                x: 20,
                y: 136,
                width: 200,
                height: 20,
            },
            _ if parent_role == "list_row" || parent_role == "power_row" => Layout {
                x: 8,
                y: 8,
                width: 180,
                height: 16,
            },
            _ => Layout {
                x: 20,
                y: 20,
                width: 200,
                height: 18,
            },
        };

        Ok(layout)
    }
}

impl LvglFacade for NativeLvglFacade {
    fn create_root(&mut self) -> Result<WidgetId> {
        let obj = unsafe { sys::lv_obj_create(ptr::null_mut()) };
        let obj = NonNull::new(obj).ok_or_else(|| anyhow!("LVGL root widget creation failed"))?;
        let layout = self.layout_for_root();
        Self::reset_style_raw(obj);
        Self::apply_style_raw(obj, theme::style_for_role("root"));
        Self::apply_layout_raw(obj, layout);
        unsafe {
            sys::lv_screen_load(obj.as_ptr());
        }
        self.list_row_count = 0;
        self.power_row_count = 0;
        let id = self.register_widget(obj, WidgetKind::Root, "root", None, layout);
        self.active_root = Some(id);
        Ok(id)
    }

    fn create_container(&mut self, parent: WidgetId, role: &'static str) -> Result<WidgetId> {
        let parent_obj = self.widget_obj(parent)?;
        let obj = unsafe { sys::lv_obj_create(parent_obj.as_ptr()) };
        let obj = NonNull::new(obj)
            .ok_or_else(|| anyhow!("LVGL container creation failed for {role}"))?;
        let layout = self.next_role_layout(Some(parent), role)?;
        Self::reset_style_raw(obj);
        Self::apply_style_raw(obj, theme::style_for_role(role));
        Self::apply_layout_raw(obj, layout);
        Ok(self.register_widget(obj, WidgetKind::Container, role, Some(parent), layout))
    }

    fn create_label(&mut self, parent: WidgetId, role: &'static str) -> Result<WidgetId> {
        let parent_obj = self.widget_obj(parent)?;
        let obj = unsafe { sys::lv_label_create(parent_obj.as_ptr()) };
        let obj =
            NonNull::new(obj).ok_or_else(|| anyhow!("LVGL label creation failed for {role}"))?;
        let layout = self.next_role_layout(Some(parent), role)?;
        Self::reset_style_raw(obj);
        Self::apply_style_raw(obj, theme::style_for_role(role));
        Self::apply_layout_raw(obj, layout);
        let empty = CString::new("").expect("empty CString");
        unsafe {
            sys::lv_label_set_text(obj.as_ptr(), empty.as_ptr());
        }
        Ok(self.register_widget(obj, WidgetKind::Label, role, Some(parent), layout))
    }

    fn set_text(&mut self, widget: WidgetId, text: &str) -> Result<()> {
        let obj = self.widget_obj(widget)?;
        let text = CString::new(text).with_context(|| {
            format!(
                "LVGL text for widget {} contains an interior NUL byte",
                widget.raw()
            )
        })?;
        unsafe {
            sys::lv_label_set_text(obj.as_ptr(), text.as_ptr());
        }
        Ok(())
    }

    fn set_selected(&mut self, _widget: WidgetId, _selected: bool) -> Result<()> {
        let node = self.widget_node_mut(_widget)?;
        if matches!(node.role, "list_row" | "power_row") {
            let mut layout = node.layout;
            if _selected {
                layout.x -= 6;
                layout.width += 12;
            }
            Self::apply_style_raw(
                node.obj,
                theme::style_for_selected_role(node.role, _selected),
            );
            Self::apply_layout_raw(node.obj, layout);
        }
        Ok(())
    }

    fn set_icon(&mut self, widget: WidgetId, icon_key: &str) -> Result<()> {
        self.set_text(widget, icon_label(icon_key))
    }

    fn set_progress(&mut self, widget: WidgetId, value: i32) -> Result<()> {
        let value = value.clamp(0, 1000);
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
        if visible {
            Self::apply_layout_raw(node.obj, node.layout);
        } else {
            Self::hide_widget_raw(node.obj);
        }
        Ok(())
    }

    fn set_accent(&mut self, widget: WidgetId, rgb: u32) -> Result<()> {
        let node = self.widget_node_mut(widget)?;
        Self::apply_accent_raw(node.obj, node.role, rgb);
        Ok(())
    }

    fn destroy(&mut self, widget: WidgetId) -> Result<()> {
        let obj = self.widget_obj(widget)?;
        if self.active_root == Some(widget) {
            let blank = self.ensure_blank_screen()?;
            unsafe {
                sys::lv_screen_load(blank.as_ptr());
            }
        }
        unsafe {
            sys::lv_obj_delete(obj.as_ptr());
        }
        self.remove_widget_subtree(widget);
        if self.active_root == Some(widget) {
            self.active_root = None;
            self.list_row_count = 0;
            self.power_row_count = 0;
        }
        Ok(())
    }
}

impl NativeLvglFacade {
    fn apply_accent_raw(obj: NonNull<sys::lv_obj_t>, role: &'static str, rgb: u32) {
        const SELECTOR: sys::LvStyleSelector = 0;
        let accent = sys::lv_color_hex(rgb & 0xFFFFFF);
        unsafe {
            match role {
                "hub_icon_glow" => {
                    sys::lv_obj_set_style_bg_color(obj.as_ptr(), accent, SELECTOR);
                    sys::lv_obj_set_style_bg_opa(obj.as_ptr(), 96, SELECTOR);
                }
                "hub_card_panel" | "call_panel" | "now_playing_art" => {
                    sys::lv_obj_set_style_bg_color(obj.as_ptr(), accent, SELECTOR);
                    sys::lv_obj_set_style_bg_opa(obj.as_ptr(), theme::OPA_COVER, SELECTOR);
                }
                "ask_icon_halo" | "power_icon_halo" => {
                    sys::lv_obj_set_style_bg_color(obj.as_ptr(), accent, SELECTOR);
                    sys::lv_obj_set_style_bg_opa(obj.as_ptr(), 64, SELECTOR);
                }
                "hub_icon"
                | "ask_icon"
                | "call_state_icon"
                | "list_row_icon"
                | "power_row_icon"
                | "now_playing_art_icon"
                | "power_icon"
                | "now_playing_progress" => {
                    sys::lv_obj_set_style_text_color(obj.as_ptr(), accent, SELECTOR);
                }
                "list_row" | "power_row" => {
                    sys::lv_obj_set_style_border_color(obj.as_ptr(), accent, SELECTOR);
                }
                _ => {}
            }
        }
    }
}

impl Drop for NativeLvglFacade {
    fn drop(&mut self) {
        if let Some(root) = self.active_root.take() {
            if let Some(node) = self.widgets.remove(&root) {
                unsafe {
                    sys::lv_obj_delete(node.obj.as_ptr());
                }
            }
        }
        if let Some(blank) = self.blank_screen.take() {
            unsafe {
                sys::lv_obj_delete(blank.as_ptr());
            }
        }
        self.invalidate_widget_registry();
        if let Some(display) = self.display.take() {
            unsafe {
                sys::lv_display_delete(display.as_ptr());
            }
        }
        unsafe {
            sys::lv_deinit();
        }
    }
}

fn validate_explicit_source_dir(explicit_source: Option<&Path>) -> Result<()> {
    if let Some(source) = explicit_source {
        if source.exists() {
            return Ok(());
        }
        bail!("LVGL source directory not found at {}", source.display());
    }

    Ok(())
}

fn icon_label(icon_key: &str) -> &'static str {
    match icon_key {
        "ask" => "ASK",
        "battery" => "PWR",
        "call_active" => "CALL",
        "call_incoming" => "RING",
        "call_outgoing" => "DIAL",
        "microphone" => "MIC",
        "playlist" => "LIST",
        "recent" => "HIST",
        "talk" => "TALK",
        "track" => "PLAY",
        _ => "UI",
    }
}

unsafe extern "C" fn lvgl_flush_callback(
    display: *mut sys::lv_display_t,
    area: *const sys::lv_area_t,
    px_map: *mut u8,
) {
    let Some(area) = area.as_ref() else {
        if let Some(display) = NonNull::new(display) {
            unsafe {
                sys::lv_display_flush_ready(display.as_ptr());
            }
        }
        return;
    };

    let width = (area.x2 - area.x1 + 1).max(0) as usize;
    let height = (area.y2 - area.y1 + 1).max(0) as usize;

    if width == 0 || height == 0 || px_map.is_null() {
        if let Some(display) = NonNull::new(display) {
            unsafe {
                sys::lv_display_flush_ready(display.as_ptr());
            }
        }
        return;
    }

    let Some(display) = NonNull::new(display) else {
        return;
    };
    let target = unsafe { sys::lv_display_get_user_data(display.as_ptr()) as *mut FlushTarget };
    if target.is_null() {
        unsafe {
            sys::lv_display_flush_ready(display.as_ptr());
        }
        return;
    }

    let draw_len = width * height * 2;
    let pixels = unsafe { std::slice::from_raw_parts(px_map, draw_len) };
    let target = unsafe { &mut *target };
    if !target.framebuffer.is_null() {
        let mut swapped = Vec::with_capacity(draw_len);
        for pair in pixels.chunks_exact(2) {
            swapped.push(pair[1]);
            swapped.push(pair[0]);
        }
        let framebuffer = unsafe { &mut *target.framebuffer };
        framebuffer.paste_be_bytes_region(
            area.x1.max(0) as usize,
            area.y1.max(0) as usize,
            width,
            height,
            &swapped,
        );
    }

    unsafe {
        sys::lv_display_flush_ready(display.as_ptr());
    }
}
