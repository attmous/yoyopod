use yoyopod_ui::whisplay_panel::{
    backlight_output_high, whisplay_address_window, whisplay_init_sequence,
    DEFAULT_BACKLIGHT_ACTIVE_LOW, DEFAULT_BACKLIGHT_GPIO, DEFAULT_BUTTON_ACTIVE_LOW,
    DEFAULT_BUTTON_GPIO, DEFAULT_DC_GPIO, DEFAULT_RESET_GPIO, DEFAULT_SPI_HZ, HEIGHT, WIDTH,
};

#[test]
fn init_sequence_matches_vendor_orientation_and_color_mode() {
    let sequence = whisplay_init_sequence();

    assert_eq!(sequence[0].command, 0x11);
    assert!(sequence
        .iter()
        .any(|command| command.command == 0x36 && command.data == [0xC0]));
    assert!(sequence
        .iter()
        .any(|command| command.command == 0x3A && command.data == [0x05]));
    assert!(sequence.iter().any(|command| command.command == 0x21));
    assert_eq!(sequence.last().expect("init command").command, 0x29);
}

#[test]
fn address_window_applies_whisplay_row_offset() {
    let window = whisplay_address_window(0, 0, 239, 279);

    assert_eq!(window.x, [0x00, 0x00, 0x00, 0xEF]);
    assert_eq!(window.y, [0x00, 0x14, 0x01, 0x2B]);
}

#[test]
fn defaults_match_whisplay_hat_board_pins() {
    assert_eq!(WIDTH, 240);
    assert_eq!(HEIGHT, 280);
    assert_eq!(DEFAULT_SPI_HZ, 100_000_000);
    assert_eq!(DEFAULT_DC_GPIO, 27);
    assert_eq!(DEFAULT_RESET_GPIO, 4);
    assert_eq!(DEFAULT_BACKLIGHT_GPIO, 22);
    assert_eq!(DEFAULT_BUTTON_GPIO, 17);
    const {
        assert!(DEFAULT_BACKLIGHT_ACTIVE_LOW);
        assert!(!DEFAULT_BUTTON_ACTIVE_LOW);
    }
}

#[test]
fn active_low_backlight_turns_on_by_driving_low() {
    assert!(!backlight_output_high(1.0, true));
    assert!(backlight_output_high(0.0, true));
    assert!(backlight_output_high(1.0, false));
    assert!(!backlight_output_high(0.0, false));
}
