use std::path::Path;
use std::ptr;
use std::time::Instant;

use anyhow::{anyhow, bail, Context, Result};

use crate::renderer::assets;
use crate::renderer::lvgl::ffi;
use crate::renderer::lvgl::flush::lvgl_flush_callback;
use crate::renderer::lvgl::NativeLvglFacade;
use crate::renderer::Framebuffer;
use crate::theme::ColorScheme;

const DRAW_BUFFER_ROWS: usize = 40;

impl NativeLvglFacade {
    pub fn open(explicit_source: Option<&Path>) -> Result<Self> {
        validate_explicit_source_dir(explicit_source)?;
        let render_assets = assets::load_render_assets().context("loading LVGL render assets")?;
        unsafe {
            ffi::lv_init();
        }

        Ok(Self {
            display: None,
            blank_screen: None,
            draw_buffer: Vec::new(),
            flush_target: Default::default(),
            display_size: None,
            last_tick: Instant::now(),
            widgets: Default::default(),
            active_root: None,
            render_assets,
            color_scheme: ColorScheme::Light,
        })
    }

    pub(crate) fn set_color_scheme(&mut self, color_scheme: ColorScheme) -> Result<bool> {
        if self.color_scheme == color_scheme {
            return Ok(false);
        }
        self.color_scheme = color_scheme;

        if let Some(blank) = self.blank_screen {
            crate::renderer::styling::reset_style_raw(blank);
            crate::renderer::styling::apply_style_raw(
                blank,
                self.style_for_role(crate::scene::roles::ROOT)?,
            );
        }

        if let Some(root) = self.active_root.take() {
            let root_obj = self.widget_obj(root)?;
            let blank = self.ensure_blank_screen()?;
            unsafe {
                ffi::lv_screen_load(blank.as_ptr());
                ffi::lv_obj_delete(root_obj.as_ptr());
            }
        }
        self.widgets.clear();
        Ok(true)
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
                ffi::lv_display_delete(display.as_ptr());
            }
        }
        self.invalidate_widget_registry();
        self.display_size = Some(size);

        let display = unsafe { ffi::lv_display_create(size.0 as i32, size.1 as i32) };
        let display = std::ptr::NonNull::new(display)
            .ok_or_else(|| anyhow!("LVGL display creation failed"))?;

        self.draw_buffer = vec![0; size.0 * DRAW_BUFFER_ROWS * 2];
        unsafe {
            ffi::lv_display_set_default(display.as_ptr());
            ffi::lv_display_set_flush_cb(display.as_ptr(), Some(lvgl_flush_callback));
            ffi::lv_display_set_user_data(
                display.as_ptr(),
                &mut self.flush_target as *mut _ as *mut _,
            );
            ffi::lv_display_set_buffers(
                display.as_ptr(),
                self.draw_buffer.as_mut_ptr().cast(),
                ptr::null_mut(),
                self.draw_buffer.len() as u32,
                ffi::LV_DISPLAY_RENDER_MODE_PARTIAL,
            );
        }

        self.display = Some(display);
        Ok(())
    }

    pub(crate) fn render_frame(&mut self, framebuffer: &mut Framebuffer) -> Result<()> {
        self.ensure_display_registered(framebuffer)?;
        self.flush_target.framebuffer = framebuffer as *mut Framebuffer;
        self.invalidate_active_screen()?;
        self.tick_lvgl();
        Ok(())
    }

    fn invalidate_active_screen(&self) -> Result<()> {
        if let Some(root) = self.active_root {
            let root_obj = self.widget_obj(root)?;
            unsafe {
                ffi::lv_obj_invalidate(root_obj.as_ptr());
            }
        } else if let Some(display) = self.display {
            let active = unsafe { ffi::lv_display_get_screen_active(display.as_ptr()) };
            if let Some(active) = std::ptr::NonNull::new(active) {
                unsafe {
                    ffi::lv_obj_invalidate(active.as_ptr());
                }
            }
        }
        Ok(())
    }

    fn tick_lvgl(&mut self) {
        let elapsed_ms = self
            .last_tick
            .elapsed()
            .as_millis()
            .min(u128::from(u32::MAX)) as u32;
        self.last_tick = Instant::now();
        unsafe {
            ffi::lv_tick_inc(elapsed_ms.max(1));
            let _ = ffi::lv_timer_handler();
        }
    }
}

impl Drop for NativeLvglFacade {
    fn drop(&mut self) {
        if let Some(root) = self.active_root.take() {
            if let Ok(obj) = self.widgets.obj(root) {
                unsafe {
                    ffi::lv_obj_delete(obj.as_ptr());
                }
            }
        }
        if let Some(blank) = self.blank_screen.take() {
            unsafe {
                ffi::lv_obj_delete(blank.as_ptr());
            }
        }
        self.invalidate_widget_registry();
        if let Some(display) = self.display.take() {
            unsafe {
                ffi::lv_display_delete(display.as_ptr());
            }
        }
        unsafe {
            ffi::lv_deinit();
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
