use crate::components::primitives::{container, progress};
use crate::engine::Element;
use crate::scene::roles;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct VoiceMeterProps {
    pub level_permille: i32,
}

pub fn voice_meter(props: VoiceMeterProps) -> Element {
    container(roles::VOICE_METER).child(progress(roles::VOICE_METER_LEVEL, props.level_permille))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn live_meter_uses_its_base_theme_role_not_interaction_selection() {
        let meter = voice_meter(VoiceMeterProps {
            level_permille: 618,
        });

        assert_eq!(meter.role, Some(roles::VOICE_METER));
        assert_eq!(meter.props.selected, None);
        assert_eq!(meter.children[0].props.progress, Some(618));
    }
}
