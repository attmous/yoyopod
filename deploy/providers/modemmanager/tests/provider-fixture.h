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

#endif
