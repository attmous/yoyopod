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

#include <linphone/api/c-account-cbs.h>
#include <linphone/api/c-account-params.h>
#include <linphone/api/c-account.h>
#include <linphone/api/c-address.h>
#include <linphone/api/c-auth-info.h>
#include <linphone/api/c-call.h>
#include <linphone/api/c-chat-message-cbs.h>
#include <linphone/api/c-chat-message.h>
#include <linphone/api/c-chat-room.h>
#include <linphone/api/c-content.h>
#include <linphone/api/c-factory.h>
#include <linphone/api/c-nat-policy.h>
#include <linphone/api/c-recorder.h>
#include <linphone/buffer.h>
#include <linphone/core.h>
#include <linphone/misc.h>

#define YOYOPY_EVENT_QUEUE_CAPACITY 128

enum {
    YOYOPY_EVENT_NONE = 0,
    YOYOPY_EVENT_REGISTRATION = 1,
    YOYOPY_EVENT_CALL_STATE = 2,
    YOYOPY_EVENT_INCOMING_CALL = 3,
    YOYOPY_EVENT_BACKEND_STOPPED = 4,
    YOYOPY_EVENT_MESSAGE_RECEIVED = 5,
    YOYOPY_EVENT_MESSAGE_DELIVERY_CHANGED = 6,
    YOYOPY_EVENT_MESSAGE_DOWNLOAD_COMPLETED = 7,
    YOYOPY_EVENT_MESSAGE_FAILED = 8
};

enum {
    YOYOPY_REGISTRATION_NONE = 0,
    YOYOPY_REGISTRATION_PROGRESS = 1,
    YOYOPY_REGISTRATION_OK = 2,
    YOYOPY_REGISTRATION_CLEARED = 3,
    YOYOPY_REGISTRATION_FAILED = 4
};

enum {
    YOYOPY_CALL_IDLE = 0,
    YOYOPY_CALL_INCOMING = 1,
    YOYOPY_CALL_OUTGOING_INIT = 2,
    YOYOPY_CALL_OUTGOING_PROGRESS = 3,
    YOYOPY_CALL_OUTGOING_RINGING = 4,
    YOYOPY_CALL_OUTGOING_EARLY_MEDIA = 5,
    YOYOPY_CALL_CONNECTED = 6,
    YOYOPY_CALL_STREAMS_RUNNING = 7,
    YOYOPY_CALL_PAUSED = 8,
    YOYOPY_CALL_PAUSED_BY_REMOTE = 9,
    YOYOPY_CALL_UPDATED_BY_REMOTE = 10,
    YOYOPY_CALL_RELEASED = 11,
    YOYOPY_CALL_ERROR = 12,
    YOYOPY_CALL_END = 13
};

enum {
    YOYOPY_MESSAGE_KIND_TEXT = 1,
    YOYOPY_MESSAGE_KIND_VOICE_NOTE = 2
};

enum {
    YOYOPY_MESSAGE_DIRECTION_INCOMING = 1,
    YOYOPY_MESSAGE_DIRECTION_OUTGOING = 2
};

enum {
    YOYOPY_MESSAGE_DELIVERY_QUEUED = 1,
    YOYOPY_MESSAGE_DELIVERY_SENDING = 2,
    YOYOPY_MESSAGE_DELIVERY_SENT = 3,
    YOYOPY_MESSAGE_DELIVERY_DELIVERED = 4,
    YOYOPY_MESSAGE_DELIVERY_FAILED = 5
};

typedef struct {
    bool initialized;
    bool started;
    LinphoneFactory *factory;
    LinphoneCore *core;
    LinphoneAccount *account;
    LinphoneAccountCbs *account_cbs;
    LinphoneCoreCbs *core_cbs;
    LinphoneChatMessageCbs *message_cbs;
    LinphoneCall *current_call;
    LinphoneRecorder *current_recorder;
    bool recorder_running;
    bool auto_download_incoming_voice_recordings;
    char voice_note_store_dir[512];
    char current_recording_path[512];
    pthread_mutex_t queue_lock;
    yoyopy_liblinphone_event_t queue[YOYOPY_EVENT_QUEUE_CAPACITY];
    size_t queue_head;
    size_t queue_tail;
    unsigned long long message_counter;
} yoyopy_liblinphone_state_t;

static yoyopy_liblinphone_state_t g_state = {0};
static pthread_mutex_t g_error_lock = PTHREAD_MUTEX_INITIALIZER;
static char g_last_error[512] = "";

static void yoyopy_set_error(const char *format, ...) {
    va_list args;
    pthread_mutex_lock(&g_error_lock);
    va_start(args, format);
    vsnprintf(g_last_error, sizeof(g_last_error), format, args);
    va_end(args);
    pthread_mutex_unlock(&g_error_lock);
}

static void yoyopy_clear_error(void) {
    pthread_mutex_lock(&g_error_lock);
    g_last_error[0] = '\0';
    pthread_mutex_unlock(&g_error_lock);
}

static void yoyopy_copy_string(char *destination, size_t destination_size, const char *source) {
    if (destination_size == 0) {
        return;
    }
    if (source == NULL) {
        destination[0] = '\0';
        return;
    }
    snprintf(destination, destination_size, "%s", source);
}

static const char *yoyopy_safe_string(const char *value) {
    return value != NULL ? value : "";
}

static int yoyopy_map_registration_state(LinphoneRegistrationState state) {
    switch (state) {
        case LinphoneRegistrationProgress:
            return YOYOPY_REGISTRATION_PROGRESS;
        case LinphoneRegistrationOk:
            return YOYOPY_REGISTRATION_OK;
        case LinphoneRegistrationCleared:
            return YOYOPY_REGISTRATION_CLEARED;
        case LinphoneRegistrationFailed:
            return YOYOPY_REGISTRATION_FAILED;
        case LinphoneRegistrationNone:
        default:
            return YOYOPY_REGISTRATION_NONE;
    }
}

static int yoyopy_map_call_state(LinphoneCallState state) {
    switch (state) {
        case LinphoneCallIncomingReceived:
        case LinphoneCallIncomingEarlyMedia:
            return YOYOPY_CALL_INCOMING;
        case LinphoneCallOutgoingInit:
            return YOYOPY_CALL_OUTGOING_INIT;
        case LinphoneCallOutgoingProgress:
            return YOYOPY_CALL_OUTGOING_PROGRESS;
        case LinphoneCallOutgoingRinging:
            return YOYOPY_CALL_OUTGOING_RINGING;
        case LinphoneCallOutgoingEarlyMedia:
            return YOYOPY_CALL_OUTGOING_EARLY_MEDIA;
        case LinphoneCallConnected:
            return YOYOPY_CALL_CONNECTED;
        case LinphoneCallStreamsRunning:
            return YOYOPY_CALL_STREAMS_RUNNING;
        case LinphoneCallPaused:
            return YOYOPY_CALL_PAUSED;
        case LinphoneCallPausedByRemote:
            return YOYOPY_CALL_PAUSED_BY_REMOTE;
        case LinphoneCallUpdatedByRemote:
        case LinphoneCallUpdating:
        case LinphoneCallEarlyUpdatedByRemote:
        case LinphoneCallEarlyUpdating:
            return YOYOPY_CALL_UPDATED_BY_REMOTE;
        case LinphoneCallReleased:
            return YOYOPY_CALL_RELEASED;
        case LinphoneCallError:
            return YOYOPY_CALL_ERROR;
        case LinphoneCallEnd:
            return YOYOPY_CALL_END;
        case LinphoneCallIdle:
        default:
            return YOYOPY_CALL_IDLE;
    }
}

static int yoyopy_map_message_delivery_state(LinphoneChatMessageState state) {
    switch (state) {
        case LinphoneChatMessageStateIdle:
            return YOYOPY_MESSAGE_DELIVERY_QUEUED;
        case LinphoneChatMessageStateInProgress:
        case LinphoneChatMessageStateFileTransferInProgress:
            return YOYOPY_MESSAGE_DELIVERY_SENDING;
        case LinphoneChatMessageStateDelivered:
        case LinphoneChatMessageStateFileTransferDone:
            return YOYOPY_MESSAGE_DELIVERY_SENT;
        case LinphoneChatMessageStateDeliveredToUser:
        case LinphoneChatMessageStateDisplayed:
            return YOYOPY_MESSAGE_DELIVERY_DELIVERED;
        case LinphoneChatMessageStateNotDelivered:
        case LinphoneChatMessageStateFileTransferError:
        default:
            return YOYOPY_MESSAGE_DELIVERY_FAILED;
    }
}

static int yoyopy_path_exists(const char *path) {
    if (path == NULL || path[0] == '\0') {
        return 0;
    }
    return access(path, F_OK) == 0;
}

static void yoyopy_ensure_directory(const char *path) {
    char buffer[512];
    size_t length;
    size_t index;

    if (path == NULL || path[0] == '\0') {
        return;
    }

    yoyopy_copy_string(buffer, sizeof(buffer), path);
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

static void yoyopy_build_address_uri(const LinphoneAddress *address, char *buffer, size_t buffer_size) {
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

static void yoyopy_build_message_id(LinphoneChatMessage *message, char *buffer, size_t buffer_size) {
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
        yoyopy_copy_string(buffer, buffer_size, message_id);
        return;
    }

    user_data = (const char *)linphone_chat_message_get_user_data(message);
    if (user_data != NULL && user_data[0] != '\0') {
        yoyopy_copy_string(buffer, buffer_size, user_data);
        return;
    }

    clock_gettime(CLOCK_REALTIME, &now);
    g_state.message_counter += 1;
    snprintf(buffer, buffer_size, "local-%lld-%llu", (long long)now.tv_sec, g_state.message_counter);
    linphone_chat_message_set_user_data(message, strdup(buffer));
}

static void yoyopy_build_mime_type(const LinphoneContent *content, char *buffer, size_t buffer_size) {
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
        yoyopy_copy_string(buffer, buffer_size, type);
    }
}

static int yoyopy_is_voice_note_content(const LinphoneContent *content) {
    const char *type;
    if (content == NULL) {
        return 0;
    }
    type = linphone_content_get_type(content);
    return type != NULL && strcmp(type, "audio") == 0;
}

static int yoyopy_message_kind_from_message(LinphoneChatMessage *message) {
    LinphoneContent *content = linphone_chat_message_get_file_transfer_information(message);
    return yoyopy_is_voice_note_content(content) ? YOYOPY_MESSAGE_KIND_VOICE_NOTE : YOYOPY_MESSAGE_KIND_TEXT;
}

static int yoyopy_message_direction_from_message(const LinphoneChatMessage *message) {
    return linphone_chat_message_is_outgoing(message)
               ? YOYOPY_MESSAGE_DIRECTION_OUTGOING
               : YOYOPY_MESSAGE_DIRECTION_INCOMING;
}

static void yoyopy_enqueue_event(const yoyopy_liblinphone_event_t *event_value) {
    size_t next_tail;
    pthread_mutex_lock(&g_state.queue_lock);
    next_tail = (g_state.queue_tail + 1U) % YOYOPY_EVENT_QUEUE_CAPACITY;
    if (next_tail == g_state.queue_head) {
        g_state.queue_head = (g_state.queue_head + 1U) % YOYOPY_EVENT_QUEUE_CAPACITY;
    }
    g_state.queue[g_state.queue_tail] = *event_value;
    g_state.queue_tail = next_tail;
    pthread_mutex_unlock(&g_state.queue_lock);
}

static void yoyopy_queue_registration_event(LinphoneRegistrationState state, const char *reason) {
    yoyopy_liblinphone_event_t event_value;
    memset(&event_value, 0, sizeof(event_value));
    event_value.type = YOYOPY_EVENT_REGISTRATION;
    event_value.registration_state = yoyopy_map_registration_state(state);
    yoyopy_copy_string(event_value.reason, sizeof(event_value.reason), reason);
    yoyopy_enqueue_event(&event_value);
}

static void yoyopy_queue_call_state_event(LinphoneCall *call, LinphoneCallState state, const char *reason) {
    yoyopy_liblinphone_event_t event_value;
    memset(&event_value, 0, sizeof(event_value));
    event_value.type = YOYOPY_EVENT_CALL_STATE;
    event_value.call_state = yoyopy_map_call_state(state);
    if (call != NULL) {
        yoyopy_build_address_uri(
            linphone_call_get_remote_address(call),
            event_value.peer_sip_address,
            sizeof(event_value.peer_sip_address)
        );
    }
    yoyopy_copy_string(event_value.reason, sizeof(event_value.reason), reason);
    yoyopy_enqueue_event(&event_value);
}

static void yoyopy_queue_incoming_call_event(LinphoneCall *call) {
    yoyopy_liblinphone_event_t event_value;
    memset(&event_value, 0, sizeof(event_value));
    event_value.type = YOYOPY_EVENT_INCOMING_CALL;
    if (call != NULL) {
        yoyopy_build_address_uri(
            linphone_call_get_remote_address(call),
            event_value.peer_sip_address,
            sizeof(event_value.peer_sip_address)
        );
    }
    yoyopy_enqueue_event(&event_value);
}

static void yoyopy_fill_message_event_common(
    yoyopy_liblinphone_event_t *event_value,
    LinphoneChatMessage *message
) {
    LinphoneContent *content;

    content = linphone_chat_message_get_file_transfer_information(message);
    event_value->message_kind = yoyopy_message_kind_from_message(message);
    event_value->message_direction = yoyopy_message_direction_from_message(message);
    event_value->message_delivery_state = yoyopy_map_message_delivery_state(
        linphone_chat_message_get_state(message)
    );
    yoyopy_build_message_id(message, event_value->message_id, sizeof(event_value->message_id));
    yoyopy_build_address_uri(
        linphone_chat_message_get_peer_address(message),
        event_value->peer_sip_address,
        sizeof(event_value->peer_sip_address)
    );
    yoyopy_build_address_uri(
        linphone_chat_message_get_from_address(message),
        event_value->sender_sip_address,
        sizeof(event_value->sender_sip_address)
    );
    yoyopy_build_address_uri(
        linphone_chat_message_get_to_address(message),
        event_value->recipient_sip_address,
        sizeof(event_value->recipient_sip_address)
    );
    yoyopy_copy_string(
        event_value->text,
        sizeof(event_value->text),
        linphone_chat_message_get_utf8_text(message)
    );
    yoyopy_build_mime_type(content, event_value->mime_type, sizeof(event_value->mime_type));
    if (content != NULL) {
        yoyopy_copy_string(
            event_value->local_file_path,
            sizeof(event_value->local_file_path),
            linphone_content_get_file_path(content)
        );
    }
}

static void yoyopy_attach_message_callbacks(LinphoneChatMessage *message) {
    if (message == NULL || g_state.message_cbs == NULL) {
        return;
    }
    linphone_chat_message_add_callbacks(message, g_state.message_cbs);
}

static void yoyopy_generate_voice_note_path(
    const char *message_id,
    const char *mime_type,
    char *buffer,
    size_t buffer_size
) {
    const char *extension = "wav";
    if (mime_type != NULL && strstr(mime_type, "/") != NULL) {
        const char *slash = strchr(mime_type, '/');
        if (slash != NULL && slash[1] != '\0') {
            extension = slash + 1;
        }
    }
    snprintf(buffer, buffer_size, "%s/%s.%s", g_state.voice_note_store_dir, message_id, extension);
}

static void yoyopy_prepare_auto_download(LinphoneChatMessage *message) {
    LinphoneContent *content;
    char message_id[128];
    char mime_type[128];
    char target_path[512];

    if (!g_state.auto_download_incoming_voice_recordings || message == NULL) {
        return;
    }

    content = linphone_chat_message_get_file_transfer_information(message);
    if (!yoyopy_is_voice_note_content(content)) {
        return;
    }

    yoyopy_build_message_id(message, message_id, sizeof(message_id));
    yoyopy_build_mime_type(content, mime_type, sizeof(mime_type));
    yoyopy_generate_voice_note_path(message_id, mime_type, target_path, sizeof(target_path));
    yoyopy_ensure_directory(g_state.voice_note_store_dir);
    linphone_content_set_file_path(content, target_path);
    linphone_chat_message_download_content(message, content);
}

static int yoyopy_apply_transports(LinphoneCore *core, const char *transport) {
    LinphoneTransports *transports = NULL;
    const char *selected = transport;
    LinphoneStatus status;

    if (core == NULL) {
        yoyopy_set_error("Cannot configure Liblinphone transports without a core");
        return -1;
    }

    if (selected == NULL || selected[0] == '\0' || strcmp(selected, "auto") == 0) {
        selected = "tcp";
    }

    transports = linphone_core_get_transports(core);
    if (transports == NULL) {
        yoyopy_set_error("Failed to allocate Linphone transports");
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
        yoyopy_set_error("Failed to configure Liblinphone transports for %s", selected);
        return -1;
    }
    return 0;
}

static int yoyopy_configure_media_policy(LinphoneCore *core, LinphoneFactory *factory) {
    LinphoneVideoActivationPolicy *policy = NULL;

    if (core == NULL || factory == NULL) {
        yoyopy_set_error("Cannot configure Liblinphone media policy without a core and factory");
        return -1;
    }

    linphone_core_enable_video_capture(core, FALSE);
    linphone_core_enable_video_display(core, FALSE);

    policy = linphone_factory_create_video_activation_policy(factory);
    if (policy == NULL) {
        yoyopy_set_error("Failed to create Liblinphone video activation policy");
        return -1;
    }

    linphone_video_activation_policy_set_automatically_accept(policy, FALSE);
    linphone_video_activation_policy_set_automatically_initiate(policy, FALSE);
    linphone_core_set_video_activation_policy(core, policy);
    linphone_video_activation_policy_unref(policy);
    return 0;
}

static int yoyopy_configure_network_media_defaults(LinphoneCore *core, const char *stun_server) {
    LinphoneNatPolicy *nat_policy = NULL;

    if (core == NULL) {
        yoyopy_set_error("Cannot configure Liblinphone network defaults without a core");
        return -1;
    }

    linphone_core_set_media_encryption(core, LinphoneMediaEncryptionSRTP);
    linphone_core_set_media_encryption_mandatory(core, FALSE);
    linphone_core_set_audio_port_range(core, 7076, 7100);
    linphone_core_set_video_port_range(core, 9076, 9100);

    nat_policy = linphone_core_create_nat_policy(core);
    if (nat_policy == NULL) {
        yoyopy_set_error("Failed to create Liblinphone NAT policy");
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

static void yoyopy_queue_message_received_event(LinphoneChatMessage *message) {
    yoyopy_liblinphone_event_t event_value;
    memset(&event_value, 0, sizeof(event_value));
    event_value.type = YOYOPY_EVENT_MESSAGE_RECEIVED;
    event_value.unread = linphone_chat_message_is_read(message) ? 0 : 1;
    yoyopy_fill_message_event_common(&event_value, message);
    yoyopy_enqueue_event(&event_value);
}

static void yoyopy_queue_message_delivery_event(
    LinphoneChatMessage *message,
    LinphoneChatMessageState state
) {
    yoyopy_liblinphone_event_t event_value;
    memset(&event_value, 0, sizeof(event_value));
    event_value.type = YOYOPY_EVENT_MESSAGE_DELIVERY_CHANGED;
    yoyopy_fill_message_event_common(&event_value, message);
    event_value.message_delivery_state = yoyopy_map_message_delivery_state(state);
    if (state == LinphoneChatMessageStateNotDelivered || state == LinphoneChatMessageStateFileTransferError) {
        const char *state_text = linphone_chat_message_state_to_string(state);
        yoyopy_copy_string(event_value.reason, sizeof(event_value.reason), state_text);
    }
    yoyopy_enqueue_event(&event_value);
}

static void yoyopy_queue_download_completed_event(LinphoneChatMessage *message) {
    LinphoneContent *content;
    yoyopy_liblinphone_event_t event_value;
    memset(&event_value, 0, sizeof(event_value));
    content = linphone_chat_message_get_file_transfer_information(message);
    if (content == NULL) {
        return;
    }
    event_value.type = YOYOPY_EVENT_MESSAGE_DOWNLOAD_COMPLETED;
    yoyopy_fill_message_event_common(&event_value, message);
    yoyopy_copy_string(
        event_value.local_file_path,
        sizeof(event_value.local_file_path),
        linphone_content_get_file_path(content)
    );
    yoyopy_enqueue_event(&event_value);
}

static void yoyopy_on_registration_state_changed(
    LinphoneAccount *account,
    LinphoneRegistrationState state,
    const char *message
) {
    (void)account;
    yoyopy_queue_registration_event(state, message);
}

static void yoyopy_on_call_state_changed(
    LinphoneCore *core,
    LinphoneCall *call,
    LinphoneCallState state,
    const char *message
) {
    (void)core;
    g_state.current_call = call;
    yoyopy_queue_call_state_event(call, state, message);
    if (state == LinphoneCallIncomingReceived) {
        yoyopy_queue_incoming_call_event(call);
    }
    if (state == LinphoneCallReleased || state == LinphoneCallEnd || state == LinphoneCallError) {
        g_state.current_call = NULL;
    }
}

static void yoyopy_on_message_received(
    LinphoneCore *core,
    LinphoneChatRoom *chat_room,
    LinphoneChatMessage *message
) {
    (void)core;
    (void)chat_room;
    yoyopy_attach_message_callbacks(message);
    yoyopy_queue_message_received_event(message);
    yoyopy_prepare_auto_download(message);
}

static void yoyopy_on_message_state_changed(
    LinphoneChatMessage *message,
    LinphoneChatMessageState state
) {
    yoyopy_queue_message_delivery_event(message, state);
    if (state == LinphoneChatMessageStateFileTransferDone) {
        yoyopy_queue_download_completed_event(message);
    }
}

static int yoyopy_configure_account(
    const char *sip_server,
    const char *sip_username,
    const char *sip_password,
    const char *sip_password_ha1,
    const char *sip_identity,
    const char *transport,
    const char *file_transfer_server_url
) {
    LinphoneAddress *server_address = NULL;
    LinphoneAddress *identity_address = NULL;
    LinphoneAccountParams *params = NULL;
    LinphoneAccount *account = NULL;
    LinphoneAuthInfo *auth_info = NULL;
    char server_uri[256];

    snprintf(
        server_uri,
        sizeof(server_uri),
        "sip:%s;transport=%s",
        yoyopy_safe_string(sip_server),
        transport != NULL && transport[0] != '\0' ? transport : "tcp"
    );

    params = linphone_core_create_account_params(g_state.core);
    if (params == NULL) {
        yoyopy_set_error("Failed to create Linphone account params");
        return -1;
    }

    server_address = linphone_factory_create_address(g_state.factory, server_uri);
    identity_address = linphone_factory_create_address(g_state.factory, sip_identity);
    if (server_address == NULL || identity_address == NULL) {
        yoyopy_set_error("Failed to create Linphone account addresses");
        goto fail;
    }

    if (linphone_account_params_set_server_address(params, server_address) != 0) {
        yoyopy_set_error("Failed to set Linphone server address");
        goto fail;
    }
    if (linphone_account_params_set_identity_address(params, identity_address) != 0) {
        yoyopy_set_error("Failed to set Linphone identity address");
        goto fail;
    }
    linphone_account_params_enable_register(params, TRUE);
    if (file_transfer_server_url != NULL && file_transfer_server_url[0] != '\0') {
        linphone_account_params_set_file_transfer_server(params, file_transfer_server_url);
        linphone_core_set_file_transfer_server(g_state.core, file_transfer_server_url);
    }

    account = linphone_core_create_account(g_state.core, params);
    if (account == NULL) {
        yoyopy_set_error("Failed to create Linphone account");
        goto fail;
    }

    g_state.account_cbs = linphone_account_cbs_new();
    if (g_state.account_cbs == NULL) {
        yoyopy_set_error("Failed to create Linphone account callbacks");
        goto fail;
    }
    linphone_account_cbs_set_registration_state_changed(
        g_state.account_cbs,
        yoyopy_on_registration_state_changed
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
        yoyopy_set_error("Failed to add Linphone account to core");
        goto fail;
    }
    linphone_core_set_default_account(g_state.core, account);
    g_state.account = account;

    linphone_address_unref(server_address);
    linphone_address_unref(identity_address);
    linphone_account_params_unref(params);
    return 0;

fail:
    if (account != NULL) {
        linphone_account_unref(account);
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
}

static void yoyopy_cleanup_recorder(void) {
    if (g_state.current_recorder != NULL) {
        if (g_state.recorder_running) {
            linphone_recorder_pause(g_state.current_recorder);
        }
        linphone_recorder_close(g_state.current_recorder);
        linphone_recorder_unref(g_state.current_recorder);
        g_state.current_recorder = NULL;
    }
    g_state.recorder_running = false;
    g_state.current_recording_path[0] = '\0';
}

int yoyopy_liblinphone_init(void) {
    if (g_state.initialized) {
        return 0;
    }
    memset(&g_state, 0, sizeof(g_state));
    if (pthread_mutex_init(&g_state.queue_lock, NULL) != 0) {
        yoyopy_set_error("Failed to initialize Liblinphone event queue mutex");
        return -1;
    }
    g_state.factory = linphone_factory_get();
    if (g_state.factory == NULL) {
        yoyopy_set_error("Failed to get Liblinphone factory");
        pthread_mutex_destroy(&g_state.queue_lock);
        return -1;
    }
    g_state.initialized = true;
    yoyopy_clear_error();
    return 0;
}

void yoyopy_liblinphone_shutdown(void) {
    yoyopy_liblinphone_stop();
    if (g_state.initialized) {
        pthread_mutex_destroy(&g_state.queue_lock);
        memset(&g_state, 0, sizeof(g_state));
    }
}

int yoyopy_liblinphone_start(
    const char *sip_server,
    const char *sip_username,
    const char *sip_password,
    const char *sip_password_ha1,
    const char *sip_identity,
    const char *factory_config_path,
    const char *transport,
    const char *stun_server,
    const char *file_transfer_server_url,
    int32_t auto_download_incoming_voice_recordings,
    const char *playback_device_id,
    const char *ringer_device_id,
    const char *capture_device_id,
    const char *media_device_id,
    int32_t echo_cancellation,
    int32_t mic_gain,
    int32_t speaker_volume,
    const char *voice_note_store_dir
) {
    if (!g_state.initialized && yoyopy_liblinphone_init() != 0) {
        return -1;
    }

    if (g_state.started) {
        return 0;
    }

    if (sip_server == NULL || sip_server[0] == '\0' || sip_identity == NULL || sip_identity[0] == '\0') {
        yoyopy_set_error("Missing SIP identity or SIP server for Liblinphone startup");
        return -1;
    }

    g_state.core = linphone_factory_create_core_3(
        g_state.factory,
        NULL,
        (factory_config_path != NULL && factory_config_path[0] != '\0') ? factory_config_path : NULL,
        NULL
    );
    if (g_state.core == NULL) {
        yoyopy_set_error("Failed to create Liblinphone core");
        return -1;
    }

    g_state.core_cbs = linphone_factory_create_core_cbs(g_state.factory);
    if (g_state.core_cbs == NULL) {
        yoyopy_set_error("Failed to create Liblinphone core callbacks");
        yoyopy_liblinphone_stop();
        return -1;
    }

    g_state.message_cbs = linphone_chat_message_cbs_new();
    if (g_state.message_cbs == NULL) {
        yoyopy_set_error("Failed to create Liblinphone chat message callbacks");
        yoyopy_liblinphone_stop();
        return -1;
    }

    g_state.auto_download_incoming_voice_recordings = auto_download_incoming_voice_recordings != 0;
    yoyopy_copy_string(g_state.voice_note_store_dir, sizeof(g_state.voice_note_store_dir), voice_note_store_dir);
    yoyopy_ensure_directory(g_state.voice_note_store_dir);

    linphone_chat_message_cbs_set_msg_state_changed(g_state.message_cbs, yoyopy_on_message_state_changed);
    linphone_core_cbs_set_call_state_changed(g_state.core_cbs, yoyopy_on_call_state_changed);
    linphone_core_cbs_set_message_received(g_state.core_cbs, yoyopy_on_message_received);
    linphone_core_add_callbacks(g_state.core, g_state.core_cbs);

    linphone_core_set_playback_device(g_state.core, playback_device_id);
    linphone_core_set_ringer_device(g_state.core, ringer_device_id);
    linphone_core_set_capture_device(g_state.core, capture_device_id);
    linphone_core_set_media_device(g_state.core, media_device_id);
    linphone_core_enable_echo_cancellation(g_state.core, echo_cancellation != 0);
    linphone_core_set_mic_gain_db(g_state.core, ((float)mic_gain * 0.3f));
    linphone_core_set_playback_gain_db(g_state.core, ((float)speaker_volume * 0.12f) - 6.0f);
    if (yoyopy_configure_media_policy(g_state.core, g_state.factory) != 0) {
        yoyopy_liblinphone_stop();
        return -1;
    }
    if (yoyopy_configure_network_media_defaults(g_state.core, stun_server) != 0) {
        yoyopy_liblinphone_stop();
        return -1;
    }
    if (yoyopy_apply_transports(g_state.core, transport) != 0) {
        yoyopy_liblinphone_stop();
        return -1;
    }
    if (stun_server != NULL && stun_server[0] != '\0') {
        linphone_core_set_stun_server(g_state.core, stun_server);
    }
    if (file_transfer_server_url != NULL && file_transfer_server_url[0] != '\0') {
        linphone_core_set_file_transfer_server(g_state.core, file_transfer_server_url);
    }
    linphone_core_enable_auto_download_voice_recordings(
        g_state.core,
        g_state.auto_download_incoming_voice_recordings ? TRUE : FALSE
    );

    if (
        yoyopy_configure_account(
            sip_server,
            sip_username,
            sip_password,
            sip_password_ha1,
            sip_identity,
            transport,
            file_transfer_server_url
        ) != 0
    ) {
        yoyopy_liblinphone_stop();
        return -1;
    }

    if (linphone_core_start(g_state.core) != 0) {
        yoyopy_set_error("Liblinphone core failed to start");
        yoyopy_liblinphone_stop();
        return -1;
    }

    g_state.started = true;
    yoyopy_clear_error();
    return 0;
}

void yoyopy_liblinphone_stop(void) {
    if (g_state.core != NULL) {
        linphone_core_stop(g_state.core);
    }

    yoyopy_cleanup_recorder();
    g_state.current_call = NULL;

    if (g_state.account_cbs != NULL) {
        linphone_account_cbs_unref(g_state.account_cbs);
        g_state.account_cbs = NULL;
    }
    if (g_state.message_cbs != NULL) {
        linphone_chat_message_cbs_unref(g_state.message_cbs);
        g_state.message_cbs = NULL;
    }
    if (g_state.core_cbs != NULL) {
        linphone_core_cbs_unref(g_state.core_cbs);
        g_state.core_cbs = NULL;
    }
    if (g_state.account != NULL) {
        linphone_account_unref(g_state.account);
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

void yoyopy_liblinphone_iterate(void) {
    if (g_state.started && g_state.core != NULL) {
        linphone_core_iterate(g_state.core);
    }
}

int yoyopy_liblinphone_poll_event(yoyopy_liblinphone_event_t *event_out) {
    if (event_out == NULL || !g_state.initialized) {
        return 0;
    }

    pthread_mutex_lock(&g_state.queue_lock);
    if (g_state.queue_head == g_state.queue_tail) {
        pthread_mutex_unlock(&g_state.queue_lock);
        return 0;
    }

    *event_out = g_state.queue[g_state.queue_head];
    g_state.queue_head = (g_state.queue_head + 1U) % YOYOPY_EVENT_QUEUE_CAPACITY;
    pthread_mutex_unlock(&g_state.queue_lock);
    return 1;
}

int yoyopy_liblinphone_make_call(const char *sip_address) {
    LinphoneAddress *address = NULL;
    LinphoneCallParams *params = NULL;
    LinphoneCall *call = NULL;

    if (!g_state.started || g_state.core == NULL || sip_address == NULL || sip_address[0] == '\0') {
        yoyopy_set_error("Liblinphone core is not ready to place a call");
        return -1;
    }

    address = linphone_factory_create_address(g_state.factory, sip_address);
    if (address == NULL) {
        yoyopy_set_error("Invalid SIP address for outgoing call");
        return -1;
    }

    params = linphone_core_create_call_params(g_state.core, NULL);
    if (params == NULL) {
        linphone_address_unref(address);
        yoyopy_set_error("Failed to create Liblinphone call params");
        return -1;
    }

    call = linphone_core_invite_address_with_params(g_state.core, address, params);
    linphone_call_params_unref(params);
    linphone_address_unref(address);

    if (call == NULL) {
        yoyopy_set_error("Liblinphone failed to initiate outgoing call");
        return -1;
    }

    g_state.current_call = call;
    return 0;
}

int yoyopy_liblinphone_answer_call(void) {
    if (!g_state.started || g_state.current_call == NULL) {
        yoyopy_set_error("No incoming call is available to answer");
        return -1;
    }
    return linphone_call_accept(g_state.current_call) == 0 ? 0 : -1;
}

int yoyopy_liblinphone_reject_call(void) {
    if (!g_state.started || g_state.current_call == NULL) {
        yoyopy_set_error("No incoming call is available to reject");
        return -1;
    }
    return linphone_call_decline(g_state.current_call, LinphoneReasonDeclined) == 0 ? 0 : -1;
}

int yoyopy_liblinphone_hangup(void) {
    if (!g_state.started || g_state.current_call == NULL) {
        yoyopy_set_error("No active call is available to hang up");
        return -1;
    }
    return linphone_call_terminate(g_state.current_call) == 0 ? 0 : -1;
}

int yoyopy_liblinphone_set_muted(int32_t muted) {
    if (!g_state.started || g_state.current_call == NULL) {
        yoyopy_set_error("No active call is available to mute");
        return -1;
    }
    linphone_call_set_microphone_muted(g_state.current_call, muted ? TRUE : FALSE);
    return 0;
}

static LinphoneChatRoom *yoyopy_get_chat_room(const char *sip_address) {
    if (!g_state.started || g_state.core == NULL) {
        return NULL;
    }
    return linphone_core_get_chat_room_from_uri(g_state.core, sip_address);
}

static void yoyopy_fill_message_id_out(
    LinphoneChatMessage *message,
    char *message_id_out,
    uint32_t message_id_out_size
) {
    char message_id[128];
    yoyopy_build_message_id(message, message_id, sizeof(message_id));
    if (message_id_out != NULL && message_id_out_size > 0) {
        snprintf(message_id_out, message_id_out_size, "%s", message_id);
    }
}

int yoyopy_liblinphone_send_text_message(
    const char *sip_address,
    const char *text,
    char *message_id_out,
    uint32_t message_id_out_size
) {
    LinphoneChatRoom *chat_room;
    LinphoneChatMessage *message;

    if (!g_state.started || sip_address == NULL || sip_address[0] == '\0' || text == NULL) {
        yoyopy_set_error("Liblinphone text message send is missing peer or payload");
        return -1;
    }

    chat_room = yoyopy_get_chat_room(sip_address);
    if (chat_room == NULL) {
        yoyopy_set_error("Liblinphone could not resolve a chat room for %s", sip_address);
        return -1;
    }

    message = linphone_chat_room_create_message_from_utf8(chat_room, text);
    if (message == NULL) {
        yoyopy_set_error("Liblinphone failed to create a text chat message");
        return -1;
    }

    yoyopy_attach_message_callbacks(message);
    yoyopy_fill_message_id_out(message, message_id_out, message_id_out_size);
    linphone_chat_message_send(message);
    return 0;
}

int yoyopy_liblinphone_start_voice_recording(const char *file_path) {
    LinphoneRecorderParams *params;
    if (!g_state.started || g_state.core == NULL || file_path == NULL || file_path[0] == '\0') {
        yoyopy_set_error("Liblinphone voice-note recording requires an active core and target path");
        return -1;
    }

    yoyopy_cleanup_recorder();
    params = linphone_core_create_recorder_params(g_state.core);
    if (params == NULL) {
        yoyopy_set_error("Failed to create Liblinphone recorder params");
        return -1;
    }
    linphone_recorder_params_set_file_format(params, LinphoneRecorderFileFormatWav);

    g_state.current_recorder = linphone_core_create_recorder(g_state.core, params);
    linphone_recorder_params_unref(params);
    if (g_state.current_recorder == NULL) {
        yoyopy_set_error("Failed to create Liblinphone recorder");
        return -1;
    }

    yoyopy_copy_string(g_state.current_recording_path, sizeof(g_state.current_recording_path), file_path);
    yoyopy_ensure_directory(g_state.voice_note_store_dir);
    if (linphone_recorder_open(g_state.current_recorder, file_path) != 0) {
        yoyopy_set_error("Failed to open voice-note file for recording");
        yoyopy_cleanup_recorder();
        return -1;
    }
    if (linphone_recorder_start(g_state.current_recorder) != 0) {
        yoyopy_set_error("Failed to start voice-note recording");
        yoyopy_cleanup_recorder();
        return -1;
    }

    g_state.recorder_running = true;
    return 0;
}

int yoyopy_liblinphone_stop_voice_recording(int32_t *duration_ms_out) {
    int duration_ms;
    if (!g_state.started || g_state.current_recorder == NULL || !g_state.recorder_running) {
        yoyopy_set_error("No active Liblinphone voice-note recording is running");
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
}

int yoyopy_liblinphone_cancel_voice_recording(void) {
    if (g_state.current_recording_path[0] != '\0') {
        unlink(g_state.current_recording_path);
    }
    yoyopy_cleanup_recorder();
    return 0;
}

int yoyopy_liblinphone_send_voice_note(
    const char *sip_address,
    const char *file_path,
    int32_t duration_ms,
    const char *mime_type,
    char *message_id_out,
    uint32_t message_id_out_size
) {
    LinphoneChatRoom *chat_room;
    LinphoneChatMessage *message;

    (void)duration_ms;
    (void)mime_type;

    if (!g_state.started || g_state.current_recorder == NULL || sip_address == NULL || sip_address[0] == '\0') {
        yoyopy_set_error("Liblinphone voice-note send requires a closed recording and recipient");
        return -1;
    }
    if (g_state.recorder_running) {
        yoyopy_set_error("Voice-note recording must be stopped before sending");
        return -1;
    }
    if (file_path != NULL && file_path[0] != '\0' && strcmp(file_path, g_state.current_recording_path) != 0) {
        yoyopy_set_error("Voice-note send only supports the active recorder output in this build");
        return -1;
    }
    if (!yoyopy_path_exists(g_state.current_recording_path)) {
        yoyopy_set_error("Voice-note file does not exist at %s", g_state.current_recording_path);
        return -1;
    }

    chat_room = yoyopy_get_chat_room(sip_address);
    if (chat_room == NULL) {
        yoyopy_set_error("Liblinphone could not resolve a chat room for %s", sip_address);
        return -1;
    }

    message = linphone_chat_room_create_voice_recording_message(chat_room, g_state.current_recorder);
    if (message == NULL) {
        yoyopy_set_error("Liblinphone failed to create a voice-note message");
        return -1;
    }

    yoyopy_attach_message_callbacks(message);
    yoyopy_fill_message_id_out(message, message_id_out, message_id_out_size);
    linphone_chat_message_send(message);
    return 0;
}

const char *yoyopy_liblinphone_last_error(void) {
    return g_last_error;
}

const char *yoyopy_liblinphone_version(void) {
    return linphone_core_get_version();
}
