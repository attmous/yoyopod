use thiserror::Error;

#[derive(Debug, Error)]
pub enum LiblinphoneError {
    #[error("Liblinphone is not available in this build")]
    NotBuilt,
    #[error("Liblinphone call failed: {0}")]
    Call(String),
    #[error("string contains interior NUL: {0}")]
    InvalidCString(#[from] std::ffi::NulError),
}
