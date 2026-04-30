pub mod cli;
pub mod config;
pub mod event;
pub mod logging;
pub mod protocol;
pub mod runtime_loop;
pub mod state;
pub mod status;
pub mod worker;

pub fn runtime_name() -> &'static str {
    "yoyopod-runtime"
}
