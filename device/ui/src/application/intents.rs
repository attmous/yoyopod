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
    }
}

pub fn voice_recipient_action(contact: &ListItemSnapshot) -> Option<VoiceRecipientAction> {
    if contact.id.trim().is_empty() {
        return None;
    }
    Some(VoiceRecipientAction {
        id: contact.id.clone(),
        recipient_address: contact.id.clone(),
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
