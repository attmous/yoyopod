#include "lvgl.h"
#include "lvgl_shim.h"
#include "hub_icon_assets.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#define KEY_QUEUE_CAPACITY 32
#define YOYOPOD_POWER_MAX_DOTS 8
#define YOYOPOD_POWER_MAX_ITEMS 5

typedef struct {
    int32_t key;
    int32_t pressed;
} yoyopod_key_event_t;

typedef struct {
    lv_obj_t * signal_bars[4];
    lv_obj_t * wifi_label;
    lv_obj_t * gps_ring;
    lv_obj_t * gps_center;
    lv_obj_t * gps_tail;
    lv_obj_t * voip_dot;
    lv_obj_t * time_label;
    lv_obj_t * battery_outline;
    lv_obj_t * battery_fill;
    lv_obj_t * battery_tip;
    lv_obj_t * battery_label;
} yoyopod_status_bar_t;

typedef struct {
    int32_t network_enabled;
    int32_t network_connected;
    int32_t wifi_connected;
    int32_t signal_strength;
    int32_t gps_has_fix;
} yoyopod_status_bar_state_t;

static const uint32_t YOYOPOD_THEME_BACKGROUND_RGB = 0x2A2D35;
static const uint32_t YOYOPOD_THEME_SURFACE_RGB = 0x31343C;
static const uint32_t YOYOPOD_THEME_SURFACE_RAISED_RGB = 0x363A44;
static const uint32_t YOYOPOD_THEME_FOOTER_RGB = 0x1F2127;
static const uint32_t YOYOPOD_THEME_INK_RGB = 0xFFFFFF;
static const uint32_t YOYOPOD_THEME_MUTED_RGB = 0xB4B7BE;
static const uint32_t YOYOPOD_THEME_MUTED_DIM_RGB = 0x7A7D84;
static const uint32_t YOYOPOD_THEME_BORDER_RGB = 0x505561;
static const uint32_t YOYOPOD_THEME_SUCCESS_RGB = 0x3DDD53;
static const uint32_t YOYOPOD_THEME_WARNING_RGB = 0xFFD549;
static const uint32_t YOYOPOD_THEME_ERROR_RGB = 0xFF675D;
static const uint32_t YOYOPOD_THEME_NEUTRAL_RGB = 0x9CA3AF;
static const uint32_t YOYOPOD_MODE_LISTEN_RGB = 0x00FF88;
static const uint32_t YOYOPOD_MODE_TALK_RGB = 0x00D4FF;
static const int YOYOPOD_STATUS_SIGNAL_BAR_HEIGHTS[4] = {4, 7, 10, 13};
static yoyopod_status_bar_state_t g_status_bar_state = {0, 0, 0, 0, 0};

typedef struct {
    int built;
    lv_obj_t * screen;
    yoyopod_status_bar_t status_bar;
    lv_obj_t * icon_glow;
    lv_obj_t * card_panel;
    lv_obj_t * icon_image;
    lv_obj_t * title_label;
    lv_obj_t * subtitle_label;
    lv_obj_t * footer_bar;
    lv_obj_t * footer_label;
    lv_obj_t * dots[4];
} yoyopod_hub_scene_t;

typedef struct {
    int built;
    lv_obj_t * screen;
    yoyopod_status_bar_t status_bar;
    lv_obj_t * card_glow;
    lv_obj_t * card_panel;
    lv_obj_t * card_label;
    lv_obj_t * title_label;
    lv_obj_t * footer_label;
    lv_obj_t * dots[4];
} yoyopod_talk_scene_t;

typedef struct {
    int built;
    lv_obj_t * screen;
    yoyopod_status_bar_t status_bar;
    lv_obj_t * header_box;
    lv_obj_t * header_label;
    lv_obj_t * header_name_label;
    lv_obj_t * buttons[3];
    lv_obj_t * button_labels[3];
    lv_obj_t * title_label;
    lv_obj_t * status_label;
    lv_obj_t * footer_label;
    lv_obj_t * dots[3];
} yoyopod_talk_actions_scene_t;

typedef struct {
    int built;
    lv_obj_t * screen;
    yoyopod_status_bar_t status_bar;
    lv_obj_t * title_label;
    lv_obj_t * subtitle_label;
    lv_obj_t * panel;
    lv_obj_t * item_panels[4];
    lv_obj_t * item_icons[4];
    lv_obj_t * item_titles[4];
    lv_obj_t * item_subtitles[4];
    lv_obj_t * empty_panel;
    lv_obj_t * empty_icon;
    lv_obj_t * empty_title;
    lv_obj_t * empty_subtitle;
    lv_obj_t * footer_label;
} yoyopod_listen_scene_t;

typedef struct {
    int built;
    lv_obj_t * screen;
    yoyopod_status_bar_t status_bar;
    lv_obj_t * title_label;
    lv_obj_t * title_underline;
    lv_obj_t * page_label;
    lv_obj_t * status_chip;
    lv_obj_t * status_chip_label;
    lv_obj_t * panel;
    lv_obj_t * item_panels[4];
    lv_obj_t * item_icons[4];
    lv_obj_t * item_titles[4];
    lv_obj_t * item_subtitles[4];
    lv_obj_t * item_badges[4];
    lv_obj_t * empty_panel;
    lv_obj_t * empty_icon;
    lv_obj_t * empty_title;
    lv_obj_t * empty_subtitle;
    lv_obj_t * footer_label;
} yoyopod_playlist_scene_t;

typedef struct {
    int built;
    lv_obj_t * screen;
    yoyopod_status_bar_t status_bar;
    lv_obj_t * panel;
    lv_obj_t * icon_halo;
    lv_obj_t * icon_label;
    lv_obj_t * state_chip;
    lv_obj_t * state_label;
    lv_obj_t * title_label;
    lv_obj_t * artist_label;
    lv_obj_t * progress_track;
    lv_obj_t * progress_fill;
    lv_obj_t * footer_label;
} yoyopod_now_playing_scene_t;

typedef struct {
    int built;
    lv_obj_t * screen;
    yoyopod_status_bar_t status_bar;
    lv_obj_t * panel;
    lv_obj_t * icon_halo;
    lv_obj_t * icon_label;
    lv_obj_t * state_chip;
    lv_obj_t * state_label;
    lv_obj_t * caller_name_label;
    lv_obj_t * caller_address_label;
    lv_obj_t * footer_label;
} yoyopod_incoming_call_scene_t;

typedef struct {
    int built;
    lv_obj_t * screen;
    yoyopod_status_bar_t status_bar;
    lv_obj_t * panel;
    lv_obj_t * icon_halo;
    lv_obj_t * icon_label;
    lv_obj_t * state_chip;
    lv_obj_t * state_label;
    lv_obj_t * callee_name_label;
    lv_obj_t * callee_address_label;
    lv_obj_t * footer_label;
} yoyopod_outgoing_call_scene_t;

typedef struct {
    int built;
    lv_obj_t * screen;
    yoyopod_status_bar_t status_bar;
    lv_obj_t * panel;
    lv_obj_t * icon_halo;
    lv_obj_t * icon_label;
    lv_obj_t * caller_name_label;
    lv_obj_t * state_chip;
    lv_obj_t * duration_label;
    lv_obj_t * mute_chip;
    lv_obj_t * mute_label;
    lv_obj_t * footer_label;
} yoyopod_in_call_scene_t;

typedef struct {
    int built;
    lv_obj_t * screen;
    yoyopod_status_bar_t status_bar;
    lv_obj_t * icon_glow;
    lv_obj_t * icon_halo;
    lv_obj_t * icon_image;
    lv_obj_t * title_label;
    lv_obj_t * subtitle_label;
    lv_obj_t * footer_label;
} yoyopod_ask_scene_t;

typedef struct {
    int built;
    lv_obj_t * screen;
    yoyopod_status_bar_t status_bar;
    lv_obj_t * icon_halo;
    lv_obj_t * icon_label;
    lv_obj_t * title_label;
    lv_obj_t * item_panels[YOYOPOD_POWER_MAX_ITEMS];
    lv_obj_t * item_titles[YOYOPOD_POWER_MAX_ITEMS];
    lv_obj_t * dots[YOYOPOD_POWER_MAX_DOTS];
    lv_obj_t * footer_label;
} yoyopod_power_scene_t;

static int g_initialized = 0;
static lv_display_t * g_display = NULL;
static lv_indev_t * g_indev = NULL;
static lv_group_t * g_group = NULL;
static lv_color_t * g_draw_buf = NULL;
static uint32_t g_draw_buf_bytes = 0;
static lv_obj_t * g_blank_screen = NULL;
static yoyopod_lvgl_flush_cb_t g_flush_cb = NULL;
static void * g_flush_user_data = NULL;
static char g_last_error[256] = "";
static yoyopod_key_event_t g_key_queue[KEY_QUEUE_CAPACITY];
static int g_key_head = 0;
static int g_key_tail = 0;
static int g_key_count = 0;
static yoyopod_hub_scene_t g_hub_scene = {0};
static yoyopod_talk_scene_t g_talk_scene = {0};
static yoyopod_talk_actions_scene_t g_talk_actions_scene = {0};
static yoyopod_listen_scene_t g_listen_scene = {0};
static yoyopod_playlist_scene_t g_playlist_scene = {0};
static yoyopod_now_playing_scene_t g_now_playing_scene = {0};
static yoyopod_incoming_call_scene_t g_incoming_call_scene = {0};
static yoyopod_outgoing_call_scene_t g_outgoing_call_scene = {0};
static yoyopod_in_call_scene_t g_in_call_scene = {0};
static yoyopod_ask_scene_t g_ask_scene = {0};
static yoyopod_power_scene_t g_power_scene = {0};

static uint8_t yoyopod_rgb_red(uint32_t rgb) {
    return (uint8_t)((rgb >> 16) & 0xFFU);
}

static uint8_t yoyopod_rgb_green(uint32_t rgb) {
    return (uint8_t)((rgb >> 8) & 0xFFU);
}

static uint8_t yoyopod_rgb_blue(uint32_t rgb) {
    return (uint8_t)(rgb & 0xFFU);
}

static lv_color_t yoyopod_color_u24(uint32_t rgb) {
    return lv_color_hex(rgb & 0xFFFFFFU);
}

static lv_color_t yoyopod_color_rgb(uint8_t red, uint8_t green, uint8_t blue) {
    uint32_t raw = ((uint32_t)red << 16) | ((uint32_t)green << 8) | (uint32_t)blue;
    return lv_color_hex(raw);
}

static lv_color_t yoyopod_mix_rgb(
    uint8_t primary_red,
    uint8_t primary_green,
    uint8_t primary_blue,
    uint8_t secondary_red,
    uint8_t secondary_green,
    uint8_t secondary_blue,
    uint8_t secondary_ratio_percent
) {
    uint8_t primary_ratio = (uint8_t)(100U - secondary_ratio_percent);
    uint8_t mixed_red = (uint8_t)(((uint16_t)primary_red * primary_ratio + (uint16_t)secondary_red * secondary_ratio_percent) / 100U);
    uint8_t mixed_green = (uint8_t)(((uint16_t)primary_green * primary_ratio + (uint16_t)secondary_green * secondary_ratio_percent) / 100U);
    uint8_t mixed_blue = (uint8_t)(((uint16_t)primary_blue * primary_ratio + (uint16_t)secondary_blue * secondary_ratio_percent) / 100U);
    return yoyopod_color_rgb(mixed_red, mixed_green, mixed_blue);
}

static lv_color_t yoyopod_mix_u24(uint32_t primary_rgb, uint32_t secondary_rgb, uint8_t secondary_ratio_percent) {
    return yoyopod_mix_rgb(
        yoyopod_rgb_red(primary_rgb),
        yoyopod_rgb_green(primary_rgb),
        yoyopod_rgb_blue(primary_rgb),
        yoyopod_rgb_red(secondary_rgb),
        yoyopod_rgb_green(secondary_rgb),
        yoyopod_rgb_blue(secondary_rgb),
        secondary_ratio_percent
    );
}

static void yoyopod_reset_hub_scene_refs(void) {
    memset(&g_hub_scene, 0, sizeof(g_hub_scene));
}

static void yoyopod_reset_talk_scene_refs(void) {
    memset(&g_talk_scene, 0, sizeof(g_talk_scene));
}

static void yoyopod_reset_talk_actions_scene_refs(void) {
    memset(&g_talk_actions_scene, 0, sizeof(g_talk_actions_scene));
}

static void yoyopod_reset_listen_scene_refs(void) {
    memset(&g_listen_scene, 0, sizeof(g_listen_scene));
}

static void yoyopod_reset_playlist_scene_refs(void) {
    memset(&g_playlist_scene, 0, sizeof(g_playlist_scene));
}

static void yoyopod_reset_now_playing_scene_refs(void) {
    memset(&g_now_playing_scene, 0, sizeof(g_now_playing_scene));
}

static void yoyopod_reset_incoming_call_scene_refs(void) {
    memset(&g_incoming_call_scene, 0, sizeof(g_incoming_call_scene));
}

static void yoyopod_reset_outgoing_call_scene_refs(void) {
    memset(&g_outgoing_call_scene, 0, sizeof(g_outgoing_call_scene));
}

static void yoyopod_reset_in_call_scene_refs(void) {
    memset(&g_in_call_scene, 0, sizeof(g_in_call_scene));
}

static void yoyopod_reset_ask_scene_refs(void) {
    memset(&g_ask_scene, 0, sizeof(g_ask_scene));
}

static void yoyopod_reset_power_scene_refs(void) {
    memset(&g_power_scene, 0, sizeof(g_power_scene));
}

static void yoyopod_reset_scene_refs(void) {
    yoyopod_reset_hub_scene_refs();
    yoyopod_reset_talk_scene_refs();
    yoyopod_reset_talk_actions_scene_refs();
    yoyopod_reset_listen_scene_refs();
    yoyopod_reset_playlist_scene_refs();
    yoyopod_reset_now_playing_scene_refs();
    yoyopod_reset_incoming_call_scene_refs();
    yoyopod_reset_outgoing_call_scene_refs();
    yoyopod_reset_in_call_scene_refs();
    yoyopod_reset_ask_scene_refs();
    yoyopod_reset_power_scene_refs();
}

static void yoyopod_set_error(const char * message) {
    if(message == NULL) {
        g_last_error[0] = '\0';
        return;
    }

    strncpy(g_last_error, message, sizeof(g_last_error) - 1);
    g_last_error[sizeof(g_last_error) - 1] = '\0';
}

static int yoyopod_translate_key(int32_t key) {
    switch(key) {
        case YOYOPOD_LVGL_KEY_RIGHT:
            return LV_KEY_RIGHT;
        case YOYOPOD_LVGL_KEY_ENTER:
            return LV_KEY_ENTER;
        case YOYOPOD_LVGL_KEY_ESC:
            return LV_KEY_ESC;
        default:
            return 0;
    }
}

static void yoyopod_flush_cb(lv_display_t * disp, const lv_area_t * area, uint8_t * px_map) {
    int32_t width = lv_area_get_width(area);
    int32_t height = lv_area_get_height(area);
    uint32_t bytes_per_pixel = lv_color_format_get_size(lv_display_get_color_format(disp));
    uint32_t byte_length = (uint32_t)(width * height * bytes_per_pixel);

    if(g_flush_cb != NULL) {
        g_flush_cb(
            area->x1,
            area->y1,
            width,
            height,
            (const unsigned char *)px_map,
            byte_length,
            g_flush_user_data
        );
    }

    lv_display_flush_ready(disp);
}

static void yoyopod_indev_read_cb(lv_indev_t * indev, lv_indev_data_t * data) {
    (void)indev;

    if(g_key_count == 0) {
        data->state = LV_INDEV_STATE_RELEASED;
        data->key = 0;
        data->continue_reading = 0;
        return;
    }

    yoyopod_key_event_t event = g_key_queue[g_key_head];
    g_key_head = (g_key_head + 1) % KEY_QUEUE_CAPACITY;
    g_key_count--;

    data->key = yoyopod_translate_key(event.key);
    data->state = event.pressed ? LV_INDEV_STATE_PRESSED : LV_INDEV_STATE_RELEASED;
    data->continue_reading = g_key_count > 0 ? 1 : 0;
}

static void yoyopod_clear_group(void) {
    if(g_group != NULL) {
        lv_group_remove_all_objs(g_group);
    }
}

static void yoyopod_prepare_active_screen(void) {
    lv_obj_t * screen = lv_screen_active();
    lv_obj_clean(screen);
    yoyopod_clear_group();
    yoyopod_reset_scene_refs();
}

static int yoyopod_require_scene_screen(lv_obj_t * screen, const char * error_message) {
    if(screen != NULL) {
        return 0;
    }

    yoyopod_set_error(error_message);
    return -1;
}

static lv_obj_t * yoyopod_ensure_blank_screen(void) {
    if(g_blank_screen == NULL) {
        g_blank_screen = lv_obj_create(NULL);
        if(g_blank_screen == NULL) {
            yoyopod_set_error("lv_obj_create(NULL) failed for blank scene");
            return NULL;
        }
    }

    lv_obj_set_style_bg_color(g_blank_screen, yoyopod_color_u24(YOYOPOD_THEME_BACKGROUND_RGB), 0);
    lv_obj_set_style_bg_opa(g_blank_screen, LV_OPA_COVER, 0);
    return g_blank_screen;
}

static void yoyopod_release_scene_screen(lv_obj_t * screen) {
    if(screen == NULL || screen == g_blank_screen) {
        return;
    }

    if(lv_screen_active() == screen) {
        lv_obj_t * blank_screen = yoyopod_ensure_blank_screen();
        if(blank_screen == NULL) {
            return;
        }

        yoyopod_clear_group();
        if(blank_screen != lv_screen_active()) {
            lv_screen_load(blank_screen);
        }
    }

    lv_obj_delete(screen);
}

static int yoyopod_activate_scene_screen(lv_obj_t * screen, const char * error_message) {
    if(yoyopod_require_scene_screen(screen, error_message) != 0) {
        return -1;
    }

    if(screen != lv_screen_active()) {
        yoyopod_clear_group();
        lv_screen_load(screen);
    }

    return 0;
}

static lv_obj_t * yoyopod_create_card(lv_obj_t * screen, const char * title, const char * subtitle, lv_color_t accent) {
    lv_obj_t * panel = lv_obj_create(screen);
    lv_obj_set_size(panel, 200, 190);
    lv_obj_align(panel, LV_ALIGN_CENTER, 0, 8);
    lv_obj_set_style_radius(panel, 24, 0);
    lv_obj_set_style_border_width(panel, 2, 0);
    lv_obj_set_style_border_color(panel, accent, 0);
    lv_obj_set_style_bg_color(panel, yoyopod_color_u24(YOYOPOD_THEME_SURFACE_RGB), 0);
    lv_obj_set_style_bg_opa(panel, LV_OPA_COVER, 0);
    lv_obj_set_style_pad_all(panel, 16, 0);
    lv_obj_set_layout(panel, LV_LAYOUT_FLEX);
    lv_obj_set_flex_flow(panel, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_flex_align(panel, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);

    lv_obj_t * icon = lv_obj_create(panel);
    lv_obj_set_size(icon, 72, 72);
    lv_obj_set_style_radius(icon, 20, 0);
    lv_obj_set_style_bg_color(icon, accent, 0);
    lv_obj_set_style_bg_opa(icon, LV_OPA_20, 0);
    lv_obj_set_style_border_width(icon, 2, 0);
    lv_obj_set_style_border_color(icon, accent, 0);

    lv_obj_t * title_label = lv_label_create(panel);
    lv_label_set_text(title_label, title);
    lv_obj_set_style_text_font(title_label, &lv_font_montserrat_24, 0);
    lv_obj_set_style_text_color(title_label, yoyopod_color_u24(YOYOPOD_THEME_INK_RGB), 0);

    lv_obj_t * subtitle_label = lv_label_create(panel);
    lv_label_set_text(subtitle_label, subtitle);
    lv_obj_set_style_text_font(subtitle_label, &lv_font_montserrat_16, 0);
    lv_obj_set_style_text_color(subtitle_label, accent, 0);

    return panel;
}

static void yoyopod_build_card_scene(void) {
    lv_obj_t * screen = lv_screen_active();
    yoyopod_prepare_active_screen();
    yoyopod_create_card(
        screen,
        "Listen",
        "LVGL card proof",
        yoyopod_color_u24(YOYOPOD_MODE_LISTEN_RGB)
    );
}

static void yoyopod_build_list_scene(void) {
    lv_obj_t * screen = lv_screen_active();
    yoyopod_prepare_active_screen();

    lv_obj_t * list = lv_list_create(screen);
    lv_obj_set_size(list, 208, 210);
    lv_obj_align(list, LV_ALIGN_CENTER, 0, 8);
    lv_obj_set_style_radius(list, 22, 0);
    lv_obj_set_style_bg_color(list, yoyopod_color_u24(YOYOPOD_THEME_SURFACE_RGB), 0);
    lv_obj_set_style_border_color(list, yoyopod_color_u24(YOYOPOD_THEME_BORDER_RGB), 0);
    lv_obj_set_style_border_width(list, 2, 0);

    lv_obj_t * button = NULL;

    button = lv_list_add_button(list, NULL, "Playlists");
    if(g_group != NULL) lv_group_add_obj(g_group, button);

    button = lv_list_add_button(list, NULL, "Recent");
    if(g_group != NULL) lv_group_add_obj(g_group, button);

    button = lv_list_add_button(list, NULL, "Shuffle");
    if(g_group != NULL) lv_group_add_obj(g_group, button);

    button = lv_list_add_button(list, NULL, "Local Files");
    if(g_group != NULL) lv_group_add_obj(g_group, button);
}

static void yoyopod_build_footer_scene(void) {
    lv_obj_t * screen = lv_screen_active();
    yoyopod_prepare_active_screen();

    lv_obj_t * label = lv_label_create(screen);
    lv_label_set_text(label, "Tap next / Double open / Hold back");
    lv_obj_align(label, LV_ALIGN_BOTTOM_MID, 0, -10);
    lv_obj_set_style_text_font(label, &lv_font_montserrat_14, 0);
    lv_obj_set_style_text_color(label, yoyopod_color_u24(YOYOPOD_THEME_INK_RGB), 0);
}

static void yoyopod_build_carousel_scene(void) {
    lv_obj_t * screen = lv_screen_active();
    yoyopod_prepare_active_screen();
    yoyopod_create_card(
        screen,
        "Talk",
        "Carousel proof",
        yoyopod_color_u24(YOYOPOD_MODE_TALK_RGB)
    );

    lv_obj_t * footer = lv_label_create(screen);
    lv_label_set_text(footer, "Tap next / Open");
    lv_obj_align(footer, LV_ALIGN_BOTTOM_MID, 0, -10);
    lv_obj_set_style_text_font(footer, &lv_font_montserrat_14, 0);
    lv_obj_set_style_text_color(footer, yoyopod_color_u24(YOYOPOD_THEME_INK_RGB), 0);
}

static void yoyopod_apply_voip_dot(lv_obj_t * dot, int32_t voip_state) {
    const lv_color_t success = yoyopod_color_u24(YOYOPOD_THEME_SUCCESS_RGB);
    const lv_color_t error = yoyopod_color_u24(YOYOPOD_THEME_ERROR_RGB);

    if(voip_state == 0) {
        lv_obj_add_flag(dot, LV_OBJ_FLAG_HIDDEN);
        return;
    }

    lv_obj_clear_flag(dot, LV_OBJ_FLAG_HIDDEN);
    lv_obj_set_style_bg_color(dot, voip_state == 1 ? success : error, 0);
    lv_obj_set_style_bg_opa(dot, LV_OPA_COVER, 0);
}

static void yoyopod_apply_battery(
    lv_obj_t * outline,
    lv_obj_t * fill,
    lv_obj_t * tip,
    int32_t battery_percent,
    int32_t charging,
    int32_t power_available
) {
    const lv_color_t muted = yoyopod_color_u24(YOYOPOD_THEME_MUTED_RGB);
    const lv_color_t ink = yoyopod_color_u24(YOYOPOD_THEME_INK_RGB);
    const lv_color_t success = yoyopod_color_u24(YOYOPOD_THEME_SUCCESS_RGB);
    const lv_color_t error = yoyopod_color_u24(YOYOPOD_THEME_ERROR_RGB);

    if(battery_percent < 0) {
        battery_percent = 0;
    }
    if(battery_percent > 100) {
        battery_percent = 100;
    }

    lv_obj_set_style_border_color(outline, muted, 0);
    lv_obj_set_style_bg_color(tip, muted, 0);

    int fill_width = (battery_percent * 12) / 100;
    lv_color_t fill_color = muted;
    if(power_available) {
        if(battery_percent <= 20) {
            fill_color = error;
        } else if(charging) {
            fill_color = success;
        } else {
            fill_color = ink;
        }
    }

    lv_obj_set_size(fill, fill_width, 6);
    lv_obj_set_style_bg_color(fill, fill_color, 0);
    if(fill_width <= 0) {
        lv_obj_add_flag(fill, LV_OBJ_FLAG_HIDDEN);
    } else {
        lv_obj_clear_flag(fill, LV_OBJ_FLAG_HIDDEN);
    }
}

static const char * yoyopod_time_or_default(const char * time_text) {
    static char time_buffer[6];
    if(time_text != NULL && time_text[0] != '\0') {
        return time_text;
    }

    time_t now = time(NULL);
    struct tm * local_now = localtime(&now);
    if(local_now == NULL) {
        return "";
    }
    strftime(time_buffer, sizeof(time_buffer), "%H:%M", local_now);
    return time_buffer;
}

static void yoyopod_make_monogram(const char * text, char output[3]) {
    output[0] = '?';
    output[1] = '\0';
    output[2] = '\0';
    if(text == NULL || text[0] == '\0') {
        return;
    }

    int first_index = -1;
    int second_index = -1;
    int in_word = 0;
    for(int index = 0; text[index] != '\0'; ++index) {
        char current = text[index];
        int is_space = current == ' ' || current == '-' || current == '_' || current == '\t';
        if(is_space) {
            in_word = 0;
            continue;
        }
        if(!in_word) {
            if(first_index < 0) {
                first_index = index;
            } else if(second_index < 0) {
                second_index = index;
                break;
            }
            in_word = 1;
        }
    }

    if(first_index < 0) {
        return;
    }

    output[0] = text[first_index];
    output[1] = '\0';
    if(second_index >= 0) {
        output[1] = text[second_index];
        output[2] = '\0';
    } else if(text[first_index + 1] != '\0' && text[first_index + 1] != ' ') {
        output[1] = text[first_index + 1];
        output[2] = '\0';
    }
}

static const char * yoyopod_symbol_for_empty_icon(const char * icon_key) {
    if(icon_key == NULL) {
        return LV_SYMBOL_LIST;
    }
    if(strncmp(icon_key, "mono:", 5) == 0 && icon_key[5] != '\0') {
        return icon_key + 5;
    }

    if(strcmp(icon_key, "playlist") == 0) {
        return LV_SYMBOL_LIST;
    }
    if(strcmp(icon_key, "listen") == 0) {
        return LV_SYMBOL_AUDIO;
    }
    if(strcmp(icon_key, "music_note") == 0) {
        return LV_SYMBOL_AUDIO;
    }
    if(strcmp(icon_key, "talk") == 0) {
        return LV_SYMBOL_CALL;
    }
    if(strcmp(icon_key, "call") == 0) {
        return LV_SYMBOL_CALL;
    }
    if(strcmp(icon_key, "ask") == 0) {
        return "AI";
    }
    if(strcmp(icon_key, "voice_note") == 0) {
        return LV_SYMBOL_EDIT;
    }
    if(strcmp(icon_key, "people") == 0) {
        return LV_SYMBOL_LIST;
    }
    if(strcmp(icon_key, "play") == 0) {
        return LV_SYMBOL_AUDIO;
    }
    if(strcmp(icon_key, "retry") == 0) {
        return LV_SYMBOL_REFRESH;
    }
    if(strcmp(icon_key, "close") == 0) {
        return LV_SYMBOL_CLOSE;
    }
    if(strcmp(icon_key, "check") == 0) {
        return LV_SYMBOL_OK;
    }
    if(strcmp(icon_key, "mic_off") == 0) {
        return "X";
    }
    if(strcmp(icon_key, "clock") == 0) {
        return LV_SYMBOL_REFRESH;
    }
    if(strcmp(icon_key, "battery") == 0) {
        return LV_SYMBOL_POWER;
    }
    if(strcmp(icon_key, "signal") == 0) {
        return LV_SYMBOL_WIFI;
    }
    if(strcmp(icon_key, "care") == 0) {
        return LV_SYMBOL_SETTINGS;
    }
    if(strcmp(icon_key, "setup") == 0 || strcmp(icon_key, "power") == 0) {
        return LV_SYMBOL_SETTINGS;
    }

    return LV_SYMBOL_LIST;
}

static const lv_image_dsc_t * yoyopod_hub_icon_for_key(const char * icon_key) {
    if(icon_key == NULL) {
        return &yoyopod_hub_icon_setup;
    }

    if(strcmp(icon_key, "listen") == 0) {
        return &yoyopod_hub_icon_listen;
    }
    if(strcmp(icon_key, "talk") == 0) {
        return &yoyopod_hub_icon_talk;
    }
    if(strcmp(icon_key, "ask") == 0) {
        return &yoyopod_hub_icon_ask;
    }
    if(strcmp(icon_key, "setup") == 0 || strcmp(icon_key, "power") == 0) {
        return &yoyopod_hub_icon_setup;
    }

    return &yoyopod_hub_icon_setup;
}

static void yoyopod_hub_style_dot(lv_obj_t * dot, lv_color_t color, int selected) {
    lv_obj_set_size(dot, 4, 4);
    lv_obj_set_style_radius(dot, LV_RADIUS_CIRCLE, 0);
    lv_obj_set_style_bg_color(dot, color, 0);
    lv_obj_set_style_bg_opa(dot, selected ? LV_OPA_COVER : LV_OPA_20, 0);
    lv_obj_set_style_border_width(dot, 0, 0);
}

static lv_color_t yoyopod_color_for_kind(int32_t color_kind, uint32_t accent_rgb) {
    if(color_kind == 1) {
        return yoyopod_color_u24(YOYOPOD_THEME_SUCCESS_RGB);
    }
    if(color_kind == 2) {
        return yoyopod_color_u24(YOYOPOD_THEME_WARNING_RGB);
    }
    if(color_kind == 3) {
        return yoyopod_color_u24(YOYOPOD_THEME_ERROR_RGB);
    }
    if(color_kind == 4) {
        return yoyopod_color_u24(YOYOPOD_THEME_MUTED_RGB);
    }
    return yoyopod_color_u24(accent_rgb);
}

#define YOYOPOD_STATUS_LEFT_INSET 16
#define YOYOPOD_STATUS_ICON_BOTTOM_Y 20
#define YOYOPOD_STATUS_TIME_Y 8
#define YOYOPOD_STATUS_TIME_WIDTH 64
#define YOYOPOD_STATUS_CLUSTER_GAP 6
#define YOYOPOD_STATUS_SIGNAL_BAR_WIDTH 3
#define YOYOPOD_STATUS_SIGNAL_BAR_GAP 1
#define YOYOPOD_STATUS_WIFI_WIDTH 12
#define YOYOPOD_STATUS_GPS_WIDTH 8
#define YOYOPOD_STATUS_GPS_HEIGHT 12
#define YOYOPOD_STATUS_VOIP_SIZE 6
#define YOYOPOD_STATUS_BATTERY_X 172
#define YOYOPOD_STATUS_BATTERY_Y 11
#define YOYOPOD_STATUS_BATTERY_TIP_X 186
#define YOYOPOD_STATUS_BATTERY_TIP_Y 14
#define YOYOPOD_STATUS_BATTERY_LABEL_X 196
#define YOYOPOD_STATUS_BATTERY_LABEL_Y 8
#define YOYOPOD_FOOTER_BAR_HEIGHT 32
#define YOYOPOD_FOOTER_BAR_TOP 248
#define YOYOPOD_FOOTER_WIDTH 214
#define YOYOPOD_FOOTER_OFFSET_Y -8

static void yoyopod_build_footer_bar(lv_obj_t * parent) {
    lv_obj_t * bar = lv_obj_create(parent);
    lv_obj_remove_style_all(bar);
    lv_obj_set_size(bar, 240, YOYOPOD_FOOTER_BAR_HEIGHT);
    lv_obj_set_pos(bar, 0, YOYOPOD_FOOTER_BAR_TOP);
    lv_obj_set_style_bg_color(bar, yoyopod_color_u24(YOYOPOD_THEME_FOOTER_RGB), 0);
    lv_obj_set_style_bg_opa(bar, LV_OPA_COVER, 0);
    lv_obj_set_scrollbar_mode(bar, LV_SCROLLBAR_MODE_OFF);
}

static void yoyopod_prepare_footer_label(lv_obj_t * label) {
    lv_obj_set_width(label, YOYOPOD_FOOTER_WIDTH);
    lv_label_set_long_mode(label, LV_LABEL_LONG_MODE_CLIP);
    lv_obj_set_style_text_font(label, &lv_font_montserrat_12, 0);
    lv_obj_set_style_text_align(label, LV_TEXT_ALIGN_CENTER, 0);
    lv_obj_align(label, LV_ALIGN_BOTTOM_MID, 0, YOYOPOD_FOOTER_OFFSET_Y);
}

static void yoyopod_apply_footer_label(lv_obj_t * label, const char * text, lv_color_t color) {
    lv_label_set_text(label, text != NULL ? text : "");
    lv_obj_set_style_text_color(label, color, 0);
    lv_obj_align(label, LV_ALIGN_BOTTOM_MID, 0, YOYOPOD_FOOTER_OFFSET_Y);
}

static void yoyopod_apply_signal_bars(
    yoyopod_status_bar_t * bar,
    int32_t network_enabled,
    int32_t network_connected,
    int32_t signal_strength,
    int32_t start_x
) {
    lv_color_t active_color = yoyopod_color_u24(
        network_connected ? YOYOPOD_THEME_SUCCESS_RGB : YOYOPOD_THEME_MUTED_RGB
    );
    lv_color_t inactive_color = yoyopod_color_u24(0x3C3F46);

    for(int index = 0; index < 4; index++) {
        lv_obj_t * signal_bar = bar->signal_bars[index];
        if(signal_bar == NULL) {
            continue;
        }

        if(!network_enabled) {
            lv_obj_add_flag(signal_bar, LV_OBJ_FLAG_HIDDEN);
            continue;
        }

        int height = YOYOPOD_STATUS_SIGNAL_BAR_HEIGHTS[index];
        lv_obj_set_size(signal_bar, YOYOPOD_STATUS_SIGNAL_BAR_WIDTH, height);
        lv_obj_set_pos(
            signal_bar,
            start_x + (index * (YOYOPOD_STATUS_SIGNAL_BAR_WIDTH + YOYOPOD_STATUS_SIGNAL_BAR_GAP)),
            YOYOPOD_STATUS_ICON_BOTTOM_Y - height + 1
        );
        lv_obj_set_style_bg_color(
            signal_bar,
            index < signal_strength ? active_color : inactive_color,
            0
        );
        lv_obj_clear_flag(signal_bar, LV_OBJ_FLAG_HIDDEN);
    }
}

static int32_t yoyopod_status_top_for_height(int32_t height) {
    return YOYOPOD_STATUS_ICON_BOTTOM_Y - height + 1;
}

static int32_t yoyopod_apply_wifi_icon(
    yoyopod_status_bar_t * bar,
    int32_t wifi_connected,
    int32_t start_x
) {
    if(bar->wifi_label == NULL) {
        return start_x;
    }

    if(!wifi_connected) {
        lv_obj_add_flag(bar->wifi_label, LV_OBJ_FLAG_HIDDEN);
        return start_x;
    }

    lv_obj_clear_flag(bar->wifi_label, LV_OBJ_FLAG_HIDDEN);
    lv_obj_update_layout(bar->wifi_label);
    int32_t label_height = lv_obj_get_height(bar->wifi_label);
    if(label_height <= 0) {
        label_height = 10;
    }
    lv_obj_set_pos(
        bar->wifi_label,
        start_x,
        yoyopod_status_top_for_height(label_height)
    );
    lv_obj_set_style_text_color(bar->wifi_label, yoyopod_color_u24(YOYOPOD_THEME_SUCCESS_RGB), 0);
    return start_x + YOYOPOD_STATUS_WIFI_WIDTH + YOYOPOD_STATUS_CLUSTER_GAP;
}

static int32_t yoyopod_apply_gps_icon(
    yoyopod_status_bar_t * bar,
    int32_t network_enabled,
    int32_t gps_has_fix,
    int32_t start_x
) {
    if(bar->gps_ring == NULL || bar->gps_center == NULL || bar->gps_tail == NULL) {
        return start_x;
    }

    if(!network_enabled) {
        lv_obj_add_flag(bar->gps_ring, LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag(bar->gps_center, LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag(bar->gps_tail, LV_OBJ_FLAG_HIDDEN);
        return start_x;
    }

    lv_color_t color = yoyopod_color_u24(gps_has_fix ? YOYOPOD_THEME_SUCCESS_RGB : YOYOPOD_THEME_MUTED_RGB);
    int32_t icon_top = yoyopod_status_top_for_height(YOYOPOD_STATUS_GPS_HEIGHT);
    lv_obj_set_pos(bar->gps_ring, start_x, icon_top);
    lv_obj_set_pos(bar->gps_center, start_x + 3, icon_top + 3);
    lv_obj_set_pos(bar->gps_tail, start_x + 3, icon_top + 7);
    lv_obj_set_style_border_color(bar->gps_ring, color, 0);
    lv_obj_set_style_bg_color(bar->gps_center, color, 0);
    lv_obj_set_style_bg_color(bar->gps_tail, color, 0);
    lv_obj_clear_flag(bar->gps_ring, LV_OBJ_FLAG_HIDDEN);
    lv_obj_clear_flag(bar->gps_center, LV_OBJ_FLAG_HIDDEN);
    lv_obj_clear_flag(bar->gps_tail, LV_OBJ_FLAG_HIDDEN);
    return start_x + YOYOPOD_STATUS_GPS_WIDTH + YOYOPOD_STATUS_CLUSTER_GAP;
}

static void yoyopod_status_bar_build(lv_obj_t * parent, yoyopod_status_bar_t * bar, int show_time) {
    memset(bar, 0, sizeof(*bar));

    for(int index = 0; index < 4; index++) {
        bar->signal_bars[index] = lv_obj_create(parent);
        lv_obj_remove_style_all(bar->signal_bars[index]);
        lv_obj_set_style_bg_opa(bar->signal_bars[index], LV_OPA_COVER, 0);
        lv_obj_set_style_radius(bar->signal_bars[index], 1, 0);
        lv_obj_add_flag(bar->signal_bars[index], LV_OBJ_FLAG_HIDDEN);
    }

    bar->wifi_label = lv_label_create(parent);
    lv_label_set_text(bar->wifi_label, LV_SYMBOL_WIFI);
    lv_obj_set_width(bar->wifi_label, YOYOPOD_STATUS_WIFI_WIDTH);
    lv_label_set_long_mode(bar->wifi_label, LV_LABEL_LONG_MODE_CLIP);
    lv_obj_set_style_text_font(bar->wifi_label, &lv_font_montserrat_12, 0);
    lv_obj_set_style_text_align(bar->wifi_label, LV_TEXT_ALIGN_CENTER, 0);
    lv_obj_set_style_text_color(bar->wifi_label, yoyopod_color_u24(YOYOPOD_THEME_MUTED_RGB), 0);
    lv_obj_add_flag(bar->wifi_label, LV_OBJ_FLAG_HIDDEN);

    bar->gps_ring = lv_obj_create(parent);
    lv_obj_remove_style_all(bar->gps_ring);
    lv_obj_set_size(bar->gps_ring, 8, 8);
    lv_obj_set_style_radius(bar->gps_ring, LV_RADIUS_CIRCLE, 0);
    lv_obj_set_style_border_width(bar->gps_ring, 1, 0);
    lv_obj_set_style_bg_opa(bar->gps_ring, LV_OPA_TRANSP, 0);
    lv_obj_add_flag(bar->gps_ring, LV_OBJ_FLAG_HIDDEN);

    bar->gps_center = lv_obj_create(parent);
    lv_obj_remove_style_all(bar->gps_center);
    lv_obj_set_size(bar->gps_center, 2, 2);
    lv_obj_set_style_radius(bar->gps_center, LV_RADIUS_CIRCLE, 0);
    lv_obj_set_style_bg_opa(bar->gps_center, LV_OPA_COVER, 0);
    lv_obj_add_flag(bar->gps_center, LV_OBJ_FLAG_HIDDEN);

    bar->gps_tail = lv_obj_create(parent);
    lv_obj_remove_style_all(bar->gps_tail);
    lv_obj_set_size(bar->gps_tail, 2, 5);
    lv_obj_set_style_radius(bar->gps_tail, 1, 0);
    lv_obj_set_style_bg_opa(bar->gps_tail, LV_OPA_COVER, 0);
    lv_obj_add_flag(bar->gps_tail, LV_OBJ_FLAG_HIDDEN);

    bar->voip_dot = lv_obj_create(parent);
    lv_obj_remove_style_all(bar->voip_dot);
    lv_obj_set_size(bar->voip_dot, YOYOPOD_STATUS_VOIP_SIZE, YOYOPOD_STATUS_VOIP_SIZE);
    lv_obj_set_style_radius(bar->voip_dot, LV_RADIUS_CIRCLE, 0);
    lv_obj_set_style_bg_opa(bar->voip_dot, LV_OPA_COVER, 0);

    if(show_time) {
        bar->time_label = lv_label_create(parent);
        lv_obj_set_width(bar->time_label, YOYOPOD_STATUS_TIME_WIDTH);
        lv_label_set_long_mode(bar->time_label, LV_LABEL_LONG_MODE_CLIP);
        lv_obj_set_style_text_font(bar->time_label, &lv_font_montserrat_12, 0);
        lv_obj_set_style_text_align(bar->time_label, LV_TEXT_ALIGN_CENTER, 0);
        lv_obj_set_style_text_color(bar->time_label, yoyopod_color_u24(YOYOPOD_THEME_MUTED_RGB), 0);
        lv_obj_align(bar->time_label, LV_ALIGN_TOP_MID, 0, YOYOPOD_STATUS_TIME_Y);
    }

    bar->battery_outline = lv_obj_create(parent);
    lv_obj_remove_style_all(bar->battery_outline);
    lv_obj_set_size(bar->battery_outline, 14, 8);
    lv_obj_set_pos(bar->battery_outline, YOYOPOD_STATUS_BATTERY_X, YOYOPOD_STATUS_BATTERY_Y);
    lv_obj_set_style_border_width(bar->battery_outline, 1, 0);
    lv_obj_set_style_border_color(bar->battery_outline, yoyopod_color_u24(YOYOPOD_THEME_MUTED_RGB), 0);
    lv_obj_set_style_radius(bar->battery_outline, 2, 0);
    lv_obj_set_style_bg_opa(bar->battery_outline, LV_OPA_TRANSP, 0);

    bar->battery_fill = lv_obj_create(bar->battery_outline);
    lv_obj_remove_style_all(bar->battery_fill);
    lv_obj_set_pos(bar->battery_fill, 1, 1);
    lv_obj_set_size(bar->battery_fill, 12, 6);
    lv_obj_set_style_radius(bar->battery_fill, 1, 0);
    lv_obj_set_style_bg_opa(bar->battery_fill, LV_OPA_COVER, 0);

    bar->battery_tip = lv_obj_create(parent);
    lv_obj_remove_style_all(bar->battery_tip);
    lv_obj_set_size(bar->battery_tip, 2, 4);
    lv_obj_set_pos(bar->battery_tip, YOYOPOD_STATUS_BATTERY_TIP_X, YOYOPOD_STATUS_BATTERY_TIP_Y);
    lv_obj_set_style_bg_color(bar->battery_tip, yoyopod_color_u24(YOYOPOD_THEME_MUTED_RGB), 0);
    lv_obj_set_style_bg_opa(bar->battery_tip, LV_OPA_COVER, 0);

    bar->battery_label = lv_label_create(parent);
    lv_obj_set_pos(bar->battery_label, YOYOPOD_STATUS_BATTERY_LABEL_X, YOYOPOD_STATUS_BATTERY_LABEL_Y);
    lv_obj_set_style_text_font(bar->battery_label, &lv_font_montserrat_12, 0);
    lv_obj_set_style_text_color(bar->battery_label, yoyopod_color_u24(YOYOPOD_THEME_MUTED_RGB), 0);
}

static void yoyopod_status_bar_sync(
    yoyopod_status_bar_t * bar,
    int32_t voip_state,
    const char * time_text,
    int32_t battery_percent,
    int32_t charging,
    int32_t power_available
) {
    int32_t network_enabled = g_status_bar_state.network_enabled;
    int32_t network_connected = g_status_bar_state.network_connected;
    int32_t wifi_connected = g_status_bar_state.wifi_connected;
    int32_t signal_strength = g_status_bar_state.signal_strength;
    int32_t gps_has_fix = g_status_bar_state.gps_has_fix;
    int32_t cursor_x = YOYOPOD_STATUS_LEFT_INSET;

    yoyopod_apply_signal_bars(bar, network_enabled, network_connected, signal_strength, cursor_x);
    if(network_enabled) {
        cursor_x +=
            (4 * YOYOPOD_STATUS_SIGNAL_BAR_WIDTH) +
            (3 * YOYOPOD_STATUS_SIGNAL_BAR_GAP) +
            YOYOPOD_STATUS_CLUSTER_GAP;
    }
    cursor_x = yoyopod_apply_wifi_icon(bar, wifi_connected, cursor_x);
    cursor_x = yoyopod_apply_gps_icon(bar, network_enabled, gps_has_fix, cursor_x);
    if(bar->voip_dot != NULL) {
        lv_obj_set_pos(
            bar->voip_dot,
            cursor_x,
            yoyopod_status_top_for_height(YOYOPOD_STATUS_VOIP_SIZE)
        );
    }
    yoyopod_apply_voip_dot(bar->voip_dot, voip_state);

    if(bar->time_label != NULL) {
        lv_label_set_text(bar->time_label, yoyopod_time_or_default(time_text));
        lv_obj_align(bar->time_label, LV_ALIGN_TOP_MID, 0, YOYOPOD_STATUS_TIME_Y);
        lv_obj_clear_flag(bar->time_label, LV_OBJ_FLAG_HIDDEN);
    }

    if(bar->battery_label != NULL) {
        char battery_text[8];
        int32_t battery_value = battery_percent;
        if(battery_value < 0) {
            battery_value = 0;
        }
        if(battery_value > 100) {
            battery_value = 100;
        }
        snprintf(battery_text, sizeof(battery_text), "%d%%", battery_value);
        lv_label_set_text(bar->battery_label, battery_text);
    }

    yoyopod_apply_battery(
        bar->battery_outline,
        bar->battery_fill,
        bar->battery_tip,
        battery_percent,
        charging,
        power_available
    );
}

int yoyopod_lvgl_set_status_bar_state(
    int32_t network_enabled,
    int32_t network_connected,
    int32_t wifi_connected,
    int32_t signal_strength,
    int32_t gps_has_fix
) {
    g_status_bar_state.network_enabled = network_enabled ? 1 : 0;
    g_status_bar_state.network_connected = network_connected ? 1 : 0;
    g_status_bar_state.wifi_connected = wifi_connected ? 1 : 0;
    if(signal_strength < 0) {
        signal_strength = 0;
    }
    if(signal_strength > 4) {
        signal_strength = 4;
    }
    g_status_bar_state.signal_strength = signal_strength;
    g_status_bar_state.gps_has_fix = gps_has_fix ? 1 : 0;
    return 0;
}

int yoyopod_lvgl_hub_build(void) {
    if(!g_initialized || g_display == NULL) {
        yoyopod_set_error("display must be registered before building the hub");
        return -1;
    }

    if(g_hub_scene.built) {
        return 0;
    }

    g_hub_scene.screen = lv_obj_create(NULL);
    if(g_hub_scene.screen == NULL) {
        yoyopod_set_error("lv_obj_create(NULL) failed for hub scene");
        return -1;
    }
    lv_obj_set_style_bg_color(g_hub_scene.screen, yoyopod_color_u24(YOYOPOD_THEME_BACKGROUND_RGB), 0);
    lv_obj_set_style_bg_opa(g_hub_scene.screen, LV_OPA_COVER, 0);
    yoyopod_status_bar_build(g_hub_scene.screen, &g_hub_scene.status_bar, 1);

    g_hub_scene.icon_glow = lv_obj_create(g_hub_scene.screen);
    lv_obj_remove_style_all(g_hub_scene.icon_glow);
    lv_obj_set_size(g_hub_scene.icon_glow, 116, 116);
    lv_obj_set_pos(g_hub_scene.icon_glow, 62, 48);
    lv_obj_set_style_radius(g_hub_scene.icon_glow, 24, 0);
    lv_obj_set_style_border_width(g_hub_scene.icon_glow, 0, 0);
    lv_obj_set_style_bg_opa(g_hub_scene.icon_glow, LV_OPA_40, 0);

    g_hub_scene.card_panel = lv_obj_create(g_hub_scene.screen);
    lv_obj_remove_style_all(g_hub_scene.card_panel);
    lv_obj_set_size(g_hub_scene.card_panel, 96, 96);
    lv_obj_set_pos(g_hub_scene.card_panel, 72, 58);
    lv_obj_set_style_radius(g_hub_scene.card_panel, 16, 0);
    lv_obj_set_style_border_width(g_hub_scene.card_panel, 0, 0);
    lv_obj_set_style_pad_all(g_hub_scene.card_panel, 0, 0);
    lv_obj_set_style_shadow_width(g_hub_scene.card_panel, 24, 0);
    lv_obj_set_style_shadow_opa(g_hub_scene.card_panel, LV_OPA_30, 0);
    lv_obj_set_style_outline_width(g_hub_scene.card_panel, 0, 0);
    lv_obj_set_scrollbar_mode(g_hub_scene.card_panel, LV_SCROLLBAR_MODE_OFF);

    g_hub_scene.icon_image = lv_image_create(g_hub_scene.card_panel);
    lv_obj_set_style_image_recolor_opa(g_hub_scene.icon_image, LV_OPA_COVER, 0);
    lv_obj_set_style_image_opa(g_hub_scene.icon_image, LV_OPA_COVER, 0);
    lv_obj_center(g_hub_scene.icon_image);

    g_hub_scene.title_label = lv_label_create(g_hub_scene.screen);
    lv_obj_set_width(g_hub_scene.title_label, 120);
    lv_obj_set_pos(g_hub_scene.title_label, 60, 176);
    lv_obj_set_style_text_font(g_hub_scene.title_label, &lv_font_montserrat_24, 0);
    lv_obj_set_style_text_align(g_hub_scene.title_label, LV_TEXT_ALIGN_CENTER, 0);

    g_hub_scene.subtitle_label = lv_label_create(g_hub_scene.screen);
    lv_obj_set_width(g_hub_scene.subtitle_label, 120);
    lv_obj_set_pos(g_hub_scene.subtitle_label, 60, 204);
    lv_label_set_long_mode(g_hub_scene.subtitle_label, LV_LABEL_LONG_MODE_CLIP);
    lv_obj_set_style_text_font(g_hub_scene.subtitle_label, &lv_font_montserrat_12, 0);
    lv_obj_set_style_text_align(g_hub_scene.subtitle_label, LV_TEXT_ALIGN_CENTER, 0);
    lv_obj_add_flag(g_hub_scene.subtitle_label, LV_OBJ_FLAG_HIDDEN);

    for(int index = 0; index < 4; ++index) {
        g_hub_scene.dots[index] = lv_obj_create(g_hub_scene.screen);
        lv_obj_remove_style_all(g_hub_scene.dots[index]);
        lv_obj_set_style_bg_opa(g_hub_scene.dots[index], LV_OPA_COVER, 0);
        lv_obj_set_style_radius(g_hub_scene.dots[index], LV_RADIUS_CIRCLE, 0);
    }

    g_hub_scene.footer_bar = lv_obj_create(g_hub_scene.screen);
    lv_obj_remove_style_all(g_hub_scene.footer_bar);
    lv_obj_set_size(g_hub_scene.footer_bar, 240, 32);
    lv_obj_set_pos(g_hub_scene.footer_bar, 0, 248);
    lv_obj_set_style_bg_opa(g_hub_scene.footer_bar, LV_OPA_COVER, 0);

    g_hub_scene.footer_label = lv_label_create(g_hub_scene.screen);
    yoyopod_prepare_footer_label(g_hub_scene.footer_label);

    g_hub_scene.built = 1;
    return 0;
}

int yoyopod_lvgl_hub_sync(
    const char * icon_key,
    const char * title,
    const char * subtitle,
    const char * footer,
    const char * time_text,
    uint32_t accent_rgb,
    int32_t selected_index,
    int32_t total_cards,
    int32_t voip_state,
    int32_t battery_percent,
    int32_t charging,
    int32_t power_available
) {
    if(!g_hub_scene.built) {
        yoyopod_set_error("hub scene must be built before sync");
        return -1;
    }
    if(yoyopod_require_scene_screen(g_hub_scene.screen, "hub scene screen is unavailable during sync") != 0) {
        return -1;
    }

    const lv_color_t background = yoyopod_color_u24(YOYOPOD_THEME_BACKGROUND_RGB);
    const lv_color_t footer_fill = yoyopod_color_u24(YOYOPOD_THEME_FOOTER_RGB);
    const lv_color_t ink = yoyopod_color_u24(YOYOPOD_THEME_INK_RGB);
    const lv_color_t muted_dim = yoyopod_color_u24(YOYOPOD_THEME_MUTED_DIM_RGB);
    const lv_color_t accent = yoyopod_color_u24(accent_rgb);
    const lv_color_t glow_fill = yoyopod_mix_u24(accent_rgb, YOYOPOD_THEME_BACKGROUND_RGB, 72);

    lv_obj_set_style_bg_color(g_hub_scene.screen, background, 0);
    lv_obj_set_style_bg_opa(g_hub_scene.screen, LV_OPA_COVER, 0);
    yoyopod_status_bar_sync(
        &g_hub_scene.status_bar,
        voip_state,
        time_text,
        battery_percent,
        charging,
        power_available
    );

    lv_obj_set_style_bg_color(g_hub_scene.icon_glow, glow_fill, 0);
    lv_obj_set_style_bg_opa(g_hub_scene.icon_glow, LV_OPA_40, 0);
    lv_obj_set_style_bg_color(g_hub_scene.card_panel, accent, 0);
    lv_obj_set_style_bg_opa(g_hub_scene.card_panel, LV_OPA_COVER, 0);
    lv_obj_set_style_shadow_color(g_hub_scene.card_panel, accent, 0);

    lv_image_set_src(g_hub_scene.icon_image, yoyopod_hub_icon_for_key(icon_key));
    lv_obj_set_style_image_recolor(g_hub_scene.icon_image, ink, 0);
    lv_obj_set_style_image_recolor_opa(g_hub_scene.icon_image, LV_OPA_COVER, 0);
    lv_obj_center(g_hub_scene.icon_image);
    lv_label_set_text(g_hub_scene.title_label, title != NULL ? title : "");
    lv_obj_set_style_text_color(g_hub_scene.title_label, ink, 0);
    lv_label_set_text(g_hub_scene.subtitle_label, "");
    lv_obj_add_flag(g_hub_scene.subtitle_label, LV_OBJ_FLAG_HIDDEN);
    lv_obj_set_style_bg_color(g_hub_scene.footer_bar, footer_fill, 0);
    yoyopod_apply_footer_label(g_hub_scene.footer_label, footer, muted_dim);

    if(total_cards < 1) {
        total_cards = 1;
    }
    if(total_cards > 4) {
        total_cards = 4;
    }

    selected_index = selected_index % total_cards;
    if(selected_index < 0) {
        selected_index += total_cards;
    }

    int dot_spacing = 10;
    int dots_width = ((total_cards - 1) * dot_spacing) + 4;
    int first_x = (240 - dots_width) / 2;
    for(int index = 0; index < 4; ++index) {
        if(index >= total_cards) {
            lv_obj_add_flag(g_hub_scene.dots[index], LV_OBJ_FLAG_HIDDEN);
            continue;
        }

        int selected = index == selected_index;
        lv_obj_clear_flag(g_hub_scene.dots[index], LV_OBJ_FLAG_HIDDEN);
        lv_obj_set_pos(g_hub_scene.dots[index], first_x + (index * dot_spacing), 218);
        yoyopod_hub_style_dot(g_hub_scene.dots[index], ink, selected);
    }

    if(yoyopod_activate_scene_screen(g_hub_scene.screen, "hub scene screen is unavailable during sync") < 0) {
        return -1;
    }

    return 0;
}

void yoyopod_lvgl_hub_destroy(void) {
    if(!g_hub_scene.built) {
        return;
    }

    yoyopod_release_scene_screen(g_hub_scene.screen);
    yoyopod_clear_group();
    yoyopod_reset_hub_scene_refs();
}

int yoyopod_lvgl_talk_build(void) {
    if(!g_initialized || g_display == NULL) {
        yoyopod_set_error("display must be registered before building the talk scene");
        return -1;
    }

    if(g_talk_scene.built) {
        return 0;
    }

    g_talk_scene.screen = lv_obj_create(NULL);
    if(g_talk_scene.screen == NULL) {
        yoyopod_set_error("lv_obj_create(NULL) failed for talk scene");
        return -1;
    }
    lv_obj_set_style_bg_color(g_talk_scene.screen, yoyopod_color_u24(YOYOPOD_THEME_BACKGROUND_RGB), 0);
    lv_obj_set_style_bg_opa(g_talk_scene.screen, LV_OPA_COVER, 0);
    yoyopod_status_bar_build(g_talk_scene.screen, &g_talk_scene.status_bar, 1);

    g_talk_scene.card_glow = lv_obj_create(g_talk_scene.screen);
    lv_obj_remove_style_all(g_talk_scene.card_glow);
    lv_obj_set_size(g_talk_scene.card_glow, 124, 124);
    lv_obj_set_pos(g_talk_scene.card_glow, 58, 42);
    lv_obj_set_style_radius(g_talk_scene.card_glow, 22, 0);
    lv_obj_set_style_bg_opa(g_talk_scene.card_glow, LV_OPA_20, 0);

    g_talk_scene.card_panel = lv_obj_create(g_talk_scene.screen);
    lv_obj_remove_style_all(g_talk_scene.card_panel);
    lv_obj_set_size(g_talk_scene.card_panel, 112, 112);
    lv_obj_set_pos(g_talk_scene.card_panel, 64, 48);
    lv_obj_set_style_radius(g_talk_scene.card_panel, 16, 0);
    lv_obj_set_style_pad_all(g_talk_scene.card_panel, 0, 0);
    lv_obj_set_style_shadow_width(g_talk_scene.card_panel, 22, 0);
    lv_obj_set_style_shadow_opa(g_talk_scene.card_panel, LV_OPA_30, 0);
    lv_obj_set_style_outline_width(g_talk_scene.card_panel, 0, 0);
    lv_obj_set_scrollbar_mode(g_talk_scene.card_panel, LV_SCROLLBAR_MODE_OFF);

    g_talk_scene.card_label = lv_label_create(g_talk_scene.card_panel);
    lv_obj_set_style_text_font(g_talk_scene.card_label, &lv_font_montserrat_24, 0);
    lv_obj_center(g_talk_scene.card_label);

    g_talk_scene.title_label = lv_label_create(g_talk_scene.screen);
    lv_obj_set_width(g_talk_scene.title_label, 180);
    lv_obj_set_pos(g_talk_scene.title_label, 30, 176);
    lv_label_set_long_mode(g_talk_scene.title_label, LV_LABEL_LONG_MODE_DOTS);
    lv_obj_set_style_text_font(g_talk_scene.title_label, &lv_font_montserrat_24, 0);
    lv_obj_set_style_text_align(g_talk_scene.title_label, LV_TEXT_ALIGN_CENTER, 0);

    for(int index = 0; index < 4; ++index) {
        g_talk_scene.dots[index] = lv_obj_create(g_talk_scene.screen);
        lv_obj_remove_style_all(g_talk_scene.dots[index]);
        lv_obj_set_style_bg_opa(g_talk_scene.dots[index], LV_OPA_COVER, 0);
        lv_obj_set_style_radius(g_talk_scene.dots[index], LV_RADIUS_CIRCLE, 0);
    }

    yoyopod_build_footer_bar(g_talk_scene.screen);
    g_talk_scene.footer_label = lv_label_create(g_talk_scene.screen);
    yoyopod_prepare_footer_label(g_talk_scene.footer_label);

    g_talk_scene.built = 1;
    return 0;
}

int yoyopod_lvgl_talk_sync(
    const char * title_text,
    const char * icon_key,
    int32_t outlined,
    const char * footer,
    int32_t selected_index,
    int32_t total_cards,
    int32_t voip_state,
    int32_t battery_percent,
    int32_t charging,
    int32_t power_available,
    uint32_t accent_rgb
) {
    if(!g_talk_scene.built) {
        yoyopod_set_error("talk scene must be built before sync");
        return -1;
    }
    if(yoyopod_require_scene_screen(g_talk_scene.screen, "talk scene screen is unavailable during sync") != 0) {
        return -1;
    }

    const lv_color_t background = yoyopod_color_u24(YOYOPOD_THEME_BACKGROUND_RGB);
    const lv_color_t ink = yoyopod_color_u24(YOYOPOD_THEME_INK_RGB);
    const lv_color_t accent = yoyopod_color_u24(accent_rgb);
    const lv_color_t muted_dim = yoyopod_color_u24(YOYOPOD_THEME_MUTED_DIM_RGB);
    const lv_color_t accent_dim = yoyopod_mix_u24(accent_rgb, YOYOPOD_THEME_BACKGROUND_RGB, 68);
    const lv_color_t outlined_fill = yoyopod_mix_u24(accent_rgb, YOYOPOD_THEME_BACKGROUND_RGB, 80);
    char monogram[3];

    lv_obj_set_style_bg_color(g_talk_scene.screen, background, 0);
    lv_obj_set_style_bg_opa(g_talk_scene.screen, LV_OPA_COVER, 0);
    yoyopod_status_bar_sync(
        &g_talk_scene.status_bar,
        voip_state,
        NULL,
        battery_percent,
        charging,
        power_available
    );

    lv_obj_set_style_bg_color(g_talk_scene.card_glow, accent_dim, 0);
    lv_obj_set_style_bg_opa(g_talk_scene.card_glow, outlined ? LV_OPA_10 : LV_OPA_20, 0);
    lv_obj_set_style_bg_color(g_talk_scene.card_panel, outlined ? outlined_fill : accent, 0);
    lv_obj_set_style_bg_opa(g_talk_scene.card_panel, LV_OPA_COVER, 0);
    lv_obj_set_style_border_width(g_talk_scene.card_panel, outlined ? 2 : 0, 0);
    lv_obj_set_style_border_color(g_talk_scene.card_panel, accent, 0);
    lv_obj_set_style_shadow_color(g_talk_scene.card_panel, accent, 0);

    if(icon_key != NULL && icon_key[0] != '\0') {
        lv_label_set_text(g_talk_scene.card_label, yoyopod_symbol_for_empty_icon(icon_key));
    } else {
        yoyopod_make_monogram(title_text, monogram);
        lv_label_set_text(g_talk_scene.card_label, monogram);
    }
    lv_obj_set_style_text_color(g_talk_scene.card_label, outlined ? accent : ink, 0);
    lv_obj_center(g_talk_scene.card_label);

    lv_label_set_text(g_talk_scene.title_label, title_text != NULL ? title_text : "");
    lv_obj_set_style_text_color(g_talk_scene.title_label, ink, 0);

    if(total_cards < 1) {
        total_cards = 1;
    }
    if(total_cards > 4) {
        total_cards = 4;
    }
    if(selected_index < 0) {
        selected_index = 0;
    }
    if(selected_index >= total_cards) {
        selected_index = total_cards - 1;
    }

    for(int index = 0; index < 4; ++index) {
        if(index >= total_cards) {
            lv_obj_add_flag(g_talk_scene.dots[index], LV_OBJ_FLAG_HIDDEN);
            continue;
        }
        lv_obj_clear_flag(g_talk_scene.dots[index], LV_OBJ_FLAG_HIDDEN);
        lv_obj_set_size(g_talk_scene.dots[index], index == selected_index ? 8 : 6, index == selected_index ? 8 : 6);
        lv_obj_set_pos(g_talk_scene.dots[index], 120 - ((total_cards * 14) / 2) + (index * 14), 224);
        lv_obj_set_style_bg_color(g_talk_scene.dots[index], index == selected_index ? accent : accent_dim, 0);
        lv_obj_set_style_bg_opa(g_talk_scene.dots[index], index == selected_index ? LV_OPA_COVER : LV_OPA_40, 0);
    }

    yoyopod_apply_footer_label(g_talk_scene.footer_label, footer, muted_dim);

    if(yoyopod_activate_scene_screen(g_talk_scene.screen, "talk scene screen is unavailable during sync") < 0) {
        return -1;
    }

    return 0;
}

void yoyopod_lvgl_talk_destroy(void) {
    if(!g_talk_scene.built) {
        return;
    }

    yoyopod_release_scene_screen(g_talk_scene.screen);
    yoyopod_clear_group();
    yoyopod_reset_talk_scene_refs();
}

int yoyopod_lvgl_talk_actions_build(void) {
    if(!g_initialized || g_display == NULL) {
        yoyopod_set_error("display must be registered before building the talk-actions scene");
        return -1;
    }

    if(g_talk_actions_scene.built) {
        return 0;
    }

    g_talk_actions_scene.screen = lv_obj_create(NULL);
    if(g_talk_actions_scene.screen == NULL) {
        yoyopod_set_error("lv_obj_create(NULL) failed for talk actions scene");
        return -1;
    }
    lv_obj_set_style_bg_color(g_talk_actions_scene.screen, yoyopod_color_u24(YOYOPOD_THEME_BACKGROUND_RGB), 0);
    lv_obj_set_style_bg_opa(g_talk_actions_scene.screen, LV_OPA_COVER, 0);
    yoyopod_status_bar_build(g_talk_actions_scene.screen, &g_talk_actions_scene.status_bar, 1);

    g_talk_actions_scene.header_box = lv_obj_create(g_talk_actions_scene.screen);
    lv_obj_remove_style_all(g_talk_actions_scene.header_box);
    lv_obj_set_size(g_talk_actions_scene.header_box, 48, 48);
    lv_obj_set_pos(g_talk_actions_scene.header_box, 96, 50);
    lv_obj_set_style_radius(g_talk_actions_scene.header_box, 12, 0);
    lv_obj_set_style_bg_opa(g_talk_actions_scene.header_box, LV_OPA_COVER, 0);

    g_talk_actions_scene.header_label = lv_label_create(g_talk_actions_scene.header_box);
    lv_obj_set_style_text_font(g_talk_actions_scene.header_label, &lv_font_montserrat_18, 0);
    lv_obj_center(g_talk_actions_scene.header_label);

    g_talk_actions_scene.header_name_label = lv_label_create(g_talk_actions_scene.screen);
    lv_obj_set_width(g_talk_actions_scene.header_name_label, 140);
    lv_obj_set_pos(g_talk_actions_scene.header_name_label, 50, 104);
    lv_label_set_long_mode(g_talk_actions_scene.header_name_label, LV_LABEL_LONG_MODE_DOTS);
    lv_obj_set_style_text_font(g_talk_actions_scene.header_name_label, &lv_font_montserrat_12, 0);
    lv_obj_set_style_text_align(g_talk_actions_scene.header_name_label, LV_TEXT_ALIGN_CENTER, 0);

    for(int index = 0; index < 3; ++index) {
        g_talk_actions_scene.buttons[index] = lv_obj_create(g_talk_actions_scene.screen);
        lv_obj_remove_style_all(g_talk_actions_scene.buttons[index]);
        lv_obj_set_style_radius(g_talk_actions_scene.buttons[index], LV_RADIUS_CIRCLE, 0);
        lv_obj_set_style_pad_all(g_talk_actions_scene.buttons[index], 0, 0);
        lv_obj_set_style_shadow_width(g_talk_actions_scene.buttons[index], 0, 0);
        lv_obj_set_scrollbar_mode(g_talk_actions_scene.buttons[index], LV_SCROLLBAR_MODE_OFF);

        g_talk_actions_scene.button_labels[index] = lv_label_create(g_talk_actions_scene.buttons[index]);
        lv_obj_set_style_text_font(g_talk_actions_scene.button_labels[index], &lv_font_montserrat_18, 0);
        lv_obj_center(g_talk_actions_scene.button_labels[index]);
    }

    g_talk_actions_scene.title_label = lv_label_create(g_talk_actions_scene.screen);
    lv_obj_set_width(g_talk_actions_scene.title_label, 180);
    lv_obj_set_pos(g_talk_actions_scene.title_label, 30, 198);
    lv_label_set_long_mode(g_talk_actions_scene.title_label, LV_LABEL_LONG_MODE_DOTS);
    lv_obj_set_style_text_font(g_talk_actions_scene.title_label, &lv_font_montserrat_18, 0);
    lv_obj_set_style_text_align(g_talk_actions_scene.title_label, LV_TEXT_ALIGN_CENTER, 0);

    g_talk_actions_scene.status_label = lv_label_create(g_talk_actions_scene.screen);
    lv_obj_set_width(g_talk_actions_scene.status_label, 180);
    lv_obj_set_pos(g_talk_actions_scene.status_label, 30, 214);
    lv_obj_set_style_text_font(g_talk_actions_scene.status_label, &lv_font_montserrat_12, 0);
    lv_obj_set_style_text_align(g_talk_actions_scene.status_label, LV_TEXT_ALIGN_CENTER, 0);

    for(int index = 0; index < 3; ++index) {
        g_talk_actions_scene.dots[index] = lv_obj_create(g_talk_actions_scene.screen);
        lv_obj_remove_style_all(g_talk_actions_scene.dots[index]);
        lv_obj_set_style_bg_opa(g_talk_actions_scene.dots[index], LV_OPA_COVER, 0);
        lv_obj_set_style_radius(g_talk_actions_scene.dots[index], LV_RADIUS_CIRCLE, 0);
    }

    yoyopod_build_footer_bar(g_talk_actions_scene.screen);
    g_talk_actions_scene.footer_label = lv_label_create(g_talk_actions_scene.screen);
    yoyopod_prepare_footer_label(g_talk_actions_scene.footer_label);

    g_talk_actions_scene.built = 1;
    return 0;
}

int yoyopod_lvgl_talk_actions_sync(
    const char * contact_name,
    const char * title_text,
    const char * status_text,
    int32_t status_kind,
    const char * footer,
    const char * icon_0,
    int32_t color_kind_0,
    const char * icon_1,
    int32_t color_kind_1,
    const char * icon_2,
    int32_t color_kind_2,
    int32_t action_count,
    int32_t selected_index,
    int32_t layout_kind,
    int32_t button_size_kind,
    int32_t voip_state,
    int32_t battery_percent,
    int32_t charging,
    int32_t power_available,
    uint32_t accent_rgb
) {
    if(!g_talk_actions_scene.built) {
        yoyopod_set_error("talk-actions scene must be built before sync");
        return -1;
    }
    if(yoyopod_require_scene_screen(
        g_talk_actions_scene.screen,
        "talk-actions scene screen is unavailable during sync"
    ) != 0) {
        return -1;
    }

    const lv_color_t background = yoyopod_color_u24(YOYOPOD_THEME_BACKGROUND_RGB);
    const lv_color_t surface = yoyopod_color_u24(YOYOPOD_THEME_SURFACE_RAISED_RGB);
    const lv_color_t ink = yoyopod_color_u24(YOYOPOD_THEME_INK_RGB);
    const lv_color_t muted = yoyopod_color_u24(YOYOPOD_THEME_MUTED_RGB);
    const lv_color_t accent = yoyopod_color_u24(accent_rgb);
    const lv_color_t muted_dim = yoyopod_color_u24(YOYOPOD_THEME_MUTED_DIM_RGB);
    const lv_color_t accent_dim = yoyopod_mix_u24(accent_rgb, YOYOPOD_THEME_BACKGROUND_RGB, 68);
    const char * icons[3] = {icon_0, icon_1, icon_2};
    int32_t color_kinds[3] = {color_kind_0, color_kind_1, color_kind_2};
    char monogram[3];

    if(action_count < 0) {
        action_count = 0;
    }
    if(action_count > 3) {
        action_count = 3;
    }
    if(selected_index < 0) {
        selected_index = 0;
    }
    if(action_count > 0 && selected_index >= action_count) {
        selected_index = action_count - 1;
    }

    lv_obj_set_style_bg_color(g_talk_actions_scene.screen, background, 0);
    lv_obj_set_style_bg_opa(g_talk_actions_scene.screen, LV_OPA_COVER, 0);
    yoyopod_status_bar_sync(
        &g_talk_actions_scene.status_bar,
        voip_state,
        NULL,
        battery_percent,
        charging,
        power_available
    );

    lv_obj_set_style_bg_color(g_talk_actions_scene.header_box, yoyopod_mix_u24(accent_rgb, YOYOPOD_THEME_BACKGROUND_RGB, 85), 0);
    lv_obj_set_style_bg_opa(g_talk_actions_scene.header_box, LV_OPA_COVER, 0);
    yoyopod_make_monogram(contact_name, monogram);
    lv_label_set_text(g_talk_actions_scene.header_label, monogram);
    lv_obj_set_style_text_color(g_talk_actions_scene.header_label, accent, 0);
    lv_obj_center(g_talk_actions_scene.header_label);
    lv_label_set_text(g_talk_actions_scene.header_name_label, contact_name != NULL ? contact_name : "");
    lv_obj_set_style_text_color(g_talk_actions_scene.header_name_label, muted, 0);

    if(layout_kind == 1) {
        const int diameter = 88;
        const int left = 76;
        const int top = 126;
        lv_obj_add_flag(g_talk_actions_scene.title_label, LV_OBJ_FLAG_HIDDEN);
        for(int index = 0; index < 3; ++index) {
            lv_obj_add_flag(g_talk_actions_scene.dots[index], LV_OBJ_FLAG_HIDDEN);
        }

        for(int index = 0; index < 3; ++index) {
            if(index == 0 && action_count > 0) {
                lv_obj_clear_flag(g_talk_actions_scene.buttons[index], LV_OBJ_FLAG_HIDDEN);
                lv_obj_set_pos(g_talk_actions_scene.buttons[index], left, top);
                lv_obj_set_size(g_talk_actions_scene.buttons[index], diameter, diameter);
                lv_obj_set_style_radius(g_talk_actions_scene.buttons[index], LV_RADIUS_CIRCLE, 0);
                lv_obj_set_style_bg_color(g_talk_actions_scene.buttons[index], surface, 0);
                lv_obj_set_style_bg_opa(g_talk_actions_scene.buttons[index], LV_OPA_COVER, 0);
                lv_obj_set_style_border_width(g_talk_actions_scene.buttons[index], 2, 0);
                lv_obj_set_style_border_color(g_talk_actions_scene.buttons[index], yoyopod_color_for_kind(color_kinds[0], accent_rgb), 0);
                lv_label_set_text(g_talk_actions_scene.button_labels[index], yoyopod_symbol_for_empty_icon(icons[0]));
                lv_obj_set_style_text_font(g_talk_actions_scene.button_labels[index], &lv_font_montserrat_24, 0);
                lv_obj_set_style_text_color(g_talk_actions_scene.button_labels[index], yoyopod_color_for_kind(color_kinds[0], accent_rgb), 0);
                lv_obj_center(g_talk_actions_scene.button_labels[index]);
            } else {
                lv_obj_add_flag(g_talk_actions_scene.buttons[index], LV_OBJ_FLAG_HIDDEN);
            }
        }

        lv_label_set_text(g_talk_actions_scene.status_label, status_text != NULL ? status_text : "");
        lv_obj_set_style_text_color(g_talk_actions_scene.status_label, yoyopod_color_for_kind(status_kind, accent_rgb), 0);
        lv_obj_set_pos(g_talk_actions_scene.status_label, 30, 220);
        lv_obj_clear_flag(g_talk_actions_scene.status_label, LV_OBJ_FLAG_HIDDEN);
    } else {
        const int diameter = button_size_kind == 1 ? 64 : 56;
        const int gap = button_size_kind == 1 ? 16 : 12;
        const int center_y = button_size_kind == 1 ? 154 : 156;
        const int row_width = (action_count * diameter) + ((action_count > 0 ? action_count - 1 : 0) * gap);
        const int start_x = 120 - (row_width / 2);
        const int title_y = center_y + (diameter / 2) + 16;
        lv_obj_add_flag(g_talk_actions_scene.status_label, LV_OBJ_FLAG_HIDDEN);

        for(int index = 0; index < 3; ++index) {
            if(index >= action_count) {
                lv_obj_add_flag(g_talk_actions_scene.buttons[index], LV_OBJ_FLAG_HIDDEN);
                continue;
            }
            lv_color_t button_color = yoyopod_color_for_kind(color_kinds[index], accent_rgb);
            int selected = index == selected_index;
            lv_obj_clear_flag(g_talk_actions_scene.buttons[index], LV_OBJ_FLAG_HIDDEN);
            lv_obj_set_pos(g_talk_actions_scene.buttons[index], start_x + (index * (diameter + gap)), center_y - (diameter / 2));
            lv_obj_set_size(g_talk_actions_scene.buttons[index], diameter, diameter);
            lv_obj_set_style_radius(g_talk_actions_scene.buttons[index], LV_RADIUS_CIRCLE, 0);
            lv_obj_set_style_bg_color(g_talk_actions_scene.buttons[index], selected ? button_color : surface, 0);
            lv_obj_set_style_bg_opa(g_talk_actions_scene.buttons[index], LV_OPA_COVER, 0);
            lv_obj_set_style_border_width(g_talk_actions_scene.buttons[index], selected ? 0 : 2, 0);
            lv_obj_set_style_border_color(g_talk_actions_scene.buttons[index], button_color, 0);
            lv_label_set_text(g_talk_actions_scene.button_labels[index], yoyopod_symbol_for_empty_icon(icons[index]));
            lv_obj_set_style_text_font(g_talk_actions_scene.button_labels[index], &lv_font_montserrat_18, 0);
            lv_obj_set_style_text_color(g_talk_actions_scene.button_labels[index], selected ? ink : button_color, 0);
            lv_obj_center(g_talk_actions_scene.button_labels[index]);
        }

        lv_label_set_text(g_talk_actions_scene.title_label, title_text != NULL ? title_text : "");
        lv_obj_set_style_text_color(g_talk_actions_scene.title_label, ink, 0);
        lv_obj_set_pos(g_talk_actions_scene.title_label, 30, title_y);
        lv_obj_clear_flag(g_talk_actions_scene.title_label, LV_OBJ_FLAG_HIDDEN);

        for(int index = 0; index < 3; ++index) {
            if(index >= action_count) {
                lv_obj_add_flag(g_talk_actions_scene.dots[index], LV_OBJ_FLAG_HIDDEN);
                continue;
            }
            lv_obj_clear_flag(g_talk_actions_scene.dots[index], LV_OBJ_FLAG_HIDDEN);
            lv_obj_set_size(g_talk_actions_scene.dots[index], index == selected_index ? 8 : 6, index == selected_index ? 8 : 6);
            lv_obj_set_pos(g_talk_actions_scene.dots[index], 120 - ((action_count * 14) / 2) + (index * 14), title_y + 30);
            lv_obj_set_style_bg_color(g_talk_actions_scene.dots[index], index == selected_index ? accent : accent_dim, 0);
            lv_obj_set_style_bg_opa(g_talk_actions_scene.dots[index], index == selected_index ? LV_OPA_COVER : LV_OPA_40, 0);
        }
    }

    yoyopod_apply_footer_label(g_talk_actions_scene.footer_label, footer, muted_dim);

    if(yoyopod_activate_scene_screen(g_talk_actions_scene.screen, "talk-actions scene screen is unavailable during sync") < 0) {
        return -1;
    }

    return 0;
}

void yoyopod_lvgl_talk_actions_destroy(void) {
    if(!g_talk_actions_scene.built) {
        return;
    }

    yoyopod_release_scene_screen(g_talk_actions_scene.screen);
    yoyopod_clear_group();
    yoyopod_reset_talk_actions_scene_refs();
}

int yoyopod_lvgl_listen_build(void) {
    if(!g_initialized || g_display == NULL) {
        yoyopod_set_error("display must be registered before building the listen scene");
        return -1;
    }

    if(g_listen_scene.built) {
        return 0;
    }

    g_listen_scene.screen = lv_obj_create(NULL);
    if(g_listen_scene.screen == NULL) {
        yoyopod_set_error("lv_obj_create(NULL) failed for listen scene");
        return -1;
    }
    lv_obj_set_style_bg_color(g_listen_scene.screen, yoyopod_color_u24(YOYOPOD_THEME_BACKGROUND_RGB), 0);
    lv_obj_set_style_bg_opa(g_listen_scene.screen, LV_OPA_COVER, 0);
    yoyopod_status_bar_build(g_listen_scene.screen, &g_listen_scene.status_bar, 0);

    g_listen_scene.title_label = lv_label_create(g_listen_scene.screen);
    lv_label_set_text(g_listen_scene.title_label, "Your Music");
    lv_obj_set_pos(g_listen_scene.title_label, 16, 38);
    lv_obj_set_style_text_font(g_listen_scene.title_label, &lv_font_montserrat_24, 0);

    g_listen_scene.subtitle_label = lv_label_create(g_listen_scene.screen);
    lv_label_set_text(g_listen_scene.subtitle_label, "Local library");
    lv_obj_set_pos(g_listen_scene.subtitle_label, 16, 68);
    lv_obj_set_style_text_font(g_listen_scene.subtitle_label, &lv_font_montserrat_12, 0);

    g_listen_scene.panel = lv_obj_create(g_listen_scene.screen);
    lv_obj_set_size(g_listen_scene.panel, 208, 188);
    lv_obj_set_pos(g_listen_scene.panel, 16, 92);
    lv_obj_set_style_radius(g_listen_scene.panel, 0, 0);
    lv_obj_set_style_border_width(g_listen_scene.panel, 0, 0);
    lv_obj_set_style_bg_opa(g_listen_scene.panel, LV_OPA_TRANSP, 0);
    lv_obj_set_style_pad_all(g_listen_scene.panel, 0, 0);
    lv_obj_set_style_shadow_width(g_listen_scene.panel, 0, 0);
    lv_obj_set_style_outline_width(g_listen_scene.panel, 0, 0);
    lv_obj_set_scrollbar_mode(g_listen_scene.panel, LV_SCROLLBAR_MODE_OFF);

    for(int index = 0; index < 4; ++index) {
        g_listen_scene.item_panels[index] = lv_obj_create(g_listen_scene.panel);
        lv_obj_set_size(g_listen_scene.item_panels[index], 208, 44);
        lv_obj_set_pos(g_listen_scene.item_panels[index], 0, index * 52);
        lv_obj_set_style_radius(g_listen_scene.item_panels[index], 16, 0);
        lv_obj_set_style_border_width(g_listen_scene.item_panels[index], 1, 0);
        lv_obj_set_style_pad_all(g_listen_scene.item_panels[index], 0, 0);
        lv_obj_set_style_shadow_width(g_listen_scene.item_panels[index], 0, 0);
        lv_obj_set_style_outline_width(g_listen_scene.item_panels[index], 0, 0);
        lv_obj_set_scrollbar_mode(g_listen_scene.item_panels[index], LV_SCROLLBAR_MODE_OFF);

        g_listen_scene.item_icons[index] = lv_label_create(g_listen_scene.item_panels[index]);
        lv_obj_set_pos(g_listen_scene.item_icons[index], 16, 12);
        lv_obj_set_style_text_font(g_listen_scene.item_icons[index], &lv_font_montserrat_18, 0);

        g_listen_scene.item_titles[index] = lv_label_create(g_listen_scene.item_panels[index]);
        lv_obj_set_width(g_listen_scene.item_titles[index], 120);
        lv_obj_set_pos(g_listen_scene.item_titles[index], 48, 8);
        lv_label_set_long_mode(g_listen_scene.item_titles[index], LV_LABEL_LONG_MODE_CLIP);
        lv_obj_set_style_text_font(g_listen_scene.item_titles[index], &lv_font_montserrat_16, 0);

        g_listen_scene.item_subtitles[index] = lv_label_create(g_listen_scene.item_panels[index]);
        lv_obj_set_width(g_listen_scene.item_subtitles[index], 120);
        lv_obj_set_pos(g_listen_scene.item_subtitles[index], 48, 26);
        lv_label_set_long_mode(g_listen_scene.item_subtitles[index], LV_LABEL_LONG_MODE_CLIP);
        lv_obj_set_style_text_font(g_listen_scene.item_subtitles[index], &lv_font_montserrat_12, 0);
    }

    g_listen_scene.empty_panel = lv_obj_create(g_listen_scene.screen);
    lv_obj_set_size(g_listen_scene.empty_panel, 204, 156);
    lv_obj_set_pos(g_listen_scene.empty_panel, 18, 94);
    lv_obj_set_style_radius(g_listen_scene.empty_panel, 22, 0);
    lv_obj_set_style_border_width(g_listen_scene.empty_panel, 0, 0);
    lv_obj_set_style_pad_all(g_listen_scene.empty_panel, 0, 0);
    lv_obj_set_style_shadow_width(g_listen_scene.empty_panel, 0, 0);
    lv_obj_set_style_outline_width(g_listen_scene.empty_panel, 0, 0);
    lv_obj_set_scrollbar_mode(g_listen_scene.empty_panel, LV_SCROLLBAR_MODE_OFF);

    g_listen_scene.empty_icon = lv_label_create(g_listen_scene.empty_panel);
    lv_label_set_text(g_listen_scene.empty_icon, LV_SYMBOL_AUDIO);
    lv_obj_set_style_text_font(g_listen_scene.empty_icon, &lv_font_montserrat_24, 0);
    lv_obj_align(g_listen_scene.empty_icon, LV_ALIGN_TOP_MID, 0, 18);

    g_listen_scene.empty_title = lv_label_create(g_listen_scene.empty_panel);
    lv_obj_set_width(g_listen_scene.empty_title, 168);
    lv_obj_set_pos(g_listen_scene.empty_title, 18, 84);
    lv_obj_set_style_text_font(g_listen_scene.empty_title, &lv_font_montserrat_18, 0);
    lv_obj_set_style_text_align(g_listen_scene.empty_title, LV_TEXT_ALIGN_CENTER, 0);

    g_listen_scene.empty_subtitle = lv_label_create(g_listen_scene.empty_panel);
    lv_obj_set_width(g_listen_scene.empty_subtitle, 168);
    lv_obj_set_pos(g_listen_scene.empty_subtitle, 18, 112);
    lv_label_set_long_mode(g_listen_scene.empty_subtitle, LV_LABEL_LONG_MODE_WRAP);
    lv_obj_set_style_text_font(g_listen_scene.empty_subtitle, &lv_font_montserrat_12, 0);
    lv_obj_set_style_text_align(g_listen_scene.empty_subtitle, LV_TEXT_ALIGN_CENTER, 0);

    g_listen_scene.footer_label = lv_label_create(g_listen_scene.screen);
    yoyopod_prepare_footer_label(g_listen_scene.footer_label);

    g_listen_scene.built = 1;
    return 0;
}

int yoyopod_lvgl_listen_sync(
    const char * page_text,
    const char * footer,
    const char * item_0,
    const char * item_1,
    const char * item_2,
    const char * item_3,
    const char * subtitle_0,
    const char * subtitle_1,
    const char * subtitle_2,
    const char * subtitle_3,
    const char * icon_0,
    const char * icon_1,
    const char * icon_2,
    const char * icon_3,
    int32_t item_count,
    int32_t selected_index,
    int32_t voip_state,
    int32_t battery_percent,
    int32_t charging,
    int32_t power_available,
    uint32_t accent_rgb,
    const char * empty_title,
    const char * empty_subtitle
) {
    if(!g_listen_scene.built) {
        yoyopod_set_error("listen scene must be built before sync");
        return -1;
    }
    if(yoyopod_require_scene_screen(g_listen_scene.screen, "listen scene screen is unavailable during sync") != 0) {
        return -1;
    }

    const lv_color_t background = yoyopod_color_u24(YOYOPOD_THEME_BACKGROUND_RGB);
    const lv_color_t surface = yoyopod_color_u24(YOYOPOD_THEME_SURFACE_RGB);
    const lv_color_t raised = yoyopod_color_u24(YOYOPOD_THEME_SURFACE_RAISED_RGB);
    const lv_color_t ink = yoyopod_color_u24(YOYOPOD_THEME_INK_RGB);
    const lv_color_t muted = yoyopod_color_u24(YOYOPOD_THEME_MUTED_RGB);
    const lv_color_t muted_dim = yoyopod_color_u24(YOYOPOD_THEME_MUTED_DIM_RGB);
    const lv_color_t accent = yoyopod_color_u24(accent_rgb);
    const lv_color_t accent_dim = yoyopod_mix_u24(accent_rgb, YOYOPOD_THEME_BACKGROUND_RGB, 65);
    const lv_color_t border = yoyopod_color_u24(YOYOPOD_THEME_BORDER_RGB);
    const lv_color_t selected_fill = lv_color_hex(0xFAFAFA);
    const lv_color_t selected_text = yoyopod_color_u24(YOYOPOD_THEME_BACKGROUND_RGB);
    const lv_color_t selected_subtitle = yoyopod_mix_u24(YOYOPOD_THEME_BACKGROUND_RGB, YOYOPOD_THEME_MUTED_RGB, 55);

    const char * items[4] = {item_0, item_1, item_2, item_3};
    const char * subtitles[4] = {subtitle_0, subtitle_1, subtitle_2, subtitle_3};
    const char * icon_keys[4] = {icon_0, icon_1, icon_2, icon_3};

    lv_obj_set_style_bg_color(g_listen_scene.screen, background, 0);
    lv_obj_set_style_bg_opa(g_listen_scene.screen, LV_OPA_COVER, 0);
    yoyopod_status_bar_sync(
        &g_listen_scene.status_bar,
        voip_state,
        NULL,
        battery_percent,
        charging,
        power_available
    );

    lv_label_set_text(g_listen_scene.title_label, "Your Music");
    lv_obj_set_style_text_color(g_listen_scene.title_label, ink, 0);
    lv_label_set_text(g_listen_scene.subtitle_label, "Local library");
    lv_obj_set_style_text_color(g_listen_scene.subtitle_label, muted, 0);

    if(item_count < 0) {
        item_count = 0;
    }
    if(item_count > 4) {
        item_count = 4;
    }

    if(item_count == 0) {
        lv_obj_add_flag(g_listen_scene.panel, LV_OBJ_FLAG_HIDDEN);
        lv_obj_clear_flag(g_listen_scene.empty_panel, LV_OBJ_FLAG_HIDDEN);
        lv_obj_set_style_bg_color(g_listen_scene.empty_panel, surface, 0);
        lv_obj_set_style_bg_opa(g_listen_scene.empty_panel, LV_OPA_COVER, 0);
        lv_obj_set_style_text_color(g_listen_scene.empty_icon, accent, 0);
        lv_obj_set_style_text_color(g_listen_scene.empty_title, ink, 0);
        lv_obj_set_style_text_color(g_listen_scene.empty_subtitle, muted, 0);
        lv_label_set_text(g_listen_scene.empty_title, empty_title != NULL ? empty_title : "No sources");
        lv_label_set_text(
            g_listen_scene.empty_subtitle,
            empty_subtitle != NULL ? empty_subtitle : "Add music sources in config to fill this page."
        );
    } else {
        lv_obj_clear_flag(g_listen_scene.panel, LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag(g_listen_scene.empty_panel, LV_OBJ_FLAG_HIDDEN);
    }

    if(item_count > 0) {
        selected_index = selected_index % item_count;
        if(selected_index < 0) {
            selected_index += item_count;
        }
    } else {
        selected_index = 0;
    }

    for(int index = 0; index < 4; ++index) {
        if(index >= item_count) {
            lv_obj_add_flag(g_listen_scene.item_panels[index], LV_OBJ_FLAG_HIDDEN);
            continue;
        }

        int selected = index == selected_index;
        const char * subtitle_text = subtitles[index] != NULL ? subtitles[index] : "";
        lv_obj_clear_flag(g_listen_scene.item_panels[index], LV_OBJ_FLAG_HIDDEN);
        lv_label_set_text(g_listen_scene.item_titles[index], items[index] != NULL ? items[index] : "");
        lv_label_set_text(g_listen_scene.item_icons[index], yoyopod_symbol_for_empty_icon(icon_keys[index]));
        lv_obj_set_style_text_color(g_listen_scene.item_icons[index], accent, 0);
        lv_obj_set_style_bg_color(g_listen_scene.item_panels[index], selected ? selected_fill : raised, 0);
        lv_obj_set_style_bg_opa(g_listen_scene.item_panels[index], LV_OPA_COVER, 0);
        lv_obj_set_style_border_color(g_listen_scene.item_panels[index], selected ? selected_fill : border, 0);
        lv_obj_set_style_text_color(
            g_listen_scene.item_titles[index],
            selected ? selected_text : ink,
            0
        );
        if(subtitle_text[0] != '\0') {
            lv_obj_clear_flag(g_listen_scene.item_subtitles[index], LV_OBJ_FLAG_HIDDEN);
            lv_label_set_text(g_listen_scene.item_subtitles[index], subtitle_text);
            lv_obj_set_style_text_color(
                g_listen_scene.item_subtitles[index],
                selected ? selected_subtitle : muted,
                0
            );
            lv_obj_set_y(g_listen_scene.item_titles[index], 7);
            lv_obj_set_y(g_listen_scene.item_subtitles[index], 24);
        } else {
            lv_label_set_text(g_listen_scene.item_subtitles[index], "");
            lv_obj_add_flag(g_listen_scene.item_subtitles[index], LV_OBJ_FLAG_HIDDEN);
            lv_obj_set_y(g_listen_scene.item_titles[index], 13);
        }
    }

    yoyopod_apply_footer_label(g_listen_scene.footer_label, footer, accent_dim);

    if(yoyopod_activate_scene_screen(g_listen_scene.screen, "listen scene screen is unavailable during sync") < 0) {
        return -1;
    }

    return 0;
}

void yoyopod_lvgl_listen_destroy(void) {
    if(!g_listen_scene.built) {
        return;
    }

    yoyopod_release_scene_screen(g_listen_scene.screen);
    yoyopod_clear_group();
    yoyopod_reset_listen_scene_refs();
}

int yoyopod_lvgl_playlist_build(void) {
    if(!g_initialized || g_display == NULL) {
        yoyopod_set_error("display must be registered before building the playlist scene");
        return -1;
    }

    if(g_playlist_scene.built) {
        return 0;
    }

    g_playlist_scene.screen = lv_obj_create(NULL);
    if(g_playlist_scene.screen == NULL) {
        yoyopod_set_error("lv_obj_create(NULL) failed for playlist scene");
        return -1;
    }
    lv_obj_set_style_bg_color(g_playlist_scene.screen, yoyopod_color_u24(YOYOPOD_THEME_BACKGROUND_RGB), 0);
    lv_obj_set_style_bg_opa(g_playlist_scene.screen, LV_OPA_COVER, 0);
    yoyopod_status_bar_build(g_playlist_scene.screen, &g_playlist_scene.status_bar, 0);

    g_playlist_scene.title_label = lv_label_create(g_playlist_scene.screen);
    lv_obj_set_pos(g_playlist_scene.title_label, 18, 38);
    lv_obj_set_style_text_font(g_playlist_scene.title_label, &lv_font_montserrat_18, 0);

    g_playlist_scene.title_underline = lv_obj_create(g_playlist_scene.screen);
    lv_obj_remove_style_all(g_playlist_scene.title_underline);
    lv_obj_set_pos(g_playlist_scene.title_underline, 18, 60);
    lv_obj_set_size(g_playlist_scene.title_underline, 30, 3);
    lv_obj_set_style_radius(g_playlist_scene.title_underline, 3, 0);
    lv_obj_set_style_bg_opa(g_playlist_scene.title_underline, LV_OPA_COVER, 0);

    g_playlist_scene.page_label = lv_label_create(g_playlist_scene.screen);
    lv_obj_set_pos(g_playlist_scene.page_label, 182, 40);
    lv_obj_set_style_text_font(g_playlist_scene.page_label, &lv_font_montserrat_12, 0);
    lv_obj_set_style_text_color(g_playlist_scene.page_label, yoyopod_color_u24(YOYOPOD_THEME_MUTED_RGB), 0);

    g_playlist_scene.status_chip = lv_obj_create(g_playlist_scene.screen);
    lv_obj_set_size(g_playlist_scene.status_chip, 68, 22);
    lv_obj_set_pos(g_playlist_scene.status_chip, 84, 36);
    lv_obj_set_style_radius(g_playlist_scene.status_chip, 11, 0);
    lv_obj_set_style_border_width(g_playlist_scene.status_chip, 0, 0);
    lv_obj_set_style_pad_all(g_playlist_scene.status_chip, 0, 0);
    lv_obj_set_style_pad_left(g_playlist_scene.status_chip, 12, 0);
    lv_obj_set_style_pad_right(g_playlist_scene.status_chip, 12, 0);
    lv_obj_set_style_shadow_width(g_playlist_scene.status_chip, 0, 0);
    lv_obj_set_style_outline_width(g_playlist_scene.status_chip, 0, 0);
    lv_obj_set_scrollbar_mode(g_playlist_scene.status_chip, LV_SCROLLBAR_MODE_OFF);
    lv_obj_add_flag(g_playlist_scene.status_chip, LV_OBJ_FLAG_HIDDEN);

    g_playlist_scene.status_chip_label = lv_label_create(g_playlist_scene.status_chip);
    lv_obj_set_style_text_font(g_playlist_scene.status_chip_label, &lv_font_montserrat_12, 0);
    lv_obj_align(g_playlist_scene.status_chip_label, LV_ALIGN_LEFT_MID, 0, 0);

    g_playlist_scene.panel = lv_obj_create(g_playlist_scene.screen);
    lv_obj_set_size(g_playlist_scene.panel, 216, 166);
    lv_obj_set_pos(g_playlist_scene.panel, 12, 86);
    lv_obj_set_style_radius(g_playlist_scene.panel, 0, 0);
    lv_obj_set_style_border_width(g_playlist_scene.panel, 0, 0);
    lv_obj_set_style_bg_opa(g_playlist_scene.panel, LV_OPA_TRANSP, 0);
    lv_obj_set_style_pad_all(g_playlist_scene.panel, 0, 0);
    lv_obj_set_style_shadow_width(g_playlist_scene.panel, 0, 0);
    lv_obj_set_style_outline_width(g_playlist_scene.panel, 0, 0);
    lv_obj_set_scrollbar_mode(g_playlist_scene.panel, LV_SCROLLBAR_MODE_OFF);

    for(int index = 0; index < 4; ++index) {
        g_playlist_scene.item_panels[index] = lv_obj_create(g_playlist_scene.panel);
        lv_obj_set_size(g_playlist_scene.item_panels[index], 184, 44);
        lv_obj_set_pos(g_playlist_scene.item_panels[index], 16, 8 + (index * 48));
        lv_obj_set_style_radius(g_playlist_scene.item_panels[index], 16, 0);
        lv_obj_set_style_border_width(g_playlist_scene.item_panels[index], 1, 0);
        lv_obj_set_style_pad_all(g_playlist_scene.item_panels[index], 0, 0);
        lv_obj_set_style_shadow_width(g_playlist_scene.item_panels[index], 0, 0);
        lv_obj_set_style_outline_width(g_playlist_scene.item_panels[index], 0, 0);
        lv_obj_set_scrollbar_mode(g_playlist_scene.item_panels[index], LV_SCROLLBAR_MODE_OFF);

        g_playlist_scene.item_icons[index] = lv_label_create(g_playlist_scene.item_panels[index]);
        lv_obj_set_pos(g_playlist_scene.item_icons[index], 14, 12);
        lv_obj_set_style_text_font(g_playlist_scene.item_icons[index], &lv_font_montserrat_18, 0);

        g_playlist_scene.item_titles[index] = lv_label_create(g_playlist_scene.item_panels[index]);
        lv_obj_set_width(g_playlist_scene.item_titles[index], 92);
        lv_obj_set_pos(g_playlist_scene.item_titles[index], 44, 7);
        lv_label_set_long_mode(g_playlist_scene.item_titles[index], LV_LABEL_LONG_MODE_CLIP);
        lv_obj_set_style_text_font(g_playlist_scene.item_titles[index], &lv_font_montserrat_16, 0);

        g_playlist_scene.item_subtitles[index] = lv_label_create(g_playlist_scene.item_panels[index]);
        lv_obj_set_width(g_playlist_scene.item_subtitles[index], 92);
        lv_obj_set_pos(g_playlist_scene.item_subtitles[index], 44, 24);
        lv_label_set_long_mode(g_playlist_scene.item_subtitles[index], LV_LABEL_LONG_MODE_CLIP);
        lv_obj_set_style_text_font(g_playlist_scene.item_subtitles[index], &lv_font_montserrat_12, 0);

        g_playlist_scene.item_badges[index] = lv_label_create(g_playlist_scene.item_panels[index]);
        lv_obj_set_pos(g_playlist_scene.item_badges[index], 150, 12);
        lv_obj_set_style_text_font(g_playlist_scene.item_badges[index], &lv_font_montserrat_12, 0);
    }

    g_playlist_scene.empty_panel = lv_obj_create(g_playlist_scene.screen);
    lv_obj_set_size(g_playlist_scene.empty_panel, 204, 156);
    lv_obj_set_pos(g_playlist_scene.empty_panel, 18, 96);
    lv_obj_set_style_radius(g_playlist_scene.empty_panel, 22, 0);
    lv_obj_set_style_border_width(g_playlist_scene.empty_panel, 0, 0);
    lv_obj_set_style_pad_all(g_playlist_scene.empty_panel, 0, 0);
    lv_obj_set_style_shadow_width(g_playlist_scene.empty_panel, 0, 0);
    lv_obj_set_style_outline_width(g_playlist_scene.empty_panel, 0, 0);
    lv_obj_set_scrollbar_mode(g_playlist_scene.empty_panel, LV_SCROLLBAR_MODE_OFF);

    g_playlist_scene.empty_icon = lv_label_create(g_playlist_scene.empty_panel);
    lv_obj_set_style_text_font(g_playlist_scene.empty_icon, &lv_font_montserrat_24, 0);
    lv_obj_align(g_playlist_scene.empty_icon, LV_ALIGN_TOP_MID, 0, 18);

    g_playlist_scene.empty_title = lv_label_create(g_playlist_scene.empty_panel);
    lv_obj_set_width(g_playlist_scene.empty_title, 168);
    lv_obj_set_pos(g_playlist_scene.empty_title, 18, 84);
    lv_obj_set_style_text_font(g_playlist_scene.empty_title, &lv_font_montserrat_18, 0);
    lv_obj_set_style_text_align(g_playlist_scene.empty_title, LV_TEXT_ALIGN_CENTER, 0);

    g_playlist_scene.empty_subtitle = lv_label_create(g_playlist_scene.empty_panel);
    lv_obj_set_width(g_playlist_scene.empty_subtitle, 168);
    lv_obj_set_pos(g_playlist_scene.empty_subtitle, 18, 112);
    lv_label_set_long_mode(g_playlist_scene.empty_subtitle, LV_LABEL_LONG_MODE_WRAP);
    lv_obj_set_style_text_font(g_playlist_scene.empty_subtitle, &lv_font_montserrat_12, 0);
    lv_obj_set_style_text_align(g_playlist_scene.empty_subtitle, LV_TEXT_ALIGN_CENTER, 0);

    yoyopod_build_footer_bar(g_playlist_scene.screen);
    g_playlist_scene.footer_label = lv_label_create(g_playlist_scene.screen);
    yoyopod_prepare_footer_label(g_playlist_scene.footer_label);

    g_playlist_scene.built = 1;
    return 0;
}

int yoyopod_lvgl_playlist_sync(
    const char * title_text,
    const char * page_text,
    const char * status_chip_text,
    int32_t status_chip_kind,
    const char * footer,
    const char * item_0,
    const char * item_1,
    const char * item_2,
    const char * item_3,
    const char * subtitle_0,
    const char * subtitle_1,
    const char * subtitle_2,
    const char * subtitle_3,
    const char * badge_0,
    const char * badge_1,
    const char * badge_2,
    const char * badge_3,
    const char * icon_0,
    const char * icon_1,
    const char * icon_2,
    const char * icon_3,
    int32_t item_count,
    int32_t selected_visible_index,
    int32_t voip_state,
    int32_t battery_percent,
    int32_t charging,
    int32_t power_available,
    uint32_t accent_rgb,
    const char * empty_title,
    const char * empty_subtitle,
    const char * empty_icon_key
) {
    if(!g_playlist_scene.built) {
        yoyopod_set_error("playlist scene must be built before sync");
        return -1;
    }
    if(yoyopod_require_scene_screen(
        g_playlist_scene.screen,
        "playlist scene screen is unavailable during sync"
    ) != 0) {
        return -1;
    }

    const lv_color_t background = yoyopod_color_u24(YOYOPOD_THEME_BACKGROUND_RGB);
    const lv_color_t surface = yoyopod_color_u24(YOYOPOD_THEME_SURFACE_RGB);
    const lv_color_t raised = yoyopod_color_u24(YOYOPOD_THEME_SURFACE_RAISED_RGB);
    const lv_color_t ink = yoyopod_color_u24(YOYOPOD_THEME_INK_RGB);
    const lv_color_t muted = yoyopod_color_u24(YOYOPOD_THEME_MUTED_RGB);
    const lv_color_t muted_dim = yoyopod_color_u24(YOYOPOD_THEME_MUTED_DIM_RGB);
    const lv_color_t accent = yoyopod_color_u24(accent_rgb);
    const lv_color_t accent_dim = yoyopod_mix_u24(accent_rgb, YOYOPOD_THEME_BACKGROUND_RGB, 65);
    const lv_color_t selected_fill = lv_color_hex(0xFAFAFA);
    const lv_color_t selected_text = yoyopod_color_u24(YOYOPOD_THEME_BACKGROUND_RGB);
    const lv_color_t selected_subtitle = yoyopod_mix_u24(YOYOPOD_THEME_BACKGROUND_RGB, YOYOPOD_THEME_MUTED_RGB, 55);
    const lv_color_t border = yoyopod_color_u24(YOYOPOD_THEME_BORDER_RGB);
    const lv_color_t success = yoyopod_color_u24(YOYOPOD_THEME_SUCCESS_RGB);
    const lv_color_t warning = yoyopod_color_u24(YOYOPOD_THEME_WARNING_RGB);
    const lv_color_t error = yoyopod_color_u24(YOYOPOD_THEME_ERROR_RGB);
    const lv_color_t neutral = yoyopod_color_u24(YOYOPOD_THEME_NEUTRAL_RGB);

    const char * items[4] = {item_0, item_1, item_2, item_3};
    const char * subtitles[4] = {subtitle_0, subtitle_1, subtitle_2, subtitle_3};
    const char * badges[4] = {badge_0, badge_1, badge_2, badge_3};
    const char * icon_keys[4] = {icon_0, icon_1, icon_2, icon_3};

    lv_obj_set_style_bg_color(g_playlist_scene.screen, background, 0);
    lv_obj_set_style_bg_opa(g_playlist_scene.screen, LV_OPA_COVER, 0);
    yoyopod_status_bar_sync(
        &g_playlist_scene.status_bar,
        voip_state,
        NULL,
        battery_percent,
        charging,
        power_available
    );

    lv_label_set_text(g_playlist_scene.title_label, title_text != NULL ? title_text : "");
    lv_obj_set_style_text_color(g_playlist_scene.title_label, ink, 0);
    lv_obj_set_style_bg_color(g_playlist_scene.title_underline, accent, 0);
    if(page_text != NULL && page_text[0] != '\0') {
        lv_label_set_text(g_playlist_scene.page_label, page_text);
        lv_obj_clear_flag(g_playlist_scene.page_label, LV_OBJ_FLAG_HIDDEN);
    } else {
        lv_label_set_text(g_playlist_scene.page_label, "");
        lv_obj_add_flag(g_playlist_scene.page_label, LV_OBJ_FLAG_HIDDEN);
    }

    if(status_chip_text != NULL && status_chip_text[0] != '\0') {
        lv_color_t chip_fill = yoyopod_mix_u24(YOYOPOD_THEME_SUCCESS_RGB, YOYOPOD_THEME_BACKGROUND_RGB, 70);
        lv_color_t chip_text = success;
        if(status_chip_kind == 2) {
            chip_fill = yoyopod_mix_u24(YOYOPOD_THEME_WARNING_RGB, YOYOPOD_THEME_BACKGROUND_RGB, 72);
            chip_text = warning;
        } else if(status_chip_kind == 3) {
            chip_fill = yoyopod_mix_u24(YOYOPOD_THEME_ERROR_RGB, YOYOPOD_THEME_BACKGROUND_RGB, 72);
            chip_text = error;
        } else if(status_chip_kind == 4) {
            chip_fill = yoyopod_mix_u24(YOYOPOD_THEME_NEUTRAL_RGB, YOYOPOD_THEME_BACKGROUND_RGB, 72);
            chip_text = neutral;
        }

        lv_obj_set_style_bg_color(g_playlist_scene.status_chip, chip_fill, 0);
        lv_obj_set_style_bg_opa(g_playlist_scene.status_chip, LV_OPA_COVER, 0);
        lv_label_set_text(g_playlist_scene.status_chip_label, status_chip_text);
        lv_obj_set_style_text_color(g_playlist_scene.status_chip_label, chip_text, 0);
        lv_obj_clear_flag(g_playlist_scene.status_chip, LV_OBJ_FLAG_HIDDEN);
        lv_obj_align(g_playlist_scene.status_chip_label, LV_ALIGN_LEFT_MID, 0, 0);
    } else {
        lv_label_set_text(g_playlist_scene.status_chip_label, "");
        lv_obj_add_flag(g_playlist_scene.status_chip, LV_OBJ_FLAG_HIDDEN);
    }

    if(item_count < 0) {
        item_count = 0;
    }
    if(item_count > 4) {
        item_count = 4;
    }

    if(item_count == 0) {
        lv_obj_add_flag(g_playlist_scene.panel, LV_OBJ_FLAG_HIDDEN);
        lv_obj_clear_flag(g_playlist_scene.empty_panel, LV_OBJ_FLAG_HIDDEN);
        lv_obj_set_style_bg_color(g_playlist_scene.empty_panel, surface, 0);
        lv_obj_set_style_bg_opa(g_playlist_scene.empty_panel, LV_OPA_COVER, 0);
        lv_obj_set_style_border_color(g_playlist_scene.empty_panel, accent_dim, 0);
        lv_label_set_text(g_playlist_scene.empty_icon, yoyopod_symbol_for_empty_icon(empty_icon_key));
        lv_obj_set_style_text_color(g_playlist_scene.empty_icon, accent, 0);
        lv_label_set_text(g_playlist_scene.empty_title, empty_title != NULL ? empty_title : "");
        lv_obj_set_style_text_color(g_playlist_scene.empty_title, ink, 0);
        lv_label_set_text(g_playlist_scene.empty_subtitle, empty_subtitle != NULL ? empty_subtitle : "");
        lv_obj_set_style_text_color(g_playlist_scene.empty_subtitle, muted, 0);
    } else {
        lv_obj_clear_flag(g_playlist_scene.panel, LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag(g_playlist_scene.empty_panel, LV_OBJ_FLAG_HIDDEN);
    }

    if(item_count > 0) {
        selected_visible_index = selected_visible_index % item_count;
        if(selected_visible_index < 0) {
            selected_visible_index += item_count;
        }
    } else {
        selected_visible_index = 0;
    }

    for(int index = 0; index < 4; ++index) {
        if(index >= item_count) {
            lv_obj_add_flag(g_playlist_scene.item_panels[index], LV_OBJ_FLAG_HIDDEN);
            continue;
        }

        int selected = index == selected_visible_index;
        const char * subtitle_text = subtitles[index] != NULL ? subtitles[index] : "";
        const char * badge_text = badges[index] != NULL ? badges[index] : "";
        lv_obj_clear_flag(g_playlist_scene.item_panels[index], LV_OBJ_FLAG_HIDDEN);
        lv_label_set_text(g_playlist_scene.item_titles[index], items[index] != NULL ? items[index] : "");
        lv_label_set_text(g_playlist_scene.item_icons[index], yoyopod_symbol_for_empty_icon(icon_keys[index]));
        lv_obj_set_style_text_color(g_playlist_scene.item_icons[index], accent, 0);
        lv_obj_set_style_bg_color(g_playlist_scene.item_panels[index], selected ? selected_fill : raised, 0);
        lv_obj_set_style_bg_opa(g_playlist_scene.item_panels[index], LV_OPA_COVER, 0);
        lv_obj_set_style_border_color(g_playlist_scene.item_panels[index], selected ? selected_fill : border, 0);
        lv_obj_set_style_text_color(
            g_playlist_scene.item_titles[index],
            selected ? selected_text : ink,
            0
        );

        if(subtitle_text[0] == '\0') {
            lv_label_set_text(g_playlist_scene.item_subtitles[index], "");
            lv_obj_add_flag(g_playlist_scene.item_subtitles[index], LV_OBJ_FLAG_HIDDEN);
            lv_obj_set_y(g_playlist_scene.item_titles[index], 13);
        } else {
            lv_label_set_text(g_playlist_scene.item_subtitles[index], subtitle_text);
            lv_obj_set_style_text_color(
                g_playlist_scene.item_subtitles[index],
                selected ? selected_subtitle : muted,
                0
            );
            lv_obj_clear_flag(g_playlist_scene.item_subtitles[index], LV_OBJ_FLAG_HIDDEN);
            lv_obj_set_y(g_playlist_scene.item_titles[index], 7);
            lv_obj_set_y(g_playlist_scene.item_subtitles[index], 24);
        }

        if(badge_text[0] == '\0') {
            lv_obj_add_flag(g_playlist_scene.item_badges[index], LV_OBJ_FLAG_HIDDEN);
        } else {
            lv_obj_clear_flag(g_playlist_scene.item_badges[index], LV_OBJ_FLAG_HIDDEN);
            lv_label_set_text(g_playlist_scene.item_badges[index], badge_text);
            lv_obj_set_style_text_color(
                g_playlist_scene.item_badges[index],
                selected ? selected_subtitle : muted_dim,
                0
            );
            lv_obj_set_x(g_playlist_scene.item_badges[index], 184 - (int)lv_obj_get_width(g_playlist_scene.item_badges[index]) - 16);
        }
    }

    yoyopod_apply_footer_label(g_playlist_scene.footer_label, footer, muted_dim);

    if(yoyopod_activate_scene_screen(g_playlist_scene.screen, "playlist scene screen is unavailable during sync") < 0) {
        return -1;
    }

    return 0;
}

void yoyopod_lvgl_playlist_destroy(void) {
    if(!g_playlist_scene.built) {
        return;
    }

    yoyopod_release_scene_screen(g_playlist_scene.screen);
    yoyopod_clear_group();
    yoyopod_reset_playlist_scene_refs();
}

int yoyopod_lvgl_now_playing_build(void) {
    if(!g_initialized || g_display == NULL) {
        yoyopod_set_error("display must be registered before building the now-playing scene");
        return -1;
    }

    if(g_now_playing_scene.built) {
        return 0;
    }

    g_now_playing_scene.screen = lv_obj_create(NULL);
    if(g_now_playing_scene.screen == NULL) {
        yoyopod_set_error("lv_obj_create(NULL) failed for now-playing scene");
        return -1;
    }
    lv_obj_set_style_bg_color(g_now_playing_scene.screen, yoyopod_color_u24(YOYOPOD_THEME_BACKGROUND_RGB), 0);
    lv_obj_set_style_bg_opa(g_now_playing_scene.screen, LV_OPA_COVER, 0);
    yoyopod_status_bar_build(g_now_playing_scene.screen, &g_now_playing_scene.status_bar, 0);

    g_now_playing_scene.panel = lv_obj_create(g_now_playing_scene.screen);
    lv_obj_set_size(g_now_playing_scene.panel, 240, 214);
    lv_obj_set_pos(g_now_playing_scene.panel, 0, 38);
    lv_obj_set_style_radius(g_now_playing_scene.panel, 0, 0);
    lv_obj_set_style_border_width(g_now_playing_scene.panel, 0, 0);
    lv_obj_set_style_pad_all(g_now_playing_scene.panel, 0, 0);
    lv_obj_set_style_shadow_width(g_now_playing_scene.panel, 0, 0);
    lv_obj_set_style_outline_width(g_now_playing_scene.panel, 0, 0);
    lv_obj_set_scrollbar_mode(g_now_playing_scene.panel, LV_SCROLLBAR_MODE_OFF);

    g_now_playing_scene.icon_halo = lv_obj_create(g_now_playing_scene.panel);
    lv_obj_set_size(g_now_playing_scene.icon_halo, 92, 66);
    lv_obj_set_pos(g_now_playing_scene.icon_halo, 74, 12);
    lv_obj_set_style_radius(g_now_playing_scene.icon_halo, 20, 0);
    lv_obj_set_style_border_width(g_now_playing_scene.icon_halo, 2, 0);
    lv_obj_set_style_shadow_width(g_now_playing_scene.icon_halo, 0, 0);
    lv_obj_set_style_outline_width(g_now_playing_scene.icon_halo, 0, 0);
    lv_obj_set_scrollbar_mode(g_now_playing_scene.icon_halo, LV_SCROLLBAR_MODE_OFF);

    g_now_playing_scene.icon_label = lv_label_create(g_now_playing_scene.icon_halo);
    lv_label_set_text(g_now_playing_scene.icon_label, LV_SYMBOL_AUDIO);
    lv_obj_set_style_text_font(g_now_playing_scene.icon_label, &lv_font_montserrat_24, 0);
    lv_obj_center(g_now_playing_scene.icon_label);

    g_now_playing_scene.state_chip = lv_obj_create(g_now_playing_scene.panel);
    lv_obj_set_size(g_now_playing_scene.state_chip, 100, 24);
    lv_obj_set_pos(g_now_playing_scene.state_chip, 70, 170);
    lv_obj_set_style_radius(g_now_playing_scene.state_chip, 12, 0);
    lv_obj_set_style_border_width(g_now_playing_scene.state_chip, 0, 0);
    lv_obj_set_style_pad_all(g_now_playing_scene.state_chip, 0, 0);
    lv_obj_set_style_shadow_width(g_now_playing_scene.state_chip, 0, 0);
    lv_obj_set_style_outline_width(g_now_playing_scene.state_chip, 0, 0);
    lv_obj_set_scrollbar_mode(g_now_playing_scene.state_chip, LV_SCROLLBAR_MODE_OFF);

    g_now_playing_scene.state_label = lv_label_create(g_now_playing_scene.state_chip);
    lv_obj_set_style_text_font(g_now_playing_scene.state_label, &lv_font_montserrat_12, 0);
    lv_obj_center(g_now_playing_scene.state_label);

    g_now_playing_scene.title_label = lv_label_create(g_now_playing_scene.panel);
    lv_obj_set_size(g_now_playing_scene.title_label, 208, 44);
    lv_obj_set_pos(g_now_playing_scene.title_label, 16, 96);
    lv_label_set_long_mode(g_now_playing_scene.title_label, LV_LABEL_LONG_MODE_WRAP);
    lv_obj_set_style_text_font(g_now_playing_scene.title_label, &lv_font_montserrat_18, 0);
    lv_obj_set_style_text_align(g_now_playing_scene.title_label, LV_TEXT_ALIGN_CENTER, 0);
    lv_obj_set_style_text_line_space(g_now_playing_scene.title_label, -2, 0);

    g_now_playing_scene.artist_label = lv_label_create(g_now_playing_scene.panel);
    lv_obj_set_size(g_now_playing_scene.artist_label, 208, 16);
    lv_obj_set_pos(g_now_playing_scene.artist_label, 16, 146);
    lv_label_set_long_mode(g_now_playing_scene.artist_label, LV_LABEL_LONG_MODE_DOTS);
    lv_obj_set_style_text_font(g_now_playing_scene.artist_label, &lv_font_montserrat_12, 0);
    lv_obj_set_style_text_align(g_now_playing_scene.artist_label, LV_TEXT_ALIGN_CENTER, 0);

    g_now_playing_scene.progress_track = lv_obj_create(g_now_playing_scene.panel);
    lv_obj_set_size(g_now_playing_scene.progress_track, 168, 8);
    lv_obj_set_pos(g_now_playing_scene.progress_track, 36, 202);
    lv_obj_set_style_radius(g_now_playing_scene.progress_track, 4, 0);
    lv_obj_set_style_border_width(g_now_playing_scene.progress_track, 0, 0);
    lv_obj_set_style_pad_all(g_now_playing_scene.progress_track, 0, 0);
    lv_obj_set_style_shadow_width(g_now_playing_scene.progress_track, 0, 0);
    lv_obj_set_style_outline_width(g_now_playing_scene.progress_track, 0, 0);
    lv_obj_set_scrollbar_mode(g_now_playing_scene.progress_track, LV_SCROLLBAR_MODE_OFF);

    g_now_playing_scene.progress_fill = lv_obj_create(g_now_playing_scene.progress_track);
    lv_obj_set_size(g_now_playing_scene.progress_fill, 0, 8);
    lv_obj_set_pos(g_now_playing_scene.progress_fill, 0, 0);
    lv_obj_set_style_radius(g_now_playing_scene.progress_fill, 4, 0);
    lv_obj_set_style_border_width(g_now_playing_scene.progress_fill, 0, 0);
    lv_obj_set_style_pad_all(g_now_playing_scene.progress_fill, 0, 0);
    lv_obj_set_style_shadow_width(g_now_playing_scene.progress_fill, 0, 0);
    lv_obj_set_style_outline_width(g_now_playing_scene.progress_fill, 0, 0);
    lv_obj_set_scrollbar_mode(g_now_playing_scene.progress_fill, LV_SCROLLBAR_MODE_OFF);

    g_now_playing_scene.footer_label = lv_label_create(g_now_playing_scene.screen);
    yoyopod_prepare_footer_label(g_now_playing_scene.footer_label);

    g_now_playing_scene.built = 1;
    return 0;
}

int yoyopod_lvgl_now_playing_sync(
    const char * title_text,
    const char * artist_text,
    const char * state_text,
    const char * footer,
    int32_t progress_permille,
    int32_t voip_state,
    int32_t battery_percent,
    int32_t charging,
    int32_t power_available,
    uint32_t accent_rgb
) {
    if(!g_now_playing_scene.built) {
        yoyopod_set_error("now-playing scene must be built before sync");
        return -1;
    }
    if(yoyopod_require_scene_screen(
        g_now_playing_scene.screen,
        "now-playing scene screen is unavailable during sync"
    ) != 0) {
        return -1;
    }

    const lv_color_t background = yoyopod_color_u24(YOYOPOD_THEME_BACKGROUND_RGB);
    const lv_color_t ink = yoyopod_color_u24(YOYOPOD_THEME_INK_RGB);
    const lv_color_t muted = yoyopod_color_u24(YOYOPOD_THEME_MUTED_RGB);
    const lv_color_t progress_bg = yoyopod_mix_u24(YOYOPOD_THEME_BACKGROUND_RGB, YOYOPOD_THEME_SURFACE_RGB, 35);
    const lv_color_t accent = yoyopod_color_u24(accent_rgb);
    const lv_color_t accent_dim = yoyopod_mix_u24(accent_rgb, YOYOPOD_THEME_BACKGROUND_RGB, 65);
    const lv_color_t accent_soft = yoyopod_mix_u24(accent_rgb, YOYOPOD_THEME_SURFACE_RGB, 55);
    const lv_color_t halo_fill = yoyopod_mix_u24(accent_rgb, YOYOPOD_THEME_BACKGROUND_RGB, 80);
    const lv_color_t halo_border = yoyopod_mix_u24(accent_rgb, YOYOPOD_THEME_BACKGROUND_RGB, 60);
    lv_color_t icon_fill = halo_fill;
    lv_color_t icon_border = halo_border;
    lv_color_t icon_text = accent;
    lv_color_t chip_fill = accent_dim;
    lv_color_t chip_text = accent;
    lv_color_t progress_fill = accent;
    lv_color_t footer_text = accent_soft;
    const int state_is_paused = state_text != NULL
        && (strcmp(state_text, "Paused") == 0 || strcmp(state_text, "PAUSED") == 0);
    const int state_is_offline = state_text != NULL
        && (strcmp(state_text, "Offline") == 0 || strcmp(state_text, "OFFLINE") == 0);

    if(progress_permille < 0) {
        progress_permille = 0;
    }
    if(progress_permille > 1000) {
        progress_permille = 1000;
    }

    if(state_is_paused) {
        icon_fill = yoyopod_mix_u24(YOYOPOD_THEME_SURFACE_RAISED_RGB, YOYOPOD_THEME_BACKGROUND_RGB, 20);
        icon_border = yoyopod_mix_u24(YOYOPOD_THEME_MUTED_RGB, YOYOPOD_THEME_BACKGROUND_RGB, 60);
        icon_text = muted;
        chip_fill = yoyopod_color_u24(YOYOPOD_THEME_SURFACE_RAISED_RGB);
        chip_text = muted;
        progress_fill = yoyopod_color_u24(YOYOPOD_THEME_MUTED_DIM_RGB);
        footer_text = muted;
    } else if(state_is_offline) {
        icon_fill = yoyopod_mix_u24(YOYOPOD_THEME_ERROR_RGB, YOYOPOD_THEME_BACKGROUND_RGB, 82);
        icon_border = yoyopod_mix_u24(YOYOPOD_THEME_ERROR_RGB, YOYOPOD_THEME_BACKGROUND_RGB, 60);
        icon_text = ink;
        chip_fill = yoyopod_mix_u24(YOYOPOD_THEME_ERROR_RGB, YOYOPOD_THEME_BACKGROUND_RGB, 78);
        chip_text = yoyopod_color_u24(YOYOPOD_THEME_ERROR_RGB);
        progress_fill = yoyopod_color_u24(YOYOPOD_THEME_MUTED_DIM_RGB);
        footer_text = yoyopod_color_u24(YOYOPOD_THEME_MUTED_DIM_RGB);
    }

    lv_obj_set_style_bg_color(g_now_playing_scene.screen, background, 0);
    lv_obj_set_style_bg_opa(g_now_playing_scene.screen, LV_OPA_COVER, 0);
    yoyopod_status_bar_sync(
        &g_now_playing_scene.status_bar,
        voip_state,
        NULL,
        battery_percent,
        charging,
        power_available
    );

    lv_obj_set_style_bg_opa(g_now_playing_scene.panel, LV_OPA_TRANSP, 0);
    lv_obj_set_style_border_width(g_now_playing_scene.panel, 0, 0);

    lv_obj_set_style_bg_color(g_now_playing_scene.icon_halo, icon_fill, 0);
    lv_obj_set_style_bg_opa(g_now_playing_scene.icon_halo, LV_OPA_COVER, 0);
    lv_obj_set_style_border_color(g_now_playing_scene.icon_halo, icon_border, 0);
    lv_obj_set_style_text_color(g_now_playing_scene.icon_label, icon_text, 0);
    lv_obj_center(g_now_playing_scene.icon_label);

    lv_obj_set_style_bg_color(g_now_playing_scene.state_chip, chip_fill, 0);
    lv_obj_set_style_bg_opa(g_now_playing_scene.state_chip, LV_OPA_COVER, 0);
    lv_label_set_text(g_now_playing_scene.state_label, state_text != NULL ? state_text : "");
    lv_obj_set_style_text_color(g_now_playing_scene.state_label, chip_text, 0);
    lv_obj_center(g_now_playing_scene.state_label);

    lv_label_set_text(g_now_playing_scene.title_label, title_text != NULL ? title_text : "");
    lv_obj_set_style_text_color(g_now_playing_scene.title_label, ink, 0);

    lv_label_set_text(g_now_playing_scene.artist_label, artist_text != NULL ? artist_text : "");
    lv_obj_set_style_text_color(g_now_playing_scene.artist_label, muted, 0);

    lv_obj_set_style_bg_color(g_now_playing_scene.progress_track, progress_bg, 0);
    lv_obj_set_style_bg_opa(g_now_playing_scene.progress_track, LV_OPA_COVER, 0);
    lv_obj_set_style_bg_color(g_now_playing_scene.progress_fill, progress_fill, 0);
    lv_obj_set_style_bg_opa(g_now_playing_scene.progress_fill, LV_OPA_COVER, 0);

    int fill_width = (168 * progress_permille) / 1000;
    if(fill_width <= 0) {
        lv_obj_add_flag(g_now_playing_scene.progress_fill, LV_OBJ_FLAG_HIDDEN);
    } else {
        lv_obj_clear_flag(g_now_playing_scene.progress_fill, LV_OBJ_FLAG_HIDDEN);
        lv_obj_set_size(g_now_playing_scene.progress_fill, fill_width, 8);
    }

    yoyopod_apply_footer_label(g_now_playing_scene.footer_label, footer, footer_text);

    if(yoyopod_activate_scene_screen(g_now_playing_scene.screen, "now-playing scene screen is unavailable during sync") < 0) {
        return -1;
    }

    return 0;
}

void yoyopod_lvgl_now_playing_destroy(void) {
    if(!g_now_playing_scene.built) {
        return;
    }

    yoyopod_release_scene_screen(g_now_playing_scene.screen);
    yoyopod_clear_group();
    yoyopod_reset_now_playing_scene_refs();
}

int yoyopod_lvgl_incoming_call_build(void) {
    if(!g_initialized || g_display == NULL) {
        yoyopod_set_error("display must be registered before building the incoming-call scene");
        return -1;
    }

    if(g_incoming_call_scene.built) {
        return 0;
    }

    g_incoming_call_scene.screen = lv_obj_create(NULL);
    if(g_incoming_call_scene.screen == NULL) {
        yoyopod_set_error("lv_obj_create(NULL) failed for incoming-call scene");
        return -1;
    }
    lv_obj_set_style_bg_color(g_incoming_call_scene.screen, yoyopod_color_u24(YOYOPOD_THEME_BACKGROUND_RGB), 0);
    lv_obj_set_style_bg_opa(g_incoming_call_scene.screen, LV_OPA_COVER, 0);
    yoyopod_status_bar_build(g_incoming_call_scene.screen, &g_incoming_call_scene.status_bar, 1);

    g_incoming_call_scene.icon_halo = lv_obj_create(g_incoming_call_scene.screen);
    lv_obj_remove_style_all(g_incoming_call_scene.icon_halo);
    lv_obj_set_size(g_incoming_call_scene.icon_halo, 124, 124);
    lv_obj_set_pos(g_incoming_call_scene.icon_halo, 58, 42);
    lv_obj_set_style_radius(g_incoming_call_scene.icon_halo, 22, 0);
    lv_obj_set_style_bg_opa(g_incoming_call_scene.icon_halo, LV_OPA_20, 0);

    g_incoming_call_scene.panel = lv_obj_create(g_incoming_call_scene.screen);
    lv_obj_remove_style_all(g_incoming_call_scene.panel);
    lv_obj_set_size(g_incoming_call_scene.panel, 112, 112);
    lv_obj_set_pos(g_incoming_call_scene.panel, 64, 48);
    lv_obj_set_style_radius(g_incoming_call_scene.panel, 16, 0);
    lv_obj_set_style_pad_all(g_incoming_call_scene.panel, 0, 0);
    lv_obj_set_style_shadow_width(g_incoming_call_scene.panel, 22, 0);
    lv_obj_set_style_shadow_opa(g_incoming_call_scene.panel, LV_OPA_30, 0);
    lv_obj_set_style_outline_width(g_incoming_call_scene.panel, 0, 0);
    lv_obj_set_scrollbar_mode(g_incoming_call_scene.panel, LV_SCROLLBAR_MODE_OFF);

    g_incoming_call_scene.icon_label = lv_label_create(g_incoming_call_scene.panel);
    lv_obj_set_style_text_font(g_incoming_call_scene.icon_label, &lv_font_montserrat_24, 0);
    lv_obj_center(g_incoming_call_scene.icon_label);

    g_incoming_call_scene.caller_name_label = lv_label_create(g_incoming_call_scene.screen);
    lv_obj_set_width(g_incoming_call_scene.caller_name_label, 180);
    lv_obj_set_pos(g_incoming_call_scene.caller_name_label, 30, 176);
    lv_label_set_long_mode(g_incoming_call_scene.caller_name_label, LV_LABEL_LONG_MODE_DOTS);
    lv_obj_set_style_text_font(g_incoming_call_scene.caller_name_label, &lv_font_montserrat_18, 0);
    lv_obj_set_style_text_align(g_incoming_call_scene.caller_name_label, LV_TEXT_ALIGN_CENTER, 0);

    g_incoming_call_scene.state_chip = lv_obj_create(g_incoming_call_scene.screen);
    lv_obj_remove_style_all(g_incoming_call_scene.state_chip);
    lv_obj_set_size(g_incoming_call_scene.state_chip, 132, 24);
    lv_obj_set_pos(g_incoming_call_scene.state_chip, 54, 208);
    lv_obj_set_style_radius(g_incoming_call_scene.state_chip, 12, 0);
    lv_obj_set_style_pad_all(g_incoming_call_scene.state_chip, 0, 0);
    lv_obj_set_scrollbar_mode(g_incoming_call_scene.state_chip, LV_SCROLLBAR_MODE_OFF);

    g_incoming_call_scene.state_label = lv_label_create(g_incoming_call_scene.state_chip);
    lv_obj_set_style_text_font(g_incoming_call_scene.state_label, &lv_font_montserrat_12, 0);
    lv_obj_center(g_incoming_call_scene.state_label);

    yoyopod_build_footer_bar(g_incoming_call_scene.screen);
    g_incoming_call_scene.footer_label = lv_label_create(g_incoming_call_scene.screen);
    yoyopod_prepare_footer_label(g_incoming_call_scene.footer_label);

    g_incoming_call_scene.built = 1;
    return 0;
}

int yoyopod_lvgl_incoming_call_sync(
    const char * caller_name,
    const char * caller_address,
    const char * footer,
    int32_t voip_state,
    int32_t battery_percent,
    int32_t charging,
    int32_t power_available,
    uint32_t accent_rgb
) {
    if(!g_incoming_call_scene.built) {
        yoyopod_set_error("incoming-call scene must be built before sync");
        return -1;
    }
    if(yoyopod_require_scene_screen(
        g_incoming_call_scene.screen,
        "incoming-call scene screen is unavailable during sync"
    ) != 0) {
        return -1;
    }

    (void)caller_address;
    const lv_color_t background = yoyopod_color_u24(YOYOPOD_THEME_BACKGROUND_RGB);
    const lv_color_t ink = yoyopod_color_u24(YOYOPOD_THEME_INK_RGB);
    const lv_color_t accent = yoyopod_color_u24(accent_rgb);
    const lv_color_t muted_dim = yoyopod_color_u24(YOYOPOD_THEME_MUTED_DIM_RGB);
    const lv_color_t accent_dim = yoyopod_mix_u24(accent_rgb, YOYOPOD_THEME_BACKGROUND_RGB, 68);
    const lv_color_t chip_fill = yoyopod_mix_u24(accent_rgb, YOYOPOD_THEME_BACKGROUND_RGB, 85);
    char monogram[3];

    lv_obj_set_style_bg_color(g_incoming_call_scene.screen, background, 0);
    lv_obj_set_style_bg_opa(g_incoming_call_scene.screen, LV_OPA_COVER, 0);
    yoyopod_status_bar_sync(
        &g_incoming_call_scene.status_bar,
        voip_state,
        NULL,
        battery_percent,
        charging,
        power_available
    );

    lv_obj_set_style_bg_color(g_incoming_call_scene.icon_halo, accent_dim, 0);
    lv_obj_set_style_bg_opa(g_incoming_call_scene.icon_halo, LV_OPA_COVER, 0);
    lv_obj_set_style_bg_color(g_incoming_call_scene.panel, accent, 0);
    lv_obj_set_style_bg_opa(g_incoming_call_scene.panel, LV_OPA_COVER, 0);
    lv_obj_set_style_border_width(g_incoming_call_scene.panel, 0, 0);
    lv_obj_set_style_shadow_color(g_incoming_call_scene.panel, accent, 0);
    yoyopod_make_monogram(caller_name, monogram);
    lv_label_set_text(g_incoming_call_scene.icon_label, monogram);
    lv_obj_set_style_text_color(g_incoming_call_scene.icon_label, ink, 0);
    lv_obj_center(g_incoming_call_scene.icon_label);

    lv_label_set_text(
        g_incoming_call_scene.caller_name_label,
        caller_name != NULL && caller_name[0] != '\0' ? caller_name : "Unknown"
    );
    lv_obj_set_style_text_color(g_incoming_call_scene.caller_name_label, ink, 0);
    lv_obj_set_style_bg_color(g_incoming_call_scene.state_chip, chip_fill, 0);
    lv_obj_set_style_bg_opa(g_incoming_call_scene.state_chip, LV_OPA_COVER, 0);
    lv_label_set_text(g_incoming_call_scene.state_label, "INCOMING CALL");
    lv_obj_set_style_text_color(g_incoming_call_scene.state_label, accent, 0);
    lv_obj_center(g_incoming_call_scene.state_label);

    yoyopod_apply_footer_label(g_incoming_call_scene.footer_label, footer, muted_dim);

    if(yoyopod_activate_scene_screen(g_incoming_call_scene.screen, "incoming-call scene screen is unavailable during sync") < 0) {
        return -1;
    }

    return 0;
}

void yoyopod_lvgl_incoming_call_destroy(void) {
    if(!g_incoming_call_scene.built) {
        return;
    }

    yoyopod_release_scene_screen(g_incoming_call_scene.screen);
    yoyopod_clear_group();
    yoyopod_reset_incoming_call_scene_refs();
}

int yoyopod_lvgl_outgoing_call_build(void) {
    if(!g_initialized || g_display == NULL) {
        yoyopod_set_error("display must be registered before building the outgoing-call scene");
        return -1;
    }

    if(g_outgoing_call_scene.built) {
        return 0;
    }

    g_outgoing_call_scene.screen = lv_obj_create(NULL);
    if(g_outgoing_call_scene.screen == NULL) {
        yoyopod_set_error("lv_obj_create(NULL) failed for outgoing-call scene");
        return -1;
    }
    lv_obj_set_style_bg_color(g_outgoing_call_scene.screen, yoyopod_color_u24(YOYOPOD_THEME_BACKGROUND_RGB), 0);
    lv_obj_set_style_bg_opa(g_outgoing_call_scene.screen, LV_OPA_COVER, 0);
    yoyopod_status_bar_build(g_outgoing_call_scene.screen, &g_outgoing_call_scene.status_bar, 1);

    g_outgoing_call_scene.icon_halo = lv_obj_create(g_outgoing_call_scene.screen);
    lv_obj_remove_style_all(g_outgoing_call_scene.icon_halo);
    lv_obj_set_size(g_outgoing_call_scene.icon_halo, 124, 124);
    lv_obj_set_pos(g_outgoing_call_scene.icon_halo, 58, 42);
    lv_obj_set_style_radius(g_outgoing_call_scene.icon_halo, 22, 0);
    lv_obj_set_style_bg_opa(g_outgoing_call_scene.icon_halo, LV_OPA_10, 0);

    g_outgoing_call_scene.panel = lv_obj_create(g_outgoing_call_scene.screen);
    lv_obj_remove_style_all(g_outgoing_call_scene.panel);
    lv_obj_set_size(g_outgoing_call_scene.panel, 112, 112);
    lv_obj_set_pos(g_outgoing_call_scene.panel, 64, 48);
    lv_obj_set_style_radius(g_outgoing_call_scene.panel, 16, 0);
    lv_obj_set_style_pad_all(g_outgoing_call_scene.panel, 0, 0);
    lv_obj_set_style_shadow_width(g_outgoing_call_scene.panel, 0, 0);
    lv_obj_set_style_outline_width(g_outgoing_call_scene.panel, 0, 0);
    lv_obj_set_scrollbar_mode(g_outgoing_call_scene.panel, LV_SCROLLBAR_MODE_OFF);

    g_outgoing_call_scene.icon_label = lv_label_create(g_outgoing_call_scene.panel);
    lv_obj_set_style_text_font(g_outgoing_call_scene.icon_label, &lv_font_montserrat_24, 0);
    lv_obj_center(g_outgoing_call_scene.icon_label);

    g_outgoing_call_scene.callee_name_label = lv_label_create(g_outgoing_call_scene.screen);
    lv_obj_set_width(g_outgoing_call_scene.callee_name_label, 180);
    lv_obj_set_pos(g_outgoing_call_scene.callee_name_label, 30, 176);
    lv_label_set_long_mode(g_outgoing_call_scene.callee_name_label, LV_LABEL_LONG_MODE_DOTS);
    lv_obj_set_style_text_font(g_outgoing_call_scene.callee_name_label, &lv_font_montserrat_18, 0);
    lv_obj_set_style_text_align(g_outgoing_call_scene.callee_name_label, LV_TEXT_ALIGN_CENTER, 0);

    g_outgoing_call_scene.state_chip = lv_obj_create(g_outgoing_call_scene.screen);
    lv_obj_remove_style_all(g_outgoing_call_scene.state_chip);
    lv_obj_set_size(g_outgoing_call_scene.state_chip, 116, 24);
    lv_obj_set_pos(g_outgoing_call_scene.state_chip, 62, 208);
    lv_obj_set_style_radius(g_outgoing_call_scene.state_chip, 12, 0);
    lv_obj_set_style_pad_all(g_outgoing_call_scene.state_chip, 0, 0);
    lv_obj_set_scrollbar_mode(g_outgoing_call_scene.state_chip, LV_SCROLLBAR_MODE_OFF);

    g_outgoing_call_scene.state_label = lv_label_create(g_outgoing_call_scene.state_chip);
    lv_obj_set_style_text_font(g_outgoing_call_scene.state_label, &lv_font_montserrat_12, 0);
    lv_obj_center(g_outgoing_call_scene.state_label);

    yoyopod_build_footer_bar(g_outgoing_call_scene.screen);
    g_outgoing_call_scene.footer_label = lv_label_create(g_outgoing_call_scene.screen);
    yoyopod_prepare_footer_label(g_outgoing_call_scene.footer_label);

    g_outgoing_call_scene.built = 1;
    return 0;
}

int yoyopod_lvgl_outgoing_call_sync(
    const char * callee_name,
    const char * callee_address,
    const char * footer,
    int32_t voip_state,
    int32_t battery_percent,
    int32_t charging,
    int32_t power_available,
    uint32_t accent_rgb
) {
    if(!g_outgoing_call_scene.built) {
        yoyopod_set_error("outgoing-call scene must be built before sync");
        return -1;
    }
    if(yoyopod_require_scene_screen(
        g_outgoing_call_scene.screen,
        "outgoing-call scene screen is unavailable during sync"
    ) != 0) {
        return -1;
    }

    (void)callee_address;
    const lv_color_t background = yoyopod_color_u24(YOYOPOD_THEME_BACKGROUND_RGB);
    const lv_color_t ink = yoyopod_color_u24(YOYOPOD_THEME_INK_RGB);
    const lv_color_t accent = yoyopod_color_u24(accent_rgb);
    const lv_color_t muted_dim = yoyopod_color_u24(YOYOPOD_THEME_MUTED_DIM_RGB);
    const lv_color_t accent_dim = yoyopod_mix_u24(accent_rgb, YOYOPOD_THEME_BACKGROUND_RGB, 68);
    const lv_color_t outlined_fill = yoyopod_mix_u24(accent_rgb, YOYOPOD_THEME_BACKGROUND_RGB, 80);
    const lv_color_t chip_fill = yoyopod_mix_u24(accent_rgb, YOYOPOD_THEME_BACKGROUND_RGB, 85);
    char monogram[3];

    lv_obj_set_style_bg_color(g_outgoing_call_scene.screen, background, 0);
    lv_obj_set_style_bg_opa(g_outgoing_call_scene.screen, LV_OPA_COVER, 0);
    yoyopod_status_bar_sync(
        &g_outgoing_call_scene.status_bar,
        voip_state,
        NULL,
        battery_percent,
        charging,
        power_available
    );

    lv_obj_set_style_bg_color(g_outgoing_call_scene.icon_halo, accent_dim, 0);
    lv_obj_set_style_bg_opa(g_outgoing_call_scene.icon_halo, LV_OPA_COVER, 0);
    lv_obj_set_style_bg_color(g_outgoing_call_scene.panel, outlined_fill, 0);
    lv_obj_set_style_bg_opa(g_outgoing_call_scene.panel, LV_OPA_COVER, 0);
    lv_obj_set_style_border_width(g_outgoing_call_scene.panel, 2, 0);
    lv_obj_set_style_border_color(g_outgoing_call_scene.panel, accent, 0);
    yoyopod_make_monogram(callee_name, monogram);
    lv_label_set_text(g_outgoing_call_scene.icon_label, monogram);
    lv_obj_set_style_text_color(g_outgoing_call_scene.icon_label, accent, 0);
    lv_obj_center(g_outgoing_call_scene.icon_label);

    lv_label_set_text(
        g_outgoing_call_scene.callee_name_label,
        callee_name != NULL && callee_name[0] != '\0' ? callee_name : "Unknown"
    );
    lv_obj_set_style_text_color(g_outgoing_call_scene.callee_name_label, ink, 0);
    lv_obj_set_style_bg_color(g_outgoing_call_scene.state_chip, chip_fill, 0);
    lv_obj_set_style_bg_opa(g_outgoing_call_scene.state_chip, LV_OPA_COVER, 0);
    lv_label_set_text(g_outgoing_call_scene.state_label, "CALLING...");
    lv_obj_set_style_text_color(g_outgoing_call_scene.state_label, accent, 0);
    lv_obj_center(g_outgoing_call_scene.state_label);

    yoyopod_apply_footer_label(g_outgoing_call_scene.footer_label, footer, muted_dim);

    if(yoyopod_activate_scene_screen(g_outgoing_call_scene.screen, "outgoing-call scene screen is unavailable during sync") < 0) {
        return -1;
    }

    return 0;
}

void yoyopod_lvgl_outgoing_call_destroy(void) {
    if(!g_outgoing_call_scene.built) {
        return;
    }

    yoyopod_release_scene_screen(g_outgoing_call_scene.screen);
    yoyopod_clear_group();
    yoyopod_reset_outgoing_call_scene_refs();
}

int yoyopod_lvgl_in_call_build(void) {
    if(!g_initialized || g_display == NULL) {
        yoyopod_set_error("display must be registered before building the in-call scene");
        return -1;
    }

    if(g_in_call_scene.built) {
        return 0;
    }

    g_in_call_scene.screen = lv_obj_create(NULL);
    if(g_in_call_scene.screen == NULL) {
        yoyopod_set_error("lv_obj_create(NULL) failed for in-call scene");
        return -1;
    }
    lv_obj_set_style_bg_color(g_in_call_scene.screen, yoyopod_color_u24(YOYOPOD_THEME_BACKGROUND_RGB), 0);
    lv_obj_set_style_bg_opa(g_in_call_scene.screen, LV_OPA_COVER, 0);
    yoyopod_status_bar_build(g_in_call_scene.screen, &g_in_call_scene.status_bar, 1);

    g_in_call_scene.icon_halo = lv_obj_create(g_in_call_scene.screen);
    lv_obj_remove_style_all(g_in_call_scene.icon_halo);
    lv_obj_set_size(g_in_call_scene.icon_halo, 124, 124);
    lv_obj_set_pos(g_in_call_scene.icon_halo, 58, 42);
    lv_obj_set_style_radius(g_in_call_scene.icon_halo, 22, 0);
    lv_obj_set_style_bg_opa(g_in_call_scene.icon_halo, LV_OPA_20, 0);

    g_in_call_scene.panel = lv_obj_create(g_in_call_scene.screen);
    lv_obj_remove_style_all(g_in_call_scene.panel);
    lv_obj_set_size(g_in_call_scene.panel, 112, 112);
    lv_obj_set_pos(g_in_call_scene.panel, 64, 48);
    lv_obj_set_style_radius(g_in_call_scene.panel, 16, 0);
    lv_obj_set_style_pad_all(g_in_call_scene.panel, 0, 0);
    lv_obj_set_style_shadow_width(g_in_call_scene.panel, 22, 0);
    lv_obj_set_style_shadow_opa(g_in_call_scene.panel, LV_OPA_30, 0);
    lv_obj_set_style_outline_width(g_in_call_scene.panel, 0, 0);
    lv_obj_set_scrollbar_mode(g_in_call_scene.panel, LV_SCROLLBAR_MODE_OFF);

    g_in_call_scene.icon_label = lv_label_create(g_in_call_scene.panel);
    lv_obj_set_style_text_font(g_in_call_scene.icon_label, &lv_font_montserrat_24, 0);
    lv_obj_center(g_in_call_scene.icon_label);

    g_in_call_scene.caller_name_label = lv_label_create(g_in_call_scene.screen);
    lv_obj_set_width(g_in_call_scene.caller_name_label, 180);
    lv_obj_set_pos(g_in_call_scene.caller_name_label, 30, 176);
    lv_label_set_long_mode(g_in_call_scene.caller_name_label, LV_LABEL_LONG_MODE_DOTS);
    lv_obj_set_style_text_font(g_in_call_scene.caller_name_label, &lv_font_montserrat_18, 0);
    lv_obj_set_style_text_align(g_in_call_scene.caller_name_label, LV_TEXT_ALIGN_CENTER, 0);

    g_in_call_scene.state_chip = lv_obj_create(g_in_call_scene.screen);
    lv_obj_remove_style_all(g_in_call_scene.state_chip);
    lv_obj_set_size(g_in_call_scene.state_chip, 144, 24);
    lv_obj_set_pos(g_in_call_scene.state_chip, 48, 206);
    lv_obj_set_style_radius(g_in_call_scene.state_chip, 12, 0);
    lv_obj_set_style_pad_all(g_in_call_scene.state_chip, 0, 0);
    lv_obj_set_scrollbar_mode(g_in_call_scene.state_chip, LV_SCROLLBAR_MODE_OFF);

    g_in_call_scene.duration_label = lv_label_create(g_in_call_scene.state_chip);
    lv_obj_set_style_text_font(g_in_call_scene.duration_label, &lv_font_montserrat_12, 0);
    lv_obj_center(g_in_call_scene.duration_label);

    g_in_call_scene.mute_chip = lv_obj_create(g_in_call_scene.screen);
    lv_obj_remove_style_all(g_in_call_scene.mute_chip);
    lv_obj_set_size(g_in_call_scene.mute_chip, 96, 24);
    lv_obj_set_pos(g_in_call_scene.mute_chip, 72, 232);
    lv_obj_set_style_radius(g_in_call_scene.mute_chip, 12, 0);
    lv_obj_set_style_pad_all(g_in_call_scene.mute_chip, 0, 0);
    lv_obj_set_scrollbar_mode(g_in_call_scene.mute_chip, LV_SCROLLBAR_MODE_OFF);
    lv_obj_add_flag(g_in_call_scene.mute_chip, LV_OBJ_FLAG_HIDDEN);

    g_in_call_scene.mute_label = lv_label_create(g_in_call_scene.mute_chip);
    lv_obj_set_style_text_font(g_in_call_scene.mute_label, &lv_font_montserrat_12, 0);
    lv_obj_center(g_in_call_scene.mute_label);

    yoyopod_build_footer_bar(g_in_call_scene.screen);
    g_in_call_scene.footer_label = lv_label_create(g_in_call_scene.screen);
    yoyopod_prepare_footer_label(g_in_call_scene.footer_label);

    g_in_call_scene.built = 1;
    return 0;
}

int yoyopod_lvgl_in_call_sync(
    const char * caller_name,
    const char * duration_text,
    const char * mute_text,
    const char * footer,
    int32_t muted,
    int32_t voip_state,
    int32_t battery_percent,
    int32_t charging,
    int32_t power_available,
    uint32_t accent_rgb
) {
    if(!g_in_call_scene.built) {
        yoyopod_set_error("in-call scene must be built before sync");
        return -1;
    }
    if(yoyopod_require_scene_screen(g_in_call_scene.screen, "in-call scene screen is unavailable during sync") != 0) {
        return -1;
    }

    const lv_color_t background = yoyopod_color_u24(YOYOPOD_THEME_BACKGROUND_RGB);
    const lv_color_t ink = yoyopod_color_u24(YOYOPOD_THEME_INK_RGB);
    const lv_color_t accent = yoyopod_color_u24(accent_rgb);
    const lv_color_t muted_dim = yoyopod_color_u24(YOYOPOD_THEME_MUTED_DIM_RGB);
    const lv_color_t accent_dim = yoyopod_mix_u24(accent_rgb, YOYOPOD_THEME_BACKGROUND_RGB, 68);
    const lv_color_t success = yoyopod_color_u24(YOYOPOD_THEME_SUCCESS_RGB);
    const lv_color_t success_fill = yoyopod_mix_u24(YOYOPOD_THEME_SUCCESS_RGB, YOYOPOD_THEME_BACKGROUND_RGB, 85);
    const lv_color_t error = yoyopod_color_u24(YOYOPOD_THEME_ERROR_RGB);
    const lv_color_t error_fill = yoyopod_mix_u24(YOYOPOD_THEME_ERROR_RGB, YOYOPOD_THEME_BACKGROUND_RGB, 85);
    char monogram[3];

    lv_obj_set_style_bg_color(g_in_call_scene.screen, background, 0);
    lv_obj_set_style_bg_opa(g_in_call_scene.screen, LV_OPA_COVER, 0);
    yoyopod_status_bar_sync(
        &g_in_call_scene.status_bar,
        voip_state,
        NULL,
        battery_percent,
        charging,
        power_available
    );

    lv_obj_set_style_bg_color(g_in_call_scene.icon_halo, accent_dim, 0);
    lv_obj_set_style_bg_opa(g_in_call_scene.icon_halo, LV_OPA_COVER, 0);
    lv_obj_set_style_bg_color(g_in_call_scene.panel, accent, 0);
    lv_obj_set_style_bg_opa(g_in_call_scene.panel, LV_OPA_COVER, 0);
    lv_obj_set_style_border_width(g_in_call_scene.panel, 0, 0);
    lv_obj_set_style_shadow_color(g_in_call_scene.panel, accent, 0);
    yoyopod_make_monogram(caller_name, monogram);
    lv_label_set_text(g_in_call_scene.icon_label, monogram);
    lv_obj_set_style_text_color(g_in_call_scene.icon_label, ink, 0);
    lv_obj_center(g_in_call_scene.icon_label);

    lv_label_set_text(
        g_in_call_scene.caller_name_label,
        caller_name != NULL && caller_name[0] != '\0' ? caller_name : "Unknown"
    );
    lv_obj_set_style_text_color(g_in_call_scene.caller_name_label, ink, 0);
    lv_obj_set_style_bg_color(g_in_call_scene.state_chip, success_fill, 0);
    lv_obj_set_style_bg_opa(g_in_call_scene.state_chip, LV_OPA_COVER, 0);
    lv_label_set_text(g_in_call_scene.duration_label, duration_text != NULL ? duration_text : "IN CALL | 00:00");
    lv_obj_set_style_text_color(g_in_call_scene.duration_label, success, 0);
    lv_obj_center(g_in_call_scene.duration_label);

    if(muted) {
        lv_obj_clear_flag(g_in_call_scene.mute_chip, LV_OBJ_FLAG_HIDDEN);
        lv_obj_set_style_bg_color(g_in_call_scene.mute_chip, error_fill, 0);
        lv_obj_set_style_bg_opa(g_in_call_scene.mute_chip, LV_OPA_COVER, 0);
        lv_label_set_text(g_in_call_scene.mute_label, mute_text != NULL && mute_text[0] != '\0' ? mute_text : "MUTED");
        lv_obj_set_style_text_color(g_in_call_scene.mute_label, error, 0);
        lv_obj_center(g_in_call_scene.mute_label);
    } else {
        lv_obj_add_flag(g_in_call_scene.mute_chip, LV_OBJ_FLAG_HIDDEN);
    }

    yoyopod_apply_footer_label(g_in_call_scene.footer_label, footer, muted_dim);

    if(yoyopod_activate_scene_screen(g_in_call_scene.screen, "in-call scene screen is unavailable during sync") < 0) {
        return -1;
    }

    return 0;
}

void yoyopod_lvgl_in_call_destroy(void) {
    if(!g_in_call_scene.built) {
        return;
    }

    yoyopod_release_scene_screen(g_in_call_scene.screen);
    yoyopod_clear_group();
    yoyopod_reset_in_call_scene_refs();
}

int yoyopod_lvgl_ask_build(void) {
    if(!g_initialized || g_display == NULL) {
        yoyopod_set_error("display must be registered before building the ask scene");
        return -1;
    }

    if(g_ask_scene.built) {
        return 0;
    }

    g_ask_scene.screen = lv_obj_create(NULL);
    if(g_ask_scene.screen == NULL) {
        yoyopod_set_error("lv_obj_create(NULL) failed for ask scene");
        return -1;
    }
    lv_obj_set_style_bg_color(g_ask_scene.screen, yoyopod_color_u24(YOYOPOD_THEME_BACKGROUND_RGB), 0);
    lv_obj_set_style_bg_opa(g_ask_scene.screen, LV_OPA_COVER, 0);
    yoyopod_status_bar_build(g_ask_scene.screen, &g_ask_scene.status_bar, 1);

    g_ask_scene.icon_glow = lv_obj_create(g_ask_scene.screen);
    lv_obj_remove_style_all(g_ask_scene.icon_glow);
    lv_obj_set_size(g_ask_scene.icon_glow, 120, 120);
    lv_obj_set_pos(g_ask_scene.icon_glow, 60, 44);
    lv_obj_set_style_radius(g_ask_scene.icon_glow, LV_RADIUS_CIRCLE, 0);
    lv_obj_set_style_border_width(g_ask_scene.icon_glow, 0, 0);
    lv_obj_set_style_shadow_spread(g_ask_scene.icon_glow, 0, 0);
    lv_obj_set_scrollbar_mode(g_ask_scene.icon_glow, LV_SCROLLBAR_MODE_OFF);

    g_ask_scene.icon_halo = lv_obj_create(g_ask_scene.screen);
    lv_obj_remove_style_all(g_ask_scene.icon_halo);
    lv_obj_set_size(g_ask_scene.icon_halo, 96, 96);
    lv_obj_set_pos(g_ask_scene.icon_halo, 72, 56);
    lv_obj_set_style_radius(g_ask_scene.icon_halo, LV_RADIUS_CIRCLE, 0);
    lv_obj_set_style_border_width(g_ask_scene.icon_halo, 0, 0);
    lv_obj_set_style_shadow_width(g_ask_scene.icon_halo, 0, 0);
    lv_obj_set_style_outline_width(g_ask_scene.icon_halo, 0, 0);
    lv_obj_set_scrollbar_mode(g_ask_scene.icon_halo, LV_SCROLLBAR_MODE_OFF);

    g_ask_scene.icon_image = lv_image_create(g_ask_scene.icon_halo);
    lv_obj_set_style_image_recolor_opa(g_ask_scene.icon_image, LV_OPA_COVER, 0);
    lv_obj_set_style_image_opa(g_ask_scene.icon_image, LV_OPA_COVER, 0);
    lv_obj_center(g_ask_scene.icon_image);

    g_ask_scene.title_label = lv_label_create(g_ask_scene.screen);
    lv_obj_set_width(g_ask_scene.title_label, 200);
    lv_obj_set_pos(g_ask_scene.title_label, 20, 176);
    lv_label_set_long_mode(g_ask_scene.title_label, LV_LABEL_LONG_MODE_WRAP);
    lv_obj_set_style_text_font(g_ask_scene.title_label, &lv_font_montserrat_24, 0);
    lv_obj_set_style_text_align(g_ask_scene.title_label, LV_TEXT_ALIGN_CENTER, 0);

    g_ask_scene.subtitle_label = lv_label_create(g_ask_scene.screen);
    lv_obj_set_width(g_ask_scene.subtitle_label, 192);
    lv_obj_set_pos(g_ask_scene.subtitle_label, 24, 212);
    lv_label_set_long_mode(g_ask_scene.subtitle_label, LV_LABEL_LONG_MODE_WRAP);
    lv_obj_set_style_text_font(g_ask_scene.subtitle_label, &lv_font_montserrat_14, 0);
    lv_obj_set_style_text_align(g_ask_scene.subtitle_label, LV_TEXT_ALIGN_CENTER, 0);

    yoyopod_build_footer_bar(g_ask_scene.screen);
    g_ask_scene.footer_label = lv_label_create(g_ask_scene.screen);
    yoyopod_prepare_footer_label(g_ask_scene.footer_label);

    g_ask_scene.built = 1;
    return 0;
}

int yoyopod_lvgl_ask_sync(
    const char * icon_key,
    const char * title_text,
    const char * subtitle_text,
    const char * footer,
    int32_t voip_state,
    int32_t battery_percent,
    int32_t charging,
    int32_t power_available,
    uint32_t accent_rgb
) {
    if(!g_ask_scene.built) {
        yoyopod_set_error("ask scene must be built before sync");
        return -1;
    }
    if(yoyopod_require_scene_screen(g_ask_scene.screen, "ask scene screen is unavailable during sync") != 0) {
        return -1;
    }

    const lv_color_t background = yoyopod_color_u24(YOYOPOD_THEME_BACKGROUND_RGB);
    const lv_color_t ink = yoyopod_color_u24(YOYOPOD_THEME_INK_RGB);
    const lv_color_t muted = yoyopod_color_u24(YOYOPOD_THEME_MUTED_RGB);
    const lv_color_t muted_dim = yoyopod_color_u24(YOYOPOD_THEME_MUTED_DIM_RGB);
    const lv_color_t accent = yoyopod_color_u24(accent_rgb);
    const lv_color_t halo_fill_idle = yoyopod_mix_u24(accent_rgb, YOYOPOD_THEME_BACKGROUND_RGB, 74);
    const lv_color_t halo_fill_listening = yoyopod_mix_u24(accent_rgb, YOYOPOD_THEME_BACKGROUND_RGB, 68);
    const lv_color_t glow_fill = yoyopod_mix_u24(accent_rgb, YOYOPOD_THEME_BACKGROUND_RGB, 82);
    const lv_color_t glow_fill_listening = yoyopod_mix_u24(accent_rgb, YOYOPOD_THEME_BACKGROUND_RGB, 76);
    const int state_is_listening = title_text != NULL && strcmp(title_text, "Listening") == 0;
    const int state_is_thinking = title_text != NULL && strcmp(title_text, "Thinking") == 0;
    const int state_is_idle = title_text != NULL && strcmp(title_text, "Ask") == 0;
    const int state_is_reply = !state_is_listening && !state_is_thinking && !state_is_idle;
    const char * active_icon_key =
        icon_key != NULL && icon_key[0] != '\0' ? icon_key : "ask";

    lv_obj_set_style_bg_color(g_ask_scene.screen, background, 0);
    lv_obj_set_style_bg_opa(g_ask_scene.screen, LV_OPA_COVER, 0);
    yoyopod_status_bar_sync(
        &g_ask_scene.status_bar,
        voip_state,
        NULL,
        battery_percent,
        charging,
        power_available
    );

    lv_label_set_text(g_ask_scene.title_label, title_text != NULL ? title_text : "");
    lv_label_set_text(g_ask_scene.subtitle_label, subtitle_text != NULL ? subtitle_text : "");
    lv_obj_set_style_text_color(g_ask_scene.title_label, ink, 0);
    lv_image_set_src(g_ask_scene.icon_image, yoyopod_hub_icon_for_key(active_icon_key));
    lv_obj_set_style_image_recolor(g_ask_scene.icon_image, accent, 0);
    lv_obj_center(g_ask_scene.icon_image);

    if(state_is_reply) {
        lv_obj_add_flag(g_ask_scene.icon_glow, LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag(g_ask_scene.icon_halo, LV_OBJ_FLAG_HIDDEN);

        lv_obj_set_width(g_ask_scene.title_label, 192);
        lv_obj_set_pos(g_ask_scene.title_label, 24, 48);
        lv_obj_set_style_text_font(g_ask_scene.title_label, &lv_font_montserrat_18, 0);
        lv_obj_set_style_text_align(g_ask_scene.title_label, LV_TEXT_ALIGN_LEFT, 0);

        lv_obj_set_width(g_ask_scene.subtitle_label, 192);
        lv_obj_set_pos(g_ask_scene.subtitle_label, 24, 84);
        lv_obj_set_style_text_font(g_ask_scene.subtitle_label, &lv_font_montserrat_16, 0);
        lv_obj_set_style_text_align(g_ask_scene.subtitle_label, LV_TEXT_ALIGN_LEFT, 0);
        lv_obj_set_style_text_color(g_ask_scene.subtitle_label, muted, 0);
    } else {
        const lv_color_t halo_fill =
            state_is_listening ? halo_fill_listening : halo_fill_idle;
        const lv_color_t glow_color =
            state_is_listening ? glow_fill_listening : glow_fill;
        const int glow_opa =
            state_is_listening ? LV_OPA_50 : (state_is_thinking ? LV_OPA_20 : LV_OPA_30);
        const int shadow_opa =
            state_is_listening ? LV_OPA_40 : (state_is_thinking ? LV_OPA_20 : LV_OPA_30);
        const int shadow_width = state_is_listening ? 42 : (state_is_thinking ? 22 : 28);

        lv_obj_clear_flag(g_ask_scene.icon_glow, LV_OBJ_FLAG_HIDDEN);
        lv_obj_clear_flag(g_ask_scene.icon_halo, LV_OBJ_FLAG_HIDDEN);

        lv_obj_set_style_bg_color(g_ask_scene.icon_glow, glow_color, 0);
        lv_obj_set_style_bg_opa(g_ask_scene.icon_glow, glow_opa, 0);
        lv_obj_set_style_shadow_color(g_ask_scene.icon_glow, accent, 0);
        lv_obj_set_style_shadow_width(g_ask_scene.icon_glow, shadow_width, 0);
        lv_obj_set_style_shadow_opa(g_ask_scene.icon_glow, shadow_opa, 0);

        lv_obj_set_style_bg_color(g_ask_scene.icon_halo, halo_fill, 0);
        lv_obj_set_style_bg_opa(g_ask_scene.icon_halo, LV_OPA_COVER, 0);

        lv_obj_set_width(g_ask_scene.title_label, 200);
        lv_obj_set_pos(g_ask_scene.title_label, 20, 176);
        lv_obj_set_style_text_font(g_ask_scene.title_label, &lv_font_montserrat_24, 0);
        lv_obj_set_style_text_align(g_ask_scene.title_label, LV_TEXT_ALIGN_CENTER, 0);

        lv_obj_set_width(g_ask_scene.subtitle_label, 192);
        lv_obj_set_pos(g_ask_scene.subtitle_label, 24, 212);
        lv_obj_set_style_text_font(g_ask_scene.subtitle_label, &lv_font_montserrat_14, 0);
        lv_obj_set_style_text_align(g_ask_scene.subtitle_label, LV_TEXT_ALIGN_CENTER, 0);
        lv_obj_set_style_text_color(
            g_ask_scene.subtitle_label,
            state_is_thinking ? muted : accent,
            0
        );
    }

    yoyopod_apply_footer_label(g_ask_scene.footer_label, footer, muted_dim);

    if(yoyopod_activate_scene_screen(g_ask_scene.screen, "ask scene screen is unavailable during sync") < 0) {
        return -1;
    }

    return 0;
}

void yoyopod_lvgl_ask_destroy(void) {
    if(!g_ask_scene.built) {
        return;
    }

    yoyopod_release_scene_screen(g_ask_scene.screen);
    yoyopod_clear_group();
    yoyopod_reset_ask_scene_refs();
}

int yoyopod_lvgl_power_build(void) {
    if(!g_initialized || g_display == NULL) {
        yoyopod_set_error("display must be registered before building the power scene");
        return -1;
    }

    if(g_power_scene.built) {
        return 0;
    }

    g_power_scene.screen = lv_obj_create(NULL);
    if(g_power_scene.screen == NULL) {
        yoyopod_set_error("lv_obj_create(NULL) failed for power scene");
        return -1;
    }
    lv_obj_set_style_bg_color(g_power_scene.screen, yoyopod_color_u24(YOYOPOD_THEME_BACKGROUND_RGB), 0);
    lv_obj_set_style_bg_opa(g_power_scene.screen, LV_OPA_COVER, 0);
    yoyopod_status_bar_build(g_power_scene.screen, &g_power_scene.status_bar, 0);

    g_power_scene.icon_halo = lv_obj_create(g_power_scene.screen);
    lv_obj_set_size(g_power_scene.icon_halo, 56, 56);
    lv_obj_set_pos(g_power_scene.icon_halo, 92, 42);
    lv_obj_set_style_radius(g_power_scene.icon_halo, LV_RADIUS_CIRCLE, 0);
    lv_obj_set_style_border_width(g_power_scene.icon_halo, 0, 0);
    lv_obj_set_style_pad_all(g_power_scene.icon_halo, 0, 0);
    lv_obj_set_style_shadow_width(g_power_scene.icon_halo, 0, 0);
    lv_obj_set_style_outline_width(g_power_scene.icon_halo, 0, 0);
    lv_obj_set_scrollbar_mode(g_power_scene.icon_halo, LV_SCROLLBAR_MODE_OFF);

    g_power_scene.icon_label = lv_label_create(g_power_scene.icon_halo);
    lv_obj_set_style_text_font(g_power_scene.icon_label, &lv_font_montserrat_24, 0);
    lv_obj_center(g_power_scene.icon_label);

    g_power_scene.title_label = lv_label_create(g_power_scene.screen);
    lv_label_set_text(g_power_scene.title_label, "Power");
    lv_obj_set_width(g_power_scene.title_label, 120);
    lv_obj_set_pos(g_power_scene.title_label, 60, 98);
    lv_obj_set_style_text_font(g_power_scene.title_label, &lv_font_montserrat_24, 0);
    lv_obj_set_style_text_align(g_power_scene.title_label, LV_TEXT_ALIGN_CENTER, 0);

    for(int index = 0; index < YOYOPOD_POWER_MAX_ITEMS; ++index) {
        g_power_scene.item_panels[index] = lv_obj_create(g_power_scene.screen);
        lv_obj_set_size(g_power_scene.item_panels[index], 208, 18);
        lv_obj_set_pos(g_power_scene.item_panels[index], 16, 126 + (index * 22));
        lv_obj_set_style_radius(g_power_scene.item_panels[index], 10, 0);
        lv_obj_set_style_border_width(g_power_scene.item_panels[index], 0, 0);
        lv_obj_set_style_pad_left(g_power_scene.item_panels[index], 12, 0);
        lv_obj_set_style_pad_right(g_power_scene.item_panels[index], 12, 0);
        lv_obj_set_style_pad_top(g_power_scene.item_panels[index], 2, 0);
        lv_obj_set_style_pad_bottom(g_power_scene.item_panels[index], 2, 0);
        lv_obj_set_style_shadow_width(g_power_scene.item_panels[index], 0, 0);
        lv_obj_set_style_outline_width(g_power_scene.item_panels[index], 0, 0);
        lv_obj_set_scrollbar_mode(g_power_scene.item_panels[index], LV_SCROLLBAR_MODE_OFF);

        g_power_scene.item_titles[index] = lv_label_create(g_power_scene.item_panels[index]);
        lv_obj_set_width(g_power_scene.item_titles[index], 184);
        lv_label_set_long_mode(g_power_scene.item_titles[index], LV_LABEL_LONG_MODE_CLIP);
        lv_obj_set_style_text_font(g_power_scene.item_titles[index], &lv_font_montserrat_12, 0);
        lv_obj_set_style_text_align(g_power_scene.item_titles[index], LV_TEXT_ALIGN_LEFT, 0);
        lv_obj_center(g_power_scene.item_titles[index]);
    }

    for(int index = 0; index < YOYOPOD_POWER_MAX_DOTS; ++index) {
        g_power_scene.dots[index] = lv_obj_create(g_power_scene.screen);
        lv_obj_remove_style_all(g_power_scene.dots[index]);
        lv_obj_set_style_bg_opa(g_power_scene.dots[index], LV_OPA_COVER, 0);
        lv_obj_set_style_radius(g_power_scene.dots[index], LV_RADIUS_CIRCLE, 0);
    }

    g_power_scene.footer_label = lv_label_create(g_power_scene.screen);
    yoyopod_prepare_footer_label(g_power_scene.footer_label);

    g_power_scene.built = 1;
    return 0;
}

int yoyopod_lvgl_power_sync(
    const char * title_text,
    const char * page_text,
    const char * icon_key,
    const char * footer,
    const char * item_0,
    const char * item_1,
    const char * item_2,
    const char * item_3,
    const char * item_4,
    int32_t item_count,
    int32_t current_page_index,
    int32_t total_pages,
    int32_t voip_state,
    int32_t battery_percent,
    int32_t charging,
    int32_t power_available,
    uint32_t accent_rgb
) {
    if(!g_power_scene.built) {
        yoyopod_set_error("power scene must be built before sync");
        return -1;
    }
    if(yoyopod_require_scene_screen(g_power_scene.screen, "power scene screen is unavailable during sync") != 0) {
        return -1;
    }

    const lv_color_t background = yoyopod_color_u24(YOYOPOD_THEME_BACKGROUND_RGB);
    const lv_color_t row_fill = yoyopod_color_u24(YOYOPOD_THEME_SURFACE_RAISED_RGB);
    const lv_color_t ink = yoyopod_color_u24(YOYOPOD_THEME_INK_RGB);
    const lv_color_t accent = yoyopod_color_u24(accent_rgb);
    const lv_color_t accent_dim = yoyopod_mix_u24(accent_rgb, YOYOPOD_THEME_BACKGROUND_RGB, 65);
    const lv_color_t muted = yoyopod_color_u24(YOYOPOD_THEME_MUTED_RGB);
    const char * rows[YOYOPOD_POWER_MAX_ITEMS] = {item_0, item_1, item_2, item_3, item_4};

    (void)page_text;

    lv_obj_set_style_bg_color(g_power_scene.screen, background, 0);
    lv_obj_set_style_bg_opa(g_power_scene.screen, LV_OPA_COVER, 0);
    yoyopod_status_bar_sync(
        &g_power_scene.status_bar,
        voip_state,
        NULL,
        battery_percent,
        charging,
        power_available
    );

    lv_obj_set_style_bg_color(g_power_scene.icon_halo, yoyopod_color_u24(0x494D59), 0);
    lv_obj_set_style_bg_opa(g_power_scene.icon_halo, LV_OPA_COVER, 0);
    lv_label_set_text(g_power_scene.icon_label, yoyopod_symbol_for_empty_icon(icon_key));
    lv_obj_set_style_text_color(g_power_scene.icon_label, ink, 0);
    lv_obj_center(g_power_scene.icon_label);

    lv_label_set_text(g_power_scene.title_label, title_text != NULL ? title_text : "Setup");
    lv_obj_set_style_text_color(g_power_scene.title_label, ink, 0);

    for(int index = 0; index < YOYOPOD_POWER_MAX_ITEMS; ++index) {
        if(index < item_count && rows[index] != NULL && rows[index][0] != '\0') {
            lv_obj_clear_flag(g_power_scene.item_panels[index], LV_OBJ_FLAG_HIDDEN);
            lv_obj_set_style_bg_color(g_power_scene.item_panels[index], row_fill, 0);
            lv_obj_set_style_bg_opa(g_power_scene.item_panels[index], LV_OPA_COVER, 0);
            lv_label_set_text(g_power_scene.item_titles[index], rows[index]);
            lv_obj_set_style_text_color(g_power_scene.item_titles[index], ink, 0);
            lv_obj_center(g_power_scene.item_titles[index]);
        } else {
            lv_obj_add_flag(g_power_scene.item_panels[index], LV_OBJ_FLAG_HIDDEN);
        }
    }

    if(total_pages < 0) {
        total_pages = 0;
    }
    if(total_pages > YOYOPOD_POWER_MAX_DOTS) {
        total_pages = YOYOPOD_POWER_MAX_DOTS;
    }
    if(total_pages > 0) {
        current_page_index = current_page_index % total_pages;
        if(current_page_index < 0) {
            current_page_index += total_pages;
        }
    } else if(current_page_index < 0) {
        current_page_index = 0;
    }
    for(int index = 0; index < YOYOPOD_POWER_MAX_DOTS; ++index) {
        if(index >= total_pages) {
            lv_obj_add_flag(g_power_scene.dots[index], LV_OBJ_FLAG_HIDDEN);
            continue;
        }
        lv_obj_clear_flag(g_power_scene.dots[index], LV_OBJ_FLAG_HIDDEN);
        int size = 4;
        int first_x = 118 - (((total_pages - 1) * 10) / 2);
        lv_obj_set_pos(g_power_scene.dots[index], first_x + (index * 10), 238);
        lv_obj_set_size(g_power_scene.dots[index], size, size);
        lv_obj_set_style_bg_color(g_power_scene.dots[index], index == current_page_index ? accent : muted, 0);
    }

    yoyopod_apply_footer_label(g_power_scene.footer_label, footer, accent_dim);

    if(yoyopod_activate_scene_screen(g_power_scene.screen, "power scene screen is unavailable during sync") < 0) {
        return -1;
    }

    return 0;
}

void yoyopod_lvgl_power_destroy(void) {
    if(!g_power_scene.built) {
        return;
    }

    yoyopod_release_scene_screen(g_power_scene.screen);
    yoyopod_clear_group();
    yoyopod_reset_power_scene_refs();
}

int yoyopod_lvgl_init(void) {
    if(g_initialized) {
        return 0;
    }

    yoyopod_set_error(NULL);
    lv_init();
    g_initialized = 1;
    return 0;
}

void yoyopod_lvgl_shutdown(void) {
    yoyopod_lvgl_clear_screen();

    if(g_blank_screen != NULL) {
        lv_obj_delete(g_blank_screen);
        g_blank_screen = NULL;
    }

    if(g_draw_buf != NULL) {
        lv_free(g_draw_buf);
        g_draw_buf = NULL;
    }

    if(g_group != NULL) {
        lv_group_delete(g_group);
        g_group = NULL;
    }

    g_display = NULL;
    g_indev = NULL;
    g_flush_cb = NULL;
    g_flush_user_data = NULL;
    g_draw_buf_bytes = 0;
    g_key_head = 0;
    g_key_tail = 0;
    g_key_count = 0;
    g_initialized = 0;
    yoyopod_set_error(NULL);
}

int yoyopod_lvgl_register_display(
    int32_t width,
    int32_t height,
    uint32_t buffer_pixel_count,
    yoyopod_lvgl_flush_cb_t flush_cb,
    void * user_data
) {
    if(!g_initialized) {
        yoyopod_set_error("LVGL must be initialized before registering a display");
        return -1;
    }

    if(g_display != NULL) {
        yoyopod_set_error("display already registered");
        return -1;
    }

    if(flush_cb == NULL) {
        yoyopod_set_error("flush callback is required");
        return -1;
    }

    g_display = lv_display_create(width, height);
    if(g_display == NULL) {
        yoyopod_set_error("lv_display_create failed");
        return -1;
    }

    /* Whisplay expects RGB565 bytes in swapped/big-endian wire order. */
    lv_display_set_color_format(g_display, LV_COLOR_FORMAT_RGB565_SWAPPED);

    g_draw_buf_bytes = buffer_pixel_count * lv_color_format_get_size(lv_display_get_color_format(g_display));
    g_draw_buf = lv_malloc(g_draw_buf_bytes);
    if(g_draw_buf == NULL) {
        yoyopod_set_error("draw buffer allocation failed");
        return -1;
    }

    g_flush_cb = flush_cb;
    g_flush_user_data = user_data;

    lv_display_set_flush_cb(g_display, yoyopod_flush_cb);
    lv_display_set_buffers(
        g_display,
        g_draw_buf,
        NULL,
        g_draw_buf_bytes,
        LV_DISPLAY_RENDER_MODE_PARTIAL
    );

    return 0;
}

int yoyopod_lvgl_register_input(void) {
    if(!g_initialized || g_display == NULL) {
        yoyopod_set_error("display must be registered before input");
        return -1;
    }

    if(g_group == NULL) {
        g_group = lv_group_create();
        lv_group_set_default(g_group);
    }

    if(g_indev == NULL) {
        g_indev = lv_indev_create();
        if(g_indev == NULL) {
            yoyopod_set_error("lv_indev_create failed");
            return -1;
        }
        lv_indev_set_type(g_indev, LV_INDEV_TYPE_KEYPAD);
        lv_indev_set_read_cb(g_indev, yoyopod_indev_read_cb);
        lv_indev_set_group(g_indev, g_group);
    }

    return 0;
}

void yoyopod_lvgl_tick_inc(uint32_t ms) {
    if(g_initialized) {
        lv_tick_inc(ms);
    }
}

uint32_t yoyopod_lvgl_timer_handler(void) {
    if(!g_initialized) {
        return 0U;
    }

    return lv_timer_handler();
}

int yoyopod_lvgl_queue_key_event(int32_t key, int32_t pressed) {
    if(g_key_count >= KEY_QUEUE_CAPACITY) {
        yoyopod_set_error("input queue full");
        return -1;
    }

    g_key_queue[g_key_tail].key = key;
    g_key_queue[g_key_tail].pressed = pressed;
    g_key_tail = (g_key_tail + 1) % KEY_QUEUE_CAPACITY;
    g_key_count++;
    return 0;
}

int yoyopod_lvgl_show_probe_scene(int32_t scene_id) {
    if(!g_initialized || g_display == NULL) {
        yoyopod_set_error("display must be registered before showing a scene");
        return -1;
    }

    switch(scene_id) {
        case YOYOPOD_LVGL_SCENE_CARD:
            yoyopod_build_card_scene();
            break;
        case YOYOPOD_LVGL_SCENE_LIST:
            yoyopod_build_list_scene();
            break;
        case YOYOPOD_LVGL_SCENE_FOOTER:
            yoyopod_build_footer_scene();
            break;
        case YOYOPOD_LVGL_SCENE_CAROUSEL:
            yoyopod_build_carousel_scene();
            break;
        default:
            yoyopod_set_error("unknown probe scene");
            return -1;
    }

    return 0;
}

void yoyopod_lvgl_clear_screen(void) {
    if(!g_initialized || g_display == NULL) {
        return;
    }

    yoyopod_release_scene_screen(g_hub_scene.screen);
    yoyopod_release_scene_screen(g_talk_scene.screen);
    yoyopod_release_scene_screen(g_talk_actions_scene.screen);
    yoyopod_release_scene_screen(g_listen_scene.screen);
    yoyopod_release_scene_screen(g_playlist_scene.screen);
    yoyopod_release_scene_screen(g_now_playing_scene.screen);
    yoyopod_release_scene_screen(g_incoming_call_scene.screen);
    yoyopod_release_scene_screen(g_outgoing_call_scene.screen);
    yoyopod_release_scene_screen(g_in_call_scene.screen);
    yoyopod_release_scene_screen(g_ask_scene.screen);
    yoyopod_release_scene_screen(g_power_scene.screen);

    lv_obj_t * screen = lv_screen_active();
    if(screen != NULL) {
        lv_obj_clean(screen);
    }
    yoyopod_clear_group();
    yoyopod_reset_scene_refs();
}

void yoyopod_lvgl_force_refresh(void) {
    if(!g_initialized || g_display == NULL) {
        return;
    }

    lv_obj_t * screen = lv_screen_active();
    if(screen == NULL) {
        return;
    }

    lv_obj_invalidate(screen);
    lv_timer_handler();
}

int32_t yoyopod_lvgl_snapshot(unsigned char * output_buf, uint32_t buf_size) {
    if(!g_initialized || g_display == NULL) {
        yoyopod_set_error("display must be registered before taking a snapshot");
        return -1;
    }

    if(output_buf == NULL || buf_size == 0) {
        yoyopod_set_error("output buffer is NULL or zero-length");
        return -1;
    }

    lv_obj_t * screen = lv_screen_active();
    if(screen == NULL) {
        yoyopod_set_error("no active screen for snapshot");
        return -1;
    }

    /*
     * LVGL snapshotting supports RGB565, but not RGB565_SWAPPED.
     * Capture in RGB565, then byte-swap into the existing RGB565_SWAPPED
     * contract used by the Python binding and screenshot decoder.
     */
    lv_draw_buf_t * snapshot = lv_snapshot_take(screen, LV_COLOR_FORMAT_RGB565);
    if(snapshot == NULL) {
        yoyopod_set_error("lv_snapshot_take returned NULL");
        return -1;
    }

    uint32_t data_size = snapshot->header.w * snapshot->header.h
                         * lv_color_format_get_size(snapshot->header.cf);
    uint32_t copy_size = data_size < buf_size ? data_size : buf_size;
    const uint8_t * snapshot_data = (const uint8_t *)snapshot->data;
    for(uint32_t index = 0; index + 1 < copy_size; index += 2) {
        output_buf[index] = snapshot_data[index + 1];
        output_buf[index + 1] = snapshot_data[index];
    }

    lv_draw_buf_destroy(snapshot);
    return (int32_t)copy_size;
}

const char * yoyopod_lvgl_last_error(void) {
    return g_last_error;
}

const char * yoyopod_lvgl_version(void) {
    static char version[32];
    snprintf(
        version,
        sizeof(version),
        "%d.%d.%d",
        LVGL_VERSION_MAJOR,
        LVGL_VERSION_MINOR,
        LVGL_VERSION_PATCH
    );
    return version;
}
