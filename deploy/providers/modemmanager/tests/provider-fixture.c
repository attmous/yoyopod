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
#include "mm-serial-parsers.h"
#include <pty.h>
#include <termios.h>
#include <fcntl.h>
#include <unistd.h>
#include <errno.h>

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
    gboolean qmi_missing;
    GHashTable *at_counts;
    GHashTable *at_errors;
    gchar *readback;
    gchar *hold_command;
    GTask *held_at;
    gboolean lifecycle_done;
    gboolean lifecycle_success;
    GError *lifecycle_error;
    MMPortSerialAt *pty_port;
    int pty_master;
    gboolean blocker_done;
    gint64 channel_dispatch_time;
    MMBaseCall *publication_call; /* owned by owned_calls */
    gulong publication_notify;
    guint publication_invalidations;
};

typedef struct {
    MMVoiceAudioToken token;
    gboolean cleanup;
    gboolean done;
    GTask *transport;
    GCancellable *cancellable;
    gboolean hold_ready;
    GAsyncResult *ready;
} FixtureChannel;

static void fixture_return_at (GTask *task);
void __real_mm_base_modem_at_command_full (MMBaseModem *, MMIfacePortAt *, const gchar *, guint, gboolean, gboolean, GCancellable *, GAsyncReadyCallback, gpointer);
const gchar *__real_mm_base_modem_at_command_full_finish (MMBaseModem *, GAsyncResult *, GError **);
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
    g_assert_null (channel->ready);
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
static void
fixture_at (MMBaseModem *self, const gchar *command,
            guint timeout, gboolean cached, GCancellable *cancellable,
            GAsyncReadyCallback callback, gpointer user_data)
{
    VoiceFixture *f = g_object_get_data (G_OBJECT (self), "voice-fixture");
    GTask *task;
    const gchar *reply = "";
    guint i;

    g_assert_nonnull (f);
    g_assert_cmpuint (timeout, ==, 3);
    if (!g_strcmp0 (command, "+CPCMREG=1") || !g_strcmp0 (command, "+CPCMREG=0"))
        f->channel_dispatch_time = g_get_monotonic_time ();
    g_hash_table_replace (f->at_counts, g_strdup (command),
                          GUINT_TO_POINTER (GPOINTER_TO_UINT (g_hash_table_lookup (f->at_counts, command)) + 1));
    if (f->pty_port && (!g_strcmp0 (command, "+CPCMREG=1") || !g_strcmp0 (command, "+CPCMREG=0"))) {
        g_assert_false (cached);
        __real_mm_base_modem_at_command_full (self, MM_IFACE_PORT_AT (f->pty_port), command,
                                             timeout, cached, FALSE, cancellable, callback, user_data);
        return;
    }
    task = g_task_new (self, cancellable, callback, user_data);
    g_object_set_data (G_OBJECT (task), "fixture-at", GINT_TO_POINTER (1));
    fixture_track_transport (f, task);
    if (!g_strcmp0 (command, "+CPCMREG=1") || !g_strcmp0 (command, "+CPCMREG=0")) {
        gboolean cleanup = !g_strcmp0 (command, "+CPCMREG=0");
        g_assert_false (cached);
        for (i = 0; i < f->channels->len; i++) {
            FixtureChannel *channel = g_ptr_array_index (f->channels, i);
            if (!channel->done && !channel->ready && !channel->transport && channel->cleanup == cleanup) {
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
    else if (!g_strcmp0 (command, "+CPCMFRM?"))
        reply = f->readback;
    else if (g_strcmp0 (command, "+CPCMFRM=1") && g_strcmp0 (command, "+CLCC=1") && g_strcmp0 (command, "+CLCC=0"))
        g_assert_not_reached ();
    g_assert_cmpint (cached, ==, (!g_strcmp0 (command, "+CLCC=?") ||
                                !g_strcmp0 (command, "+CPCMREG=?") ||
                                !g_strcmp0 (command, "+CPCMFRM=?")));
    if (g_hash_table_contains (f->at_errors, command)) {
        GError *error = g_error_copy (g_hash_table_lookup (f->at_errors, command));
        g_hash_table_remove (f->at_errors, command);
        g_task_return_error (task, error);
        g_object_unref (task);
        return;
    }
    g_task_set_task_data (task, g_strdup (reply), g_free);
    if (!g_strcmp0 (command, f->hold_command)) {
        g_assert_null (f->held_at);
        f->held_at = task;
        g_clear_pointer (&f->hold_command, g_free);
        return;
    }
    fixture_return_at (task);
}

static void
fixture_return_at (GTask *task)
{
    g_task_return_boolean (task, TRUE);
    g_object_unref (task);
}

void
__wrap_mm_base_modem_at_command (MMBaseModem *self, const gchar *command, guint timeout,
                                gboolean cached, GAsyncReadyCallback callback, gpointer user_data)
{
    fixture_at (self, command, timeout, cached, NULL, callback, user_data);
}

void
__wrap_mm_base_modem_at_command_full (MMBaseModem *self, MMIfacePortAt *port,
                                     const gchar *command, guint timeout, gboolean cached,
                                     gboolean raw, GCancellable *cancellable,
                                     GAsyncReadyCallback callback, gpointer user_data)
{
    g_assert_false (raw);
    fixture_at (self, command, timeout, cached, cancellable, callback, user_data);
}

const gchar *
__wrap_mm_base_modem_at_command_finish (MMBaseModem *self, GAsyncResult *res, GError **error)
{
    g_assert_true (g_task_is_valid (res, self));
    if (!g_object_get_data (G_OBJECT (res), "fixture-at"))
        return __real_mm_base_modem_at_command_full_finish (self, res, error);
    if (!g_task_propagate_boolean (G_TASK (res), error))
        return NULL;
    return g_task_get_task_data (G_TASK (res));
}

const gchar *
__wrap_mm_base_modem_at_command_full_finish (MMBaseModem *self, GAsyncResult *res, GError **error)
{
    return __wrap_mm_base_modem_at_command_finish (self, res, error);
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
    return f->qmi_missing ? NULL : QMI_CLIENT (f->qmi_client);
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
voice_fixture_new_uninitialized (void)
{
    VoiceFixture *f = g_new0 (VoiceFixture, 1);
    GError *error = NULL;
    const gchar *drivers[] = { "fixture", NULL };
    GDBusConnectionFlags flags = G_DBUS_CONNECTION_FLAGS_AUTHENTICATION_CLIENT |
                                 G_DBUS_CONNECTION_FLAGS_MESSAGE_BUS_CONNECTION;

    f->at_counts = g_hash_table_new_full (g_str_hash, g_str_equal, g_free, NULL);
    f->at_errors = g_hash_table_new_full (g_str_hash, g_str_equal, g_free, (GDestroyNotify) g_error_free);
    f->readback = g_strdup ("+CPCMFRM: 1");
    f->pty_master = -1;
    f->bus = g_test_dbus_new (G_TEST_DBUS_NONE);
    g_test_dbus_up (f->bus);
    f->server = g_dbus_connection_new_for_address_sync (g_test_dbus_get_bus_address (f->bus), flags, NULL, NULL, &error);
    g_assert_no_error (error);
    f->client = g_dbus_connection_new_for_address_sync (g_test_dbus_get_bus_address (f->bus), flags, NULL, NULL, &error);
    g_assert_no_error (error);
    f->voice = MM_IFACE_MODEM_VOICE (mm_broadband_modem_qmi_simtech_new ("fixture", "/fixture", drivers, "simtech", 0, 0));
    g_object_set (f->voice, MM_BASE_MODEM_CONNECTION, f->server,
                  NULL);
    f->channels = g_ptr_array_new_with_free_func ((GDestroyNotify) fixture_channel_free);
    g_object_set_data (G_OBJECT (f->voice), "voice-fixture", f);
    fixture_grab_port (f, "tty", "fixture-at", MM_PORT_TYPE_AT);
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
    f->owned_calls = g_ptr_array_new_with_free_func (g_object_unref);
    return f;
}

VoiceFixture *
voice_fixture_new (void)
{
    VoiceFixture *f = voice_fixture_new_uninitialized ();
    gboolean supported = FALSE;
    f->calls = mm_call_list_new (MM_BASE_MODEM (f->voice));
    g_object_set (f->voice, MM_IFACE_MODEM_VOICE_CALL_LIST, f->calls, NULL);
    MM_IFACE_MODEM_VOICE_GET_IFACE (f->voice)->check_support (
        f->voice, (GAsyncReadyCallback) fixture_support_ready, &supported);
    while (!supported)
        g_main_context_iteration (NULL, TRUE);
    return f;
}

void
voice_fixture_free (VoiceFixture *f)
{
    guint i;
    gpointer weak_voice = f->voice;
    if (f->publication_notify)
        g_signal_handler_disconnect (f->publication_call, f->publication_notify);
    g_assert_null (f->held_at);
    mm_iface_modem_voice_shutdown (f->voice);
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
    g_clear_object (&f->pty_port);
    if (f->pty_master >= 0)
        close (f->pty_master);
    g_hash_table_unref (f->at_counts);
    g_hash_table_unref (f->at_errors);
    g_free (f->readback);
    g_free (f->hold_command);
    g_clear_error (&f->lifecycle_error);
    g_free (f->last_port);
    g_free (f);
}

MMIfaceModemVoice *voice_fixture_voice (VoiceFixture *f) { return f->voice; }
MMPort *voice_fixture_audio_port (VoiceFixture *f) { return f->port; }

static MMBaseCall *
add_call (VoiceFixture *f, MMBaseCall *call)
{
    MMCallList *current = NULL;
    g_object_get (f->voice, MM_IFACE_MODEM_VOICE_CALL_LIST, &current, NULL);
    g_assert_nonnull (current);
    g_assert_true (f->calls == current);
    g_object_unref (current);
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

void
voice_fixture_assert_candidate_format (VoiceFixture *f, MMBaseCall *call)
{
    g_autoptr(GVariant) value = read_property (f, call, "AudioFormat");
    const gchar *encoding = NULL, *resolution = NULL;
    guint32 rate = 0;
    g_assert_true (g_variant_is_of_type (value, G_VARIANT_TYPE_VARDICT));
    g_assert_cmpuint (g_variant_n_children (value), ==, 3);
    g_assert_true (g_variant_lookup (value, "encoding", "&s", &encoding));
    g_assert_true (g_variant_lookup (value, "resolution", "&s", &resolution));
    g_assert_true (g_variant_lookup (value, "rate", "u", &rate));
    g_assert_cmpstr (encoding, ==, "pcm");
    g_assert_cmpstr (resolution, ==, "s16le");
    g_assert_cmpuint (rate, ==, 16000);
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
voice_fixture_publish_active_rate (VoiceFixture *f, guint rate)
{
    MMVoiceAudioToken token = mm_iface_modem_voice_audio_begin_channel (f->voice);
    MMCallAudioFormat *format = mm_call_audio_format_new ();
    mm_call_audio_format_set_encoding (format, "pcm");
    mm_call_audio_format_set_resolution (format, "s16le");
    mm_call_audio_format_set_rate (format, rate);
    g_assert_true (mm_iface_modem_voice_audio_commit_channel (f->voice, token, f->port, format));
    g_object_unref (format);
}

void
voice_fixture_publish_active (VoiceFixture *f)
{
    voice_fixture_publish_active_rate (f, 16000);
}

static void
fixture_setup_ready (MMIfaceModemVoice *self, GAsyncResult *res, FixtureChannel *channel)
{
    if (channel->hold_ready) {
        g_assert_null (channel->ready);
        channel->ready = g_object_ref (res);
        return;
    }
    MMVoiceAudioToken *token = g_new (MMVoiceAudioToken, 1);
    *token = channel->token;
    in_call_setup_ready (self, res, token);
    channel->done = TRUE;
}

static void
fixture_cleanup_ready (MMIfaceModemVoice *self, GAsyncResult *res, FixtureChannel *channel)
{
    if (channel->hold_ready) {
        g_assert_null (channel->ready);
        channel->ready = g_object_ref (res);
        return;
    }
    MMVoiceAudioToken *token = g_new (MMVoiceAudioToken, 1);
    *token = channel->token;
    in_call_cleanup_ready (self, res, token);
    channel->done = TRUE;
}

static MMVoiceAudioToken
fixture_start_channel (VoiceFixture *f, gboolean cleanup, gboolean wait)
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
    if (!wait)
        return channel->token;
    while (!channel->transport && !channel->done)
        g_main_context_iteration (NULL, TRUE);
    g_assert_nonnull (channel->transport);
    return channel->token;
}

MMVoiceAudioToken
voice_fixture_start_channel (VoiceFixture *f)
{
    return fixture_start_channel (f, FALSE, TRUE);
}

MMVoiceAudioToken
voice_fixture_start_cleanup (VoiceFixture *f)
{
    return fixture_start_channel (f, TRUE, TRUE);
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
            while (!channel->done && !channel->ready)
                g_main_context_iteration (NULL, TRUE);
            return;
        }
    }
    g_assert_not_reached ();
}

static FixtureChannel *
fixture_find_channel (VoiceFixture *f, MMVoiceAudioToken token)
{
    guint i;
    for (i = 0; i < f->channels->len; i++) {
        FixtureChannel *channel = g_ptr_array_index (f->channels, i);
        if (channel->token.generation == token.generation && channel->token.operation == token.operation)
            return channel;
    }
    g_assert_not_reached ();
}

void
voice_fixture_hold_channel_ready (VoiceFixture *f, MMVoiceAudioToken token)
{
    fixture_find_channel (f, token)->hold_ready = TRUE;
}

void
voice_fixture_deliver_channel_ready (VoiceFixture *f, MMVoiceAudioToken token)
{
    FixtureChannel *channel = fixture_find_channel (f, token);
    g_autoptr(GAsyncResult) ready = g_steal_pointer (&channel->ready);
    g_assert_nonnull (ready);
    channel->hold_ready = FALSE;
    if (channel->cleanup)
        fixture_cleanup_ready (f->voice, ready, channel);
    else
        fixture_setup_ready (f->voice, ready, channel);
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

/* Task3 integration uses public lifecycle entry/finish pairs, never vfunc replacements. */
static void
fixture_initialize_ready (MMIfaceModemVoice *self, GAsyncResult *res, VoiceFixture *f)
{
    MMCallList *list = NULL;
    f->lifecycle_success = mm_iface_modem_voice_initialize_finish (self, res, &f->lifecycle_error);
    g_object_get (self, MM_IFACE_MODEM_VOICE_CALL_LIST, &list, NULL);
    /* Always bind the current production list, including NULL on failure.
     * Never retain a pre-initialization list as a fallback. */
    g_clear_object (&f->calls);
    f->calls = list;
    if (f->lifecycle_success)
        g_assert_nonnull (f->calls);
    f->lifecycle_done = TRUE;
}

static void
fixture_enable_ready (MMIfaceModemVoice *self, GAsyncResult *res, VoiceFixture *f)
{
    f->lifecycle_success = mm_iface_modem_voice_enable_finish (self, res, &f->lifecycle_error);
    f->qmi_missing = FALSE;
    f->lifecycle_done = TRUE;
}

static void
fixture_disable_ready (MMIfaceModemVoice *self, GAsyncResult *res, VoiceFixture *f)
{
    f->lifecycle_success = mm_iface_modem_voice_disable_finish (self, res, &f->lifecycle_error);
    f->lifecycle_done = TRUE;
}

void
voice_fixture_begin_initialize (VoiceFixture *f)
{
    f->lifecycle_done = FALSE;
    g_clear_error (&f->lifecycle_error);
    mm_iface_modem_voice_initialize (f->voice, NULL,
                                    (GAsyncReadyCallback) fixture_initialize_ready, f);
}

static void
fixture_wait_lifecycle_done (VoiceFixture *f)
{
    while (!f->lifecycle_done)
        g_main_context_iteration (NULL, TRUE);
}

void
voice_fixture_wait_lifecycle (VoiceFixture *f)
{
    fixture_wait_lifecycle_done (f);
    g_assert_no_error (f->lifecycle_error);
    g_assert_true (f->lifecycle_success);
}

void
voice_fixture_wait_lifecycle_failure (VoiceFixture *f, GQuark domain, gint code)
{
    fixture_wait_lifecycle_done (f);
    g_assert_false (f->lifecycle_success);
    g_assert_error (f->lifecycle_error, domain, code);
}

void
voice_fixture_initialize (VoiceFixture *f)
{
    voice_fixture_begin_initialize (f);
    voice_fixture_wait_lifecycle (f);
}

void
voice_fixture_begin_enable (VoiceFixture *f)
{
    f->qmi_missing = TRUE;
    f->lifecycle_done = FALSE;
    g_clear_error (&f->lifecycle_error);
    mm_iface_modem_voice_enable (f->voice, NULL, (GAsyncReadyCallback) fixture_enable_ready, f);
}

void
voice_fixture_enable (VoiceFixture *f)
{
    voice_fixture_begin_enable (f);
    voice_fixture_wait_lifecycle (f);
}

void
voice_fixture_disable (VoiceFixture *f)
{
    f->qmi_missing = TRUE;
    f->lifecycle_done = FALSE;
    g_clear_error (&f->lifecycle_error);
    mm_iface_modem_voice_disable (f->voice, (GAsyncReadyCallback) fixture_disable_ready, f);
    voice_fixture_wait_lifecycle (f);
    f->qmi_missing = FALSE;
}

void
voice_fixture_set_readback (VoiceFixture *f, const gchar *reply)
{
    g_free (f->readback);
    f->readback = g_strdup (reply);
}

guint
voice_fixture_at_count (VoiceFixture *f, const gchar *command)
{
    return GPOINTER_TO_UINT (g_hash_table_lookup (f->at_counts, command));
}

void
voice_fixture_hold_at (VoiceFixture *f, const gchar *command)
{
    g_free (f->hold_command);
    f->hold_command = g_strdup (command);
}

void
voice_fixture_wait_held_at (VoiceFixture *f)
{
    while (!f->held_at && !f->lifecycle_done)
        g_main_context_iteration (NULL, TRUE);
    g_assert_nonnull (f->held_at);
}

void
voice_fixture_release_at (VoiceFixture *f, gboolean success)
{
    GTask *task = g_steal_pointer (&f->held_at);
    g_assert_nonnull (task);
    if (success)
        fixture_return_at (task);
    else {
        g_task_return_new_error (task, G_IO_ERROR, G_IO_ERROR_FAILED, "fixture AT ERROR");
        g_object_unref (task);
    }
}

static gboolean
fixture_stop_wait (gpointer data)
{
    *((gboolean *) data) = TRUE;
    return G_SOURCE_REMOVE;
}

void
voice_fixture_run_timers (VoiceFixture *f)
{
    gboolean done = FALSE;
    /* Cross the actual plugin's 100 ms timer, without replacing that timer. */
    g_timeout_add (200, fixture_stop_wait, &done);
    while (!done)
        g_main_context_iteration (NULL, TRUE);
}

MMVoiceAudioToken
voice_fixture_schedule_channel (VoiceFixture *f, gboolean cleanup)
{
    return fixture_start_channel (f, cleanup, FALSE);
}

static void
fixture_blocker_ready (MMBaseModem *self, GAsyncResult *res, VoiceFixture *f)
{
    g_autoptr(GError) error = NULL;
    g_assert_nonnull (__real_mm_base_modem_at_command_full_finish (self, res, &error));
    g_assert_no_error (error);
    f->blocker_done = TRUE;
}

static gchar *
fixture_read_peer (VoiceFixture *f)
{
    GString *bytes = g_string_new (NULL);
    gchar buf[256];
    ssize_t n;
    while ((n = read (f->pty_master, buf, sizeof (buf))) > 0)
        g_string_append_len (bytes, buf, n);
    g_assert_true (n < 0 && (errno == EAGAIN || errno == EWOULDBLOCK));
    return g_string_free (bytes, FALSE);
}

void
voice_fixture_assert_real_queue_cancellation (VoiceFixture *f)
{
    int slave;
    struct termios settings;
    g_autoptr(GError) error = NULL;
    g_autofree gchar *first = NULL;
    g_autofree gchar *after = NULL;
    guint i;
    MMBaseCall *call = voice_fixture_incoming (f, "+49123456789");
    MMBaseCall *during;

    voice_fixture_publish_active (f);
    g_assert_true (mm_port_get_connected (f->port));

    /* Adapt upstream test-qcdm-serial-port's PTY/fd setup for the real AT class.
     * This port is only an off-device transport peer; the real modem remains
     * the source object of every AT task and every plugin callback. */
    g_assert_cmpint (openpty (&f->pty_master, &slave, NULL, NULL, NULL), ==, 0);
    g_assert_cmpint (tcgetattr (slave, &settings), ==, 0);
    cfmakeraw (&settings);
    g_assert_cmpint (tcsetattr (slave, TCSANOW, &settings), ==, 0);
    g_assert_cmpint (fcntl (f->pty_master, F_SETFL, O_NONBLOCK), ==, 0);
    f->pty_port = g_object_new (MM_TYPE_PORT_SERIAL_AT,
                               MM_PORT_DEVICE, "fixture-pty",
                               MM_PORT_SUBSYS, MM_PORT_SUBSYS_TTY,
                               MM_PORT_TYPE, MM_PORT_TYPE_AT,
                               MM_PORT_SERIAL_FD, slave,
                               MM_PORT_SERIAL_SEND_DELAY, (guint64) 0,
                               MM_PORT_SERIAL_AT_INIT_SEQUENCE_ENABLED, FALSE, NULL);
    mm_port_serial_at_set_response_parser (f->pty_port, mm_serial_parser_v1_parse,
                                           mm_serial_parser_v1_new (), mm_serial_parser_v1_destroy);
    g_assert_true (mm_port_serial_open (MM_PORT_SERIAL (f->pty_port), &error));
    g_assert_no_error (error);

    /* A genuine uncancelled in-flight fixed command occupies the serial queue.
     * Its response is withheld by the PTY peer, not by a transport model. */
    __real_mm_base_modem_at_command_full (MM_BASE_MODEM (f->voice), MM_IFACE_PORT_AT (f->pty_port),
                                         "+CPCMREG=1", 3, FALSE, FALSE, NULL,
                                         (GAsyncReadyCallback) fixture_blocker_ready, f);
    voice_fixture_run_timers (f);
    first = fixture_read_peer (f);
    g_assert_cmpstr (first, ==, "AT+CPCMREG=1\r");
    voice_fixture_schedule_channel (f, TRUE);
    voice_fixture_run_timers (f);
    g_assert_cmpuint (voice_fixture_at_count (f, "+CPCMREG=0"), ==, 1);
    voice_fixture_schedule_channel (f, FALSE);
    voice_fixture_run_timers (f);
    g_assert_cmpuint (voice_fixture_at_count (f, "+CPCMREG=1"), ==, 0);
    g_assert_cmpstr (voice_fixture_read_port (f, call), ==, "");
    g_assert_true (mm_port_get_connected (f->port));
    during = voice_fixture_outgoing (f, "+49123456780");
    g_assert_cmpstr (voice_fixture_read_port (f, during), ==, "");
    voice_fixture_assert_candidate_format (f, during);
    g_assert_cmpint (write (f->pty_master, "\r\nOK\r\n", 6), ==, 6);
    voice_fixture_run_timers (f);
    g_assert_true (f->blocker_done);
    after = fixture_read_peer (f);
    /* Already-submitted cleanup may emit. No newer activation/commit may
     * occur until this actual physical cleanup ACK has been consumed. */
    g_assert_cmpstr (after, ==, "AT+CPCMREG=0\r");
    g_assert_cmpuint (voice_fixture_at_count (f, "+CPCMREG=1"), ==, 0);
    g_assert_cmpstr (voice_fixture_read_port (f, call), ==, "");
    g_assert_true (mm_port_get_connected (f->port));
    g_assert_cmpint (write (f->pty_master, "\r\nOK\r\n", 6), ==, 6);
    voice_fixture_run_timers (f);
    g_clear_pointer (&after, g_free);
    after = fixture_read_peer (f);
    g_assert_cmpstr (after, ==, "AT+CPCMREG=1\r");
    g_assert_cmpstr (voice_fixture_read_port (f, call), ==, "");
    g_assert_true (mm_port_get_connected (f->port));
    g_assert_cmpint (write (f->pty_master, "\r\nOK\r\n", 6), ==, 6);
    voice_fixture_run_timers (f);
    g_assert_cmpstr (voice_fixture_read_port (f, call), ==, "fixture-audio");
    g_assert_cmpstr (voice_fixture_read_port (f, during), ==, "fixture-audio");
    voice_fixture_assert_candidate_format (f, call);
    g_assert_true (mm_port_get_connected (f->port));
    for (i = 0; i < f->channels->len; i++)
        g_assert_true (((FixtureChannel *) g_ptr_array_index (f->channels, i))->done);
    mm_port_serial_close (MM_PORT_SERIAL (f->pty_port));
}

void
voice_fixture_fail_next_at (VoiceFixture *f, const gchar *command, GQuark domain, gint code)
{
    g_assert_true (!g_strcmp0 (command, "+CPCMREG=?") || !g_strcmp0 (command, "+CPCMFRM=?") ||
                   !g_strcmp0 (command, "+CPCMFRM=1") || !g_strcmp0 (command, "+CPCMFRM?"));
    g_assert_false (g_hash_table_contains (f->at_errors, command));
    g_hash_table_insert (f->at_errors, g_strdup (command),
                         g_error_new_literal (domain, code, "fixture fixed AT transport failure"));
}

void
voice_fixture_cancel_held_at (VoiceFixture *f)
{
    GCancellable *cancellable;
    g_assert_nonnull (f->held_at);
    /* Cancel the actual producer-supplied transport cancellation object. */
    cancellable = g_task_get_cancellable (f->held_at);
    g_assert_nonnull (cancellable);
    g_cancellable_cancel (cancellable);
}

MMVoiceAudioToken
voice_fixture_configuration_token (VoiceFixture *f)
{
    InCallEventContext *ctx = peek_in_call_event_context (f->voice);
    MMVoiceAudioToken token = { 0, 0 };
    g_assert_nonnull (ctx);
    token.generation = ctx->generation;
    token.operation = ctx->configuration_operation;
    return token;
}

void
voice_fixture_release_at_error (VoiceFixture *f, GQuark domain, gint code)
{
    GTask *task = g_steal_pointer (&f->held_at);
    g_assert_nonnull (task);
    g_task_return_new_error (task, domain, code, "fixture held AT transport failure");
    g_object_unref (task);
}

static void
fixture_publication_notified (MMBaseCall *call, GParamSpec *pspec, VoiceFixture *f)
{
    GVariant *format = mm_gdbus_call_get_audio_format (MM_GDBUS_CALL (call));
    InCallEventContext *ctx;
    guint rate = 0;

    if (f->publication_invalidations || !format ||
        !g_variant_lookup (format, "rate", "u", &rate) || rate != 16000)
        return;
    /* This runs synchronously FROM the real live Call property publication,
     * after publish_configured consumed pending, before it returns. */
    ctx = peek_in_call_event_context (f->voice);
    g_assert_nonnull (ctx);
    g_assert_false (ctx->configuration_pending);
    f->publication_invalidations++;
    mm_base_modem_set_reprobe (MM_BASE_MODEM (f->voice), TRUE);
}

void
voice_fixture_invalidate_on_publication (VoiceFixture *f, MMBaseCall *call)
{
    g_assert_cmpuint (f->publication_notify, ==, 0);
    f->publication_call = call;
    f->publication_notify = g_signal_connect (call, "notify::audio-format",
                                               G_CALLBACK (fixture_publication_notified), f);
}

guint
voice_fixture_publication_invalidations (VoiceFixture *f)
{
    return f->publication_invalidations;
}

/* Mutation occurs from the real generated property notify, during the helper's
 * snapshot walk. A fresh commit must survive the stale walk's remaining items. */
typedef struct {
    VoiceFixture *fixture;
    gboolean fired;
} SuspensionNotify;

static void
fixture_suspension_notified (MMBaseCall *call, GParamSpec *pspec, SuspensionNotify *notify)
{
    VoiceFixture *f = notify->fixture;
    g_autoptr(GError) error = NULL;
    g_autofree gchar *path = NULL;
    if (notify->fired || *mm_gdbus_call_get_audio_port (MM_GDBUS_CALL (call)))
        return;
    notify->fired = TRUE;
    g_assert_true (mm_port_get_connected (f->port));
    /* Real removal mutates the underlying GList, not a copied fixture list. */
    path = g_strdup (mm_base_call_get_path (call));
    g_assert_true (mm_call_list_delete_call (f->calls, path, &error));
    g_assert_no_error (error);
    voice_fixture_publish_active_rate (f, 8000);
}

void
voice_fixture_assert_reentrant_suspension (VoiceFixture *f)
{
    MMBaseCall *first = voice_fixture_incoming (f, "+49123456789");
    MMBaseCall *second = voice_fixture_outgoing (f, "+49123456780");
    SuspensionNotify notify = { f, FALSE };
    gulong first_id, second_id;
    guint i;
    voice_fixture_publish_active (f);
    first_id = g_signal_connect (first, "notify::audio-port", G_CALLBACK (fixture_suspension_notified), &notify);
    second_id = g_signal_connect (second, "notify::audio-port", G_CALLBACK (fixture_suspension_notified), &notify);
    voice_fixture_schedule_channel (f, TRUE);
    voice_fixture_run_timers (f);
    g_assert_true (notify.fired);
    g_assert_cmpuint (voice_fixture_at_count (f, "+CPCMREG=0"), ==, 0);
    g_assert_true (mm_port_get_connected (f->port));
    g_assert_cmpuint (mm_call_list_get_count (f->calls), ==, 1);
    /* Whichever Call remains is the fresh commit's actual live target. */
    for (i = 0; i < f->owned_calls->len; i++) {
        MMBaseCall *call = g_ptr_array_index (f->owned_calls, i);
        if (mm_call_list_get_call (f->calls, mm_base_call_get_path (call))) {
            g_assert_cmpstr (voice_fixture_read_port (f, call), ==, "fixture-audio");
            g_assert_cmpuint (voice_fixture_read_format (f, call), ==, 8000);
        }
    }
    g_signal_handler_disconnect (first, first_id);
    g_signal_handler_disconnect (second, second_id);
}

void
voice_fixture_assert_replacement_delay (VoiceFixture *f)
{
    gboolean done = FALSE;
    gint64 replacement;
    MMVoiceAudioToken current;
    voice_fixture_schedule_channel (f, TRUE);
    g_timeout_add (50, fixture_stop_wait, &done);
    while (!done)
        g_main_context_iteration (NULL, TRUE);
    g_assert_cmpuint (voice_fixture_at_count (f, "+CPCMREG=0"), ==, 0);
    replacement = g_get_monotonic_time ();
    current = voice_fixture_schedule_channel (f, FALSE);
    done = FALSE;
    g_timeout_add (75, fixture_stop_wait, &done);
    while (!done)
        g_main_context_iteration (NULL, TRUE);
    if (g_get_monotonic_time () - replacement < 100000)
        g_assert_cmpuint (voice_fixture_at_count (f, "+CPCMREG=1"), ==, 0);
    voice_fixture_run_timers (f);
    g_assert_cmpuint (voice_fixture_at_count (f, "+CPCMREG=0"), ==, 0);
    g_assert_cmpuint (voice_fixture_at_count (f, "+CPCMREG=1"), ==, 1);
    /* Actual monotonic timestamp at the fixed transport entry, never a fake
     * clock or modeled timer. Host lateness cannot produce a false early hit. */
    g_assert_cmpint (f->channel_dispatch_time - replacement, >=, 100000);
    voice_fixture_complete_channel (f, current, TRUE);
}

typedef struct {
    VoiceFixture *fixture;
    gboolean connected;
    gboolean fired;
} ConnectedNotify;

static void
fixture_connected_notified (MMPort *port, GParamSpec *pspec, ConnectedNotify *notify)
{
    VoiceFixture *f = notify->fixture;
    MMVoiceAudioToken token;
    g_autoptr(MMCallAudioFormat) format = NULL;
    if (notify->fired || mm_port_get_connected (port) != notify->connected)
        return;
    notify->fired = TRUE;
    /* Real notify::connected, inside audio ownership normalization. */
    mm_iface_modem_voice_audio_invalidate (f->voice);
    token = mm_iface_modem_voice_audio_begin_configuration (f->voice);
    format = mm_call_audio_format_new ();
    mm_call_audio_format_set_encoding (format, "pcm");
    mm_call_audio_format_set_resolution (format, "s16le");
    mm_call_audio_format_set_rate (format, 16000);
    g_assert_true (mm_iface_modem_voice_audio_publish_configured (f->voice, token, format));
    voice_fixture_publish_active_rate (f, 8000);
}

void
voice_fixture_assert_connected_reentrancy (VoiceFixture *f, gboolean terminal_old_port)
{
    MMBaseCall *live = voice_fixture_incoming (f, "+49123456789");
    ConnectedNotify notify = { f, !terminal_old_port, FALSE };
    MMVoiceAudioToken setup;
    g_autoptr(MMPort) owned = NULL;
    gulong handler;

    if (!terminal_old_port) {
        handler = g_signal_connect (f->port, "notify::connected", G_CALLBACK (fixture_connected_notified), &notify);
        setup = voice_fixture_start_channel (f);
        voice_fixture_complete_channel (f, setup, TRUE);
        g_signal_handler_disconnect (f->port, handler);
        g_assert_true (notify.fired);
        owned = mm_base_call_ref_audio_port (live);
        g_assert_true (owned == f->port);
    } else {
        MMBaseCall *terminal = voice_fixture_outgoing (f, "+49123456780");
        MMPort *old = g_object_new (MM_TYPE_PORT_SERIAL_AT,
            MM_PORT_DEVICE, "fixture-old-terminal", MM_PORT_SUBSYS, MM_PORT_SUBSYS_TTY,
            MM_PORT_TYPE, MM_PORT_TYPE_AT, NULL);
        gpointer weak_old = old;
        g_autoptr(MMCallAudioFormat) format = mm_call_audio_format_new ();
        mm_call_audio_format_set_rate (format, 8000);
        mm_base_call_change_audio_settings (terminal, old, format);
        mm_base_call_change_state (terminal, MM_CALL_STATE_TERMINATED, MM_CALL_STATE_REASON_TERMINATED);
        voice_fixture_publish_active (f);
        owned = mm_base_call_ref_audio_port (terminal);
        g_assert_true (owned == old && owned != f->port);
        g_object_add_weak_pointer (G_OBJECT (old), &weak_old);
        g_signal_connect (old, "notify::connected", G_CALLBACK (fixture_connected_notified), &notify);
        /* There is now no creator-owned ref. The getter must retain the actual
         * old port across clearing the terminal Call's only remaining owner. */
        g_object_unref (old);
        mm_iface_modem_voice_audio_invalidate (f->voice);
        g_assert_true (notify.fired);
        g_assert_false (mm_port_get_connected (owned));
        g_assert_null (mm_base_call_ref_audio_port (terminal));
        g_assert_cmpstr (voice_fixture_read_port (f, terminal), ==, "");
        g_assert_cmpuint (voice_fixture_read_format (f, terminal), ==, 0);
        g_assert_nonnull (weak_old);
        g_clear_object (&owned);
        g_assert_null (weak_old);
    }
    g_assert_true (mm_port_get_connected (f->port));
    g_assert_cmpstr (voice_fixture_read_port (f, live), ==, "fixture-audio");
    g_assert_cmpuint (voice_fixture_read_format (f, live), ==, 8000);
    voice_fixture_cleanup_last_channel (f);
}
