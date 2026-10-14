/* SPDX-License-Identifier: GPL-2.0-or-later */
#include <config.h>
/* Compile the real implementation once in this translation unit so regressions
 * can reach private constructors and event callbacks without an installed API.
 * Meson excludes this file from the remaining daemon sources in this target. */
#include "../mm-iface-modem-voice.c"
#include "mm-broadband-modem.h"
#include "provider-fixture.h"
#include "plugins/simtech/mm-broadband-modem-qmi-simtech.h"
#include "mm-kernel-device-generic.h"
#include "mm-call-qmi.h"

struct _VoiceFixture {
    GTestDBus *bus;
    GDBusConnection *server;
    GDBusConnection *client;
    MMIfaceModemVoice *voice;
    MMCallList *calls;
    MMPort *port;
    GPtrArray *owned_calls;
    gchar *last_port;
    GPtrArray *channels;
    MMPortQmi *qmi_port;
    QmiClientVoice *qmi_client;
    guint end_call_count;
    guint8 end_call_id;
    guint transport_tasks;
};

typedef struct {
    MMVoiceAudioToken token;
    gboolean cleanup;
    gboolean done;
    GTask *transport;
    GCancellable *cancellable;
} FixtureChannel;

static void fixture_support_ready (MMIfaceModemVoice *self, GAsyncResult *res, gboolean *done);

static void
fixture_transport_freed (gpointer user_data, GObject *object)
{
    VoiceFixture *f = user_data;
    g_assert_cmpuint (f->transport_tasks, >, 0);
    f->transport_tasks--;
}

static void
fixture_track_transport (VoiceFixture *f, GTask *task)
{
    f->transport_tasks++;
    g_object_weak_ref (G_OBJECT (task), fixture_transport_freed, f);
}

static void
fixture_channel_free (FixtureChannel *channel)
{
    g_assert_true (channel->done);
    g_assert_null (channel->transport);
    g_clear_object (&channel->cancellable);
    g_free (channel);
}

static void
fixture_grab_port (VoiceFixture *f, const gchar *subsystem, const gchar *name, MMPortType type)
{
    g_autoptr(MMKernelEventProperties) properties = mm_kernel_event_properties_new ();
    g_autoptr(MMKernelDevice) device = NULL;
    g_autoptr(GError) error = NULL;

    /* Inert kernel-event descriptors: 'remove' permits nonexistent sysfs paths.
     * We register real port objects; no device nodes are opened by this fixture. */
    mm_kernel_event_properties_set_action (properties, "remove");
    mm_kernel_event_properties_set_subsystem (properties, subsystem);
    mm_kernel_event_properties_set_name (properties, name);
    device = mm_kernel_device_generic_new_with_rules (properties, NULL, &error);
    g_assert_no_error (error);
    g_assert_nonnull (device);
    g_assert_true (mm_base_modem_grab_port (MM_BASE_MODEM (f->voice), device, type,
                                          MM_PORT_SERIAL_AT_FLAG_NONE, &error));
    g_assert_no_error (error);
}

static void
fixture_support_ready (MMIfaceModemVoice *self, GAsyncResult *res, gboolean *done)
{
    g_autoptr(GError) error = NULL;
    g_assert_true (MM_IFACE_MODEM_VOICE_GET_IFACE (self)->check_support_finish (self, res, &error));
    g_assert_no_error (error);
    *done = TRUE;
}

/* Only fixed transport effects are replaced. Real Simtech callbacks consume
 * source-object-bound tasks; no modem state or Call behavior is reimplemented. */
void
__wrap_mm_base_modem_at_command (MMBaseModem *self, const gchar *command,
                                 guint timeout, gboolean cached,
                                 GAsyncReadyCallback callback, gpointer user_data)
{
    VoiceFixture *f = g_object_get_data (G_OBJECT (self), "voice-fixture");
    GTask *task;
    const gchar *reply = "";
    guint i;

    g_assert_nonnull (f);
    g_assert_cmpuint (timeout, ==, 3);
    task = g_task_new (self, NULL, callback, user_data);
    fixture_track_transport (f, task);
    if (!g_strcmp0 (command, "+CPCMREG=1") || !g_strcmp0 (command, "+CPCMREG=0")) {
        gboolean cleanup = !g_strcmp0 (command, "+CPCMREG=0");
        g_assert_false (cached);
        for (i = 0; i < f->channels->len; i++) {
            FixtureChannel *channel = g_ptr_array_index (f->channels, i);
            if (!channel->done && !channel->transport && channel->cleanup == cleanup) {
                channel->transport = task;
                return;
            }
        }
        g_assert_not_reached ();
    }
    if (!g_strcmp0 (command, "+CLCC=?"))
        reply = "+CLCC: (0-1)";
    else if (!g_strcmp0 (command, "+CPCMREG=?"))
        reply = "+CPCMREG: (0,1)";
    else if (!g_strcmp0 (command, "+CPCMFRM=?"))
        reply = "+CPCMFRM: (0,1)";
    else
        g_assert_cmpstr (command, ==, "+CPCMFRM=1");
    g_assert_cmpint (cached, ==, g_strcmp0 (command, "+CPCMFRM=1") != 0);
    g_task_set_task_data (task, g_strdup (reply), g_free);
    g_task_return_boolean (task, TRUE);
    g_object_unref (task);
}

const gchar *
__wrap_mm_base_modem_at_command_finish (MMBaseModem *self, GAsyncResult *res, GError **error)
{
    g_assert_true (g_task_is_valid (res, self));
    if (!g_task_propagate_boolean (G_TASK (res), error))
        return NULL;
    return g_task_get_task_data (G_TASK (res));
}

MMPortQmi *
__wrap_mm_broadband_modem_qmi_peek_port_qmi (MMBroadbandModemQmi *self)
{
    VoiceFixture *f = g_object_get_data (G_OBJECT (self), "voice-fixture");
    g_assert_nonnull (f);
    return f->qmi_port;
}

QmiClient *
__wrap_mm_port_qmi_peek_client (MMPortQmi *port, QmiService service, guint flag)
{
    VoiceFixture *f = g_object_get_data (G_OBJECT (port), "voice-fixture");
    g_assert_nonnull (f);
    g_assert_cmpint (service, ==, QMI_SERVICE_VOICE);
    g_assert_cmpint (flag, ==, MM_PORT_QMI_FLAG_DEFAULT);
    return QMI_CLIENT (f->qmi_client);
}

void
__wrap_qmi_client_voice_end_call (QmiClientVoice *client, QmiMessageVoiceEndCallInput *input,
                                  guint timeout, GCancellable *cancellable,
                                  GAsyncReadyCallback callback, gpointer user_data)
{
    VoiceFixture *f = g_object_get_data (G_OBJECT (client), "voice-fixture");
    GTask *task;
    g_autoptr(GError) error = NULL;
    guint8 call_id = 0;

    g_assert_nonnull (f);
    g_assert_cmpuint (timeout, ==, 5);
    g_assert_true (qmi_message_voice_end_call_input_get_call_id (input, &call_id, &error));
    g_assert_no_error (error);
    f->end_call_id = call_id;
    f->end_call_count++;
    task = g_task_new (client, cancellable, callback, user_data);
    fixture_track_transport (f, task);
    /* A transport failure still proves the actual native-ID request and finish
     * error propagation. No QMI output structure or Call implementation is faked. */
    g_task_return_new_error (task, G_IO_ERROR, G_IO_ERROR_FAILED, "fixture QMI transport failure");
    g_object_unref (task);
}

QmiMessageVoiceEndCallOutput *
__wrap_qmi_client_voice_end_call_finish (QmiClientVoice *client, GAsyncResult *res, GError **error)
{
    g_assert_true (g_task_is_valid (res, client));
    return g_task_propagate_pointer (G_TASK (res), error);
}

static void
drain (void)
{
    while (g_main_context_iteration (NULL, FALSE));
}

VoiceFixture *
voice_fixture_new (void)
{
    VoiceFixture *f = g_new0 (VoiceFixture, 1);
    GError *error = NULL;
    gboolean supported = FALSE;
    const gchar *drivers[] = { "fixture", NULL };
    GDBusConnectionFlags flags = G_DBUS_CONNECTION_FLAGS_AUTHENTICATION_CLIENT |
                                 G_DBUS_CONNECTION_FLAGS_MESSAGE_BUS_CONNECTION;

    f->bus = g_test_dbus_new (G_TEST_DBUS_NONE);
    g_test_dbus_up (f->bus);
    f->server = g_dbus_connection_new_for_address_sync (g_test_dbus_get_bus_address (f->bus), flags, NULL, NULL, &error);
    g_assert_no_error (error);
    f->client = g_dbus_connection_new_for_address_sync (g_test_dbus_get_bus_address (f->bus), flags, NULL, NULL, &error);
    g_assert_no_error (error);
    f->voice = MM_IFACE_MODEM_VOICE (mm_broadband_modem_qmi_simtech_new ("fixture", "/fixture", drivers, "simtech", 0, 0));
    f->calls = mm_call_list_new (MM_BASE_MODEM (f->voice));
    g_object_set (f->voice, MM_BASE_MODEM_CONNECTION, f->server,
                  MM_IFACE_MODEM_VOICE_CALL_LIST, f->calls, NULL);
    f->channels = g_ptr_array_new_with_free_func ((GDestroyNotify) fixture_channel_free);
    g_object_set_data (G_OBJECT (f->voice), "voice-fixture", f);
    fixture_grab_port (f, "tty", "fixture-audio", MM_PORT_TYPE_AUDIO);
    fixture_grab_port (f, "usbmisc", "fixture-qmi", MM_PORT_TYPE_QMI);
    fixture_grab_port (f, "net", "fixture-net", MM_PORT_TYPE_NET);
    f->port = mm_base_modem_get_port (MM_BASE_MODEM (f->voice), "fixture-audio");
    f->qmi_port = MM_PORT_QMI (mm_base_modem_get_port (MM_BASE_MODEM (f->voice), "fixture-qmi"));
    g_assert_nonnull (f->port);
    g_assert_nonnull (f->qmi_port);
    g_object_set_data (G_OBJECT (f->qmi_port), "voice-fixture", f);
    f->qmi_client = g_object_new (QMI_TYPE_CLIENT_VOICE, NULL);
    g_object_set_data (G_OBJECT (f->qmi_client), "voice-fixture", f);
    g_assert_true (mm_base_modem_organize_ports (MM_BASE_MODEM (f->voice), &error));
    g_assert_no_error (error);
    MM_IFACE_MODEM_VOICE_GET_IFACE (f->voice)->check_support (
        f->voice, (GAsyncReadyCallback) fixture_support_ready, &supported);
    while (!supported)
        g_main_context_iteration (NULL, TRUE);
    f->owned_calls = g_ptr_array_new_with_free_func (g_object_unref);
    return f;
}

void
voice_fixture_free (VoiceFixture *f)
{
    guint i;
    gpointer weak_voice = f->voice;
    for (i = 0; i < f->owned_calls->len; i++)
        mm_base_call_unexport (g_ptr_array_index (f->owned_calls, i));
    g_object_set (f->voice, MM_IFACE_MODEM_VOICE_CALL_LIST, NULL,
                  MM_BASE_MODEM_CONNECTION, NULL, NULL);
    g_clear_object (&f->calls);
    g_ptr_array_unref (f->owned_calls);
    mm_iface_modem_voice_audio_invalidate (f->voice);
    g_object_add_weak_pointer (G_OBJECT (f->voice), &weak_voice);
    g_clear_object (&f->voice);
    g_clear_object (&f->port);
    g_clear_object (&f->qmi_port);
    g_clear_object (&f->qmi_client);
    g_ptr_array_unref (f->channels);
    drain ();
    g_assert_null (weak_voice);
    g_assert_cmpuint (f->transport_tasks, ==, 0);
    g_dbus_connection_close_sync (f->client, NULL, NULL);
    g_dbus_connection_close_sync (f->server, NULL, NULL);
    g_clear_object (&f->client);
    g_clear_object (&f->server);
    drain ();
    g_test_dbus_down (f->bus);
    g_object_unref (f->bus);
    g_free (f->last_port);
    g_free (f);
}

MMIfaceModemVoice *voice_fixture_voice (VoiceFixture *f) { return f->voice; }
MMPort *voice_fixture_audio_port (VoiceFixture *f) { return f->port; }

static MMBaseCall *
add_call (VoiceFixture *f, MMBaseCall *call)
{
    mm_base_call_export (call);
    mm_call_list_add_call (f->calls, call);
    g_ptr_array_add (f->owned_calls, call);
    return call;
}

MMBaseCall *
voice_fixture_incoming (VoiceFixture *f, const gchar *number)
{
    MMBaseCall *call = create_incoming_call (f->voice, number);
    mm_base_call_change_state (call, MM_CALL_STATE_RINGING_IN, MM_CALL_STATE_REASON_INCOMING_NEW);
    return add_call (f, call);
}

MMBaseCall *
voice_fixture_outgoing (VoiceFixture *f, const gchar *number)
{
    MMCallProperties *properties = mm_call_properties_new ();
    MMBaseCall *call;
    GError *error = NULL;
    mm_call_properties_set_number (properties, number);
    call = create_outgoing_call_from_properties (f->voice, properties, &error);
    g_assert_no_error (error);
    g_object_unref (properties);
    return add_call (f, call);
}

typedef struct { gboolean done; GVariant *reply; GError *error; } ReadResult;

static void
read_ready (GDBusConnection *connection, GAsyncResult *res, ReadResult *r)
{
    r->reply = g_dbus_connection_call_finish (connection, res, &r->error);
    r->done = TRUE;
}

static GVariant *
read_property (VoiceFixture *f, MMBaseCall *call, const gchar *name)
{
    ReadResult r = { 0 };
    GVariant *boxed, *value;
    g_dbus_interface_skeleton_flush (G_DBUS_INTERFACE_SKELETON (call));
    g_dbus_connection_call (f->client, g_dbus_connection_get_unique_name (f->server),
                            mm_base_call_get_path (call), "org.freedesktop.DBus.Properties", "Get",
                            g_variant_new ("(ss)", "org.freedesktop.ModemManager1.Call", name),
                            G_VARIANT_TYPE ("(v)"), G_DBUS_CALL_FLAGS_NONE, 5000, NULL,
                            (GAsyncReadyCallback) read_ready, &r);
    while (!r.done) g_main_context_iteration (NULL, TRUE);
    g_assert_no_error (r.error);
    g_variant_get (r.reply, "(@v)", &boxed);
    value = g_variant_get_variant (boxed);
    g_variant_unref (boxed);
    g_variant_unref (r.reply);
    return value;
}

guint
voice_fixture_read_format (VoiceFixture *f, MMBaseCall *call)
{
    GVariant *value = read_property (f, call, "AudioFormat");
    guint rate = 0;
    g_variant_lookup (value, "rate", "u", &rate);
    g_variant_unref (value);
    return rate;
}

const gchar *
voice_fixture_read_port (VoiceFixture *f, MMBaseCall *call)
{
    GVariant *value = read_property (f, call, "AudioPort");
    g_free (f->last_port);
    f->last_port = g_variant_dup_string (value, NULL);
    g_variant_unref (value);
    return f->last_port;
}

/* Synthetic test format; this makes no modem framing or qualification claim. */
void
voice_fixture_publish_active (VoiceFixture *f)
{
    MMVoiceAudioToken token = mm_iface_modem_voice_audio_begin_channel (f->voice);
    MMCallAudioFormat *format = mm_call_audio_format_new ();
    mm_call_audio_format_set_encoding (format, "pcm");
    mm_call_audio_format_set_resolution (format, "s16le");
    mm_call_audio_format_set_rate (format, 16000);
    g_assert_true (mm_iface_modem_voice_audio_commit_channel (f->voice, token, f->port, format));
    g_object_unref (format);
}

static void
fixture_setup_ready (MMIfaceModemVoice *self, GAsyncResult *res, FixtureChannel *channel)
{
    MMVoiceAudioToken *token = g_new (MMVoiceAudioToken, 1);
    *token = channel->token;
    in_call_setup_ready (self, res, token);
    channel->done = TRUE;
}

static void
fixture_cleanup_ready (MMIfaceModemVoice *self, GAsyncResult *res, FixtureChannel *channel)
{
    MMVoiceAudioToken *token = g_new (MMVoiceAudioToken, 1);
    *token = channel->token;
    in_call_cleanup_ready (self, res, token);
    channel->done = TRUE;
}

static MMVoiceAudioToken
fixture_start_channel (VoiceFixture *f, gboolean cleanup)
{
    InCallEventContext *ctx = get_in_call_event_context (f->voice);
    FixtureChannel *channel = g_new0 (FixtureChannel, 1);

    channel->token = mm_iface_modem_voice_audio_begin_channel (f->voice);
    g_assert_cmpuint (channel->token.operation, >, 0);
    channel->cleanup = cleanup;
    channel->cancellable = g_cancellable_new ();
    g_ptr_array_add (f->channels, channel);
    if (cleanup) {
        g_set_object (&ctx->cleanup_cancellable, channel->cancellable);
        in_call_cleanup (f->voice, channel->cancellable,
                         (GAsyncReadyCallback) fixture_cleanup_ready, channel);
    } else {
        g_set_object (&ctx->setup_cancellable, channel->cancellable);
        in_call_setup (f->voice, channel->cancellable,
                       (GAsyncReadyCallback) fixture_setup_ready, channel);
    }
    /* The actual Simtech 100ms timer reaches the wrapped fixed transport. */
    while (!channel->transport && !channel->done)
        g_main_context_iteration (NULL, TRUE);
    g_assert_nonnull (channel->transport);
    return channel->token;
}

MMVoiceAudioToken
voice_fixture_start_channel (VoiceFixture *f)
{
    return fixture_start_channel (f, FALSE);
}

MMVoiceAudioToken
voice_fixture_start_cleanup (VoiceFixture *f)
{
    return fixture_start_channel (f, TRUE);
}

void
voice_fixture_complete_channel (VoiceFixture *f, MMVoiceAudioToken token, gboolean success)
{
    guint i;
    for (i = 0; i < f->channels->len; i++) {
        FixtureChannel *channel = g_ptr_array_index (f->channels, i);
        if (channel->token.generation == token.generation &&
            channel->token.operation == token.operation) {
            GTask *transport = g_steal_pointer (&channel->transport);
            g_assert_nonnull (transport);
            g_task_set_task_data (transport, g_strdup (""), g_free);
            if (success)
                g_task_return_boolean (transport, TRUE);
            else
                g_task_return_new_error (transport, G_IO_ERROR, G_IO_ERROR_FAILED,
                                         "fixture AT transport failure");
            g_object_unref (transport);
            while (!channel->done)
                g_main_context_iteration (NULL, TRUE);
            return;
        }
    }
    g_assert_not_reached ();
}

void
voice_fixture_cleanup_last_channel (VoiceFixture *f)
{
    MMVoiceAudioToken token = voice_fixture_start_cleanup (f);
    voice_fixture_complete_channel (f, token, TRUE);
}

gboolean
voice_fixture_channel_pending (VoiceFixture *f, MMVoiceAudioToken token)
{
    InCallEventContext *ctx = peek_in_call_event_context (f->voice);
    return voice_audio_channel_matches (f->voice, ctx, token) && ctx->setup_cancellable != NULL;
}

static void
fixture_hangup_ready (MMBaseCall *call, GAsyncResult *res, gboolean *done)
{
    g_autoptr(GError) error = NULL;
    g_assert_false (MM_BASE_CALL_GET_CLASS (call)->hangup_finish (call, res, &error));
    g_assert_error (error, G_IO_ERROR, G_IO_ERROR_FAILED);
    *done = TRUE;
}

void
voice_fixture_assert_native_hangup (VoiceFixture *f, MMBaseCall *call, guint8 call_id)
{
    gboolean done = FALSE;
    g_assert_true (MM_IS_CALL_QMI (call));
    mm_base_call_set_index (call, call_id);
    f->end_call_count = 0;
    MM_BASE_CALL_GET_CLASS (call)->hangup (call, (GAsyncReadyCallback) fixture_hangup_ready, &done);
    while (!done)
        g_main_context_iteration (NULL, TRUE);
    g_assert_cmpuint (f->end_call_count, ==, 1);
    g_assert_cmpuint (f->end_call_id, ==, call_id);
}

void
voice_fixture_assert_exhaustion (VoiceFixture *f)
{
    InCallEventContext *ctx = get_in_call_event_context (f->voice);
    MMVoiceAudioToken token;

    ctx->channel_operation = G_MAXUINT64;
    token = mm_iface_modem_voice_audio_begin_channel (f->voice);
    g_assert_cmpuint (token.operation, ==, 0);
    g_assert_false (ctx->accepting_results);
    g_assert_cmpuint (ctx->channel_operation, ==, G_MAXUINT64);
    token = mm_iface_modem_voice_audio_begin_configuration (f->voice);
    g_assert_cmpuint (token.operation, ==, 0);
    g_assert_null (ctx->configured_audio_format);
}
