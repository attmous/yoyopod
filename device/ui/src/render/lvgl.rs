use std::path::Path;

use anyhow::{bail, Result};

use crate::framebuffer::Framebuffer;
use crate::lvgl::{LvglFacade, LvglRenderer as SemanticLvglRenderer};
#[cfg(feature = "native-lvgl")]
use crate::lvgl::{
    NativeLvglFacade, NativeSceneRenderer, RustSceneBridge, SceneBridge, ShimSceneBridge,
};
use crate::screens::ScreenModel;

#[cfg(feature = "native-lvgl")]
const SCENE_BACKEND_ENV: &str = "YOYOPOD_LVGL_SCENE_BACKEND";

#[cfg(feature = "native-lvgl")]
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum SceneBackendMode {
    Shim,
    Rust,
}

#[cfg(feature = "native-lvgl")]
fn scene_backend_mode_from_value(value: Option<&str>) -> Result<SceneBackendMode> {
    let value = value.map(str::trim).filter(|value| !value.is_empty());
    match value.unwrap_or("rust").to_ascii_lowercase().as_str() {
        "shim" | "c" | "lvgl_shim" => Ok(SceneBackendMode::Shim),
        "rust" | "native" | "rust_native" => Ok(SceneBackendMode::Rust),
        other => bail!("unsupported {SCENE_BACKEND_ENV}={other:?}; expected shim or rust"),
    }
}

#[cfg(feature = "native-lvgl")]
fn scene_backend_mode_from_env() -> Result<SceneBackendMode> {
    let value = std::env::var(SCENE_BACKEND_ENV).ok();
    scene_backend_mode_from_value(value.as_deref())
}

#[allow(dead_code)]
pub(crate) trait RuntimeLvglBackend: LvglFacade {
    fn display_needs_reset(&self, framebuffer: &Framebuffer) -> bool;
    fn ensure_display_registered(&mut self, framebuffer: &Framebuffer) -> Result<()>;
    fn render_frame(&mut self, framebuffer: &mut Framebuffer) -> Result<()>;
}

#[cfg(feature = "native-lvgl")]
impl RuntimeLvglBackend for NativeLvglFacade {
    fn display_needs_reset(&self, framebuffer: &Framebuffer) -> bool {
        NativeLvglFacade::display_needs_reset(self, framebuffer)
    }

    fn ensure_display_registered(&mut self, framebuffer: &Framebuffer) -> Result<()> {
        NativeLvglFacade::ensure_display_registered(self, framebuffer)
    }

    fn render_frame(&mut self, framebuffer: &mut Framebuffer) -> Result<()> {
        NativeLvglFacade::render_frame(self, framebuffer)
    }
}

#[allow(dead_code)]
pub(crate) struct RuntimeLvglRenderer<B> {
    renderer: SemanticLvglRenderer<B>,
}

impl<B> RuntimeLvglRenderer<B>
where
    B: RuntimeLvglBackend,
{
    #[allow(dead_code)]
    pub fn render_screen_model(
        &mut self,
        framebuffer: &mut Framebuffer,
        model: &ScreenModel,
    ) -> Result<()> {
        if self.renderer.facade().display_needs_reset(framebuffer) {
            self.renderer.clear()?;
        }
        self.renderer
            .facade_mut()
            .ensure_display_registered(framebuffer)?;
        self.renderer.render(model)?;
        self.renderer.facade_mut().render_frame(framebuffer)
    }

}

#[cfg(not(feature = "native-lvgl"))]
pub struct LvglRenderer;

#[cfg(feature = "native-lvgl")]
pub struct LvglRenderer {
    renderer: ActiveRuntimeSceneLvglRenderer,
}

#[cfg(feature = "native-lvgl")]
impl LvglRenderer {
    pub fn open(explicit_source: Option<&Path>) -> Result<Self> {
        let renderer = match scene_backend_mode_from_env()? {
            SceneBackendMode::Shim => ActiveRuntimeSceneLvglRenderer::Shim(
                RuntimeSceneLvglRenderer::new(ShimSceneBridge::open(explicit_source)?),
            ),
            SceneBackendMode::Rust => ActiveRuntimeSceneLvglRenderer::Rust(
                RuntimeSceneLvglRenderer::new(RustSceneBridge::open(explicit_source)?),
            ),
        };
        Ok(Self { renderer })
    }

    pub fn render_screen_model(
        &mut self,
        framebuffer: &mut Framebuffer,
        model: &ScreenModel,
    ) -> Result<()> {
        self.renderer.render_screen_model(framebuffer, model)
    }
}

#[cfg(feature = "native-lvgl")]
trait RuntimeSceneBridge: SceneBridge {
    fn display_needs_reset(&self, framebuffer: &Framebuffer) -> bool;
    fn ensure_display_registered(&mut self, framebuffer: &Framebuffer) -> Result<()>;
    fn render_frame(&mut self, framebuffer: &mut Framebuffer) -> Result<()>;
}

#[cfg(feature = "native-lvgl")]
impl RuntimeSceneBridge for ShimSceneBridge {
    fn display_needs_reset(&self, framebuffer: &Framebuffer) -> bool {
        ShimSceneBridge::display_needs_reset(self, framebuffer)
    }

    fn ensure_display_registered(&mut self, framebuffer: &Framebuffer) -> Result<()> {
        ShimSceneBridge::ensure_display_registered(self, framebuffer)
    }

    fn render_frame(&mut self, framebuffer: &mut Framebuffer) -> Result<()> {
        ShimSceneBridge::render_frame(self, framebuffer)
    }
}

#[cfg(feature = "native-lvgl")]
impl RuntimeSceneBridge for RustSceneBridge<NativeLvglFacade> {
    fn display_needs_reset(&self, framebuffer: &Framebuffer) -> bool {
        RustSceneBridge::<NativeLvglFacade>::display_needs_reset(self, framebuffer)
    }

    fn ensure_display_registered(&mut self, framebuffer: &Framebuffer) -> Result<()> {
        RustSceneBridge::<NativeLvglFacade>::ensure_display_registered(self, framebuffer)
    }

    fn render_frame(&mut self, framebuffer: &mut Framebuffer) -> Result<()> {
        RustSceneBridge::<NativeLvglFacade>::render_frame(self, framebuffer)
    }
}

#[cfg(feature = "native-lvgl")]
enum ActiveRuntimeSceneLvglRenderer {
    Shim(RuntimeSceneLvglRenderer<ShimSceneBridge>),
    Rust(RuntimeSceneLvglRenderer<RustSceneBridge<NativeLvglFacade>>),
}

#[cfg(feature = "native-lvgl")]
impl ActiveRuntimeSceneLvglRenderer {
    fn render_screen_model(
        &mut self,
        framebuffer: &mut Framebuffer,
        model: &ScreenModel,
    ) -> Result<()> {
        match self {
            Self::Shim(renderer) => renderer.render_screen_model(framebuffer, model),
            Self::Rust(renderer) => renderer.render_screen_model(framebuffer, model),
        }
    }
}

#[cfg(feature = "native-lvgl")]
struct RuntimeSceneLvglRenderer<B> {
    renderer: NativeSceneRenderer<B>,
}

#[cfg(feature = "native-lvgl")]
impl<B> RuntimeSceneLvglRenderer<B>
where
    B: RuntimeSceneBridge,
{
    fn new(bridge: B) -> Self {
        Self {
            renderer: NativeSceneRenderer::new(bridge),
        }
    }

    fn render_screen_model(
        &mut self,
        framebuffer: &mut Framebuffer,
        model: &ScreenModel,
    ) -> Result<()> {
        if self.renderer.bridge().display_needs_reset(framebuffer) {
            self.renderer.clear()?;
        }
        self.renderer
            .bridge_mut()
            .ensure_display_registered(framebuffer)?;
        self.renderer.render(model)?;
        self.renderer.bridge_mut().render_frame(framebuffer)
    }
}

#[cfg(not(feature = "native-lvgl"))]
impl LvglRenderer {
    pub fn open(_explicit_source: Option<&Path>) -> Result<Self> {
        bail!("native-lvgl feature is disabled for this build")
    }

    pub fn render_screen_model(
        &mut self,
        _framebuffer: &mut Framebuffer,
        _model: &ScreenModel,
    ) -> Result<()> {
        bail!("native-lvgl feature is disabled for this build")
    }
}

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
