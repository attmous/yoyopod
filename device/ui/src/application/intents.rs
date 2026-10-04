use yoyopod_protocol::ui::{
    ContactAction, ListItemAction, ListItemSnapshot, PlaylistTrackAction, VoiceFileAction,
    VoiceNoteSummarySnapshot, VoiceRecipientAction,
};

pub fn list_item_action(item: &ListItemSnapshot) -> ListItemAction {
    ListItemAction {
        id: item.id.clone(),
        title: item.title.clone(),
        path: String::new(),
        track_uri: String::new(),
    }
}

pub fn playlist_track_action(
    playlist: &ListItemSnapshot,
    track: &ListItemSnapshot,
    track_index: usize,
) -> PlaylistTrackAction {
    PlaylistTrackAction {
        playlist_path: playlist.id.clone(),
        track_uri: track.id.clone(),
        track_index,
    }
}

pub fn contact_action(item: &ListItemSnapshot) -> ContactAction {
    ContactAction {
        id: item.id.clone(),
        name: item.title.clone(),
        sip_address: String::new(),
        uri: String::new(),
        method: yoyopod_protocol::ui::CallMethod::Sip,
    }
}

pub fn voice_recipient_action(contact: &ListItemSnapshot) -> Option<VoiceRecipientAction> {
    let target = contact.sip_target()?;
    Some(VoiceRecipientAction {
        id: if contact.contact_id.is_empty() {
            contact.id.clone()
        } else {
            contact.contact_id.clone()
        },
        recipient_address: target.to_string(),
        recipient_name: contact.title.clone(),
        file_path: String::new(),
    })
}

pub fn voice_file_action(
    contact: &ListItemSnapshot,
    note: &VoiceNoteSummarySnapshot,
) -> Option<VoiceFileAction> {
    if note.local_file_path.trim().is_empty() {
        return None;
    }
    Some(VoiceFileAction {
        id: contact.id.clone(),
        recipient_name: contact.title.clone(),
        file_path: note.local_file_path.clone(),
        uri: String::new(),
        sip_address: String::new(),
        message_id: note.message_id.clone(),
        duration_ms: note.duration_ms.max(0),
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn voice_recipient_retains_stable_cloud_identity_and_the_captured_address() {
        let mut contact = ListItemSnapshot::new("sip:mama@example.test", "Mama", "", "");
        contact.contact_id = "approved-mama".into();
        contact.sip_address = "sip:mama@example.test".into();
        let action = voice_recipient_action(&contact).unwrap();
        assert_eq!(action.id, "approved-mama");
        assert_eq!(action.recipient_address, "sip:mama@example.test");
    }
}
