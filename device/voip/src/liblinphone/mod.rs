#[cfg(feature = "native-liblinphone")]
mod abi_event;
#[cfg(feature = "native-liblinphone")]
pub mod backend;
pub mod error;
pub mod events;
#[cfg(feature = "native-liblinphone")]
mod ffi;
#[cfg(feature = "native-liblinphone")]
mod runtime;
#[cfg(feature = "native-liblinphone")]
mod runtime_error;
#[cfg(feature = "native-liblinphone")]
mod state;

#[cfg(feature = "native-liblinphone")]
pub use backend::LiblinphoneBackend;
pub use events::{EventQueue, LiblinphoneEvent};
