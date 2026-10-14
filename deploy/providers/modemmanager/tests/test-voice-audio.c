/* SPDX-License-Identifier: GPL-2.0-or-later */
#include <config.h>
#include "provider-fixture.h"
#include "mm-log.h"

static void
test_ongoing_update (void)
{
    VoiceFixture *f = voice_fixture_new ();
    MMBaseCall *ringing = voice_fixture_incoming (f, "+49123456789");
    MMBaseCall *unknown = voice_fixture_outgoing (f, "+49123456780");
    voice_fixture_publish_active (f);
    g_assert_cmpuint (voice_fixture_read_format (f, ringing), ==, 16000);
    g_assert_cmpuint (voice_fixture_read_format (f, unknown), ==, 16000);
    g_assert_cmpstr (voice_fixture_read_port (f, ringing), ==, "fixture-audio");
    voice_fixture_free (f);
}

static void
test_terminal_update (void)
{
    VoiceFixture *f = voice_fixture_new ();
    MMBaseCall *call = voice_fixture_incoming (f, "+49123456789");
    mm_base_call_change_state (call, MM_CALL_STATE_TERMINATED, MM_CALL_STATE_REASON_TERMINATED);
    voice_fixture_publish_active (f);
    g_assert_cmpuint (voice_fixture_read_format (f, call), ==, 0);
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
    result = g_test_run ();
    mm_log_shutdown ();
    return result;
}
