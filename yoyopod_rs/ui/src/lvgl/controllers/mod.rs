mod ask;
mod call;
mod hub;
mod list;
mod listen;
mod now_playing;
mod overlay;
mod playlist;
mod power;
mod shared;
mod talk;
mod talk_actions;

use anyhow::Result;

use crate::lvgl::LvglFacade;
use crate::screens::ScreenModel;

pub use ask::AskController;
pub use call::CallController;
pub use hub::HubController;
pub use list::ListController;
pub use listen::ListenController;
pub use now_playing::NowPlayingController;
pub use overlay::OverlayController;
pub use playlist::PlaylistController;
pub use power::PowerController;
pub use talk::TalkController;
pub use talk_actions::TalkActionsController;

pub trait ScreenController {
    fn sync(&mut self, facade: &mut dyn LvglFacade, model: &ScreenModel) -> Result<()>;

    fn teardown(&mut self, facade: &mut dyn LvglFacade) -> Result<()>;
}
