/* SPDX-License-Identifier: GPL-2.0-or-later */
#include <config.h>
#include "provider-fixture.h"
#include "mm-base-modem.h"
#include "mm-log.h"
#include "mm-errors-types.h"
#include <glib/gstdio.h>
#include <unistd.h>
#include <string.h>

static gchar *test_log_path;

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
    /* Candidate dictionary only: no firmware framing qualification claim. */
    voice_fixture_assert_candidate_format (f, incoming);
    voice_fixture_assert_candidate_format (f, outgoing);
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
test_submitted_cleanup_ack_precedes_new_commit (void)
{
    VoiceFixture *f = voice_fixture_new ();
    voice_fixture_assert_real_queue_cancellation (f);
    voice_fixture_free (f);
}

static void
test_unsupported_audio_capability (gconstpointer command)
{
    VoiceFixture *f = voice_fixture_new_uninitialized ();
    voice_fixture_fail_next_at (f, command, MM_MOBILE_EQUIPMENT_ERROR, MM_MOBILE_EQUIPMENT_ERROR_NOT_SUPPORTED);
    /* CPCMREG/CPCMFRM capability is optional for voice; actual init succeeds,
     * but no unverified PCM configuration or activation may be published. */
    voice_fixture_initialize (f);
    assert_rate (f, 0);
    g_assert_cmpuint (voice_fixture_at_count (f, command), ==, 1);
    g_assert_cmpuint (voice_fixture_at_count (f, "+CPCMFRM=1"), ==, 0);
    g_assert_cmpuint (voice_fixture_at_count (f, "+CPCMFRM?"), ==, 0);
    g_assert_cmpuint (voice_fixture_at_count (f, "+CPCMREG=1"), ==, 0);
    voice_fixture_free (f);
}

static void
test_setter_timeout (void)
{
    VoiceFixture *f = voice_fixture_new_uninitialized ();
    voice_fixture_fail_next_at (f, "+CPCMFRM=1", MM_SERIAL_ERROR, MM_SERIAL_ERROR_RESPONSE_TIMEOUT);
    voice_fixture_begin_initialize (f);
    voice_fixture_wait_lifecycle_failure (f, MM_CORE_ERROR, MM_CORE_ERROR_UNSUPPORTED);
    assert_rate (f, 0);
    g_assert_cmpuint (voice_fixture_at_count (f, "+CPCMFRM=1"), ==, 1);
    g_assert_cmpuint (voice_fixture_at_count (f, "+CPCMFRM?"), ==, 0);
    voice_fixture_free (f);
}

static void
test_query_error (gconstpointer timeout)
{
    VoiceFixture *f = voice_fixture_new_uninitialized ();
    voice_fixture_fail_next_at (f, "+CPCMFRM?",
                               timeout ? MM_SERIAL_ERROR : MM_MOBILE_EQUIPMENT_ERROR,
                               timeout ? MM_SERIAL_ERROR_RESPONSE_TIMEOUT : MM_MOBILE_EQUIPMENT_ERROR_NOT_SUPPORTED);
    voice_fixture_begin_initialize (f);
    voice_fixture_wait_lifecycle_failure (f, MM_CORE_ERROR, MM_CORE_ERROR_UNSUPPORTED);
    assert_rate (f, 0);
    g_assert_cmpuint (voice_fixture_at_count (f, "+CPCMFRM=1"), ==, 1);
    g_assert_cmpuint (voice_fixture_at_count (f, "+CPCMFRM?"), ==, 1);
    voice_fixture_free (f);
}

static void
test_query_cancellation (void)
{
    VoiceFixture *f = voice_fixture_new_uninitialized ();
    voice_fixture_hold_at (f, "+CPCMFRM?");
    voice_fixture_begin_initialize (f);
    voice_fixture_wait_held_at (f);
    assert_rate (f, 0);
    voice_fixture_cancel_held_at (f);
    voice_fixture_release_at (f, TRUE);
    voice_fixture_wait_lifecycle_failure (f, MM_CORE_ERROR, MM_CORE_ERROR_UNSUPPORTED);
    assert_rate (f, 0);
    voice_fixture_free (f);
}

static gsize
log_offset (void)
{
    g_autofree gchar *contents = NULL;
    g_autoptr(GError) error = NULL;
    gsize size;
    g_assert_true (g_file_get_contents (test_log_path, &contents, &size, &error));
    g_assert_no_error (error);
    return size;
}

static gchar *
log_since (gsize offset)
{
    g_autofree gchar *contents = NULL;
    g_autoptr(GError) error = NULL;
    gsize size;
    g_assert_true (g_file_get_contents (test_log_path, &contents, &size, &error));
    g_assert_no_error (error);
    g_assert_cmpuint (size, >=, offset);
    return g_strdup (contents + offset);
}

static void
assert_bounded_marker (MMVoiceAudioToken token, gsize offset, const gchar *selection, const gchar *readback)
{
    g_autofree gchar *log = log_since (offset);
    g_autofree gchar *expected = g_strdup_printf (
        "voice-audio contract=1 generation=%" G_GUINT64_FORMAT
        " operation=%" G_GUINT64_FORMAT " selection=%s readback=%s",
        token.generation, token.operation, selection, readback);
    const gchar *marker = strstr (log, "voice-audio contract=");
    const gchar *end;
    const gchar *line;
    g_assert_nonnull (marker);
    line = marker;
    while (line > log && line[-1] != '\n')
        line--;
    /* MSG threshold alone also admits WARN/ERR: require actual severity. */
    g_assert_true (g_str_has_prefix (line, "<msg> "));
    end = strchr (marker, '\n');
    g_assert_nonnull (end);
    g_assert_cmpuint (end - marker, <=, 160);
    g_assert_cmpuint (end - marker, ==, strlen (expected));
    g_assert_true (g_str_has_prefix (marker, expected));
    g_assert_null (strstr (end, "voice-audio contract="));
    /* Exact bounded payload permits only contract/token/outcome fields: no
     * raw AT response, test number, subscriber identifier or exception text. */
}

static void
test_normal_level_success_marker (void)
{
    VoiceFixture *f = voice_fixture_new_uninitialized ();
    gsize offset = log_offset ();
    MMVoiceAudioToken attempted;
    voice_fixture_hold_at (f, "+CPCMFRM=1");
    voice_fixture_begin_initialize (f);
    voice_fixture_wait_held_at (f);
    attempted = voice_fixture_configuration_token (f);
    voice_fixture_release_at (f, TRUE);
    voice_fixture_wait_lifecycle (f);
    assert_rate (f, 16000);
    assert_bounded_marker (attempted, offset, "ok", "ok");
    voice_fixture_free (f);
}

static void
test_normal_level_failure_marker (gconstpointer query_failure)
{
    VoiceFixture *f = voice_fixture_new_uninitialized ();
    gsize offset = log_offset ();
    MMVoiceAudioToken attempted;
    voice_fixture_hold_at (f, query_failure ? "+CPCMFRM?" : "+CPCMFRM=1");
    voice_fixture_begin_initialize (f);
    voice_fixture_wait_held_at (f);
    /* Capture the actual task's current token while its fixed effect is held.
     * A timeout may invalidate and advance the context generation afterwards. */
    attempted = voice_fixture_configuration_token (f);
    voice_fixture_release_at_error (f, MM_SERIAL_ERROR, MM_SERIAL_ERROR_RESPONSE_TIMEOUT);
    voice_fixture_wait_lifecycle_failure (f, MM_CORE_ERROR, MM_CORE_ERROR_UNSUPPORTED);
    assert_rate (f, 0);
    assert_bounded_marker (attempted, offset, query_failure ? "ok" : "failed",
                           query_failure ? "failed" : "not-run");
    voice_fixture_free (f);
}

static void
test_reset_during_refresh (gconstpointer query_held)
{
    VoiceFixture *f = voice_fixture_new_uninitialized ();
    MMBaseModem *modem = MM_BASE_MODEM (voice_fixture_voice (f));
    MMBaseCall *call;
    gsize offset;
    g_autofree gchar *log = NULL;
    guint queries;
    voice_fixture_initialize (f);
    voice_fixture_enable (f);
    call = voice_fixture_incoming (f, "+49123456789");
    g_assert_cmpuint (voice_fixture_read_format (f, call), ==, 16000);
    voice_fixture_disable (f);
    queries = voice_fixture_at_count (f, "+CPCMFRM?");
    offset = log_offset ();
    voice_fixture_hold_at (f, query_held ? "+CPCMFRM?" : "+CPCMFRM=1");
    voice_fixture_begin_enable (f);
    voice_fixture_wait_held_at (f);
    mm_base_modem_set_reprobe (modem, TRUE);
    assert_rate (f, 0);
    g_assert_cmpuint (voice_fixture_read_format (f, call), ==, 0);
    g_assert_cmpstr (voice_fixture_read_port (f, call), ==, "");
    voice_fixture_release_at (f, TRUE);
    /* Public enable retains its actual noncritical unsolicited-error contract. */
    voice_fixture_wait_lifecycle (f);
    assert_rate (f, 0);
    g_assert_cmpuint (voice_fixture_at_count (f, "+CPCMFRM?"), ==, queries + (query_held ? 1 : 0));
    log = log_since (offset);
    g_assert_null (strstr (log, "selection=ok readback=ok"));
    voice_fixture_free (f);
}

static void
test_reentrant_publication_invalidation_has_no_success_marker (void)
{
    VoiceFixture *f = voice_fixture_new_uninitialized ();
    MMBaseCall *call;
    MMVoiceAudioToken attempted, after;
    gsize offset;
    g_autofree gchar *log = NULL;

    voice_fixture_initialize (f);
    voice_fixture_enable (f);
    call = voice_fixture_incoming (f, "+49123456789");
    voice_fixture_disable (f);
    g_assert_cmpuint (voice_fixture_read_format (f, call), ==, 0);
    voice_fixture_invalidate_on_publication (f, call);
    offset = log_offset ();
    voice_fixture_hold_at (f, "+CPCMFRM?");
    voice_fixture_begin_enable (f);
    voice_fixture_wait_held_at (f);
    attempted = voice_fixture_configuration_token (f);
    g_assert_cmpuint (voice_fixture_publication_invalidations (f), ==, 0);
    voice_fixture_release_at (f, TRUE);
    voice_fixture_wait_lifecycle (f);
    g_assert_cmpuint (voice_fixture_publication_invalidations (f), ==, 1);
    after = voice_fixture_configuration_token (f);
    g_assert_cmpuint (after.generation, !=, attempted.generation);
    assert_rate (f, 0);
    g_assert_cmpuint (voice_fixture_read_format (f, call), ==, 0);
    g_assert_cmpstr (voice_fixture_read_port (f, call), ==, "");
    log = log_since (offset);
    g_assert_null (strstr (log, "selection=ok readback=ok"));
    voice_fixture_free (f);
}

static void
test_unsettled_channel_blocks_refresh_and_latches (gconstpointer reset)
{
    VoiceFixture *f = voice_fixture_new_uninitialized ();
    MMBaseModem *modem = MM_BASE_MODEM (voice_fixture_voice (f));
    MMVoiceAudioToken channel;
    gsize offset;
    g_autofree gchar *log = NULL;
    voice_fixture_initialize (f);
    voice_fixture_enable (f);
    channel = voice_fixture_start_channel (f);
    offset = log_offset ();
    if (reset)
        mm_base_modem_set_reprobe (modem, TRUE);
    voice_fixture_disable (f);
    if (reset)
        mm_base_modem_set_reprobe (modem, FALSE);
    /* The old physical command is STILL held. A fresh lifecycle must not
     * issue selection or publish format before its response is accounted for. */
    voice_fixture_enable (f);
    assert_rate (f, 0);
    g_assert_cmpuint (voice_fixture_at_count (f, "+CPCMFRM=1"), ==, 1);
    g_assert_cmpuint (voice_fixture_at_count (f, "+CPCMFRM?"), ==, 1);
    voice_fixture_complete_channel (f, channel, TRUE);
    voice_fixture_disable (f);
    voice_fixture_enable (f);
    assert_rate (f, 0);
    g_assert_cmpuint (voice_fixture_at_count (f, "+CPCMFRM=1"), ==, 1);
    log = log_since (offset);
    g_assert_null (strstr (log, "selection=ok readback=ok"));
    voice_fixture_free (f);
}

static void
test_refresh_timeout_latches_future_admission (void)
{
    VoiceFixture *f = voice_fixture_new_uninitialized ();
    MMBaseCall *call;
    MMVoiceAudioToken fresh;
    gsize offset;
    g_autofree gchar *log = NULL;
    voice_fixture_initialize (f);
    voice_fixture_enable (f);
    call = voice_fixture_incoming (f, "+49123456789");
    voice_fixture_assert_candidate_format (f, call);
    voice_fixture_disable (f);
    voice_fixture_fail_next_at (f, "+CPCMFRM?", MM_SERIAL_ERROR, MM_SERIAL_ERROR_RESPONSE_TIMEOUT);
    voice_fixture_enable (f);
    assert_rate (f, 0);
    offset = log_offset ();
    voice_fixture_disable (f);
    voice_fixture_enable (f);
    assert_rate (f, 0);
    g_assert_cmpuint (voice_fixture_read_format (f, call), ==, 0);
    g_assert_cmpuint (voice_fixture_at_count (f, "+CPCMFRM=1"), ==, 2);
    g_assert_cmpuint (voice_fixture_at_count (f, "+CPCMFRM?"), ==, 2);
    /* A fresh real core token opens generic admission but must not reset the
     * source-owned uncertainty latch. Do not publish any candidate format. */
    fresh = mm_iface_modem_voice_audio_begin_configuration (voice_fixture_voice (f));
    g_assert_cmpuint (fresh.operation, >, 0);
    assert_rate (f, 0);
    voice_fixture_schedule_channel (f, FALSE);
    voice_fixture_run_timers (f);
    g_assert_cmpuint (voice_fixture_at_count (f, "+CPCMREG=1"), ==, 0);
    g_assert_cmpstr (voice_fixture_read_port (f, call), ==, "");
    assert_rate (f, 0);
    g_assert_cmpuint (voice_fixture_read_format (f, call), ==, 0);
    log = log_since (offset);
    g_assert_null (strstr (log, "voice-audio contract="));
    voice_fixture_free (f);
}

static void
test_reentrant_suspension_retains_new_commit (void)
{
    VoiceFixture *f = voice_fixture_new ();
    voice_fixture_assert_reentrant_suspension (f);
    voice_fixture_free (f);
}

static void
test_stale_capability_cannot_reopen_configuration (gconstpointer command)
{
    VoiceFixture *f = voice_fixture_new_uninitialized ();
    MMBaseModem *modem = MM_BASE_MODEM (voice_fixture_voice (f));
    gsize offset = log_offset ();
    g_autofree gchar *log = NULL;
    voice_fixture_hold_at (f, command);
    voice_fixture_begin_initialize (f);
    voice_fixture_wait_held_at (f);
    if (!g_strcmp0 (command, "+CLCC=?"))
        mm_iface_modem_voice_shutdown (voice_fixture_voice (f));
    else {
        mm_base_modem_set_reprobe (modem, TRUE);
        mm_base_modem_set_reprobe (modem, FALSE);
    }
    voice_fixture_release_at (f, TRUE);
    voice_fixture_wait_lifecycle_failure (f, MM_CORE_ERROR, MM_CORE_ERROR_UNSUPPORTED);
    assert_rate (f, 0);
    g_assert_cmpuint (voice_fixture_at_count (f, "+CPCMFRM=1"), ==, 0);
    g_assert_cmpuint (voice_fixture_at_count (f, "+CPCMFRM?"), ==, 0);
    if (!g_strcmp0 (command, "+CLCC=?"))
        g_assert_cmpuint (voice_fixture_at_count (f, "+CPCMREG=?"), ==, 0);
    log = log_since (offset);
    g_assert_null (strstr (log, "voice-audio contract="));
    voice_fixture_free (f);
}

static void
test_replacement_waits_its_own_delay (void)
{
    VoiceFixture *f = voice_fixture_new ();
    voice_fixture_assert_replacement_delay (f);
    voice_fixture_free (f);
}

static void
test_shutdown_before_parent_support_finish (void)
{
    VoiceFixture *f = voice_fixture_new_uninitialized ();
    voice_fixture_begin_initialize (f);
    /* The real parent result is queued; no vfunc/finish is replaced. */
    mm_iface_modem_voice_shutdown (voice_fixture_voice (f));
    voice_fixture_wait_lifecycle_failure (f, MM_CORE_ERROR, MM_CORE_ERROR_UNSUPPORTED);
    g_assert_cmpuint (voice_fixture_at_count (f, "+CLCC=?"), ==, 0);
    g_assert_cmpuint (voice_fixture_at_count (f, "+CPCMFRM=1"), ==, 0);
    assert_rate (f, 0);
    voice_fixture_free (f);
}

static void
test_shutdown_before_parent_enable_setup_finish (void)
{
    VoiceFixture *f = voice_fixture_new_uninitialized ();
    voice_fixture_initialize (f);
    voice_fixture_begin_enable (f);
    /* Parent setup uses the real missing-QMI-client completion path; shutdown
     * happens before its queued callback can advance public enable. */
    mm_iface_modem_voice_shutdown (voice_fixture_voice (f));
    voice_fixture_wait_lifecycle_failure (f, MM_CORE_ERROR, MM_CORE_ERROR_CANCELLED);
    assert_rate (f, 0);
    g_assert_cmpuint (voice_fixture_at_count (f, "+CPCMFRM=1"), ==, 1);
    g_assert_cmpuint (voice_fixture_at_count (f, "+CLCC=1"), ==, 0);
    voice_fixture_free (f);
}

static void
test_shutdown_held_enable_clcc (void)
{
    VoiceFixture *f = voice_fixture_new_uninitialized ();
    voice_fixture_initialize (f);
    voice_fixture_hold_at (f, "+CLCC=1");
    voice_fixture_begin_enable (f);
    voice_fixture_wait_held_at (f);
    mm_iface_modem_voice_shutdown (voice_fixture_voice (f));
    voice_fixture_release_at (f, TRUE);
    /* The actual enable-events failure remains noncritical to generic enable. */
    voice_fixture_wait_lifecycle (f);
    assert_rate (f, 0);
    g_assert_cmpuint (voice_fixture_at_count (f, "+CPCMFRM=1"), ==, 1);
    g_assert_cmpuint (voice_fixture_at_count (f, "+CPCMFRM?"), ==, 1);
    voice_fixture_free (f);
}

static void
test_connected_notification_cannot_restore_stale_exports (gconstpointer terminal)
{
    VoiceFixture *f = voice_fixture_new ();
    voice_fixture_assert_connected_reentrancy (f, !!terminal);
    voice_fixture_free (f);
}

int
main (int argc, char **argv)
{
    g_autoptr(GError) error = NULL;
    int result, log_fd;
    g_test_init (&argc, &argv, NULL);
    log_fd = g_file_open_tmp ("yoyopod-simtech-log-XXXXXX", &test_log_path, &error);
    g_assert_no_error (error);
    g_assert_cmpint (log_fd, >=, 0);
    g_assert_cmpint (close (log_fd), ==, 0);
    /* Use the real file backend at the daemon's normal MSG level. */
    g_assert_true (mm_log_setup ("MSG", test_log_path, FALSE, FALSE, FALSE, FALSE, &error));
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
    g_test_add_func ("/simtech-audio/submitted-cleanup-ack-before-commit", test_submitted_cleanup_ack_precedes_new_commit);
    g_test_add_data_func ("/simtech-audio/unsupported-cpcmreg", "+CPCMREG=?", test_unsupported_audio_capability);
    g_test_add_data_func ("/simtech-audio/unsupported-cpcmfrm", "+CPCMFRM=?", test_unsupported_audio_capability);
    g_test_add_func ("/simtech-audio/setter-timeout", test_setter_timeout);
    g_test_add_data_func ("/simtech-audio/query-error", NULL, test_query_error);
    g_test_add_data_func ("/simtech-audio/query-timeout", GINT_TO_POINTER (1), test_query_error);
    g_test_add_func ("/simtech-audio/query-cancellation", test_query_cancellation);
    g_test_add_data_func ("/simtech-audio/reset-held-refresh-ack", NULL, test_reset_during_refresh);
    g_test_add_data_func ("/simtech-audio/reset-held-refresh-query", GINT_TO_POINTER (1), test_reset_during_refresh);
    g_test_add_func ("/simtech-audio/normal-marker-success", test_normal_level_success_marker);
    g_test_add_data_func ("/simtech-audio/normal-marker-setter-failure", NULL, test_normal_level_failure_marker);
    g_test_add_data_func ("/simtech-audio/normal-marker-query-failure", GINT_TO_POINTER (1), test_normal_level_failure_marker);
    g_test_add_func ("/simtech-audio/reentrant-publication-no-success-marker", test_reentrant_publication_invalidation_has_no_success_marker);
    g_test_add_data_func ("/simtech-audio/unsettled-channel-disable-enable", NULL, test_unsettled_channel_blocks_refresh_and_latches);
    g_test_add_data_func ("/simtech-audio/unsettled-channel-reset", GINT_TO_POINTER (1), test_unsettled_channel_blocks_refresh_and_latches);
    g_test_add_func ("/simtech-audio/refresh-timeout-latches", test_refresh_timeout_latches_future_admission);
    g_test_add_func ("/simtech-audio/reentrant-suspension-new-commit", test_reentrant_suspension_retains_new_commit);
    g_test_add_data_func ("/simtech-audio/shutdown-held-clcc-probe", "+CLCC=?", test_stale_capability_cannot_reopen_configuration);
    g_test_add_data_func ("/simtech-audio/reset-held-cpcmfrm-probe", "+CPCMFRM=?", test_stale_capability_cannot_reopen_configuration);
    g_test_add_func ("/simtech-audio/replacement-own-100ms", test_replacement_waits_its_own_delay);
    g_test_add_func ("/simtech-audio/shutdown-parent-support", test_shutdown_before_parent_support_finish);
    g_test_add_func ("/simtech-audio/shutdown-parent-enable-setup", test_shutdown_before_parent_enable_setup_finish);
    g_test_add_func ("/simtech-audio/shutdown-held-enable-clcc", test_shutdown_held_enable_clcc);
    g_test_add_data_func ("/simtech-audio/connected-notify-new-commit", NULL, test_connected_notification_cannot_restore_stale_exports);
    g_test_add_data_func ("/simtech-audio/terminal-old-port-owned-notify", GINT_TO_POINTER (1), test_connected_notification_cannot_restore_stale_exports);
    result = g_test_run ();
    mm_log_shutdown ();
    g_assert_cmpint (g_unlink (test_log_path), ==, 0);
    g_free (test_log_path);
    return result;
}
