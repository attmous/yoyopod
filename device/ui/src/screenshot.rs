//! Screenshot capture for `yoyopod target screenshot`.
//!
//! The runtime forwards SIGUSR1/SIGUSR2 as a `ui.screenshot` command; this
//! module renders the requested capture (LVGL readback or the shadow
//! framebuffer) to a PNG and writes it atomically so the CLI never scp's a
//! half-written file.

use std::fs;
use std::io::BufWriter;
use std::path::{Path, PathBuf};

use anyhow::{bail, Context, Result};
use yoyopod_protocol::ui::{ScreenshotMethod, UiScreenshotCaptured};

use crate::renderer::Framebuffer;

/// A full-frame RGB565 capture.
pub struct Rgb565Image {
    pub width: usize,
    pub height: usize,
    pub pixels: Vec<u16>,
}

impl Rgb565Image {
    pub fn from_framebuffer(framebuffer: &Framebuffer) -> Self {
        Self {
            width: framebuffer.width(),
            height: framebuffer.height(),
            pixels: framebuffer.pixels().to_vec(),
        }
    }

    fn to_rgb888(&self) -> Vec<u8> {
        let mut bytes = Vec::with_capacity(self.pixels.len() * 3);
        for &pixel in &self.pixels {
            let red = ((pixel >> 11) & 0x1F) as u8;
            let green = ((pixel >> 5) & 0x3F) as u8;
            let blue = (pixel & 0x1F) as u8;
            bytes.push((red << 3) | (red >> 2));
            bytes.push((green << 2) | (green >> 4));
            bytes.push((blue << 3) | (blue >> 2));
        }
        bytes
    }
}

/// Capture order mirrors the Python supervisor: the preferred method first,
/// the other as fallback, first fully-written PNG wins.
pub(crate) fn capture(
    mut readback: impl FnMut() -> Result<Rgb565Image>,
    mut shadow: impl FnMut() -> Result<Rgb565Image>,
    path: &str,
    prefer_readback: bool,
) -> UiScreenshotCaptured {
    let order = if prefer_readback {
        [
            ScreenshotMethod::LvglReadback,
            ScreenshotMethod::ShadowBuffer,
        ]
    } else {
        [
            ScreenshotMethod::ShadowBuffer,
            ScreenshotMethod::LvglReadback,
        ]
    };

    let mut failures = Vec::new();
    for method in order {
        let attempt = match method {
            ScreenshotMethod::LvglReadback => readback(),
            ScreenshotMethod::ShadowBuffer => shadow(),
        }
        .and_then(|image| write_png_atomic(Path::new(path), &image));
        match attempt {
            Ok(()) => {
                return UiScreenshotCaptured {
                    path: path.to_string(),
                    ok: true,
                    method: Some(method),
                    detail: String::new(),
                }
            }
            Err(error) => failures.push(format!("{}: {error:#}", method.label())),
        }
    }

    UiScreenshotCaptured {
        path: path.to_string(),
        ok: false,
        method: None,
        detail: failures.join("; "),
    }
}

fn write_png_atomic(path: &Path, image: &Rgb565Image) -> Result<()> {
    if image.width == 0 || image.height == 0 {
        bail!("screenshot image is empty");
    }
    if image.pixels.len() != image.width * image.height {
        bail!(
            "screenshot pixel count {} does not match {}x{}",
            image.pixels.len(),
            image.width,
            image.height
        );
    }
    if let Some(parent) = path.parent() {
        if !parent.as_os_str().is_empty() {
            fs::create_dir_all(parent)
                .with_context(|| format!("create screenshot directory {}", parent.display()))?;
        }
    }

    let tmp_path = temp_sibling(path);
    if let Err(error) = write_png(&tmp_path, image) {
        let _ = fs::remove_file(&tmp_path);
        return Err(error);
    }
    fs::rename(&tmp_path, path).with_context(|| {
        format!(
            "move screenshot {} into place at {}",
            tmp_path.display(),
            path.display()
        )
    })
}

fn temp_sibling(path: &Path) -> PathBuf {
    let mut name = path
        .file_name()
        .map(|name| name.to_os_string())
        .unwrap_or_else(|| "screenshot.png".into());
    name.push(".tmp");
    path.with_file_name(name)
}

fn write_png(path: &Path, image: &Rgb565Image) -> Result<()> {
    let file =
        fs::File::create(path).with_context(|| format!("create screenshot {}", path.display()))?;
    let mut encoder = png::Encoder::new(
        BufWriter::new(file),
        image.width as u32,
        image.height as u32,
    );
    encoder.set_color(png::ColorType::Rgb);
    encoder.set_depth(png::BitDepth::Eight);
    let mut writer = encoder.write_header().context("write PNG header")?;
    writer
        .write_image_data(&image.to_rgb888())
        .context("write PNG pixel data")?;
    writer.finish().context("finalize PNG")?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn solid_image(width: usize, height: usize, pixel: u16) -> Rgb565Image {
        Rgb565Image {
            width,
            height,
            pixels: vec![pixel; width * height],
        }
    }

    fn temp_png(name: &str) -> PathBuf {
        std::env::temp_dir().join(format!(
            "yoyopod-screenshot-{}-{name}.png",
            std::process::id()
        ))
    }

    fn decode_png(path: &Path) -> (u32, u32, Vec<u8>) {
        let decoder = png::Decoder::new(fs::File::open(path).unwrap());
        let mut reader = decoder.read_info().unwrap();
        let mut buffer = vec![0; reader.output_buffer_size()];
        let info = reader.next_frame(&mut buffer).unwrap();
        buffer.truncate(info.buffer_size());
        (info.width, info.height, buffer)
    }

    #[test]
    fn rgb565_expands_to_full_range_rgb888() {
        let image = Rgb565Image {
            width: 4,
            height: 1,
            pixels: vec![0xF800, 0x07E0, 0x001F, 0xFFFF],
        };
        assert_eq!(
            image.to_rgb888(),
            vec![255, 0, 0, 0, 255, 0, 0, 0, 255, 255, 255, 255]
        );
    }

    #[test]
    fn shadow_first_capture_writes_decodable_png() {
        let path = temp_png("shadow-first");
        let _ = fs::remove_file(&path);

        let captured = capture(
            || bail!("readback must not run for shadow-first capture"),
            || Ok(solid_image(4, 3, 0xF800)),
            path.to_str().unwrap(),
            false,
        );

        assert!(captured.ok);
        assert_eq!(captured.method, Some(ScreenshotMethod::ShadowBuffer));
        let (width, height, pixels) = decode_png(&path);
        assert_eq!((width, height), (4, 3));
        assert_eq!(&pixels[..3], &[255, 0, 0]);
        assert!(!temp_sibling(&path).exists());
        let _ = fs::remove_file(&path);
    }

    #[test]
    fn readback_first_capture_prefers_readback() {
        let path = temp_png("readback-first");
        let _ = fs::remove_file(&path);

        let captured = capture(
            || Ok(solid_image(2, 2, 0x001F)),
            || Ok(solid_image(2, 2, 0xF800)),
            path.to_str().unwrap(),
            true,
        );

        assert!(captured.ok);
        assert_eq!(captured.method, Some(ScreenshotMethod::LvglReadback));
        let (_, _, pixels) = decode_png(&path);
        assert_eq!(&pixels[..3], &[0, 0, 255]);
        let _ = fs::remove_file(&path);
    }

    #[test]
    fn failed_readback_falls_back_to_shadow() {
        let path = temp_png("readback-fallback");
        let _ = fs::remove_file(&path);

        let captured = capture(
            || bail!("native-lvgl feature is disabled for this build"),
            || Ok(solid_image(2, 2, 0x07E0)),
            path.to_str().unwrap(),
            true,
        );

        assert!(captured.ok);
        assert_eq!(captured.method, Some(ScreenshotMethod::ShadowBuffer));
        assert!(path.exists());
        let _ = fs::remove_file(&path);
    }

    #[test]
    fn capture_reports_failure_when_both_methods_fail() {
        let path = temp_png("both-fail");
        let _ = fs::remove_file(&path);

        let captured = capture(
            || bail!("readback unavailable"),
            || bail!("shadow unavailable"),
            path.to_str().unwrap(),
            false,
        );

        assert!(!captured.ok);
        assert_eq!(captured.method, None);
        assert!(captured.detail.contains("readback unavailable"));
        assert!(captured.detail.contains("shadow unavailable"));
        assert!(!path.exists());
    }

    #[test]
    fn mismatched_pixel_count_is_rejected() {
        let path = temp_png("bad-image");
        let _ = fs::remove_file(&path);

        let captured = capture(
            || bail!("readback unavailable"),
            || {
                Ok(Rgb565Image {
                    width: 4,
                    height: 4,
                    pixels: vec![0; 3],
                })
            },
            path.to_str().unwrap(),
            false,
        );

        assert!(!captured.ok);
        assert!(!path.exists());
        assert!(!temp_sibling(&path).exists());
    }
}
