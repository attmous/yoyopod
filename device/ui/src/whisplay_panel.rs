pub const WIDTH: usize = 240;
pub const HEIGHT: usize = 280;
pub const ROW_OFFSET: u16 = 20;

pub const DEFAULT_SPI_HZ: u32 = 100_000_000;
pub const DEFAULT_DC_GPIO: u8 = 27;
pub const DEFAULT_RESET_GPIO: u8 = 4;
pub const DEFAULT_BACKLIGHT_GPIO: u8 = 22;
pub const DEFAULT_BUTTON_GPIO: u8 = 17;
pub const DEFAULT_BACKLIGHT_ACTIVE_LOW: bool = true;
pub const DEFAULT_BUTTON_ACTIVE_LOW: bool = false;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct PanelCommand {
    pub command: u8,
    pub data: &'static [u8],
    pub delay_ms: u64,
}

impl PanelCommand {
    const fn new(command: u8, data: &'static [u8], delay_ms: u64) -> Self {
        Self {
            command,
            data,
            delay_ms,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct AddressWindow {
    pub x: [u8; 4],
    pub y: [u8; 4],
}

const GAMMA_POSITIVE: &[u8] = &[
    0xD0, 0x08, 0x0E, 0x09, 0x09, 0x05, 0x31, 0x33, 0x48, 0x17, 0x14, 0x15, 0x31, 0x34,
];
const GAMMA_NEGATIVE: &[u8] = &[
    0xD0, 0x08, 0x0E, 0x09, 0x09, 0x15, 0x31, 0x33, 0x48, 0x17, 0x14, 0x15, 0x31, 0x34,
];

const INIT_SEQUENCE: &[PanelCommand] = &[
    PanelCommand::new(0x11, &[], 120),    // sleep out
    PanelCommand::new(0x36, &[0xC0], 0),  // vendor Whisplay orientation
    PanelCommand::new(0x3A, &[0x05], 10), // RGB565
    PanelCommand::new(0xB2, &[0x0C, 0x0C, 0x00, 0x33, 0x33], 0),
    PanelCommand::new(0xB7, &[0x35], 0),
    PanelCommand::new(0xBB, &[0x32], 0),
    PanelCommand::new(0xC2, &[0x01], 0),
    PanelCommand::new(0xC3, &[0x15], 0),
    PanelCommand::new(0xC4, &[0x20], 0),
    PanelCommand::new(0xC6, &[0x0F], 0),
    PanelCommand::new(0xD0, &[0xA4, 0xA1], 0),
    PanelCommand::new(0xE0, GAMMA_POSITIVE, 0),
    PanelCommand::new(0xE1, GAMMA_NEGATIVE, 0),
    PanelCommand::new(0x21, &[], 10), // inversion on
    PanelCommand::new(0x29, &[], 50), // display on
];

pub fn whisplay_init_sequence() -> &'static [PanelCommand] {
    INIT_SEQUENCE
}

pub fn whisplay_address_window(x0: u16, y0: u16, x1: u16, y1: u16) -> AddressWindow {
    AddressWindow {
        x: range_bytes(x0, x1),
        y: range_bytes(y0 + ROW_OFFSET, y1 + ROW_OFFSET),
    }
}

pub fn backlight_output_high(brightness: f32, active_low: bool) -> bool {
    let enabled = brightness > 0.0;
    if active_low {
        !enabled
    } else {
        enabled
    }
}

fn range_bytes(start: u16, end: u16) -> [u8; 4] {
    let mut data = [0u8; 4];
    data[0..2].copy_from_slice(&start.to_be_bytes());
    data[2..4].copy_from_slice(&end.to_be_bytes());
    data
}
