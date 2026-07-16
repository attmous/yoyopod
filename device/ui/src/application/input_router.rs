use yoyopod_protocol::ui::InputAction;

use super::UiScreen;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct InputRouteState {
    pub active_screen: UiScreen,
    pub voice_note_phase: String,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum AppCommand {
    AdvanceFocus,
    SelectFocused,
    GoHome,
    GoBack,
    PttPress,
    PttRelease,
}

pub fn route(action: InputAction, _state: &InputRouteState) -> AppCommand {
    match action {
        InputAction::Advance => AppCommand::AdvanceFocus,
        InputAction::Select => AppCommand::SelectFocused,
        InputAction::Home => AppCommand::GoHome,
        InputAction::Back => AppCommand::GoBack,
        InputAction::PttPress => AppCommand::PttPress,
        InputAction::PttRelease => AppCommand::PttRelease,
    }
}
