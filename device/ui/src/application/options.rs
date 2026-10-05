use yoyopod_protocol::ui::{ListItemSnapshot, RuntimeSnapshot};

#[derive(Debug, Clone, Copy)]
pub struct TalkContactAction {
    pub kind: &'static str,
}

pub fn listen_items(_snapshot: &RuntimeSnapshot) -> Vec<ListItemSnapshot> {
    vec![
        ListItemSnapshot::new("playlists", "Playlists", "", "icon_playlists"),
        ListItemSnapshot::new("recent_tracks", "Recents", "", "icon_recents"),
        ListItemSnapshot::new("shuffle", "Shuffle all", "", "icon_shuffle"),
    ]
}

pub fn talk_contact_actions(
    snapshot: &RuntimeSnapshot,
    selected_contact: Option<&ListItemSnapshot>,
) -> Vec<TalkContactAction> {
    if snapshot.voice.interrupted_draft_path.is_some()
        && selected_contact
            .or_else(|| snapshot.call.contacts.first())
            .is_none()
    {
        return vec![
            TalkContactAction {
                kind: "review_draft",
            },
            TalkContactAction {
                kind: "discard_draft",
            },
        ];
    }
    if selected_contact
        .or_else(|| snapshot.call.contacts.first())
        .is_some_and(|contact| contact.communication_unavailable)
    {
        return Vec::new();
    }
    let mut actions = Vec::new();
    if selected_contact
        .or_else(|| snapshot.call.contacts.first())
        .is_none_or(|contact| contact.can_call)
    {
        actions.push(TalkContactAction { kind: "call" });
    }
    if let Some(contact) = selected_contact.or_else(|| snapshot.call.contacts.first()) {
        if contact.sip_target().is_some() {
            if contact.can_call
                && contact.can_receive
                && snapshot.voice.interrupted_draft_path.is_none()
            {
                actions.push(TalkContactAction { kind: "record" });
            }
            actions.push(TalkContactAction { kind: "replay" });
        }
    }
    if snapshot.voice.interrupted_draft_path.is_some() {
        actions.push(TalkContactAction {
            kind: "review_draft",
        });
        actions.push(TalkContactAction {
            kind: "discard_draft",
        });
    }
    actions
}

pub fn call_method_disabled_reason<'a>(
    snapshot: &'a RuntimeSnapshot,
    contact: &ListItemSnapshot,
    method: yoyopod_protocol::ui::CallMethod,
) -> Option<&'a str> {
    if !contact.can_call {
        return Some("Not allowed");
    }
    match method {
        yoyopod_protocol::ui::CallMethod::Sip if contact.sip_target().is_none() => {
            Some("Not set up")
        }
        // Direct SIP calls can use a running backend without registrar registration.
        yoyopod_protocol::ui::CallMethod::Sip
            if !snapshot.call.sip_available && !snapshot.call.registered =>
        {
            Some("Offline")
        }
        yoyopod_protocol::ui::CallMethod::Gsm if contact.phone_number.trim().is_empty() => {
            Some("No phone number")
        }
        yoyopod_protocol::ui::CallMethod::Gsm if !snapshot.call.gsm_available => {
            Some(if snapshot.call.gsm_unavailable_reason.is_empty() {
                "Unavailable"
            } else {
                &snapshot.call.gsm_unavailable_reason
            })
        }
        _ => None,
    }
}

pub fn voice_note_action_count(snapshot: &RuntimeSnapshot) -> usize {
    if snapshot.voice.interrupted_draft_path.is_some()
        && matches!(
            voice_note_phase(snapshot).as_str(),
            "review" | "failed" | "unknown"
        )
    {
        return 3;
    }
    match voice_note_phase(snapshot).as_str() {
        "review" => 3,
        "failed" => 2,
        _ => 0,
    }
}

pub(crate) fn voice_note_phase(snapshot: &RuntimeSnapshot) -> String {
    if snapshot.voice.interrupted_draft_path.is_some() {
        return if snapshot.voice.interrupted_draft_phase.is_empty() {
            "review".into()
        } else {
            snapshot.voice.interrupted_draft_phase.clone()
        };
    }
    let phase = snapshot.voice.phase.trim().to_ascii_lowercase();
    if snapshot.voice.capture_in_flight || snapshot.voice.ptt_active || phase == "recording" {
        return "recording".to_string();
    }
    if matches!(phase.as_str(), "review" | "sending" | "sent" | "failed") {
        return phase;
    }
    "ready".to_string()
}

#[cfg(test)]
mod call_permission_tests {
    use super::*;
    #[test]
    fn revoked_contact_cannot_offer_or_start_outbound_calls() {
        let mut contact = ListItemSnapshot::new("sip:dad@example.test", "Dad", "", "");
        contact.can_call = false;
        let mut snapshot = RuntimeSnapshot::default();
        snapshot.call.sip_available = true;
        snapshot.call.gsm_available = true;
        assert_eq!(
            talk_contact_actions(&snapshot, Some(&contact))
                .iter()
                .map(|action| action.kind)
                .collect::<Vec<_>>(),
            vec!["replay"]
        );
        assert!(call_method_disabled_reason(
            &snapshot,
            &contact,
            yoyopod_protocol::ui::CallMethod::Sip
        )
        .is_some());
        assert!(call_method_disabled_reason(
            &snapshot,
            &contact,
            yoyopod_protocol::ui::CallMethod::Gsm
        )
        .is_some());
    }
}
