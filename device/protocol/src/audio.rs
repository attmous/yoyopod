//! Audio activity stamps are independent of the call manager admission counter.
use crate::call::InterruptForCall;
use serde::{Deserialize, Serialize};

pub fn is_audio_start(message_type: &str) -> bool {
    matches!(
        message_type,
        "voice.ask"
            | "voice.transcribe"
            | "voice.speak"
            | "voice.focus_prompt"
            | "voip.start_voice_note_recording"
            | "voip.play_voice_note"
            | "voip.play_focus_prompt"
            | "voip.resume_voice_note_playback"
            | "voip.send_voice_note"
            | "media.start"
            | "media.play"
            | "media.resume"
            | "media.next_track"
            | "media.previous_track"
            | "media.load_tracks"
            | "media.load_playlist"
            | "media.play_playlist_track"
            | "media.shuffle_all"
            | "media.play_recent_track"
    )
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize)]
pub struct AudioActivityStamp {
    pub voice_activity_generation: u64,
}

#[derive(Debug, Default)]
pub struct AudioCallFence {
    active: Option<InterruptForCall>,
    last_call_token: u64,
    voice_floor: u64,
    interrupted: bool,
}

impl AudioCallFence {
    pub fn is_current(&self, request: &InterruptForCall) -> bool {
        self.active.as_ref() == Some(request)
    }
    pub fn interrupt(&mut self, request: &InterruptForCall) -> Result<(), String> {
        if self.active.as_ref() == Some(request) {
            return Ok(());
        }
        if request.activity_generation <= self.last_call_token || self.active.is_some() {
            return Err("stale or conflicting call interruption".into());
        }
        self.last_call_token = request.activity_generation;
        self.voice_floor = self.voice_floor.max(request.voice_activity_generation);
        self.interrupted = true;
        self.active = Some(request.clone());
        Ok(())
    }

    pub fn release(&mut self, request: &InterruptForCall) -> bool {
        if self.active.as_ref() == Some(request) {
            self.active = None;
            true
        } else {
            false
        }
    }

    pub fn permit_start(&self, stamp: Option<AudioActivityStamp>) -> Result<(), String> {
        if self.active.is_some() {
            return Err("audio reserved for call".into());
        }
        if self.interrupted && stamp.is_none_or(|s| s.voice_activity_generation < self.voice_floor)
        {
            return Err("stale audio activity".into());
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::call::{CallTransport, SessionKey};
    #[test]
    fn release_never_allows_pre_call_or_unstamped_audio_and_cannot_release_new_owner() {
        let request = InterruptForCall {
            key: SessionKey {
                transport: CallTransport::Sip,
                generation: 1,
                call_id: "a".into(),
            },
            activity_generation: 7,
            voice_activity_generation: 30,
        };
        let mut fence = AudioCallFence::default();
        assert!(fence.permit_start(None).is_ok());
        fence.interrupt(&request).unwrap();
        assert!(fence
            .permit_start(Some(AudioActivityStamp {
                voice_activity_generation: 30
            }))
            .is_err());
        let mut stale = request.clone();
        stale.activity_generation = 6;
        assert!(!fence.release(&stale));
        assert!(fence.release(&request));
        assert!(fence.permit_start(None).is_err());
        assert!(fence
            .permit_start(Some(AudioActivityStamp {
                voice_activity_generation: 29
            }))
            .is_err());
        assert!(fence
            .permit_start(Some(AudioActivityStamp {
                voice_activity_generation: 30
            }))
            .is_ok());
        assert!(fence.interrupt(&request).is_err());
        let mut next = request.clone();
        next.activity_generation = 8;
        next.voice_activity_generation = 31;
        next.key.call_id = "b".into();
        fence.interrupt(&next).unwrap();
        assert!(!fence.release(&request));
        assert!(fence
            .permit_start(Some(AudioActivityStamp {
                voice_activity_generation: 31
            }))
            .is_err());
    }
}
