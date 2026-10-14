/* SPDX-License-Identifier: GPL-2.0-or-later */
#ifndef YOYOPOD_PROVIDER_FIXTURE_H
#define YOYOPOD_PROVIDER_FIXTURE_H

#include "mm-iface-modem-voice.h"
#include "mm-base-call.h"

typedef struct _VoiceFixture VoiceFixture;
VoiceFixture *voice_fixture_new (void);
void voice_fixture_free (VoiceFixture *f);
MMIfaceModemVoice *voice_fixture_voice (VoiceFixture *f);
MMBaseCall *voice_fixture_incoming (VoiceFixture *f, const gchar *number);
MMBaseCall *voice_fixture_outgoing (VoiceFixture *f, const gchar *number);
MMPort *voice_fixture_audio_port (VoiceFixture *f);
guint voice_fixture_read_format (VoiceFixture *f, MMBaseCall *call);
const gchar *voice_fixture_read_port (VoiceFixture *f, MMBaseCall *call);
void voice_fixture_cleanup_last_channel (VoiceFixture *f);
void voice_fixture_publish_active (VoiceFixture *f);

MMVoiceAudioToken voice_fixture_start_channel (VoiceFixture *f);
MMVoiceAudioToken voice_fixture_start_cleanup (VoiceFixture *f);
void voice_fixture_complete_channel (VoiceFixture *f, MMVoiceAudioToken token, gboolean success);
gboolean voice_fixture_channel_pending (VoiceFixture *f, MMVoiceAudioToken token);
void voice_fixture_assert_native_hangup (VoiceFixture *f, MMBaseCall *call, guint8 call_id);

void voice_fixture_assert_exhaustion (VoiceFixture *f);

VoiceFixture *voice_fixture_new_uninitialized (void);
void voice_fixture_begin_initialize (VoiceFixture *f);
void voice_fixture_wait_lifecycle (VoiceFixture *f);
void voice_fixture_wait_lifecycle_failure (VoiceFixture *f, GQuark domain, gint code);
void voice_fixture_initialize (VoiceFixture *f);
void voice_fixture_enable (VoiceFixture *f);
void voice_fixture_disable (VoiceFixture *f);
void voice_fixture_set_readback (VoiceFixture *f, const gchar *reply);
guint voice_fixture_at_count (VoiceFixture *f, const gchar *command);
void voice_fixture_hold_at (VoiceFixture *f, const gchar *command);
void voice_fixture_wait_held_at (VoiceFixture *f);
void voice_fixture_release_at (VoiceFixture *f, gboolean success);
void voice_fixture_run_timers (VoiceFixture *f);
MMVoiceAudioToken voice_fixture_schedule_channel (VoiceFixture *f, gboolean cleanup);
void voice_fixture_assert_real_queue_cancellation (VoiceFixture *f);
void voice_fixture_publish_active_rate (VoiceFixture *f, guint rate);
#endif
