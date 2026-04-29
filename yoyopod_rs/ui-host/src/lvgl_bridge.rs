use std::ffi::{CStr, CString};
use std::os::raw::{c_char, c_int, c_uchar, c_void};
use std::path::{Path, PathBuf};

use anyhow::{bail, Context, Result};
use libloading::Library;

use crate::framebuffer::Framebuffer;
use crate::hub::HubSnapshot;
use crate::render::RendererState;
use crate::runtime::{ListItemSnapshot, RuntimeSnapshot, UiScreen, UiView};

type LvglFlushCb =
    unsafe extern "C" fn(c_int, c_int, c_int, c_int, *const c_uchar, u32, *mut c_void);
type LvglBuildFn = unsafe extern "C" fn() -> c_int;
type LvglDestroyFn = unsafe extern "C" fn();

#[allow(dead_code)]
struct LvglShim {
    _library: Library,
    init: unsafe extern "C" fn() -> c_int,
    shutdown: unsafe extern "C" fn(),
    register_display: unsafe extern "C" fn(c_int, c_int, u32, LvglFlushCb, *mut c_void) -> c_int,
    hub_build: unsafe extern "C" fn() -> c_int,
    hub_sync: unsafe extern "C" fn(
        *const c_char,
        *const c_char,
        *const c_char,
        *const c_char,
        *const c_char,
        u32,
        c_int,
        c_int,
        c_int,
        c_int,
        c_int,
        c_int,
    ) -> c_int,
    hub_destroy: LvglDestroyFn,
    talk_build: LvglBuildFn,
    talk_sync: unsafe extern "C" fn(
        *const c_char,
        *const c_char,
        c_int,
        *const c_char,
        c_int,
        c_int,
        c_int,
        c_int,
        c_int,
        c_int,
        u32,
    ) -> c_int,
    talk_destroy: LvglDestroyFn,
    listen_build: LvglBuildFn,
    listen_sync: unsafe extern "C" fn(
        *const c_char,
        *const c_char,
        *const c_char,
        *const c_char,
        *const c_char,
        *const c_char,
        *const c_char,
        *const c_char,
        *const c_char,
        *const c_char,
        *const c_char,
        *const c_char,
        *const c_char,
        *const c_char,
        c_int,
        c_int,
        c_int,
        c_int,
        c_int,
        c_int,
        u32,
        *const c_char,
        *const c_char,
    ) -> c_int,
    listen_destroy: LvglDestroyFn,
    playlist_build: LvglBuildFn,
    playlist_sync: unsafe extern "C" fn(
        *const c_char,
        *const c_char,
        *const c_char,
        c_int,
        *const c_char,
        *const c_char,
        *const c_char,
        *const c_char,
        *const c_char,
        *const c_char,
        *const c_char,
        *const c_char,
        *const c_char,
        *const c_char,
        *const c_char,
        *const c_char,
        *const c_char,
        *const c_char,
        *const c_char,
        *const c_char,
        *const c_char,
        c_int,
        c_int,
        c_int,
        c_int,
        c_int,
        c_int,
        u32,
        *const c_char,
        *const c_char,
        *const c_char,
    ) -> c_int,
    playlist_destroy: LvglDestroyFn,
    now_playing_build: LvglBuildFn,
    now_playing_sync: unsafe extern "C" fn(
        *const c_char,
        *const c_char,
        *const c_char,
        *const c_char,
        c_int,
        c_int,
        c_int,
        c_int,
        c_int,
        u32,
    ) -> c_int,
    now_playing_destroy: LvglDestroyFn,
    incoming_call_build: LvglBuildFn,
    incoming_call_sync: unsafe extern "C" fn(
        *const c_char,
        *const c_char,
        *const c_char,
        c_int,
        c_int,
        c_int,
        c_int,
        u32,
    ) -> c_int,
    incoming_call_destroy: LvglDestroyFn,
    outgoing_call_build: LvglBuildFn,
    outgoing_call_sync: unsafe extern "C" fn(
        *const c_char,
        *const c_char,
        *const c_char,
        c_int,
        c_int,
        c_int,
        c_int,
        u32,
    ) -> c_int,
    outgoing_call_destroy: LvglDestroyFn,
    in_call_build: LvglBuildFn,
    in_call_sync: unsafe extern "C" fn(
        *const c_char,
        *const c_char,
        *const c_char,
        *const c_char,
        c_int,
        c_int,
        c_int,
        c_int,
        c_int,
        u32,
    ) -> c_int,
    in_call_destroy: LvglDestroyFn,
    ask_build: LvglBuildFn,
    ask_sync: unsafe extern "C" fn(
        *const c_char,
        *const c_char,
        *const c_char,
        *const c_char,
        c_int,
        c_int,
        c_int,
        c_int,
        u32,
    ) -> c_int,
    ask_destroy: LvglDestroyFn,
    power_build: LvglBuildFn,
    power_sync: unsafe extern "C" fn(
        *const c_char,
        *const c_char,
        *const c_char,
        *const c_char,
        *const c_char,
        *const c_char,
        *const c_char,
        *const c_char,
        *const c_char,
        c_int,
        c_int,
        c_int,
        c_int,
        c_int,
        c_int,
        c_int,
        u32,
    ) -> c_int,
    power_destroy: LvglDestroyFn,
    force_refresh: unsafe extern "C" fn(),
    timer_handler: unsafe extern "C" fn() -> u32,
    last_error: unsafe extern "C" fn() -> *const c_char,
}

impl LvglShim {
    unsafe fn load(path: &Path) -> Result<Self> {
        let library = unsafe { Library::new(path) }
            .with_context(|| format!("loading native LVGL shim {}", path.display()))?;
        let init = unsafe { load_symbol(&library, b"yoyopod_lvgl_init\0")? };
        let shutdown = unsafe { load_symbol(&library, b"yoyopod_lvgl_shutdown\0")? };
        let register_display =
            unsafe { load_symbol(&library, b"yoyopod_lvgl_register_display\0")? };
        let hub_build = unsafe { load_symbol(&library, b"yoyopod_lvgl_hub_build\0")? };
        let hub_sync = unsafe { load_symbol(&library, b"yoyopod_lvgl_hub_sync\0")? };
        let hub_destroy = unsafe { load_symbol(&library, b"yoyopod_lvgl_hub_destroy\0")? };
        let talk_build = unsafe { load_symbol(&library, b"yoyopod_lvgl_talk_build\0")? };
        let talk_sync = unsafe { load_symbol(&library, b"yoyopod_lvgl_talk_sync\0")? };
        let talk_destroy = unsafe { load_symbol(&library, b"yoyopod_lvgl_talk_destroy\0")? };
        let listen_build = unsafe { load_symbol(&library, b"yoyopod_lvgl_listen_build\0")? };
        let listen_sync = unsafe { load_symbol(&library, b"yoyopod_lvgl_listen_sync\0")? };
        let listen_destroy = unsafe { load_symbol(&library, b"yoyopod_lvgl_listen_destroy\0")? };
        let playlist_build = unsafe { load_symbol(&library, b"yoyopod_lvgl_playlist_build\0")? };
        let playlist_sync = unsafe { load_symbol(&library, b"yoyopod_lvgl_playlist_sync\0")? };
        let playlist_destroy =
            unsafe { load_symbol(&library, b"yoyopod_lvgl_playlist_destroy\0")? };
        let now_playing_build =
            unsafe { load_symbol(&library, b"yoyopod_lvgl_now_playing_build\0")? };
        let now_playing_sync =
            unsafe { load_symbol(&library, b"yoyopod_lvgl_now_playing_sync\0")? };
        let now_playing_destroy =
            unsafe { load_symbol(&library, b"yoyopod_lvgl_now_playing_destroy\0")? };
        let incoming_call_build =
            unsafe { load_symbol(&library, b"yoyopod_lvgl_incoming_call_build\0")? };
        let incoming_call_sync =
            unsafe { load_symbol(&library, b"yoyopod_lvgl_incoming_call_sync\0")? };
        let incoming_call_destroy =
            unsafe { load_symbol(&library, b"yoyopod_lvgl_incoming_call_destroy\0")? };
        let outgoing_call_build =
            unsafe { load_symbol(&library, b"yoyopod_lvgl_outgoing_call_build\0")? };
        let outgoing_call_sync =
            unsafe { load_symbol(&library, b"yoyopod_lvgl_outgoing_call_sync\0")? };
        let outgoing_call_destroy =
            unsafe { load_symbol(&library, b"yoyopod_lvgl_outgoing_call_destroy\0")? };
        let in_call_build = unsafe { load_symbol(&library, b"yoyopod_lvgl_in_call_build\0")? };
        let in_call_sync = unsafe { load_symbol(&library, b"yoyopod_lvgl_in_call_sync\0")? };
        let in_call_destroy = unsafe { load_symbol(&library, b"yoyopod_lvgl_in_call_destroy\0")? };
        let ask_build = unsafe { load_symbol(&library, b"yoyopod_lvgl_ask_build\0")? };
        let ask_sync = unsafe { load_symbol(&library, b"yoyopod_lvgl_ask_sync\0")? };
        let ask_destroy = unsafe { load_symbol(&library, b"yoyopod_lvgl_ask_destroy\0")? };
        let power_build = unsafe { load_symbol(&library, b"yoyopod_lvgl_power_build\0")? };
        let power_sync = unsafe { load_symbol(&library, b"yoyopod_lvgl_power_sync\0")? };
        let power_destroy = unsafe { load_symbol(&library, b"yoyopod_lvgl_power_destroy\0")? };
        let force_refresh = unsafe { load_symbol(&library, b"yoyopod_lvgl_force_refresh\0")? };
        let timer_handler = unsafe { load_symbol(&library, b"yoyopod_lvgl_timer_handler\0")? };
        let last_error = unsafe { load_symbol(&library, b"yoyopod_lvgl_last_error\0")? };

        Ok(Self {
            _library: library,
            init,
            shutdown,
            register_display,
            hub_build,
            hub_sync,
            hub_destroy,
            talk_build,
            talk_sync,
            talk_destroy,
            listen_build,
            listen_sync,
            listen_destroy,
            playlist_build,
            playlist_sync,
            playlist_destroy,
            now_playing_build,
            now_playing_sync,
            now_playing_destroy,
            incoming_call_build,
            incoming_call_sync,
            incoming_call_destroy,
            outgoing_call_build,
            outgoing_call_sync,
            outgoing_call_destroy,
            in_call_build,
            in_call_sync,
            in_call_destroy,
            ask_build,
            ask_sync,
            ask_destroy,
            power_build,
            power_sync,
            power_destroy,
            force_refresh,
            timer_handler,
            last_error,
        })
    }

    fn check(&self, result: c_int, operation: &str) -> Result<()> {
        if result == 0 {
            return Ok(());
        }
        bail!(
            "native LVGL shim {operation} failed: {}",
            self.last_error_message()
        );
    }

    fn last_error_message(&self) -> String {
        let pointer = unsafe { (self.last_error)() };
        if pointer.is_null() {
            return "unknown LVGL error".to_string();
        }
        unsafe { CStr::from_ptr(pointer) }
            .to_string_lossy()
            .into_owned()
    }
}

unsafe fn load_symbol<T: Copy>(library: &Library, name: &[u8]) -> Result<T> {
    let symbol = unsafe { library.get::<T>(name) }
        .with_context(|| format!("loading native LVGL shim symbol {}", symbol_name(name)))?;
    Ok(*symbol)
}

fn symbol_name(name: &[u8]) -> String {
    String::from_utf8_lossy(name)
        .trim_end_matches('\0')
        .to_string()
}

struct LvglFlushTarget {
    framebuffer: *mut Framebuffer,
}

pub struct LvglRenderer {
    shim: LvglShim,
    target: LvglFlushTarget,
    state: RendererState,
    registered_size: Option<(usize, usize)>,
}

impl LvglRenderer {
    pub fn open(explicit_shim_path: Option<&Path>) -> Result<Self> {
        let shim_path = resolve_shim_path(explicit_shim_path)?;
        let shim = unsafe { LvglShim::load(&shim_path)? };
        shim.check(unsafe { (shim.init)() }, "init")?;
        Ok(Self {
            shim,
            target: LvglFlushTarget {
                framebuffer: std::ptr::null_mut(),
            },
            state: RendererState::default(),
            registered_size: None,
        })
    }

    pub fn render_view(
        &mut self,
        framebuffer: &mut Framebuffer,
        view: &UiView,
        snapshot: &RuntimeSnapshot,
    ) -> Result<()> {
        self.target.framebuffer = framebuffer as *mut Framebuffer;
        self.ensure_display_registered(framebuffer)?;
        if self.state.needs_rebuild(view.screen) {
            self.destroy_active_screen();
            unsafe { build_screen(&self.shim, view.screen)? };
            self.state.mark_screen_built(view.screen);
        }
        unsafe { sync_view_with_loaded_shim(&self.shim, view, snapshot)? };
        unsafe { (self.shim.force_refresh)() };
        let _ = unsafe { (self.shim.timer_handler)() };
        Ok(())
    }

    fn ensure_display_registered(&mut self, framebuffer: &Framebuffer) -> Result<()> {
        let size = (framebuffer.width(), framebuffer.height());
        if self.registered_size == Some(size) {
            return Ok(());
        }
        self.shim.check(
            unsafe {
                (self.shim.register_display)(
                    framebuffer.width() as c_int,
                    framebuffer.height() as c_int,
                    (framebuffer.width() * 40) as u32,
                    lvgl_flush_callback,
                    &mut self.target as *mut LvglFlushTarget as *mut c_void,
                )
            },
            "register_display",
        )?;
        self.registered_size = Some(size);
        Ok(())
    }

    fn destroy_active_screen(&mut self) {
        if let Some(screen) = self.state.active_screen() {
            unsafe { destroy_screen(&self.shim, screen) };
            self.state.clear();
        }
    }
}

impl Drop for LvglRenderer {
    fn drop(&mut self) {
        self.destroy_active_screen();
        unsafe { (self.shim.shutdown)() };
    }
}

pub fn render_hub_with_lvgl(
    framebuffer: &mut Framebuffer,
    snapshot: &HubSnapshot,
    explicit_shim_path: Option<&Path>,
) -> Result<()> {
    let shim_path = resolve_shim_path(explicit_shim_path)?;
    let shim = unsafe { LvglShim::load(&shim_path)? };
    let result = unsafe { render_hub_with_loaded_shim(&shim, framebuffer, snapshot) };
    unsafe { (shim.shutdown)() };
    result
}

pub fn render_view_with_lvgl(
    framebuffer: &mut Framebuffer,
    view: &UiView,
    snapshot: &RuntimeSnapshot,
    explicit_shim_path: Option<&Path>,
) -> Result<()> {
    let shim_path = resolve_shim_path(explicit_shim_path)?;
    let shim = unsafe { LvglShim::load(&shim_path)? };
    let result = unsafe { render_view_with_loaded_shim(&shim, framebuffer, view, snapshot) };
    unsafe { (shim.shutdown)() };
    result
}

unsafe fn render_hub_with_loaded_shim(
    shim: &LvglShim,
    framebuffer: &mut Framebuffer,
    snapshot: &HubSnapshot,
) -> Result<()> {
    let icon_key = c_string("icon_key", &snapshot.icon_key)?;
    let title = c_string("title", &snapshot.title)?;
    let subtitle = c_string("subtitle", &snapshot.subtitle)?;
    let footer = c_string("footer", &snapshot.footer)?;
    let time_text = c_string("time_text", &snapshot.time_text)?;
    let mut target = LvglFlushTarget {
        framebuffer: framebuffer as *mut Framebuffer,
    };

    shim.check(unsafe { (shim.init)() }, "init")?;
    shim.check(
        unsafe {
            (shim.register_display)(
                framebuffer.width() as c_int,
                framebuffer.height() as c_int,
                (framebuffer.width() * 40) as u32,
                lvgl_flush_callback,
                &mut target as *mut LvglFlushTarget as *mut c_void,
            )
        },
        "register_display",
    )?;
    shim.check(unsafe { (shim.hub_build)() }, "hub_build")?;
    shim.check(
        unsafe {
            (shim.hub_sync)(
                icon_key.as_ptr(),
                title.as_ptr(),
                subtitle.as_ptr(),
                footer.as_ptr(),
                time_text.as_ptr(),
                snapshot.accent,
                snapshot.selected_index,
                snapshot.total_cards,
                snapshot.voip_state,
                snapshot.battery_percent,
                bool_to_c_int(snapshot.charging),
                bool_to_c_int(snapshot.power_available),
            )
        },
        "hub_sync",
    )?;
    unsafe { (shim.force_refresh)() };
    let _ = unsafe { (shim.timer_handler)() };
    Ok(())
}

unsafe fn render_view_with_loaded_shim(
    shim: &LvglShim,
    framebuffer: &mut Framebuffer,
    view: &UiView,
    snapshot: &RuntimeSnapshot,
) -> Result<()> {
    let mut target = LvglFlushTarget {
        framebuffer: framebuffer as *mut Framebuffer,
    };
    shim.check(unsafe { (shim.init)() }, "init")?;
    shim.check(
        unsafe {
            (shim.register_display)(
                framebuffer.width() as c_int,
                framebuffer.height() as c_int,
                (framebuffer.width() * 40) as u32,
                lvgl_flush_callback,
                &mut target as *mut LvglFlushTarget as *mut c_void,
            )
        },
        "register_display",
    )?;

    unsafe { build_screen(shim, view.screen)? };
    unsafe { sync_view_with_loaded_shim(shim, view, snapshot)? };

    unsafe { (shim.force_refresh)() };
    let _ = unsafe { (shim.timer_handler)() };
    Ok(())
}

unsafe fn build_screen(shim: &LvglShim, screen: UiScreen) -> Result<()> {
    match native_scene(screen) {
        NativeScene::Hub => shim.check(unsafe { (shim.hub_build)() }, "hub_build"),
        NativeScene::Listen => shim.check(unsafe { (shim.listen_build)() }, "listen_build"),
        NativeScene::Playlist => shim.check(unsafe { (shim.playlist_build)() }, "playlist_build"),
        NativeScene::NowPlaying => {
            shim.check(unsafe { (shim.now_playing_build)() }, "now_playing_build")
        }
        NativeScene::Talk => shim.check(unsafe { (shim.talk_build)() }, "talk_build"),
        NativeScene::IncomingCall => shim.check(
            unsafe { (shim.incoming_call_build)() },
            "incoming_call_build",
        ),
        NativeScene::OutgoingCall => shim.check(
            unsafe { (shim.outgoing_call_build)() },
            "outgoing_call_build",
        ),
        NativeScene::InCall => shim.check(unsafe { (shim.in_call_build)() }, "in_call_build"),
        NativeScene::Ask => shim.check(unsafe { (shim.ask_build)() }, "ask_build"),
        NativeScene::Power => shim.check(unsafe { (shim.power_build)() }, "power_build"),
    }
}

unsafe fn destroy_screen(shim: &LvglShim, screen: UiScreen) {
    match native_scene(screen) {
        NativeScene::Hub => unsafe { (shim.hub_destroy)() },
        NativeScene::Listen => unsafe { (shim.listen_destroy)() },
        NativeScene::Playlist => unsafe { (shim.playlist_destroy)() },
        NativeScene::NowPlaying => unsafe { (shim.now_playing_destroy)() },
        NativeScene::Talk => unsafe { (shim.talk_destroy)() },
        NativeScene::IncomingCall => unsafe { (shim.incoming_call_destroy)() },
        NativeScene::OutgoingCall => unsafe { (shim.outgoing_call_destroy)() },
        NativeScene::InCall => unsafe { (shim.in_call_destroy)() },
        NativeScene::Ask => unsafe { (shim.ask_destroy)() },
        NativeScene::Power => unsafe { (shim.power_destroy)() },
    }
}

unsafe fn sync_view_with_loaded_shim(
    shim: &LvglShim,
    view: &UiView,
    snapshot: &RuntimeSnapshot,
) -> Result<()> {
    match view.screen {
        UiScreen::Hub => unsafe { sync_hub_view(shim, view, snapshot) },
        UiScreen::Listen => unsafe { sync_listen_view(shim, view, snapshot) },
        UiScreen::Playlists
        | UiScreen::RecentTracks
        | UiScreen::Contacts
        | UiScreen::CallHistory => unsafe { sync_playlist_view(shim, view, snapshot) },
        UiScreen::NowPlaying => unsafe { sync_now_playing_view(shim, view, snapshot) },
        UiScreen::Talk => unsafe { sync_talk_view(shim, view, snapshot) },
        UiScreen::IncomingCall => unsafe { sync_incoming_call_view(shim, view, snapshot) },
        UiScreen::OutgoingCall => unsafe { sync_outgoing_call_view(shim, view, snapshot) },
        UiScreen::InCall => unsafe { sync_in_call_view(shim, view, snapshot) },
        UiScreen::Ask | UiScreen::VoiceNote | UiScreen::Loading | UiScreen::Error => unsafe {
            sync_ask_view(shim, view, snapshot)
        },
        UiScreen::Power => unsafe { sync_power_view(shim, view, snapshot) },
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum NativeScene {
    Hub,
    Listen,
    Playlist,
    NowPlaying,
    Talk,
    IncomingCall,
    OutgoingCall,
    InCall,
    Ask,
    Power,
}

fn native_scene(screen: UiScreen) -> NativeScene {
    match screen {
        UiScreen::Hub => NativeScene::Hub,
        UiScreen::Listen => NativeScene::Listen,
        UiScreen::Playlists
        | UiScreen::RecentTracks
        | UiScreen::Contacts
        | UiScreen::CallHistory => NativeScene::Playlist,
        UiScreen::NowPlaying => NativeScene::NowPlaying,
        UiScreen::Talk => NativeScene::Talk,
        UiScreen::IncomingCall => NativeScene::IncomingCall,
        UiScreen::OutgoingCall => NativeScene::OutgoingCall,
        UiScreen::InCall => NativeScene::InCall,
        UiScreen::Ask | UiScreen::VoiceNote | UiScreen::Loading | UiScreen::Error => {
            NativeScene::Ask
        }
        UiScreen::Power => NativeScene::Power,
    }
}

unsafe fn sync_hub_view(shim: &LvglShim, view: &UiView, snapshot: &RuntimeSnapshot) -> Result<()> {
    let focused = snapshot
        .hub
        .cards
        .get(view.focus_index)
        .or_else(|| snapshot.hub.cards.first());
    let icon_key = c_string(
        "icon_key",
        focused.map(|card| card.key.as_str()).unwrap_or("listen"),
    )?;
    let title = c_string("title", &view.title)?;
    let subtitle = c_string("subtitle", &view.subtitle)?;
    let footer = c_string("footer", &view.footer)?;
    let time_text = c_string("time_text", "")?;
    shim.check(
        unsafe {
            (shim.hub_sync)(
                icon_key.as_ptr(),
                title.as_ptr(),
                subtitle.as_ptr(),
                footer.as_ptr(),
                time_text.as_ptr(),
                focused.map(|card| card.accent).unwrap_or(0x00FF88),
                view.focus_index as c_int,
                snapshot.hub.cards.len().max(1) as c_int,
                voip_state(snapshot),
                battery_percent(snapshot),
                bool_to_c_int(snapshot.power.charging),
                bool_to_c_int(snapshot.power.power_available),
            )
        },
        "hub_sync",
    )
}

unsafe fn sync_listen_view(
    shim: &LvglShim,
    view: &UiView,
    snapshot: &RuntimeSnapshot,
) -> Result<()> {
    let page = c_string("page_text", "Listen")?;
    let footer = c_string("footer", &view.footer)?;
    let items = fixed_item_strings(view, 4, |item| item.title.as_str())?;
    let subtitles = fixed_item_strings(view, 4, |item| item.subtitle.as_str())?;
    let icons = fixed_item_strings(view, 4, |item| item.icon_key.as_str())?;
    let empty_title = c_string("empty_title", "No music yet")?;
    let empty_subtitle = c_string("empty_subtitle", "Add music to the library")?;
    shim.check(
        unsafe {
            (shim.listen_sync)(
                page.as_ptr(),
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
                view.items.len() as c_int,
                view.focus_index as c_int,
                voip_state(snapshot),
                battery_percent(snapshot),
                bool_to_c_int(snapshot.power.charging),
                bool_to_c_int(snapshot.power.power_available),
                0x00FF88,
                empty_title.as_ptr(),
                empty_subtitle.as_ptr(),
            )
        },
        "listen_sync",
    )
}

unsafe fn sync_playlist_view(
    shim: &LvglShim,
    view: &UiView,
    snapshot: &RuntimeSnapshot,
) -> Result<()> {
    let title = c_string("title_text", &view.title)?;
    let page = c_string("page_text", "Music")?;
    let status = c_string("status_chip_text", "")?;
    let footer = c_string("footer", &view.footer)?;
    let items = fixed_item_strings(view, 4, |item| item.title.as_str())?;
    let subtitles = fixed_item_strings(view, 4, |item| item.subtitle.as_str())?;
    let badges = fixed_item_strings(view, 4, |_| "")?;
    let icons = fixed_item_strings(view, 4, |item| item.icon_key.as_str())?;
    let empty_title = c_string("empty_title", "No playlists")?;
    let empty_subtitle = c_string("empty_subtitle", "Sync music first")?;
    let empty_icon = c_string("empty_icon_key", "playlist")?;
    shim.check(
        unsafe {
            (shim.playlist_sync)(
                title.as_ptr(),
                page.as_ptr(),
                status.as_ptr(),
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
                view.items.len() as c_int,
                view.focus_index as c_int,
                voip_state(snapshot),
                battery_percent(snapshot),
                bool_to_c_int(snapshot.power.charging),
                bool_to_c_int(snapshot.power.power_available),
                0x00FF88,
                empty_title.as_ptr(),
                empty_subtitle.as_ptr(),
                empty_icon.as_ptr(),
            )
        },
        "playlist_sync",
    )
}

unsafe fn sync_now_playing_view(
    shim: &LvglShim,
    view: &UiView,
    snapshot: &RuntimeSnapshot,
) -> Result<()> {
    let title = c_string("title_text", &view.title)?;
    let artist = c_string("artist_text", &view.subtitle)?;
    let state = c_string(
        "state_text",
        if snapshot.music.playing {
            "Playing"
        } else if snapshot.music.paused {
            "Paused"
        } else {
            "Stopped"
        },
    )?;
    let footer = c_string("footer", &view.footer)?;
    shim.check(
        unsafe {
            (shim.now_playing_sync)(
                title.as_ptr(),
                artist.as_ptr(),
                state.as_ptr(),
                footer.as_ptr(),
                snapshot.music.progress_permille.clamp(0, 1000),
                voip_state(snapshot),
                battery_percent(snapshot),
                bool_to_c_int(snapshot.power.charging),
                bool_to_c_int(snapshot.power.power_available),
                0x00FF88,
            )
        },
        "now_playing_sync",
    )
}

unsafe fn sync_talk_view(shim: &LvglShim, view: &UiView, snapshot: &RuntimeSnapshot) -> Result<()> {
    let title = c_string("title_text", &view.title)?;
    let icon = c_string("icon_key", "talk")?;
    let footer = c_string("footer", &view.footer)?;
    shim.check(
        unsafe {
            (shim.talk_sync)(
                title.as_ptr(),
                icon.as_ptr(),
                0,
                footer.as_ptr(),
                view.focus_index as c_int,
                view.items.len().max(1) as c_int,
                voip_state(snapshot),
                battery_percent(snapshot),
                bool_to_c_int(snapshot.power.charging),
                bool_to_c_int(snapshot.power.power_available),
                0x00D4FF,
            )
        },
        "talk_sync",
    )
}

unsafe fn sync_incoming_call_view(
    shim: &LvglShim,
    view: &UiView,
    snapshot: &RuntimeSnapshot,
) -> Result<()> {
    let name = c_string("caller_name", &view.title)?;
    let address = c_string("caller_address", &view.subtitle)?;
    let footer = c_string("footer", &view.footer)?;
    shim.check(
        unsafe {
            (shim.incoming_call_sync)(
                name.as_ptr(),
                address.as_ptr(),
                footer.as_ptr(),
                voip_state(snapshot),
                battery_percent(snapshot),
                bool_to_c_int(snapshot.power.charging),
                bool_to_c_int(snapshot.power.power_available),
                0x00D4FF,
            )
        },
        "incoming_call_sync",
    )
}

unsafe fn sync_outgoing_call_view(
    shim: &LvglShim,
    view: &UiView,
    snapshot: &RuntimeSnapshot,
) -> Result<()> {
    let name = c_string("callee_name", &view.title)?;
    let address = c_string("callee_address", &view.subtitle)?;
    let footer = c_string("footer", &view.footer)?;
    shim.check(
        unsafe {
            (shim.outgoing_call_sync)(
                name.as_ptr(),
                address.as_ptr(),
                footer.as_ptr(),
                voip_state(snapshot),
                battery_percent(snapshot),
                bool_to_c_int(snapshot.power.charging),
                bool_to_c_int(snapshot.power.power_available),
                0x00D4FF,
            )
        },
        "outgoing_call_sync",
    )
}

unsafe fn sync_in_call_view(
    shim: &LvglShim,
    view: &UiView,
    snapshot: &RuntimeSnapshot,
) -> Result<()> {
    let name = c_string("caller_name", &view.title)?;
    let duration = c_string("duration_text", &view.subtitle)?;
    let mute = c_string(
        "mute_text",
        if snapshot.call.muted {
            "Muted"
        } else {
            "Mic on"
        },
    )?;
    let footer = c_string("footer", &view.footer)?;
    shim.check(
        unsafe {
            (shim.in_call_sync)(
                name.as_ptr(),
                duration.as_ptr(),
                mute.as_ptr(),
                footer.as_ptr(),
                bool_to_c_int(snapshot.call.muted),
                voip_state(snapshot),
                battery_percent(snapshot),
                bool_to_c_int(snapshot.power.charging),
                bool_to_c_int(snapshot.power.power_available),
                0x00D4FF,
            )
        },
        "in_call_sync",
    )
}

unsafe fn sync_ask_view(shim: &LvglShim, view: &UiView, snapshot: &RuntimeSnapshot) -> Result<()> {
    let icon = c_string("icon_key", "ask")?;
    let title = c_string("title_text", &view.title)?;
    let subtitle = c_string("subtitle_text", &view.subtitle)?;
    let footer = c_string("footer", &view.footer)?;
    shim.check(
        unsafe {
            (shim.ask_sync)(
                icon.as_ptr(),
                title.as_ptr(),
                subtitle.as_ptr(),
                footer.as_ptr(),
                voip_state(snapshot),
                battery_percent(snapshot),
                bool_to_c_int(snapshot.power.charging),
                bool_to_c_int(snapshot.power.power_available),
                0x9F7AEA,
            )
        },
        "ask_sync",
    )
}

unsafe fn sync_power_view(
    shim: &LvglShim,
    view: &UiView,
    snapshot: &RuntimeSnapshot,
) -> Result<()> {
    let title = c_string("title_text", &view.title)?;
    let page = c_string("page_text", &view.subtitle)?;
    let icon = c_string("icon_key", "battery")?;
    let footer = c_string("footer", &view.footer)?;
    let rows = fixed_item_strings(view, 5, |item| item.title.as_str())?;
    shim.check(
        unsafe {
            (shim.power_sync)(
                title.as_ptr(),
                page.as_ptr(),
                icon.as_ptr(),
                footer.as_ptr(),
                rows[0].as_ptr(),
                rows[1].as_ptr(),
                rows[2].as_ptr(),
                rows[3].as_ptr(),
                rows[4].as_ptr(),
                view.items.len() as c_int,
                view.focus_index as c_int,
                view.items.len().max(1) as c_int,
                voip_state(snapshot),
                battery_percent(snapshot),
                bool_to_c_int(snapshot.power.charging),
                bool_to_c_int(snapshot.power.power_available),
                0xF6AD55,
            )
        },
        "power_sync",
    )
}

unsafe extern "C" fn lvgl_flush_callback(
    x: c_int,
    y: c_int,
    width: c_int,
    height: c_int,
    pixel_data: *const c_uchar,
    byte_length: u32,
    user_data: *mut c_void,
) {
    if user_data.is_null() || pixel_data.is_null() || x < 0 || y < 0 || width < 1 || height < 1 {
        return;
    }

    let target = unsafe { &mut *(user_data as *mut LvglFlushTarget) };
    let framebuffer = unsafe { &mut *target.framebuffer };
    let bytes = unsafe { std::slice::from_raw_parts(pixel_data, byte_length as usize) };
    framebuffer.paste_be_bytes_region(
        x as usize,
        y as usize,
        width as usize,
        height as usize,
        bytes,
    );
}

fn c_string(name: &str, value: &str) -> Result<CString> {
    CString::new(value).with_context(|| format!("Hub field {name} contains a NUL byte"))
}

fn fixed_item_strings<F>(view: &UiView, count: usize, field: F) -> Result<Vec<CString>>
where
    F: Fn(&ListItemSnapshot) -> &str,
{
    let mut values = Vec::with_capacity(count);
    for index in 0..count {
        let value = view.items.get(index).map(&field).unwrap_or("");
        values.push(c_string("item", value)?);
    }
    Ok(values)
}

fn voip_state(snapshot: &RuntimeSnapshot) -> c_int {
    match snapshot.call.state.as_str() {
        "incoming" | "outgoing" | "active" => 2,
        _ => 1,
    }
}

fn battery_percent(snapshot: &RuntimeSnapshot) -> c_int {
    snapshot.power.battery_percent.clamp(0, 100)
}

fn bool_to_c_int(value: bool) -> c_int {
    if value {
        1
    } else {
        0
    }
}

fn resolve_shim_path(explicit_shim_path: Option<&Path>) -> Result<PathBuf> {
    if let Some(path) = explicit_shim_path {
        if path.exists() {
            return Ok(path.to_path_buf());
        }
        bail!("native LVGL shim not found at {}", path.display());
    }

    for env_name in ["YOYOPOD_RUST_UI_LVGL_SHIM_PATH", "YOYOPOD_LVGL_SHIM_PATH"] {
        if let Ok(value) = std::env::var(env_name) {
            let path = PathBuf::from(value);
            if path.exists() {
                return Ok(path);
            }
        }
    }

    let cwd = std::env::current_dir().context("resolving current directory for LVGL shim")?;
    for path in default_shim_candidates(&cwd) {
        if path.exists() {
            return Ok(path);
        }
    }

    bail!(
        "native LVGL shim not found; set YOYOPOD_RUST_UI_LVGL_SHIM_PATH or run yoyopod build lvgl"
    );
}

pub fn default_shim_candidates(base_dir: &Path) -> Vec<PathBuf> {
    vec![
        base_dir
            .join("yoyopod")
            .join("ui")
            .join("lvgl_binding")
            .join("native")
            .join("build")
            .join(shim_file_name()),
        base_dir.join("build").join("lvgl").join(shim_file_name()),
    ]
}

fn shim_file_name() -> &'static str {
    if cfg!(target_os = "windows") {
        "yoyopod_lvgl_shim.dll"
    } else if cfg!(target_os = "macos") {
        "libyoyopod_lvgl_shim.dylib"
    } else {
        "libyoyopod_lvgl_shim.so"
    }
}
