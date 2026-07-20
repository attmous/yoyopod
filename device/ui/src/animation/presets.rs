use crate::scene::RegionId;

use super::{
    ActorRef, AnimatableProp, AnimatableValue, ClockSource, Easing, EventId, Keyframe, LoopMode,
    Timeline, TimelineId, Track,
};

pub const BREATHE_TIMELINE_ID: TimelineId = TimelineId(10);
pub const SCENE_ENTER_TIMELINE_ID: TimelineId = TimelineId(1);
pub const STAGGER_ENTER_TIMELINE_ID: TimelineId = TimelineId(2);
pub const PULSE_ONE_SHOT_TIMELINE_ID: TimelineId = TimelineId(3);
pub const SLIDE_IN_FROM_RIGHT_TIMELINE_ID: TimelineId = TimelineId(4);
pub const PROGRESS_SWEEP_TIMELINE_ID: TimelineId = TimelineId(5);
pub const SELECTION_SNAP_TIMELINE_ID: TimelineId = TimelineId(6);
pub const MEDIA_WHEEL_ROLL_TIMELINE_ID: TimelineId = TimelineId(7);
pub const CONTACT_WHEEL_ROLL_TIMELINE_ID: TimelineId = TimelineId(8);
pub const SETUP_WHEEL_ROLL_TIMELINE_ID: TimelineId = TimelineId(9);
pub const WHEEL_ROLL_DURATION_MS: u64 = 180;
pub const MEDIA_WHEEL_PEEK_OPACITY: u8 = 148;
pub const CONTACT_WHEEL_PEEK_OPACITY: u8 = 115;
pub const SETUP_WHEEL_PEEK_OPACITY: u8 = 190;

pub fn breathe_focused_item(deck: usize, index: usize) -> Timeline {
    Timeline {
        id: TimelineId(100 + deck as u32 * 16 + index as u32),
        clock: ClockSource::GlobalTime,
        tracks: vec![Track {
            target: ActorRef::DeckItem { deck, index },
            property: AnimatableProp::Scale,
            keyframes: vec![
                Keyframe {
                    at_ms: 0,
                    value: AnimatableValue::I32(980),
                },
                Keyframe {
                    at_ms: 700,
                    value: AnimatableValue::I32(1020),
                },
                Keyframe {
                    at_ms: 1_400,
                    value: AnimatableValue::I32(980),
                },
            ],
            easing: Easing::EaseInOut,
        }],
        loop_mode: LoopMode::Loop,
        on_complete: None,
        started_ms: 0,
    }
}

pub fn breathe_around(region: RegionId) -> Timeline {
    Timeline {
        id: BREATHE_TIMELINE_ID,
        clock: ClockSource::GlobalTime,
        tracks: vec![Track {
            target: ActorRef::Region(region),
            property: AnimatableProp::Opacity,
            keyframes: vec![
                Keyframe {
                    at_ms: 0,
                    value: AnimatableValue::U8(64),
                },
                Keyframe {
                    at_ms: 700,
                    value: AnimatableValue::U8(128),
                },
                Keyframe {
                    at_ms: 1_400,
                    value: AnimatableValue::U8(64),
                },
            ],
            easing: Easing::EaseInOut,
        }],
        loop_mode: LoopMode::Loop,
        on_complete: None,
        started_ms: 0,
    }
}

pub fn scene_enter() -> Timeline {
    Timeline {
        id: SCENE_ENTER_TIMELINE_ID,
        clock: ClockSource::SceneTime,
        tracks: vec![
            Track {
                target: ActorRef::Screen,
                property: AnimatableProp::Opacity,
                keyframes: vec![
                    Keyframe {
                        at_ms: 0,
                        value: AnimatableValue::U8(0),
                    },
                    Keyframe {
                        at_ms: 220,
                        value: AnimatableValue::U8(255),
                    },
                ],
                easing: Easing::EaseOut,
            },
            Track {
                target: ActorRef::Screen,
                property: AnimatableProp::Y,
                keyframes: vec![
                    Keyframe {
                        at_ms: 0,
                        value: AnimatableValue::I32(8),
                    },
                    Keyframe {
                        at_ms: 220,
                        value: AnimatableValue::I32(0),
                    },
                ],
                easing: Easing::EaseOut,
            },
        ],
        loop_mode: LoopMode::Once,
        on_complete: None,
        started_ms: 0,
    }
}

pub fn stagger_enter(delay_per_index_ms: u32) -> Timeline {
    let tracks = (0..4)
        .map(|index| Track {
            target: ActorRef::DeckItem { deck: 0, index },
            property: AnimatableProp::Opacity,
            keyframes: vec![
                Keyframe {
                    at_ms: delay_per_index_ms * index as u32,
                    value: AnimatableValue::U8(0),
                },
                Keyframe {
                    at_ms: 160 + delay_per_index_ms * index as u32,
                    value: AnimatableValue::U8(255),
                },
            ],
            easing: Easing::EaseOut,
        })
        .collect();
    Timeline {
        id: STAGGER_ENTER_TIMELINE_ID,
        clock: ClockSource::SceneTime,
        tracks,
        loop_mode: LoopMode::Once,
        on_complete: None,
        started_ms: 0,
    }
}

pub fn pulse_one_shot(actor: ActorRef) -> Timeline {
    Timeline {
        id: PULSE_ONE_SHOT_TIMELINE_ID,
        clock: ClockSource::EventTime(EventId(3)),
        tracks: vec![
            Track {
                target: actor,
                property: AnimatableProp::Opacity,
                keyframes: vec![
                    Keyframe {
                        at_ms: 0,
                        value: AnimatableValue::U8(192),
                    },
                    Keyframe {
                        at_ms: 600,
                        value: AnimatableValue::U8(0),
                    },
                ],
                easing: Easing::EaseOut,
            },
            Track {
                target: actor,
                property: AnimatableProp::Scale,
                keyframes: vec![
                    Keyframe {
                        at_ms: 0,
                        value: AnimatableValue::I32(920),
                    },
                    Keyframe {
                        at_ms: 600,
                        value: AnimatableValue::I32(1120),
                    },
                ],
                easing: Easing::EaseOut,
            },
        ],
        loop_mode: LoopMode::Once,
        on_complete: None,
        started_ms: 0,
    }
}

pub fn slide_in_from_right() -> Timeline {
    Timeline {
        id: SLIDE_IN_FROM_RIGHT_TIMELINE_ID,
        clock: ClockSource::SceneTime,
        tracks: vec![Track {
            target: ActorRef::Screen,
            property: AnimatableProp::X,
            keyframes: vec![
                Keyframe {
                    at_ms: 0,
                    value: AnimatableValue::I32(28),
                },
                Keyframe {
                    at_ms: 220,
                    value: AnimatableValue::I32(0),
                },
            ],
            easing: Easing::EaseOut,
        }],
        loop_mode: LoopMode::Once,
        on_complete: None,
        started_ms: 0,
    }
}

pub fn progress_sweep(from: i32, to: i32) -> Timeline {
    Timeline {
        id: PROGRESS_SWEEP_TIMELINE_ID,
        clock: ClockSource::EventTime(EventId(5)),
        tracks: vec![Track {
            target: ActorRef::Region(RegionId::Progress),
            property: AnimatableProp::ProgressPermille,
            keyframes: vec![
                Keyframe {
                    at_ms: 0,
                    value: AnimatableValue::I32(from),
                },
                Keyframe {
                    at_ms: 360,
                    value: AnimatableValue::I32(to),
                },
            ],
            easing: Easing::EaseInOut,
        }],
        loop_mode: LoopMode::Once,
        on_complete: None,
        started_ms: 0,
    }
}

pub fn selection_snap(to_index: usize) -> Timeline {
    Timeline {
        id: SELECTION_SNAP_TIMELINE_ID,
        clock: ClockSource::EventTime(EventId(6)),
        tracks: vec![Track {
            target: ActorRef::Cursor,
            property: AnimatableProp::SelectionOffset,
            keyframes: vec![
                Keyframe {
                    at_ms: 0,
                    value: AnimatableValue::I32(0),
                },
                Keyframe {
                    at_ms: 120,
                    value: AnimatableValue::I32((to_index as i32) * 1_000),
                },
            ],
            easing: Easing::EaseOut,
        }],
        loop_mode: LoopMode::Once,
        on_complete: None,
        started_ms: 0,
    }
}

pub fn media_wheel_roll(item_count: usize, deck_index: usize, started_ms: u64) -> Option<Timeline> {
    if item_count < 2 {
        return None;
    }

    // Animate the currently painted items first. The runtime commits the new
    // focus only after this timeline ends, so labels never change mid-roll.
    let tracks = if item_count == 2 {
        [
            motion_tracks(deck_index, 0, 102, 1_000, 600, 255, 0),
            motion_tracks(
                deck_index,
                1,
                -102,
                1_000,
                1_120,
                MEDIA_WHEEL_PEEK_OPACITY,
                255,
            ),
        ]
        .into_iter()
        .flatten()
        .collect()
    } else {
        [
            motion_tracks(deck_index, 0, -12, 1_000, 860, MEDIA_WHEEL_PEEK_OPACITY, 0),
            motion_tracks(
                deck_index,
                1,
                -34,
                1_000,
                780,
                255,
                MEDIA_WHEEL_PEEK_OPACITY,
            ),
            motion_tracks(
                deck_index,
                2,
                -82,
                1_000,
                1_120,
                MEDIA_WHEEL_PEEK_OPACITY,
                255,
            ),
        ]
        .into_iter()
        .flatten()
        .collect()
    };

    Some(Timeline {
        id: MEDIA_WHEEL_ROLL_TIMELINE_ID,
        clock: ClockSource::EventTime(EventId(7)),
        tracks,
        loop_mode: LoopMode::Once,
        on_complete: None,
        started_ms,
    })
}

pub fn contact_wheel_roll(
    item_count: usize,
    deck_index: usize,
    started_ms: u64,
) -> Option<Timeline> {
    if item_count < 2 {
        return None;
    }

    let tracks = if item_count == 2 {
        [
            motion_tracks(
                deck_index,
                0,
                -80,
                1_000,
                700,
                255,
                CONTACT_WHEEL_PEEK_OPACITY,
            ),
            motion_tracks(
                deck_index,
                1,
                -80,
                700,
                1_000,
                CONTACT_WHEEL_PEEK_OPACITY,
                255,
            ),
        ]
        .into_iter()
        .flatten()
        .collect()
    } else {
        [
            motion_tracks(deck_index, 0, -80, 700, 700, CONTACT_WHEEL_PEEK_OPACITY, 0),
            motion_tracks(
                deck_index,
                1,
                -80,
                1_000,
                700,
                255,
                CONTACT_WHEEL_PEEK_OPACITY,
            ),
            motion_tracks(
                deck_index,
                2,
                -80,
                700,
                1_000,
                CONTACT_WHEEL_PEEK_OPACITY,
                255,
            ),
        ]
        .into_iter()
        .flatten()
        .collect()
    };

    Some(Timeline {
        id: CONTACT_WHEEL_ROLL_TIMELINE_ID,
        clock: ClockSource::EventTime(EventId(8)),
        tracks,
        loop_mode: LoopMode::Once,
        on_complete: None,
        started_ms,
    })
}

pub fn setup_wheel_roll(item_count: usize, deck_index: usize, started_ms: u64) -> Option<Timeline> {
    if item_count < 2 {
        return None;
    }

    let tracks = if item_count == 2 {
        [
            motion_tracks(deck_index, 0, -40, 1_000, 700, 255, 0),
            motion_tracks(
                deck_index,
                1,
                -104,
                1_000,
                1_000,
                SETUP_WHEEL_PEEK_OPACITY,
                255,
            ),
        ]
        .into_iter()
        .flatten()
        .collect()
    } else {
        [
            motion_tracks(deck_index, 0, -32, 1_000, 850, SETUP_WHEEL_PEEK_OPACITY, 0),
            motion_tracks(
                deck_index,
                1,
                -40,
                1_000,
                700,
                255,
                SETUP_WHEEL_PEEK_OPACITY,
            ),
            motion_tracks(
                deck_index,
                2,
                -104,
                1_000,
                1_000,
                SETUP_WHEEL_PEEK_OPACITY,
                255,
            ),
        ]
        .into_iter()
        .flatten()
        .collect()
    };

    Some(Timeline {
        id: SETUP_WHEEL_ROLL_TIMELINE_ID,
        clock: ClockSource::EventTime(EventId(9)),
        tracks,
        loop_mode: LoopMode::Once,
        on_complete: None,
        started_ms,
    })
}

fn motion_tracks(
    deck: usize,
    index: usize,
    to_y: i32,
    from_scale: i32,
    to_scale: i32,
    from_opacity: u8,
    to_opacity: u8,
) -> [Track; 3] {
    let target = ActorRef::DeckItem { deck, index };
    [
        Track {
            target,
            property: AnimatableProp::Y,
            keyframes: vec![
                Keyframe {
                    at_ms: 0,
                    value: AnimatableValue::I32(0),
                },
                Keyframe {
                    at_ms: WHEEL_ROLL_DURATION_MS as u32,
                    value: AnimatableValue::I32(to_y),
                },
            ],
            easing: Easing::EaseOut,
        },
        Track {
            target,
            property: AnimatableProp::Scale,
            keyframes: vec![
                Keyframe {
                    at_ms: 0,
                    value: AnimatableValue::I32(from_scale),
                },
                Keyframe {
                    at_ms: WHEEL_ROLL_DURATION_MS as u32,
                    value: AnimatableValue::I32(to_scale),
                },
            ],
            easing: Easing::EaseOut,
        },
        Track {
            target,
            property: AnimatableProp::Opacity,
            keyframes: vec![
                Keyframe {
                    at_ms: 0,
                    value: AnimatableValue::U8(from_opacity),
                },
                Keyframe {
                    at_ms: WHEEL_ROLL_DURATION_MS as u32,
                    value: AnimatableValue::U8(to_opacity),
                },
            ],
            easing: Easing::EaseOut,
        },
    ]
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::animation::TimelineSampler;

    #[test]
    fn media_wheel_roll_matches_the_three_slot_motion_contract() {
        let timeline = media_wheel_roll(3, 0, 1_000).expect("three tracks should roll");
        assert_eq!(timeline.tracks.len(), 9);
        let timelines = [timeline];
        let sampler = TimelineSampler::new(&timelines, 1_180, 0);

        assert_eq!(
            sampler.value(
                ActorRef::DeckItem { deck: 0, index: 0 },
                AnimatableProp::Opacity
            ),
            Some(AnimatableValue::U8(0))
        );
        assert_eq!(
            sampler.value(ActorRef::DeckItem { deck: 0, index: 1 }, AnimatableProp::Y),
            Some(AnimatableValue::I32(-34))
        );
        assert_eq!(
            sampler.value(
                ActorRef::DeckItem { deck: 0, index: 2 },
                AnimatableProp::Scale
            ),
            Some(AnimatableValue::I32(1_120))
        );
    }

    #[test]
    fn media_wheel_roll_handles_short_wheels_without_fake_peeks() {
        assert!(media_wheel_roll(1, 0, 0).is_none());
        assert_eq!(
            media_wheel_roll(2, 0, 0)
                .expect("two tracks should cross-roll")
                .tracks
                .len(),
            6
        );
    }

    #[test]
    fn contact_wheel_roll_matches_the_three_slot_motion_contract() {
        let timeline = contact_wheel_roll(3, 0, 1_000).expect("three contacts should roll");
        assert_eq!(timeline.id, CONTACT_WHEEL_ROLL_TIMELINE_ID);
        assert_eq!(timeline.tracks.len(), 9);
        let timelines = [timeline];
        let sampler = TimelineSampler::new(&timelines, 1_180, 0);

        assert_eq!(
            sampler.value(
                ActorRef::DeckItem { deck: 0, index: 0 },
                AnimatableProp::Opacity
            ),
            Some(AnimatableValue::U8(0))
        );
        assert_eq!(
            sampler.value(ActorRef::DeckItem { deck: 0, index: 1 }, AnimatableProp::Y),
            Some(AnimatableValue::I32(-80))
        );
        assert_eq!(
            sampler.value(
                ActorRef::DeckItem { deck: 0, index: 2 },
                AnimatableProp::Scale
            ),
            Some(AnimatableValue::I32(1_000))
        );
    }

    #[test]
    fn contact_wheel_roll_handles_empty_single_and_two_contact_lists() {
        assert!(contact_wheel_roll(0, 0, 0).is_none());
        assert!(contact_wheel_roll(1, 0, 0).is_none());
        assert_eq!(
            contact_wheel_roll(2, 0, 0)
                .expect("two contacts should cross-roll")
                .tracks
                .len(),
            6
        );
    }

    #[test]
    fn setup_wheel_roll_lands_on_the_named_slot_offsets() {
        let timeline = setup_wheel_roll(3, 0, 1_000).expect("three setup slots should roll");
        assert_eq!(timeline.id, SETUP_WHEEL_ROLL_TIMELINE_ID);
        assert_eq!(timeline.tracks.len(), 9);
        let timelines = [timeline];
        let sampler = TimelineSampler::new(&timelines, 1_180, 0);

        assert_eq!(
            sampler.value(ActorRef::DeckItem { deck: 0, index: 1 }, AnimatableProp::Y),
            Some(AnimatableValue::I32(-40))
        );
        assert_eq!(
            sampler.value(ActorRef::DeckItem { deck: 0, index: 2 }, AnimatableProp::Y),
            Some(AnimatableValue::I32(-104))
        );
        assert_eq!(
            sampler.value(
                ActorRef::DeckItem { deck: 0, index: 2 },
                AnimatableProp::Opacity
            ),
            Some(AnimatableValue::U8(255))
        );
    }

    #[test]
    fn setup_wheel_roll_handles_short_lists_without_fake_slots() {
        assert!(setup_wheel_roll(1, 0, 0).is_none());
        assert_eq!(
            setup_wheel_roll(2, 0, 0)
                .expect("two setup slots should cross-roll")
                .tracks
                .len(),
            6
        );
    }
}
