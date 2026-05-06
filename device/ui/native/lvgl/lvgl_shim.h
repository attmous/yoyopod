#ifndef YOYOPOD_LVGL_SHIM_H
#define YOYOPOD_LVGL_SHIM_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef void (*yoyopod_lvgl_flush_cb_t)(
    int32_t x,
    int32_t y,
    int32_t width,
    int32_t height,
    const unsigned char * pixel_data,
    uint32_t byte_length,
    void * user_data
);

enum yoyopod_lvgl_key {
    YOYOPOD_LVGL_KEY_NONE = 0,
    YOYOPOD_LVGL_KEY_RIGHT = 1,
    YOYOPOD_LVGL_KEY_ENTER = 2,
    YOYOPOD_LVGL_KEY_ESC = 3
};

enum yoyopod_lvgl_probe_scene {
    YOYOPOD_LVGL_SCENE_CARD = 1,
    YOYOPOD_LVGL_SCENE_LIST = 2,
    YOYOPOD_LVGL_SCENE_FOOTER = 3,
    YOYOPOD_LVGL_SCENE_CAROUSEL = 4
};

int yoyopod_lvgl_init(void);
void yoyopod_lvgl_shutdown(void);
int yoyopod_lvgl_register_display(
    int32_t width,
    int32_t height,
    uint32_t buffer_pixel_count,
    yoyopod_lvgl_flush_cb_t flush_cb,
    void * user_data
);
int yoyopod_lvgl_register_input(void);
void yoyopod_lvgl_tick_inc(uint32_t ms);
uint32_t yoyopod_lvgl_timer_handler(void);
int yoyopod_lvgl_queue_key_event(int32_t key, int32_t pressed);
int yoyopod_lvgl_show_probe_scene(int32_t scene_id);
int yoyopod_lvgl_set_status_bar_state(
    int32_t network_enabled,
    int32_t network_connected,
    int32_t wifi_connected,
    int32_t signal_strength,
    int32_t gps_has_fix
);
int yoyopod_lvgl_hub_build(void);
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
);
void yoyopod_lvgl_hub_destroy(void);
int yoyopod_lvgl_talk_build(void);
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
);
void yoyopod_lvgl_talk_destroy(void);
int yoyopod_lvgl_talk_actions_build(void);
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
);
void yoyopod_lvgl_talk_actions_destroy(void);
int yoyopod_lvgl_listen_build(void);
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
);
void yoyopod_lvgl_listen_destroy(void);
int yoyopod_lvgl_playlist_build(void);
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
);
void yoyopod_lvgl_playlist_destroy(void);
int yoyopod_lvgl_now_playing_build(void);
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
);
void yoyopod_lvgl_now_playing_destroy(void);
int yoyopod_lvgl_incoming_call_build(void);
int yoyopod_lvgl_incoming_call_sync(
    const char * caller_name,
    const char * caller_address,
    const char * footer,
    int32_t voip_state,
    int32_t battery_percent,
    int32_t charging,
    int32_t power_available,
    uint32_t accent_rgb
);
void yoyopod_lvgl_incoming_call_destroy(void);
int yoyopod_lvgl_outgoing_call_build(void);
int yoyopod_lvgl_outgoing_call_sync(
    const char * callee_name,
    const char * callee_address,
    const char * footer,
    int32_t voip_state,
    int32_t battery_percent,
    int32_t charging,
    int32_t power_available,
    uint32_t accent_rgb
);
void yoyopod_lvgl_outgoing_call_destroy(void);
int yoyopod_lvgl_in_call_build(void);
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
);
void yoyopod_lvgl_in_call_destroy(void);
int yoyopod_lvgl_ask_build(void);
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
);
void yoyopod_lvgl_ask_destroy(void);
int yoyopod_lvgl_power_build(void);
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
);
void yoyopod_lvgl_power_destroy(void);
void yoyopod_lvgl_clear_screen(void);
void yoyopod_lvgl_force_refresh(void);
int32_t yoyopod_lvgl_snapshot(unsigned char * output_buf, uint32_t buf_size);
const char * yoyopod_lvgl_last_error(void);
const char * yoyopod_lvgl_version(void);

#ifdef __cplusplus
}
#endif

#endif
