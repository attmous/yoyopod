use crate::animation::{
    AnimatableProp, AnimatableValue, ClockSource, Easing, Keyframe, LoopMode, Timeline, TimelineId,
    TimelineRef, Track, TrackIndex,
};
use crate::components::primitives::{container, image, label};
use crate::engine::{AnimSlot, Element, Key};
use crate::scene::{roles, AskPhase, AskSurfaceModel};

pub const THINKING_TIMELINE_ID: TimelineId = TimelineId(40);

const BUTTER: u32 = 0xFFD06A;
const CREAM: u32 = 0xFCE6D2;
const INK: u32 = 0x1B1B1F;

pub fn ask_surface(model: &AskSurfaceModel) -> Element {
    let listening = model.phase == AskPhase::Listening;
    let thinking = model.phase == AskPhase::Thinking;
    let answering = model.phase == AskPhase::Answering;
    let icon_key = match model.phase {
        AskPhase::Idle => "ask_q",
        AskPhase::Answering => "ask_speaker",
        AskPhase::Offline => "ask_cloud_zzz",
        AskPhase::Listening | AskPhase::Thinking => "ask_q",
    };
    let line = match model.phase {
        AskPhase::Idle => "Hold the side button\nand ask me anything",
        AskPhase::Listening => "I'm listening…",
        AskPhase::Thinking => "Hmm, let me think…",
        AskPhase::Answering => "",
        AskPhase::Offline => "I can't think right now —\ntry again soon",
    };

    let mut root = container(roles::ASK_SURFACE)
        .key(Key::Static("ask_surface"))
        .child(
            container(roles::ASK_HERO)
                .key(Key::Static("ask_hero"))
                .accent(
                    if matches!(
                        model.phase,
                        AskPhase::Listening | AskPhase::Thinking | AskPhase::Offline
                    ) {
                        CREAM
                    } else {
                        BUTTER
                    },
                ),
        )
        .child(
            image(roles::ASK_HERO_ICON)
                .key(Key::Static("ask_hero_icon"))
                .icon(icon_key)
                .accent(INK)
                .visible(!listening && !thinking),
        );

    for (index, height) in waveform_heights(model.level_permille)
        .into_iter()
        .enumerate()
    {
        root = root.child(
            container(roles::ASK_WAVE_BAR)
                .key(Key::String(format!("ask_wave:{index}")))
                .absolute(100 + index as i32 * 6, 94 - height / 2, 4, height)
                .visible(listening),
        );
    }
    for index in 0..3 {
        root = root.child(
            container(roles::ASK_THINKING_DOT)
                .key(Key::String(format!("ask_dot:{index}")))
                .absolute(97 + index as i32 * 18, 89, 10, 10)
                .visible(thinking)
                .with_anim(AnimSlot {
                    timeline: TimelineRef(THINKING_TIMELINE_ID),
                    track: TrackIndex(index),
                }),
        );
    }

    root.child(
        label(roles::ASK_LINE)
            .key(Key::Static("ask_line"))
            .text(line),
    )
    .child(
        container(roles::ASK_PROGRESS)
            .key(Key::Static("ask_progress"))
            .visible(answering)
            .child(
                container(roles::ASK_PROGRESS_FILL)
                    .key(Key::Static("ask_progress_fill"))
                    .absolute(0, 0, 180 * model.progress_permille.clamp(0, 1000) / 1000, 8),
            ),
    )
    .child(
        label(roles::ASK_HINT)
            .key(Key::Static("ask_hint"))
            .text(&model.hint),
    )
}

pub fn ask_timelines(phase: AskPhase) -> Vec<Timeline> {
    if phase != AskPhase::Thinking {
        return Vec::new();
    }
    vec![Timeline {
        id: THINKING_TIMELINE_ID,
        clock: ClockSource::GlobalTime,
        tracks: (0..3)
            .map(|index| {
                let delay = index as u32 * 150;
                Track {
                    target: crate::animation::ActorRef::Screen,
                    property: AnimatableProp::Y,
                    keyframes: vec![
                        Keyframe {
                            at_ms: 0,
                            value: AnimatableValue::I32(0),
                        },
                        Keyframe {
                            at_ms: delay,
                            value: AnimatableValue::I32(0),
                        },
                        Keyframe {
                            at_ms: delay + 150,
                            value: AnimatableValue::I32(-8),
                        },
                        Keyframe {
                            at_ms: delay + 300,
                            value: AnimatableValue::I32(0),
                        },
                        Keyframe {
                            at_ms: 750,
                            value: AnimatableValue::I32(0),
                        },
                    ],
                    easing: Easing::EaseInOut,
                }
            })
            .collect(),
        loop_mode: LoopMode::Loop,
        on_complete: None,
        started_ms: 0,
    }]
}

fn waveform_heights(level_permille: i32) -> [i32; 7] {
    const SHAPE: [i32; 7] = [12, 22, 34, 26, 30, 18, 10];
    let scale = 450 + level_permille.clamp(0, 1000) * 550 / 1000;
    SHAPE.map(|height| (height * scale / 1000).max(4))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn listening_surface_has_seven_live_bars() {
        let element = ask_surface(&AskSurfaceModel {
            phase: AskPhase::Listening,
            hint: "let go when you're done".to_string(),
            level_permille: 1_000,
            progress_permille: 0,
        });
        assert_eq!(
            element
                .children
                .iter()
                .filter(|child| child.role == Some(roles::ASK_WAVE_BAR))
                .count(),
            7
        );
        assert!(element
            .children
            .iter()
            .filter(|child| child.role == Some(roles::ASK_WAVE_BAR))
            .all(|child| child.props.visible == Some(true)));
    }

    #[test]
    fn answering_progress_is_clamped_to_track_width() {
        let element = ask_surface(&AskSurfaceModel {
            phase: AskPhase::Answering,
            hint: "double-press to stop".to_string(),
            level_permille: 0,
            progress_permille: 2_000,
        });
        let progress = element
            .children
            .iter()
            .find(|child| child.role == Some(roles::ASK_PROGRESS))
            .unwrap();
        assert_eq!(
            progress.children[0].layout,
            crate::engine::Layout::Absolute {
                x: 0,
                y: 0,
                w: 180,
                h: 8
            }
        );
    }
}
