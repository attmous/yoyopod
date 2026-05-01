mod ask;
mod call;
mod hub;
mod list;
mod now_playing;
mod overlay;
mod power;
mod shared;

use anyhow::Result;

use crate::lvgl::LvglFacade;
use crate::screens::ScreenModel;

pub use ask::AskController;
pub use call::CallController;
pub use hub::HubController;
pub use list::ListController;
pub use now_playing::NowPlayingController;
pub use overlay::OverlayController;
pub use power::PowerController;

pub trait ScreenController {
    fn sync(&mut self, facade: &mut dyn LvglFacade, model: &ScreenModel) -> Result<()>;

    fn teardown(&mut self, facade: &mut dyn LvglFacade) -> Result<()>;
}
