use std::path::Path;

use anyhow::{bail, Result};

use crate::framebuffer::Framebuffer;
use crate::lvgl::{LvglFacade, LvglRenderer as SemanticLvglRenderer};
#[cfg(feature = "native-lvgl")]
use crate::lvgl::{
    NativeLvglFacade, NativeSceneRenderer, RustSceneBridge, SceneBridge, ShimSceneBridge,
};
use crate::screens::ScreenModel;

#[cfg(any(test, feature = "native-lvgl"))]
const SCENE_BACKEND_ENV: &str = "YOYOPOD_LVGL_SCENE_BACKEND";

#[cfg(any(test, feature = "native-lvgl"))]
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum SceneBackendMode {
    Shim,
    Rust,
}

#[cfg(any(test, feature = "native-lvgl"))]
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

    #[cfg(test)]
    fn from_backend_for_test(backend: B) -> Self {
        Self {
            renderer: SemanticLvglRenderer::new(backend),
        }
    }

    #[cfg(test)]
    fn backend_for_test(&self) -> &B {
        self.renderer.facade()
    }

    #[cfg(test)]
    fn backend_mut_for_test(&mut self) -> &mut B {
        self.renderer.facade_mut()
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

#[cfg(test)]
mod tests {
    use anyhow::Result;

    use super::RuntimeLvglRenderer;
    use crate::framebuffer::Framebuffer;
    use crate::lvgl::{LvglFacade, WidgetId};
    use crate::screens::{ChromeModel, HubCardModel, HubViewModel, ScreenModel, StatusBarModel};

    #[test]
    fn scene_backend_mode_parser_defaults_to_rust_and_accepts_shim_fallback() -> Result<()> {
        assert_eq!(
            super::scene_backend_mode_from_value(None)?,
            super::SceneBackendMode::Rust
        );
        assert_eq!(
            super::scene_backend_mode_from_value(Some("shim"))?,
            super::SceneBackendMode::Shim
        );
        assert_eq!(
            super::scene_backend_mode_from_value(Some("c"))?,
            super::SceneBackendMode::Shim
        );
        assert_eq!(
            super::scene_backend_mode_from_value(Some("rust"))?,
            super::SceneBackendMode::Rust
        );
        assert_eq!(
            super::scene_backend_mode_from_value(Some("native"))?,
            super::SceneBackendMode::Rust
        );

        let error = super::scene_backend_mode_from_value(Some("python"))
            .expect_err("unknown LVGL scene backend should be rejected");
        assert!(error.to_string().contains("YOYOPOD_LVGL_SCENE_BACKEND"));

        Ok(())
    }

    #[derive(Default)]
    struct FakeBackend {
        next_id: u64,
        reset_on_next_prepare: bool,
        fail_render: bool,
        events: Vec<String>,
    }

    impl FakeBackend {
        fn mark_display_reset(&mut self) {
            self.reset_on_next_prepare = true;
        }
    }

    impl super::RuntimeLvglBackend for FakeBackend {
        fn display_needs_reset(&self, _framebuffer: &Framebuffer) -> bool {
            self.reset_on_next_prepare
        }

        fn ensure_display_registered(&mut self, _framebuffer: &Framebuffer) -> Result<()> {
            self.reset_on_next_prepare = false;
            Ok(())
        }

        fn render_frame(&mut self, _framebuffer: &mut Framebuffer) -> Result<()> {
            if self.fail_render {
                anyhow::bail!("forced render failure");
            }
            Ok(())
        }
    }

    impl LvglFacade for FakeBackend {
        fn create_root(&mut self) -> Result<WidgetId> {
            let id = WidgetId::new(self.next_id);
            self.next_id += 1;
            self.events.push(format!("create_root:{}", id.raw()));
            Ok(id)
        }

        fn create_container(&mut self, _parent: WidgetId, role: &'static str) -> Result<WidgetId> {
            let id = WidgetId::new(self.next_id);
            self.next_id += 1;
            self.events
                .push(format!("create_container:{role}:{}", id.raw()));
            Ok(id)
        }

        fn create_label(&mut self, _parent: WidgetId, role: &'static str) -> Result<WidgetId> {
            let id = WidgetId::new(self.next_id);
            self.next_id += 1;
            self.events
                .push(format!("create_label:{role}:{}", id.raw()));
            Ok(id)
        }

        fn set_text(&mut self, widget: WidgetId, text: &str) -> Result<()> {
            self.events
                .push(format!("set_text:{}:{text}", widget.raw()));
            Ok(())
        }

        fn set_selected(&mut self, _widget: WidgetId, _selected: bool) -> Result<()> {
            Ok(())
        }

        fn set_icon(&mut self, _widget: WidgetId, _icon_key: &str) -> Result<()> {
            Ok(())
        }

        fn set_progress(&mut self, _widget: WidgetId, _value: i32) -> Result<()> {
            Ok(())
        }

        fn set_visible(&mut self, _widget: WidgetId, _visible: bool) -> Result<()> {
            Ok(())
        }

        fn set_accent(&mut self, _widget: WidgetId, _rgb: u32) -> Result<()> {
            Ok(())
        }

        fn destroy(&mut self, widget: WidgetId) -> Result<()> {
            self.events.push(format!("destroy:{}", widget.raw()));
            Ok(())
        }
    }

    #[test]
    fn runtime_wrapper_rebuilds_semantic_state_after_display_reset() -> Result<()> {
        let backend = FakeBackend::default();
        let mut renderer = RuntimeLvglRenderer::from_backend_for_test(backend);
        let mut framebuffer = Framebuffer::new(240, 280);

        renderer.render_screen_model(&mut framebuffer, &hub_screen_model("Listen"))?;
        renderer.backend_mut_for_test().mark_display_reset();
        renderer.render_screen_model(&mut framebuffer, &hub_screen_model("Talk"))?;

        let normalized_events: Vec<String> = renderer
            .backend_for_test()
            .events
            .iter()
            .map(|event| {
                if event.starts_with("set_text:21:") {
                    "set_text:21:<time>".to_string()
                } else if event.starts_with("set_text:49:") {
                    "set_text:49:<time>".to_string()
                } else {
                    event.clone()
                }
            })
            .collect();

        assert_eq!(
            normalized_events,
            vec![
                "create_root:0",
                "create_container:hub_icon_glow:1",
                "create_container:hub_card_panel:2",
                "create_label:hub_icon:3",
                "create_label:hub_title:4",
                "create_label:hub_subtitle:5",
                "create_container:hub_dot:6",
                "create_container:hub_dot:7",
                "create_container:hub_dot:8",
                "create_container:hub_dot:9",
                "create_container:status_bar:10",
                "create_container:status_signal_bar_0:11",
                "create_container:status_signal_bar_1:12",
                "create_container:status_signal_bar_2:13",
                "create_container:status_signal_bar_3:14",
                "create_label:status_wifi:15",
                "create_container:status_gps_ring:16",
                "create_container:status_gps_center:17",
                "create_container:status_gps_tail:18",
                "create_container:status_voip_dot_left:19",
                "create_container:status_voip_dot_after_gps:20",
                "create_label:status_time:21",
                "create_container:status_battery_outline:22",
                "create_container:status_battery_fill:23",
                "create_container:status_battery_tip:24",
                "create_label:status_battery_label:25",
                "set_text:15:\u{f1eb}",
                "set_text:21:<time>",
                "set_text:25:80%",
                "create_container:footer_bar:26",
                "create_label:hub_footer:27",
                "set_text:27:Footer",
                "set_text:4:Listen",
                "set_text:5:Subtitle",
                "destroy:0",
                "create_root:28",
                "create_container:hub_icon_glow:29",
                "create_container:hub_card_panel:30",
                "create_label:hub_icon:31",
                "create_label:hub_title:32",
                "create_label:hub_subtitle:33",
                "create_container:hub_dot:34",
                "create_container:hub_dot:35",
                "create_container:hub_dot:36",
                "create_container:hub_dot:37",
                "create_container:status_bar:38",
                "create_container:status_signal_bar_0:39",
                "create_container:status_signal_bar_1:40",
                "create_container:status_signal_bar_2:41",
                "create_container:status_signal_bar_3:42",
                "create_label:status_wifi:43",
                "create_container:status_gps_ring:44",
                "create_container:status_gps_center:45",
                "create_container:status_gps_tail:46",
                "create_container:status_voip_dot_left:47",
                "create_container:status_voip_dot_after_gps:48",
                "create_label:status_time:49",
                "create_container:status_battery_outline:50",
                "create_container:status_battery_fill:51",
                "create_container:status_battery_tip:52",
                "create_label:status_battery_label:53",
                "set_text:43:\u{f1eb}",
                "set_text:49:<time>",
                "set_text:53:80%",
                "create_container:footer_bar:54",
                "create_label:hub_footer:55",
                "set_text:55:Footer",
                "set_text:32:Talk",
                "set_text:33:Subtitle",
            ]
        );

        Ok(())
    }

    #[test]
    fn runtime_wrapper_propagates_backend_render_errors() -> Result<()> {
        let mut renderer = RuntimeLvglRenderer::from_backend_for_test(FakeBackend {
            fail_render: true,
            ..FakeBackend::default()
        });
        let mut framebuffer = Framebuffer::new(240, 280);

        let error = renderer
            .render_screen_model(&mut framebuffer, &hub_screen_model("Listen"))
            .expect_err("backend render failure should propagate");

        assert!(error.to_string().contains("forced render failure"));
        Ok(())
    }

    fn hub_screen_model(title: &str) -> ScreenModel {
        ScreenModel::Hub(HubViewModel {
            chrome: ChromeModel {
                status: StatusBarModel {
                    network_connected: true,
                    network_enabled: true,
                    connection_type: "4g".to_string(),
                    signal_strength: 4,
                    gps_has_fix: true,
                    battery_percent: 80,
                    charging: false,
                    power_available: true,
                    voip_state: 1,
                },
                footer: "Footer".to_string(),
            },
            cards: vec![HubCardModel {
                key: "listen".to_string(),
                title: title.to_string(),
                subtitle: "Subtitle".to_string(),
                accent: 0x00FF88,
            }],
            selected_index: 0,
        })
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
