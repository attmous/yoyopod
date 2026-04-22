#include "liblinphone_shim.h"

#include <ctype.h>
#include <pthread.h>
#include <stdarg.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <time.h>
#include <unistd.h>

#if defined(__has_include)
#if __has_include(<linphone/api/c-account.h>)
#define YOYOPOD_HAS_LINPHONE_ACCOUNT_API 1
#else
#define YOYOPOD_HAS_LINPHONE_ACCOUNT_API 0
#endif
#if __has_include(<linphone/api/c-recorder.h>)
#define YOYOPOD_HAS_LINPHONE_RECORDER_API 1
#else
#define YOYOPOD_HAS_LINPHONE_RECORDER_API 0
#endif
#else
#define YOYOPOD_HAS_LINPHONE_ACCOUNT_API 1
#define YOYOPOD_HAS_LINPHONE_RECORDER_API 1
#endif

#if YOYOPOD_HAS_LINPHONE_ACCOUNT_API
#include <linphone/api/c-account-cbs.h>
#include <linphone/api/c-account-params.h>
#include <linphone/api/c-account.h>
#else
#include <linphone/callbacks.h>
#include <linphone/sipsetup.h>
#include <linphone/proxy_config.h>
#endif
#include <linphone/api/c-address.h>
#include <linphone/api/c-auth-info.h>
#include <linphone/api/c-call.h>
#include <linphone/api/c-chat-message-cbs.h>
#include <linphone/api/c-chat-message.h>
#include <linphone/api/c-chat-room.h>
#include <linphone/api/c-chat-room-cbs.h>
#include <linphone/api/c-chat-room-params.h>
#include <linphone/api/c-content.h>
#if defined(__has_include) && __has_include(<linphone/api/c-event.h>)
#include <linphone/api/c-event.h>
#else
#include <linphone/event.h>
#endif
#include <linphone/api/c-event-log.h>
#if defined(__has_include) && __has_include(<linphone/api/c-factory.h>)
#include <linphone/api/c-factory.h>
#else
#include <linphone/factory.h>
#endif
#if defined(__has_include) && __has_include(<linphone/api/c-nat-policy.h>)
#include <linphone/api/c-nat-policy.h>
#else
#include <linphone/nat_policy.h>
#endif
#if YOYOPOD_HAS_LINPHONE_RECORDER_API
#include <linphone/api/c-recorder.h>
#endif
#include <bctoolbox/list.h>
#include <linphone/buffer.h>
#include <linphone/core.h>
#include <linphone/error_info.h>
#include <linphone/im_notif_policy.h>
#include <linphone/misc.h>

#define YOYOPOD_EVENT_QUEUE_CAPACITY 128

enum {
    YOYOPOD_EVENT_NONE = 0,
    YOYOPOD_EVENT_REGISTRATION = 1,
    YOYOPOD_EVENT_CALL_STATE = 2,
    YOYOPOD_EVENT_INCOMING_CALL = 3,
    YOYOPOD_EVENT_BACKEND_STOPPED = 4,
    YOYOPOD_EVENT_MESSAGE_RECEIVED = 5,
    YOYOPOD_EVENT_MESSAGE_DELIVERY_CHANGED = 6,
    YOYOPOD_EVENT_MESSAGE_DOWNLOAD_COMPLETED = 7,
    YOYOPOD_EVENT_MESSAGE_FAILED = 8
};

enum {
    YOYOPOD_REGISTRATION_NONE = 0,
    YOYOPOD_REGISTRATION_PROGRESS = 1,
    YOYOPOD_REGISTRATION_OK = 2,
    YOYOPOD_REGISTRATION_CLEARED = 3,
    YOYOPOD_REGISTRATION_FAILED = 4
};

enum {
    YOYOPOD_CALL_IDLE = 0,
    YOYOPOD_CALL_INCOMING = 1,
    YOYOPOD_CALL_OUTGOING_INIT = 2,
    YOYOPOD_CALL_OUTGOING_PROGRESS = 3,
    YOYOPOD_CALL_OUTGOING_RINGING = 4,
    YOYOPOD_CALL_OUTGOING_EARLY_MEDIA = 5,
    YOYOPOD_CALL_CONNECTED = 6,
    YOYOPOD_CALL_STREAMS_RUNNING = 7,
    YOYOPOD_CALL_PAUSED = 8,
    YOYOPOD_CALL_PAUSED_BY_REMOTE = 9,
    YOYOPOD_CALL_UPDATED_BY_REMOTE = 10,
    YOYOPOD_CALL_RELEASED = 11,
    YOYOPOD_CALL_ERROR = 12,
    YOYOPOD_CALL_END = 13
};

enum {
    YOYOPOD_MESSAGE_KIND_TEXT = 1,
    YOYOPOD_MESSAGE_KIND_VOICE_NOTE = 2
};

enum {
    YOYOPOD_MESSAGE_DIRECTION_INCOMING = 1,
    YOYOPOD_MESSAGE_DIRECTION_OUTGOING = 2
};

enum {
    YOYOPOD_MESSAGE_DELIVERY_QUEUED = 1,
    YOYOPOD_MESSAGE_DELIVERY_SENDING = 2,
    YOYOPOD_MESSAGE_DELIVERY_SENT = 3,
    YOYOPOD_MESSAGE_DELIVERY_DELIVERED = 4,
    YOYOPOD_MESSAGE_DELIVERY_FAILED = 5
};

#if YOYOPOD_HAS_LINPHONE_ACCOUNT_API
typedef LinphoneAccount yoyopod_linphone_account_t;
typedef LinphoneAccountCbs yoyopod_linphone_account_cbs_t;
#else
typedef LinphoneProxyConfig yoyopod_linphone_account_t;
typedef void yoyopod_linphone_account_cbs_t;
#endif

#if YOYOPOD_HAS_LINPHONE_RECORDER_API
typedef LinphoneRecorder yoyopod_linphone_recorder_t;
#else
typedef void yoyopod_linphone_recorder_t;
#endif

typedef struct {
    bool initialized;
    bool started;
    LinphoneFactory *factory;
    LinphoneCore *core;
    yoyopod_linphone_account_t *account;
    yoyopod_linphone_account_cbs_t *account_cbs;
    LinphoneCoreCbs *core_cbs;
    LinphoneChatMessageCbs *message_cbs;
    LinphoneChatRoomCbs *chat_room_cbs;
    LinphoneCall *current_call;
    yoyopod_linphone_recorder_t *current_recorder;
    bool recorder_running;
    bool auto_download_incoming_voice_recordings;
    char voice_note_store_dir[512];
    char current_recording_path[512];
    char configured_conference_factory_uri[256];
    char configured_file_transfer_server_url[256];
    char configured_lime_server_url[256];
    LinphoneChatRoom *attached_chat_rooms[64];
    size_t attached_chat_room_count;
    pthread_mutex_t queue_lock;
    yoyopod_liblinphone_event_t queue[YOYOPOD_EVENT_QUEUE_CAPACITY];
    size_t queue_head;
    size_t queue_tail;
    unsigned long long message_counter;
} yoyopod_liblinphone_state_t;

static yoyopod_liblinphone_state_t g_state = {0};
static pthread_mutex_t g_error_lock = PTHREAD_MUTEX_INITIALIZER;
static char g_last_error[512] = "";

static void yoyopod_build_chat_room_peer(
    LinphoneChatRoom *chat_room,
    char *buffer,
    size_t buffer_size
);

static void yoyopod_build_specs_string(char *buffer, size_t buffer_size);
static const char *yoyopod_chat_message_text(const LinphoneChatMessage *message);
static int yoyopod_chat_room_is_read_only_compat(const LinphoneChatRoom *chat_room);
static int yoyopod_chat_room_params_ephemeral_mode_compat(const LinphoneChatRoomParams *params);
static long yoyopod_chat_room_params_ephemeral_lifetime_compat(const LinphoneChatRoomParams *params);
static const LinphoneAddress *yoyopod_event_to_address(const LinphoneEvent *linphone_event);
static LinphoneChatMessage *yoyopod_chat_room_create_text_message(
    LinphoneChatRoom *chat_room,
    const char *text
);

static void yoyopod_set_error(const char *format, ...) {
    va_list args;
    pthread_mutex_lock(&g_error_lock);
    va_start(args, format);
    vsnprintf(g_last_error, sizeof(g_last_error), format, args);
    va_end(args);
    pthread_mutex_unlock(&g_error_lock);
}

static void yoyopod_clear_error(void) {
    pthread_mutex_lock(&g_error_lock);
    g_last_error[0] = '\0';
    pthread_mutex_unlock(&g_error_lock);
}

static void yoyopod_debug_log(const char *format, ...) {
    va_list args;
    va_start(args, format);
    fprintf(stderr, "YOYOPOD-LIBLINPHONE: ");
    vfprintf(stderr, format, args);
    fprintf(stderr, "\n");
    fflush(stderr);
    va_end(args);
}

static void yoyopod_copy_string(char *destination, size_t destination_size, const char *source) {
    if (destination_size == 0) {
        return;
    }
    if (source == NULL) {
        destination[0] = '\0';
        return;
    }
    snprintf(destination, destination_size, "%s", source);
}

static const char *yoyopod_safe_string(const char *value) {
    return value != NULL ? value : "";
}

static int yoyopod_map_registration_state(LinphoneRegistrationState state) {
    switch (state) {
        case LinphoneRegistrationProgress:
            return YOYOPOD_REGISTRATION_PROGRESS;
        case LinphoneRegistrationOk:
            return YOYOPOD_REGISTRATION_OK;
        case LinphoneRegistrationCleared:
            return YOYOPOD_REGISTRATION_CLEARED;
        case LinphoneRegistrationFailed:
            return YOYOPOD_REGISTRATION_FAILED;
        case LinphoneRegistrationNone:
        default:
            return YOYOPOD_REGISTRATION_NONE;
    }
}

static int yoyopod_map_call_state(LinphoneCallState state) {
    switch (state) {
        case LinphoneCallIncomingReceived:
        case LinphoneCallIncomingEarlyMedia:
            return YOYOPOD_CALL_INCOMING;
        case LinphoneCallOutgoingInit:
            return YOYOPOD_CALL_OUTGOING_INIT;
        case LinphoneCallOutgoingProgress:
            return YOYOPOD_CALL_OUTGOING_PROGRESS;
        case LinphoneCallOutgoingRinging:
            return YOYOPOD_CALL_OUTGOING_RINGING;
        case LinphoneCallOutgoingEarlyMedia:
            return YOYOPOD_CALL_OUTGOING_EARLY_MEDIA;
        case LinphoneCallConnected:
            return YOYOPOD_CALL_CONNECTED;
        case LinphoneCallStreamsRunning:
            return YOYOPOD_CALL_STREAMS_RUNNING;
        case LinphoneCallPaused:
            return YOYOPOD_CALL_PAUSED;
        case LinphoneCallPausedByRemote:
            return YOYOPOD_CALL_PAUSED_BY_REMOTE;
        case LinphoneCallUpdatedByRemote:
        case LinphoneCallUpdating:
        case LinphoneCallEarlyUpdatedByRemote:
        case LinphoneCallEarlyUpdating:
            return YOYOPOD_CALL_UPDATED_BY_REMOTE;
        case LinphoneCallReleased:
            return YOYOPOD_CALL_RELEASED;
        case LinphoneCallError:
            return YOYOPOD_CALL_ERROR;
        case LinphoneCallEnd:
            return YOYOPOD_CALL_END;
        case LinphoneCallIdle:
        default:
            return YOYOPOD_CALL_IDLE;
    }
}

static int yoyopod_map_message_delivery_state(LinphoneChatMessageState state) {
    switch (state) {
        case LinphoneChatMessageStateIdle:
            return YOYOPOD_MESSAGE_DELIVERY_QUEUED;
        case LinphoneChatMessageStateInProgress:
        case LinphoneChatMessageStateFileTransferInProgress:
            return YOYOPOD_MESSAGE_DELIVERY_SENDING;
        case LinphoneChatMessageStateDelivered:
        case LinphoneChatMessageStateFileTransferDone:
            return YOYOPOD_MESSAGE_DELIVERY_SENT;
        case LinphoneChatMessageStateDeliveredToUser:
        case LinphoneChatMessageStateDisplayed:
            return YOYOPOD_MESSAGE_DELIVERY_DELIVERED;
        case LinphoneChatMessageStateNotDelivered:
        case LinphoneChatMessageStateFileTransferError:
        default:
            return YOYOPOD_MESSAGE_DELIVERY_FAILED;
    }
}

static int yoyopod_path_exists(const char *path) {
    if (path == NULL || path[0] == '\0') {
        return 0;
    }
    return access(path, F_OK) == 0;
}

static void yoyopod_ensure_directory(const char *path) {
    char buffer[512];
    size_t length;
    size_t index;

    if (path == NULL || path[0] == '\0') {
        return;
    }

    yoyopod_copy_string(buffer, sizeof(buffer), path);
    length = strlen(buffer);
    if (length == 0) {
        return;
    }

    if (buffer[length - 1] == '/') {
        buffer[length - 1] = '\0';
    }

    for (index = 1; buffer[index] != '\0'; ++index) {
        if (buffer[index] == '/') {
            buffer[index] = '\0';
            mkdir(buffer, 0775);
            buffer[index] = '/';
        }
    }
    mkdir(buffer, 0775);
}

static void yoyopod_build_address_uri(const LinphoneAddress *address, char *buffer, size_t buffer_size) {
    const char *username;
    const char *domain;
    if (buffer_size == 0) {
        return;
    }
    buffer[0] = '\0';
    if (address == NULL) {
        return;
    }

    username = linphone_address_get_username(address);
    domain = linphone_address_get_domain(address);
    if (username != NULL && domain != NULL) {
        snprintf(buffer, buffer_size, "sip:%s@%s", username, domain);
        return;
    }
    if (domain != NULL) {
        snprintf(buffer, buffer_size, "sip:%s", domain);
    }
}

static void yoyopod_build_message_id(LinphoneChatMessage *message, char *buffer, size_t buffer_size) {
    const char *message_id;
    const char *user_data;
    struct timespec now;

    if (buffer_size == 0) {
        return;
    }
    buffer[0] = '\0';
    if (message == NULL) {
        return;
    }

    message_id = linphone_chat_message_get_message_id(message);
    if (message_id != NULL && message_id[0] != '\0') {
        yoyopod_copy_string(buffer, buffer_size, message_id);
        return;
    }

    user_data = (const char *)linphone_chat_message_get_user_data(message);
    if (user_data != NULL && user_data[0] != '\0') {
        yoyopod_copy_string(buffer, buffer_size, user_data);
        return;
    }

    clock_gettime(CLOCK_REALTIME, &now);
    g_state.message_counter += 1;
    snprintf(buffer, buffer_size, "local-%lld-%llu", (long long)now.tv_sec, g_state.message_counter);
    linphone_chat_message_set_user_data(message, strdup(buffer));
}

static void yoyopod_build_mime_type(const LinphoneContent *content, char *buffer, size_t buffer_size) {
    const char *type;
    const char *subtype;
    if (buffer_size == 0) {
        return;
    }
    buffer[0] = '\0';
    if (content == NULL) {
        return;
    }
    type = linphone_content_get_type(content);
    subtype = linphone_content_get_subtype(content);
    if (type != NULL && subtype != NULL) {
        snprintf(buffer, buffer_size, "%s/%s", type, subtype);
    } else if (type != NULL) {
        yoyopod_copy_string(buffer, buffer_size, type);
    }
}

static int yoyopod_string_contains(const char *value, const char *needle) {
    return value != NULL && needle != NULL && strstr(value, needle) != NULL;
}

static int yoyopod_extract_xml_tag_value(
    const char *xml,
    const char *open_tag,
    const char *close_tag,
    char *buffer,
    size_t buffer_size
) {
    const char *start;
    const char *end;
    size_t length;

    if (buffer_size == 0) {
        return 0;
    }
    buffer[0] = '\0';
    if (xml == NULL || open_tag == NULL || close_tag == NULL) {
        return 0;
    }

    start = strstr(xml, open_tag);
    if (start == NULL) {
        return 0;
    }
    start += strlen(open_tag);
    end = strstr(start, close_tag);
    if (end == NULL || end <= start) {
        return 0;
    }
    length = (size_t)(end - start);
    if (length >= buffer_size) {
        length = buffer_size - 1U;
    }
    memcpy(buffer, start, length);
    buffer[length] = '\0';
    return 1;
}

static int yoyopod_is_file_transfer_xml_content(const LinphoneContent *content) {
    const char *type;
    const char *subtype;

    if (content == NULL) {
        return 0;
    }
    type = linphone_content_get_type(content);
    subtype = linphone_content_get_subtype(content);
    return type != NULL && subtype != NULL
           && strcmp(type, "application") == 0
           && strcmp(subtype, "vnd.gsma.rcs-ft-http+xml") == 0;
}

static int yoyopod_is_voice_note_content(const LinphoneContent *content) {
    const char *type;
    if (content == NULL) {
        return 0;
    }
    type = linphone_content_get_type(content);
    return type != NULL && strcmp(type, "audio") == 0;
}

static int yoyopod_is_voice_note_xml_text(const char *text) {
    return yoyopod_string_contains(text, "voice-recording=yes");
}

static void yoyopod_extract_voice_note_payload_mime(
    LinphoneChatMessage *message,
    LinphoneContent *content,
    char *buffer,
    size_t buffer_size
) {
    char xml_value[256];
    const char *text;
    char *separator;

    if (buffer_size == 0) {
        return;
    }
    buffer[0] = '\0';

    if (yoyopod_is_voice_note_content(content)) {
        yoyopod_build_mime_type(content, buffer, buffer_size);
        return;
    }

    text = yoyopod_chat_message_text(message);
    if (!yoyopod_extract_xml_tag_value(
            text,
            "<content-type>",
            "</content-type>",
            xml_value,
            sizeof(xml_value)
        )) {
        return;
    }
    separator = strchr(xml_value, ';');
    if (separator != NULL) {
        *separator = '\0';
    }
    yoyopod_copy_string(buffer, buffer_size, xml_value);
}

static int yoyopod_extract_voice_note_duration_ms(LinphoneChatMessage *message) {
    char value[64];
    const char *text = yoyopod_chat_message_text(message);
    if (
        !yoyopod_extract_xml_tag_value(
            text,
            "<am:playing-length>",
            "</am:playing-length>",
            value,
            sizeof(value)
        )
    ) {
        return 0;
    }
    return atoi(value);
}

static void yoyopod_extract_voice_note_extension(
    LinphoneChatMessage *message,
    const char *mime_type,
    char *buffer,
    size_t buffer_size
) {
    char file_name[256];
    const char *text = yoyopod_chat_message_text(message);
    const char *dot;

    if (buffer_size == 0) {
        return;
    }
    buffer[0] = '\0';
    if (
        yoyopod_extract_xml_tag_value(
            text,
            "<file-name>",
            "</file-name>",
            file_name,
            sizeof(file_name)
        )
    ) {
        dot = strrchr(file_name, '.');
        if (dot != NULL && dot[1] != '\0') {
            yoyopod_copy_string(buffer, buffer_size, dot + 1);
            return;
        }
    }
    if (mime_type != NULL && strstr(mime_type, "/") != NULL) {
        const char *slash = strchr(mime_type, '/');
        if (slash != NULL && slash[1] != '\0') {
            yoyopod_copy_string(buffer, buffer_size, slash + 1);
            return;
        }
    }
    yoyopod_copy_string(buffer, buffer_size, "wav");
}

static int yoyopod_is_voice_note_message(LinphoneChatMessage *message) {
    LinphoneContent *content;
    const char *text;

    if (message == NULL) {
        return 0;
    }
    content = linphone_chat_message_get_file_transfer_information(message);
    if (yoyopod_is_voice_note_content(content)) {
        return 1;
    }
    if (!yoyopod_is_file_transfer_xml_content(content)) {
        return 0;
    }
    text = yoyopod_chat_message_text(message);
    return yoyopod_is_voice_note_xml_text(text);
}

static int yoyopod_message_kind_from_message(LinphoneChatMessage *message) {
    return yoyopod_is_voice_note_message(message) ? YOYOPOD_MESSAGE_KIND_VOICE_NOTE : YOYOPOD_MESSAGE_KIND_TEXT;
}

static int yoyopod_message_direction_from_message(const LinphoneChatMessage *message) {
    return linphone_chat_message_is_outgoing(message)
               ? YOYOPOD_MESSAGE_DIRECTION_OUTGOING
               : YOYOPOD_MESSAGE_DIRECTION_INCOMING;
}

static void yoyopod_enqueue_event(const yoyopod_liblinphone_event_t *event_value) {
    size_t next_tail;
    pthread_mutex_lock(&g_state.queue_lock);
    next_tail = (g_state.queue_tail + 1U) % YOYOPOD_EVENT_QUEUE_CAPACITY;
    if (next_tail == g_state.queue_head) {
        g_state.queue_head = (g_state.queue_head + 1U) % YOYOPOD_EVENT_QUEUE_CAPACITY;
    }
    g_state.queue[g_state.queue_tail] = *event_value;
    g_state.queue_tail = next_tail;
    pthread_mutex_unlock(&g_state.queue_lock);
}

static void yoyopod_queue_registration_event(LinphoneRegistrationState state, const char *reason) {
    yoyopod_liblinphone_event_t event_value;
    memset(&event_value, 0, sizeof(event_value));
    event_value.type = YOYOPOD_EVENT_REGISTRATION;
    event_value.registration_state = yoyopod_map_registration_state(state);
    yoyopod_copy_string(event_value.reason, sizeof(event_value.reason), reason);
    yoyopod_enqueue_event(&event_value);
}

static void yoyopod_queue_call_state_event(LinphoneCall *call, LinphoneCallState state, const char *reason) {
    yoyopod_liblinphone_event_t event_value;
    memset(&event_value, 0, sizeof(event_value));
    event_value.type = YOYOPOD_EVENT_CALL_STATE;
    event_value.call_state = yoyopod_map_call_state(state);
    if (call != NULL) {
        yoyopod_build_address_uri(
            linphone_call_get_remote_address(call),
            event_value.peer_sip_address,
            sizeof(event_value.peer_sip_address)
        );
    }
    yoyopod_copy_string(event_value.reason, sizeof(event_value.reason), reason);
    yoyopod_enqueue_event(&event_value);
}

static void yoyopod_queue_incoming_call_event(LinphoneCall *call) {
    yoyopod_liblinphone_event_t event_value;
    memset(&event_value, 0, sizeof(event_value));
    event_value.type = YOYOPOD_EVENT_INCOMING_CALL;
    if (call != NULL) {
        yoyopod_build_address_uri(
            linphone_call_get_remote_address(call),
            event_value.peer_sip_address,
            sizeof(event_value.peer_sip_address)
        );
    }
    yoyopod_enqueue_event(&event_value);
}

static void yoyopod_fill_message_event_common(
    yoyopod_liblinphone_event_t *event_value,
    LinphoneChatMessage *message
) {
    LinphoneContent *content;
    char voice_note_mime[128];

    content = linphone_chat_message_get_file_transfer_information(message);
    event_value->message_kind = yoyopod_message_kind_from_message(message);
    event_value->message_direction = yoyopod_message_direction_from_message(message);
    event_value->message_delivery_state = yoyopod_map_message_delivery_state(
        linphone_chat_message_get_state(message)
    );
    yoyopod_build_message_id(message, event_value->message_id, sizeof(event_value->message_id));
    yoyopod_build_address_uri(
        linphone_chat_message_get_peer_address(message),
        event_value->peer_sip_address,
        sizeof(event_value->peer_sip_address)
    );
    yoyopod_build_address_uri(
        linphone_chat_message_get_from_address(message),
        event_value->sender_sip_address,
        sizeof(event_value->sender_sip_address)
    );
    yoyopod_build_address_uri(
        linphone_chat_message_get_to_address(message),
        event_value->recipient_sip_address,
        sizeof(event_value->recipient_sip_address)
    );
    yoyopod_copy_string(
        event_value->text,
        sizeof(event_value->text),
        yoyopod_chat_message_text(message)
    );
    voice_note_mime[0] = '\0';
    if (event_value->message_kind == YOYOPOD_MESSAGE_KIND_VOICE_NOTE) {
        yoyopod_extract_voice_note_payload_mime(
            message,
            content,
            voice_note_mime,
            sizeof(voice_note_mime)
        );
        yoyopod_copy_string(
            event_value->mime_type,
            sizeof(event_value->mime_type),
            voice_note_mime[0] != '\0' ? voice_note_mime : "audio/wav"
        );
        event_value->duration_ms = yoyopod_extract_voice_note_duration_ms(message);
        if (yoyopod_is_file_transfer_xml_content(content)) {
            event_value->text[0] = '\0';
        }
    } else {
        yoyopod_build_mime_type(content, event_value->mime_type, sizeof(event_value->mime_type));
    }
    if (content != NULL) {
        yoyopod_copy_string(
            event_value->local_file_path,
            sizeof(event_value->local_file_path),
            linphone_content_get_file_path(content)
        );
    }
}

static void yoyopod_attach_message_callbacks(LinphoneChatMessage *message) {
    if (message == NULL || g_state.message_cbs == NULL) {
        return;
    }
    linphone_chat_message_add_callbacks(message, g_state.message_cbs);
}

static void yoyopod_generate_voice_note_path(
    const char *message_id,
    const char *extension,
    char *buffer,
    size_t buffer_size
) {
    const char *selected_extension = extension;
    if (selected_extension == NULL || selected_extension[0] == '\0') {
        selected_extension = "wav";
    }
    snprintf(
        buffer,
        buffer_size,
        "%s/%s.%s",
        g_state.voice_note_store_dir,
        message_id,
        selected_extension
    );
}

static size_t yoyopod_list_size(const bctbx_list_t *list) {
    size_t count = 0U;
    const bctbx_list_t *item = list;
    while (item != NULL) {
        count += 1U;
        item = item->next;
    }
    return count;
}

static const char *yoyopod_chat_message_text(const LinphoneChatMessage *message) {
#if YOYOPOD_HAS_LINPHONE_ACCOUNT_API
    return linphone_chat_message_get_utf8_text(message);
#else
    return linphone_chat_message_get_text(message);
#endif
}

static int yoyopod_chat_room_is_read_only_compat(const LinphoneChatRoom *chat_room) {
#if YOYOPOD_HAS_LINPHONE_ACCOUNT_API
    return chat_room != NULL && linphone_chat_room_is_read_only(chat_room) ? 1 : 0;
#else
    (void)chat_room;
    return 0;
#endif
}

static int yoyopod_chat_room_params_ephemeral_mode_compat(const LinphoneChatRoomParams *params) {
#if YOYOPOD_HAS_LINPHONE_ACCOUNT_API
    return params != NULL ? (int)linphone_chat_room_params_get_ephemeral_mode(params) : 0;
#else
    (void)params;
    return 0;
#endif
}

static long yoyopod_chat_room_params_ephemeral_lifetime_compat(const LinphoneChatRoomParams *params) {
#if YOYOPOD_HAS_LINPHONE_ACCOUNT_API
    return params != NULL ? linphone_chat_room_params_get_ephemeral_lifetime(params) : 0L;
#else
    (void)params;
    return 0L;
#endif
}

static const LinphoneAddress *yoyopod_event_to_address(const LinphoneEvent *linphone_event) {
#if YOYOPOD_HAS_LINPHONE_ACCOUNT_API
    return linphone_event_get_to(linphone_event);
#else
    (void)linphone_event;
    return NULL;
#endif
}

static LinphoneChatMessage *yoyopod_chat_room_create_text_message(
    LinphoneChatRoom *chat_room,
    const char *text
) {
#if YOYOPOD_HAS_LINPHONE_ACCOUNT_API
    return linphone_chat_room_create_message_from_utf8(chat_room, text);
#else
    return linphone_chat_room_create_message(chat_room, text);
#endif
}

static const LinphoneAddress *yoyopod_account_identity_address(void) {
    if (g_state.account == NULL) {
        return NULL;
    }
#if YOYOPOD_HAS_LINPHONE_ACCOUNT_API
    {
        const LinphoneAccountParams *params = linphone_account_get_params(g_state.account);
        return params != NULL ? linphone_account_params_get_identity_address(params) : NULL;
    }
#else
    return linphone_proxy_config_get_identity_address(g_state.account);
#endif
}

static const char *yoyopod_account_file_transfer_server(void) {
    if (g_state.account == NULL) {
        return yoyopod_safe_string(g_state.configured_file_transfer_server_url);
    }
#if YOYOPOD_HAS_LINPHONE_ACCOUNT_API
    {
        const LinphoneAccountParams *params = linphone_account_get_params(g_state.account);
        return params != NULL
               ? yoyopod_safe_string(linphone_account_params_get_file_transfer_server(params))
               : yoyopod_safe_string(g_state.configured_file_transfer_server_url);
    }
#else
    return yoyopod_safe_string(g_state.configured_file_transfer_server_url);
#endif
}

static const char *yoyopod_account_lime_server_url(void) {
#if YOYOPOD_HAS_LINPHONE_ACCOUNT_API
    if (g_state.account != NULL) {
        const LinphoneAccountParams *params = linphone_account_get_params(g_state.account);
        if (params != NULL) {
            return yoyopod_safe_string(linphone_account_params_get_lime_server_url(params));
        }
    }
#endif
    return yoyopod_safe_string(g_state.configured_lime_server_url);
}

static int yoyopod_account_cpim_enabled(void) {
#if YOYOPOD_HAS_LINPHONE_ACCOUNT_API
    if (g_state.account != NULL) {
        const LinphoneAccountParams *params = linphone_account_get_params(g_state.account);
        return params != NULL && linphone_account_params_cpim_in_basic_chat_room_enabled(params)
               ? 1
               : 0;
    }
#endif
    return 0;
}

static size_t yoyopod_account_room_count(void) {
#if YOYOPOD_HAS_LINPHONE_ACCOUNT_API
    if (g_state.account != NULL) {
        bctbx_list_t *rooms = linphone_account_get_chat_rooms(g_state.account);
        size_t count = yoyopod_list_size(rooms);
        if (rooms != NULL) {
            bctbx_list_free(rooms);
        }
        return count;
    }
#endif
    return 0U;
}

static int yoyopod_account_unread_count(void) {
#if YOYOPOD_HAS_LINPHONE_ACCOUNT_API
    if (g_state.account != NULL) {
        return linphone_account_get_unread_chat_message_count(g_state.account);
    }
#endif
    return 0;
}

static void yoyopod_build_account_conference_factory_uri(char *buffer, size_t buffer_size) {
    if (buffer_size == 0) {
        return;
    }
    buffer[0] = '\0';
    if (g_state.account == NULL) {
        yoyopod_copy_string(buffer, buffer_size, g_state.configured_conference_factory_uri);
        return;
    }
#if YOYOPOD_HAS_LINPHONE_ACCOUNT_API
    {
        const LinphoneAccountParams *params = linphone_account_get_params(g_state.account);
        const LinphoneAddress *conference_factory_address = NULL;
        if (params != NULL) {
            conference_factory_address = linphone_account_params_get_conference_factory_address(params);
        }
        yoyopod_build_address_uri(conference_factory_address, buffer, buffer_size);
    }
#else
    yoyopod_copy_string(
        buffer,
        buffer_size,
        linphone_proxy_config_get_conference_factory_uri(g_state.account)
    );
#endif
}

static void yoyopod_log_room_snapshot(LinphoneChatRoom *chat_room, const char *phase) {
    const LinphoneChatRoomParams *room_params = NULL;
    char peer[256];
    peer[0] = '\0';
    yoyopod_build_chat_room_peer(chat_room, peer, sizeof(peer));
    if (chat_room != NULL) {
        room_params = linphone_chat_room_get_current_params(chat_room);
    }
    yoyopod_debug_log(
        "diag[%s] room peer=%s state=%d caps=%d backend=%d encryption_backend=%d group=%d encrypted=%d read_only=%d participants=%d",
        phase,
        peer,
        chat_room != NULL ? (int)linphone_chat_room_get_state(chat_room) : -1,
        chat_room != NULL ? (int)linphone_chat_room_get_capabilities(chat_room) : -1,
        room_params != NULL ? (int)linphone_chat_room_params_get_backend(room_params) : -1,
        room_params != NULL ? (int)linphone_chat_room_params_get_encryption_backend(room_params) : -1,
        room_params != NULL && linphone_chat_room_params_group_enabled(room_params) ? 1 : 0,
        room_params != NULL && linphone_chat_room_params_encryption_enabled(room_params) ? 1 : 0,
        yoyopod_chat_room_is_read_only_compat(chat_room),
        chat_room != NULL ? linphone_chat_room_get_nb_participants(chat_room) : -1
    );
}

static void yoyopod_log_account_diagnostics(const char *phase) {
    const bctbx_list_t *core_rooms;
    LinphoneChatRoomParams *default_params;
    const char *file_transfer_server = "";
    const char *lime_server = "";
    char core_specs[256];
    char conference_factory_uri[256];
    size_t core_room_count;
    size_t account_room_count;
    const bctbx_list_t *item;

    if (g_state.core == NULL || g_state.account == NULL) {
        return;
    }

    core_rooms = linphone_core_get_chat_rooms(g_state.core);
    core_room_count = yoyopod_list_size(core_rooms);
    account_room_count = yoyopod_account_room_count();
    yoyopod_build_account_conference_factory_uri(
        conference_factory_uri,
        sizeof(conference_factory_uri)
    );
    file_transfer_server = yoyopod_account_file_transfer_server();
    lime_server = yoyopod_account_lime_server_url();

    yoyopod_debug_log(
        "diag[%s] account unread=%d core_rooms=%llu account_rooms=%llu cpim_basic=%d conference_factory=%s file_transfer=%s lime=%s",
        phase,
        yoyopod_account_unread_count(),
        (unsigned long long)core_room_count,
        (unsigned long long)account_room_count,
        yoyopod_account_cpim_enabled(),
        conference_factory_uri,
        file_transfer_server,
        lime_server
    );
    yoyopod_build_specs_string(core_specs, sizeof(core_specs));
    yoyopod_debug_log("diag[%s] core_specs=%s", phase, core_specs);

    default_params = linphone_core_create_default_chat_room_params(g_state.core);
    if (default_params != NULL) {
        yoyopod_debug_log(
            "diag[%s] default_chat_room backend=%d encryption_backend=%d group=%d encrypted=%d rtt=%d ephemeral_mode=%d ephemeral_lifetime=%ld",
            phase,
            (int)linphone_chat_room_params_get_backend(default_params),
            (int)linphone_chat_room_params_get_encryption_backend(default_params),
            linphone_chat_room_params_group_enabled(default_params) ? 1 : 0,
            linphone_chat_room_params_encryption_enabled(default_params) ? 1 : 0,
            linphone_chat_room_params_rtt_enabled(default_params) ? 1 : 0,
            yoyopod_chat_room_params_ephemeral_mode_compat(default_params),
            yoyopod_chat_room_params_ephemeral_lifetime_compat(default_params)
        );
        linphone_chat_room_params_unref(default_params);
    }

    item = core_rooms;
    while (item != NULL) {
        LinphoneChatRoom *chat_room = (LinphoneChatRoom *)bctbx_list_get_data(item);
        yoyopod_log_room_snapshot(chat_room, phase);
        item = item->next;
    }
}

static void yoyopod_build_specs_string(char *buffer, size_t buffer_size) {
    bctbx_list_t *specs;
    bctbx_list_t *item;
    size_t used = 0;

    if (buffer_size == 0) {
        return;
    }
    buffer[0] = '\0';
    if (g_state.core == NULL) {
        return;
    }

    specs = linphone_core_get_linphone_specs_list(g_state.core);
    item = specs;
    while (item != NULL) {
        const char *spec = (const char *)bctbx_list_get_data(item);
        int written;
        if (spec == NULL) {
            item = item->next;
            continue;
        }
        written = snprintf(
            buffer + used,
            buffer_size - used,
            "%s%s",
            used == 0 ? "" : ",",
            spec
        );
        if (written < 0 || (size_t)written >= (buffer_size - used)) {
            break;
        }
        used += (size_t)written;
        item = item->next;
    }
    if (specs != NULL) {
        bctbx_list_free(specs);
    }
}

static void yoyopod_ensure_core_spec(const char *spec) {
    bctbx_list_t *specs;
    bctbx_list_t *item;

    if (g_state.core == NULL || spec == NULL || spec[0] == '\0') {
        return;
    }

    specs = linphone_core_get_linphone_specs_list(g_state.core);
    item = specs;
    while (item != NULL) {
        const char *current = (const char *)bctbx_list_get_data(item);
        if (current != NULL && strcmp(current, spec) == 0) {
            if (specs != NULL) {
                bctbx_list_free(specs);
            }
            return;
        }
        item = item->next;
    }
    if (specs != NULL) {
        bctbx_list_free(specs);
    }
    linphone_core_add_linphone_spec(g_state.core, spec);
}

static void yoyopod_prepare_auto_download(LinphoneChatMessage *message) {
    LinphoneContent *content;
    char message_id[128];
    char mime_type[128];
    char extension[32];
    char target_path[512];

    if (!g_state.auto_download_incoming_voice_recordings || message == NULL) {
        return;
    }

    content = linphone_chat_message_get_file_transfer_information(message);
    if (!yoyopod_is_voice_note_message(message) || content == NULL) {
        return;
    }

    yoyopod_build_message_id(message, message_id, sizeof(message_id));
    yoyopod_extract_voice_note_payload_mime(message, content, mime_type, sizeof(mime_type));
    yoyopod_extract_voice_note_extension(message, mime_type, extension, sizeof(extension));
    yoyopod_generate_voice_note_path(message_id, extension, target_path, sizeof(target_path));
    yoyopod_ensure_directory(g_state.voice_note_store_dir);
    linphone_content_set_file_path(content, target_path);
    yoyopod_debug_log(
        "auto-download voice note message_id=%s mime_type=%s target=%s",
        message_id,
        mime_type,
        target_path
    );
    linphone_chat_message_download_content(message, content);
}

static void yoyopod_build_chat_room_peer(
    LinphoneChatRoom *chat_room,
    char *buffer,
    size_t buffer_size
) {
    if (buffer_size == 0) {
        return;
    }
    buffer[0] = '\0';
    if (chat_room == NULL) {
        return;
    }
    yoyopod_build_address_uri(linphone_chat_room_get_peer_address(chat_room), buffer, buffer_size);
}

static int yoyopod_chat_room_already_attached(LinphoneChatRoom *chat_room) {
    size_t index;
    if (chat_room == NULL) {
        return 1;
    }
    for (index = 0; index < g_state.attached_chat_room_count; ++index) {
        if (g_state.attached_chat_rooms[index] == chat_room) {
            return 1;
        }
    }
    return 0;
}

static int yoyopod_apply_transports(LinphoneCore *core, const char *transport) {
    LinphoneTransports *transports = NULL;
    const char *selected = transport;
    LinphoneStatus status;

    if (core == NULL) {
        yoyopod_set_error("Cannot configure Liblinphone transports without a core");
        return -1;
    }

    if (selected == NULL || selected[0] == '\0' || strcmp(selected, "auto") == 0) {
        selected = "tcp";
    }

    transports = linphone_core_get_transports(core);
    if (transports == NULL) {
        yoyopod_set_error("Failed to allocate Linphone transports");
        return -1;
    }

    linphone_transports_set_udp_port(transports, 0);
    linphone_transports_set_tcp_port(transports, 0);
    linphone_transports_set_tls_port(transports, 0);
    linphone_transports_set_dtls_port(transports, 0);

    if (strcmp(selected, "udp") == 0) {
        linphone_transports_set_udp_port(transports, LC_SIP_TRANSPORT_RANDOM);
    } else if (strcmp(selected, "tls") == 0) {
        linphone_transports_set_tls_port(transports, LC_SIP_TRANSPORT_RANDOM);
    } else if (strcmp(selected, "dtls") == 0) {
        linphone_transports_set_dtls_port(transports, LC_SIP_TRANSPORT_RANDOM);
    } else {
        linphone_transports_set_tcp_port(transports, LC_SIP_TRANSPORT_RANDOM);
    }

    status = linphone_core_set_transports(core, transports);
    linphone_transports_unref(transports);
    if (status != 0) {
        yoyopod_set_error("Failed to configure Liblinphone transports for %s", selected);
        return -1;
    }
    return 0;
}

static int yoyopod_configure_media_policy(LinphoneCore *core, LinphoneFactory *factory) {
    LinphoneVideoActivationPolicy *policy = NULL;

    if (core == NULL || factory == NULL) {
        yoyopod_set_error("Cannot configure Liblinphone media policy without a core and factory");
        return -1;
    }

    linphone_core_enable_video_capture(core, FALSE);
    linphone_core_enable_video_display(core, FALSE);

    policy = linphone_factory_create_video_activation_policy(factory);
    if (policy == NULL) {
        yoyopod_set_error("Failed to create Liblinphone video activation policy");
        return -1;
    }

    linphone_video_activation_policy_set_automatically_accept(policy, FALSE);
    linphone_video_activation_policy_set_automatically_initiate(policy, FALSE);
    linphone_core_set_video_activation_policy(core, policy);
    linphone_video_activation_policy_unref(policy);
    return 0;
}

static int yoyopod_configure_network_media_defaults(LinphoneCore *core, const char *stun_server) {
    LinphoneNatPolicy *nat_policy = NULL;

    if (core == NULL) {
        yoyopod_set_error("Cannot configure Liblinphone network defaults without a core");
        return -1;
    }

    linphone_core_set_media_encryption(core, LinphoneMediaEncryptionSRTP);
    linphone_core_set_media_encryption_mandatory(core, FALSE);
    linphone_core_set_audio_port_range(core, 7076, 7100);
    linphone_core_set_video_port_range(core, 9076, 9100);

    nat_policy = linphone_core_create_nat_policy(core);
    if (nat_policy == NULL) {
        yoyopod_set_error("Failed to create Liblinphone NAT policy");
        return -1;
    }

    linphone_nat_policy_enable_stun(nat_policy, TRUE);
    linphone_nat_policy_enable_ice(nat_policy, TRUE);
    if (stun_server != NULL && stun_server[0] != '\0') {
        linphone_nat_policy_set_stun_server(nat_policy, stun_server);
    }
    linphone_core_set_nat_policy(core, nat_policy);
    linphone_nat_policy_unref(nat_policy);
    return 0;
}

static void yoyopod_queue_message_received_event(LinphoneChatMessage *message) {
    yoyopod_liblinphone_event_t event_value;
    memset(&event_value, 0, sizeof(event_value));
    event_value.type = YOYOPOD_EVENT_MESSAGE_RECEIVED;
    event_value.unread = linphone_chat_message_is_read(message) ? 0 : 1;
    yoyopod_fill_message_event_common(&event_value, message);
    yoyopod_enqueue_event(&event_value);
}

static void yoyopod_queue_message_delivery_event(
    LinphoneChatMessage *message,
    LinphoneChatMessageState state
) {
    yoyopod_liblinphone_event_t event_value;
    memset(&event_value, 0, sizeof(event_value));
    event_value.type = YOYOPOD_EVENT_MESSAGE_DELIVERY_CHANGED;
    yoyopod_fill_message_event_common(&event_value, message);
    event_value.message_delivery_state = yoyopod_map_message_delivery_state(state);
    if (state == LinphoneChatMessageStateNotDelivered || state == LinphoneChatMessageStateFileTransferError) {
        const char *state_text = linphone_chat_message_state_to_string(state);
        yoyopod_copy_string(event_value.reason, sizeof(event_value.reason), state_text);
    }
    yoyopod_enqueue_event(&event_value);
}

static void yoyopod_queue_download_completed_event(LinphoneChatMessage *message) {
    LinphoneContent *content;
    yoyopod_liblinphone_event_t event_value;
    memset(&event_value, 0, sizeof(event_value));
    content = linphone_chat_message_get_file_transfer_information(message);
    if (content == NULL) {
        return;
    }
    event_value.type = YOYOPOD_EVENT_MESSAGE_DOWNLOAD_COMPLETED;
    yoyopod_fill_message_event_common(&event_value, message);
    yoyopod_copy_string(
        event_value.local_file_path,
        sizeof(event_value.local_file_path),
        linphone_content_get_file_path(content)
    );
    yoyopod_enqueue_event(&event_value);
}

#if YOYOPOD_HAS_LINPHONE_ACCOUNT_API
static void yoyopod_on_registration_state_changed(
    LinphoneAccount *account,
    LinphoneRegistrationState state,
    const char *message
) {
    (void)account;
#else
static void yoyopod_on_registration_state_changed(
    LinphoneCore *core,
    LinphoneProxyConfig *proxy_config,
    LinphoneRegistrationState state,
    const char *message
) {
    (void)core;
    (void)proxy_config;
#endif
    yoyopod_queue_registration_event(state, message);
    if (state == LinphoneRegistrationOk) {
        yoyopod_log_account_diagnostics("registration_ok");
    }
}

static void yoyopod_on_call_state_changed(
    LinphoneCore *core,
    LinphoneCall *call,
    LinphoneCallState state,
    const char *message
) {
    (void)core;
    g_state.current_call = call;
    yoyopod_queue_call_state_event(call, state, message);
    if (state == LinphoneCallIncomingReceived) {
        yoyopod_queue_incoming_call_event(call);
    }
    if (state == LinphoneCallReleased || state == LinphoneCallEnd || state == LinphoneCallError) {
        g_state.current_call = NULL;
    }
}

static void yoyopod_on_message_received(
    LinphoneCore *core,
    LinphoneChatRoom *chat_room,
    LinphoneChatMessage *message
) {
    char peer[256];
    (void)core;
    (void)chat_room;
    peer[0] = '\0';
    if (message != NULL) {
        yoyopod_build_address_uri(
            linphone_chat_message_get_peer_address(message),
            peer,
            sizeof(peer)
        );
    }
    yoyopod_debug_log(
        "message_received peer=%s kind=%d delivery=%d",
        peer,
        yoyopod_message_kind_from_message(message),
        yoyopod_map_message_delivery_state(linphone_chat_message_get_state(message))
    );
    yoyopod_attach_message_callbacks(message);
    yoyopod_queue_message_received_event(message);
    yoyopod_prepare_auto_download(message);
}

static void yoyopod_on_chat_room_message_received(
    LinphoneChatRoom *chat_room,
    LinphoneChatMessage *message
) {
    char peer[256];
    peer[0] = '\0';
    yoyopod_build_chat_room_peer(chat_room, peer, sizeof(peer));
    yoyopod_debug_log(
        "chat_room.message_received peer=%s kind=%d delivery=%d",
        peer,
        yoyopod_message_kind_from_message(message),
        yoyopod_map_message_delivery_state(linphone_chat_message_get_state(message))
    );
    yoyopod_attach_message_callbacks(message);
    yoyopod_queue_message_received_event(message);
    yoyopod_prepare_auto_download(message);
}

static void yoyopod_on_chat_room_messages_received(
    LinphoneChatRoom *chat_room,
    const bctbx_list_t *messages
) {
    const bctbx_list_t *item = messages;
    char peer[256];
    peer[0] = '\0';
    yoyopod_build_chat_room_peer(chat_room, peer, sizeof(peer));
    yoyopod_debug_log("chat_room.messages_received peer=%s", peer);
    while (item != NULL) {
        LinphoneChatMessage *message = (LinphoneChatMessage *)bctbx_list_get_data(item);
        if (message != NULL) {
            yoyopod_on_chat_room_message_received(chat_room, message);
        }
        item = item->next;
    }
}

static void yoyopod_on_chat_room_chat_message_received(
    LinphoneChatRoom *chat_room,
    const LinphoneEventLog *event_log
) {
    LinphoneChatMessage *message = linphone_event_log_get_chat_message(event_log);
    char peer[256];
    peer[0] = '\0';
    yoyopod_build_chat_room_peer(chat_room, peer, sizeof(peer));
    yoyopod_debug_log("chat_room.chat_message_received peer=%s", peer);
    if (message != NULL) {
        yoyopod_on_chat_room_message_received(chat_room, message);
    }
}

static void yoyopod_on_chat_room_undecryptable_message_received(
    LinphoneChatRoom *chat_room,
    LinphoneChatMessage *message
) {
    char peer[256];
    peer[0] = '\0';
    yoyopod_build_chat_room_peer(chat_room, peer, sizeof(peer));
    yoyopod_debug_log(
        "chat_room.undecryptable_message_received peer=%s kind=%d",
        peer,
        message != NULL ? yoyopod_message_kind_from_message(message) : 0
    );
}

static void yoyopod_attach_chat_room_callbacks(LinphoneChatRoom *chat_room) {
    char peer[256];
    if (chat_room == NULL || g_state.chat_room_cbs == NULL || yoyopod_chat_room_already_attached(chat_room)) {
        return;
    }
    if (g_state.attached_chat_room_count >= (sizeof(g_state.attached_chat_rooms) / sizeof(g_state.attached_chat_rooms[0]))) {
        yoyopod_debug_log("chat_room callback registry is full; skipping room attachment");
        return;
    }
    linphone_chat_room_add_callbacks(chat_room, g_state.chat_room_cbs);
    g_state.attached_chat_rooms[g_state.attached_chat_room_count++] = chat_room;
    peer[0] = '\0';
    yoyopod_build_chat_room_peer(chat_room, peer, sizeof(peer));
    yoyopod_debug_log(
        "attached chat_room callbacks peer=%s state=%d read_only=%d",
        peer,
        (int)linphone_chat_room_get_state(chat_room),
        yoyopod_chat_room_is_read_only_compat(chat_room)
    );
}

static void yoyopod_attach_all_chat_room_callbacks(void) {
    const bctbx_list_t *rooms;
    const bctbx_list_t *item;
    if (g_state.core == NULL) {
        return;
    }
    rooms = linphone_core_get_chat_rooms(g_state.core);
    item = rooms;
    while (item != NULL) {
        LinphoneChatRoom *chat_room = (LinphoneChatRoom *)bctbx_list_get_data(item);
        yoyopod_attach_chat_room_callbacks(chat_room);
        item = item->next;
    }
}

static LinphoneChatRoomParams *yoyopod_create_preferred_chat_room_params(void) {
    LinphoneChatRoomParams *params;
    const char *file_transfer_server = "";
    const char *lime_server = "";

    if (g_state.core == NULL) {
        return NULL;
    }

    params = linphone_core_create_default_chat_room_params(g_state.core);
    if (params == NULL) {
        return NULL;
    }

    linphone_chat_room_params_enable_group(params, FALSE);
    linphone_chat_room_params_enable_rtt(params, FALSE);

    file_transfer_server = yoyopod_account_file_transfer_server();
    lime_server = yoyopod_account_lime_server_url();

    if (file_transfer_server[0] != '\0' || lime_server[0] != '\0') {
        linphone_chat_room_params_set_backend(params, LinphoneChatRoomBackendFlexisipChat);
#if YOYOPOD_HAS_LINPHONE_ACCOUNT_API
        linphone_chat_room_params_set_subject(params, "YoyoPod");
#endif
    }
    if (lime_server[0] != '\0') {
        linphone_chat_room_params_set_encryption_backend(params, LinphoneChatRoomEncryptionBackendLime);
        linphone_chat_room_params_enable_encryption(params, TRUE);
    }

    return params;
}

static LinphoneChatRoomParams *yoyopod_create_direct_chat_room_params(void) {
    LinphoneChatRoomParams *params;

    if (g_state.core == NULL) {
        return NULL;
    }

    params = linphone_core_create_default_chat_room_params(g_state.core);
    if (params == NULL) {
        return NULL;
    }

    linphone_chat_room_params_set_backend(params, LinphoneChatRoomBackendBasic);
    linphone_chat_room_params_enable_group(params, FALSE);
    linphone_chat_room_params_enable_rtt(params, FALSE);
    linphone_chat_room_params_enable_encryption(params, FALSE);
    return params;
}

static int yoyopod_should_prefer_hosted_chat_rooms(void) {
    const char *file_transfer_server = "";
    const char *lime_server = yoyopod_account_lime_server_url();
    char conference_factory_uri[256];

    if (g_state.account == NULL) {
        return 0;
    }

    conference_factory_uri[0] = '\0';
    yoyopod_build_account_conference_factory_uri(
        conference_factory_uri,
        sizeof(conference_factory_uri)
    );
    file_transfer_server = yoyopod_account_file_transfer_server();

    return conference_factory_uri[0] != '\0'
           || file_transfer_server[0] != '\0'
           || lime_server[0] != '\0';
}

static void yoyopod_prune_stale_basic_chat_rooms(void) {
    const bctbx_list_t *rooms;
    const bctbx_list_t *item;
    int removed_any = 0;

    if (
        g_state.core == NULL ||
        !yoyopod_should_prefer_hosted_chat_rooms() ||
        g_state.auto_download_incoming_voice_recordings
    ) {
        return;
    }

    rooms = linphone_core_get_chat_rooms(g_state.core);
    item = rooms;
    while (item != NULL) {
        const bctbx_list_t *next = item->next;
        LinphoneChatRoom *chat_room = (LinphoneChatRoom *)bctbx_list_get_data(item);
        const LinphoneChatRoomParams *room_params = NULL;

        if (chat_room != NULL) {
            room_params = linphone_chat_room_get_current_params(chat_room);
            if (
                room_params != NULL &&
                linphone_chat_room_params_get_backend(room_params) == LinphoneChatRoomBackendBasic
            ) {
                char peer[256];
                peer[0] = '\0';
                yoyopod_build_chat_room_peer(chat_room, peer, sizeof(peer));
                yoyopod_debug_log("pruning stale basic chat room peer=%s", peer);
                linphone_core_delete_chat_room(g_state.core, chat_room);
                removed_any = 1;
            }
        }

        item = next;
    }

    if (removed_any) {
        g_state.attached_chat_room_count = 0U;
    }
}

static void yoyopod_on_messages_received(
    LinphoneCore *core,
    LinphoneChatRoom *chat_room,
    const bctbx_list_t *messages
) {
    const bctbx_list_t *item = messages;
    (void)core;
    (void)chat_room;
    yoyopod_debug_log("messages_received aggregated callback triggered");
    while (item != NULL) {
        LinphoneChatMessage *message = (LinphoneChatMessage *)bctbx_list_get_data(item);
        if (message != NULL) {
            yoyopod_on_message_received(core, chat_room, message);
        }
        item = item->next;
    }
}

static void yoyopod_on_message_received_unable_decrypt(
    LinphoneCore *core,
    LinphoneChatRoom *chat_room,
    LinphoneChatMessage *message
) {
    char peer[256];
    (void)core;
    (void)chat_room;
    peer[0] = '\0';
    if (message != NULL) {
        yoyopod_build_address_uri(
            linphone_chat_message_get_peer_address(message),
            peer,
            sizeof(peer)
        );
    }
    yoyopod_debug_log(
        "message_received_unable_decrypt peer=%s kind=%d",
        peer,
        message != NULL ? yoyopod_message_kind_from_message(message) : 0
    );
}

static void yoyopod_on_subscription_state_changed(
    LinphoneCore *core,
    LinphoneEvent *linphone_event,
    LinphoneSubscriptionState state
) {
    const LinphoneErrorInfo *error_info;
    char from[256];
    char to[256];
    char resource[256];

    (void)core;
    if (linphone_event == NULL) {
        return;
    }

    error_info = linphone_event_get_error_info(linphone_event);
    yoyopod_build_address_uri(linphone_event_get_from(linphone_event), from, sizeof(from));
    yoyopod_build_address_uri(yoyopod_event_to_address(linphone_event), to, sizeof(to));
    yoyopod_build_address_uri(linphone_event_get_resource(linphone_event), resource, sizeof(resource));
    yoyopod_debug_log(
        "subscription_state_changed name=%s state=%s reason=%s protocol_code=%d phrase=%s from=%s to=%s resource=%s",
        yoyopod_safe_string(linphone_event_get_name(linphone_event)),
        yoyopod_safe_string(linphone_subscription_state_to_string(state)),
        yoyopod_safe_string(linphone_reason_to_string(linphone_event_get_reason(linphone_event))),
        error_info != NULL ? linphone_error_info_get_protocol_code(error_info) : -1,
        error_info != NULL ? yoyopod_safe_string(linphone_error_info_get_phrase(error_info)) : "",
        from,
        to,
        resource
    );
}

static void yoyopod_on_message_state_changed(
    LinphoneChatMessage *message,
    LinphoneChatMessageState state
) {
    yoyopod_queue_message_delivery_event(message, state);
    if (state == LinphoneChatMessageStateFileTransferDone) {
        yoyopod_queue_download_completed_event(message);
    }
}

static int yoyopod_configure_account(
    const char *sip_server,
    const char *sip_username,
    const char *sip_password,
    const char *sip_password_ha1,
    const char *sip_identity,
    const char *transport,
    const char *conference_factory_uri,
    const char *file_transfer_server_url,
    const char *lime_server_url
) {
    LinphoneAddress *server_address = NULL;
    LinphoneAddress *identity_address = NULL;
#if YOYOPOD_HAS_LINPHONE_ACCOUNT_API
    LinphoneAddress *conference_factory_address = NULL;
    LinphoneAccountParams *params = NULL;
    LinphoneAccount *account = NULL;
#else
    LinphoneProxyConfig *account = NULL;
#endif
    LinphoneAuthInfo *auth_info = NULL;
    char server_uri[256];

    yoyopod_copy_string(
        g_state.configured_conference_factory_uri,
        sizeof(g_state.configured_conference_factory_uri),
        conference_factory_uri
    );
    yoyopod_copy_string(
        g_state.configured_file_transfer_server_url,
        sizeof(g_state.configured_file_transfer_server_url),
        file_transfer_server_url
    );
    yoyopod_copy_string(
        g_state.configured_lime_server_url,
        sizeof(g_state.configured_lime_server_url),
        lime_server_url
    );

    snprintf(
        server_uri,
        sizeof(server_uri),
        "sip:%s;transport=%s",
        yoyopod_safe_string(sip_server),
        transport != NULL && transport[0] != '\0' ? transport : "tcp"
    );

#if YOYOPOD_HAS_LINPHONE_ACCOUNT_API
    params = linphone_core_create_account_params(g_state.core);
    if (params == NULL) {
        yoyopod_set_error("Failed to create Linphone account params");
        return -1;
    }

    server_address = linphone_factory_create_address(g_state.factory, server_uri);
    identity_address = linphone_factory_create_address(g_state.factory, sip_identity);
    if (server_address == NULL || identity_address == NULL) {
        yoyopod_set_error("Failed to create Linphone account addresses");
        goto fail;
    }

    if (linphone_account_params_set_server_address(params, server_address) != 0) {
        yoyopod_set_error("Failed to set Linphone server address");
        goto fail;
    }
    if (linphone_account_params_set_identity_address(params, identity_address) != 0) {
        yoyopod_set_error("Failed to set Linphone identity address");
        goto fail;
    }
    linphone_account_params_enable_register(params, TRUE);
    linphone_account_params_enable_cpim_in_basic_chat_room(params, TRUE);
    if (conference_factory_uri != NULL && conference_factory_uri[0] != '\0') {
        conference_factory_address = linphone_factory_create_address(
            g_state.factory,
            conference_factory_uri
        );
        if (conference_factory_address == NULL) {
            yoyopod_set_error("Failed to create conference factory address");
            goto fail;
        }
        linphone_account_params_set_conference_factory_address(params, conference_factory_address);
        linphone_account_params_set_audio_video_conference_factory_address(
            params,
            conference_factory_address
        );
    }
    if (file_transfer_server_url != NULL && file_transfer_server_url[0] != '\0') {
        linphone_account_params_set_file_transfer_server(params, file_transfer_server_url);
        linphone_core_set_file_transfer_server(g_state.core, file_transfer_server_url);
    }
    if (lime_server_url != NULL && lime_server_url[0] != '\0') {
        linphone_core_enable_lime_x3dh(g_state.core, TRUE);
        linphone_account_params_set_lime_server_url(params, lime_server_url);
    } else {
        linphone_core_enable_lime_x3dh(g_state.core, FALSE);
    }

    account = linphone_core_create_account(g_state.core, params);
    if (account == NULL) {
        yoyopod_set_error("Failed to create Linphone account");
        goto fail;
    }

    g_state.account_cbs = linphone_account_cbs_new();
    if (g_state.account_cbs == NULL) {
        yoyopod_set_error("Failed to create Linphone account callbacks");
        goto fail;
    }
    linphone_account_cbs_set_registration_state_changed(
        g_state.account_cbs,
        yoyopod_on_registration_state_changed
    );
    linphone_account_add_callbacks(account, g_state.account_cbs);

    auth_info = linphone_factory_create_auth_info_2(
        g_state.factory,
        sip_username,
        sip_username,
        (sip_password != NULL && sip_password[0] != '\0') ? sip_password : NULL,
        (sip_password_ha1 != NULL && sip_password_ha1[0] != '\0') ? sip_password_ha1 : NULL,
        sip_server,
        sip_server,
        "SHA-256"
    );
    if (auth_info != NULL) {
        linphone_core_add_auth_info(g_state.core, auth_info);
        linphone_auth_info_unref(auth_info);
    }

    if (linphone_core_add_account(g_state.core, account) != 0) {
        yoyopod_set_error("Failed to add Linphone account to core");
        goto fail;
    }
    linphone_core_set_default_account(g_state.core, account);
    g_state.account = account;

    linphone_address_unref(server_address);
    linphone_address_unref(identity_address);
    if (conference_factory_address != NULL) {
        linphone_address_unref(conference_factory_address);
    }
    linphone_account_params_unref(params);
    return 0;

fail:
    if (account != NULL) {
        linphone_account_unref(account);
    }
    if (conference_factory_address != NULL) {
        linphone_address_unref(conference_factory_address);
    }
    if (identity_address != NULL) {
        linphone_address_unref(identity_address);
    }
    if (server_address != NULL) {
        linphone_address_unref(server_address);
    }
    if (params != NULL) {
        linphone_account_params_unref(params);
    }
    return -1;
#else
    account = linphone_core_create_proxy_config(g_state.core);
    if (account == NULL) {
        yoyopod_set_error("Failed to create Linphone proxy config");
        return -1;
    }

    identity_address = linphone_factory_create_address(g_state.factory, sip_identity);
    if (identity_address == NULL) {
        yoyopod_set_error("Failed to create Linphone identity address");
        goto fail;
    }

    if (linphone_proxy_config_set_server_addr(account, server_uri) != 0) {
        yoyopod_set_error("Failed to set Linphone proxy server address");
        goto fail;
    }
    if (linphone_proxy_config_set_identity_address(account, identity_address) != 0) {
        yoyopod_set_error("Failed to set Linphone proxy identity address");
        goto fail;
    }
    linphone_proxy_config_enable_register(account, TRUE);
    if (conference_factory_uri != NULL && conference_factory_uri[0] != '\0') {
        linphone_proxy_config_set_conference_factory_uri(account, conference_factory_uri);
    }
    if (file_transfer_server_url != NULL && file_transfer_server_url[0] != '\0') {
        linphone_core_set_file_transfer_server(g_state.core, file_transfer_server_url);
    }
    if (lime_server_url != NULL && lime_server_url[0] != '\0') {
        linphone_core_enable_lime_x3dh(g_state.core, TRUE);
    } else {
        linphone_core_enable_lime_x3dh(g_state.core, FALSE);
    }

    auth_info = linphone_factory_create_auth_info_2(
        g_state.factory,
        sip_username,
        sip_username,
        (sip_password != NULL && sip_password[0] != '\0') ? sip_password : NULL,
        (sip_password_ha1 != NULL && sip_password_ha1[0] != '\0') ? sip_password_ha1 : NULL,
        sip_server,
        sip_server,
        "SHA-256"
    );
    if (auth_info != NULL) {
        linphone_core_add_auth_info(g_state.core, auth_info);
        linphone_auth_info_unref(auth_info);
    }

    if (linphone_core_add_proxy_config(g_state.core, account) != 0) {
        yoyopod_set_error("Failed to add Linphone proxy config to core");
        goto fail;
    }
    linphone_core_set_default_proxy_config(g_state.core, account);
    g_state.account = account;

    linphone_address_unref(identity_address);
    return 0;

fail:
    if (identity_address != NULL) {
        linphone_address_unref(identity_address);
    }
    if (account != NULL) {
        linphone_proxy_config_unref(account);
    }
    return -1;
#endif
}

static void yoyopod_cleanup_recorder(void) {
#if YOYOPOD_HAS_LINPHONE_RECORDER_API
    if (g_state.current_recorder != NULL) {
        if (g_state.recorder_running) {
            linphone_recorder_pause(g_state.current_recorder);
        }
        linphone_recorder_close(g_state.current_recorder);
        linphone_recorder_unref(g_state.current_recorder);
        g_state.current_recorder = NULL;
    }
#else
    g_state.current_recorder = NULL;
#endif
    g_state.recorder_running = false;
    g_state.current_recording_path[0] = '\0';
}

int yoyopod_liblinphone_init(void) {
    if (g_state.initialized) {
        return 0;
    }
    memset(&g_state, 0, sizeof(g_state));
    if (pthread_mutex_init(&g_state.queue_lock, NULL) != 0) {
        yoyopod_set_error("Failed to initialize Liblinphone event queue mutex");
        return -1;
    }
    g_state.factory = linphone_factory_get();
    if (g_state.factory == NULL) {
        yoyopod_set_error("Failed to get Liblinphone factory");
        pthread_mutex_destroy(&g_state.queue_lock);
        return -1;
    }
    g_state.initialized = true;
    yoyopod_clear_error();
    return 0;
}

void yoyopod_liblinphone_shutdown(void) {
    yoyopod_liblinphone_stop();
    if (g_state.initialized) {
        pthread_mutex_destroy(&g_state.queue_lock);
        memset(&g_state, 0, sizeof(g_state));
    }
}

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
) {
    if (!g_state.initialized && yoyopod_liblinphone_init() != 0) {
        return -1;
    }

    if (g_state.started) {
        return 0;
    }

    if (sip_server == NULL || sip_server[0] == '\0' || sip_identity == NULL || sip_identity[0] == '\0') {
        yoyopod_set_error("Missing SIP identity or SIP server for Liblinphone startup");
        return -1;
    }

    linphone_logging_service_set_log_level_mask(
        linphone_logging_service_get(),
        LinphoneLogLevelDebug
            | LinphoneLogLevelTrace
            | LinphoneLogLevelMessage
            | LinphoneLogLevelWarning
            | LinphoneLogLevelError
            | LinphoneLogLevelFatal
    );

    g_state.core = linphone_factory_create_core_3(
        g_state.factory,
        NULL,
        (factory_config_path != NULL && factory_config_path[0] != '\0') ? factory_config_path : NULL,
        NULL
    );
    if (g_state.core == NULL) {
        yoyopod_set_error("Failed to create Liblinphone core");
        return -1;
    }

    g_state.core_cbs = linphone_factory_create_core_cbs(g_state.factory);
    if (g_state.core_cbs == NULL) {
        yoyopod_set_error("Failed to create Liblinphone core callbacks");
        yoyopod_liblinphone_stop();
        return -1;
    }

    g_state.message_cbs = linphone_chat_message_cbs_new();
    if (g_state.message_cbs == NULL) {
        yoyopod_set_error("Failed to create Liblinphone chat message callbacks");
        yoyopod_liblinphone_stop();
        return -1;
    }
    g_state.chat_room_cbs = linphone_factory_create_chat_room_cbs(g_state.factory);
    if (g_state.chat_room_cbs == NULL) {
        yoyopod_set_error("Failed to create Liblinphone chat room callbacks");
        yoyopod_liblinphone_stop();
        return -1;
    }

    g_state.auto_download_incoming_voice_recordings = auto_download_incoming_voice_recordings != 0;
    yoyopod_copy_string(g_state.voice_note_store_dir, sizeof(g_state.voice_note_store_dir), voice_note_store_dir);
    yoyopod_ensure_directory(g_state.voice_note_store_dir);

    linphone_chat_message_cbs_set_msg_state_changed(g_state.message_cbs, yoyopod_on_message_state_changed);
    linphone_chat_room_cbs_set_message_received(g_state.chat_room_cbs, yoyopod_on_chat_room_message_received);
#if YOYOPOD_HAS_LINPHONE_ACCOUNT_API
    linphone_chat_room_cbs_set_messages_received(g_state.chat_room_cbs, yoyopod_on_chat_room_messages_received);
#endif
    linphone_chat_room_cbs_set_chat_message_received(
        g_state.chat_room_cbs,
        yoyopod_on_chat_room_chat_message_received
    );
    linphone_chat_room_cbs_set_undecryptable_message_received(
        g_state.chat_room_cbs,
        yoyopod_on_chat_room_undecryptable_message_received
    );
    linphone_core_cbs_set_call_state_changed(g_state.core_cbs, yoyopod_on_call_state_changed);
#if !YOYOPOD_HAS_LINPHONE_ACCOUNT_API
    linphone_core_cbs_set_registration_state_changed(
        g_state.core_cbs,
        yoyopod_on_registration_state_changed
    );
#endif
    linphone_core_cbs_set_subscription_state_changed(
        g_state.core_cbs,
        yoyopod_on_subscription_state_changed
    );
#if YOYOPOD_HAS_LINPHONE_ACCOUNT_API
    linphone_core_cbs_set_messages_received(g_state.core_cbs, yoyopod_on_messages_received);
#endif
    linphone_core_cbs_set_message_received(g_state.core_cbs, yoyopod_on_message_received);
    linphone_core_cbs_set_message_received_unable_decrypt(
        g_state.core_cbs,
        yoyopod_on_message_received_unable_decrypt
    );
    linphone_core_add_callbacks(g_state.core, g_state.core_cbs);

    linphone_core_set_playback_device(g_state.core, playback_device_id);
    linphone_core_set_ringer_device(g_state.core, ringer_device_id);
    linphone_core_set_capture_device(g_state.core, capture_device_id);
    linphone_core_set_media_device(g_state.core, media_device_id);
    linphone_core_enable_chat(g_state.core);
    if (linphone_core_get_im_notif_policy(g_state.core) != NULL) {
        linphone_im_notif_policy_enable_all(linphone_core_get_im_notif_policy(g_state.core));
    }
    yoyopod_ensure_core_spec("conference/2.0");
    linphone_core_enable_echo_cancellation(g_state.core, echo_cancellation != 0);
#if YOYOPOD_HAS_LINPHONE_ACCOUNT_API
    linphone_core_set_chat_messages_aggregation_enabled(g_state.core, FALSE);
#endif
    linphone_core_set_mic_gain_db(g_state.core, ((float)mic_gain * 0.3f));
    linphone_core_set_playback_gain_db(g_state.core, ((float)output_volume * 0.12f) - 6.0f);
    if (yoyopod_configure_media_policy(g_state.core, g_state.factory) != 0) {
        yoyopod_liblinphone_stop();
        return -1;
    }
    if (yoyopod_configure_network_media_defaults(g_state.core, stun_server) != 0) {
        yoyopod_liblinphone_stop();
        return -1;
    }
    if (yoyopod_apply_transports(g_state.core, transport) != 0) {
        yoyopod_liblinphone_stop();
        return -1;
    }
    if (stun_server != NULL && stun_server[0] != '\0') {
        linphone_core_set_stun_server(g_state.core, stun_server);
    }
    if (file_transfer_server_url != NULL && file_transfer_server_url[0] != '\0') {
        linphone_core_set_file_transfer_server(g_state.core, file_transfer_server_url);
    }
#if YOYOPOD_HAS_LINPHONE_ACCOUNT_API
    linphone_core_enable_auto_download_voice_recordings(g_state.core, FALSE);
#endif

    if (
        yoyopod_configure_account(
            sip_server,
            sip_username,
            sip_password,
            sip_password_ha1,
            sip_identity,
            transport,
            conference_factory_uri,
            file_transfer_server_url,
            lime_server_url
        ) != 0
    ) {
        yoyopod_liblinphone_stop();
        return -1;
    }

    if (linphone_core_start(g_state.core) != 0) {
        yoyopod_set_error("Liblinphone core failed to start");
        yoyopod_liblinphone_stop();
        return -1;
    }
    yoyopod_prune_stale_basic_chat_rooms();
    yoyopod_attach_all_chat_room_callbacks();
    yoyopod_log_account_diagnostics("startup");

    g_state.started = true;
    yoyopod_clear_error();
    return 0;
}

void yoyopod_liblinphone_stop(void) {
    if (g_state.core != NULL) {
        linphone_core_stop(g_state.core);
    }

    yoyopod_cleanup_recorder();
    g_state.current_call = NULL;

#if YOYOPOD_HAS_LINPHONE_ACCOUNT_API
    if (g_state.account_cbs != NULL) {
        linphone_account_cbs_unref(g_state.account_cbs);
        g_state.account_cbs = NULL;
    }
#else
    g_state.account_cbs = NULL;
#endif
    if (g_state.message_cbs != NULL) {
        linphone_chat_message_cbs_unref(g_state.message_cbs);
        g_state.message_cbs = NULL;
    }
    if (g_state.chat_room_cbs != NULL) {
        linphone_chat_room_cbs_unref(g_state.chat_room_cbs);
        g_state.chat_room_cbs = NULL;
    }
    if (g_state.core_cbs != NULL) {
        linphone_core_cbs_unref(g_state.core_cbs);
        g_state.core_cbs = NULL;
    }
    if (g_state.account != NULL) {
#if YOYOPOD_HAS_LINPHONE_ACCOUNT_API
        linphone_account_unref(g_state.account);
#else
        if (g_state.core != NULL) {
            linphone_core_remove_proxy_config(g_state.core, g_state.account);
        } else {
            linphone_proxy_config_unref(g_state.account);
        }
#endif
        g_state.account = NULL;
    }
    if (g_state.core != NULL) {
        linphone_core_unref(g_state.core);
        g_state.core = NULL;
    }

    pthread_mutex_lock(&g_state.queue_lock);
    g_state.queue_head = 0;
    g_state.queue_tail = 0;
    pthread_mutex_unlock(&g_state.queue_lock);

    g_state.started = false;
}

void yoyopod_liblinphone_iterate(void) {
    if (g_state.started && g_state.core != NULL) {
        linphone_core_iterate(g_state.core);
        yoyopod_prune_stale_basic_chat_rooms();
        yoyopod_attach_all_chat_room_callbacks();
    }
}

int yoyopod_liblinphone_poll_event(yoyopod_liblinphone_event_t *event_out) {
    if (event_out == NULL || !g_state.initialized) {
        return 0;
    }

    pthread_mutex_lock(&g_state.queue_lock);
    if (g_state.queue_head == g_state.queue_tail) {
        pthread_mutex_unlock(&g_state.queue_lock);
        return 0;
    }

    *event_out = g_state.queue[g_state.queue_head];
    g_state.queue_head = (g_state.queue_head + 1U) % YOYOPOD_EVENT_QUEUE_CAPACITY;
    pthread_mutex_unlock(&g_state.queue_lock);
    return 1;
}

int yoyopod_liblinphone_make_call(const char *sip_address) {
    LinphoneAddress *address = NULL;
    LinphoneCallParams *params = NULL;
    LinphoneCall *call = NULL;

    if (!g_state.started || g_state.core == NULL || sip_address == NULL || sip_address[0] == '\0') {
        yoyopod_set_error("Liblinphone core is not ready to place a call");
        return -1;
    }

    address = linphone_factory_create_address(g_state.factory, sip_address);
    if (address == NULL) {
        yoyopod_set_error("Invalid SIP address for outgoing call");
        return -1;
    }

    params = linphone_core_create_call_params(g_state.core, NULL);
    if (params == NULL) {
        linphone_address_unref(address);
        yoyopod_set_error("Failed to create Liblinphone call params");
        return -1;
    }

    call = linphone_core_invite_address_with_params(g_state.core, address, params);
    linphone_call_params_unref(params);
    linphone_address_unref(address);

    if (call == NULL) {
        yoyopod_set_error("Liblinphone failed to initiate outgoing call");
        return -1;
    }

    g_state.current_call = call;
    return 0;
}

int yoyopod_liblinphone_answer_call(void) {
    if (!g_state.started || g_state.current_call == NULL) {
        yoyopod_set_error("No incoming call is available to answer");
        return -1;
    }
    return linphone_call_accept(g_state.current_call) == 0 ? 0 : -1;
}

int yoyopod_liblinphone_reject_call(void) {
    if (!g_state.started || g_state.current_call == NULL) {
        yoyopod_set_error("No incoming call is available to reject");
        return -1;
    }
    return linphone_call_decline(g_state.current_call, LinphoneReasonDeclined) == 0 ? 0 : -1;
}

int yoyopod_liblinphone_hangup(void) {
    if (!g_state.started || g_state.current_call == NULL) {
        yoyopod_set_error("No active call is available to hang up");
        return -1;
    }
    return linphone_call_terminate(g_state.current_call) == 0 ? 0 : -1;
}

int yoyopod_liblinphone_set_muted(int32_t muted) {
    if (!g_state.started || g_state.current_call == NULL) {
        yoyopod_set_error("No active call is available to mute");
        return -1;
    }
    linphone_call_set_microphone_muted(g_state.current_call, muted ? TRUE : FALSE);
    return 0;
}

static LinphoneChatRoom *yoyopod_get_chat_room_for_params(
    const char *sip_address,
    LinphoneChatRoomParams *params,
    const char *phase
) {
    LinphoneChatRoom *chat_room = NULL;
    LinphoneAddress *remote_address = NULL;
    const LinphoneAddress *local_address = NULL;

    if (!g_state.started || g_state.core == NULL) {
        if (params != NULL) {
            linphone_chat_room_params_unref(params);
        }
        return NULL;
    }

    remote_address = linphone_factory_create_address(g_state.factory, sip_address);
    local_address = yoyopod_account_identity_address();

    if (params != NULL && remote_address != NULL) {
#if YOYOPOD_HAS_LINPHONE_ACCOUNT_API
        bctbx_list_t *participants = NULL;
        chat_room = linphone_core_search_chat_room(
            g_state.core,
            params,
            local_address,
            remote_address,
            NULL
        );
        if (chat_room == NULL) {
            participants = bctbx_list_append(participants, remote_address);
            chat_room = linphone_core_create_chat_room_6(
                g_state.core,
                params,
                local_address,
                participants
            );
        }
        if (participants != NULL) {
            bctbx_list_free(participants);
        }
#else
        chat_room = linphone_core_find_chat_room(g_state.core, remote_address, local_address);
        if (chat_room == NULL && local_address != NULL) {
            chat_room = linphone_core_create_chat_room_4(
                g_state.core,
                params,
                local_address,
                remote_address
            );
        }
        if (chat_room == NULL && local_address != NULL) {
            chat_room = linphone_core_get_chat_room_2(
                g_state.core,
                remote_address,
                local_address
            );
        }
#endif
    }

    if (chat_room == NULL) {
        chat_room = linphone_core_get_chat_room_from_uri(g_state.core, sip_address);
    }

    yoyopod_attach_chat_room_callbacks(chat_room);
    if (chat_room != NULL) {
        yoyopod_log_room_snapshot(chat_room, phase != NULL ? phase : "lookup");
    }

    if (remote_address != NULL) {
        linphone_address_unref(remote_address);
    }
    if (params != NULL) {
        linphone_chat_room_params_unref(params);
    }
    return chat_room;
}

static LinphoneChatRoom *yoyopod_get_chat_room(const char *sip_address) {
    return yoyopod_get_chat_room_for_params(
        sip_address,
        yoyopod_create_preferred_chat_room_params(),
        "lookup"
    );
}

static LinphoneChatRoom *yoyopod_get_direct_chat_room(const char *sip_address) {
    return yoyopod_get_chat_room_for_params(
        sip_address,
        yoyopod_create_direct_chat_room_params(),
        "direct_lookup"
    );
}

static void yoyopod_fill_message_id_out(
    LinphoneChatMessage *message,
    char *message_id_out,
    uint32_t message_id_out_size
) {
    char message_id[128];
    yoyopod_build_message_id(message, message_id, sizeof(message_id));
    if (message_id_out != NULL && message_id_out_size > 0) {
        snprintf(message_id_out, message_id_out_size, "%s", message_id);
    }
}

int yoyopod_liblinphone_send_text_message(
    const char *sip_address,
    const char *text,
    char *message_id_out,
    uint32_t message_id_out_size
) {
    LinphoneChatRoom *chat_room;
    LinphoneChatMessage *message;

    if (!g_state.started || sip_address == NULL || sip_address[0] == '\0' || text == NULL) {
        yoyopod_set_error("Liblinphone text message send is missing peer or payload");
        return -1;
    }

    chat_room = yoyopod_get_direct_chat_room(sip_address);
    if (chat_room == NULL) {
        yoyopod_set_error("Liblinphone could not resolve a chat room for %s", sip_address);
        return -1;
    }

    message = yoyopod_chat_room_create_text_message(chat_room, text);
    if (message == NULL) {
        yoyopod_set_error("Liblinphone failed to create a text chat message");
        return -1;
    }

    yoyopod_attach_message_callbacks(message);
    yoyopod_fill_message_id_out(message, message_id_out, message_id_out_size);
    linphone_chat_message_send(message);
    return 0;
}

int yoyopod_liblinphone_start_voice_recording(const char *file_path) {
#if YOYOPOD_HAS_LINPHONE_RECORDER_API
    LinphoneRecorderParams *params;
    if (!g_state.started || g_state.core == NULL || file_path == NULL || file_path[0] == '\0') {
        yoyopod_set_error("Liblinphone voice-note recording requires an active core and target path");
        return -1;
    }

    yoyopod_cleanup_recorder();
    params = linphone_core_create_recorder_params(g_state.core);
    if (params == NULL) {
        yoyopod_set_error("Failed to create Liblinphone recorder params");
        return -1;
    }
    linphone_recorder_params_set_file_format(params, LinphoneRecorderFileFormatWav);

    g_state.current_recorder = linphone_core_create_recorder(g_state.core, params);
    linphone_recorder_params_unref(params);
    if (g_state.current_recorder == NULL) {
        yoyopod_set_error("Failed to create Liblinphone recorder");
        return -1;
    }

    yoyopod_copy_string(g_state.current_recording_path, sizeof(g_state.current_recording_path), file_path);
    yoyopod_ensure_directory(g_state.voice_note_store_dir);
    if (linphone_recorder_open(g_state.current_recorder, file_path) != 0) {
        yoyopod_set_error("Failed to open voice-note file for recording");
        yoyopod_cleanup_recorder();
        return -1;
    }
    if (linphone_recorder_start(g_state.current_recorder) != 0) {
        yoyopod_set_error("Failed to start voice-note recording");
        yoyopod_cleanup_recorder();
        return -1;
    }

    g_state.recorder_running = true;
    return 0;
#else
    (void)file_path;
    yoyopod_set_error("Installed Liblinphone build does not support recorder-based voice notes");
    return -1;
#endif
}

int yoyopod_liblinphone_stop_voice_recording(int32_t *duration_ms_out) {
#if YOYOPOD_HAS_LINPHONE_RECORDER_API
    int duration_ms;
    if (!g_state.started || g_state.current_recorder == NULL || !g_state.recorder_running) {
        yoyopod_set_error("No active Liblinphone voice-note recording is running");
        return -1;
    }

    linphone_recorder_pause(g_state.current_recorder);
    g_state.recorder_running = false;
    duration_ms = linphone_recorder_get_duration(g_state.current_recorder);
    linphone_recorder_close(g_state.current_recorder);
    if (duration_ms_out != NULL) {
        *duration_ms_out = duration_ms;
    }
    return 0;
#else
    (void)duration_ms_out;
    yoyopod_set_error("Installed Liblinphone build does not support recorder-based voice notes");
    return -1;
#endif
}

int yoyopod_liblinphone_cancel_voice_recording(void) {
    if (g_state.current_recording_path[0] != '\0') {
        unlink(g_state.current_recording_path);
    }
    yoyopod_cleanup_recorder();
    return 0;
}

int yoyopod_liblinphone_send_voice_note(
    const char *sip_address,
    const char *file_path,
    int32_t duration_ms,
    const char *mime_type,
    char *message_id_out,
    uint32_t message_id_out_size
) {
#if YOYOPOD_HAS_LINPHONE_RECORDER_API
    LinphoneChatRoom *chat_room;
    LinphoneChatMessage *message;

    (void)duration_ms;
    (void)mime_type;

    if (!g_state.started || g_state.current_recorder == NULL || sip_address == NULL || sip_address[0] == '\0') {
        yoyopod_set_error("Liblinphone voice-note send requires a closed recording and recipient");
        return -1;
    }
    if (g_state.recorder_running) {
        yoyopod_set_error("Voice-note recording must be stopped before sending");
        return -1;
    }
    if (file_path != NULL && file_path[0] != '\0' && strcmp(file_path, g_state.current_recording_path) != 0) {
        yoyopod_set_error("Voice-note send only supports the active recorder output in this build");
        return -1;
    }
    if (!yoyopod_path_exists(g_state.current_recording_path)) {
        yoyopod_set_error("Voice-note file does not exist at %s", g_state.current_recording_path);
        return -1;
    }

    chat_room = yoyopod_get_direct_chat_room(sip_address);
    if (chat_room == NULL) {
        yoyopod_set_error("Liblinphone could not resolve a chat room for %s", sip_address);
        return -1;
    }

    message = linphone_chat_room_create_voice_recording_message(chat_room, g_state.current_recorder);
    if (message == NULL) {
        yoyopod_set_error("Liblinphone failed to create a voice-note message");
        return -1;
    }

    yoyopod_attach_message_callbacks(message);
    yoyopod_fill_message_id_out(message, message_id_out, message_id_out_size);
    linphone_chat_message_send(message);
    return 0;
#else
    (void)sip_address;
    (void)file_path;
    (void)duration_ms;
    (void)mime_type;
    (void)message_id_out;
    (void)message_id_out_size;
    yoyopod_set_error("Installed Liblinphone build does not support recorder-based voice notes");
    return -1;
#endif
}

const char *yoyopod_liblinphone_last_error(void) {
    return g_last_error;
}

const char *yoyopod_liblinphone_version(void) {
    return linphone_core_get_version();
}
