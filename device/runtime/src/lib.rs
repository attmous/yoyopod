pub mod cli;
#[cfg(target_os = "linux")]
mod cold_recovery;
pub mod config;
pub mod event;
pub mod logging;
#[cfg(target_os = "linux")]
pub mod network_owner;
pub mod protocol;
pub mod runtime_loop;
pub mod state;
pub mod status;
pub mod voice;
pub mod worker;

pub fn runtime_name() -> &'static str {
    "yoyopod-runtime"
}
pub mod call_manager;

pub mod call_preferences;
