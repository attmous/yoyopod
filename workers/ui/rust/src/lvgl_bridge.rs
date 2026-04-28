use std::ffi::{CStr, CString};
use std::os::raw::{c_char, c_int, c_uchar, c_void};
use std::path::{Path, PathBuf};

use anyhow::{bail, Context, Result};
use libloading::Library;

use crate::framebuffer::Framebuffer;
use crate::hub::HubSnapshot;

type LvglFlushCb =
    unsafe extern "C" fn(c_int, c_int, c_int, c_int, *const c_uchar, u32, *mut c_void);

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

#[cfg(test)]
mod tests {
    use super::*;
    use crate::framebuffer::Framebuffer;
    use crate::hub::HubSnapshot;
    use std::path::Path;

    #[test]
    fn missing_explicit_shim_path_returns_contextual_error() {
        let mut framebuffer = Framebuffer::new(240, 280);
        let error = render_hub_with_lvgl(
            &mut framebuffer,
            &HubSnapshot::static_default(),
            Some(Path::new("missing-yoyopod-lvgl-shim.so")),
        )
        .expect_err("missing shim must fail");

        assert!(error.to_string().contains("native LVGL shim"));
    }

    #[test]
    fn default_shim_candidates_include_repo_native_build() {
        let candidates = default_shim_candidates(Path::new("/repo"));

        assert!(candidates.iter().any(|path| path
            .to_string_lossy()
            .replace('\\', "/")
            .contains("yoyopod/ui/lvgl_binding/native/build")));
    }
}
