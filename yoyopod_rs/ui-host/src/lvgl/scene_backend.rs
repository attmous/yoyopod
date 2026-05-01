#[cfg(feature = "native-lvgl")]
use std::path::Path;

use anyhow::{bail, Result};

use crate::runtime::UiScreen;
use crate::screens::{AskViewModel, ChromeModel, ListScreenModel, ScreenModel, StatusBarModel};

use super::{
    AskController, CallController, HubController, ListenController, LvglFacade, NativeSceneKey,
    NowPlayingController, PlaylistController, PowerController, ScreenController,
    TalkActionsController, TalkController,
};

pub trait SceneBridge {
    fn build_scene(&mut self, scene: NativeSceneKey) -> Result<()>;
    fn sync_status(&mut self, status: &StatusBarModel) -> Result<()>;
    fn sync_scene(&mut self, model: &ScreenModel) -> Result<()>;
    fn destroy_scene(&mut self, scene: NativeSceneKey);
    fn clear_screen(&mut self) -> Result<()>;
}

pub struct NativeSceneRenderer<B> {
    bridge: B,
    active_scene: Option<NativeSceneKey>,
    active_screen: Option<UiScreen>,
}

impl<B> NativeSceneRenderer<B>
where
    B: SceneBridge,
{
    pub fn new(bridge: B) -> Self {
        Self {
            bridge,
            active_scene: None,
            active_screen: None,
        }
    }

    pub fn render(&mut self, model: &ScreenModel) -> Result<()> {
        let screen = model.screen();
        let scene = NativeSceneKey::for_screen(screen);

        if self.active_scene != Some(scene) {
            if let Some(active_scene) = self.active_scene.take() {
                self.bridge.destroy_scene(active_scene);
            }
            self.bridge.build_scene(scene)?;
            self.active_scene = Some(scene);
        }

        self.bridge.sync_status(chrome(model).status())?;
        self.bridge.sync_scene(model)?;
        self.active_screen = Some(screen);
        Ok(())
    }

    pub fn clear(&mut self) -> Result<()> {
        if let Some(active_scene) = self.active_scene.take() {
            self.bridge.destroy_scene(active_scene);
        }
        self.bridge.clear_screen()?;
        self.active_screen = None;
        Ok(())
    }

    pub fn active_scene(&self) -> Option<NativeSceneKey> {
        self.active_scene
    }

    pub fn active_screen(&self) -> Option<UiScreen> {
        self.active_screen
    }

    pub fn bridge(&self) -> &B {
        &self.bridge
    }

    pub fn bridge_mut(&mut self) -> &mut B {
        &mut self.bridge
    }
}

pub struct RustSceneBridge<F> {
    facade: F,
    controller: Option<Box<dyn ScreenController>>,
    active_scene: Option<NativeSceneKey>,
    last_status: Option<StatusBarModel>,
}

impl<F> RustSceneBridge<F>
where
    F: LvglFacade,
{
    pub fn new(facade: F) -> Self {
        Self {
            facade,
            controller: None,
            active_scene: None,
            last_status: None,
        }
    }

    pub fn active_scene(&self) -> Option<NativeSceneKey> {
        self.active_scene
    }

    pub fn last_status(&self) -> Option<&StatusBarModel> {
        self.last_status.as_ref()
    }

    pub fn facade(&self) -> &F {
        &self.facade
    }

    pub fn facade_mut(&mut self) -> &mut F {
        &mut self.facade
    }
}

impl<F> SceneBridge for RustSceneBridge<F>
where
    F: LvglFacade,
{
    fn build_scene(&mut self, scene: NativeSceneKey) -> Result<()> {
        if self.active_scene == Some(scene) {
            return Ok(());
        }
        if self.active_scene.is_some() {
            if let Some(controller) = self.controller.as_mut() {
                let _ = controller.teardown(&mut self.facade);
            }
        }
        self.controller = Some(controller_for_native_scene(scene));
        self.active_scene = Some(scene);
        Ok(())
    }

    fn sync_status(&mut self, status: &StatusBarModel) -> Result<()> {
        self.last_status = Some(status.clone());
        Ok(())
    }

    fn sync_scene(&mut self, model: &ScreenModel) -> Result<()> {
        let expected_scene = NativeSceneKey::for_screen(model.screen());
        let Some(active_scene) = self.active_scene else {
            bail!(
                "{} scene must be built before sync",
                expected_scene.as_str()
            );
        };
        if active_scene != expected_scene {
            bail!(
                "Rust LVGL scene bridge built {} but received {} model",
                active_scene.as_str(),
                model.screen().as_str()
            );
        }
        let model = rust_owned_scene_model(model, active_scene);
        let controller = self
            .controller
            .as_mut()
            .ok_or_else(|| anyhow::anyhow!("Rust LVGL scene bridge has no active controller"))?;
        controller.sync(&mut self.facade, &model)
    }

    fn destroy_scene(&mut self, scene: NativeSceneKey) {
        if self.active_scene == Some(scene) {
            if let Some(controller) = self.controller.as_mut() {
                let _ = controller.teardown(&mut self.facade);
            }
            self.controller = None;
            self.active_scene = None;
        }
    }

    fn clear_screen(&mut self) -> Result<()> {
        if let Some(controller) = self.controller.as_mut() {
            controller.teardown(&mut self.facade)?;
        }
        self.controller = None;
        self.active_scene = None;
        Ok(())
    }
}

fn controller_for_native_scene(scene: NativeSceneKey) -> Box<dyn ScreenController> {
    match scene {
        NativeSceneKey::Hub => Box::new(HubController::default()),
        NativeSceneKey::Listen => Box::new(ListenController::default()),
        NativeSceneKey::Playlist => Box::new(PlaylistController::default()),
        NativeSceneKey::NowPlaying => Box::new(NowPlayingController::default()),
        NativeSceneKey::Talk => Box::new(TalkController::default()),
        NativeSceneKey::TalkActions => Box::new(TalkActionsController::default()),
        NativeSceneKey::IncomingCall | NativeSceneKey::OutgoingCall | NativeSceneKey::InCall => {
            Box::new(CallController::default())
        }
        NativeSceneKey::Ask => Box::new(AskController::default()),
        NativeSceneKey::Power => Box::new(PowerController::default()),
        NativeSceneKey::Overlay => Box::new(AskController::default()),
    }
}

#[cfg(feature = "native-lvgl")]
impl RustSceneBridge<super::NativeLvglFacade> {
    pub fn open(explicit_source: Option<&Path>) -> Result<Self> {
        Ok(Self::new(super::NativeLvglFacade::open(explicit_source)?))
    }

    pub fn display_needs_reset(&self, framebuffer: &crate::framebuffer::Framebuffer) -> bool {
        self.facade().display_needs_reset(framebuffer)
    }

    pub fn ensure_display_registered(
        &mut self,
        framebuffer: &crate::framebuffer::Framebuffer,
    ) -> Result<()> {
        self.facade_mut().ensure_display_registered(framebuffer)
    }

    pub fn render_frame(
        &mut self,
        framebuffer: &mut crate::framebuffer::Framebuffer,
    ) -> Result<()> {
        self.facade_mut().render_frame(framebuffer)
    }
}

const NATIVE_LIST_VISIBLE_ROWS: usize = 4;

#[derive(Debug, Clone, Copy)]
enum NativeListSelection {
    Wrap,
    Clamp,
}

fn rust_owned_scene_model(model: &ScreenModel, scene: NativeSceneKey) -> ScreenModel {
    match (scene, model) {
        (NativeSceneKey::Listen, ScreenModel::Listen(list)) => {
            ScreenModel::Listen(capped_list_model(list, NativeListSelection::Wrap))
        }
        (NativeSceneKey::Playlist, ScreenModel::Playlists(list)) => {
            ScreenModel::Playlists(capped_list_model(list, NativeListSelection::Clamp))
        }
        (NativeSceneKey::Playlist, ScreenModel::RecentTracks(list)) => {
            ScreenModel::RecentTracks(capped_list_model(list, NativeListSelection::Clamp))
        }
        (NativeSceneKey::Playlist, ScreenModel::Contacts(list)) => {
            ScreenModel::Contacts(capped_list_model(list, NativeListSelection::Clamp))
        }
        (NativeSceneKey::Playlist, ScreenModel::CallHistory(list)) => {
            ScreenModel::CallHistory(capped_list_model(list, NativeListSelection::Clamp))
        }
        (NativeSceneKey::Overlay, ScreenModel::Loading(overlay))
        | (NativeSceneKey::Overlay, ScreenModel::Error(overlay)) => {
            ScreenModel::Ask(AskViewModel {
                chrome: overlay.chrome.clone(),
                title: overlay.title.clone(),
                subtitle: overlay.subtitle.clone(),
                icon_key: "ask".to_string(),
            })
        }
        _ => model.clone(),
    }
}

fn capped_list_model(model: &ListScreenModel, selection: NativeListSelection) -> ListScreenModel {
    let mut rows = model
        .rows
        .iter()
        .take(NATIVE_LIST_VISIBLE_ROWS)
        .cloned()
        .collect::<Vec<_>>();

    if !rows.is_empty() {
        let selected_index = model.rows.iter().position(|row| row.selected).unwrap_or(0);
        let visible_index = match selection {
            NativeListSelection::Wrap => selected_index % rows.len(),
            NativeListSelection::Clamp => selected_index.min(rows.len() - 1),
        };
        for row in &mut rows {
            row.selected = false;
        }
        rows[visible_index].selected = true;
    }

    ListScreenModel {
        chrome: model.chrome.clone(),
        title: model.title.clone(),
        subtitle: model.subtitle.clone(),
        rows,
    }
}

trait ChromeRef {
    fn status(&self) -> &StatusBarModel;
}

impl ChromeRef for ChromeModel {
    fn status(&self) -> &StatusBarModel {
        &self.status
    }
}

fn chrome(model: &ScreenModel) -> &ChromeModel {
    match model {
        ScreenModel::Hub(model) => &model.chrome,
        ScreenModel::Listen(model)
        | ScreenModel::Playlists(model)
        | ScreenModel::RecentTracks(model)
        | ScreenModel::Talk(model)
        | ScreenModel::Contacts(model)
        | ScreenModel::CallHistory(model) => &model.chrome,
        ScreenModel::NowPlaying(model) => &model.chrome,
        ScreenModel::Ask(model) | ScreenModel::VoiceNote(model) => &model.chrome,
        ScreenModel::IncomingCall(model)
        | ScreenModel::OutgoingCall(model)
        | ScreenModel::InCall(model) => &model.chrome,
        ScreenModel::Power(model) => &model.chrome,
        ScreenModel::Loading(model) | ScreenModel::Error(model) => &model.chrome,
    }
}

#[cfg(feature = "native-lvgl")]
fn validate_explicit_source_dir(explicit_source: Option<&Path>) -> Result<()> {
    if let Some(source) = explicit_source {
        if source.exists() {
            return Ok(());
        }
        anyhow::bail!("LVGL source directory not found at {}", source.display());
    }

    Ok(())
}

#[cfg(feature = "native-lvgl")]
mod shim {
    use std::ffi::{CStr, CString};
    use std::os::raw::c_void;
    use std::path::Path;
    use std::ptr;
    use std::time::Instant;

    use anyhow::{anyhow, Context, Result};

    use crate::framebuffer::Framebuffer;
    use crate::lvgl::sys;
    use crate::screens::{
        AskViewModel, CallViewModel, HubViewModel, ListRowModel, ListScreenModel,
        NowPlayingViewModel, OverlayViewModel, PowerViewModel, ScreenModel, StatusBarModel,
    };

    use super::{validate_explicit_source_dir, NativeSceneKey, SceneBridge};

    const DRAW_BUFFER_ROWS: usize = 40;
    const LISTEN_ACCENT: u32 = 0x00FF88;
    const TALK_ACCENT: u32 = 0x00D4FF;
    const ASK_ACCENT: u32 = 0xFFD000;
    const SETUP_ACCENT: u32 = 0x9CA3AF;

    #[derive(Default)]
    struct FlushTarget {
        framebuffer: *mut Framebuffer,
    }

    pub struct ShimSceneBridge {
        display_size: Option<(usize, usize)>,
        flush_target: FlushTarget,
        last_tick: Instant,
        initialized: bool,
    }

    impl ShimSceneBridge {
        pub fn open(explicit_source: Option<&Path>) -> Result<Self> {
            validate_explicit_source_dir(explicit_source)?;
            check(
                unsafe { sys::yoyopod_lvgl_init() },
                "initializing YoYoPod LVGL shim",
            )?;
            Ok(Self {
                display_size: None,
                flush_target: FlushTarget::default(),
                last_tick: Instant::now(),
                initialized: true,
            })
        }

        pub fn display_needs_reset(&self, framebuffer: &Framebuffer) -> bool {
            self.display_size.is_some()
                && self.display_size != Some((framebuffer.width(), framebuffer.height()))
        }

        pub fn ensure_display_registered(&mut self, framebuffer: &Framebuffer) -> Result<()> {
            let size = (framebuffer.width(), framebuffer.height());
            if self.display_size == Some(size) {
                return Ok(());
            }
            if self.display_size.is_some() {
                self.reinitialize()?;
            }

            let buffer_pixel_count = framebuffer.width() * DRAW_BUFFER_ROWS;
            check(
                unsafe {
                    sys::yoyopod_lvgl_register_display(
                        framebuffer.width() as i32,
                        framebuffer.height() as i32,
                        buffer_pixel_count as u32,
                        Some(shim_flush_callback),
                        &mut self.flush_target as *mut FlushTarget as *mut c_void,
                    )
                },
                "registering YoYoPod LVGL shim display",
            )?;
            check(
                unsafe { sys::yoyopod_lvgl_register_input() },
                "registering YoYoPod LVGL shim input",
            )?;
            self.display_size = Some(size);
            Ok(())
        }

        pub fn render_frame(&mut self, framebuffer: &mut Framebuffer) -> Result<()> {
            self.flush_target.framebuffer = framebuffer as *mut Framebuffer;
            let elapsed_ms = self
                .last_tick
                .elapsed()
                .as_millis()
                .min(u128::from(u32::MAX)) as u32;
            self.last_tick = Instant::now();
            unsafe {
                sys::yoyopod_lvgl_tick_inc(elapsed_ms.max(1));
                sys::yoyopod_lvgl_force_refresh();
                let _ = sys::yoyopod_lvgl_timer_handler();
            }
            Ok(())
        }

        fn reinitialize(&mut self) -> Result<()> {
            if self.initialized {
                unsafe {
                    sys::yoyopod_lvgl_shutdown();
                }
            }
            self.display_size = None;
            check(
                unsafe { sys::yoyopod_lvgl_init() },
                "reinitializing YoYoPod LVGL shim",
            )?;
            self.initialized = true;
            Ok(())
        }
    }

    impl SceneBridge for ShimSceneBridge {
        fn build_scene(&mut self, scene: NativeSceneKey) -> Result<()> {
            let result = unsafe {
                match scene {
                    NativeSceneKey::Hub => sys::yoyopod_lvgl_hub_build(),
                    NativeSceneKey::Listen => sys::yoyopod_lvgl_listen_build(),
                    NativeSceneKey::Playlist => sys::yoyopod_lvgl_playlist_build(),
                    NativeSceneKey::NowPlaying => sys::yoyopod_lvgl_now_playing_build(),
                    NativeSceneKey::Talk => sys::yoyopod_lvgl_talk_build(),
                    NativeSceneKey::TalkActions => sys::yoyopod_lvgl_talk_actions_build(),
                    NativeSceneKey::IncomingCall => sys::yoyopod_lvgl_incoming_call_build(),
                    NativeSceneKey::OutgoingCall => sys::yoyopod_lvgl_outgoing_call_build(),
                    NativeSceneKey::InCall => sys::yoyopod_lvgl_in_call_build(),
                    NativeSceneKey::Ask | NativeSceneKey::Overlay => sys::yoyopod_lvgl_ask_build(),
                    NativeSceneKey::Power => sys::yoyopod_lvgl_power_build(),
                }
            };
            check(result, format!("building {} LVGL scene", scene.as_str()))
        }

        fn sync_status(&mut self, status: &StatusBarModel) -> Result<()> {
            check(
                unsafe {
                    sys::yoyopod_lvgl_set_status_bar_state(
                        bool_i32(status.network_enabled),
                        bool_i32(status.network_connected),
                        bool_i32(status.network_connected),
                        status.signal_strength,
                        0,
                    )
                },
                "syncing YoYoPod LVGL status bar",
            )
        }

        fn sync_scene(&mut self, model: &ScreenModel) -> Result<()> {
            match model {
                ScreenModel::Hub(model) => sync_hub(model),
                ScreenModel::Listen(model) => sync_listen(model),
                ScreenModel::Playlists(model)
                | ScreenModel::RecentTracks(model)
                | ScreenModel::Contacts(model)
                | ScreenModel::CallHistory(model) => sync_playlist(model),
                ScreenModel::NowPlaying(model) => sync_now_playing(model),
                ScreenModel::Talk(model) => sync_talk(model),
                ScreenModel::VoiceNote(model) => sync_talk_actions(model),
                ScreenModel::IncomingCall(model) => sync_incoming_call(model),
                ScreenModel::OutgoingCall(model) => sync_outgoing_call(model),
                ScreenModel::InCall(model) => sync_in_call(model),
                ScreenModel::Ask(model) => sync_ask(model),
                ScreenModel::Power(model) => sync_power(model),
                ScreenModel::Loading(model) | ScreenModel::Error(model) => sync_overlay(model),
            }
        }

        fn destroy_scene(&mut self, scene: NativeSceneKey) {
            unsafe {
                match scene {
                    NativeSceneKey::Hub => sys::yoyopod_lvgl_hub_destroy(),
                    NativeSceneKey::Listen => sys::yoyopod_lvgl_listen_destroy(),
                    NativeSceneKey::Playlist => sys::yoyopod_lvgl_playlist_destroy(),
                    NativeSceneKey::NowPlaying => sys::yoyopod_lvgl_now_playing_destroy(),
                    NativeSceneKey::Talk => sys::yoyopod_lvgl_talk_destroy(),
                    NativeSceneKey::TalkActions => sys::yoyopod_lvgl_talk_actions_destroy(),
                    NativeSceneKey::IncomingCall => sys::yoyopod_lvgl_incoming_call_destroy(),
                    NativeSceneKey::OutgoingCall => sys::yoyopod_lvgl_outgoing_call_destroy(),
                    NativeSceneKey::InCall => sys::yoyopod_lvgl_in_call_destroy(),
                    NativeSceneKey::Ask | NativeSceneKey::Overlay => {
                        sys::yoyopod_lvgl_ask_destroy()
                    }
                    NativeSceneKey::Power => sys::yoyopod_lvgl_power_destroy(),
                }
            }
        }

        fn clear_screen(&mut self) -> Result<()> {
            unsafe {
                sys::yoyopod_lvgl_clear_screen();
            }
            Ok(())
        }
    }

    impl Drop for ShimSceneBridge {
        fn drop(&mut self) {
            if self.initialized {
                unsafe {
                    sys::yoyopod_lvgl_shutdown();
                }
                self.initialized = false;
            }
        }
    }

    fn sync_hub(model: &HubViewModel) -> Result<()> {
        let selected = model
            .cards
            .get(model.selected_index % model.cards.len().max(1));
        let fallback_title = "Listen";
        let icon_key = selected.map(|card| card.key.as_str()).unwrap_or("listen");
        let title = selected
            .map(|card| card.title.as_str())
            .unwrap_or(fallback_title);
        let subtitle = selected.map(|card| card.subtitle.as_str()).unwrap_or("");
        let accent = selected.map(|card| card.accent).unwrap_or(LISTEN_ACCENT);
        let icon_key = cstring(icon_key)?;
        let title = cstring(title)?;
        let subtitle = cstring(subtitle)?;
        let footer = cstring(&model.chrome.footer)?;

        check(
            unsafe {
                sys::yoyopod_lvgl_hub_sync(
                    icon_key.as_ptr(),
                    title.as_ptr(),
                    subtitle.as_ptr(),
                    footer.as_ptr(),
                    ptr::null(),
                    accent,
                    model.selected_index as i32,
                    model.cards.len().max(1) as i32,
                    model.chrome.status.voip_state,
                    model.chrome.status.battery_percent,
                    bool_i32(model.chrome.status.charging),
                    1,
                )
            },
            "syncing hub LVGL scene",
        )
    }

    fn sync_talk(model: &ListScreenModel) -> Result<()> {
        let selected_index = selected_index(&model.rows);
        let selected = model.rows.get(selected_index);
        let title = selected
            .map(|row| row.title.as_str())
            .unwrap_or(model.title.as_str());
        let icon_key = selected.map(|row| row.icon_key.as_str()).unwrap_or("talk");
        let title = cstring(title)?;
        let icon_key = cstring(icon_key)?;
        let footer = cstring(&model.chrome.footer)?;

        check(
            unsafe {
                sys::yoyopod_lvgl_talk_sync(
                    title.as_ptr(),
                    icon_key.as_ptr(),
                    0,
                    footer.as_ptr(),
                    selected_index as i32,
                    model.rows.len().max(1) as i32,
                    model.chrome.status.voip_state,
                    model.chrome.status.battery_percent,
                    bool_i32(model.chrome.status.charging),
                    1,
                    TALK_ACCENT,
                )
            },
            "syncing talk LVGL scene",
        )
    }

    fn sync_talk_actions(model: &AskViewModel) -> Result<()> {
        let contact_name = cstring(&model.title)?;
        let title_text = cstring(&model.subtitle)?;
        let footer = cstring(&model.chrome.footer)?;
        let icon = cstring(&model.icon_key)?;
        let empty = cstring("")?;

        check(
            unsafe {
                sys::yoyopod_lvgl_talk_actions_sync(
                    contact_name.as_ptr(),
                    title_text.as_ptr(),
                    ptr::null(),
                    0,
                    footer.as_ptr(),
                    icon.as_ptr(),
                    0,
                    empty.as_ptr(),
                    0,
                    empty.as_ptr(),
                    0,
                    1,
                    0,
                    1,
                    2,
                    model.chrome.status.voip_state,
                    model.chrome.status.battery_percent,
                    bool_i32(model.chrome.status.charging),
                    1,
                    TALK_ACCENT,
                )
            },
            "syncing talk actions LVGL scene",
        )
    }

    fn sync_listen(model: &ListScreenModel) -> Result<()> {
        let rows = first_rows(&model.rows, 4);
        let items = fixed_cstrings(rows.iter().map(|row| row.title.as_str()), 4)?;
        let subtitles = fixed_cstrings(rows.iter().map(|row| row.subtitle.as_str()), 4)?;
        let icons = fixed_cstrings(rows.iter().map(|row| row.icon_key.as_str()), 4)?;
        let footer = cstring(&model.chrome.footer)?;
        let empty_title = cstring("No music items")?;
        let empty_subtitle = cstring("Add local music actions to fill this page.")?;

        check(
            unsafe {
                sys::yoyopod_lvgl_listen_sync(
                    ptr::null(),
                    footer.as_ptr(),
                    items[0].as_ptr(),
                    items[1].as_ptr(),
                    items[2].as_ptr(),
                    items[3].as_ptr(),
                    subtitles[0].as_ptr(),
                    subtitles[1].as_ptr(),
                    subtitles[2].as_ptr(),
                    subtitles[3].as_ptr(),
                    icons[0].as_ptr(),
                    icons[1].as_ptr(),
                    icons[2].as_ptr(),
                    icons[3].as_ptr(),
                    model.rows.len() as i32,
                    selected_index(&model.rows) as i32,
                    model.chrome.status.voip_state,
                    model.chrome.status.battery_percent,
                    bool_i32(model.chrome.status.charging),
                    1,
                    LISTEN_ACCENT,
                    empty_title.as_ptr(),
                    empty_subtitle.as_ptr(),
                )
            },
            "syncing listen LVGL scene",
        )
    }

    fn sync_playlist(model: &ListScreenModel) -> Result<()> {
        let rows = first_rows(&model.rows, 4);
        let items = fixed_cstrings(rows.iter().map(|row| row.title.as_str()), 4)?;
        let subtitles = fixed_cstrings(rows.iter().map(|row| row.subtitle.as_str()), 4)?;
        let icons = fixed_cstrings(rows.iter().map(|row| row.icon_key.as_str()), 4)?;
        let badges = fixed_cstrings(std::iter::empty::<&str>(), 4)?;
        let title = cstring(&model.title)?;
        let footer = cstring(&model.chrome.footer)?;
        let empty_title = cstring(&format!("No {}", model.title.to_ascii_lowercase()))?;
        let empty_subtitle = cstring(&model.subtitle)?;
        let empty_icon = cstring("playlist")?;

        check(
            unsafe {
                sys::yoyopod_lvgl_playlist_sync(
                    title.as_ptr(),
                    ptr::null(),
                    ptr::null(),
                    0,
                    footer.as_ptr(),
                    items[0].as_ptr(),
                    items[1].as_ptr(),
                    items[2].as_ptr(),
                    items[3].as_ptr(),
                    subtitles[0].as_ptr(),
                    subtitles[1].as_ptr(),
                    subtitles[2].as_ptr(),
                    subtitles[3].as_ptr(),
                    badges[0].as_ptr(),
                    badges[1].as_ptr(),
                    badges[2].as_ptr(),
                    badges[3].as_ptr(),
                    icons[0].as_ptr(),
                    icons[1].as_ptr(),
                    icons[2].as_ptr(),
                    icons[3].as_ptr(),
                    model.rows.len() as i32,
                    selected_visible_index(&model.rows, 4) as i32,
                    model.chrome.status.voip_state,
                    model.chrome.status.battery_percent,
                    bool_i32(model.chrome.status.charging),
                    1,
                    accent_for_list_title(&model.title),
                    empty_title.as_ptr(),
                    empty_subtitle.as_ptr(),
                    empty_icon.as_ptr(),
                )
            },
            "syncing playlist LVGL scene",
        )
    }

    fn sync_now_playing(model: &NowPlayingViewModel) -> Result<()> {
        let title = cstring(&model.title)?;
        let artist = cstring(&model.artist)?;
        let state = cstring(&model.state_text)?;
        let footer = cstring(&model.chrome.footer)?;

        check(
            unsafe {
                sys::yoyopod_lvgl_now_playing_sync(
                    title.as_ptr(),
                    artist.as_ptr(),
                    state.as_ptr(),
                    footer.as_ptr(),
                    model.progress_permille.clamp(0, 1000),
                    model.chrome.status.voip_state,
                    model.chrome.status.battery_percent,
                    bool_i32(model.chrome.status.charging),
                    1,
                    LISTEN_ACCENT,
                )
            },
            "syncing now playing LVGL scene",
        )
    }

    fn sync_incoming_call(model: &CallViewModel) -> Result<()> {
        let caller = cstring(&model.title)?;
        let address = cstring(&model.subtitle)?;
        let footer = cstring(&model.chrome.footer)?;

        check(
            unsafe {
                sys::yoyopod_lvgl_incoming_call_sync(
                    caller.as_ptr(),
                    address.as_ptr(),
                    footer.as_ptr(),
                    model.chrome.status.voip_state,
                    model.chrome.status.battery_percent,
                    bool_i32(model.chrome.status.charging),
                    1,
                    TALK_ACCENT,
                )
            },
            "syncing incoming call LVGL scene",
        )
    }

    fn sync_outgoing_call(model: &CallViewModel) -> Result<()> {
        let callee = cstring(&model.title)?;
        let address = cstring(&model.subtitle)?;
        let footer = cstring(&model.chrome.footer)?;

        check(
            unsafe {
                sys::yoyopod_lvgl_outgoing_call_sync(
                    callee.as_ptr(),
                    address.as_ptr(),
                    footer.as_ptr(),
                    model.chrome.status.voip_state,
                    model.chrome.status.battery_percent,
                    bool_i32(model.chrome.status.charging),
                    1,
                    TALK_ACCENT,
                )
            },
            "syncing outgoing call LVGL scene",
        )
    }

    fn sync_in_call(model: &CallViewModel) -> Result<()> {
        let caller = cstring(&model.title)?;
        let duration = if model.subtitle.trim().is_empty() {
            cstring("IN CALL")?
        } else if model.subtitle.contains("IN CALL") {
            cstring(&model.subtitle)?
        } else {
            cstring(&format!("IN CALL | {}", model.subtitle))?
        };
        let mute = cstring(if model.muted { "MUTED" } else { "" })?;
        let footer = cstring(&model.chrome.footer)?;

        check(
            unsafe {
                sys::yoyopod_lvgl_in_call_sync(
                    caller.as_ptr(),
                    duration.as_ptr(),
                    mute.as_ptr(),
                    footer.as_ptr(),
                    bool_i32(model.muted),
                    model.chrome.status.voip_state,
                    model.chrome.status.battery_percent,
                    bool_i32(model.chrome.status.charging),
                    1,
                    TALK_ACCENT,
                )
            },
            "syncing in-call LVGL scene",
        )
    }

    fn sync_ask(model: &AskViewModel) -> Result<()> {
        let icon = cstring(&model.icon_key)?;
        let title = cstring(&model.title)?;
        let subtitle = cstring(&model.subtitle)?;
        let footer = cstring(&model.chrome.footer)?;

        check(
            unsafe {
                sys::yoyopod_lvgl_ask_sync(
                    icon.as_ptr(),
                    title.as_ptr(),
                    subtitle.as_ptr(),
                    footer.as_ptr(),
                    model.chrome.status.voip_state,
                    model.chrome.status.battery_percent,
                    bool_i32(model.chrome.status.charging),
                    1,
                    ASK_ACCENT,
                )
            },
            "syncing ask LVGL scene",
        )
    }

    fn sync_power(model: &PowerViewModel) -> Result<()> {
        let rows = first_rows(&model.rows, 5);
        let items = fixed_cstrings(rows.iter().map(|row| row.title.as_str()), 5)?;
        let title = cstring(&model.title)?;
        let icon = cstring("battery")?;
        let footer = cstring(&model.chrome.footer)?;

        check(
            unsafe {
                sys::yoyopod_lvgl_power_sync(
                    title.as_ptr(),
                    ptr::null(),
                    icon.as_ptr(),
                    footer.as_ptr(),
                    items[0].as_ptr(),
                    items[1].as_ptr(),
                    items[2].as_ptr(),
                    items[3].as_ptr(),
                    items[4].as_ptr(),
                    model.rows.len() as i32,
                    selected_visible_index(&model.rows, 5) as i32,
                    model.rows.len().max(1) as i32,
                    model.chrome.status.voip_state,
                    model.chrome.status.battery_percent,
                    bool_i32(model.chrome.status.charging),
                    1,
                    SETUP_ACCENT,
                )
            },
            "syncing power LVGL scene",
        )
    }

    fn sync_overlay(model: &OverlayViewModel) -> Result<()> {
        let overlay = AskViewModel {
            chrome: model.chrome.clone(),
            title: model.title.clone(),
            subtitle: model.subtitle.clone(),
            icon_key: "ask".to_string(),
        };
        sync_ask(&overlay)
    }

    fn first_rows(rows: &[ListRowModel], count: usize) -> Vec<&ListRowModel> {
        rows.iter().take(count).collect()
    }

    fn selected_index(rows: &[ListRowModel]) -> usize {
        rows.iter().position(|row| row.selected).unwrap_or(0)
    }

    fn selected_visible_index(rows: &[ListRowModel], visible_count: usize) -> usize {
        selected_index(rows).min(visible_count.saturating_sub(1))
    }

    fn accent_for_list_title(title: &str) -> u32 {
        match title.to_ascii_lowercase().as_str() {
            "contacts" | "history" | "recents" => TALK_ACCENT,
            _ => LISTEN_ACCENT,
        }
    }

    fn fixed_cstrings<'a, I>(values: I, count: usize) -> Result<Vec<CString>>
    where
        I: IntoIterator<Item = &'a str>,
    {
        let mut result = values
            .into_iter()
            .take(count)
            .map(cstring)
            .collect::<Result<Vec<_>>>()?;
        while result.len() < count {
            result.push(cstring("")?);
        }
        Ok(result)
    }

    fn cstring(value: &str) -> Result<CString> {
        CString::new(value).with_context(|| format!("LVGL text contains NUL byte: {value:?}"))
    }

    fn bool_i32(value: bool) -> i32 {
        if value {
            1
        } else {
            0
        }
    }

    fn check(result: i32, operation: impl AsRef<str>) -> Result<()> {
        if result == 0 {
            return Ok(());
        }
        Err(anyhow!("{} failed: {}", operation.as_ref(), last_error()))
    }

    fn last_error() -> String {
        let raw = unsafe { sys::yoyopod_lvgl_last_error() };
        if raw.is_null() {
            return "unknown LVGL shim error".to_string();
        }
        unsafe { CStr::from_ptr(raw) }
            .to_string_lossy()
            .into_owned()
    }

    unsafe extern "C" fn shim_flush_callback(
        x: i32,
        y: i32,
        width: i32,
        height: i32,
        pixel_data: *const u8,
        byte_length: u32,
        user_data: *mut c_void,
    ) {
        if user_data.is_null() || pixel_data.is_null() || width <= 0 || height <= 0 {
            return;
        }

        let target = unsafe { &mut *(user_data as *mut FlushTarget) };
        if target.framebuffer.is_null() {
            return;
        }

        let pixel_data = unsafe { std::slice::from_raw_parts(pixel_data, byte_length as usize) };
        let framebuffer = unsafe { &mut *target.framebuffer };
        framebuffer.paste_be_bytes_region(
            x.max(0) as usize,
            y.max(0) as usize,
            width as usize,
            height as usize,
            pixel_data,
        );
    }
}

#[cfg(feature = "native-lvgl")]
pub use shim::ShimSceneBridge;

#[cfg(test)]
mod tests {
    use anyhow::Result;

    use super::{NativeSceneKey, NativeSceneRenderer, SceneBridge};
    use crate::screens::{
        ChromeModel, HubCardModel, HubViewModel, ListScreenModel, ScreenModel, StatusBarModel,
    };

    #[derive(Debug, Clone, PartialEq, Eq)]
    enum Event {
        Build(NativeSceneKey),
        SyncStatus,
        Sync(NativeSceneKey),
        Destroy(NativeSceneKey),
        Clear,
    }

    #[derive(Default)]
    struct FakeBridge {
        events: Vec<Event>,
    }

    impl SceneBridge for FakeBridge {
        fn build_scene(&mut self, scene: NativeSceneKey) -> Result<()> {
            self.events.push(Event::Build(scene));
            Ok(())
        }

        fn sync_status(&mut self, _status: &StatusBarModel) -> Result<()> {
            self.events.push(Event::SyncStatus);
            Ok(())
        }

        fn sync_scene(&mut self, model: &ScreenModel) -> Result<()> {
            self.events
                .push(Event::Sync(NativeSceneKey::for_screen(model.screen())));
            Ok(())
        }

        fn destroy_scene(&mut self, scene: NativeSceneKey) {
            self.events.push(Event::Destroy(scene));
        }

        fn clear_screen(&mut self) -> Result<()> {
            self.events.push(Event::Clear);
            Ok(())
        }
    }

    #[test]
    fn scene_renderer_builds_and_destroys_retained_c_scene_families() -> Result<()> {
        let mut renderer = NativeSceneRenderer::new(FakeBridge::default());

        renderer.render(&hub_model("Listen"))?;
        renderer.render(&hub_model("Talk"))?;
        renderer.render(&listen_model())?;
        renderer.clear()?;

        assert_eq!(
            renderer.bridge().events,
            vec![
                Event::Build(NativeSceneKey::Hub),
                Event::SyncStatus,
                Event::Sync(NativeSceneKey::Hub),
                Event::SyncStatus,
                Event::Sync(NativeSceneKey::Hub),
                Event::Destroy(NativeSceneKey::Hub),
                Event::Build(NativeSceneKey::Listen),
                Event::SyncStatus,
                Event::Sync(NativeSceneKey::Listen),
                Event::Destroy(NativeSceneKey::Listen),
                Event::Clear,
            ]
        );

        Ok(())
    }

    fn hub_model(title: &str) -> ScreenModel {
        ScreenModel::Hub(HubViewModel {
            chrome: chrome(),
            cards: vec![HubCardModel {
                key: "listen".to_string(),
                title: title.to_string(),
                subtitle: "Music".to_string(),
                accent: 0x00FF88,
            }],
            selected_index: 0,
        })
    }

    fn listen_model() -> ScreenModel {
        ScreenModel::Listen(ListScreenModel {
            chrome: chrome(),
            title: "Listen".to_string(),
            subtitle: "Music".to_string(),
            rows: Vec::new(),
        })
    }

    fn chrome() -> ChromeModel {
        ChromeModel {
            status: StatusBarModel {
                network_connected: true,
                network_enabled: true,
                signal_strength: 4,
                battery_percent: 100,
                charging: false,
                voip_state: 1,
            },
            footer: "Footer".to_string(),
        }
    }
}
