pub const BACKGROUND_RGB: u32 = 0x2A2D35;
pub const SURFACE_RGB: u32 = 0x31343C;
pub const SURFACE_RAISED_RGB: u32 = 0x363A44;
pub const FOOTER_RGB: u32 = 0x1F2127;
pub const INK_RGB: u32 = 0xFFFFFF;
pub const MUTED_RGB: u32 = 0xB4B7BE;
pub const MUTED_DIM_RGB: u32 = 0x7A7D84;
pub const BORDER_RGB: u32 = 0x505561;
pub const SELECTED_ROW_RGB: u32 = 0xFAFAFA;
pub const ACCENT_GREEN_RGB: u32 = 0x3DDD53;
pub const ACCENT_CYAN_RGB: u32 = 0x00D4FF;
pub const ACCENT_YELLOW_RGB: u32 = 0xFFD000;
pub const ACCENT_NEUTRAL_RGB: u32 = 0x9CA3AF;
pub const WARNING_RGB: u32 = 0xFFD549;
pub const ERROR_RGB: u32 = 0xFF675D;

pub const OPA_TRANSP: u8 = 0;
pub const OPA_COVER: u8 = 255;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct WidgetStyle {
    pub bg_color: Option<u32>,
    pub bg_opa: u8,
    pub text_color: Option<u32>,
    pub border_color: Option<u32>,
    pub border_width: i32,
    pub radius: i32,
    pub outline_width: i32,
    pub outline_color: Option<u32>,
    pub outline_pad: i32,
    pub arc_color: Option<u32>,
    pub arc_width: i32,
    pub arc_rounded: bool,
    pub shadow_width: i32,
}

impl WidgetStyle {
    pub const fn plain() -> Self {
        Self {
            bg_color: None,
            bg_opa: OPA_TRANSP,
            text_color: None,
            border_color: None,
            border_width: 0,
            radius: 0,
            outline_width: 0,
            outline_color: None,
            outline_pad: 0,
            arc_color: None,
            arc_width: 0,
            arc_rounded: false,
            shadow_width: 0,
        }
    }
}
