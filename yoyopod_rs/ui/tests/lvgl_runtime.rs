use yoyopod_ui::lvgl::open_default_facade;

#[cfg(not(feature = "native-lvgl"))]
#[test]
fn open_default_facade_without_native_feature_returns_contextual_error() {
    let error = match open_default_facade(None) {
        Ok(_) => panic!("native-lvgl should be required"),
        Err(error) => error,
    };

    assert!(error.to_string().contains("native-lvgl feature"));
}

#[cfg(feature = "native-lvgl")]
use std::path::Path;
#[cfg(feature = "native-lvgl")]
use std::sync::{Mutex, MutexGuard, OnceLock};
#[cfg(feature = "native-lvgl")]
use yoyopod_ui::framebuffer::{rgb565, Framebuffer};
#[cfg(feature = "native-lvgl")]
use yoyopod_ui::render::LvglRenderer;
#[cfg(feature = "native-lvgl")]
use yoyopod_ui::screens::{ChromeModel, ListScreenModel, ScreenModel, StatusBarModel};

#[cfg(feature = "native-lvgl")]
fn native_lvgl_test_guard() -> MutexGuard<'static, ()> {
    static LOCK: OnceLock<Mutex<()>> = OnceLock::new();
    LOCK.get_or_init(|| Mutex::new(()))
        .lock()
        .expect("native LVGL test lock should not be poisoned")
}

#[cfg(feature = "native-lvgl")]
#[test]
fn open_default_facade_with_missing_explicit_source_returns_contextual_error() {
    let _guard = native_lvgl_test_guard();
    let error = match open_default_facade(Some(Path::new("missing-lvgl-source"))) {
        Ok(_) => panic!("missing LVGL source must fail"),
        Err(error) => error,
    };

    assert!(error.to_string().contains("LVGL source"));
}

#[cfg(feature = "native-lvgl")]
#[test]
fn open_default_facade_without_runtime_source_configuration_opens_backend() {
    let _guard = native_lvgl_test_guard();
    open_default_facade(None).expect("native backend should open without runtime source config");
}

#[cfg(feature = "native-lvgl")]
#[test]
fn native_renderer_paints_yoyopod_background_instead_of_lvgl_default_white() {
    let _guard = native_lvgl_test_guard();
    let mut renderer = LvglRenderer::open(None).expect("native backend should open");
    let mut framebuffer = Framebuffer::new(240, 280);

    renderer
        .render_screen_model(&mut framebuffer, &listen_screen_model())
        .expect("native LVGL render should succeed");

    assert_eq!(framebuffer.pixel(4, 4), rgb565(0x2A, 0x2D, 0x35));
    assert_ne!(framebuffer.pixel(4, 4), rgb565(0xFF, 0xFF, 0xFF));
}

#[cfg(feature = "native-lvgl")]
fn listen_screen_model() -> ScreenModel {
    ScreenModel::Listen(ListScreenModel {
        chrome: ChromeModel {
            status: StatusBarModel {
                network_connected: true,
                network_enabled: true,
                connection_type: "4g".to_string(),
                signal_strength: 4,
                gps_has_fix: true,
                battery_percent: 100,
                charging: false,
                power_available: true,
                voip_state: 1,
            },
            footer: "Tap = Next | Hold = Back".to_string(),
        },
        title: "Listen".to_string(),
        subtitle: "Tracks".to_string(),
        rows: Vec::new(),
    })
}
