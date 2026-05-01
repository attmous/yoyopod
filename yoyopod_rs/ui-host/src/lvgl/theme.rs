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
            shadow_width: 0,
        }
    }

    const fn root() -> Self {
        Self {
            bg_color: Some(BACKGROUND_RGB),
            bg_opa: OPA_COVER,
            text_color: Some(INK_RGB),
            border_color: None,
            border_width: 0,
            radius: 0,
            outline_width: 0,
            shadow_width: 0,
        }
    }

    const fn label(text_color: u32) -> Self {
        Self {
            text_color: Some(text_color),
            ..Self::plain()
        }
    }

    const fn panel(bg_color: u32, border_color: Option<u32>, radius: i32) -> Self {
        Self {
            bg_color: Some(bg_color),
            bg_opa: OPA_COVER,
            text_color: Some(INK_RGB),
            border_color,
            border_width: if border_color.is_some() { 1 } else { 0 },
            radius,
            outline_width: 0,
            shadow_width: 0,
        }
    }
}

pub fn style_for_role(role: &str) -> WidgetStyle {
    match role {
        "root" => WidgetStyle::root(),
        "status_bar" => WidgetStyle::plain(),
        "footer_bar" => WidgetStyle::panel(FOOTER_RGB, None, 0),
        "hub_icon_glow" => WidgetStyle::panel(SURFACE_RAISED_RGB, None, 24),
        "talk_card_glow" | "call_icon_halo" => WidgetStyle::panel(SURFACE_RAISED_RGB, None, 22),
        "hub_card_panel" | "talk_card_panel" | "call_panel" => {
            WidgetStyle::panel(SURFACE_RAISED_RGB, None, 16)
        }
        "hub_dot" => WidgetStyle {
            bg_color: Some(INK_RGB),
            bg_opa: 51,
            radius: 2,
            ..WidgetStyle::plain()
        },
        "ask_icon_glow" | "ask_icon_halo" => WidgetStyle::panel(SURFACE_RAISED_RGB, None, 60),
        "power_icon_halo" => WidgetStyle::panel(0x494D59, None, 28),
        "now_playing_panel" | "listen_panel" | "playlist_panel" => WidgetStyle::plain(),
        "now_playing_icon_halo" => WidgetStyle::panel(SURFACE_RAISED_RGB, Some(BORDER_RGB), 20),
        "now_playing_state_chip" => WidgetStyle::panel(SURFACE_RAISED_RGB, None, 12),
        "now_playing_progress_track" => WidgetStyle::panel(0x2D313A, None, 4),
        "now_playing_progress_fill" => WidgetStyle::panel(ACCENT_GREEN_RGB, None, 4),
        "listen_row" | "playlist_row" | "list_row" => {
            WidgetStyle::panel(SURFACE_RAISED_RGB, Some(BORDER_RGB), 16)
        }
        "listen_empty_panel" | "playlist_empty_panel" => WidgetStyle::panel(SURFACE_RGB, None, 22),
        "power_row" => WidgetStyle::panel(SURFACE_RAISED_RGB, None, 10),
        "playlist_underline" => WidgetStyle::panel(ACCENT_GREEN_RGB, None, 3),
        "talk_actions_header_box" => WidgetStyle::panel(SURFACE_RAISED_RGB, None, 12),
        "call_state_chip" => WidgetStyle::panel(SURFACE_RAISED_RGB, None, 12),
        "talk_actions_primary_button" => {
            WidgetStyle::panel(SURFACE_RAISED_RGB, Some(ACCENT_CYAN_RGB), 44)
        }
        "hub_title"
        | "list_title"
        | "listen_title"
        | "playlist_title"
        | "ask_title"
        | "call_title"
        | "power_title"
        | "overlay_title"
        | "now_playing_title"
        | "talk_title"
        | "listen_empty_title"
        | "playlist_empty_title" => WidgetStyle::label(INK_RGB),
        "hub_subtitle"
        | "list_subtitle"
        | "listen_subtitle"
        | "ask_subtitle"
        | "call_subtitle"
        | "call_detail"
        | "power_subtitle"
        | "overlay_subtitle"
        | "now_playing_artist"
        | "list_row_subtitle"
        | "listen_row_subtitle"
        | "playlist_row_subtitle"
        | "power_row_subtitle"
        | "talk_actions_header_name"
        | "listen_empty_subtitle"
        | "playlist_empty_subtitle" => WidgetStyle::label(MUTED_RGB),
        "status_network"
        | "status_signal"
        | "status_battery"
        | "list_footer"
        | "ask_footer"
        | "call_footer"
        | "power_footer"
        | "overlay_footer"
        | "now_playing_footer"
        | "hub_footer"
        | "listen_footer"
        | "playlist_footer"
        | "talk_footer"
        | "talk_actions_footer" => WidgetStyle::label(MUTED_DIM_RGB),
        "hub_icon"
        | "list_row_icon"
        | "listen_row_icon"
        | "playlist_row_icon"
        | "ask_icon"
        | "call_state_icon"
        | "now_playing_icon_label"
        | "now_playing_state_label"
        | "power_icon"
        | "listen_empty_icon"
        | "playlist_empty_icon"
        | "talk_card_label"
        | "talk_actions_header_label"
        | "talk_actions_button_label"
        | "talk_actions_status_label"
        | "call_state_label" => WidgetStyle::label(ACCENT_CYAN_RGB),
        "list_row_title" | "listen_row_title" | "playlist_row_title" | "power_row_title" => {
            WidgetStyle::label(INK_RGB)
        }
        "now_playing_progress" => WidgetStyle::label(ACCENT_GREEN_RGB),
        "call_mute_badge" => WidgetStyle::panel(0x49353B, None, 12),
        "call_mute_label" => WidgetStyle::label(ERROR_RGB),
        _ => WidgetStyle::label(INK_RGB),
    }
}

pub fn style_for_selected_role(role: &str, selected: bool) -> WidgetStyle {
    if !selected {
        return style_for_role(role);
    }

    match role {
        "listen_row" | "playlist_row" | "list_row" => {
            WidgetStyle::panel(SELECTED_ROW_RGB, Some(SELECTED_ROW_RGB), 16)
        }
        "hub_dot" => WidgetStyle {
            bg_color: Some(INK_RGB),
            bg_opa: OPA_COVER,
            radius: 2,
            ..WidgetStyle::plain()
        },
        "listen_row_title" | "playlist_row_title" | "list_row_title" => {
            WidgetStyle::label(BACKGROUND_RGB)
        }
        "listen_row_subtitle" | "playlist_row_subtitle" | "list_row_subtitle" => {
            WidgetStyle::label(MUTED_DIM_RGB)
        }
        _ => style_for_role(role),
    }
}
