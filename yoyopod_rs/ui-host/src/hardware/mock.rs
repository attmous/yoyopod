use anyhow::Result;

use crate::framebuffer::Framebuffer;
use crate::hardware::{ButtonDevice, DisplayDevice};

#[derive(Debug)]
pub struct MockDisplay {
    width: usize,
    height: usize,
    pub frames: usize,
}

impl MockDisplay {
    pub fn new(width: usize, height: usize) -> Self {
        Self {
            width,
            height,
            frames: 0,
        }
    }
}

impl DisplayDevice for MockDisplay {
    fn width(&self) -> usize {
        self.width
    }

    fn height(&self) -> usize {
        self.height
    }

    fn flush_full_frame(&mut self, _framebuffer: &Framebuffer) -> Result<()> {
        self.frames += 1;
        Ok(())
    }

    fn set_backlight(&mut self, _brightness: f32) -> Result<()> {
        Ok(())
    }
}

#[derive(Debug, Default)]
pub struct MockButton {
    pressed: bool,
}

impl MockButton {
    pub fn new() -> Self {
        Self::default()
    }
}

impl ButtonDevice for MockButton {
    fn pressed(&mut self) -> Result<bool> {
        Ok(self.pressed)
    }
}
