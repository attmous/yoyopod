use crate::framebuffer::{rgb565, Framebuffer};
use crate::hub::HubSnapshot;
use crate::runtime::UiScreen;
use crate::screens::{ChromeModel, ListRowModel, ScreenModel, StatusBarModel};

pub struct FramebufferRenderer;

impl FramebufferRenderer {
    pub fn render_screen_model(framebuffer: &mut Framebuffer, model: &ScreenModel) {
        render_screen_model_fallback(framebuffer, model);
    }
}

pub fn render_test_scene(framebuffer: &mut Framebuffer, counter: u64) {
    framebuffer.clear(rgb565(8, 10, 14));

    framebuffer.fill_rect(12, 16, 216, 52, rgb565(34, 48, 70));
    framebuffer.fill_rect(24, 28, 132, 12, rgb565(240, 242, 245));
    framebuffer.fill_rect(24, 48, 86, 8, rgb565(80, 196, 160));

    let progress_width = 32 + ((counter as usize * 17) % 168);
    framebuffer.fill_rect(20, 92, 200, 18, rgb565(18, 24, 34));
    framebuffer.fill_rect(20, 92, progress_width, 18, rgb565(248, 190, 72));

    let button_top = 170 + ((counter as usize * 11) % 42);
    framebuffer.fill_rect(80, button_top, 80, 52, rgb565(22, 116, 138));
    framebuffer.fill_rect(96, button_top + 14, 48, 10, rgb565(230, 250, 248));
}

pub fn render_hub_fallback(framebuffer: &mut Framebuffer, snapshot: &HubSnapshot) {
    framebuffer.clear(rgb565(42, 45, 53));

    framebuffer.fill_rect(0, 0, 240, 28, rgb565(31, 33, 39));
    framebuffer.fill_rect(16, 10, 40, 6, status_color(snapshot.voip_state));
    let battery_width = ((snapshot.battery_percent.clamp(0, 100) as usize) * 28) / 100;
    framebuffer.fill_rect(188, 9, 32, 10, rgb565(122, 125, 132));
    framebuffer.fill_rect(190, 11, battery_width, 6, rgb565(61, 221, 83));

    let accent = rgb_from_u24(snapshot.accent);
    let glow = mix_rgb(accent, (42, 45, 53), 72);
    framebuffer.fill_rect(62, 48, 116, 116, rgb565(glow.0, glow.1, glow.2));
    framebuffer.fill_rect(72, 58, 96, 96, rgb565(accent.0, accent.1, accent.2));

    let icon_color = if snapshot.icon_key == "talk" {
        rgb565(240, 250, 255)
    } else {
        rgb565(255, 255, 255)
    };
    framebuffer.fill_rect(104, 88, 32, 36, icon_color);
    framebuffer.fill_rect(96, 124, 48, 8, icon_color);

    framebuffer.fill_rect(60, 176, 120, 24, rgb565(255, 255, 255));
    if !snapshot.subtitle.is_empty() {
        framebuffer.fill_rect(78, 206, 84, 8, rgb565(122, 125, 132));
    }

    let total_cards = snapshot.total_cards.clamp(1, 4) as usize;
    let selected_index = snapshot.selected_index.rem_euclid(total_cards as i32) as usize;
    let dot_spacing = 10usize;
    let dots_width = ((total_cards - 1) * dot_spacing) + 4;
    let first_x = (240 - dots_width) / 2;
    for index in 0..total_cards {
        let width = if index == selected_index { 10 } else { 4 };
        framebuffer.fill_rect(
            first_x + (index * dot_spacing),
            218,
            width,
            4,
            rgb565(255, 255, 255),
        );
    }

    framebuffer.fill_rect(0, 248, 240, 32, rgb565(31, 33, 39));
    framebuffer.fill_rect(34, 261, 172, 5, rgb565(122, 125, 132));
}

pub fn render_screen_model_fallback(framebuffer: &mut Framebuffer, model: &ScreenModel) {
    framebuffer.clear(background_color(model.screen()));
    render_status_bar(framebuffer, &chrome(model).status);
    render_screen_body(framebuffer, model);
    render_footer(framebuffer, &chrome(model).footer);
}

fn render_status_bar(framebuffer: &mut Framebuffer, status: &StatusBarModel) {
    framebuffer.fill_rect(0, 0, 240, 28, rgb565(25, 28, 34));
    let network = if status.network_connected {
        rgb565(61, 221, 83)
    } else if status.network_enabled {
        rgb565(255, 213, 73)
    } else {
        rgb565(122, 125, 132)
    };
    framebuffer.fill_rect(14, 10, 34, 7, network);

    let battery_width = ((status.battery_percent.clamp(0, 100) as usize) * 28) / 100;
    framebuffer.fill_rect(188, 9, 32, 10, rgb565(122, 125, 132));
    framebuffer.fill_rect(
        190,
        11,
        battery_width,
        6,
        if status.charging {
            rgb565(61, 221, 83)
        } else {
            rgb565(246, 173, 85)
        },
    );
    framebuffer.fill_rect(
        52,
        10,
        14,
        7,
        if status.signal_strength > 0 {
            rgb565(61, 221, 83)
        } else {
            rgb565(246, 173, 85)
        },
    );
}

fn render_screen_body(framebuffer: &mut Framebuffer, model: &ScreenModel) {
    match model {
        ScreenModel::Hub(hub) => {
            let accent = hub_focus_color(hub.selected_index);
            framebuffer.fill_rect(52, 48, 136, 118, rgb565(45, 50, 60));
            framebuffer.fill_rect(70, 64, 100, 86, accent);
            render_focus_dots(framebuffer, hub.cards.len().max(1), hub.selected_index, 214);
        }
        ScreenModel::IncomingCall(call)
        | ScreenModel::OutgoingCall(call)
        | ScreenModel::InCall(call) => {
            framebuffer.fill_rect(48, 52, 144, 144, rgb565(38, 45, 54));
            framebuffer.fill_rect(78, 80, 84, 84, rgb565(0, 212, 255));
            framebuffer.fill_rect(58, 214, 124, 10, rgb565(255, 255, 255));
            if call.muted {
                framebuffer.fill_rect(166, 70, 28, 12, rgb565(246, 173, 85));
            }
        }
        ScreenModel::NowPlaying(now_playing) => {
            framebuffer.fill_rect(42, 48, 156, 112, rgb565(34, 48, 70));
            framebuffer.fill_rect(60, 178, 120, 8, rgb565(122, 125, 132));
            let progress_width =
                ((now_playing.progress_permille.clamp(0, 1000) as usize) * 120) / 1000;
            framebuffer.fill_rect(60, 178, progress_width, 8, rgb565(0, 255, 136));
        }
        ScreenModel::Ask(_) | ScreenModel::TalkContact(_) | ScreenModel::VoiceNote(_) => {
            framebuffer.fill_rect(62, 52, 116, 116, rgb565(99, 102, 241));
            framebuffer.fill_rect(94, 78, 52, 68, rgb565(255, 255, 255));
        }
        ScreenModel::Power(power) => {
            framebuffer.fill_rect(30, 54, 180, 118, rgb565(34, 48, 70));
            framebuffer.fill_rect(54, 92, 132, 28, rgb565(61, 221, 83));
            render_list_rows(framebuffer, &power.rows, 188);
        }
        ScreenModel::Loading(overlay) | ScreenModel::Error(overlay) => {
            framebuffer.fill_rect(36, 68, 168, 92, rgb565(34, 48, 70));
            framebuffer.fill_rect(54, 92, 132, 16, rgb565(240, 242, 245));
            if !overlay.subtitle.trim().is_empty() {
                framebuffer.fill_rect(62, 126, 116, 10, rgb565(122, 125, 132));
            }
        }
        ScreenModel::Listen(list)
        | ScreenModel::Playlists(list)
        | ScreenModel::RecentTracks(list)
        | ScreenModel::Talk(list)
        | ScreenModel::Contacts(list)
        | ScreenModel::CallHistory(list) => render_list_rows(framebuffer, &list.rows, 54),
    }
}

fn render_list_rows(framebuffer: &mut Framebuffer, rows: &[ListRowModel], start_y: usize) {
    let count = rows.len().min(4);
    if count == 0 {
        framebuffer.fill_rect(56, 112, 128, 18, rgb565(122, 125, 132));
        return;
    }

    for (index, row) in rows.iter().enumerate().take(count) {
        let y = start_y + index * 38;
        let selected = row.selected;
        framebuffer.fill_rect(
            18,
            y,
            204,
            30,
            if selected {
                rgb565(0, 212, 255)
            } else {
                rgb565(40, 45, 54)
            },
        );
        framebuffer.fill_rect(
            30,
            y + 10,
            90 + (index * 17),
            7,
            if selected {
                rgb565(255, 255, 255)
            } else {
                rgb565(156, 163, 175)
            },
        );
    }
}

fn render_footer(framebuffer: &mut Framebuffer, footer: &str) {
    framebuffer.fill_rect(0, 248, 240, 32, rgb565(25, 28, 34));
    let footer_width = if footer.trim().is_empty() { 96 } else { 172 };
    framebuffer.fill_rect(34, 261, footer_width, 5, rgb565(122, 125, 132));
}

fn render_focus_dots(framebuffer: &mut Framebuffer, total: usize, selected_index: usize, y: usize) {
    let total = total.clamp(1, 4);
    let dot_spacing = 10usize;
    let dots_width = ((total - 1) * dot_spacing) + 4;
    let first_x = (240 - dots_width) / 2;
    for index in 0..total {
        framebuffer.fill_rect(
            first_x + (index * dot_spacing),
            y,
            if index == selected_index.min(total - 1) {
                10
            } else {
                4
            },
            4,
            rgb565(255, 255, 255),
        );
    }
}

fn background_color(screen: UiScreen) -> u16 {
    match screen {
        UiScreen::IncomingCall | UiScreen::OutgoingCall | UiScreen::InCall => rgb565(20, 28, 36),
        UiScreen::Error => rgb565(70, 20, 28),
        UiScreen::Loading => rgb565(25, 28, 34),
        _ => rgb565(42, 45, 53),
    }
}

fn chrome(model: &ScreenModel) -> &ChromeModel {
    match model {
        ScreenModel::Hub(hub) => &hub.chrome,
        ScreenModel::Listen(list)
        | ScreenModel::Playlists(list)
        | ScreenModel::RecentTracks(list)
        | ScreenModel::Talk(list)
        | ScreenModel::Contacts(list)
        | ScreenModel::CallHistory(list) => &list.chrome,
        ScreenModel::NowPlaying(now_playing) => &now_playing.chrome,
        ScreenModel::Ask(ask) => &ask.chrome,
        ScreenModel::TalkContact(actions) | ScreenModel::VoiceNote(actions) => &actions.chrome,
        ScreenModel::IncomingCall(call)
        | ScreenModel::OutgoingCall(call)
        | ScreenModel::InCall(call) => &call.chrome,
        ScreenModel::Power(power) => &power.chrome,
        ScreenModel::Loading(overlay) | ScreenModel::Error(overlay) => &overlay.chrome,
    }
}

fn hub_focus_color(index: usize) -> u16 {
    match index {
        0 => rgb565(0, 255, 136),
        1 => rgb565(0, 212, 255),
        2 => rgb565(159, 122, 234),
        _ => rgb565(246, 173, 85),
    }
}

fn status_color(voip_state: i32) -> u16 {
    match voip_state {
        1 => rgb565(61, 221, 83),
        2 => rgb565(255, 213, 73),
        _ => rgb565(156, 163, 175),
    }
}

fn rgb_from_u24(value: u32) -> (u8, u8, u8) {
    (
        ((value >> 16) & 0xFF) as u8,
        ((value >> 8) & 0xFF) as u8,
        (value & 0xFF) as u8,
    )
}

fn mix_rgb(foreground: (u8, u8, u8), background: (u8, u8, u8), weight: u8) -> (u8, u8, u8) {
    let weight = weight as u16;
    let inverse = 255u16.saturating_sub(weight);
    (
        (((foreground.0 as u16 * weight) + (background.0 as u16 * inverse)) / 255) as u8,
        (((foreground.1 as u16 * weight) + (background.1 as u16 * inverse)) / 255) as u8,
        (((foreground.2 as u16 * weight) + (background.2 as u16 * inverse)) / 255) as u8,
    )
}
