use yoyopod_protocol::ui::{CallMethod, ListItemSnapshot, RuntimeSnapshot, UiScreen};

use crate::application::options::call_method_disabled_reason;
use crate::engine::Key;
use crate::scene::{
    DeckItem, ItemRender, Scene, SceneDefaults, SceneId, WheelItemModel, WheelItemVariant,
};

pub fn scene(
    snapshot: &RuntimeSnapshot,
    contact: Option<&ListItemSnapshot>,
    focus: usize,
    defaults: SceneDefaults,
) -> Scene {
    let contact = contact.or_else(|| snapshot.call.contacts.first());
    let mut scene = super::talk_contact::scene(&super::talk_contact::TalkContactProps {
        defaults,
        context: contact
            .map(|contact| contact.title.to_uppercase())
            .unwrap_or_default(),
        actions: [
            (CallMethod::Sip, "sip", "SIP", "wifi"),
            (CallMethod::Gsm, "gsm", "GSM", "call"),
        ]
        .into_iter()
        .map(|(method, key, title, icon)| DeckItem {
            key: Key::Static(key),
            render: ItemRender::Wheel(WheelItemModel {
                title: title.to_string(),
                subtitle: contact
                    .and_then(|contact| call_method_disabled_reason(snapshot, contact, method))
                    .unwrap_or(match method {
                        CallMethod::Sip => "Wi-Fi call",
                        CallMethod::Gsm => "Mobile call",
                    })
                    .to_string(),
                variant: WheelItemVariant::Action {
                    icon_key: icon.to_string(),
                    badge: None,
                },
            }),
        })
        .collect(),
        focus,
        recording: false,
        recording_duration_ms: 0,
        capture_level_permille: 0,
    });
    scene.id = SceneId::new(UiScreen::CallMethod);
    scene
}
