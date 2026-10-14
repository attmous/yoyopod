/* SPDX-License-Identifier: GPL-2.0-or-later */
#include <config.h>
#include "provider-fixture.h"
#include "mm-base-modem.h"
#include "mm-log.h"
#include "mm-errors-types.h"

static void
assert_rate (VoiceFixture *f, guint rate)
{
    g_autoptr(MMCallAudioFormat) format = mm_iface_modem_voice_audio_dup_configured (voice_fixture_voice (f));
    if (!rate)
        g_assert_null (format);
    else {
        g_assert_nonnull (format);
        g_assert_cmpuint (mm_call_audio_format_get_rate (format), ==, rate);
    }
}

static void
test_initial_format_before_activation (void)
{
    VoiceFixture *f = voice_fixture_new_uninitialized ();
    MMBaseCall *incoming, *outgoing;
    g_assert_false (mm_base_modem_get_valid (MM_BASE_MODEM (voice_fixture_voice (f))));
    voice_fixture_initialize (f);
    incoming = voice_fixture_incoming (f, "+49123456789");
    outgoing = voice_fixture_outgoing (f, "+49123456780");
    /* Actual stock plugin returns no configured format: behavioral RED here. */
    g_assert_cmpuint (voice_fixture_read_format (f, incoming), ==, 16000);
    g_assert_cmpuint (voice_fixture_read_format (f, outgoing), ==, 16000);
    g_assert_cmpstr (voice_fixture_read_port (f, incoming), ==, "");
    g_assert_cmpstr (voice_fixture_read_port (f, outgoing), ==, "");
    g_assert_cmpuint (voice_fixture_at_count (f, "+CPCMFRM=1"), ==, 1);
    g_assert_cmpuint (voice_fixture_at_count (f, "+CPCMFRM?"), ==, 1);
    g_assert_cmpuint (voice_fixture_at_count (f, "+CPCMREG=1"), ==, 0);
    voice_fixture_assert_native_hangup (f, outgoing, 37);
    voice_fixture_free (f);
}

static void
test_ack_precedes_readback_and_publication (void)
{
    VoiceFixture *f = voice_fixture_new_uninitialized ();
    voice_fixture_hold_at (f, "+CPCMFRM=1");
    voice_fixture_begin_initialize (f);
    voice_fixture_wait_held_at (f);
    assert_rate (f, 0);
    g_assert_cmpuint (voice_fixture_at_count (f, "+CPCMFRM?"), ==, 0);
    voice_fixture_hold_at (f, "+CPCMFRM?");
    voice_fixture_release_at (f, TRUE);
    voice_fixture_wait_held_at (f);
    assert_rate (f, 0);
    voice_fixture_release_at (f, TRUE);
    voice_fixture_wait_lifecycle (f);
    assert_rate (f, 16000);
    voice_fixture_free (f);
}

static void
test_bad_readback (gconstpointer data)
{
    VoiceFixture *f = voice_fixture_new_uninitialized ();
    voice_fixture_set_readback (f, data);
    voice_fixture_begin_initialize (f);
    voice_fixture_wait_lifecycle_failure (f, MM_CORE_ERROR, MM_CORE_ERROR_UNSUPPORTED);
    g_assert_cmpuint (voice_fixture_at_count (f, "+CPCMFRM?"), ==, 1);
    assert_rate (f, 0);
    voice_fixture_free (f);
}

static void
test_lifecycle_refresh (void)
{
    VoiceFixture *f = voice_fixture_new_uninitialized ();
    MMBaseCall *call;
    voice_fixture_initialize (f);
    assert_rate (f, 16000);
    voice_fixture_enable (f);
    g_assert_cmpuint (voice_fixture_at_count (f, "+CPCMFRM=1"), ==, 1);
    voice_fixture_disable (f);
    assert_rate (f, 0);
    voice_fixture_enable (f);
    g_assert_cmpuint (voice_fixture_at_count (f, "+CPCMFRM=1"), ==, 2);
    g_assert_cmpuint (voice_fixture_at_count (f, "+CPCMFRM?"), ==, 2);
    call = voice_fixture_incoming (f, "+49123456789");
    g_assert_cmpuint (voice_fixture_read_format (f, call), ==, 16000);
    voice_fixture_disable (f);
    voice_fixture_set_readback (f, "+CPCMFRM: 0");
    /* Generic enable treats enable-unsolicited errors as noncritical: its
     * real finish must succeed, while rejected refresh must leave no format. */
    voice_fixture_enable (f);
    g_assert_cmpuint (voice_fixture_at_count (f, "+CPCMFRM?"), ==, 3);
    assert_rate (f, 0);
    g_assert_cmpuint (voice_fixture_read_format (f, call), ==, 0);
    voice_fixture_free (f);
}

static void
test_shutdown_held_configuration (void)
{
    VoiceFixture *f = voice_fixture_new_uninitialized ();
    voice_fixture_hold_at (f, "+CPCMFRM=1");
    voice_fixture_begin_initialize (f);
    voice_fixture_wait_held_at (f);
    mm_iface_modem_voice_shutdown (voice_fixture_voice (f));
    voice_fixture_release_at (f, TRUE);
    voice_fixture_wait_lifecycle_failure (f, MM_CORE_ERROR, MM_CORE_ERROR_UNSUPPORTED);
    assert_rate (f, 0);
    g_assert_cmpuint (voice_fixture_at_count (f, "+CPCMFRM?"), ==, 0);
    voice_fixture_free (f);
}

static void
test_ack_error_has_no_readback (void)
{
    VoiceFixture *f = voice_fixture_new_uninitialized ();
    voice_fixture_hold_at (f, "+CPCMFRM=1");
    voice_fixture_begin_initialize (f);
    voice_fixture_wait_held_at (f);
    voice_fixture_release_at (f, FALSE);
    voice_fixture_wait_lifecycle_failure (f, MM_CORE_ERROR, MM_CORE_ERROR_UNSUPPORTED);
    assert_rate (f, 0);
    g_assert_cmpuint (voice_fixture_at_count (f, "+CPCMFRM?"), ==, 0);
    voice_fixture_free (f);
}

static void
test_obsolete_delayed_cleanup_never_dispatches (void)
{
    VoiceFixture *f = voice_fixture_new ();
    MMVoiceAudioToken current;
    voice_fixture_schedule_channel (f, TRUE);
    current = voice_fixture_schedule_channel (f, FALSE);
    voice_fixture_run_timers (f);
    g_assert_cmpuint (voice_fixture_at_count (f, "+CPCMREG=0"), ==, 0);
    g_assert_cmpuint (voice_fixture_at_count (f, "+CPCMREG=1"), ==, 1);
    voice_fixture_complete_channel (f, current, TRUE);
    voice_fixture_free (f);
}

static void
test_obsolete_queued_cleanup_never_emits_bytes (void)
{
    VoiceFixture *f = voice_fixture_new ();
    voice_fixture_assert_real_queue_cancellation (f);
    voice_fixture_free (f);
}

int
main (int argc, char **argv)
{
    g_autoptr(GError) error = NULL;
    int result;
    g_test_init (&argc, &argv, NULL);
    g_assert_true (mm_log_setup ("INFO", NULL, FALSE, FALSE, FALSE, FALSE, &error));
    g_assert_no_error (error);
    g_test_add_func ("/simtech-audio/initial-format-before-activation", test_initial_format_before_activation);
    g_test_add_func ("/simtech-audio/ack-readback-publication-order", test_ack_precedes_readback_and_publication);
    g_test_add_func ("/simtech-audio/lifecycle-refresh", test_lifecycle_refresh);
    g_test_add_func ("/simtech-audio/shutdown-held-configuration", test_shutdown_held_configuration);
    g_test_add_func ("/simtech-audio/ack-error", test_ack_error_has_no_readback);
    g_test_add_data_func ("/simtech-audio/readback-zero", "+CPCMFRM: 0", test_bad_readback);
    g_test_add_data_func ("/simtech-audio/readback-empty", "", test_bad_readback);
    g_test_add_data_func ("/simtech-audio/readback-duplicate", "+CPCMFRM: 1\r\n+CPCMFRM: 1", test_bad_readback);
    g_test_add_data_func ("/simtech-audio/readback-malformed", "+CPCMFRM: 1 trailing", test_bad_readback);
    g_test_add_func ("/simtech-audio/obsolete-delayed-cleanup", test_obsolete_delayed_cleanup_never_dispatches);
    g_test_add_func ("/simtech-audio/obsolete-queued-cleanup", test_obsolete_queued_cleanup_never_emits_bytes);
    result = g_test_run ();
    mm_log_shutdown ();
    return result;
}
