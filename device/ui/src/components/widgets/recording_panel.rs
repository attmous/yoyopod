use crate::components::primitives::{container, label};
use crate::components::widgets::{voice_meter, VoiceMeterProps};
use crate::engine::{Element, Key};
use crate::scene::roles;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RecordingPanelProps {
    pub context: String,
    pub duration_ms: i32,
    pub level_permille: i32,
}

pub fn recording_panel(props: &RecordingPanelProps) -> Element {
    container(roles::RECORDING_PANEL)
        .key(Key::Static("recording_panel"))
        .child(
            label(roles::RECORDING_CONTEXT)
                .key(Key::Static("recording_context"))
                .text(&props.context),
        )
        .child(container(roles::RECORDING_TIMER_DOT).key(Key::Static("recording_timer_dot")))
        .child(
            label(roles::RECORDING_TIMER)
                .key(Key::Static("recording_timer"))
                .text(format_duration(props.duration_ms)),
        )
        .child(voice_meter(VoiceMeterProps {
            level_permille: props.level_permille.clamp(0, 1000),
            recording: true,
        }))
        .child(
            label(roles::RECORDING_HINT)
                .key(Key::Static("recording_hint"))
                .text("let go to send"),
        )
}

fn format_duration(duration_ms: i32) -> String {
    let total_seconds = duration_ms.max(0) / 1000;
    format!("{}:{:02}", total_seconds / 60, total_seconds % 60)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn recording_panel_uses_live_metrics_and_exact_copy() {
        let panel = recording_panel(&RecordingPanelProps {
            context: "MAMA".to_string(),
            duration_ms: 7_420,
            level_permille: 618,
        });

        assert_eq!(panel.role, Some(roles::RECORDING_PANEL));
        assert_eq!(panel.children[0].props.text.as_deref(), Some("MAMA"));
        assert_eq!(panel.children[2].props.text.as_deref(), Some("0:07"));
        assert_eq!(panel.children[3].children[0].props.progress, Some(618));
        assert_eq!(
            panel.children[4].props.text.as_deref(),
            Some("let go to send")
        );
    }
}
