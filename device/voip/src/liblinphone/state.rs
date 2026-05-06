use super::abi_event::EventQueue;
use super::ffi::{
    LinphoneAccount, LinphoneAccountCbs, LinphoneApi, LinphoneCall, LinphoneChatMessageCbs,
    LinphoneChatRoom, LinphoneChatRoomCbs, LinphoneCore, LinphoneCoreCbs, LinphoneFactory,
    LinphoneRecorder,
};
use std::sync::Arc;

#[derive(Default)]
pub struct ShimState {
    pub initialized: bool,
    pub started: bool,
    pub api: Option<Arc<LinphoneApi>>,
    pub factory: *mut LinphoneFactory,
    pub core: *mut LinphoneCore,
    pub account: *mut LinphoneAccount,
    pub account_cbs: *mut LinphoneAccountCbs,
    pub core_cbs: *mut LinphoneCoreCbs,
    pub message_cbs: *mut LinphoneChatMessageCbs,
    pub chat_room_cbs: *mut LinphoneChatRoomCbs,
    pub current_call: *mut LinphoneCall,
    pub current_recorder: *mut LinphoneRecorder,
    pub recorder_running: bool,
    pub auto_download_incoming_voice_recordings: bool,
    pub voice_note_store_dir: String,
    pub current_recording_path: String,
    pub configured_conference_factory_uri: String,
    pub configured_file_transfer_server_url: String,
    pub configured_lime_server_url: String,
    pub attached_chat_rooms: Vec<*mut LinphoneChatRoom>,
    pub message_counter: u64,
    pub queue: EventQueue,
}

impl ShimState {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn reset_runtime(&mut self) {
        let api = self.api.clone();
        let factory = self.factory;
        let initialized = self.initialized;
        *self = Self {
            initialized,
            api,
            factory,
            ..Self::default()
        };
    }
}

unsafe impl Send for ShimState {}
