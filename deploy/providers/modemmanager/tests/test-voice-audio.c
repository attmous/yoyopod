/* SPDX-License-Identifier: GPL-2.0-or-later */
#include <config.h>
#include "provider-fixture.h"
#include "mm-log.h"
#include "mm-port-serial.h"

static void
test_ongoing_update (void)
{
    VoiceFixture *f = voice_fixture_new ();
    MMBaseCall *ringing = voice_fixture_incoming (f, "+49123456789");
    MMBaseCall *unknown = voice_fixture_outgoing (f, "+49123456780");
    voice_fixture_publish_active_rate (f, 8000);
    g_assert_cmpuint (voice_fixture_read_format (f, ringing), ==, 8000);
    g_assert_cmpuint (voice_fixture_read_format (f, unknown), ==, 8000);
    g_assert_cmpstr (voice_fixture_read_port (f, ringing), ==, "fixture-audio");
    voice_fixture_free (f);
}

static void
test_terminal_update (void)
{
    VoiceFixture *f = voice_fixture_new ();
    MMBaseCall *call = voice_fixture_incoming (f, "+49123456789");
    guint terminal_rate = voice_fixture_read_format (f, call);
    mm_base_call_change_state (call, MM_CALL_STATE_TERMINATED, MM_CALL_STATE_REASON_TERMINATED);
    voice_fixture_publish_active_rate (f, 8000);
    g_assert_cmpuint (voice_fixture_read_format (f, call), ==, terminal_rate);
    g_assert_cmpstr (voice_fixture_read_port (f, call), ==, "");
    voice_fixture_free (f);
}

static void
test_cleanup_shared_port (void)
{
    VoiceFixture *f = voice_fixture_new ();
    MMBaseCall *first, *second;
    voice_fixture_publish_active (f);
    first = voice_fixture_incoming (f, "+49123456789");
    second = voice_fixture_outgoing (f, "+49123456780");
    g_assert_true (mm_port_get_connected (voice_fixture_audio_port (f)));
    voice_fixture_cleanup_last_channel (f);
    g_assert_false (mm_port_get_connected (voice_fixture_audio_port (f)));
    g_assert_cmpstr (voice_fixture_read_port (f, first), ==, "");
    g_assert_cmpstr (voice_fixture_read_port (f, second), ==, "");
    voice_fixture_free (f);
}

static MMCallAudioFormat *
synthetic_format (void)
{
    MMCallAudioFormat *format = mm_call_audio_format_new ();
    mm_call_audio_format_set_encoding (format, "pcm");
    mm_call_audio_format_set_resolution (format, "s16le");
    mm_call_audio_format_set_rate (format, 16000);
    return format;
}

static void
publish_synthetic_configuration (VoiceFixture *f)
{
    MMIfaceModemVoice *voice = voice_fixture_voice (f);
    MMVoiceAudioToken token = mm_iface_modem_voice_audio_begin_configuration (voice);
    g_autoptr(MMCallAudioFormat) format = synthetic_format ();
    g_assert_true (mm_iface_modem_voice_audio_publish_configured (voice, token, format));
}

static void
test_configured_first_and_subsequent_calls (void)
{
    VoiceFixture *f = voice_fixture_new ();
    MMIfaceModemVoice *voice = voice_fixture_voice (f);
    MMBaseCall *first, *outgoing, *second, *third;
    MMVoiceAudioToken channel;
    g_autoptr(MMCallAudioFormat) configured = NULL;

    /* This synthetic metadata is NOT evidence of modem framing qualification. */
    publish_synthetic_configuration (f);
    first = voice_fixture_incoming (f, "+49123456789");
    outgoing = voice_fixture_outgoing (f, "+49123456780");
    g_assert_cmpuint (voice_fixture_read_format (f, first), ==, 16000);
    g_assert_cmpuint (voice_fixture_read_format (f, outgoing), ==, 16000);
    g_assert_cmpint (mm_base_call_get_state (outgoing), ==, MM_CALL_STATE_UNKNOWN);
    g_assert_cmpstr (voice_fixture_read_port (f, first), ==, "");
    g_assert_cmpstr (voice_fixture_read_port (f, outgoing), ==, "");

    channel = voice_fixture_start_channel (f);
    voice_fixture_complete_channel (f, channel, TRUE);
    g_assert_cmpstr (voice_fixture_read_port (f, first), ==, "fixture-audio");
    voice_fixture_cleanup_last_channel (f);
    g_assert_false (mm_port_get_connected (voice_fixture_audio_port (f)));
    g_assert_cmpstr (voice_fixture_read_port (f, first), ==, "");
    g_assert_cmpstr (voice_fixture_read_port (f, outgoing), ==, "");
    g_assert_cmpuint (voice_fixture_read_format (f, first), ==, 16000);
    configured = mm_iface_modem_voice_audio_dup_configured (voice);
    g_assert_nonnull (configured);

    second = voice_fixture_incoming (f, "+49123456789");
    g_assert_cmpuint (voice_fixture_read_format (f, second), ==, 16000);
    g_assert_cmpstr (voice_fixture_read_port (f, second), ==, "");
    channel = voice_fixture_start_channel (f);
    voice_fixture_complete_channel (f, channel, TRUE);
    voice_fixture_cleanup_last_channel (f);
    third = voice_fixture_incoming (f, "+49123456789");
    g_assert_cmpuint (voice_fixture_read_format (f, third), ==, 16000);
    g_assert_cmpstr (voice_fixture_read_port (f, third), ==, "");
    voice_fixture_free (f);
}

static void
test_configuration_tokens_and_inflight_calls (void)
{
    VoiceFixture *f = voice_fixture_new ();
    MMIfaceModemVoice *voice = voice_fixture_voice (f);
    g_autoptr(MMCallAudioFormat) format = synthetic_format ();
    MMVoiceAudioToken old, current;
    MMBaseCall *call;

    old = mm_iface_modem_voice_audio_begin_configuration (voice);
    call = voice_fixture_incoming (f, "+49123456789");
    g_assert_cmpuint (voice_fixture_read_format (f, call), ==, 0);
    mm_iface_modem_voice_audio_invalidate (voice);
    current = mm_iface_modem_voice_audio_begin_configuration (voice);
    g_assert_false (mm_iface_modem_voice_audio_publish_configured (voice, old, format));
    g_assert_true (mm_iface_modem_voice_audio_publish_configured (voice, current, format));
    g_assert_false (mm_iface_modem_voice_audio_publish_configured (voice, current, format));
    g_assert_cmpuint (voice_fixture_read_format (f, call), ==, 16000);
    g_assert_cmpstr (voice_fixture_read_port (f, call), ==, "");
    old = mm_iface_modem_voice_audio_begin_configuration (voice);
    current = mm_iface_modem_voice_audio_begin_configuration (voice);
    g_assert_null (mm_iface_modem_voice_audio_dup_configured (voice));
    g_assert_cmpuint (voice_fixture_read_format (f, call), ==, 0);
    g_assert_false (mm_iface_modem_voice_audio_publish_configured (voice, old, format));
    g_assert_true (mm_iface_modem_voice_audio_publish_configured (voice, current, format));
    voice_fixture_free (f);
}

static void
test_stale_setup_preserves_new_task_and_port (void)
{
    VoiceFixture *f = voice_fixture_new ();
    MMIfaceModemVoice *voice = voice_fixture_voice (f);
    MMVoiceAudioToken old, current;
    MMBaseCall *call;

    publish_synthetic_configuration (f);
    call = voice_fixture_incoming (f, "+49123456789");
    old = voice_fixture_start_channel (f);
    mm_iface_modem_voice_audio_invalidate (voice);
    publish_synthetic_configuration (f);
    current = voice_fixture_start_channel (f);
    voice_fixture_complete_channel (f, old, TRUE);
    g_assert_true (voice_fixture_channel_pending (f, current));
    g_assert_cmpstr (voice_fixture_read_port (f, call), ==, "");
    voice_fixture_complete_channel (f, current, TRUE);
    g_assert_true (mm_port_get_connected (voice_fixture_audio_port (f)));
    g_assert_cmpstr (voice_fixture_read_port (f, call), ==, "fixture-audio");

    /* Reverse completion order: a stale setup must not disconnect the same
     * port object already committed by its replacement. */
    old = voice_fixture_start_channel (f);
    current = voice_fixture_start_channel (f);
    voice_fixture_complete_channel (f, current, TRUE);
    voice_fixture_complete_channel (f, old, TRUE);
    g_assert_true (mm_port_get_connected (voice_fixture_audio_port (f)));
    g_assert_cmpstr (voice_fixture_read_port (f, call), ==, "fixture-audio");
    voice_fixture_cleanup_last_channel (f);
    voice_fixture_free (f);
}

static void
test_stale_cleanup_preserves_new_channel (void)
{
    VoiceFixture *f = voice_fixture_new ();
    MMVoiceAudioToken setup, cleanup;
    MMBaseCall *call;
    publish_synthetic_configuration (f);
    call = voice_fixture_incoming (f, "+49123456789");
    setup = voice_fixture_start_channel (f);
    voice_fixture_complete_channel (f, setup, TRUE);
    cleanup = voice_fixture_start_cleanup (f);
    setup = voice_fixture_start_channel (f);
    voice_fixture_complete_channel (f, setup, TRUE);
    voice_fixture_complete_channel (f, cleanup, TRUE);
    g_assert_false (mm_iface_modem_voice_audio_clear_channel (voice_fixture_voice (f), cleanup));
    g_assert_true (mm_port_get_connected (voice_fixture_audio_port (f)));
    g_assert_cmpstr (voice_fixture_read_port (f, call), ==, "fixture-audio");
    g_assert_cmpuint (voice_fixture_read_format (f, call), ==, 16000);
    voice_fixture_cleanup_last_channel (f);
    voice_fixture_free (f);
}

static void
test_failed_activation_has_no_port (void)
{
    VoiceFixture *f = voice_fixture_new ();
    MMBaseCall *call;
    MMVoiceAudioToken setup;
    publish_synthetic_configuration (f);
    call = voice_fixture_incoming (f, "+49123456789");
    setup = voice_fixture_start_channel (f);
    voice_fixture_complete_channel (f, setup, FALSE);
    g_assert_cmpstr (voice_fixture_read_port (f, call), ==, "");
    g_assert_false (mm_port_get_connected (voice_fixture_audio_port (f)));
    g_assert_cmpuint (voice_fixture_read_format (f, call), ==, 16000);
    voice_fixture_free (f);
}

static void
test_invalidation_clears_terminal_and_blocks_results (void)
{
    VoiceFixture *f = voice_fixture_new ();
    MMIfaceModemVoice *voice = voice_fixture_voice (f);
    MMBaseCall *call;
    MMVoiceAudioToken setup, configuration;
    g_autoptr(MMCallAudioFormat) format = synthetic_format ();
    publish_synthetic_configuration (f);
    call = voice_fixture_incoming (f, "+49123456789");
    voice_fixture_publish_active (f);
    mm_base_call_change_state (call, MM_CALL_STATE_TERMINATED, MM_CALL_STATE_REASON_TERMINATED);
    setup = voice_fixture_start_channel (f);
    configuration = mm_iface_modem_voice_audio_begin_configuration (voice);
    mm_iface_modem_voice_shutdown (voice);
    g_assert_cmpuint (voice_fixture_read_format (f, call), ==, 0);
    g_assert_cmpstr (voice_fixture_read_port (f, call), ==, "");
    g_assert_false (mm_port_get_connected (voice_fixture_audio_port (f)));
    g_assert_false (mm_iface_modem_voice_audio_publish_configured (voice, configuration, format));
    voice_fixture_complete_channel (f, setup, TRUE);
    g_assert_cmpuint (voice_fixture_read_format (f, call), ==, 0);
    g_assert_cmpstr (voice_fixture_read_port (f, call), ==, "");
    voice_fixture_free (f);
}

static void
test_registered_audio_port_and_native_call (void)
{
    VoiceFixture *f = voice_fixture_new ();
    MMBaseCall *call = voice_fixture_outgoing (f, "+49123456780");
    MMPort *port = voice_fixture_audio_port (f);
    MMPortSerial *owned = mm_base_modem_get_port_audio (MM_BASE_MODEM (voice_fixture_voice (f)));
    gpointer weak_port = port;
    MMVoiceAudioToken setup;
    g_assert_true (MM_PORT (owned) == port);
    g_object_unref (owned);
    setup = voice_fixture_start_channel (f);
    voice_fixture_complete_channel (f, setup, TRUE);
    g_assert_cmpstr (voice_fixture_read_port (f, call), ==, "fixture-audio");
    voice_fixture_assert_native_hangup (f, call, 37);
    voice_fixture_cleanup_last_channel (f);
    g_object_add_weak_pointer (G_OBJECT (port), &weak_port);
    voice_fixture_free (f);
    g_assert_null (weak_port);
}

static void
test_observed_invalidity_and_operation_cancellation (void)
{
    VoiceFixture *f = voice_fixture_new ();
    MMIfaceModemVoice *voice = voice_fixture_voice (f);
    MMBaseCall *call;
    MMVoiceAudioToken old, current;
    g_autoptr(GCancellable) first = NULL;
    g_autoptr(GCancellable) second = NULL;

    publish_synthetic_configuration (f);
    call = voice_fixture_incoming (f, "+49123456789");
    old = voice_fixture_start_channel (f);
    first = mm_iface_modem_voice_audio_ref_channel_cancellable (voice, FALSE);
    g_assert_nonnull (first);
    current = voice_fixture_start_channel (f);
    second = mm_iface_modem_voice_audio_ref_channel_cancellable (voice, FALSE);
    g_assert_nonnull (second);
    g_assert_true (first != second);
    g_assert_true (g_cancellable_is_cancelled (first));
    g_assert_false (g_cancellable_is_cancelled (second));
    g_assert_null (mm_iface_modem_voice_audio_ref_channel_cancellable (voice, TRUE));
    mm_base_modem_set_valid (MM_BASE_MODEM (voice), FALSE);
    g_assert_true (g_cancellable_is_cancelled (second));
    g_assert_null (mm_iface_modem_voice_audio_ref_channel_cancellable (voice, FALSE));
    g_assert_cmpuint (voice_fixture_read_format (f, call), ==, 0);
    g_assert_cmpstr (voice_fixture_read_port (f, call), ==, "");
    voice_fixture_complete_channel (f, current, TRUE);
    voice_fixture_complete_channel (f, old, TRUE);
    g_assert_cmpstr (voice_fixture_read_port (f, call), ==, "");
    voice_fixture_free (f);
}

static void
test_operation_exhaustion_fails_closed (void)
{
    VoiceFixture *f = voice_fixture_new ();
    MMBaseCall *call;
    publish_synthetic_configuration (f);
    call = voice_fixture_incoming (f, "+49123456789");
    voice_fixture_assert_exhaustion (f);
    g_assert_cmpuint (voice_fixture_read_format (f, call), ==, 0);
    g_assert_cmpstr (voice_fixture_read_port (f, call), ==, "");
    voice_fixture_free (f);
}

static void
reprobe_notified (GObject *object, GParamSpec *pspec, guint *count)
{
    (*count)++;
}

static void
test_direct_reprobe_closes_admission (void)
{
    VoiceFixture *f = voice_fixture_new ();
    MMIfaceModemVoice *voice = voice_fixture_voice (f);
    MMBaseModem *modem = MM_BASE_MODEM (voice);
    MMBaseCall *call;
    MMVoiceAudioToken channel, configuration, rejected, refreshed;
    g_autoptr(MMCallAudioFormat) format = synthetic_format ();
    g_autoptr(GCancellable) operation = NULL;
    guint notifications = 0;

    /* Initial provider configuration must work before the modem becomes valid. */
    g_assert_false (mm_base_modem_get_valid (modem));
    publish_synthetic_configuration (f);
    call = voice_fixture_incoming (f, "+49123456789");
    voice_fixture_publish_active (f);
    channel = voice_fixture_start_channel (f);
    operation = mm_iface_modem_voice_audio_ref_channel_cancellable (voice, FALSE);
    g_assert_nonnull (operation);
    configuration = mm_iface_modem_voice_audio_begin_configuration (voice);
    g_signal_connect (modem, "notify::" MM_BASE_MODEM_REPROBE,
                      G_CALLBACK (reprobe_notified), &notifications);

    /* Match the real reset caller: direct setter, with NO set_valid, disable,
     * event-loop iteration or transport completion before admission checks. */
    mm_base_modem_set_reprobe (modem, TRUE);
    g_assert_cmpuint (notifications, ==, 1);
    g_assert_true (g_cancellable_is_cancelled (operation));
    g_assert_false (mm_iface_modem_voice_audio_publish_configured (voice, configuration, format));
    g_assert_false (mm_iface_modem_voice_audio_commit_channel (voice, channel,
                                                             voice_fixture_audio_port (f), format));
    g_assert_false (mm_iface_modem_voice_audio_clear_channel (voice, channel));
    rejected = mm_iface_modem_voice_audio_begin_configuration (voice);
    g_assert_cmpuint (rejected.operation, ==, 0);
    g_assert_false (mm_iface_modem_voice_audio_publish_configured (voice, rejected, format));
    rejected = mm_iface_modem_voice_audio_begin_channel (voice);
    g_assert_cmpuint (rejected.operation, ==, 0);
    g_assert_null (mm_iface_modem_voice_audio_dup_configured (voice));
    g_assert_null (mm_iface_modem_voice_audio_ref_channel_cancellable (voice, FALSE));
    g_assert_false (mm_port_get_connected (voice_fixture_audio_port (f)));
    g_assert_cmpuint (voice_fixture_read_format (f, call), ==, 0);
    g_assert_cmpstr (voice_fixture_read_port (f, call), ==, "");
    voice_fixture_complete_channel (f, channel, TRUE);
    g_assert_cmpstr (voice_fixture_read_port (f, call), ==, "");

    mm_base_modem_set_reprobe (modem, TRUE);
    g_assert_cmpuint (notifications, ==, 1);
    mm_base_modem_set_reprobe (modem, FALSE);
    g_assert_cmpuint (notifications, ==, 2);
    g_assert_false (mm_base_modem_get_valid (modem));
    g_assert_null (mm_iface_modem_voice_audio_dup_configured (voice));
    refreshed = mm_iface_modem_voice_audio_begin_configuration (voice);
    g_assert_cmpuint (refreshed.generation, !=, configuration.generation);
    g_assert_true (mm_iface_modem_voice_audio_publish_configured (voice, refreshed, format));
    g_assert_cmpuint (voice_fixture_read_format (f, call), ==, 16000);
    g_signal_handlers_disconnect_by_func (modem, G_CALLBACK (reprobe_notified), &notifications);
    voice_fixture_free (f);
}

int
main (int argc, char **argv)
{
    GError *error = NULL;
    int result;

    g_test_init (&argc, &argv, NULL);
    g_assert_true (mm_log_setup ("INFO", NULL, FALSE, FALSE, FALSE, FALSE, &error));
    g_assert_no_error (error);
    g_test_add_func ("/voice-audio/ongoing-update", test_ongoing_update);
    g_test_add_func ("/voice-audio/terminal-update", test_terminal_update);
    g_test_add_func ("/voice-audio/cleanup-shared-port", test_cleanup_shared_port);
    g_test_add_func ("/voice-audio/configured-first-subsequent", test_configured_first_and_subsequent_calls);
    g_test_add_func ("/voice-audio/configuration-tokens-inflight", test_configuration_tokens_and_inflight_calls);
    g_test_add_func ("/voice-audio/stale-setup", test_stale_setup_preserves_new_task_and_port);
    g_test_add_func ("/voice-audio/stale-cleanup", test_stale_cleanup_preserves_new_channel);
    g_test_add_func ("/voice-audio/failed-activation", test_failed_activation_has_no_port);
    g_test_add_func ("/voice-audio/invalidation-terminal", test_invalidation_clears_terminal_and_blocks_results);
    g_test_add_func ("/voice-audio/registered-audio-native-call", test_registered_audio_port_and_native_call);
    g_test_add_func ("/voice-audio/observed-invalidity-cancellation", test_observed_invalidity_and_operation_cancellation);
    g_test_add_func ("/voice-audio/operation-exhaustion", test_operation_exhaustion_fails_closed);
    g_test_add_func ("/voice-audio/direct-reprobe-admission", test_direct_reprobe_closes_admission);
    result = g_test_run ();
    mm_log_shutdown ();
    return result;
}
