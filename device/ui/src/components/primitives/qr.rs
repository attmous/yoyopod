use crate::engine::Element;
use crate::ElementKind;

/// A QR code widget. The payload to encode is supplied via `.text(payload)`;
/// the renderer forwards it to LVGL's `lv_qrcode_update`.
pub fn qr(role: &'static str) -> Element {
    Element::new(ElementKind::Qr, Some(role))
}
