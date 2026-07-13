use yoyopod_protocol::ui::{AnimationRequest, InputAction, RuntimeSnapshot, RuntimeSnapshotPatch};

#[derive(Debug, Clone, PartialEq)]
pub(crate) enum AppEvent {
    SetBacklight { brightness: f32 },
    RuntimeSnapshot(RuntimeSnapshot),
    RuntimePatch(RuntimeSnapshotPatch),
    InputAction(InputAction),
    Tick,
    PollInput,
    Health,
    Animate(AnimationRequest),
    Screenshot { path: String, prefer_readback: bool },
    Shutdown,
}

#[derive(Debug, Clone, PartialEq)]
pub(crate) struct DispatchOutcome {
    pub event: AppEvent,
}

pub(crate) fn dispatch_command(command: yoyopod_protocol::ui::UiCommand) -> DispatchOutcome {
    let event = match command {
        yoyopod_protocol::ui::UiCommand::SetBacklight { brightness } => {
            AppEvent::SetBacklight { brightness }
        }
        yoyopod_protocol::ui::UiCommand::RuntimeSnapshot(snapshot) => {
            AppEvent::RuntimeSnapshot(snapshot)
        }
        yoyopod_protocol::ui::UiCommand::RuntimePatch(patch) => AppEvent::RuntimePatch(patch),
        yoyopod_protocol::ui::UiCommand::InputAction(action) => AppEvent::InputAction(action),
        yoyopod_protocol::ui::UiCommand::Tick => AppEvent::Tick,
        yoyopod_protocol::ui::UiCommand::PollInput => AppEvent::PollInput,
        yoyopod_protocol::ui::UiCommand::Health => AppEvent::Health,
        yoyopod_protocol::ui::UiCommand::Animate(request) => AppEvent::Animate(request),
        yoyopod_protocol::ui::UiCommand::Screenshot {
            path,
            prefer_readback,
        } => AppEvent::Screenshot {
            path,
            prefer_readback,
        },
        yoyopod_protocol::ui::UiCommand::Shutdown | yoyopod_protocol::ui::UiCommand::WorkerStop => {
            AppEvent::Shutdown
        }
    };
    DispatchOutcome { event }
}
