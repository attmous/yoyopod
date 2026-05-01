mod chrome;
pub mod controllers;
#[cfg(feature = "native-lvgl")]
mod hub_icon_assets;
#[cfg(feature = "native-lvgl")]
mod native_backend;
pub mod primitives;
pub mod scene_backend;
#[cfg(feature = "native-lvgl")]
pub mod sys;
pub mod theme;

use std::path::Path;

#[cfg(not(feature = "native-lvgl"))]
use anyhow::bail;
use anyhow::{anyhow, Result};

use crate::runtime::UiScreen;
use crate::screens::ScreenModel;

pub use controllers::{
    AskController, CallController, HubController, ListController, ListenController,
    NowPlayingController, OverlayController, PlaylistController, PowerController, ScreenController,
    TalkActionsController, TalkController,
};
#[cfg(feature = "native-lvgl")]
pub use native_backend::NativeLvglFacade;
pub use primitives::WidgetId;
#[cfg(feature = "native-lvgl")]
pub use scene_backend::ShimSceneBridge;
pub use scene_backend::{NativeSceneRenderer, RustSceneBridge, SceneBridge};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SceneKey {
    Hub,
    List,
    NowPlaying,
    Ask,
    Call,
    Power,
    Overlay,
}

impl SceneKey {
    pub const fn for_screen(screen: UiScreen) -> Self {
        match screen {
            UiScreen::Hub => Self::Hub,
            UiScreen::Listen
            | UiScreen::Playlists
            | UiScreen::RecentTracks
            | UiScreen::Talk
            | UiScreen::Contacts
            | UiScreen::CallHistory => Self::List,
            UiScreen::NowPlaying => Self::NowPlaying,
            UiScreen::Ask | UiScreen::VoiceNote => Self::Ask,
            UiScreen::IncomingCall | UiScreen::OutgoingCall | UiScreen::InCall => Self::Call,
            UiScreen::Power => Self::Power,
            UiScreen::Loading | UiScreen::Error => Self::Overlay,
        }
    }

    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Hub => "hub",
            Self::List => "list",
            Self::NowPlaying => "now_playing",
            Self::Ask => "ask",
            Self::Call => "call",
            Self::Power => "power",
            Self::Overlay => "overlay",
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum NativeSceneKey {
    Hub,
    Listen,
    Playlist,
    NowPlaying,
    Talk,
    TalkActions,
    IncomingCall,
    OutgoingCall,
    InCall,
    Ask,
    Power,
    Overlay,
}

impl NativeSceneKey {
    pub const fn for_screen(screen: UiScreen) -> Self {
        match screen {
            UiScreen::Hub => Self::Hub,
            UiScreen::Listen => Self::Listen,
            UiScreen::Playlists
            | UiScreen::RecentTracks
            | UiScreen::Contacts
            | UiScreen::CallHistory => Self::Playlist,
            UiScreen::NowPlaying => Self::NowPlaying,
            UiScreen::Talk => Self::Talk,
            UiScreen::VoiceNote => Self::TalkActions,
            UiScreen::IncomingCall => Self::IncomingCall,
            UiScreen::OutgoingCall => Self::OutgoingCall,
            UiScreen::InCall => Self::InCall,
            UiScreen::Ask => Self::Ask,
            UiScreen::Power => Self::Power,
            UiScreen::Loading | UiScreen::Error => Self::Overlay,
        }
    }

    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Hub => "hub",
            Self::Listen => "listen",
            Self::Playlist => "playlist",
            Self::NowPlaying => "now_playing",
            Self::Talk => "talk",
            Self::TalkActions => "talk_actions",
            Self::IncomingCall => "incoming_call",
            Self::OutgoingCall => "outgoing_call",
            Self::InCall => "in_call",
            Self::Ask => "ask",
            Self::Power => "power",
            Self::Overlay => "overlay",
        }
    }
}

pub trait LvglFacade {
    fn create_root(&mut self) -> Result<WidgetId>;

    fn create_container(&mut self, parent: WidgetId, role: &'static str) -> Result<WidgetId>;

    fn create_label(&mut self, parent: WidgetId, role: &'static str) -> Result<WidgetId>;

    fn set_text(&mut self, widget: WidgetId, text: &str) -> Result<()>;

    fn set_selected(&mut self, widget: WidgetId, selected: bool) -> Result<()>;

    fn set_icon(&mut self, widget: WidgetId, icon_key: &str) -> Result<()>;

    fn set_progress(&mut self, widget: WidgetId, value: i32) -> Result<()>;

    fn set_visible(&mut self, widget: WidgetId, visible: bool) -> Result<()>;

    fn set_accent(&mut self, widget: WidgetId, rgb: u32) -> Result<()> {
        let _ = (widget, rgb);
        Ok(())
    }

    fn destroy(&mut self, widget: WidgetId) -> Result<()>;
}

impl<T> LvglFacade for Box<T>
where
    T: LvglFacade + ?Sized,
{
    fn create_root(&mut self) -> Result<WidgetId> {
        (**self).create_root()
    }

    fn create_container(&mut self, parent: WidgetId, role: &'static str) -> Result<WidgetId> {
        (**self).create_container(parent, role)
    }

    fn create_label(&mut self, parent: WidgetId, role: &'static str) -> Result<WidgetId> {
        (**self).create_label(parent, role)
    }

    fn set_text(&mut self, widget: WidgetId, text: &str) -> Result<()> {
        (**self).set_text(widget, text)
    }

    fn set_selected(&mut self, widget: WidgetId, selected: bool) -> Result<()> {
        (**self).set_selected(widget, selected)
    }

    fn set_icon(&mut self, widget: WidgetId, icon_key: &str) -> Result<()> {
        (**self).set_icon(widget, icon_key)
    }

    fn set_progress(&mut self, widget: WidgetId, value: i32) -> Result<()> {
        (**self).set_progress(widget, value)
    }

    fn set_visible(&mut self, widget: WidgetId, visible: bool) -> Result<()> {
        (**self).set_visible(widget, visible)
    }

    fn set_accent(&mut self, widget: WidgetId, rgb: u32) -> Result<()> {
        (**self).set_accent(widget, rgb)
    }

    fn destroy(&mut self, widget: WidgetId) -> Result<()> {
        (**self).destroy(widget)
    }
}

pub struct LvglRenderer<F> {
    facade: F,
    active_scene: Option<SceneKey>,
    active_screen: Option<UiScreen>,
    controller: Option<Box<dyn ScreenController>>,
}

impl<F> LvglRenderer<F>
where
    F: LvglFacade,
{
    pub fn new(facade: F) -> Self {
        Self {
            facade,
            active_scene: None,
            active_screen: None,
            controller: None,
        }
    }

    pub fn render(&mut self, model: &ScreenModel) -> Result<()> {
        let screen = model.screen();
        let scene = SceneKey::for_screen(screen);

        if self.active_scene != Some(scene) {
            let next = controller_for_scene(scene, screen)?;
            self.clear()?;
            self.controller = Some(next);
            self.active_scene = Some(scene);
        }

        let controller = self
            .controller
            .as_mut()
            .ok_or_else(|| anyhow!("LVGL renderer has no controller for {}", screen.as_str()))?;
        controller.sync(&mut self.facade, model)?;
        self.active_screen = Some(screen);
        Ok(())
    }

    pub fn clear(&mut self) -> Result<()> {
        if let Some(controller) = self.controller.as_mut() {
            controller.teardown(&mut self.facade)?;
        }
        self.controller = None;
        self.active_scene = None;
        self.active_screen = None;
        Ok(())
    }

    pub fn active_scene(&self) -> Option<SceneKey> {
        self.active_scene
    }

    pub fn active_screen(&self) -> Option<UiScreen> {
        self.active_screen
    }

    pub fn facade(&self) -> &F {
        &self.facade
    }

    pub fn facade_mut(&mut self) -> &mut F {
        &mut self.facade
    }
}

fn controller_for_scene(scene: SceneKey, _screen: UiScreen) -> Result<Box<dyn ScreenController>> {
    match scene {
        SceneKey::Hub => Ok(Box::new(HubController::default())),
        SceneKey::List => Ok(Box::new(ListController::default())),
        SceneKey::Ask => Ok(Box::new(AskController::default())),
        SceneKey::NowPlaying => Ok(Box::new(NowPlayingController::default())),
        SceneKey::Call => Ok(Box::new(CallController::default())),
        SceneKey::Power => Ok(Box::new(PowerController::default())),
        SceneKey::Overlay => Ok(Box::new(OverlayController::default())),
    }
}

#[cfg(feature = "native-lvgl")]
pub fn open_default_facade(explicit_source: Option<&Path>) -> Result<Box<dyn LvglFacade>> {
    Ok(Box::new(NativeLvglFacade::open(explicit_source)?))
}

#[cfg(not(feature = "native-lvgl"))]
pub fn open_default_facade(_explicit_source: Option<&Path>) -> Result<Box<dyn LvglFacade>> {
    bail!("native-lvgl feature is disabled for this build")
}
