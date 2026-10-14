/* SPDX-License-Identifier: GPL-2.0-or-later */
#include <config.h>
/* Compile the real implementation once in this translation unit so regressions
 * can reach private constructors and event callbacks without an installed API.
 * Meson excludes this file from the remaining daemon sources in this target. */
#include "../mm-iface-modem-voice.c"
#include "mm-broadband-modem.h"
#include "provider-fixture.h"

struct _VoiceFixture {
    GTestDBus *bus;
    GDBusConnection *server;
    GDBusConnection *client;
    MMIfaceModemVoice *voice;
    MMCallList *calls;
    MMPort *port;
    GPtrArray *owned_calls;
    gchar *last_port;
};

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
    const gchar *drivers[] = { "fixture", NULL };
    GDBusConnectionFlags flags = G_DBUS_CONNECTION_FLAGS_AUTHENTICATION_CLIENT |
                                 G_DBUS_CONNECTION_FLAGS_MESSAGE_BUS_CONNECTION;

    f->bus = g_test_dbus_new (G_TEST_DBUS_NONE);
    g_test_dbus_up (f->bus);
    f->server = g_dbus_connection_new_for_address_sync (g_test_dbus_get_bus_address (f->bus), flags, NULL, NULL, &error);
    g_assert_no_error (error);
    f->client = g_dbus_connection_new_for_address_sync (g_test_dbus_get_bus_address (f->bus), flags, NULL, NULL, &error);
    g_assert_no_error (error);
    f->voice = MM_IFACE_MODEM_VOICE (mm_broadband_modem_new ("fixture", "/fixture", drivers, "generic", 0, 0));
    f->calls = mm_call_list_new (MM_BASE_MODEM (f->voice));
    g_object_set (f->voice, MM_BASE_MODEM_CONNECTION, f->server,
                  MM_IFACE_MODEM_VOICE_CALL_LIST, f->calls, NULL);
    f->port = g_object_new (MM_TYPE_PORT, MM_PORT_DEVICE, "fixture-audio",
                           MM_PORT_SUBSYS, MM_PORT_SUBSYS_TTY,
                           MM_PORT_TYPE, MM_PORT_TYPE_AUDIO, NULL);
    f->owned_calls = g_ptr_array_new_with_free_func (g_object_unref);
    return f;
}

void
voice_fixture_free (VoiceFixture *f)
{
    guint i;
    for (i = 0; i < f->owned_calls->len; i++)
        mm_base_call_unexport (g_ptr_array_index (f->owned_calls, i));
    g_object_set (f->voice, MM_IFACE_MODEM_VOICE_CALL_LIST, NULL,
                  MM_BASE_MODEM_CONNECTION, NULL, NULL);
    g_clear_object (&f->calls);
    g_ptr_array_unref (f->owned_calls);
    g_clear_object (&f->voice);
    g_clear_object (&f->port);
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
    InCallEventContext *ctx = get_in_call_event_context (f->voice);
    MMCallAudioFormat *format = mm_call_audio_format_new ();
    mm_call_audio_format_set_encoding (format, "pcm");
    mm_call_audio_format_set_resolution (format, "s16le");
    mm_call_audio_format_set_rate (format, 16000);
    g_set_object (&ctx->audio_port, f->port);
    g_set_object (&ctx->audio_format, format);
    ctx->in_call_state = TRUE;
    update_audio_settings_in_ongoing_calls (f->voice);
    g_object_unref (format);
}

static void
fixture_cleanup_ready (MMIfaceModemVoice *self, GAsyncResult *res, gboolean *done)
{
    in_call_cleanup_ready (self, res);
    *done = TRUE;
}

void
voice_fixture_cleanup_last_channel (VoiceFixture *f)
{
    /* Exercise the real generic cleanup task and its completion, not a model. */
    gboolean done = FALSE;
    in_call_cleanup (f->voice, NULL, (GAsyncReadyCallback) fixture_cleanup_ready, &done);
    while (!done)
        g_main_context_iteration (NULL, TRUE);
}
