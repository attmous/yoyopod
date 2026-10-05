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
    pub calls: super::call_registry::SessionRegistry<super::call_registry::NativeCallHandle>,
    pub call_counter: u64,
    pub pending_outgoing_id: Option<String>,
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
    /// Bounded caller refs; terminal callbacks queue retirement after native returns.
    pub saved_messages: Vec<*mut super::ffi::LinphoneChatMessage>,
    pub saved_messages_to_retire: Vec<*mut super::ffi::LinphoneChatMessage>,
    pub saved_message_paths: std::collections::BTreeMap<usize, String>,
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
        let call_counter = self.call_counter;
        *self = Self {
            call_counter,
            initialized,
            api,
            factory,
            ..Self::default()
        };
    }
}

// The mutex provides static storage only: all Liblinphone operations and
// callbacks (including retained handle drops) run on the VoIP host thread.
unsafe impl Send for ShimState {}
