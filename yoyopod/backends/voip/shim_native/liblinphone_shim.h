#ifndef YOYOPOD_LIBLINPHONE_SHIM_H
#define YOYOPOD_LIBLINPHONE_SHIM_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    int32_t type;
    int32_t registration_state;
    int32_t call_state;
    int32_t message_kind;
    int32_t message_direction;
    int32_t message_delivery_state;
    int32_t duration_ms;
    int32_t unread;
    char message_id[128];
    char peer_sip_address[256];
    char sender_sip_address[256];
    char recipient_sip_address[256];
    char local_file_path[512];
    char mime_type[128];
    char text[1024];
    char reason[256];
} yoyopod_liblinphone_event_t;

int yoyopod_liblinphone_init(void);
void yoyopod_liblinphone_shutdown(void);
int yoyopod_liblinphone_start(
    const char *sip_server,
    const char *sip_username,
    const char *sip_password,
    const char *sip_password_ha1,
    const char *sip_identity,
    const char *factory_config_path,
    const char *transport,
    const char *stun_server,
    const char *conference_factory_uri,
    const char *file_transfer_server_url,
    const char *lime_server_url,
    int32_t auto_download_incoming_voice_recordings,
    const char *playback_device_id,
    const char *ringer_device_id,
    const char *capture_device_id,
    const char *media_device_id,
    int32_t echo_cancellation,
    int32_t mic_gain,
    int32_t output_volume,
    const char *voice_note_store_dir
);
void yoyopod_liblinphone_stop(void);
void yoyopod_liblinphone_iterate(void);
int yoyopod_liblinphone_poll_event(yoyopod_liblinphone_event_t *event_out);
int yoyopod_liblinphone_make_call(const char *sip_address);
int yoyopod_liblinphone_answer_call(void);
int yoyopod_liblinphone_reject_call(void);
int yoyopod_liblinphone_hangup(void);
int yoyopod_liblinphone_set_muted(int32_t muted);
int yoyopod_liblinphone_send_text_message(
    const char *sip_address,
    const char *text,
    char *message_id_out,
    uint32_t message_id_out_size
);
int yoyopod_liblinphone_start_voice_recording(const char *file_path);
int yoyopod_liblinphone_stop_voice_recording(int32_t *duration_ms_out);
int yoyopod_liblinphone_cancel_voice_recording(void);
int yoyopod_liblinphone_send_voice_note(
    const char *sip_address,
    const char *file_path,
    int32_t duration_ms,
    const char *mime_type,
    char *message_id_out,
    uint32_t message_id_out_size
);
const char *yoyopod_liblinphone_last_error(void);
const char *yoyopod_liblinphone_version(void);

#ifdef __cplusplus
}
#endif

#endif
