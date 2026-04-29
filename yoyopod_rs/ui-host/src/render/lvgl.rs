use crate::runtime::UiScreen;

pub use crate::lvgl_bridge::LvglRenderer;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RendererMode {
    Auto,
    Lvgl,
    Framebuffer,
}

impl RendererMode {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Auto => "auto",
            Self::Lvgl => "lvgl",
            Self::Framebuffer => "framebuffer",
        }
    }
}

#[derive(Debug, Default)]
pub struct RendererState {
    active_screen: Option<UiScreen>,
}

impl RendererState {
    pub fn needs_rebuild(&self, screen: UiScreen) -> bool {
        self.active_screen != Some(screen)
    }

    pub fn mark_screen_built(&mut self, screen: UiScreen) {
        self.active_screen = Some(screen);
    }

    pub fn clear(&mut self) {
        self.active_screen = None;
    }

    pub fn active_screen(&self) -> Option<UiScreen> {
        self.active_screen
    }
}
