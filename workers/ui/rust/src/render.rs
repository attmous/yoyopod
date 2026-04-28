use crate::framebuffer::{rgb565, Framebuffer};
use crate::hub::HubSnapshot;

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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_scene_changes_with_counter() {
        let mut first = Framebuffer::new(240, 280);
        let mut second = Framebuffer::new(240, 280);

        render_test_scene(&mut first, 1);
        render_test_scene(&mut second, 2);

        assert_ne!(first.as_be_bytes(), second.as_be_bytes());
        assert_eq!(first.pixel(0, 0), rgb565(8, 10, 14));
    }

    #[test]
    fn hub_fallback_uses_snapshot_accent() {
        let mut first = Framebuffer::new(240, 280);
        let mut second = Framebuffer::new(240, 280);
        let mut first_snapshot = HubSnapshot::static_default();
        let mut second_snapshot = HubSnapshot::static_default();
        first_snapshot.accent = 0x00FF88;
        second_snapshot.accent = 0x00D4FF;

        render_hub_fallback(&mut first, &first_snapshot);
        render_hub_fallback(&mut second, &second_snapshot);

        assert_ne!(first.as_be_bytes(), second.as_be_bytes());
        assert_eq!(first.pixel(72, 58), rgb565(0, 255, 136));
        assert_eq!(second.pixel(72, 58), rgb565(0, 212, 255));
    }
}
