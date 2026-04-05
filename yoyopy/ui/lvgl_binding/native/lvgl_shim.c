#include "lvgl.h"
#include "lvgl_shim.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define KEY_QUEUE_CAPACITY 32

typedef struct {
    int32_t key;
    int32_t pressed;
} yoyopy_key_event_t;

typedef struct {
    int built;
    lv_obj_t * screen;
    lv_obj_t * voip_dot;
    lv_obj_t * time_label;
    lv_obj_t * battery_outline;
    lv_obj_t * battery_fill;
    lv_obj_t * battery_tip;
    lv_obj_t * card_panel;
    lv_obj_t * icon_halo;
    lv_obj_t * icon_label;
    lv_obj_t * title_label;
    lv_obj_t * subtitle_label;
    lv_obj_t * footer_label;
    lv_obj_t * dots[4];
} yoyopy_hub_scene_t;

typedef struct {
    int built;
    lv_obj_t * screen;
    lv_obj_t * voip_dot;
    lv_obj_t * battery_outline;
    lv_obj_t * battery_fill;
    lv_obj_t * battery_tip;
    lv_obj_t * title_label;
    lv_obj_t * title_underline;
    lv_obj_t * page_label;
    lv_obj_t * panel;
    lv_obj_t * item_panels[4];
    lv_obj_t * item_titles[4];
    lv_obj_t * dots[4];
    lv_obj_t * empty_panel;
    lv_obj_t * empty_icon;
    lv_obj_t * empty_title;
    lv_obj_t * empty_subtitle;
    lv_obj_t * footer_label;
} yoyopy_listen_scene_t;

typedef struct {
    int built;
    lv_obj_t * screen;
    lv_obj_t * voip_dot;
    lv_obj_t * battery_outline;
    lv_obj_t * battery_fill;
    lv_obj_t * battery_tip;
    lv_obj_t * title_label;
    lv_obj_t * title_underline;
    lv_obj_t * page_label;
    lv_obj_t * panel;
    lv_obj_t * item_panels[4];
    lv_obj_t * item_titles[4];
    lv_obj_t * item_badges[4];
    lv_obj_t * empty_panel;
    lv_obj_t * empty_icon;
    lv_obj_t * empty_title;
    lv_obj_t * empty_subtitle;
    lv_obj_t * footer_label;
} yoyopy_playlist_scene_t;

typedef struct {
    int built;
    lv_obj_t * screen;
    lv_obj_t * voip_dot;
    lv_obj_t * battery_outline;
    lv_obj_t * battery_fill;
    lv_obj_t * battery_tip;
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
} yoyopy_now_playing_scene_t;

typedef struct {
    int built;
    lv_obj_t * screen;
    lv_obj_t * voip_dot;
    lv_obj_t * battery_outline;
    lv_obj_t * battery_fill;
    lv_obj_t * battery_tip;
    lv_obj_t * panel;
    lv_obj_t * icon_halo;
    lv_obj_t * icon_label;
    lv_obj_t * state_label;
    lv_obj_t * caller_name_label;
    lv_obj_t * caller_address_label;
    lv_obj_t * footer_label;
} yoyopy_incoming_call_scene_t;

static int g_initialized = 0;
static lv_display_t * g_display = NULL;
static lv_indev_t * g_indev = NULL;
static lv_group_t * g_group = NULL;
static lv_color_t * g_draw_buf = NULL;
static uint32_t g_draw_buf_bytes = 0;
static yoyopy_lvgl_flush_cb_t g_flush_cb = NULL;
static void * g_flush_user_data = NULL;
static char g_last_error[256] = "";
static yoyopy_key_event_t g_key_queue[KEY_QUEUE_CAPACITY];
static int g_key_head = 0;
static int g_key_tail = 0;
static int g_key_count = 0;
static yoyopy_hub_scene_t g_hub_scene = {0};
static yoyopy_listen_scene_t g_listen_scene = {0};
static yoyopy_playlist_scene_t g_playlist_scene = {0};
static yoyopy_now_playing_scene_t g_now_playing_scene = {0};
static yoyopy_incoming_call_scene_t g_incoming_call_scene = {0};

static lv_color_t yoyopy_color_rgb(uint8_t red, uint8_t green, uint8_t blue) {
    uint32_t raw = ((uint32_t)red << 16) | ((uint32_t)green << 8) | (uint32_t)blue;
    return lv_color_hex(raw);
}

static lv_color_t yoyopy_mix_rgb(
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
    return yoyopy_color_rgb(mixed_red, mixed_green, mixed_blue);
}

static void yoyopy_reset_hub_scene_refs(void) {
    memset(&g_hub_scene, 0, sizeof(g_hub_scene));
}

static void yoyopy_reset_listen_scene_refs(void) {
    memset(&g_listen_scene, 0, sizeof(g_listen_scene));
}

static void yoyopy_reset_playlist_scene_refs(void) {
    memset(&g_playlist_scene, 0, sizeof(g_playlist_scene));
}

static void yoyopy_reset_now_playing_scene_refs(void) {
    memset(&g_now_playing_scene, 0, sizeof(g_now_playing_scene));
}

static void yoyopy_reset_incoming_call_scene_refs(void) {
    memset(&g_incoming_call_scene, 0, sizeof(g_incoming_call_scene));
}

static void yoyopy_reset_scene_refs(void) {
    yoyopy_reset_hub_scene_refs();
    yoyopy_reset_listen_scene_refs();
    yoyopy_reset_playlist_scene_refs();
    yoyopy_reset_now_playing_scene_refs();
    yoyopy_reset_incoming_call_scene_refs();
}

static void yoyopy_set_error(const char * message) {
    if(message == NULL) {
        g_last_error[0] = '\0';
        return;
    }

    strncpy(g_last_error, message, sizeof(g_last_error) - 1);
    g_last_error[sizeof(g_last_error) - 1] = '\0';
}

static int yoyopy_translate_key(int32_t key) {
    switch(key) {
        case YOYOPY_LVGL_KEY_RIGHT:
            return LV_KEY_RIGHT;
        case YOYOPY_LVGL_KEY_ENTER:
            return LV_KEY_ENTER;
        case YOYOPY_LVGL_KEY_ESC:
            return LV_KEY_ESC;
        default:
            return 0;
    }
}

static void yoyopy_flush_cb(lv_display_t * disp, const lv_area_t * area, uint8_t * px_map) {
    int32_t width = lv_area_get_width(area);
    int32_t height = lv_area_get_height(area);
    uint32_t byte_length = (uint32_t)(width * height * sizeof(lv_color_t));

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

static void yoyopy_indev_read_cb(lv_indev_t * indev, lv_indev_data_t * data) {
    (void)indev;

    if(g_key_count == 0) {
        data->state = LV_INDEV_STATE_RELEASED;
        data->key = 0;
        data->continue_reading = 0;
        return;
    }

    yoyopy_key_event_t event = g_key_queue[g_key_head];
    g_key_head = (g_key_head + 1) % KEY_QUEUE_CAPACITY;
    g_key_count--;

    data->key = yoyopy_translate_key(event.key);
    data->state = event.pressed ? LV_INDEV_STATE_PRESSED : LV_INDEV_STATE_RELEASED;
    data->continue_reading = g_key_count > 0 ? 1 : 0;
}

static void yoyopy_clear_group(void) {
    if(g_group != NULL) {
        lv_group_remove_all_objs(g_group);
    }
}

static void yoyopy_prepare_active_screen(void) {
    lv_obj_t * screen = lv_screen_active();
    lv_obj_clean(screen);
    yoyopy_clear_group();
    yoyopy_reset_scene_refs();
}

static lv_obj_t * yoyopy_create_card(lv_obj_t * screen, const char * title, const char * subtitle, lv_color_t accent) {
    lv_obj_t * panel = lv_obj_create(screen);
    lv_obj_set_size(panel, 200, 190);
    lv_obj_align(panel, LV_ALIGN_CENTER, 0, 8);
    lv_obj_set_style_radius(panel, 24, 0);
    lv_obj_set_style_border_width(panel, 2, 0);
    lv_obj_set_style_border_color(panel, accent, 0);
    lv_obj_set_style_bg_color(panel, lv_color_hex(0x222634), 0);
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
    lv_obj_set_style_text_color(title_label, lv_color_hex(0xF6F6F8), 0);

    lv_obj_t * subtitle_label = lv_label_create(panel);
    lv_label_set_text(subtitle_label, subtitle);
    lv_obj_set_style_text_font(subtitle_label, &lv_font_montserrat_16, 0);
    lv_obj_set_style_text_color(subtitle_label, accent, 0);

    return panel;
}

static void yoyopy_build_card_scene(void) {
    lv_obj_t * screen = lv_screen_active();
    yoyopy_prepare_active_screen();
    yoyopy_create_card(screen, "Listen", "LVGL card proof", lv_color_hex(0x98D94C));
}

static void yoyopy_build_list_scene(void) {
    lv_obj_t * screen = lv_screen_active();
    yoyopy_prepare_active_screen();

    lv_obj_t * list = lv_list_create(screen);
    lv_obj_set_size(list, 208, 210);
    lv_obj_align(list, LV_ALIGN_CENTER, 0, 8);
    lv_obj_set_style_radius(list, 22, 0);
    lv_obj_set_style_bg_color(list, lv_color_hex(0x222634), 0);
    lv_obj_set_style_border_color(list, lv_color_hex(0x4CCAE4), 0);
    lv_obj_set_style_border_width(list, 2, 0);

    lv_obj_t * button = NULL;

    button = lv_list_add_button(list, NULL, "Spotify");
    if(g_group != NULL) lv_group_add_obj(g_group, button);

    button = lv_list_add_button(list, NULL, "Amazon");
    if(g_group != NULL) lv_group_add_obj(g_group, button);

    button = lv_list_add_button(list, NULL, "YouTube");
    if(g_group != NULL) lv_group_add_obj(g_group, button);

    button = lv_list_add_button(list, NULL, "Local");
    if(g_group != NULL) lv_group_add_obj(g_group, button);
}

static void yoyopy_build_footer_scene(void) {
    lv_obj_t * screen = lv_screen_active();
    yoyopy_prepare_active_screen();

    lv_obj_t * label = lv_label_create(screen);
    lv_label_set_text(label, "Tap next / Double open / Hold back");
    lv_obj_align(label, LV_ALIGN_BOTTOM_MID, 0, -10);
    lv_obj_set_style_text_font(label, &lv_font_montserrat_14, 0);
    lv_obj_set_style_text_color(label, lv_color_hex(0xE8E8EF), 0);
}

static void yoyopy_build_carousel_scene(void) {
    lv_obj_t * screen = lv_screen_active();
    yoyopy_prepare_active_screen();
    yoyopy_create_card(screen, "Talk", "Carousel proof", lv_color_hex(0x4CCAE4));

    lv_obj_t * footer = lv_label_create(screen);
    lv_label_set_text(footer, "Tap next / Open");
    lv_obj_align(footer, LV_ALIGN_BOTTOM_MID, 0, -10);
    lv_obj_set_style_text_font(footer, &lv_font_montserrat_14, 0);
    lv_obj_set_style_text_color(footer, lv_color_hex(0xF6F6F8), 0);
}

static void yoyopy_apply_voip_dot(lv_obj_t * dot, int32_t voip_state) {
    const lv_color_t success = yoyopy_color_rgb(61, 221, 83);
    const lv_color_t error = yoyopy_color_rgb(255, 103, 93);

    if(voip_state == 0) {
        lv_obj_add_flag(dot, LV_OBJ_FLAG_HIDDEN);
        return;
    }

    lv_obj_clear_flag(dot, LV_OBJ_FLAG_HIDDEN);
    lv_obj_set_style_bg_color(dot, voip_state == 1 ? success : error, 0);
    lv_obj_set_style_bg_opa(dot, LV_OPA_COVER, 0);
}

static void yoyopy_apply_battery(
    lv_obj_t * outline,
    lv_obj_t * fill,
    lv_obj_t * tip,
    int32_t battery_percent,
    int32_t charging,
    int32_t power_available
) {
    const lv_color_t muted = yoyopy_color_rgb(153, 160, 173);
    const lv_color_t ink = yoyopy_color_rgb(243, 247, 250);
    const lv_color_t success = yoyopy_color_rgb(61, 221, 83);
    const lv_color_t error = yoyopy_color_rgb(255, 103, 93);

    if(battery_percent < 0) {
        battery_percent = 0;
    }
    if(battery_percent > 100) {
        battery_percent = 100;
    }

    lv_obj_set_style_border_color(outline, muted, 0);
    lv_obj_set_style_bg_color(tip, muted, 0);

    int fill_width = (battery_percent * 18) / 100;
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

    lv_obj_set_size(fill, fill_width, 8);
    lv_obj_set_style_bg_color(fill, fill_color, 0);
    if(fill_width <= 0) {
        lv_obj_add_flag(fill, LV_OBJ_FLAG_HIDDEN);
    } else {
        lv_obj_clear_flag(fill, LV_OBJ_FLAG_HIDDEN);
    }
}

static const char * yoyopy_symbol_for_empty_icon(const char * icon_key) {
    if(icon_key == NULL) {
        return LV_SYMBOL_LIST;
    }

    if(strcmp(icon_key, "playlist") == 0) {
        return LV_SYMBOL_LIST;
    }
    if(strcmp(icon_key, "listen") == 0) {
        return LV_SYMBOL_AUDIO;
    }
    if(strcmp(icon_key, "talk") == 0) {
        return LV_SYMBOL_CALL;
    }
    if(strcmp(icon_key, "ask") == 0) {
        return LV_SYMBOL_EDIT;
    }
    if(strcmp(icon_key, "setup") == 0 || strcmp(icon_key, "power") == 0) {
        return LV_SYMBOL_SETTINGS;
    }

    return LV_SYMBOL_LIST;
}

static const char * yoyopy_hub_symbol_for_icon(const char * icon_key) {
    if(icon_key == NULL) {
        return LV_SYMBOL_SETTINGS;
    }

    if(strcmp(icon_key, "listen") == 0) {
        return LV_SYMBOL_AUDIO;
    }
    if(strcmp(icon_key, "talk") == 0) {
        return LV_SYMBOL_CALL;
    }
    if(strcmp(icon_key, "ask") == 0) {
        return LV_SYMBOL_EDIT;
    }
    if(strcmp(icon_key, "setup") == 0 || strcmp(icon_key, "power") == 0) {
        return LV_SYMBOL_SETTINGS;
    }

    return LV_SYMBOL_SETTINGS;
}

static void yoyopy_hub_style_dot(lv_obj_t * dot, lv_color_t color, int selected) {
    int size = selected ? 8 : 6;
    lv_obj_set_size(dot, size, size);
    lv_obj_set_style_radius(dot, LV_RADIUS_CIRCLE, 0);
    lv_obj_set_style_bg_color(dot, color, 0);
    lv_obj_set_style_bg_opa(dot, LV_OPA_COVER, 0);
    lv_obj_set_style_border_width(dot, 0, 0);
}

int yoyopy_lvgl_hub_build(void) {
    if(!g_initialized || g_display == NULL) {
        yoyopy_set_error("display must be registered before building the hub");
        return -1;
    }

    if(g_hub_scene.built) {
        return 0;
    }

    yoyopy_prepare_active_screen();

    g_hub_scene.screen = lv_screen_active();
    lv_obj_set_style_bg_color(g_hub_scene.screen, yoyopy_color_rgb(18, 21, 28), 0);
    lv_obj_set_style_bg_opa(g_hub_scene.screen, LV_OPA_COVER, 0);

    g_hub_scene.voip_dot = lv_obj_create(g_hub_scene.screen);
    lv_obj_remove_style_all(g_hub_scene.voip_dot);
    lv_obj_set_size(g_hub_scene.voip_dot, 8, 8);
    lv_obj_set_style_radius(g_hub_scene.voip_dot, LV_RADIUS_CIRCLE, 0);
    lv_obj_set_pos(g_hub_scene.voip_dot, 16, 10);

    g_hub_scene.time_label = lv_label_create(g_hub_scene.screen);
    lv_obj_set_pos(g_hub_scene.time_label, 28, 5);
    lv_obj_set_style_text_font(g_hub_scene.time_label, &lv_font_montserrat_14, 0);
    lv_obj_set_style_text_color(g_hub_scene.time_label, yoyopy_color_rgb(243, 247, 250), 0);

    g_hub_scene.battery_outline = lv_obj_create(g_hub_scene.screen);
    lv_obj_remove_style_all(g_hub_scene.battery_outline);
    lv_obj_set_size(g_hub_scene.battery_outline, 20, 10);
    lv_obj_set_pos(g_hub_scene.battery_outline, 202, 6);
    lv_obj_set_style_border_width(g_hub_scene.battery_outline, 1, 0);
    lv_obj_set_style_border_color(g_hub_scene.battery_outline, yoyopy_color_rgb(153, 160, 173), 0);
    lv_obj_set_style_radius(g_hub_scene.battery_outline, 2, 0);
    lv_obj_set_style_bg_opa(g_hub_scene.battery_outline, LV_OPA_TRANSP, 0);

    g_hub_scene.battery_fill = lv_obj_create(g_hub_scene.battery_outline);
    lv_obj_remove_style_all(g_hub_scene.battery_fill);
    lv_obj_set_pos(g_hub_scene.battery_fill, 1, 1);
    lv_obj_set_size(g_hub_scene.battery_fill, 18, 8);
    lv_obj_set_style_radius(g_hub_scene.battery_fill, 1, 0);
    lv_obj_set_style_bg_opa(g_hub_scene.battery_fill, LV_OPA_COVER, 0);

    g_hub_scene.battery_tip = lv_obj_create(g_hub_scene.screen);
    lv_obj_remove_style_all(g_hub_scene.battery_tip);
    lv_obj_set_size(g_hub_scene.battery_tip, 2, 4);
    lv_obj_set_pos(g_hub_scene.battery_tip, 222, 9);
    lv_obj_set_style_bg_color(g_hub_scene.battery_tip, yoyopy_color_rgb(153, 160, 173), 0);
    lv_obj_set_style_bg_opa(g_hub_scene.battery_tip, LV_OPA_COVER, 0);

    g_hub_scene.card_panel = lv_obj_create(g_hub_scene.screen);
    lv_obj_set_size(g_hub_scene.card_panel, 208, 194);
    lv_obj_set_pos(g_hub_scene.card_panel, 16, 42);
    lv_obj_set_style_radius(g_hub_scene.card_panel, 28, 0);
    lv_obj_set_style_border_width(g_hub_scene.card_panel, 2, 0);
    lv_obj_set_style_pad_all(g_hub_scene.card_panel, 0, 0);
    lv_obj_set_style_shadow_width(g_hub_scene.card_panel, 0, 0);
    lv_obj_set_style_outline_width(g_hub_scene.card_panel, 0, 0);
    lv_obj_set_scrollbar_mode(g_hub_scene.card_panel, LV_SCROLLBAR_MODE_OFF);

    g_hub_scene.icon_halo = lv_obj_create(g_hub_scene.card_panel);
    lv_obj_set_size(g_hub_scene.icon_halo, 84, 64);
    lv_obj_set_pos(g_hub_scene.icon_halo, 62, 18);
    lv_obj_set_style_radius(g_hub_scene.icon_halo, 20, 0);
    lv_obj_set_style_border_width(g_hub_scene.icon_halo, 2, 0);
    lv_obj_set_style_shadow_width(g_hub_scene.icon_halo, 0, 0);
    lv_obj_set_style_outline_width(g_hub_scene.icon_halo, 0, 0);
    lv_obj_set_scrollbar_mode(g_hub_scene.icon_halo, LV_SCROLLBAR_MODE_OFF);

    g_hub_scene.icon_label = lv_label_create(g_hub_scene.icon_halo);
    lv_obj_set_style_text_font(g_hub_scene.icon_label, &lv_font_montserrat_24, 0);
    lv_obj_center(g_hub_scene.icon_label);

    g_hub_scene.title_label = lv_label_create(g_hub_scene.card_panel);
    lv_obj_set_width(g_hub_scene.title_label, 172);
    lv_obj_set_pos(g_hub_scene.title_label, 18, 106);
    lv_obj_set_style_text_font(g_hub_scene.title_label, &lv_font_montserrat_24, 0);
    lv_obj_set_style_text_align(g_hub_scene.title_label, LV_TEXT_ALIGN_CENTER, 0);

    g_hub_scene.subtitle_label = lv_label_create(g_hub_scene.card_panel);
    lv_obj_set_width(g_hub_scene.subtitle_label, 172);
    lv_obj_set_pos(g_hub_scene.subtitle_label, 18, 140);
    lv_label_set_long_mode(g_hub_scene.subtitle_label, LV_LABEL_LONG_MODE_CLIP);
    lv_obj_set_style_text_font(g_hub_scene.subtitle_label, &lv_font_montserrat_14, 0);
    lv_obj_set_style_text_align(g_hub_scene.subtitle_label, LV_TEXT_ALIGN_CENTER, 0);

    for(int index = 0; index < 4; ++index) {
        g_hub_scene.dots[index] = lv_obj_create(g_hub_scene.card_panel);
        lv_obj_remove_style_all(g_hub_scene.dots[index]);
        lv_obj_set_style_bg_opa(g_hub_scene.dots[index], LV_OPA_COVER, 0);
        lv_obj_set_style_radius(g_hub_scene.dots[index], LV_RADIUS_CIRCLE, 0);
    }

    g_hub_scene.footer_label = lv_label_create(g_hub_scene.screen);
    lv_obj_set_style_text_font(g_hub_scene.footer_label, &lv_font_montserrat_12, 0);
    lv_obj_set_style_text_align(g_hub_scene.footer_label, LV_TEXT_ALIGN_CENTER, 0);
    lv_obj_align(g_hub_scene.footer_label, LV_ALIGN_BOTTOM_MID, 0, -5);

    g_hub_scene.built = 1;
    return 0;
}

int yoyopy_lvgl_hub_sync(
    const char * icon_key,
    const char * title,
    const char * subtitle,
    const char * footer,
    const char * time_text,
    uint8_t accent_r,
    uint8_t accent_g,
    uint8_t accent_b,
    int32_t selected_index,
    int32_t total_cards,
    int32_t voip_state,
    int32_t battery_percent,
    int32_t charging,
    int32_t power_available
) {
    if(!g_hub_scene.built) {
        yoyopy_set_error("hub scene must be built before sync");
        return -1;
    }

    const lv_color_t background = yoyopy_color_rgb(18, 21, 28);
    const lv_color_t surface = yoyopy_color_rgb(28, 33, 42);
    const lv_color_t ink = yoyopy_color_rgb(243, 247, 250);
    const lv_color_t accent = yoyopy_color_rgb(accent_r, accent_g, accent_b);
    const lv_color_t accent_dim = yoyopy_mix_rgb(accent_r, accent_g, accent_b, 18, 21, 28, 65);
    const lv_color_t card_fill = yoyopy_mix_rgb(accent_r, accent_g, accent_b, 28, 33, 42, 90);
    const lv_color_t halo_fill = yoyopy_mix_rgb(accent_r, accent_g, accent_b, 18, 21, 28, 80);
    const lv_color_t halo_border = yoyopy_mix_rgb(accent_r, accent_g, accent_b, 18, 21, 28, 60);

    lv_obj_set_style_bg_color(g_hub_scene.screen, background, 0);
    lv_obj_set_style_bg_opa(g_hub_scene.screen, LV_OPA_COVER, 0);
    yoyopy_apply_voip_dot(g_hub_scene.voip_dot, voip_state);

    if(time_text == NULL || time_text[0] == '\0') {
        lv_label_set_text(g_hub_scene.time_label, "");
        lv_obj_add_flag(g_hub_scene.time_label, LV_OBJ_FLAG_HIDDEN);
    } else {
        lv_label_set_text(g_hub_scene.time_label, time_text);
        lv_obj_clear_flag(g_hub_scene.time_label, LV_OBJ_FLAG_HIDDEN);
    }
    yoyopy_apply_battery(
        g_hub_scene.battery_outline,
        g_hub_scene.battery_fill,
        g_hub_scene.battery_tip,
        battery_percent,
        charging,
        power_available
    );

    lv_obj_set_style_bg_color(g_hub_scene.card_panel, card_fill, 0);
    lv_obj_set_style_bg_opa(g_hub_scene.card_panel, LV_OPA_COVER, 0);
    lv_obj_set_style_border_color(g_hub_scene.card_panel, accent_dim, 0);
    lv_obj_set_style_bg_color(g_hub_scene.icon_halo, halo_fill, 0);
    lv_obj_set_style_bg_opa(g_hub_scene.icon_halo, LV_OPA_COVER, 0);
    lv_obj_set_style_border_color(g_hub_scene.icon_halo, halo_border, 0);

    lv_label_set_text(g_hub_scene.icon_label, yoyopy_hub_symbol_for_icon(icon_key));
    lv_obj_set_style_text_color(g_hub_scene.icon_label, accent, 0);
    lv_obj_center(g_hub_scene.icon_label);
    lv_label_set_text(g_hub_scene.title_label, title != NULL ? title : "");
    lv_obj_set_style_text_color(g_hub_scene.title_label, accent, 0);
    lv_label_set_text(g_hub_scene.subtitle_label, subtitle != NULL ? subtitle : "");
    lv_obj_set_style_text_color(g_hub_scene.subtitle_label, ink, 0);
    lv_label_set_text(g_hub_scene.footer_label, footer != NULL ? footer : "");
    lv_obj_set_style_text_color(g_hub_scene.footer_label, accent_dim, 0);
    lv_obj_align(g_hub_scene.footer_label, LV_ALIGN_BOTTOM_MID, 0, -5);

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

    int center_x = 104;
    int first_x = center_x - (((total_cards - 1) * 18) / 2);
    for(int index = 0; index < 4; ++index) {
        if(index >= total_cards) {
            lv_obj_add_flag(g_hub_scene.dots[index], LV_OBJ_FLAG_HIDDEN);
            continue;
        }

        int selected = index == selected_index;
        int size = selected ? 8 : 6;
        lv_obj_clear_flag(g_hub_scene.dots[index], LV_OBJ_FLAG_HIDDEN);
        lv_obj_set_pos(g_hub_scene.dots[index], first_x + (index * 18) - (size / 2), 172 - (size / 2));
        yoyopy_hub_style_dot(g_hub_scene.dots[index], selected ? accent : accent_dim, selected);
    }

    return 0;
}

void yoyopy_lvgl_hub_destroy(void) {
    if(!g_hub_scene.built) {
        return;
    }

    if(g_hub_scene.screen != NULL) {
        lv_obj_clean(g_hub_scene.screen);
    }
    yoyopy_clear_group();
    yoyopy_reset_hub_scene_refs();
}

int yoyopy_lvgl_listen_build(void) {
    if(!g_initialized || g_display == NULL) {
        yoyopy_set_error("display must be registered before building the listen scene");
        return -1;
    }

    if(g_listen_scene.built) {
        return 0;
    }

    yoyopy_prepare_active_screen();

    g_listen_scene.screen = lv_screen_active();
    lv_obj_set_style_bg_color(g_listen_scene.screen, yoyopy_color_rgb(18, 21, 28), 0);
    lv_obj_set_style_bg_opa(g_listen_scene.screen, LV_OPA_COVER, 0);

    g_listen_scene.voip_dot = lv_obj_create(g_listen_scene.screen);
    lv_obj_remove_style_all(g_listen_scene.voip_dot);
    lv_obj_set_size(g_listen_scene.voip_dot, 8, 8);
    lv_obj_set_style_radius(g_listen_scene.voip_dot, LV_RADIUS_CIRCLE, 0);
    lv_obj_set_pos(g_listen_scene.voip_dot, 16, 10);

    g_listen_scene.battery_outline = lv_obj_create(g_listen_scene.screen);
    lv_obj_remove_style_all(g_listen_scene.battery_outline);
    lv_obj_set_size(g_listen_scene.battery_outline, 20, 10);
    lv_obj_set_pos(g_listen_scene.battery_outline, 202, 6);
    lv_obj_set_style_border_width(g_listen_scene.battery_outline, 1, 0);
    lv_obj_set_style_border_color(g_listen_scene.battery_outline, yoyopy_color_rgb(153, 160, 173), 0);
    lv_obj_set_style_radius(g_listen_scene.battery_outline, 2, 0);
    lv_obj_set_style_bg_opa(g_listen_scene.battery_outline, LV_OPA_TRANSP, 0);

    g_listen_scene.battery_fill = lv_obj_create(g_listen_scene.battery_outline);
    lv_obj_remove_style_all(g_listen_scene.battery_fill);
    lv_obj_set_pos(g_listen_scene.battery_fill, 1, 1);
    lv_obj_set_size(g_listen_scene.battery_fill, 18, 8);
    lv_obj_set_style_radius(g_listen_scene.battery_fill, 1, 0);
    lv_obj_set_style_bg_opa(g_listen_scene.battery_fill, LV_OPA_COVER, 0);

    g_listen_scene.battery_tip = lv_obj_create(g_listen_scene.screen);
    lv_obj_remove_style_all(g_listen_scene.battery_tip);
    lv_obj_set_size(g_listen_scene.battery_tip, 2, 4);
    lv_obj_set_pos(g_listen_scene.battery_tip, 222, 9);
    lv_obj_set_style_bg_color(g_listen_scene.battery_tip, yoyopy_color_rgb(153, 160, 173), 0);
    lv_obj_set_style_bg_opa(g_listen_scene.battery_tip, LV_OPA_COVER, 0);

    g_listen_scene.title_label = lv_label_create(g_listen_scene.screen);
    lv_label_set_text(g_listen_scene.title_label, "Listen");
    lv_obj_set_pos(g_listen_scene.title_label, 18, 36);
    lv_obj_set_style_text_font(g_listen_scene.title_label, &lv_font_montserrat_24, 0);

    g_listen_scene.title_underline = lv_obj_create(g_listen_scene.screen);
    lv_obj_remove_style_all(g_listen_scene.title_underline);
    lv_obj_set_pos(g_listen_scene.title_underline, 18, 66);
    lv_obj_set_size(g_listen_scene.title_underline, 88, 3);
    lv_obj_set_style_radius(g_listen_scene.title_underline, 2, 0);
    lv_obj_set_style_bg_opa(g_listen_scene.title_underline, LV_OPA_COVER, 0);

    g_listen_scene.page_label = lv_label_create(g_listen_scene.screen);
    lv_obj_set_pos(g_listen_scene.page_label, 188, 39);
    lv_obj_set_style_text_font(g_listen_scene.page_label, &lv_font_montserrat_12, 0);
    lv_obj_set_style_text_color(g_listen_scene.page_label, yoyopy_color_rgb(153, 160, 173), 0);

    g_listen_scene.panel = lv_obj_create(g_listen_scene.screen);
    lv_obj_set_size(g_listen_scene.panel, 216, 164);
    lv_obj_set_pos(g_listen_scene.panel, 12, 84);
    lv_obj_set_style_radius(g_listen_scene.panel, 22, 0);
    lv_obj_set_style_border_width(g_listen_scene.panel, 0, 0);
    lv_obj_set_style_bg_color(g_listen_scene.panel, yoyopy_color_rgb(28, 33, 42), 0);
    lv_obj_set_style_bg_opa(g_listen_scene.panel, LV_OPA_COVER, 0);
    lv_obj_set_style_pad_all(g_listen_scene.panel, 0, 0);
    lv_obj_set_style_shadow_width(g_listen_scene.panel, 0, 0);
    lv_obj_set_style_outline_width(g_listen_scene.panel, 0, 0);
    lv_obj_set_scrollbar_mode(g_listen_scene.panel, LV_SCROLLBAR_MODE_OFF);

    for(int index = 0; index < 4; ++index) {
        g_listen_scene.item_panels[index] = lv_obj_create(g_listen_scene.panel);
        lv_obj_set_size(g_listen_scene.item_panels[index], 184, 30);
        lv_obj_set_pos(g_listen_scene.item_panels[index], 16, 14 + (index * 34));
        lv_obj_set_style_radius(g_listen_scene.item_panels[index], 15, 0);
        lv_obj_set_style_border_width(g_listen_scene.item_panels[index], 2, 0);
        lv_obj_set_style_pad_all(g_listen_scene.item_panels[index], 0, 0);
        lv_obj_set_style_shadow_width(g_listen_scene.item_panels[index], 0, 0);
        lv_obj_set_style_outline_width(g_listen_scene.item_panels[index], 0, 0);
        lv_obj_set_scrollbar_mode(g_listen_scene.item_panels[index], LV_SCROLLBAR_MODE_OFF);

        g_listen_scene.item_titles[index] = lv_label_create(g_listen_scene.item_panels[index]);
        lv_obj_set_width(g_listen_scene.item_titles[index], 148);
        lv_obj_set_pos(g_listen_scene.item_titles[index], 16, 7);
        lv_label_set_long_mode(g_listen_scene.item_titles[index], LV_LABEL_LONG_MODE_CLIP);
        lv_obj_set_style_text_font(g_listen_scene.item_titles[index], &lv_font_montserrat_16, 0);
    }

    for(int index = 0; index < 4; ++index) {
        g_listen_scene.dots[index] = lv_obj_create(g_listen_scene.panel);
        lv_obj_remove_style_all(g_listen_scene.dots[index]);
        lv_obj_set_style_bg_opa(g_listen_scene.dots[index], LV_OPA_COVER, 0);
        lv_obj_set_style_radius(g_listen_scene.dots[index], LV_RADIUS_CIRCLE, 0);
    }

    g_listen_scene.empty_panel = lv_obj_create(g_listen_scene.screen);
    lv_obj_set_size(g_listen_scene.empty_panel, 204, 136);
    lv_obj_set_pos(g_listen_scene.empty_panel, 18, 94);
    lv_obj_set_style_radius(g_listen_scene.empty_panel, 22, 0);
    lv_obj_set_style_border_width(g_listen_scene.empty_panel, 2, 0);
    lv_obj_set_style_pad_all(g_listen_scene.empty_panel, 0, 0);
    lv_obj_set_style_shadow_width(g_listen_scene.empty_panel, 0, 0);
    lv_obj_set_style_outline_width(g_listen_scene.empty_panel, 0, 0);
    lv_obj_set_scrollbar_mode(g_listen_scene.empty_panel, LV_SCROLLBAR_MODE_OFF);

    g_listen_scene.empty_icon = lv_label_create(g_listen_scene.empty_panel);
    lv_label_set_text(g_listen_scene.empty_icon, LV_SYMBOL_AUDIO);
    lv_obj_set_style_text_font(g_listen_scene.empty_icon, &lv_font_montserrat_24, 0);
    lv_obj_align(g_listen_scene.empty_icon, LV_ALIGN_TOP_MID, 0, 16);

    g_listen_scene.empty_title = lv_label_create(g_listen_scene.empty_panel);
    lv_obj_set_width(g_listen_scene.empty_title, 168);
    lv_obj_set_pos(g_listen_scene.empty_title, 18, 60);
    lv_obj_set_style_text_font(g_listen_scene.empty_title, &lv_font_montserrat_16, 0);
    lv_obj_set_style_text_align(g_listen_scene.empty_title, LV_TEXT_ALIGN_CENTER, 0);

    g_listen_scene.empty_subtitle = lv_label_create(g_listen_scene.empty_panel);
    lv_obj_set_width(g_listen_scene.empty_subtitle, 168);
    lv_obj_set_pos(g_listen_scene.empty_subtitle, 18, 86);
    lv_label_set_long_mode(g_listen_scene.empty_subtitle, LV_LABEL_LONG_MODE_WRAP);
    lv_obj_set_style_text_font(g_listen_scene.empty_subtitle, &lv_font_montserrat_12, 0);
    lv_obj_set_style_text_align(g_listen_scene.empty_subtitle, LV_TEXT_ALIGN_CENTER, 0);

    g_listen_scene.footer_label = lv_label_create(g_listen_scene.screen);
    lv_obj_set_style_text_font(g_listen_scene.footer_label, &lv_font_montserrat_12, 0);
    lv_obj_set_style_text_align(g_listen_scene.footer_label, LV_TEXT_ALIGN_CENTER, 0);
    lv_obj_align(g_listen_scene.footer_label, LV_ALIGN_BOTTOM_MID, 0, -5);

    g_listen_scene.built = 1;
    return 0;
}

int yoyopy_lvgl_listen_sync(
    const char * page_text,
    const char * footer,
    const char * item_0,
    const char * item_1,
    const char * item_2,
    const char * item_3,
    int32_t item_count,
    int32_t selected_index,
    int32_t voip_state,
    int32_t battery_percent,
    int32_t charging,
    int32_t power_available,
    uint8_t accent_r,
    uint8_t accent_g,
    uint8_t accent_b,
    const char * empty_title,
    const char * empty_subtitle
) {
    if(!g_listen_scene.built) {
        yoyopy_set_error("listen scene must be built before sync");
        return -1;
    }

    const lv_color_t background = yoyopy_color_rgb(18, 21, 28);
    const lv_color_t surface = yoyopy_color_rgb(28, 33, 42);
    const lv_color_t ink = yoyopy_color_rgb(243, 247, 250);
    const lv_color_t muted = yoyopy_color_rgb(153, 160, 173);
    const lv_color_t accent = yoyopy_color_rgb(accent_r, accent_g, accent_b);
    const lv_color_t accent_soft = yoyopy_mix_rgb(accent_r, accent_g, accent_b, 28, 33, 42, 55);
    const lv_color_t accent_dim = yoyopy_mix_rgb(accent_r, accent_g, accent_b, 18, 21, 28, 65);
    const lv_color_t selected_fill = yoyopy_mix_rgb(accent_r, accent_g, accent_b, 28, 33, 42, 88);

    const char * items[4] = {item_0, item_1, item_2, item_3};

    lv_obj_set_style_bg_color(g_listen_scene.screen, background, 0);
    lv_obj_set_style_bg_opa(g_listen_scene.screen, LV_OPA_COVER, 0);
    yoyopy_apply_voip_dot(g_listen_scene.voip_dot, voip_state);
    yoyopy_apply_battery(
        g_listen_scene.battery_outline,
        g_listen_scene.battery_fill,
        g_listen_scene.battery_tip,
        battery_percent,
        charging,
        power_available
    );

    lv_obj_set_style_text_color(g_listen_scene.title_label, ink, 0);
    lv_obj_set_style_bg_color(g_listen_scene.title_underline, accent, 0);
    lv_label_set_text(g_listen_scene.page_label, page_text != NULL ? page_text : "");

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
        lv_obj_set_style_border_color(g_listen_scene.empty_panel, accent_dim, 0);
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
            lv_obj_add_flag(g_listen_scene.dots[index], LV_OBJ_FLAG_HIDDEN);
            continue;
        }

        int selected = index == selected_index;
        lv_obj_clear_flag(g_listen_scene.item_panels[index], LV_OBJ_FLAG_HIDDEN);
        lv_label_set_text(g_listen_scene.item_titles[index], items[index] != NULL ? items[index] : "");
        lv_obj_set_style_bg_color(g_listen_scene.item_panels[index], selected ? selected_fill : surface, 0);
        lv_obj_set_style_bg_opa(g_listen_scene.item_panels[index], LV_OPA_COVER, 0);
        lv_obj_set_style_border_color(g_listen_scene.item_panels[index], selected ? accent_soft : yoyopy_color_rgb(74, 79, 92), 0);
        lv_obj_set_style_text_color(g_listen_scene.item_titles[index], selected ? ink : yoyopy_mix_rgb(243, 247, 250, 153, 160, 173, 12), 0);

        lv_obj_clear_flag(g_listen_scene.dots[index], LV_OBJ_FLAG_HIDDEN);
        int size = 6;
        int first_x = 108 - (((item_count - 1) * 16) / 2);
        lv_obj_set_pos(g_listen_scene.dots[index], first_x + (index * 16) - (size / 2), 146);
        yoyopy_hub_style_dot(g_listen_scene.dots[index], selected ? accent : muted, selected ? 1 : 0);
    }

    lv_label_set_text(g_listen_scene.footer_label, footer != NULL ? footer : "");
    lv_obj_set_style_text_color(g_listen_scene.footer_label, accent_dim, 0);
    lv_obj_align(g_listen_scene.footer_label, LV_ALIGN_BOTTOM_MID, 0, -5);

    return 0;
}

void yoyopy_lvgl_listen_destroy(void) {
    if(!g_listen_scene.built) {
        return;
    }

    if(g_listen_scene.screen != NULL) {
        lv_obj_clean(g_listen_scene.screen);
    }
    yoyopy_clear_group();
    yoyopy_reset_listen_scene_refs();
}

int yoyopy_lvgl_playlist_build(void) {
    if(!g_initialized || g_display == NULL) {
        yoyopy_set_error("display must be registered before building the playlist scene");
        return -1;
    }

    if(g_playlist_scene.built) {
        return 0;
    }

    yoyopy_prepare_active_screen();

    g_playlist_scene.screen = lv_screen_active();
    lv_obj_set_style_bg_color(g_playlist_scene.screen, yoyopy_color_rgb(18, 21, 28), 0);
    lv_obj_set_style_bg_opa(g_playlist_scene.screen, LV_OPA_COVER, 0);

    g_playlist_scene.voip_dot = lv_obj_create(g_playlist_scene.screen);
    lv_obj_remove_style_all(g_playlist_scene.voip_dot);
    lv_obj_set_size(g_playlist_scene.voip_dot, 8, 8);
    lv_obj_set_style_radius(g_playlist_scene.voip_dot, LV_RADIUS_CIRCLE, 0);
    lv_obj_set_pos(g_playlist_scene.voip_dot, 16, 10);

    g_playlist_scene.battery_outline = lv_obj_create(g_playlist_scene.screen);
    lv_obj_remove_style_all(g_playlist_scene.battery_outline);
    lv_obj_set_size(g_playlist_scene.battery_outline, 20, 10);
    lv_obj_set_pos(g_playlist_scene.battery_outline, 202, 6);
    lv_obj_set_style_border_width(g_playlist_scene.battery_outline, 1, 0);
    lv_obj_set_style_border_color(g_playlist_scene.battery_outline, yoyopy_color_rgb(153, 160, 173), 0);
    lv_obj_set_style_radius(g_playlist_scene.battery_outline, 2, 0);
    lv_obj_set_style_bg_opa(g_playlist_scene.battery_outline, LV_OPA_TRANSP, 0);

    g_playlist_scene.battery_fill = lv_obj_create(g_playlist_scene.battery_outline);
    lv_obj_remove_style_all(g_playlist_scene.battery_fill);
    lv_obj_set_pos(g_playlist_scene.battery_fill, 1, 1);
    lv_obj_set_size(g_playlist_scene.battery_fill, 18, 8);
    lv_obj_set_style_radius(g_playlist_scene.battery_fill, 1, 0);
    lv_obj_set_style_bg_opa(g_playlist_scene.battery_fill, LV_OPA_COVER, 0);

    g_playlist_scene.battery_tip = lv_obj_create(g_playlist_scene.screen);
    lv_obj_remove_style_all(g_playlist_scene.battery_tip);
    lv_obj_set_size(g_playlist_scene.battery_tip, 2, 4);
    lv_obj_set_pos(g_playlist_scene.battery_tip, 222, 9);
    lv_obj_set_style_bg_color(g_playlist_scene.battery_tip, yoyopy_color_rgb(153, 160, 173), 0);
    lv_obj_set_style_bg_opa(g_playlist_scene.battery_tip, LV_OPA_COVER, 0);

    g_playlist_scene.title_label = lv_label_create(g_playlist_scene.screen);
    lv_obj_set_pos(g_playlist_scene.title_label, 18, 36);
    lv_obj_set_style_text_font(g_playlist_scene.title_label, &lv_font_montserrat_24, 0);

    g_playlist_scene.title_underline = lv_obj_create(g_playlist_scene.screen);
    lv_obj_remove_style_all(g_playlist_scene.title_underline);
    lv_obj_set_pos(g_playlist_scene.title_underline, 18, 66);
    lv_obj_set_size(g_playlist_scene.title_underline, 96, 3);
    lv_obj_set_style_radius(g_playlist_scene.title_underline, 2, 0);
    lv_obj_set_style_bg_opa(g_playlist_scene.title_underline, LV_OPA_COVER, 0);

    g_playlist_scene.page_label = lv_label_create(g_playlist_scene.screen);
    lv_obj_set_pos(g_playlist_scene.page_label, 184, 39);
    lv_obj_set_style_text_font(g_playlist_scene.page_label, &lv_font_montserrat_12, 0);
    lv_obj_set_style_text_color(g_playlist_scene.page_label, yoyopy_color_rgb(153, 160, 173), 0);

    g_playlist_scene.panel = lv_obj_create(g_playlist_scene.screen);
    lv_obj_set_size(g_playlist_scene.panel, 216, 166);
    lv_obj_set_pos(g_playlist_scene.panel, 12, 86);
    lv_obj_set_style_radius(g_playlist_scene.panel, 24, 0);
    lv_obj_set_style_border_width(g_playlist_scene.panel, 0, 0);
    lv_obj_set_style_bg_color(g_playlist_scene.panel, yoyopy_color_rgb(28, 33, 42), 0);
    lv_obj_set_style_bg_opa(g_playlist_scene.panel, LV_OPA_COVER, 0);
    lv_obj_set_style_pad_all(g_playlist_scene.panel, 0, 0);
    lv_obj_set_style_shadow_width(g_playlist_scene.panel, 0, 0);
    lv_obj_set_style_outline_width(g_playlist_scene.panel, 0, 0);
    lv_obj_set_scrollbar_mode(g_playlist_scene.panel, LV_SCROLLBAR_MODE_OFF);

    for(int index = 0; index < 4; ++index) {
        g_playlist_scene.item_panels[index] = lv_obj_create(g_playlist_scene.panel);
        lv_obj_set_size(g_playlist_scene.item_panels[index], 184, 42);
        lv_obj_set_pos(g_playlist_scene.item_panels[index], 16, 10 + (index * 50));
        lv_obj_set_style_radius(g_playlist_scene.item_panels[index], 16, 0);
        lv_obj_set_style_border_width(g_playlist_scene.item_panels[index], 2, 0);
        lv_obj_set_style_pad_all(g_playlist_scene.item_panels[index], 0, 0);
        lv_obj_set_style_shadow_width(g_playlist_scene.item_panels[index], 0, 0);
        lv_obj_set_style_outline_width(g_playlist_scene.item_panels[index], 0, 0);
        lv_obj_set_scrollbar_mode(g_playlist_scene.item_panels[index], LV_SCROLLBAR_MODE_OFF);

        g_playlist_scene.item_titles[index] = lv_label_create(g_playlist_scene.item_panels[index]);
        lv_obj_set_width(g_playlist_scene.item_titles[index], 118);
        lv_obj_set_pos(g_playlist_scene.item_titles[index], 14, 11);
        lv_label_set_long_mode(g_playlist_scene.item_titles[index], LV_LABEL_LONG_MODE_CLIP);
        lv_obj_set_style_text_font(g_playlist_scene.item_titles[index], &lv_font_montserrat_16, 0);

        g_playlist_scene.item_badges[index] = lv_label_create(g_playlist_scene.item_panels[index]);
        lv_obj_set_pos(g_playlist_scene.item_badges[index], 146, 12);
        lv_obj_set_style_text_font(g_playlist_scene.item_badges[index], &lv_font_montserrat_12, 0);
    }

    g_playlist_scene.empty_panel = lv_obj_create(g_playlist_scene.screen);
    lv_obj_set_size(g_playlist_scene.empty_panel, 204, 136);
    lv_obj_set_pos(g_playlist_scene.empty_panel, 18, 96);
    lv_obj_set_style_radius(g_playlist_scene.empty_panel, 22, 0);
    lv_obj_set_style_border_width(g_playlist_scene.empty_panel, 2, 0);
    lv_obj_set_style_pad_all(g_playlist_scene.empty_panel, 0, 0);
    lv_obj_set_style_shadow_width(g_playlist_scene.empty_panel, 0, 0);
    lv_obj_set_style_outline_width(g_playlist_scene.empty_panel, 0, 0);
    lv_obj_set_scrollbar_mode(g_playlist_scene.empty_panel, LV_SCROLLBAR_MODE_OFF);

    g_playlist_scene.empty_icon = lv_label_create(g_playlist_scene.empty_panel);
    lv_obj_set_style_text_font(g_playlist_scene.empty_icon, &lv_font_montserrat_24, 0);
    lv_obj_align(g_playlist_scene.empty_icon, LV_ALIGN_TOP_MID, 0, 16);

    g_playlist_scene.empty_title = lv_label_create(g_playlist_scene.empty_panel);
    lv_obj_set_width(g_playlist_scene.empty_title, 168);
    lv_obj_set_pos(g_playlist_scene.empty_title, 18, 60);
    lv_obj_set_style_text_font(g_playlist_scene.empty_title, &lv_font_montserrat_16, 0);
    lv_obj_set_style_text_align(g_playlist_scene.empty_title, LV_TEXT_ALIGN_CENTER, 0);

    g_playlist_scene.empty_subtitle = lv_label_create(g_playlist_scene.empty_panel);
    lv_obj_set_width(g_playlist_scene.empty_subtitle, 168);
    lv_obj_set_pos(g_playlist_scene.empty_subtitle, 18, 86);
    lv_label_set_long_mode(g_playlist_scene.empty_subtitle, LV_LABEL_LONG_MODE_WRAP);
    lv_obj_set_style_text_font(g_playlist_scene.empty_subtitle, &lv_font_montserrat_12, 0);
    lv_obj_set_style_text_align(g_playlist_scene.empty_subtitle, LV_TEXT_ALIGN_CENTER, 0);

    g_playlist_scene.footer_label = lv_label_create(g_playlist_scene.screen);
    lv_obj_set_style_text_font(g_playlist_scene.footer_label, &lv_font_montserrat_12, 0);
    lv_obj_set_style_text_align(g_playlist_scene.footer_label, LV_TEXT_ALIGN_CENTER, 0);
    lv_obj_align(g_playlist_scene.footer_label, LV_ALIGN_BOTTOM_MID, 0, -5);

    g_playlist_scene.built = 1;
    return 0;
}

int yoyopy_lvgl_playlist_sync(
    const char * title_text,
    const char * page_text,
    const char * footer,
    const char * item_0,
    const char * item_1,
    const char * item_2,
    const char * item_3,
    const char * badge_0,
    const char * badge_1,
    const char * badge_2,
    const char * badge_3,
    int32_t item_count,
    int32_t selected_visible_index,
    int32_t voip_state,
    int32_t battery_percent,
    int32_t charging,
    int32_t power_available,
    uint8_t accent_r,
    uint8_t accent_g,
    uint8_t accent_b,
    const char * empty_title,
    const char * empty_subtitle,
    const char * empty_icon_key
) {
    if(!g_playlist_scene.built) {
        yoyopy_set_error("playlist scene must be built before sync");
        return -1;
    }

    const lv_color_t background = yoyopy_color_rgb(18, 21, 28);
    const lv_color_t surface = yoyopy_color_rgb(28, 33, 42);
    const lv_color_t ink = yoyopy_color_rgb(243, 247, 250);
    const lv_color_t muted = yoyopy_color_rgb(153, 160, 173);
    const lv_color_t accent = yoyopy_color_rgb(accent_r, accent_g, accent_b);
    const lv_color_t accent_soft = yoyopy_mix_rgb(accent_r, accent_g, accent_b, 28, 33, 42, 55);
    const lv_color_t accent_dim = yoyopy_mix_rgb(accent_r, accent_g, accent_b, 18, 21, 28, 65);
    const lv_color_t selected_fill = yoyopy_mix_rgb(accent_r, accent_g, accent_b, 28, 33, 42, 88);
    const lv_color_t border = yoyopy_color_rgb(74, 79, 92);

    const char * items[4] = {item_0, item_1, item_2, item_3};
    const char * badges[4] = {badge_0, badge_1, badge_2, badge_3};

    lv_obj_set_style_bg_color(g_playlist_scene.screen, background, 0);
    lv_obj_set_style_bg_opa(g_playlist_scene.screen, LV_OPA_COVER, 0);
    yoyopy_apply_voip_dot(g_playlist_scene.voip_dot, voip_state);
    yoyopy_apply_battery(
        g_playlist_scene.battery_outline,
        g_playlist_scene.battery_fill,
        g_playlist_scene.battery_tip,
        battery_percent,
        charging,
        power_available
    );

    lv_label_set_text(g_playlist_scene.title_label, title_text != NULL ? title_text : "");
    lv_obj_set_style_text_color(g_playlist_scene.title_label, ink, 0);
    lv_obj_set_style_bg_color(g_playlist_scene.title_underline, accent, 0);
    lv_label_set_text(g_playlist_scene.page_label, page_text != NULL ? page_text : "");

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
        lv_label_set_text(g_playlist_scene.empty_icon, yoyopy_symbol_for_empty_icon(empty_icon_key));
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
        const char * badge_text = badges[index] != NULL ? badges[index] : "";
        lv_obj_clear_flag(g_playlist_scene.item_panels[index], LV_OBJ_FLAG_HIDDEN);
        lv_label_set_text(g_playlist_scene.item_titles[index], items[index] != NULL ? items[index] : "");
        lv_obj_set_style_bg_color(g_playlist_scene.item_panels[index], selected ? selected_fill : surface, 0);
        lv_obj_set_style_bg_opa(g_playlist_scene.item_panels[index], LV_OPA_COVER, 0);
        lv_obj_set_style_border_color(g_playlist_scene.item_panels[index], selected ? accent_soft : border, 0);
        lv_obj_set_style_text_color(g_playlist_scene.item_titles[index], selected ? ink : yoyopy_mix_rgb(243, 247, 250, 153, 160, 173, 12), 0);

        if(badge_text[0] == '\0') {
            lv_obj_add_flag(g_playlist_scene.item_badges[index], LV_OBJ_FLAG_HIDDEN);
        } else {
            lv_obj_clear_flag(g_playlist_scene.item_badges[index], LV_OBJ_FLAG_HIDDEN);
            lv_label_set_text(g_playlist_scene.item_badges[index], badge_text);
            lv_obj_set_style_text_color(g_playlist_scene.item_badges[index], selected ? accent : muted, 0);
            lv_obj_set_x(g_playlist_scene.item_badges[index], 184 - (int)lv_obj_get_width(g_playlist_scene.item_badges[index]) - 16);
        }
    }

    lv_label_set_text(g_playlist_scene.footer_label, footer != NULL ? footer : "");
    lv_obj_set_style_text_color(g_playlist_scene.footer_label, accent_dim, 0);
    lv_obj_align(g_playlist_scene.footer_label, LV_ALIGN_BOTTOM_MID, 0, -5);

    return 0;
}

void yoyopy_lvgl_playlist_destroy(void) {
    if(!g_playlist_scene.built) {
        return;
    }

    if(g_playlist_scene.screen != NULL) {
        lv_obj_clean(g_playlist_scene.screen);
    }
    yoyopy_clear_group();
    yoyopy_reset_playlist_scene_refs();
}

int yoyopy_lvgl_now_playing_build(void) {
    if(!g_initialized || g_display == NULL) {
        yoyopy_set_error("display must be registered before building the now-playing scene");
        return -1;
    }

    if(g_now_playing_scene.built) {
        return 0;
    }

    yoyopy_prepare_active_screen();

    g_now_playing_scene.screen = lv_screen_active();
    lv_obj_set_style_bg_color(g_now_playing_scene.screen, yoyopy_color_rgb(18, 21, 28), 0);
    lv_obj_set_style_bg_opa(g_now_playing_scene.screen, LV_OPA_COVER, 0);

    g_now_playing_scene.voip_dot = lv_obj_create(g_now_playing_scene.screen);
    lv_obj_remove_style_all(g_now_playing_scene.voip_dot);
    lv_obj_set_size(g_now_playing_scene.voip_dot, 8, 8);
    lv_obj_set_style_radius(g_now_playing_scene.voip_dot, LV_RADIUS_CIRCLE, 0);
    lv_obj_set_pos(g_now_playing_scene.voip_dot, 16, 10);

    g_now_playing_scene.battery_outline = lv_obj_create(g_now_playing_scene.screen);
    lv_obj_remove_style_all(g_now_playing_scene.battery_outline);
    lv_obj_set_size(g_now_playing_scene.battery_outline, 20, 10);
    lv_obj_set_pos(g_now_playing_scene.battery_outline, 202, 6);
    lv_obj_set_style_border_width(g_now_playing_scene.battery_outline, 1, 0);
    lv_obj_set_style_border_color(g_now_playing_scene.battery_outline, yoyopy_color_rgb(153, 160, 173), 0);
    lv_obj_set_style_radius(g_now_playing_scene.battery_outline, 2, 0);
    lv_obj_set_style_bg_opa(g_now_playing_scene.battery_outline, LV_OPA_TRANSP, 0);

    g_now_playing_scene.battery_fill = lv_obj_create(g_now_playing_scene.battery_outline);
    lv_obj_remove_style_all(g_now_playing_scene.battery_fill);
    lv_obj_set_pos(g_now_playing_scene.battery_fill, 1, 1);
    lv_obj_set_size(g_now_playing_scene.battery_fill, 18, 8);
    lv_obj_set_style_radius(g_now_playing_scene.battery_fill, 1, 0);
    lv_obj_set_style_bg_opa(g_now_playing_scene.battery_fill, LV_OPA_COVER, 0);

    g_now_playing_scene.battery_tip = lv_obj_create(g_now_playing_scene.screen);
    lv_obj_remove_style_all(g_now_playing_scene.battery_tip);
    lv_obj_set_size(g_now_playing_scene.battery_tip, 2, 4);
    lv_obj_set_pos(g_now_playing_scene.battery_tip, 222, 9);
    lv_obj_set_style_bg_color(g_now_playing_scene.battery_tip, yoyopy_color_rgb(153, 160, 173), 0);
    lv_obj_set_style_bg_opa(g_now_playing_scene.battery_tip, LV_OPA_COVER, 0);

    g_now_playing_scene.panel = lv_obj_create(g_now_playing_scene.screen);
    lv_obj_set_size(g_now_playing_scene.panel, 208, 194);
    lv_obj_set_pos(g_now_playing_scene.panel, 16, 42);
    lv_obj_set_style_radius(g_now_playing_scene.panel, 28, 0);
    lv_obj_set_style_border_width(g_now_playing_scene.panel, 2, 0);
    lv_obj_set_style_pad_all(g_now_playing_scene.panel, 0, 0);
    lv_obj_set_style_shadow_width(g_now_playing_scene.panel, 0, 0);
    lv_obj_set_style_outline_width(g_now_playing_scene.panel, 0, 0);
    lv_obj_set_scrollbar_mode(g_now_playing_scene.panel, LV_SCROLLBAR_MODE_OFF);

    g_now_playing_scene.icon_halo = lv_obj_create(g_now_playing_scene.panel);
    lv_obj_set_size(g_now_playing_scene.icon_halo, 76, 58);
    lv_obj_set_pos(g_now_playing_scene.icon_halo, 66, 16);
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
    lv_obj_set_size(g_now_playing_scene.state_chip, 92, 24);
    lv_obj_set_pos(g_now_playing_scene.state_chip, 58, 84);
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
    lv_obj_set_width(g_now_playing_scene.title_label, 176);
    lv_obj_set_pos(g_now_playing_scene.title_label, 16, 118);
    lv_label_set_long_mode(g_now_playing_scene.title_label, LV_LABEL_LONG_MODE_DOTS);
    lv_obj_set_style_text_font(g_now_playing_scene.title_label, &lv_font_montserrat_24, 0);
    lv_obj_set_style_text_align(g_now_playing_scene.title_label, LV_TEXT_ALIGN_CENTER, 0);

    g_now_playing_scene.artist_label = lv_label_create(g_now_playing_scene.panel);
    lv_obj_set_width(g_now_playing_scene.artist_label, 176);
    lv_obj_set_pos(g_now_playing_scene.artist_label, 16, 148);
    lv_label_set_long_mode(g_now_playing_scene.artist_label, LV_LABEL_LONG_MODE_DOTS);
    lv_obj_set_style_text_font(g_now_playing_scene.artist_label, &lv_font_montserrat_14, 0);
    lv_obj_set_style_text_align(g_now_playing_scene.artist_label, LV_TEXT_ALIGN_CENTER, 0);

    g_now_playing_scene.progress_track = lv_obj_create(g_now_playing_scene.panel);
    lv_obj_set_size(g_now_playing_scene.progress_track, 156, 8);
    lv_obj_set_pos(g_now_playing_scene.progress_track, 26, 174);
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
    lv_obj_set_style_text_font(g_now_playing_scene.footer_label, &lv_font_montserrat_12, 0);
    lv_obj_set_style_text_align(g_now_playing_scene.footer_label, LV_TEXT_ALIGN_CENTER, 0);
    lv_obj_align(g_now_playing_scene.footer_label, LV_ALIGN_BOTTOM_MID, 0, -5);

    g_now_playing_scene.built = 1;
    return 0;
}

int yoyopy_lvgl_now_playing_sync(
    const char * title_text,
    const char * artist_text,
    const char * state_text,
    const char * footer,
    int32_t progress_permille,
    int32_t voip_state,
    int32_t battery_percent,
    int32_t charging,
    int32_t power_available,
    uint8_t accent_r,
    uint8_t accent_g,
    uint8_t accent_b
) {
    if(!g_now_playing_scene.built) {
        yoyopy_set_error("now-playing scene must be built before sync");
        return -1;
    }

    const lv_color_t background = yoyopy_color_rgb(18, 21, 28);
    const lv_color_t surface = yoyopy_color_rgb(28, 33, 42);
    const lv_color_t ink = yoyopy_color_rgb(243, 247, 250);
    const lv_color_t muted = yoyopy_color_rgb(153, 160, 173);
    const lv_color_t progress_bg = yoyopy_color_rgb(22, 25, 32);
    const lv_color_t accent = yoyopy_color_rgb(accent_r, accent_g, accent_b);
    const lv_color_t accent_dim = yoyopy_mix_rgb(accent_r, accent_g, accent_b, 18, 21, 28, 65);
    const lv_color_t accent_soft = yoyopy_mix_rgb(accent_r, accent_g, accent_b, 28, 33, 42, 55);
    const lv_color_t halo_fill = yoyopy_mix_rgb(accent_r, accent_g, accent_b, 18, 21, 28, 80);
    const lv_color_t halo_border = yoyopy_mix_rgb(accent_r, accent_g, accent_b, 18, 21, 28, 60);

    if(progress_permille < 0) {
        progress_permille = 0;
    }
    if(progress_permille > 1000) {
        progress_permille = 1000;
    }

    lv_obj_set_style_bg_color(g_now_playing_scene.screen, background, 0);
    lv_obj_set_style_bg_opa(g_now_playing_scene.screen, LV_OPA_COVER, 0);
    yoyopy_apply_voip_dot(g_now_playing_scene.voip_dot, voip_state);
    yoyopy_apply_battery(
        g_now_playing_scene.battery_outline,
        g_now_playing_scene.battery_fill,
        g_now_playing_scene.battery_tip,
        battery_percent,
        charging,
        power_available
    );

    lv_obj_set_style_bg_color(g_now_playing_scene.panel, surface, 0);
    lv_obj_set_style_bg_opa(g_now_playing_scene.panel, LV_OPA_COVER, 0);
    lv_obj_set_style_border_color(g_now_playing_scene.panel, accent_dim, 0);

    lv_obj_set_style_bg_color(g_now_playing_scene.icon_halo, halo_fill, 0);
    lv_obj_set_style_bg_opa(g_now_playing_scene.icon_halo, LV_OPA_COVER, 0);
    lv_obj_set_style_border_color(g_now_playing_scene.icon_halo, halo_border, 0);
    lv_obj_set_style_text_color(g_now_playing_scene.icon_label, accent, 0);
    lv_obj_center(g_now_playing_scene.icon_label);

    lv_obj_set_style_bg_color(g_now_playing_scene.state_chip, accent_dim, 0);
    lv_obj_set_style_bg_opa(g_now_playing_scene.state_chip, LV_OPA_COVER, 0);
    lv_label_set_text(g_now_playing_scene.state_label, state_text != NULL ? state_text : "");
    lv_obj_set_style_text_color(g_now_playing_scene.state_label, accent, 0);
    lv_obj_center(g_now_playing_scene.state_label);

    lv_label_set_text(g_now_playing_scene.title_label, title_text != NULL ? title_text : "");
    lv_obj_set_style_text_color(g_now_playing_scene.title_label, ink, 0);

    lv_label_set_text(g_now_playing_scene.artist_label, artist_text != NULL ? artist_text : "");
    lv_obj_set_style_text_color(g_now_playing_scene.artist_label, muted, 0);

    lv_obj_set_style_bg_color(g_now_playing_scene.progress_track, progress_bg, 0);
    lv_obj_set_style_bg_opa(g_now_playing_scene.progress_track, LV_OPA_COVER, 0);
    lv_obj_set_style_bg_color(g_now_playing_scene.progress_fill, accent, 0);
    lv_obj_set_style_bg_opa(g_now_playing_scene.progress_fill, LV_OPA_COVER, 0);

    int fill_width = (156 * progress_permille) / 1000;
    if(fill_width <= 0) {
        lv_obj_add_flag(g_now_playing_scene.progress_fill, LV_OBJ_FLAG_HIDDEN);
    } else {
        lv_obj_clear_flag(g_now_playing_scene.progress_fill, LV_OBJ_FLAG_HIDDEN);
        lv_obj_set_size(g_now_playing_scene.progress_fill, fill_width, 8);
    }

    lv_label_set_text(g_now_playing_scene.footer_label, footer != NULL ? footer : "");
    lv_obj_set_style_text_color(g_now_playing_scene.footer_label, accent_soft, 0);
    lv_obj_align(g_now_playing_scene.footer_label, LV_ALIGN_BOTTOM_MID, 0, -5);

    return 0;
}

void yoyopy_lvgl_now_playing_destroy(void) {
    if(!g_now_playing_scene.built) {
        return;
    }

    if(g_now_playing_scene.screen != NULL) {
        lv_obj_clean(g_now_playing_scene.screen);
    }
    yoyopy_clear_group();
    yoyopy_reset_now_playing_scene_refs();
}

int yoyopy_lvgl_incoming_call_build(void) {
    if(!g_initialized || g_display == NULL) {
        yoyopy_set_error("display must be registered before building the incoming-call scene");
        return -1;
    }

    if(g_incoming_call_scene.built) {
        return 0;
    }

    yoyopy_prepare_active_screen();

    g_incoming_call_scene.screen = lv_screen_active();
    lv_obj_set_style_bg_color(g_incoming_call_scene.screen, yoyopy_color_rgb(18, 21, 28), 0);
    lv_obj_set_style_bg_opa(g_incoming_call_scene.screen, LV_OPA_COVER, 0);

    g_incoming_call_scene.voip_dot = lv_obj_create(g_incoming_call_scene.screen);
    lv_obj_remove_style_all(g_incoming_call_scene.voip_dot);
    lv_obj_set_size(g_incoming_call_scene.voip_dot, 8, 8);
    lv_obj_set_style_radius(g_incoming_call_scene.voip_dot, LV_RADIUS_CIRCLE, 0);
    lv_obj_set_pos(g_incoming_call_scene.voip_dot, 16, 10);

    g_incoming_call_scene.battery_outline = lv_obj_create(g_incoming_call_scene.screen);
    lv_obj_remove_style_all(g_incoming_call_scene.battery_outline);
    lv_obj_set_size(g_incoming_call_scene.battery_outline, 20, 10);
    lv_obj_set_pos(g_incoming_call_scene.battery_outline, 202, 6);
    lv_obj_set_style_border_width(g_incoming_call_scene.battery_outline, 1, 0);
    lv_obj_set_style_border_color(g_incoming_call_scene.battery_outline, yoyopy_color_rgb(153, 160, 173), 0);
    lv_obj_set_style_radius(g_incoming_call_scene.battery_outline, 2, 0);
    lv_obj_set_style_bg_opa(g_incoming_call_scene.battery_outline, LV_OPA_TRANSP, 0);

    g_incoming_call_scene.battery_fill = lv_obj_create(g_incoming_call_scene.battery_outline);
    lv_obj_remove_style_all(g_incoming_call_scene.battery_fill);
    lv_obj_set_pos(g_incoming_call_scene.battery_fill, 1, 1);
    lv_obj_set_size(g_incoming_call_scene.battery_fill, 18, 8);
    lv_obj_set_style_radius(g_incoming_call_scene.battery_fill, 1, 0);
    lv_obj_set_style_bg_opa(g_incoming_call_scene.battery_fill, LV_OPA_COVER, 0);

    g_incoming_call_scene.battery_tip = lv_obj_create(g_incoming_call_scene.screen);
    lv_obj_remove_style_all(g_incoming_call_scene.battery_tip);
    lv_obj_set_size(g_incoming_call_scene.battery_tip, 2, 4);
    lv_obj_set_pos(g_incoming_call_scene.battery_tip, 222, 9);
    lv_obj_set_style_bg_color(g_incoming_call_scene.battery_tip, yoyopy_color_rgb(153, 160, 173), 0);
    lv_obj_set_style_bg_opa(g_incoming_call_scene.battery_tip, LV_OPA_COVER, 0);

    g_incoming_call_scene.panel = lv_obj_create(g_incoming_call_scene.screen);
    lv_obj_set_size(g_incoming_call_scene.panel, 208, 194);
    lv_obj_set_pos(g_incoming_call_scene.panel, 16, 42);
    lv_obj_set_style_radius(g_incoming_call_scene.panel, 28, 0);
    lv_obj_set_style_border_width(g_incoming_call_scene.panel, 2, 0);
    lv_obj_set_style_pad_all(g_incoming_call_scene.panel, 0, 0);
    lv_obj_set_style_shadow_width(g_incoming_call_scene.panel, 0, 0);
    lv_obj_set_style_outline_width(g_incoming_call_scene.panel, 0, 0);
    lv_obj_set_scrollbar_mode(g_incoming_call_scene.panel, LV_SCROLLBAR_MODE_OFF);

    g_incoming_call_scene.icon_halo = lv_obj_create(g_incoming_call_scene.panel);
    lv_obj_set_size(g_incoming_call_scene.icon_halo, 76, 58);
    lv_obj_set_pos(g_incoming_call_scene.icon_halo, 66, 18);
    lv_obj_set_style_radius(g_incoming_call_scene.icon_halo, 20, 0);
    lv_obj_set_style_border_width(g_incoming_call_scene.icon_halo, 2, 0);
    lv_obj_set_style_shadow_width(g_incoming_call_scene.icon_halo, 0, 0);
    lv_obj_set_style_outline_width(g_incoming_call_scene.icon_halo, 0, 0);
    lv_obj_set_scrollbar_mode(g_incoming_call_scene.icon_halo, LV_SCROLLBAR_MODE_OFF);

    g_incoming_call_scene.icon_label = lv_label_create(g_incoming_call_scene.icon_halo);
    lv_label_set_text(g_incoming_call_scene.icon_label, LV_SYMBOL_CALL);
    lv_obj_set_style_text_font(g_incoming_call_scene.icon_label, &lv_font_montserrat_24, 0);
    lv_obj_center(g_incoming_call_scene.icon_label);

    g_incoming_call_scene.state_label = lv_label_create(g_incoming_call_scene.panel);
    lv_label_set_text(g_incoming_call_scene.state_label, "Incoming");
    lv_obj_set_width(g_incoming_call_scene.state_label, 160);
    lv_obj_set_pos(g_incoming_call_scene.state_label, 24, 88);
    lv_obj_set_style_text_font(g_incoming_call_scene.state_label, &lv_font_montserrat_14, 0);
    lv_obj_set_style_text_align(g_incoming_call_scene.state_label, LV_TEXT_ALIGN_CENTER, 0);

    g_incoming_call_scene.caller_name_label = lv_label_create(g_incoming_call_scene.panel);
    lv_obj_set_width(g_incoming_call_scene.caller_name_label, 176);
    lv_obj_set_pos(g_incoming_call_scene.caller_name_label, 16, 114);
    lv_label_set_long_mode(g_incoming_call_scene.caller_name_label, LV_LABEL_LONG_MODE_DOTS);
    lv_obj_set_style_text_font(g_incoming_call_scene.caller_name_label, &lv_font_montserrat_24, 0);
    lv_obj_set_style_text_align(g_incoming_call_scene.caller_name_label, LV_TEXT_ALIGN_CENTER, 0);

    g_incoming_call_scene.caller_address_label = lv_label_create(g_incoming_call_scene.panel);
    lv_obj_set_width(g_incoming_call_scene.caller_address_label, 176);
    lv_obj_set_pos(g_incoming_call_scene.caller_address_label, 16, 148);
    lv_label_set_long_mode(g_incoming_call_scene.caller_address_label, LV_LABEL_LONG_MODE_DOTS);
    lv_obj_set_style_text_font(g_incoming_call_scene.caller_address_label, &lv_font_montserrat_12, 0);
    lv_obj_set_style_text_align(g_incoming_call_scene.caller_address_label, LV_TEXT_ALIGN_CENTER, 0);

    g_incoming_call_scene.footer_label = lv_label_create(g_incoming_call_scene.screen);
    lv_obj_set_style_text_font(g_incoming_call_scene.footer_label, &lv_font_montserrat_12, 0);
    lv_obj_set_style_text_align(g_incoming_call_scene.footer_label, LV_TEXT_ALIGN_CENTER, 0);
    lv_obj_align(g_incoming_call_scene.footer_label, LV_ALIGN_BOTTOM_MID, 0, -5);

    g_incoming_call_scene.built = 1;
    return 0;
}

int yoyopy_lvgl_incoming_call_sync(
    const char * caller_name,
    const char * caller_address,
    const char * footer,
    int32_t voip_state,
    int32_t battery_percent,
    int32_t charging,
    int32_t power_available,
    uint8_t accent_r,
    uint8_t accent_g,
    uint8_t accent_b
) {
    if(!g_incoming_call_scene.built) {
        yoyopy_set_error("incoming-call scene must be built before sync");
        return -1;
    }

    const lv_color_t background = yoyopy_color_rgb(18, 21, 28);
    const lv_color_t surface = yoyopy_color_rgb(32, 35, 42);
    const lv_color_t ink = yoyopy_color_rgb(243, 247, 250);
    const lv_color_t muted = yoyopy_color_rgb(153, 160, 173);
    const lv_color_t accent = yoyopy_color_rgb(accent_r, accent_g, accent_b);
    const lv_color_t accent_dim = yoyopy_mix_rgb(accent_r, accent_g, accent_b, 18, 21, 28, 65);
    const lv_color_t halo_fill = yoyopy_mix_rgb(accent_r, accent_g, accent_b, 18, 21, 28, 80);
    const lv_color_t halo_border = yoyopy_mix_rgb(accent_r, accent_g, accent_b, 18, 21, 28, 60);

    lv_obj_set_style_bg_color(g_incoming_call_scene.screen, background, 0);
    lv_obj_set_style_bg_opa(g_incoming_call_scene.screen, LV_OPA_COVER, 0);
    yoyopy_apply_voip_dot(g_incoming_call_scene.voip_dot, voip_state);
    yoyopy_apply_battery(
        g_incoming_call_scene.battery_outline,
        g_incoming_call_scene.battery_fill,
        g_incoming_call_scene.battery_tip,
        battery_percent,
        charging,
        power_available
    );

    lv_obj_set_style_bg_color(g_incoming_call_scene.panel, surface, 0);
    lv_obj_set_style_bg_opa(g_incoming_call_scene.panel, LV_OPA_COVER, 0);
    lv_obj_set_style_border_color(g_incoming_call_scene.panel, accent_dim, 0);

    lv_obj_set_style_bg_color(g_incoming_call_scene.icon_halo, halo_fill, 0);
    lv_obj_set_style_bg_opa(g_incoming_call_scene.icon_halo, LV_OPA_COVER, 0);
    lv_obj_set_style_border_color(g_incoming_call_scene.icon_halo, halo_border, 0);
    lv_obj_set_style_text_color(g_incoming_call_scene.icon_label, accent, 0);
    lv_obj_center(g_incoming_call_scene.icon_label);

    lv_obj_set_style_text_color(g_incoming_call_scene.state_label, accent, 0);
    lv_label_set_text(g_incoming_call_scene.caller_name_label, caller_name != NULL ? caller_name : "");
    lv_obj_set_style_text_color(g_incoming_call_scene.caller_name_label, ink, 0);
    lv_label_set_text(g_incoming_call_scene.caller_address_label, caller_address != NULL ? caller_address : "");
    lv_obj_set_style_text_color(g_incoming_call_scene.caller_address_label, muted, 0);

    lv_label_set_text(g_incoming_call_scene.footer_label, footer != NULL ? footer : "");
    lv_obj_set_style_text_color(g_incoming_call_scene.footer_label, accent_dim, 0);
    lv_obj_align(g_incoming_call_scene.footer_label, LV_ALIGN_BOTTOM_MID, 0, -5);

    return 0;
}

void yoyopy_lvgl_incoming_call_destroy(void) {
    if(!g_incoming_call_scene.built) {
        return;
    }

    if(g_incoming_call_scene.screen != NULL) {
        lv_obj_clean(g_incoming_call_scene.screen);
    }
    yoyopy_clear_group();
    yoyopy_reset_incoming_call_scene_refs();
}

int yoyopy_lvgl_init(void) {
    if(g_initialized) {
        return 0;
    }

    yoyopy_set_error(NULL);
    lv_init();
    g_initialized = 1;
    return 0;
}

void yoyopy_lvgl_shutdown(void) {
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
    yoyopy_set_error(NULL);
}

int yoyopy_lvgl_register_display(
    int32_t width,
    int32_t height,
    uint32_t buffer_pixel_count,
    yoyopy_lvgl_flush_cb_t flush_cb,
    void * user_data
) {
    if(!g_initialized) {
        yoyopy_set_error("LVGL must be initialized before registering a display");
        return -1;
    }

    if(g_display != NULL) {
        yoyopy_set_error("display already registered");
        return -1;
    }

    if(flush_cb == NULL) {
        yoyopy_set_error("flush callback is required");
        return -1;
    }

    g_display = lv_display_create(width, height);
    if(g_display == NULL) {
        yoyopy_set_error("lv_display_create failed");
        return -1;
    }

    g_draw_buf_bytes = buffer_pixel_count * sizeof(lv_color_t);
    g_draw_buf = lv_malloc(g_draw_buf_bytes);
    if(g_draw_buf == NULL) {
        yoyopy_set_error("draw buffer allocation failed");
        return -1;
    }

    g_flush_cb = flush_cb;
    g_flush_user_data = user_data;

    lv_display_set_flush_cb(g_display, yoyopy_flush_cb);
    lv_display_set_buffers(
        g_display,
        g_draw_buf,
        NULL,
        g_draw_buf_bytes,
        LV_DISPLAY_RENDER_MODE_PARTIAL
    );

    return 0;
}

int yoyopy_lvgl_register_input(void) {
    if(!g_initialized || g_display == NULL) {
        yoyopy_set_error("display must be registered before input");
        return -1;
    }

    if(g_group == NULL) {
        g_group = lv_group_create();
        lv_group_set_default(g_group);
    }

    if(g_indev == NULL) {
        g_indev = lv_indev_create();
        if(g_indev == NULL) {
            yoyopy_set_error("lv_indev_create failed");
            return -1;
        }
        lv_indev_set_type(g_indev, LV_INDEV_TYPE_KEYPAD);
        lv_indev_set_read_cb(g_indev, yoyopy_indev_read_cb);
        lv_indev_set_group(g_indev, g_group);
    }

    return 0;
}

void yoyopy_lvgl_tick_inc(uint32_t ms) {
    if(g_initialized) {
        lv_tick_inc(ms);
    }
}

uint32_t yoyopy_lvgl_timer_handler(void) {
    if(!g_initialized) {
        return 0U;
    }

    return lv_timer_handler();
}

int yoyopy_lvgl_queue_key_event(int32_t key, int32_t pressed) {
    if(g_key_count >= KEY_QUEUE_CAPACITY) {
        yoyopy_set_error("input queue full");
        return -1;
    }

    g_key_queue[g_key_tail].key = key;
    g_key_queue[g_key_tail].pressed = pressed;
    g_key_tail = (g_key_tail + 1) % KEY_QUEUE_CAPACITY;
    g_key_count++;
    return 0;
}

int yoyopy_lvgl_show_probe_scene(int32_t scene_id) {
    if(!g_initialized || g_display == NULL) {
        yoyopy_set_error("display must be registered before showing a scene");
        return -1;
    }

    switch(scene_id) {
        case YOYOPY_LVGL_SCENE_CARD:
            yoyopy_build_card_scene();
            break;
        case YOYOPY_LVGL_SCENE_LIST:
            yoyopy_build_list_scene();
            break;
        case YOYOPY_LVGL_SCENE_FOOTER:
            yoyopy_build_footer_scene();
            break;
        case YOYOPY_LVGL_SCENE_CAROUSEL:
            yoyopy_build_carousel_scene();
            break;
        default:
            yoyopy_set_error("unknown probe scene");
            return -1;
    }

    return 0;
}

void yoyopy_lvgl_clear_screen(void) {
    if(!g_initialized || g_display == NULL) {
        return;
    }

    lv_obj_t * screen = lv_screen_active();
    lv_obj_clean(screen);
    yoyopy_clear_group();
    yoyopy_reset_scene_refs();
}

const char * yoyopy_lvgl_last_error(void) {
    return g_last_error;
}

const char * yoyopy_lvgl_version(void) {
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
