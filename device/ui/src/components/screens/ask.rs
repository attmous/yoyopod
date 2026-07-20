use yoyopod_protocol::ui::{RuntimeSnapshot, UiScreen};

use crate::components::widgets::ask_surface::ask_timelines;
use crate::engine::Key;
use crate::scene::{
    AskPhase, AskSurfaceModel, Backdrop, Deck, DeckItem, DeckItemAnim, DeckKind, FocusPolicy,
    ItemRender, RegionId, Scene, SceneDefaults, SceneId,
};

pub const ASK_STAGE_BUTTER: u32 = 0xFFF0CC;

pub struct AskProps {
    pub defaults: SceneDefaults,
    pub model: AskSurfaceModel,
}

pub fn props_from(snapshot: &RuntimeSnapshot, _focus: usize, defaults: SceneDefaults) -> AskProps {
    let phase = ask_phase(snapshot);
    let hint = match phase {
        AskPhase::Idle => {
            if snapshot.voice.headline.eq_ignore_ascii_case("ask")
                && snapshot.voice.body.to_ascii_lowercase().contains("another")
            {
                "Ask me another!"
            } else {
                "Try: why is the sky blue?"
            }
        }
        AskPhase::Listening => "let go when you're done",
        AskPhase::Thinking => "",
        AskPhase::Answering => "double-press to stop",
        AskPhase::Offline => "",
    };
    AskProps {
        defaults,
        model: AskSurfaceModel {
            phase,
            hint: hint.to_string(),
            level_permille: snapshot.voice.capture_level_permille,
            progress_permille: playback_progress(snapshot),
        },
    }
}

pub fn scene(props: &AskProps) -> Scene {
    Scene {
        id: SceneId::new(UiScreen::Ask),
        backdrop: Backdrop::Solid(ASK_STAGE_BUTTER),
        stage: props.defaults.stage,
        context: None,
        decks: vec![Deck {
            kind: DeckKind::Page,
            region: RegionId::Auto,
            items: vec![DeckItem {
                key: Key::Static("ask"),
                render: ItemRender::AskSurface(props.model.clone()),
            }],
            focus_index: 0,
            focus_policy: FocusPolicy::None,
            item_anim: DeckItemAnim::None,
            swap_anim: None,
            recycle_window: None,
        }],
        cursor: None,
        fx: Default::default(),
        modal: None,
        timelines: ask_timelines(props.model.phase),
    }
}

fn ask_phase(snapshot: &RuntimeSnapshot) -> AskPhase {
    let phase = snapshot.voice.phase.trim().to_ascii_lowercase();
    if !snapshot.network.connected && !matches!(phase.as_str(), "listening" | "recording") {
        return AskPhase::Offline;
    }
    if snapshot.voice.ptt_active
        || snapshot.voice.capture_in_flight
        || matches!(phase.as_str(), "listening" | "recording")
    {
        AskPhase::Listening
    } else if phase == "thinking" {
        AskPhase::Thinking
    } else if snapshot.voice.playback_active || matches!(phase.as_str(), "reply" | "answering") {
        AskPhase::Answering
    } else {
        AskPhase::Idle
    }
}

fn playback_progress(snapshot: &RuntimeSnapshot) -> i32 {
    let duration = snapshot.voice.playback_duration_ms;
    if duration > 0 {
        (snapshot.voice.playback_elapsed_ms.max(0) * 1_000 / duration).clamp(0, 1_000)
    } else if snapshot.voice.playback_active {
        120
    } else {
        0
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn ask_uses_full_bleed_butter_and_no_focus_cursor() {
        let mut snapshot = RuntimeSnapshot::default();
        snapshot.network.connected = true;
        let props = props_from(&snapshot, 0, crate::scene::defaults_for(UiScreen::Ask));
        let scene = scene(&props);
        assert_eq!(scene.backdrop, Backdrop::Solid(ASK_STAGE_BUTTER));
        assert_eq!(scene.decks[0].focus_policy, FocusPolicy::None);
        assert!(scene.cursor.is_none());
    }

    #[test]
    fn ask_state_tracks_runtime_voice_phase() {
        let mut snapshot = RuntimeSnapshot::default();
        snapshot.network.connected = true;
        snapshot.voice.phase = "thinking".to_string();
        assert_eq!(
            props_from(&snapshot, 0, crate::scene::defaults_for(UiScreen::Ask))
                .model
                .phase,
            AskPhase::Thinking
        );
        snapshot.voice.playback_active = true;
        snapshot.voice.phase = "reply".to_string();
        assert_eq!(
            props_from(&snapshot, 0, crate::scene::defaults_for(UiScreen::Ask))
                .model
                .phase,
            AskPhase::Answering
        );
    }
}
