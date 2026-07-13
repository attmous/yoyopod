use std::ptr::NonNull;

use anyhow::{anyhow, bail, Result};

use crate::renderer::lvgl::ffi;
use crate::renderer::lvgl::NativeLvglFacade;
use crate::screenshot::Rgb565Image;

impl NativeLvglFacade {
    /// Render the active LVGL screen into a fresh RGB565 buffer via
    /// `lv_snapshot_take` — the readback capture path, independent of the
    /// shadow framebuffer maintained by the flush callback.
    pub(crate) fn snapshot_active_screen(&mut self) -> Result<Rgb565Image> {
        let display = self
            .display
            .ok_or_else(|| anyhow!("LVGL display not initialized"))?;
        let screen = unsafe { ffi::lv_display_get_screen_active(display.as_ptr()) };
        let screen = NonNull::new(screen).ok_or_else(|| anyhow!("LVGL has no active screen"))?;

        let draw_buf =
            unsafe { ffi::lv_snapshot_take(screen.as_ptr(), ffi::LV_COLOR_FORMAT_RGB565) };
        let draw_buf =
            NonNull::new(draw_buf).ok_or_else(|| anyhow!("lv_snapshot_take returned no buffer"))?;
        let image = image_from_draw_buf(unsafe { draw_buf.as_ref() });
        unsafe {
            ffi::lv_draw_buf_destroy(draw_buf.as_ptr());
        }
        image
    }
}

fn image_from_draw_buf(draw_buf: &ffi::lv_draw_buf_t) -> Result<Rgb565Image> {
    let header = &draw_buf.header;
    if header.color_format() != ffi::LV_COLOR_FORMAT_RGB565 {
        bail!(
            "LVGL snapshot returned color format {:#x} instead of RGB565",
            header.color_format()
        );
    }

    let width = header.width();
    let height = header.height();
    if width == 0 || height == 0 {
        bail!("LVGL snapshot has empty dimensions {width}x{height}");
    }
    if draw_buf.data.is_null() {
        bail!("LVGL snapshot has no pixel data");
    }

    let row_bytes = width * 2;
    let stride = match header.stride() {
        0 => row_bytes,
        stride if stride >= row_bytes => stride,
        stride => bail!("LVGL snapshot stride {stride} is smaller than row size {row_bytes}"),
    };
    let data_size = draw_buf.data_size as usize;
    let needed = stride * (height - 1) + row_bytes;
    if data_size < needed {
        bail!("LVGL snapshot buffer holds {data_size} bytes, expected at least {needed}");
    }

    // LVGL renders native RGB565: little-endian u16 values in memory.
    let data = unsafe { std::slice::from_raw_parts(draw_buf.data, data_size) };
    let mut pixels = Vec::with_capacity(width * height);
    for row in 0..height {
        let start = row * stride;
        for pair in data[start..start + row_bytes].chunks_exact(2) {
            pixels.push(u16::from_le_bytes([pair[0], pair[1]]));
        }
    }
    Ok(Rgb565Image {
        width,
        height,
        pixels,
    })
}
