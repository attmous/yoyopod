use super::{ContactIdentity, DeviceMode};
pub(super) fn admits(mode: &DeviceMode, contact: &ContactIdentity) -> bool {
    *mode != DeviceMode::DoNotDisturb || contact.priority
}
pub(super) fn audible(mode: &DeviceMode) -> bool {
    *mode == DeviceMode::Normal
}
